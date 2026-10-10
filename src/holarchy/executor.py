# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import CancelledError, Semaphore, Task, create_task, gather, sleep, wait_for
from contextlib import suppress
from dataclasses import asdict
from inspect import Parameter, signature
from logging import getLogger
from secrets import token_urlsafe
from time import monotonic, time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, get_type_hints
from uuid import uuid4

from msgspec import convert, to_builtins

try:
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )
except ImportError:
    TraceContextTextMapPropagator = None

from rxon.constants import (
    JOB_STATUS_ERROR,
    JOB_STATUS_FAILED,
    JOB_STATUS_FINISHED,
    JOB_STATUS_QUARANTINED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_WAITING_FOR_PARALLEL,
    JOB_STATUS_WAITING_FOR_WORKER,
)
from rxon.schema import validate_data

from holarchy import telemetry

from .app_keys import S3_SERVICE_KEY
from .context import ActionFactory
from .data_types import ClientConfig, JobContext, ensure_storage_zones
from .di import (
    cast_header_value,
    extract_header_marker,
    find_header_in_dict,
    is_header_annotation,
)
from .diagnostic import generate_evidence_card
from .fsm import Next, State
from .history.base import HistoryStorageBase
from .metrics import LABEL_BLUEPRINT, Metrics
from .skill import SkillInvocation
from .testing.replay import record_execution_receipt

if TYPE_CHECKING:
    from .engine import OrchestratorEngine

logger = getLogger(__name__)

tracer = telemetry.trace.get_tracer(__name__)

if TraceContextTextMapPropagator is not None:
    propagator = TraceContextTextMapPropagator()
else:

    class NoOpTraceContextTextMapPropagator:
        @staticmethod
        def extract(*args, **kwargs):
            return None

    propagator = NoOpTraceContextTextMapPropagator()

TERMINAL_STATES = {JOB_STATUS_FINISHED, JOB_STATUS_FAILED, JOB_STATUS_ERROR, JOB_STATUS_QUARANTINED}


class JobExecutor:
    def __init__(
        self,
        engine: "OrchestratorEngine",
        history_storage: "HistoryStorageBase",
        metrics: Metrics,
    ):
        self.engine = engine
        self.storage = engine.storage
        self.history_storage = history_storage
        self.metrics = metrics
        self.dispatcher = engine.dispatcher
        self._running = False
        self._processing_messages: set[str] = set()
        self._active_tasks: set[Task[Any]] = set()

    async def _process_job(self, job_id: str, message_id: str) -> None:
        """The core logic for processing a single job dequeued from storage."""
        if message_id in self._processing_messages:
            return

        self._processing_messages.add(message_id)
        try:
            start_time = monotonic()
            job_state = await self.storage.get_job_state(job_id)
            if not job_state:
                logger.error(f"Job {job_id} not found in storage, cannot process.")
                return

            if job_state.get("status") in TERMINAL_STATES:
                logger.warning(f"Job {job_id} is already in a terminal state '{job_state['status']}', skipping.")
                return

            if "retry_count" not in job_state:
                job_state["retry_count"] = 0

            # Detect infinite loops in blueprints
            step = job_state.get("step", 0) + 1

            max_transitions = job_state.get("max_transitions")
            if max_transitions is None or not isinstance(max_transitions, int):
                max_transitions = getattr(self.engine.config, "MAX_TRANSITIONS_PER_JOB", 100)
                if not isinstance(max_transitions, int):
                    max_transitions = 100

            if step > max_transitions:
                duration_ms = int((monotonic() - start_time) * 1000)
                error_msg = (
                    f"Blueprint execution exceeded maximum transitions ({max_transitions}). "
                    "Suspected infinite loop detected."
                )
                logger.critical(f"Job {job_id} failed: {error_msg}")
                job_state["status"] = JOB_STATUS_FAILED
                job_state["error_message"] = error_msg
                await self.storage.save_job_state(job_id, job_state)

                await self.history_storage.log_job_event(
                    {
                        "job_id": job_id,
                        "client_token": job_state.get("client_config", {}).get("token"),
                        "state": job_state["current_state"],
                        "event_type": "job_failed",
                        "duration_ms": duration_ms,
                        "timestamp": time(),
                        "context_snapshot": job_state,
                    }
                )
                return

            job_state["step"] = step

            await self.history_storage.log_job_event(
                {
                    "job_id": job_id,
                    "client_token": job_state.get("client_config", {}).get("token"),
                    "state": job_state["current_state"],
                    "event_type": "state_started",
                    "origin_task_id": job_state.get("current_task_id"),
                    "attempt_number": job_state.get("retry_count", 0) + 1,
                    "timestamp": time(),
                    "context_snapshot": job_state,
                },
            )

            parent_context = propagator.extract(
                carrier=job_state.get("tracing_context", {}) or {},
            )

            with tracer.start_as_current_span(
                f"JobExecutor:{job_state['blueprint_name']}:{job_state['current_state']}",
                context=parent_context,
            ) as span:
                span.set_attribute("job.id", job_id)
                span.set_attribute("job.blueprint", job_state["blueprint_name"])
                span.set_attribute("job.current_state", job_state["current_state"])
                span.set_attribute("job.retry_count", job_state.get("retry_count", 0))
                span.set_attribute("job.client_token", job_state.get("client_config", {}).get("token", "unknown"))
                span.set_attribute("job.step", job_state.get("step", 0))
                span.set_attribute("job.depth", job_state.get("depth", 0))
                if parent_hash := job_state.get("parent_hash"):
                    span.set_attribute("job.parent_hash", parent_hash)
                if sig := job_state.get("sig"):
                    span.set_attribute("job.sig", sig)
                if costs := job_state.get("costs"):
                    span.set_attribute("job.costs", str(costs))
                if quarantine_reason := job_state.get("quarantine_reason"):
                    span.set_attribute("job.quarantine_reason", str(quarantine_reason))

                tracing_context: dict[str, str] = dict(job_state.get("tracing_context") or {})
                telemetry.inject(tracing_context)
                job_state["tracing_context"] = tracing_context

                blueprint = self.engine.blueprints.get(job_state["blueprint_name"])
                if not blueprint:
                    duration_ms = int((monotonic() - start_time) * 1000)
                    await self._handle_failure(
                        job_state,
                        RuntimeError(
                            f"Blueprint '{job_state['blueprint_name']}' not found",
                        ),
                        duration_ms,
                    )
                    return

                action_factory = ActionFactory(
                    job_id,
                    default_dispatch_timeout=job_state.get("dispatch_timeout"),
                    default_result_timeout=job_state.get("result_timeout"),
                    policy=job_state.get("policy"),
                    blueprint=blueprint,
                )
                client_config_dict = job_state.get("client_config", {})
                client_config = ClientConfig(
                    token=client_config_dict.get("token", ""),
                    plan=client_config_dict.get("plan", "unknown"),
                    params=client_config_dict.get("params", {}),
                )

                s3_service = self.engine.app.get(S3_SERVICE_KEY)
                task_files = s3_service.get_task_files(job_id) if s3_service else None
                aggregation_results = job_state.get("aggregation_results") or {}

                input_data = job_state.get("input") or {}
                steps_data = job_state.get("steps") or {}
                history_data = job_state.get("history") or []
                output_data = job_state.get("output") if "output" in job_state else job_state.get("result")
                params_data = (job_state.get("params") if "params" in job_state else client_config.params) or {}
                meta_data = (job_state.get("meta") if "meta" in job_state else job_state.get("metadata", {})) or {}

                context = JobContext(
                    job_id=job_id,
                    current_state=job_state.get("current_state", "start"),
                    input=input_data,
                    steps=steps_data,
                    output=output_data,
                    history=history_data,
                    params=params_data,
                    client=client_config,
                    actions=action_factory,
                    data_stores=SimpleNamespace(**blueprint.data_stores) if blueprint.data_stores else None,
                    tracing_context=job_state.get("tracing_context"),
                    aggregation_results=aggregation_results,
                    webhook_url=job_state.get("webhook_url"),
                    task_files=task_files,
                    policy=job_state.get("policy"),
                    meta=meta_data,
                )

                try:
                    # Aggregator handlers take priority for states that are targets of parallel execution.
                    is_aggregator_state = job_state.get("aggregation_target") == job_state.get("current_state")
                    if is_aggregator_state and job_state.get("current_state") in blueprint.aggregator_handlers:
                        handler = blueprint.aggregator_handlers[job_state["current_state"]]
                    else:
                        handler = blueprint.find_handler(context.current_state, context)

                    param_names = blueprint.get_handler_params(handler)
                    params_to_inject: dict[str, Any] = {}

                    try:
                        hints = get_type_hints(handler, include_extras=True)
                    except Exception:
                        hints = {}

                    sig = blueprint.get_handler_signature(handler)
                    if sig is None:
                        with suppress(Exception):
                            sig = signature(handler)

                    def _coerce_type(tp: Any, raw_val: Any) -> Any:
                        if not isinstance(tp, type):
                            return raw_val
                        if isinstance(raw_val, tp):
                            return raw_val
                        if not isinstance(raw_val, dict):
                            return raw_val
                        if hasattr(tp, "model_validate"):
                            with suppress(Exception):
                                return tp.model_validate(raw_val)
                        elif hasattr(tp, "parse_obj"):
                            with suppress(Exception):
                                return tp.parse_obj(raw_val)
                        elif hasattr(tp, "__struct_fields__"):
                            with suppress(Exception):
                                return convert(raw_val, tp)
                        elif hasattr(tp, "__dataclass_fields__"):
                            with suppress(Exception):
                                matched = {k: v for k, v in raw_val.items() if k in tp.__dataclass_fields__}
                                return tp(**matched)
                        return raw_val

                    def _is_domain_model(tp: Any) -> bool:
                        return isinstance(tp, type) and (
                            hasattr(tp, "model_validate")
                            or hasattr(tp, "parse_obj")
                            or hasattr(tp, "__struct_fields__")
                            or hasattr(tp, "__dataclass_fields__")
                        )

                    available_headers: dict[str, Any] = {}
                    if isinstance(context.headers, dict):
                        available_headers.update(context.headers)
                    if isinstance(job_state.get("meta"), dict) and isinstance(job_state["meta"].get("headers"), dict):
                        available_headers.update(job_state["meta"]["headers"])
                    if isinstance(job_state.get("tracing_context"), dict):
                        available_headers.update(job_state["tracing_context"])

                    context_as_dict = context._asdict()
                    for param_name in param_names:
                        param_type = hints.get(param_name)
                        param_sig = sig.parameters.get(param_name) if sig else None
                        param_default = (
                            param_sig.default if param_sig and param_sig.default is not Parameter.empty else ...
                        )

                        if param_name == "actions":
                            params_to_inject["actions"] = action_factory
                        elif param_name in ("context", "ctx") or (
                            isinstance(param_type, type) and issubclass(param_type, JobContext)
                        ):
                            params_to_inject[param_name] = context
                        elif param_name == "task_files":
                            params_to_inject[param_name] = task_files
                        elif is_header_annotation(param_type) or (
                            param_sig and is_header_annotation(param_sig.default)
                        ):
                            marker_info = extract_header_marker(param_type, default_name=param_name)
                            if not marker_info and param_sig:
                                marker_info = extract_header_marker(param_sig.default, default_name=param_name)

                            if marker_info:
                                header_name, target_type, marker_default = marker_info
                                if marker_default is ... and param_default is not ...:
                                    effective_default = param_default
                                else:
                                    effective_default = marker_default

                                raw_header_val = find_header_in_dict(available_headers, header_name)
                                params_to_inject[param_name] = cast_header_value(
                                    raw_header_val, target_type, default=effective_default
                                )
                            elif param_default is not ...:
                                params_to_inject[param_name] = param_default
                        elif param_name in context_as_dict:
                            params_to_inject[param_name] = _coerce_type(param_type, context_as_dict[param_name])
                        elif context.steps and isinstance(context.steps, dict) and param_name in context.steps:
                            params_to_inject[param_name] = _coerce_type(param_type, context.steps[param_name])
                        elif context.input and isinstance(context.input, dict) and param_name in context.input:
                            params_to_inject[param_name] = _coerce_type(param_type, context.input[param_name])
                        else:
                            injected = False
                            if context.steps and isinstance(context.steps, dict):
                                for prev_res in reversed(list(context.steps.values())):
                                    if isinstance(prev_res, dict) and param_name in prev_res:
                                        params_to_inject[param_name] = _coerce_type(param_type, prev_res[param_name])
                                        injected = True
                                        break
                            if injected:
                                continue

                            if (
                                isinstance(param_type, type)
                                and _is_domain_model(param_type)
                                and context.steps
                                and isinstance(context.steps, dict)
                            ):
                                for prev_res in reversed(list(context.steps.values())):
                                    if isinstance(prev_res, param_type):
                                        params_to_inject[param_name] = prev_res
                                        injected = True
                                        break
                                    if isinstance(prev_res, dict):
                                        coerced = _coerce_type(param_type, prev_res)
                                        if coerced is not prev_res and isinstance(coerced, param_type):
                                            params_to_inject[param_name] = coerced
                                            injected = True
                                            break
                            if injected:
                                continue

                            if isinstance(param_type, type):
                                source = context.input
                                if isinstance(source, dict):
                                    coerced = _coerce_type(param_type, source)
                                    if coerced is not source:
                                        params_to_inject[param_name] = coerced
                                        injected = True
                            if injected:
                                continue

                            if param_default is not ...:
                                params_to_inject[param_name] = param_default

                    if hasattr(self.engine, "middleware_chain") and not hasattr(
                        self.engine.middleware_chain, "_mock_name"
                    ):
                        params_to_inject = await self.engine.middleware_chain.run_process_handler_request(
                            context, params_to_inject
                        )

                    decider_info = None
                    deciders_map = getattr(blueprint, "_deciders", None)
                    if isinstance(deciders_map, dict):
                        decider_info = deciders_map.get(context.current_state)
                    if decider_info is None:
                        meta = getattr(handler, "_decide_meta", None)
                        if isinstance(meta, dict):
                            decider_info = meta

                    if isinstance(decider_info, dict) and "candidates" in decider_info and "fallback" in decider_info:
                        candidates = decider_info["candidates"]
                        fallback = decider_info["fallback"]
                        timeout_sec = decider_info.get("timeout_seconds", 3.0)
                        start_decide = monotonic()
                        fallback_triggered = False
                        decide_error: str | None = None
                        try:
                            raw_result = await wait_for(handler(**params_to_inject), timeout=timeout_sec)
                            chosen_state = str(raw_result)
                            if chosen_state in candidates:
                                chosen = chosen_state
                            else:
                                chosen = fallback
                                fallback_triggered = True
                                decide_error = f"Decider returned non-candidate '{chosen_state}'"
                        except Exception as e:
                            chosen = fallback
                            fallback_triggered = True
                            decide_error = str(e)

                        duration_decide_ms = int((monotonic() - start_decide) * 1000)
                        receipt = {
                            "correlation_id": str(job_state.get("meta", {}).get("correlation_id") or job_id),
                            "step": context.current_state,
                            "candidates": candidates,
                            "chosen": chosen,
                            "fallback_triggered": fallback_triggered,
                            "duration_ms": duration_decide_ms,
                            "error_message": decide_error,
                        }
                        if "receipts" not in job_state or not isinstance(job_state["receipts"], list):
                            job_state["receipts"] = []
                        job_state["receipts"].append(receipt)

                        with suppress(Exception):
                            record_execution_receipt(receipt)

                        action_factory.go_to(chosen)
                        result = {"chosen": chosen, "fallback_triggered": fallback_triggered}
                    else:
                        result = await handler(**params_to_inject)

                    if action_factory.last_receipt:
                        if "receipts" not in job_state or not isinstance(job_state["receipts"], list):
                            job_state["receipts"] = []
                        job_state["receipts"].append(action_factory.last_receipt)
                        with suppress(Exception):
                            record_execution_receipt(action_factory.last_receipt)

                    if hasattr(self.engine, "middleware_chain") and not hasattr(
                        self.engine.middleware_chain, "_mock_name"
                    ):
                        result = await self.engine.middleware_chain.run_process_handler_response(context, result)

                    if isinstance(result, Next):
                        action_factory.go_to(str(result.state))
                        result = result.data

                    elif isinstance(result, State):
                        action_factory.go_to(str(result))
                        result = None

                    elif isinstance(result, SkillInvocation):
                        transitions: dict[str, str] = {}
                        if result.next_state:
                            transitions["success"] = str(result.next_state)
                        if result.on_failure:
                            transitions["failed"] = str(result.on_failure)
                        action_factory.dispatch_task(
                            task_type=result.skill_name,
                            params=result.params,
                            transitions=transitions,
                            timeout_seconds=int(result.timeout) if result.timeout is not None else None,
                        )
                        result = None

                    if action_factory.step_result is not None and result is None:
                        result = action_factory.step_result

                    on_succ = getattr(handler, "_on_success", None)
                    if (
                        action_factory.next_state is None
                        and not action_factory.task_to_dispatch
                        and not action_factory.parallel_tasks_to_dispatch
                        and not action_factory.sub_blueprint_to_run
                        and on_succ
                    ):
                        action_factory.go_to(str(on_succ))

                    def _serialize_val(val: Any) -> Any:
                        if val is None:
                            return None
                        if hasattr(val, "model_dump"):
                            return val.model_dump()
                        if hasattr(val, "dict") and callable(val.dict):
                            return val.dict()
                        if hasattr(val, "__struct_fields__"):
                            return to_builtins(val)
                        if hasattr(val, "__dataclass_fields__"):
                            return asdict(val)
                        return val

                    serializable_result = _serialize_val(result)

                    current_st = str(job_state["current_state"])
                    if "steps" not in job_state or job_state["steps"] is None:
                        job_state["steps"] = {}
                    if serializable_result is not None:
                        job_state["steps"][current_st] = serializable_result
                        if isinstance(context.steps, dict):
                            context.steps[current_st] = serializable_result

                    if current_st in blueprint.end_states:
                        if serializable_result is not None:
                            job_state["result"] = serializable_result
                            job_state["output"] = serializable_result
                        elif job_state.get("output") is not None:
                            job_state["result"] = job_state["output"]
                        elif job_state.get("result") is not None:
                            job_state["output"] = job_state["result"]

                    if action_factory.context_updates:
                        if "input" not in job_state or job_state["input"] is None:
                            job_state["input"] = {}
                        if isinstance(job_state["input"], dict):
                            job_state["input"].update(action_factory.context_updates)

                    if "steps" in job_state:
                        job_state["steps"] = context.steps if context.steps is not None else job_state["steps"]
                    job_state["aggregation_results"] = context.aggregation_results

                    if action_factory.pending_events:
                        for event_type, payload, event_security, event_metadata in action_factory.pending_events:
                            final_security = event_security or job_state.get("security")
                            final_metadata = event_metadata or job_state.get("metadata")

                            event_data: dict[str, Any] = {
                                "event_id": str(uuid4()),
                                "worker_id": "ghost",
                                "origin_worker_id": "ghost",
                                "event_type": event_type,
                                "payload": payload,
                                "bubbling_chain": [],
                                "target_job_id": job_id,
                                "trace_context": tracing_context,
                                "timestamp": time(),
                                "security": final_security,
                                "metadata": final_metadata,
                            }
                            if self.engine.worker_service:
                                await self.engine.worker_service.process_worker_event("ghost", event_data)
                            else:
                                logger.error("WorkerService not initialized. Event dropped.")

                    duration_ms = int((monotonic() - start_time) * 1000)

                    if action_factory.next_state:
                        await self._handle_transition(
                            job_state,
                            action_factory.next_state,
                            duration_ms,
                        )
                    elif action_factory.task_to_dispatch:
                        await self._handle_dispatch(
                            job_state,
                            action_factory.task_to_dispatch,
                            duration_ms,
                        )
                    elif action_factory.parallel_tasks_to_dispatch:
                        await self._handle_parallel_dispatch(
                            job_state,
                            action_factory.parallel_tasks_to_dispatch,
                            duration_ms,
                        )
                    elif action_factory.sub_blueprint_to_run:
                        await self._handle_run_blueprint(
                            job_state,
                            action_factory.sub_blueprint_to_run,
                            duration_ms,
                        )
                    elif job_state["current_state"] in blueprint.end_states:
                        curr_state = str(job_state["current_state"])
                        logger.info(f"DEBUG: Job {job_id} end state detected: {curr_state}")
                        if curr_state in blueprint.terminal_statuses:
                            status = blueprint.terminal_statuses[curr_state]
                        elif curr_state == "failed" or "fail" in curr_state.lower():
                            status = JOB_STATUS_FAILED
                        else:
                            status = JOB_STATUS_FINISHED
                        await self._handle_terminal_reached(job_state, status, duration_ms)

                except Exception as e:
                    span.record_exception(e)
                    span.set_status(telemetry.trace.Status(telemetry.trace.StatusCode.ERROR, str(e)))
                    duration_ms = int((monotonic() - start_time) * 1000)
                    # For errors, we also want to ensure the result (even if partial) is captured
                    if hasattr(self, "_handle_failure"):
                        await self._handle_failure(job_state, e, duration_ms)
                    else:
                        job_state["status"] = JOB_STATUS_FAILED
                        job_state["error_message"] = str(e)
                        await self._handle_terminal_reached(job_state, JOB_STATUS_FAILED, duration_ms)
        finally:
            await self.storage.ack_job(message_id)
            if message_id in self._processing_messages:
                self._processing_messages.remove(message_id)

    async def _handle_terminal_reached(
        self,
        job_state: dict[str, Any],
        status: str,
        duration_ms: int,
    ) -> None:
        job_id = job_state["id"]
        current_state = job_state["current_state"]
        logger.info(f"Job {job_id} reached terminal state '{current_state}' with status '{status}'")

        # Automatically extract the final result into a top-level 'result' and 'output' field
        # ONLY when the job reaches a terminal state.
        steps = job_state.get("steps", {})
        final_res = None
        if job_state.get("output") is not None:
            final_res = job_state["output"]
        elif job_state.get("result") is not None:
            final_res = job_state["result"]
        elif current_state in steps:
            final_res = steps[current_state]
        elif steps:
            latest_key = list(steps.keys())[-1]
            final_res = steps[latest_key]

        if final_res is not None:
            job_state["result"] = final_res
            job_state["output"] = final_res

        if "history" in job_state and isinstance(job_state["history"], list):
            job_state["history"].append(
                {
                    "state": current_state,
                    "status": status,
                    "duration_ms": duration_ms,
                    "timestamp": time(),
                }
            )

        await self.history_storage.log_job_event(
            {
                "job_id": job_id,
                "client_token": job_state.get("client_config", {}).get("token"),
                "state": current_state,
                "event_type": "job_completed",
                "duration_ms": duration_ms,
                "timestamp": time(),
                "context_snapshot": job_state,
            },
        )

        self.metrics.job_duration_seconds.record(
            duration_ms / 1000.0,
            {LABEL_BLUEPRINT: job_state.get("blueprint_name", "unknown")},
        )

        job_state["status"] = status
        await self._check_and_resume_parent(job_state)

        if status == JOB_STATUS_FINISHED:
            contract = self.engine.blueprint_contracts.get(job_state["blueprint_name"], {})
            output_schema = contract.get("output_schema")
            if output_schema:
                output_val = job_state.get("output")
                if output_val is not None:
                    if hasattr(output_val, "model_dump"):
                        output_val = output_val.model_dump()
                    elif hasattr(output_val, "dict") and callable(output_val.dict):
                        output_val = output_val.dict()
                    elif hasattr(output_val, "__struct_fields__"):
                        output_val = to_builtins(output_val)
                    elif hasattr(output_val, "__dataclass_fields__"):
                        output_val = asdict(output_val)

                is_valid, error_msg = validate_data(output_val, output_schema)

                if not is_valid:
                    status = JOB_STATUS_FAILED
                    job_state["status"] = JOB_STATUS_FAILED
                    job_state["error_message"] = (
                        f"Blueprint contract violation: final output does not match output_schema. {error_msg}"
                    )
                    logger.error(f"Job {job_id} violated its own contract: {job_state['error_message']}")

        if status in (JOB_STATUS_FAILED, JOB_STATUS_QUARANTINED) and "evidence" not in job_state:
            with suppress(Exception):
                evidence = generate_evidence_card(
                    job_state, job_state.get("error_message"), current_state=current_state
                )
                job_state["evidence"] = evidence
                job_state["evidence_card"] = evidence["markdown"]

        await self.storage.save_job_state(job_id, job_state)

        if self.engine.on_job_finished:
            await gather(*[cb(job_id, status, job_state) for cb in self.engine.on_job_finished], return_exceptions=True)

        s3_service = self.engine.app.get(S3_SERVICE_KEY)
        if s3_service and self.engine.config.S3_AUTO_CLEANUP:
            task_files = s3_service.get_task_files(job_id)
            if task_files:
                create_task(task_files.cleanup())

        await self._check_and_resume_parent(job_state)
        event_type = "job_finished" if status == JOB_STATUS_FINISHED else "job_failed"
        await self.engine.send_job_webhook(job_state, event_type)

    async def _handle_transition(
        self,
        job_state: dict[str, Any],
        next_state: str,
        duration_ms: int,
    ) -> None:
        job_id = job_state["id"]
        previous_state = job_state["current_state"]
        logger.info(f"Job {job_id} transitioning from {previous_state} to {next_state}")

        await self.history_storage.log_job_event(
            {
                "job_id": job_id,
                "client_token": job_state.get("client_config", {}).get("token"),
                "state": previous_state,
                "event_type": "state_finished",
                "origin_task_id": job_state.get("current_task_id"),
                "duration_ms": duration_ms,
                "previous_state": previous_state,
                "next_state": next_state,
                "timestamp": time(),
                "context_snapshot": job_state,
            },
        )

        if "history" in job_state and isinstance(job_state["history"], list):
            job_state["history"].append(
                {
                    "state": previous_state,
                    "from_state": previous_state,
                    "to_state": next_state,
                    "status": "success",
                    "duration_ms": duration_ms,
                    "timestamp": time(),
                }
            )

        job_state["retry_count"] = 0
        job_state["current_state"] = next_state
        job_state["status"] = JOB_STATUS_RUNNING
        await self.storage.save_job_state(job_id, job_state)
        await self.storage.enqueue_job(job_id)

    async def _handle_dispatch(
        self,
        job_state: dict[str, Any],
        task_info: dict[str, Any],
        duration_ms: int,
    ) -> None:
        job_id = job_state["id"]
        current_state = job_state["current_state"]

        await self.history_storage.log_job_event(
            {
                "job_id": job_id,
                "client_token": job_state.get("client_config", {}).get("token"),
                "state": current_state,
                "event_type": "task_dispatched",
                "duration_ms": duration_ms,
                "timestamp": time(),
                "context_snapshot": {**job_state, "task_info": task_info},
            },
        )

        if task_info.get("type") == "human_approval":
            job_state["status"] = "waiting_for_human"
            job_state["current_task_transitions"] = task_info.get("transitions", {})
            job_state["approval_token"] = token_urlsafe(32)
            await self.storage.save_job_state(job_id, job_state)
            logger.info(f"Job {job_id} is now paused, awaiting human approval.")
        else:
            logger.info(f"Job {job_id} dispatching task: {task_info}")

            now = time()
            now_mono = monotonic()

            dispatch_timeout = task_info.get("dispatch_timeout_seconds")
            result_timeout = task_info.get("result_timeout_seconds")
            execution_timeout = task_info.get("timeout_seconds")

            job_state["skill_version"] = task_info.get("skill_version")
            job_state["skill_type"] = task_info.get("skill_type")

            dispatch_deadline = now + dispatch_timeout if dispatch_timeout else None
            result_deadline = now + result_timeout if result_timeout else None

            deadlines = [d for d in (dispatch_deadline, result_deadline) if d is not None]
            if deadlines:
                timeout_at = min(deadlines)
            else:
                timeout_at = now + (execution_timeout or self.engine.config.WORKER_TIMEOUT_SECONDS)

            job_state["status"] = JOB_STATUS_WAITING_FOR_WORKER
            job_state["task_dispatched_at"] = now_mono
            job_state["current_task_info"] = task_info
            job_state["current_task_transitions"] = task_info.get("transitions", {})
            job_state["current_task_event_transitions"] = task_info.get("event_transitions", {})

            job_state["dispatch_deadline"] = dispatch_deadline
            job_state["result_deadline"] = result_deadline
            job_state["execution_timeout_seconds"] = execution_timeout

            await self.storage.save_job_state(job_id, job_state)
            await self.storage.add_job_to_watch(job_id, timeout_at)
            await self.dispatcher.dispatch(job_state, task_info)

    async def _handle_run_blueprint(
        self,
        parent_job_state: dict[str, Any],
        sub_blueprint_info: dict[str, Any],
        duration_ms: int,
    ) -> None:
        parent_job_id = parent_job_state["id"]
        blueprint_name = sub_blueprint_info["blueprint_name"]
        sub_input = sub_blueprint_info.get("input")
        if sub_input is None:
            sub_input = {}
        if not isinstance(sub_input, dict):
            if hasattr(sub_input, "model_dump"):
                sub_input = sub_input.model_dump()
            elif hasattr(sub_input, "dict") and callable(sub_input.dict):
                sub_input = sub_input.dict()
            elif hasattr(sub_input, "__struct_fields__"):
                sub_input = to_builtins(sub_input)
            elif hasattr(sub_input, "__dataclass_fields__"):
                sub_input = asdict(sub_input)

        contract = self.engine.blueprint_contracts.get(blueprint_name, {})
        input_schema = contract.get("input_schema")
        if input_schema:
            is_valid, error_msg = validate_data(sub_input, input_schema)
            if not is_valid:
                error = ValueError(f"Sub-blueprint '{blueprint_name}' input validation failed: {error_msg}")
                await self._handle_failure(parent_job_state, error, duration_ms)
                return

        parent_depth = parent_job_state.get("depth", 0)
        new_depth = parent_depth + 1

        if new_depth > self.engine.config.MAX_HOLARCHY_DEPTH:
            error_msg = f"Holarchy depth limit exceeded ({new_depth} > {self.engine.config.MAX_HOLARCHY_DEPTH})"
            logger.critical(f"Job {parent_job_id} quarantined: {error_msg}")
            parent_job_state["status"] = JOB_STATUS_QUARANTINED
            parent_job_state["error_message"] = error_msg
            with suppress(Exception):
                evidence = generate_evidence_card(
                    parent_job_state, error_msg, current_state=parent_job_state.get("current_state")
                )
                parent_job_state["evidence"] = evidence
                parent_job_state["evidence_card"] = evidence["markdown"]
            await self.storage.save_job_state(parent_job_id, parent_job_state)
            await self.storage.quarantine_job(parent_job_id)
            return

        try:
            child_job_id = await self.engine.create_background_job(
                blueprint_name=blueprint_name,
                input=sub_input,
                source=f"parent:{parent_job_id}",
                tracing_context=parent_job_state.get("tracing_context"),
                data_metadata=parent_job_state.get("data_metadata"),
                parent_job_id=parent_job_id,
                dispatch_timeout=sub_blueprint_info.get("dispatch_timeout"),
                result_timeout=sub_blueprint_info.get("result_timeout"),
                security=parent_job_state.get("security"),
                metadata=parent_job_state.get("metadata"),
                policy=parent_job_state.get("policy"),
                depth=new_depth,
                parent_hash=parent_job_state.get("current_hash") or parent_job_state.get("parent_hash"),
                max_transitions=parent_job_state.get("max_transitions"),
            )
        except Exception as e:
            error_msg = f"Failed to dispatch sub-job: {e}"
            logger.error(error_msg)
            error_val = RuntimeError(error_msg)
            await self._handle_failure(parent_job_state, error_val, duration_ms)
            return

        parent_job_state["status"] = "waiting_for_sub_job"
        parent_job_state["child_job_id"] = child_job_id
        parent_job_state["current_task_transitions"] = sub_blueprint_info.get(
            "transitions",
            {},
        )
        await self.storage.save_job_state(parent_job_id, parent_job_state)
        logger.info(f"Job {parent_job_id} paused, starting sub-job {child_job_id}.")

    async def _handle_parallel_dispatch(
        self,
        job_state: dict[str, Any],
        parallel_info: dict[str, Any],
        duration_ms: int,
    ) -> None:
        job_id = job_state["id"]
        tasks_to_dispatch = parallel_info["tasks"]
        aggregate_into = parallel_info["aggregate_into"]

        logger.info(
            f"Job {job_id} dispatching {len(tasks_to_dispatch)} tasks in parallel, "
            f"aggregating into '{aggregate_into}'.",
        )

        branch_task_ids = [str(uuid4()) for _ in tasks_to_dispatch]

        # Update job state for parallel execution
        job_state["status"] = JOB_STATUS_WAITING_FOR_PARALLEL
        job_state["current_state"] = aggregate_into
        job_state["aggregation_target"] = aggregate_into
        job_state["active_branches"] = branch_task_ids
        job_state["aggregation_results"] = {}
        job_state["parallel_tasks_info"] = {}
        await self.storage.save_job_state(job_id, job_state)

        for i, task_info in enumerate(tasks_to_dispatch):
            branch_id = branch_task_ids[i]

            full_task_info = {
                "task_id": branch_id,
                "job_id": job_id,
                "tracing_context": job_state.get("tracing_context", {}),
                "security": job_state.get("security"),
                "metadata": job_state.get("metadata"),
                "skill_version": task_info.get("skill_version"),
                "skill_type": task_info.get("skill_type"),
                **task_info,
            }
            job_state.setdefault("parallel_tasks_info", {})[branch_id] = full_task_info

            job_state = await self.dispatcher.dispatch(job_state, full_task_info)

            now = time()
            dispatch_timeout = task_info.get("dispatch_timeout_seconds")
            result_timeout = task_info.get("result_timeout_seconds")
            execution_timeout = task_info.get("timeout_seconds")

            dispatch_deadline = now + dispatch_timeout if dispatch_timeout is not None else None
            result_deadline = now + result_timeout if result_timeout is not None else None

            deadlines = [d for d in (dispatch_deadline, result_deadline) if d is not None]
            if deadlines:
                timeout_at = min(deadlines)
            else:
                timeout_at = now + (execution_timeout or self.engine.config.WORKER_TIMEOUT_SECONDS)

            await self.storage.add_job_to_watch(
                f"{job_id}:{branch_id}",
                timeout_at,
            )

    async def _handle_failure(
        self,
        job_state: dict[str, Any],
        error: Exception,
        duration_ms: int,
    ) -> None:
        """Handles failures that occur *during the execution of a handler*.

        This is different from a task failure reported by a worker. This logic
        retries the handler execution itself and, if it repeatedly fails,
        moves the job to quarantine.
        """
        job_id = job_state["id"]
        current_retries = job_state.get("retry_count", 0)
        max_retries = self.engine.config.JOB_MAX_RETRIES
        current_state = job_state.get("current_state")

        logger.exception(
            f"Error executing handler for job {job_id}. Attempt {current_retries + 1}/{max_retries}.",
        )

        await self.history_storage.log_job_event(
            {
                "job_id": job_id,
                "client_token": job_state.get("client_config", {}).get("token"),
                "state": current_state,
                "event_type": "state_failed",
                "duration_ms": duration_ms,
                "attempt_number": current_retries + 1,
                "timestamp": time(),
                "context_snapshot": {**job_state, "error_message": str(error)},
            },
        )

        if "history" in job_state and isinstance(job_state["history"], list):
            job_state["history"].append(
                {
                    "state": current_state,
                    "status": "failed",
                    "error": str(error),
                    "duration_ms": duration_ms,
                    "timestamp": time(),
                }
            )

        job_state["error_message"] = str(error)

        if current_retries < max_retries:
            job_state["retry_count"] = current_retries + 1
            job_state["status"] = "awaiting_retry"
            await self.storage.save_job_state(job_id, job_state)
            await self.storage.enqueue_job(job_id)
            logger.warning(
                f"Job {job_id} failed in-handler, will be retried. Attempt {job_state['retry_count']}.",
            )
        else:
            logger.critical(
                f"Job {job_id} has failed handler execution {max_retries + 1} times. Moving to quarantine.",
            )
            await self._handle_terminal_reached(job_state, JOB_STATUS_QUARANTINED, duration_ms)
            await self.storage.quarantine_job(job_id)

            s3_service = self.engine.app.get(S3_SERVICE_KEY)
            if s3_service and self.engine.config.S3_AUTO_CLEANUP:
                task_files = s3_service.get_task_files(job_id)
                if task_files:
                    create_task(task_files.cleanup())

            await self._check_and_resume_parent(job_state)
            await self.engine.send_job_webhook(job_state, "job_quarantined")

            self.metrics.jobs_failed_total.add(
                1,
                {LABEL_BLUEPRINT: job_state.get("blueprint_name", "unknown")},
            )

    async def _check_and_resume_parent(self, child_job_state: dict[str, Any]) -> None:
        """Checks if a completed job was a sub-job. If so, it resumes the parent
        job, passing the success/failure outcome of the child.
        """
        try:
            parent_job_id = child_job_state.get("parent_job_id")
            child_job_id = child_job_state["id"]

            if not parent_job_id:
                return

            logger.info(
                f"Sub-job {child_job_id} finished. Resuming parent job {parent_job_id}.",
            )
            parent_job_state = await self.storage.get_job_state(parent_job_id)
            if not parent_job_state:
                logger.error(
                    f"Parent job {parent_job_id} not found for child {child_job_id}.",
                )
                return

            ensure_storage_zones(parent_job_state)
            child_outcome = (
                "success"
                if child_job_state.get("current_state") == JOB_STATUS_FINISHED
                or child_job_state.get("status") == JOB_STATUS_FINISHED
                else "failure"
            )
            transitions = parent_job_state.get("current_task_transitions", {})
            next_state = transitions.get(child_outcome, "failed")

            child_bp_name = child_job_state.get("blueprint_name")
            child_output = child_job_state.get("output")
            if child_output is None:
                child_output = child_job_state.get("result")
            if child_output is None:
                child_output = {
                    "outcome": child_outcome,
                    "final_state": child_job_state.get("current_state"),
                    "error_message": child_job_state.get("error_message"),
                }

            if "steps" not in parent_job_state or not isinstance(parent_job_state["steps"], dict):
                parent_job_state["steps"] = {}

            sub_job_key = f"sub_job_{child_job_id}"
            parent_job_state["steps"][sub_job_key] = child_output
            parent_job_state["steps"][f"{sub_job_key}_result"] = {
                "outcome": child_outcome,
                "final_state": child_job_state.get("current_state"),
                "error_message": child_job_state.get("error_message"),
            }
            if child_bp_name:
                parent_job_state["steps"][child_bp_name] = child_output

            parent_job_state["current_state"] = next_state
            parent_job_state["status"] = JOB_STATUS_RUNNING
            await self.storage.save_job_state(parent_job_id, parent_job_state)
            await self.storage.enqueue_job(parent_job_id)
        except Exception as e:
            logger.exception(f"CRITICAL ERROR in _check_and_resume_parent: {e}")

    @staticmethod
    def _handle_task_completion(task: Task) -> None:
        """Callback to handle completion of a job processing task."""
        try:
            task.result()
        except CancelledError:
            pass
        except Exception:
            logger.exception("Unhandled exception in job processing task")

    async def run(self) -> None:

        logger.info("JobExecutor started.")
        self._running = True
        semaphore = Semaphore(self.engine.config.EXECUTOR_MAX_CONCURRENT_JOBS)
        backoff_delay = 1.0

        while self._running:
            acquired = False
            try:
                await semaphore.acquire()
                acquired = True

                block_time = self.engine.config.REDIS_STREAM_BLOCK_MS
                result = await self.storage.dequeue_job(block=block_time if block_time > 0 else None)

                if result:
                    job_id, message_id = result
                    task = create_task(self._process_job(job_id, message_id))
                    self._active_tasks.add(task)
                    task.add_done_callback(self._active_tasks.discard)
                    task.add_done_callback(self._handle_task_completion)
                    task.add_done_callback(lambda _: semaphore.release())
                    backoff_delay = 1.0
                else:
                    semaphore.release()
                    acquired = False
                    if block_time <= 0:
                        await sleep(0.1)

            except CancelledError:
                if acquired:
                    semaphore.release()
                break
            except Exception:
                logger.exception("Error in JobExecutor main loop.")
                if acquired:
                    with suppress(ValueError):
                        semaphore.release()
                await sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, 60.0)

        logger.info("JobExecutor stopped.")

    def stop(self) -> None:
        self._running = False
        for t in list(self._active_tasks):
            if not t.done():
                t.cancel()
