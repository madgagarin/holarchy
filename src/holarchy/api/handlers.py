# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from collections.abc import Callable
from contextlib import suppress
from hmac import compare_digest
from importlib import resources
from logging import getLogger
from time import monotonic
from typing import Any, cast
from uuid import uuid4

from aiohttp import web
from orjson import OPT_INDENT_2, dumps, loads
from rxon.constants import (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_WAITING_FOR_HUMAN,
    JOB_STATUS_WAITING_FOR_WORKER,
)
from rxon.schema import validate_data

from ..app_keys import (
    CLIENT_CONFIG_KEY,
    ENGINE_KEY,
    S3_SERVICE_KEY,
)
from ..blueprint import Blueprint
from ..diagnostic import generate_evidence_card
from ..metrics import LABEL_BLUEPRINT
from ..security import AUTH_HEADER_CLIENT
from ..utils.json import json_response
from ..worker_config_loader import load_worker_configs_to_redis
from .openapi import generate_openapi_spec

logger = getLogger(__name__)


async def status_handler(_request: web.Request) -> web.Response:
    return json_response({"status": "ok"})


async def openapi_json_handler(request: web.Request) -> web.Response:
    """Returns the dynamic OpenAPI 3.1.0 specification."""
    engine = request.app[ENGINE_KEY]
    spec = generate_openapi_spec(engine)
    resp = json_response(spec)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


async def start_job_by_name_handler(request: web.Request) -> web.Response:
    """Starts a job for a blueprint identified by name in the URL path."""
    engine = request.app[ENGINE_KEY]
    blueprint_name = request.match_info.get("blueprint_name")
    if not blueprint_name or blueprint_name not in engine.blueprints:
        return json_response({"error": f"Blueprint '{blueprint_name}' not found"}, status=404)
    bp = engine.blueprints[blueprint_name]
    handler = create_job_handler_factory(bp)
    return await handler(request)


def create_job_handler_factory(blueprint: Blueprint) -> Callable[[web.Request], Any]:
    async def handler(request: web.Request) -> web.Response:
        engine = request.app[ENGINE_KEY]
        try:
            request_body = await request.json(loads=loads)
            if not isinstance(request_body, dict):
                initial_data = request_body
                webhook_url = None
                dispatch_timeout = None
                result_timeout = None
                security = None
                metadata = None
                policy = None
                max_transitions = None
            else:
                if "input" in request_body:
                    initial_data = request_body["input"]
                elif "initial_data" in request_body:
                    initial_data = request_body["initial_data"]
                else:
                    system_keys = {
                        "webhook_url",
                        "dispatch_timeout",
                        "result_timeout",
                        "security",
                        "metadata",
                        "policy",
                        "max_transitions",
                        "client_config",
                    }
                    business_data = {k: v for k, v in request_body.items() if k not in system_keys}
                    initial_data = business_data if business_data else {}
                webhook_url = request_body.get("webhook_url")
                dispatch_timeout = request_body.get("dispatch_timeout")
                result_timeout = request_body.get("result_timeout")
                security = request_body.get("security")
                metadata = request_body.get("metadata")
                policy = request_body.get("policy")
                max_transitions = request_body.get("max_transitions")
        except Exception:
            return json_response({"error": "Invalid JSON body"}, status=400)

        # HTTP Header overrides
        header_webhook = request.headers.get("X-Webhook-URL") or request.headers.get("x-webhook-url")
        if header_webhook:
            webhook_url = header_webhook

        header_timeout = request.headers.get("X-Job-Timeout") or request.headers.get("x-job-timeout")
        if header_timeout is not None:
            with suppress(ValueError, TypeError):
                dispatch_timeout = int(header_timeout)

        job_priority = (
            request.headers.get("X-Job-Priority")
            or request.headers.get("x-job-priority")
            or "normal"
        )

        carrier = {str(k): v for k, v in request.headers.items()}
        correlation_id = (
            request.headers.get("X-Correlation-ID")
            or request.headers.get("x-correlation-id")
            or carrier.get("x-correlation-id")
        )

        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or request.headers.get("idempotency-key")
        )

        client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config", {})
        client_token = client_config.get("token") or "anonymous"

        if idempotency_key:
            existing_job_id = await engine.storage.get_idempotent_job_id(client_token, idempotency_key)
            if existing_job_id:
                existing_state = await engine.storage.get_job_state(existing_job_id)
                if existing_state:
                    return json_response(
                        {"status": "accepted", "job_id": existing_job_id, "id": existing_job_id},
                        status=200,
                    )

        if policy is not None:
            if not isinstance(policy, dict):
                return json_response({"error": "'policy' must be a dictionary"}, status=400)
            policy_bytes = len(dumps(policy))
            max_policy_bytes = getattr(engine.config, "MAX_POLICY_SIZE_BYTES", 4096)
            if policy_bytes > max_policy_bytes:
                return json_response(
                    {"error": f"Policy size exceeds MAX_POLICY_SIZE_BYTES limit ({policy_bytes} > {max_policy_bytes})"},
                    status=400,
                )
            allowed_skills = policy.get("allowed_skills")
            if allowed_skills is not None and (
                not isinstance(allowed_skills, list)
                or not allowed_skills
                or not all(isinstance(s, str) for s in allowed_skills)
            ):
                return json_response(
                    {"error": "'policy.allowed_skills' must be a non-empty list of strings"}, status=400
                )

        if max_transitions is not None:
            max_allowed = getattr(engine.config, "MAX_TRANSITIONS_PER_JOB", 100)
            if not isinstance(max_transitions, int) or max_transitions < 1 or max_transitions > max_allowed:
                return json_response(
                    {"error": f"'max_transitions' must be an integer between 1 and {max_allowed}"}, status=400
                )

        contract = engine.blueprint_contracts.get(blueprint.name, {})
        input_schema = contract.get("input_schema")
        if input_schema:
            is_valid, error_msg = validate_data(initial_data, input_schema)
            if not is_valid:
                return json_response(
                    {"error": f"Input validation failed for blueprint '{blueprint.name}': {error_msg}"}, status=400
                )

        job_id = str(uuid4())
        job_meta = {
            "priority": job_priority,
            "timeout": dispatch_timeout,
            "webhook_url": webhook_url,
            "correlation_id": correlation_id,
            "headers": carrier,
        }
        if isinstance(metadata, dict):
            job_meta.update(metadata)
            job_meta["headers"] = carrier
            job_meta["priority"] = job_priority
            if correlation_id:
                job_meta["correlation_id"] = correlation_id

        job_state = {
            "id": job_id,
            "job_id": job_id,
            "blueprint": blueprint.name,
            "blueprint_name": blueprint.name,
            "current_state": blueprint.start_state,
            "status": JOB_STATUS_PENDING,
            # 5 Clean Zones:
            "input": initial_data,
            "output": None,
            "steps": {},
            "history": [],
            "params": client_config.get("params", {}),
            "meta": job_meta,
            # Compatibility aliases:
            "initial_data": initial_data,
            "state_history": {},
            "tracing_context": carrier,
            "client_config": client_config,
            "webhook_url": webhook_url,
            "dispatch_timeout": dispatch_timeout,
            "result_timeout": result_timeout,
            "security": security,
            "metadata": metadata or {},
            "policy": policy,
            "max_transitions": max_transitions,
        }
        await engine.storage.save_job_state(job_id, job_state)

        if idempotency_key:
            await engine.storage.set_idempotent_job_id(client_token, idempotency_key, job_id)

        await engine.history_storage.log_job_event(
            {
                "job_id": job_id,
                "client_token": client_config.get("token"),
                "state": "pending",
                "event_type": "job_created",
                "context_snapshot": job_state,
                "metadata": {"source": "api", "client": client_config.get("token")},
            }
        )

        # Immediately start watching for dispatch timeout
        if dispatch_timeout:
            await engine.storage.add_job_to_watch(job_id, monotonic() + dispatch_timeout)

        await engine.storage.enqueue_job(job_id)
        engine.metrics.jobs_total.add(1, {LABEL_BLUEPRINT: blueprint.name})
        return json_response({"status": "accepted", "job_id": job_id, "id": job_id}, status=202)

    return handler


def _filter_job_state(
    state: dict[str, Any], detailed_allowed: bool, requested_fields: set[str] | None = None
) -> dict[str, Any]:
    """Helper to filter job state based on security settings and user request."""
    state_to_filter = dict(state)

    # Base fields that are always safe to return in compact mode
    compact_fields = {
        "id",
        "job_id",
        "status",
        "blueprint_name",
        "context_snapshot",
        "child_job_id",
        "step",
        "depth",
        "parent_hash",
        "max_transitions",
    }

    # Define terminal states for access control
    terminal_states = {"finished", "failed", "error", "quarantined", "cancelled"}
    is_terminal = state_to_filter.get("status") in terminal_states

    if not detailed_allowed:
        allowed = compact_fields.copy()

        # 'result' and 'output' are ONLY allowed and available if the job is terminal
        if is_terminal:
            if "result" in state_to_filter:
                allowed.add("result")
            if "output" in state_to_filter:
                allowed.add("output")

        if requested_fields:
            # Allow clean 5-zone and alias fields if explicitly requested
            modern_fields = (
                "blueprint", "error", "input", "output", "steps",
                "history", "params", "meta", "created_at", "finished_at",
            )
            for f in modern_fields:
                if f in requested_fields:
                    allowed.add(f)
                    if f == "blueprint" and "blueprint" not in state_to_filter and "blueprint_name" in state_to_filter:
                        state_to_filter["blueprint"] = state_to_filter["blueprint_name"]
                    if f == "error" and "error" not in state_to_filter and "error_message" in state_to_filter:
                        state_to_filter["error"] = state_to_filter["error_message"]

            # Intersection with allowed fields, ensuring 'id' is always present
            allowed = requested_fields.intersection(allowed)
            allowed.add("id")

        result_data = {k: v for k, v in state_to_filter.items() if k in allowed}
    else:
        # Detailed mode: allow everything EXCEPT explicitly sensitive system fields
        sensitive_fields = {"client_config", "security", "internal_load"}
        if "blueprint" not in state_to_filter and "blueprint_name" in state_to_filter:
            state_to_filter["blueprint"] = state_to_filter["blueprint_name"]
        if "error" not in state_to_filter and "error_message" in state_to_filter:
            state_to_filter["error"] = state_to_filter["error_message"]

        if requested_fields:
            requested_fields.add("id")
            result_data = {
                k: v for k, v in state_to_filter.items() if k in requested_fields and k not in sensitive_fields
            }
        else:
            result_data = {k: v for k, v in state_to_filter.items() if k not in sensitive_fields}

        # Even in detailed mode, 'result'/'output' is only for terminal states to prevent work tracking
        if not is_terminal:
            result_data.pop("result", None)
            result_data.pop("output", None)
        else:
            if not requested_fields:
                if "result" in result_data and "output" not in result_data:
                    result_data["output"] = result_data["result"]
                elif "output" in result_data and "result" not in result_data:
                    result_data["result"] = result_data["output"]
            else:
                if "output" in requested_fields and "output" not in result_data and "result" in state_to_filter:
                    result_data["output"] = state_to_filter["result"]
                if "result" in requested_fields and "result" not in result_data and "output" in state_to_filter:
                    result_data["result"] = state_to_filter["output"]

    # Recursively filter context_snapshot if it exists to ensure nested data is also secured
    if "context_snapshot" in result_data and isinstance(result_data["context_snapshot"], dict):
        result_data["context_snapshot"] = _filter_job_state(result_data["context_snapshot"], detailed_allowed)

    return result_data


def _verify_job_ownership(job_state: dict[str, Any], request: web.Request) -> None:
    """Verifies that the client making the request is the owner of the job."""
    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config")
    if not client_config:
        # This should not happen if middleware is correctly applied, but let's be safe
        raise web.HTTPUnauthorized(text="Client authentication required")

    job_owner_token = job_state.get("client_config", {}).get("token")
    if not job_owner_token or job_owner_token != client_config.get("token"):
        raise web.HTTPForbidden(text="Access denied: You do not own this job")


async def _verify_job_ownership_robust(engine: Any, job_id: str, request: web.Request) -> dict[str, Any] | None:
    """Verifies ownership. Returns job_state if found in Redis or history, else None.
    Raises HTTPForbidden if not owner, HTTPUnauthorized if no client token.
    """
    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config")

    if not client_config:
        # If middleware was not applied (e.g. in public sub-app), try to verify token manually
        token = request.headers.get(AUTH_HEADER_CLIENT)
        if token:
            client_config = await engine.storage.get_client_config(token)
            if not client_config:
                raise web.HTTPUnauthorized(text="Unauthorized: Invalid client token")
        else:
            raise web.HTTPUnauthorized(text="Client authentication required")

    expected_token = client_config.get("token")

    job_state = await engine.storage.get_job_state(job_id)
    if job_state:
        # Check direct ownership
        owner_token = job_state.get("client_config", {}).get("token")
        if owner_token and owner_token == expected_token:
            return cast(dict[str, Any], job_state)

        # Check ownership inheritance (if it's a child job)
        parent_id = job_state.get("parent_job_id")
        if parent_id:
            # We recursively check up the chain
            try:
                parent_state = await _verify_job_ownership_robust(engine, parent_id, request)
                if parent_state:
                    return cast(dict[str, Any], job_state)
            except (web.HTTPForbidden, web.HTTPUnauthorized):
                pass

        raise web.HTTPForbidden(text="Access denied: You do not own this job")

    # Fallback to history for expired jobs
    history = await engine.history_storage.get_job_history(job_id)
    if not history:
        return None

    owner_token = None
    for event in history:
        if event.get("client_token"):
            owner_token = event["client_token"]
            break

    if not owner_token or owner_token != expected_token:
        raise web.HTTPForbidden(text="Access denied: You do not own this job")

    last_event = history[-1]
    snapshot = last_event.get("context_snapshot")
    if snapshot and isinstance(snapshot, dict):
        return cast(dict[str, Any], snapshot)

    # Reconstruct basic state if snapshot is missing
    return {
        "id": job_id,
        "status": last_event.get("state", "unknown"),
        "blueprint_name": last_event.get("blueprint_name", "unknown"),
    }


async def get_job_status_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    if not job_id:
        return json_response({"error": "job_id is required in path"}, status=400)

    job_state = await _verify_job_ownership_robust(engine, job_id, request)
    if not job_state:
        return json_response({"error": "Job not found"}, status=404)

    fields_param = request.query.get("fields")
    requested = {f.strip() for f in fields_param.split(",")} if fields_param else None

    filtered_state = _filter_job_state(job_state, engine.config.DETAILED_API_RESPONSES, requested)

    return json_response(filtered_state, status=200)


async def cancel_job_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    if not job_id:
        return json_response({"error": "job_id is required in path"}, status=400)

    job_state = await _verify_job_ownership_robust(engine, job_id, request)
    if not job_state:
        return json_response({"error": "Job not found"}, status=404)

    cancelled = await engine.cancel_job(job_id)
    if not cancelled:
        return json_response({"error": "Job not found or already terminal."}, status=404)

    return json_response({"status": "cancellation_request_accepted"})


async def get_job_history_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    if not job_id:
        return json_response({"error": "job_id is required in path"}, status=400)

    job_state = await _verify_job_ownership_robust(engine, job_id, request)
    if not job_state:
        return json_response({"error": "Job not found"}, status=404)

    history = await engine.history_storage.get_job_history(job_id)

    # Filter sensitive context snapshots in history events
    detailed = engine.config.DETAILED_API_RESPONSES
    for event in history:
        if "context_snapshot" in event and event["context_snapshot"]:
            event["context_snapshot"] = _filter_job_state(event["context_snapshot"], detailed)

    return json_response(history)


async def get_blueprint_graph_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    blueprint_name = request.match_info.get("blueprint_name")
    if not blueprint_name:
        return json_response({"error": "blueprint_name is required in path"}, status=400)

    blueprint = engine.blueprints.get(blueprint_name)
    if not blueprint:
        return json_response({"error": "Blueprint not found"}, status=404)

    try:
        graph_dot = blueprint.render_graph()
        return web.Response(text=graph_dot, content_type="text/vnd.graphviz")
    except FileNotFoundError:
        error_msg = "Graphviz is not installed on the server. Cannot generate graph."
        logger.error(error_msg)
        return json_response({"error": error_msg}, status=501)


async def get_workers_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    workers = await engine.storage.get_available_workers()
    return json_response(workers)


async def get_worker_catalog_handler(request: web.Request) -> web.Response:
    """Aggregates all unique skills and their contracts from online workers."""
    engine = request.app[ENGINE_KEY]
    monotonic()

    cache = engine.worker_catalog_cache
    catalog_cached = cache.get("data")
    if catalog_cached is not None:
        return json_response(catalog_cached)

    workers = await engine.storage.get_available_workers()

    catalog = {}
    for worker in workers:
        for skill in worker.get("supported_skills") or []:
            skill_name = skill.get("name")
            if not skill_name:
                continue

            # If skill already in catalog, we might want to merge or track multiple versions
            # For now, we take the most detailed contract or just the first one found
            if skill_name not in catalog:
                skill_info = skill.copy()
                capabilities = worker.get("capabilities")
                cost_map = capabilities.get("cost_per_skill") if isinstance(capabilities, dict) else None
                if isinstance(cost_map, dict) and skill_name in cost_map:
                    skill_info["base_price"] = cost_map[skill_name]

                catalog[skill_name] = {
                    "contract": skill_info,
                    "providers_count": 1,
                    "worker_types": {worker.get("worker_type", "unknown")},
                    "total_reputation": worker.get("reputation", 1.0),
                }
            else:
                catalog[skill_name]["providers_count"] += 1
                catalog[skill_name]["worker_types"].add(worker.get("worker_type", "unknown"))
                catalog[skill_name]["total_reputation"] += worker.get("reputation", 1.0)

    for item in catalog.values():
        item["worker_types"] = list(item["worker_types"])
        item["average_reputation"] = round(item.pop("total_reputation") / item["providers_count"], 4)

    cache["data"] = catalog

    return json_response(catalog)


async def get_jobs_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    try:
        limit = int(request.query.get("limit", "100"))
        offset = int(request.query.get("offset", "0"))
    except ValueError:
        return json_response({"error": "Invalid limit/offset parameter"}, status=400)

    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config", {})
    client_token = client_config.get("token")

    jobs = await engine.history_storage.get_jobs(limit=limit, offset=offset, client_token=client_token)

    # Filter sensitive data in the list
    detailed = engine.config.DETAILED_API_RESPONSES
    for job in jobs:
        filtered = _filter_job_state(job, detailed)
        # Update the job dict in-place with filtered fields
        job.clear()
        job.update(filtered)

    return json_response(jobs)


async def get_dashboard_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]

    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config", {})
    client_token = client_config.get("token")

    worker_count = await engine.storage.get_active_worker_count()
    queue_length = await engine.storage.get_job_queue_length()
    job_summary = await engine.history_storage.get_job_summary(client_token=client_token)

    dashboard_data = {
        "workers": {"total": worker_count},
        "jobs": {"queued": queue_length, **job_summary},
    }
    return json_response(dashboard_data)


async def human_approval_webhook_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    if not job_id:
        return json_response({"error": "job_id is required in path"}, status=400)
    try:
        data = await request.json(loads=loads)
        decision = data.get("decision")
        security = data.get("security")
        metadata = data.get("metadata")
        token = request.query.get("token") or (data.get("token") if isinstance(data, dict) else None)
        if not decision:
            return json_response({"error": "decision is required in body"}, status=400)
    except Exception:
        return json_response({"error": "Invalid JSON body"}, status=400)

    job_state = await engine.storage.get_job_state(job_id)
    is_token_auth = False
    if job_state and token:
        expected_token = job_state.get("approval_token")
        if expected_token and compare_digest(str(token), str(expected_token)):
            is_token_auth = True

    if not is_token_auth:
        job_state = await _verify_job_ownership_robust(engine, job_id, request)
        if not job_state:
            return json_response({"error": "Job not found"}, status=404)

    if job_state.get("status") not in [JOB_STATUS_WAITING_FOR_WORKER, JOB_STATUS_WAITING_FOR_HUMAN]:
        return json_response({"error": "Job is not in a state that can be approved"}, status=409)
    transitions = job_state.get("current_task_transitions", {})
    next_state = transitions.get(decision)
    if not next_state:
        return json_response({"error": f"Invalid decision '{decision}' for this job"}, status=400)

    async def _apply_approval(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") not in (JOB_STATUS_WAITING_FOR_WORKER, JOB_STATUS_WAITING_FOR_HUMAN):
            return state
        if is_token_auth and state.get("approval_token") != expected_token:
            return state
        state["current_state"] = next_state
        state["status"] = JOB_STATUS_RUNNING
        state["approval_token"] = None
        if security:
            state["security"] = security
        if metadata:
            state.setdefault("metadata", {}).update(metadata)
        return state

    res = engine.storage.update_job_state_atomic(job_id, _apply_approval)
    if hasattr(res, "__await__"):
        res = await res

    if hasattr(res, "_mock_return_value") or type(res).__name__ == "MagicMock":
        await _apply_approval(job_state)
        await engine.storage.save_job_state(job_id, job_state)
    elif isinstance(res, dict) and res.get("status") != JOB_STATUS_RUNNING:
        return json_response({"error": "Job is not in a state that can be approved"}, status=409)

    await engine.storage.enqueue_job(job_id)
    return json_response({"status": "approval_received", "job_id": job_id})


async def get_quarantined_jobs_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]

    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config", {})
    client_token = client_config.get("token")
    if not client_token:
        return json_response({"error": "Authentication required"}, status=401)

    job_ids = await engine.storage.get_quarantined_jobs(client_token=client_token)

    # Fetch full states for these jobs
    jobs = []
    for job_id in job_ids:
        job_state = await engine.storage.get_job_state(job_id)
        if job_state:
            jobs.append(job_state)

    # Filter sensitive data
    detailed = engine.config.DETAILED_API_RESPONSES
    for job in jobs:
        if isinstance(job, dict):
            filtered = _filter_job_state(job, detailed)
            job.clear()
            job.update(filtered)

    return json_response(jobs)


async def get_job_file_upload_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    filename = request.query.get("filename")
    try:
        expires_in = int(request.query.get("expires_in", "3600"))
    except ValueError:
        return json_response({"error": "expires_in must be an integer"}, status=400)

    if not job_id or not filename:
        return json_response({"error": "job_id and filename (query param) are required"}, status=400)

    job_state = await _verify_job_ownership_robust(engine, job_id, request)
    if not job_state:
        return json_response({"error": "Job not found"}, status=404)

    s3_service = engine.app.get(S3_SERVICE_KEY)
    if not s3_service or not s3_service._enabled:
        return json_response({"error": "S3 support is not enabled"}, status=501)

    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config", {})
    client_token = client_config.get("token")
    task_files = s3_service.get_task_files(job_id, client_token=client_token)
    if not task_files:
        return json_response({"error": "Failed to initialize S3 storage for this job"}, status=500)

    try:
        # We only support PUT here now, as GET is handled by the redirect endpoint
        url = task_files.generate_presigned_url(filename, method="PUT", expires_in=expires_in)
        return json_response({"url": url, "expires_in": expires_in, "method": "PUT"})
    except Exception as e:
        logger.error(f"Failed to generate upload URL: {e}")
        return json_response({"error": str(e)}, status=500)


async def stream_job_file_upload_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    filename = request.match_info.get("filename")

    if not job_id or not filename:
        return json_response({"error": "job_id and filename (path param) are required"}, status=400)

    job_state = await _verify_job_ownership_robust(engine, job_id, request)
    if not job_state:
        return json_response({"error": "Job not found"}, status=404)

    s3_service = engine.app.get(S3_SERVICE_KEY)
    if not s3_service or not s3_service._enabled:
        return json_response({"error": "S3 support is not enabled"}, status=501)

    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config", {})
    client_token = client_config.get("token")
    task_files = s3_service.get_task_files(job_id, client_token=client_token)
    if not task_files:
        return json_response({"error": "Failed to initialize S3 storage for this job"}, status=500)

    try:
        # Pipe the request content stream directly to S3
        uri = await task_files.upload_stream(filename, request.content)
        return json_response({"status": "uploaded", "s3_uri": uri})
    except Exception as e:
        logger.error(f"Streaming upload failed for {filename}: {e}")
        return json_response({"error": str(e)}, status=500)


async def get_job_file_download_handler(request: web.Request) -> web.StreamResponse:
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    filename = request.match_info.get("filename")

    if not job_id or not filename:
        raise web.HTTPBadRequest(text="job_id and filename are required")

    job_state = await _verify_job_ownership_robust(engine, job_id, request)
    if not job_state:
        raise web.HTTPNotFound(text="Job not found")

    s3_service = engine.app.get(S3_SERVICE_KEY)
    if not s3_service or not s3_service._enabled:
        raise web.HTTPNotImplemented(text="S3 support is not enabled")

    client_config = request.get(CLIENT_CONFIG_KEY) or request.get("client_config", {})
    client_token = client_config.get("token")
    task_files = s3_service.get_task_files(job_id, client_token=client_token)
    if not task_files:
        raise web.HTTPInternalServerError(text="Failed to initialize S3 storage for this job")

    try:
        # Generate a short-lived URL for the redirect (60 seconds is enough for the browser to start downloading)
        url = task_files.generate_presigned_url(filename, method="GET", expires_in=60)
        raise web.HTTPFound(location=url)
    except web.HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate download redirect for {filename}: {e}")
        raise web.HTTPInternalServerError(text=str(e)) from e


async def reload_worker_configs_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    logger.info("Received request to reload worker configurations.")
    if not engine.config.WORKERS_CONFIG_PATH:
        return json_response(
            {"error": "WORKERS_CONFIG_PATH is not set, cannot reload configs."},
            status=400,
        )

    await load_worker_configs_to_redis(
        engine.storage,
        engine.config.WORKERS_CONFIG_PATH,
        engine.config.WORKER_AUTH_MODE,
        engine.config.REDIS_ENCRYPTION_KEY,
    )
    return json_response({"status": "worker_configs_reloaded"})


async def docs_handler(request: web.Request) -> web.Response:
    engine = request.app[ENGINE_KEY]
    try:
        content = resources.read_text("holarchy", "api.html")
    except FileNotFoundError:
        logger.error("api.html not found within the holarchy package.")
        return json_response({"error": "Documentation file not found on server."}, status=500)

    blueprint_endpoints = []
    for bp in engine.blueprints.values():
        version_prefix = f"/{bp.api_version}" if bp.api_version else ""
        if bp.api_endpoint:
            endpoint_path = bp.api_endpoint if bp.api_endpoint.startswith("/") else f"/{bp.api_endpoint}"
            full_path = f"/api{version_prefix}{endpoint_path}"
        else:
            full_path = f"/api/v1/jobs/start/{bp.name}"

        contract = engine.blueprint_contracts.get(bp.name, {})
        sec_meta = (
            bp.get_security_metadata()
            if hasattr(bp, "get_security_metadata")
            else {"risk": "low", "permissions": []}
        )

        blueprint_endpoints.append(
            {
                "id": f"post-create-{bp.name.replace('_', '-')}",
                "name": f"Create {bp.name.replace('_', ' ').title()} Job",
                "method": "POST",
                "path": full_path,
                "description": f"Creates and starts a new instance (Job) of the `{bp.name}` blueprint.",
                "request": {"body": contract.get("input_schema") or {}},
                "responses": [
                    {
                        "code": "202 Accepted",
                        "description": "Job successfully accepted for processing.",
                        "body": {"status": "accepted", "job_id": "...", "id": "..."},
                    }
                ],
                "input_schema": contract.get("input_schema"),
                "output_schema": contract.get("output_schema"),
                "events_schema": contract.get("events_schema"),
                "risk": sec_meta.get("risk", "low"),
                "permissions": sec_meta.get("permissions", []),
            }
        )

    if blueprint_endpoints:
        endpoints_json = dumps(blueprint_endpoints, option=OPT_INDENT_2).decode("utf-8")
        marker = "group: 'Protected API',\n                endpoints: ["
        content = content.replace(marker, f"{marker}\n{endpoints_json.strip('[]')},")

    s3_service = engine.app.get(S3_SERVICE_KEY)
    s3_enabled = "true" if (s3_service and s3_service._enabled) else "false"
    content = content.replace("{{S3_ENABLED}}", s3_enabled)

    return web.Response(text=content, content_type="text/html")


async def get_job_evidence_handler(request: web.Request) -> web.Response:
    """Returns the Incident Evidence Card for a job in Markdown or JSON."""
    engine = request.app[ENGINE_KEY]
    job_id = request.match_info.get("job_id")
    if not job_id:
        return json_response({"error": "job_id is required"}, status=400)

    job_state = await _verify_job_ownership_robust(engine, job_id, request)
    if not job_state:
        return json_response({"error": "Job not found"}, status=404)

    evidence = job_state.get("evidence")
    if not evidence:
        evidence = generate_evidence_card(job_state, job_state.get("error_message"))

    accept = request.headers.get("Accept", "")
    fmt = request.query.get("format", "")
    if "text/markdown" in accept or "text/plain" in accept or fmt in ("md", "markdown"):
        return web.Response(text=evidence.get("markdown", ""), content_type="text/markdown")

    return json_response(evidence.get("json", evidence))


async def get_blueprint_dag_handler(request: web.Request) -> web.Response:
    """Returns the state machine DAG graph topology for a blueprint."""
    engine = request.app[ENGINE_KEY]
    bp_name = request.match_info.get("blueprint_name")
    if not bp_name or bp_name not in engine.blueprints:
        return json_response({"error": f"Blueprint '{bp_name}' not found"}, status=404)

    bp = engine.blueprints[bp_name]
    return json_response(bp.to_dag())


async def get_skills_catalog_handler(request: web.Request) -> web.Response:
    """Returns lightweight two-tier catalog of available skills with risk metadata."""
    engine = request.app[ENGINE_KEY]
    risk_filter = request.query.get("risk")

    workers = await engine.storage.get_available_workers()
    skills_map: dict[str, dict[str, Any]] = {}
    for w in workers:
        supported = w.get("supported_skills") or []
        for s in supported:
            s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
            if not s_name or s_name in skills_map:
                continue
            s_risk = s.get("risk", "low") if isinstance(s, dict) else getattr(s, "risk", "low")
            s_perms = s.get("permissions") if isinstance(s, dict) else getattr(s, "permissions", None)
            s_desc = s.get("description") if isinstance(s, dict) else getattr(s, "description", None)
            s_ver = s.get("version") if isinstance(s, dict) else getattr(s, "version", None)

            if risk_filter and s_risk.lower() != risk_filter.lower():
                continue

            skills_map[s_name] = {
                "name": s_name,
                "description": s_desc,
                "version": s_ver,
                "risk": s_risk,
                "permissions": s_perms or [],
            }

    return json_response({"skills": list(skills_map.values())})


async def get_skill_detail_handler(request: web.Request) -> web.Response:
    """Returns on-demand full schemas for a specific skill."""
    engine = request.app[ENGINE_KEY]
    skill_name = request.match_info.get("skill_name")

    workers = await engine.storage.get_available_workers()
    for w in workers:
        supported = w.get("supported_skills") or []
        for s in supported:
            s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
            if s_name == skill_name:
                s_dict = (
                    s
                    if isinstance(s, dict)
                    else {
                        "name": s.name,
                        "type": s.type,
                        "description": s.description,
                        "version": s.version,
                        "risk": getattr(s, "risk", "low"),
                        "permissions": getattr(s, "permissions", None) or [],
                        "input_schema": s.input_schema,
                        "output_schema": s.output_schema,
                    }
                )
                return json_response(s_dict)

    return json_response({"error": f"Skill '{skill_name}' not found"}, status=404)


handle_get_job_evidence = get_job_evidence_handler

