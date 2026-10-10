# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import iscoroutine, wait_for
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from inspect import signature
from logging import getLogger
from time import monotonic
from typing import Any

from msgspec import to_builtins
from rxon.models import ExecutionReceipt

logger = getLogger(__name__)


class ActionFactory:
    """A factory that provides handlers with methods for process control."""

    def __init__(
        self,
        job_id: str,
        default_dispatch_timeout: int | None = None,
        default_result_timeout: int | None = None,
        policy: dict[str, Any] | None = None,
        blueprint: Any | None = None,
    ):
        self._job_id = job_id
        self._default_dispatch_timeout = default_dispatch_timeout
        self._default_result_timeout = default_result_timeout
        self._policy = policy or {}
        self._blueprint = blueprint
        self._next_state_val: str | None = None
        self._task_to_dispatch_val: dict[str, Any] | None = None
        self._sub_blueprint_to_run_val: dict[str, Any] | None = None
        self._parallel_tasks_to_dispatch_val: dict[str, Any] | None = None
        self._pending_events: list[tuple[str, dict[str, Any], Any, Any]] = []
        self._context_updates: dict[str, Any] = {}
        self._step_result: Any | None = None
        self._last_receipt: ExecutionReceipt | dict[str, Any] | None = None

    def _check_for_existing_action(self) -> None:
        """
        Helper to ensure only one action is set.
        Raises RuntimeError if any action value is already set.
        """
        if any(
            [
                self._next_state_val,
                self._task_to_dispatch_val,
                self._sub_blueprint_to_run_val,
                self._parallel_tasks_to_dispatch_val,
            ]
        ):
            raise RuntimeError(
                "Cannot set multiple actions in the same step. "
                "An action (transition, task, blueprint, or parallel) has already been defined."
            )

    @property
    def next_state(self) -> str | None:
        return self._next_state_val

    @property
    def task_to_dispatch(self) -> dict[str, Any] | None:
        return self._task_to_dispatch_val

    @property
    def sub_blueprint_to_run(self) -> dict[str, Any] | None:
        return self._sub_blueprint_to_run_val

    @property
    def parallel_tasks_to_dispatch(self) -> dict[str, Any] | None:
        return self._parallel_tasks_to_dispatch_val

    @property
    def pending_events(self) -> list[tuple[str, dict[str, Any], Any, Any]]:
        return self._pending_events

    @property
    def context_updates(self) -> dict[str, Any]:
        """Returns the pending context updates."""
        return self._context_updates

    @property
    def step_result(self) -> Any:
        """Returns the manually saved step result."""
        return self._step_result

    def save_result(self, result: Any) -> None:
        """Saves a step result."""
        self._step_result = result

    def update_context(self, updates: dict[str, Any]) -> None:
        """Updates the job context with new values."""
        self._context_updates.update(updates)

    def send_event(self, event_type: str, payload: dict[str, Any], security: Any = None, metadata: Any = None) -> None:
        """Emits a generic event from the blueprint logic."""
        logger.debug(f"Job {self._job_id}: Ghost emitting event '{event_type}'")
        self._pending_events.append((event_type, payload, security, metadata))

    def dispatch_parallel(self, tasks: list[dict[str, Any]], aggregate_into: str) -> None:
        """
        Dispatches multiple tasks for parallel execution.
        """
        self._check_for_existing_action()

        allowed_skills = self._policy.get("allowed_skills")
        if allowed_skills is not None:
            for task in tasks:
                t_type = task.get("type")
                if t_type and t_type not in allowed_skills:
                    raise PermissionError(
                        f"Task type '{t_type}' is not permitted by job policy. Allowed skills: {allowed_skills}"
                    )

        logger.debug(
            f"Job {self._job_id}: Dispatching {len(tasks)} tasks in parallel, aggregating into '{aggregate_into}'"
        )
        self._parallel_tasks_to_dispatch_val = {
            "tasks": tasks,
            "aggregate_into": aggregate_into,
        }

    def go_to(self, state: str) -> None:
        """Schedules a transition to a new state."""
        if self._next_state_val == state:
            return
        self._check_for_existing_action()
        logger.debug(f"Job {self._job_id}: Transitioning to '{state}'")
        self._next_state_val = state

    def dispatch_task(
        self,
        task_type: str,
        params: dict[str, Any],
        transitions: dict[str, str],
        skill_version: str | None = None,
        event_transitions: dict[str, str] | None = None,
        dispatch_strategy: str = "default",
        resource_requirements: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        dispatch_timeout_seconds: int | None = None,
        result_timeout_seconds: int | None = None,
        max_cost: float | None = None,
        priority: float = 0.0,
        resource_hint: str | None = None,
        skill_type: str | None = None,
    ) -> None:
        """Dispatches a task to a worker for execution."""
        self._check_for_existing_action()

        allowed_skills = self._policy.get("allowed_skills")
        if allowed_skills is not None and task_type not in allowed_skills:
            raise PermissionError(
                f"Task type '{task_type}' is not permitted by job policy. Allowed skills: {allowed_skills}"
            )
        logger.debug(f"Job {self._job_id}: Dispatching task '{task_type}' (version {skill_version})")

        if resource_hint:
            params["resource_hint"] = resource_hint

        # Priority: explicit param > job default
        final_dispatch_timeout = (
            dispatch_timeout_seconds if dispatch_timeout_seconds is not None else self._default_dispatch_timeout
        )
        final_result_timeout = (
            result_timeout_seconds if result_timeout_seconds is not None else self._default_result_timeout
        )

        self._task_to_dispatch_val = {
            "type": task_type,
            "params": params,
            "transitions": transitions,
            "event_transitions": event_transitions or {},
            "dispatch_strategy": dispatch_strategy,
            "resource_requirements": resource_requirements,
            "timeout_seconds": timeout_seconds,
            "dispatch_timeout_seconds": final_dispatch_timeout,
            "result_timeout_seconds": final_result_timeout,
            "max_cost": max_cost,
            "priority": priority,
            "skill_version": skill_version,
            "skill_type": skill_type,
        }

    def await_human_approval(
        self,
        integration: str,
        message: str,
        transitions: dict[str, str],
    ) -> None:
        """Pauses the pipeline until an external signal (human approval) is received."""
        self._check_for_existing_action()
        logger.debug(f"Job {self._job_id}: Awaiting human approval via {integration}")
        self._task_to_dispatch_val = {
            "type": "human_approval",
            "integration": integration,
            "message": message,
            "transitions": transitions,
        }

    def run_blueprint(
        self,
        blueprint_name: str,
        input: Any = None,  # noqa: A002
        transitions: dict[str, str] | None = None,
        dispatch_timeout: int | None = None,
        result_timeout: int | None = None,
    ) -> None:
        """Runs a child blueprint and waits for its result."""
        self._check_for_existing_action()
        payload = input
        if payload is not None:
            if hasattr(payload, "model_dump"):
                payload = payload.model_dump()
            elif hasattr(payload, "dict") and callable(getattr(payload, "dict", None)):
                payload = payload.dict()
            elif hasattr(payload, "__struct_fields__"):
                payload = to_builtins(payload)
            elif is_dataclass(payload) and not isinstance(payload, type):
                payload = asdict(payload)

        data = payload if isinstance(payload, dict) else (payload or {})
        logger.debug(f"Job {self._job_id}: Running sub-blueprint '{blueprint_name}'")
        self._sub_blueprint_to_run_val = {
            "blueprint_name": blueprint_name,
            "input": data,
            "transitions": transitions or {},
            "dispatch_timeout": dispatch_timeout,
            "result_timeout": result_timeout,
        }

    @property
    def last_receipt(self) -> ExecutionReceipt | dict[str, Any] | None:
        return self._last_receipt

    async def decide(
        self,
        candidates_or_decider: list[Any] | str | None = None,
        fallback: Any = None,
        timeout_seconds: float = 3.0,
        candidates: list[Any] | None = None,
        intent: str | None = None,
        evaluator: Callable[..., Any] | None = None,
        context: Any = None,
        step: str | None = None,
    ) -> str:
        """Advisory decision method enforcing Host-Owned Choice and Fail-Open guarantee."""
        if isinstance(candidates_or_decider, str):
            decider_name = candidates_or_decider
            cands = candidates or []
            fb = fallback
        elif isinstance(candidates_or_decider, (list, tuple, set)):
            decider_name = intent or ""
            cands = list(candidates_or_decider)
            fb = fallback
        else:
            decider_name = intent or ""
            cands = candidates or []
            fb = fallback

        candidates_str = [str(c) for c in cands]
        fallback_str = str(fb) if fb is not None else (candidates_str[0] if candidates_str else "")
        start_t = monotonic()
        chosen = fallback_str
        fallback_triggered = False
        err_msg = None
        reason = "decider_selection"

        eval_fn = evaluator
        eval_timeout = timeout_seconds
        bp = self._blueprint or getattr(context, "_blueprint", None) or getattr(context, "blueprint", None)

        if eval_fn is None and decider_name:
            deciders_map = getattr(bp, "_deciders", None)
            if isinstance(deciders_map, dict):
                decider_entry = deciders_map.get(decider_name)
                if isinstance(decider_entry, dict):
                    eval_fn = decider_entry.get("func")
                    eval_timeout = decider_entry.get("timeout_seconds", timeout_seconds)
                else:
                    fallback_triggered = True
                    reason = "unregistered_decider"
                    err_msg = f"Decider '{decider_name}' is not registered on blueprint."
            else:
                fallback_triggered = True
                reason = "unregistered_decider"
                err_msg = f"Decider '{decider_name}' is not registered on blueprint."

        if not fallback_triggered:
            if eval_fn is not None:
                try:
                    sig = signature(eval_fn)
                    kwargs: dict[str, Any] = {}
                    if "candidates" in sig.parameters:
                        kwargs["candidates"] = candidates_str
                    if "ctx" in sig.parameters:
                        kwargs["ctx"] = context
                    elif "context" in sig.parameters:
                        kwargs["context"] = context

                    if kwargs:
                        res = eval_fn(**kwargs)
                    else:
                        try:
                            res = eval_fn(candidates_str, context)
                        except TypeError:
                            res = eval_fn(context) if context is not None else eval_fn()

                    if iscoroutine(res):
                        res = await wait_for(res, timeout=eval_timeout)

                    res_str = str(res)
                    if res_str in candidates_str:
                        chosen = res_str
                        reason = "decider_selection"
                    else:
                        fallback_triggered = True
                        reason = "invalid_choice"
                        err_msg = f"Decider returned non-candidate '{res_str}'"
                except TimeoutError:
                    fallback_triggered = True
                    reason = "timeout"
                    err_msg = f"Decider timed out after {eval_timeout}s"
                except Exception as e:
                    fallback_triggered = True
                    reason = "exception"
                    err_msg = str(e)
            else:
                if candidates_str:
                    chosen = candidates_str[0]
                    reason = "default_selection"
                else:
                    chosen = fallback_str
                    fallback_triggered = True
                    reason = "no_candidates"

        duration_ms = int((monotonic() - start_t) * 1000)
        corr_id = str(getattr(context, "job_id", self._job_id))
        step_name = step or str(getattr(context, "current_state", "decide"))

        receipt = ExecutionReceipt(
            correlation_id=corr_id,
            job_id=corr_id,
            step=step_name,
            decider_name=decider_name or "default",
            candidates=candidates_str,
            fallback=fallback_str,
            chosen=chosen,
            fallback_triggered=fallback_triggered,
            reason=reason,
            duration_ms=duration_ms,
            error=err_msg,
            error_message=err_msg,
            context_snapshot={"input": getattr(context, "input", {}) or {}} if context else {},
        )
        self._last_receipt = receipt
        return chosen
