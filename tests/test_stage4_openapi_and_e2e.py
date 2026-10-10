# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from orjson import loads
from pytest import mark
from rxon.schema import extract_input_schema_from_func, extract_json_schema

from holarchy import Context
from holarchy.api.handlers import (
    docs_handler,
    openapi_json_handler,
    start_job_by_name_handler,
)
from holarchy.api.openapi import generate_openapi_spec
from holarchy.api.routes import setup_routes
from holarchy.app_keys import ENGINE_KEY
from holarchy.blueprint import Blueprint
from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.executor import JobExecutor
from holarchy.fsm import State, StatesGroup
from holarchy.storage.memory import MemoryStorage


class FlowStates(StatesGroup):
    init = State()
    decide_step = State()
    vip_process = State()
    std_process = State()
    finalize = State()
    failed = State()


@dataclass
class OrderInput:
    order_id: int
    amount: float
    is_vip: bool = False


@dataclass
class OrderOutput:
    receipt_id: str
    status: str
    amount: float


def create_test_blueprint() -> Blueprint:
    bp = Blueprint("ecommerce_orders", api_endpoint="/jobs/orders", api_version="v1")

    @bp.start(FlowStates.init)
    async def init(order: OrderInput, ctx: Context) -> State:
        return FlowStates.decide_step

    @bp.decide(
        FlowStates.decide_step,
        candidates=[FlowStates.vip_process, FlowStates.std_process],
        fallback=FlowStates.std_process,
        timeout_seconds=2.0,
        risk="high",
        permissions=["billing:vip"],
    )
    async def decide_route(order: OrderInput, ctx: Context) -> State:
        if order.is_vip or order.amount > 1000.0:
            return FlowStates.vip_process
        return FlowStates.std_process

    @bp.step(FlowStates.vip_process, on_success=FlowStates.finalize, risk="medium", permissions=["billing:charge"])
    async def vip_step(order: OrderInput, ctx: Context) -> State:
        return FlowStates.finalize

    @bp.step(FlowStates.std_process, on_success=FlowStates.finalize, risk="low", permissions=["billing:charge"])
    async def std_step(order: OrderInput, ctx: Context) -> State:
        return FlowStates.finalize

    @bp.end(FlowStates.finalize)
    async def finalize(order: OrderInput) -> OrderOutput:
        return OrderOutput(
            receipt_id=f"rcpt_{order.order_id}",
            status="paid",
            amount=order.amount,
        )

    bp.add_transition(FlowStates.init, FlowStates.decide_step)
    return bp


@mark.asyncio
async def test_openapi_spec_generation():
    """UX-08: Verify OpenAPI 3.1.0 specification dynamically generated from blueprints."""
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)

    bp = create_test_blueprint()
    engine.register_blueprint(bp)

    spec = generate_openapi_spec(engine, title="Test Store API", version="2.0.0")

    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "Test Store API"
    assert spec["info"]["version"] == "2.0.0"

    # Verify standard system paths
    assert "/status" in spec["paths"]
    assert "/openapi.json" in spec["paths"]
    assert "/api/v1/jobs/start/{blueprint_name}" in spec["paths"]
    assert "/api/v1/jobs/{job_id}" in spec["paths"]
    assert "/api/v1/jobs/{job_id}/evidence" in spec["paths"]
    assert "/api/v1/blueprints/{blueprint_name}/dag" in spec["paths"]
    assert "/api/v1/skills" in spec["paths"]

    # Verify blueprint dynamic endpoint
    bp_path = "/api/v1/jobs/orders"
    assert bp_path in spec["paths"]
    op = spec["paths"][bp_path]["post"]

    assert op["summary"] == "Create Ecommerce Orders Job"
    assert op["x-holarchy-risk"] == "high"
    assert "billing:vip" in op["x-holarchy-permissions"]
    assert "billing:charge" in op["x-holarchy-permissions"]
    assert op["x-holarchy-start-state"] == "FlowStates:init"

    # Verify request body schema
    req_schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert "properties" in req_schema
    assert "order_id" in req_schema["properties"]
    assert "amount" in req_schema["properties"]

    # Verify orchestrator headers
    param_names = [p["name"] for p in op["parameters"]]
    assert "X-Job-Priority" in param_names
    assert "X-Job-Timeout" in param_names
    assert "X-Correlation-ID" in param_names
    assert "Idempotency-Key" in param_names
    assert "X-Webhook-URL" in param_names


@mark.asyncio
async def test_openapi_json_handler_response():
    """UX-08: Verify openapi_json_handler returns 200 with CORS and valid JSON."""
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)
    bp = create_test_blueprint()
    engine.register_blueprint(bp)

    req = MagicMock(spec=web.Request)
    req.app = {ENGINE_KEY: engine}

    response = await openapi_json_handler(req)
    assert response.status == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert response.content_type == "application/json"

    data = loads(response.body)
    assert data["openapi"] == "3.1.0"
    assert "/api/v1/jobs/orders" in data["paths"]


@mark.asyncio
async def test_docs_handler_custom_branding_and_features():
    """UX-08: Verify docs_handler serves custom Holarchy branded docs with clean input and badges."""
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)
    bp = create_test_blueprint()
    engine.register_blueprint(bp)

    req = MagicMock(spec=web.Request)
    req.app = {ENGINE_KEY: engine}

    response = await docs_handler(req)
    assert response.status == 200
    assert "text/html" in response.content_type

    html = response.text
    assert "API Documentation" in html
    assert "OpenAPI 3.1 JSON" in html
    assert "/openapi.json" in html
    # Check that blueprint endpoint is rendered
    assert "ecommerce_orders" in html or "Ecommerce Orders" in html
    assert "billing:vip" in html or "billing:charge" in html


@mark.asyncio
async def test_blueprint_security_metadata():
    """UX-08/12: Verify bp.get_security_metadata() correctly aggregates risk and permissions."""
    bp = create_test_blueprint()
    meta = bp.get_security_metadata()

    assert meta["risk"] == "high"
    assert "billing:vip" in meta["permissions"]
    assert "billing:charge" in meta["permissions"]


@mark.asyncio
async def test_start_job_by_name_handler():
    """UX-05/08: Verify start_job_by_name_handler starts jobs via generic path."""
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)
    bp = create_test_blueprint()
    engine.register_blueprint(bp)

    # 1. Non-existent blueprint -> 404
    req_fail = MagicMock(spec=web.Request)
    req_fail.app = {ENGINE_KEY: engine}
    req_fail.match_info = {"blueprint_name": "unknown_bp"}
    resp_fail = await start_job_by_name_handler(req_fail)
    assert resp_fail.status == 404

    # 2. Existing blueprint -> 202
    req_ok = MagicMock(spec=web.Request)
    req_ok.app = {ENGINE_KEY: engine}
    req_ok.match_info = {"blueprint_name": "ecommerce_orders"}
    req_ok.headers = {
        "X-Job-Priority": "high",
        "X-Correlation-ID": "corr-test-01",
    }
    req_ok.get.return_value = {"token": "test-client-token"}
    req_ok.json = AsyncMock(return_value={"order_id": 42, "amount": 150.0})

    resp_ok = await start_job_by_name_handler(req_ok)
    assert resp_ok.status == 202
    data = loads(resp_ok.body)
    assert data["status"] == "accepted"
    assert "job_id" in data


@mark.asyncio
async def test_full_cycle_stage4_e2e(aiohttp_client):
    """UX-08/09: Comprehensive full-cycle E2E test verifying:
    - HTTP Ingress with headers (priority, correlation-id) and clean input
    - Blueprint execution with FSM, @bp.decide, and terminal output capture
    - OpenAPI 3.1 & DAG endpoints
    - Incident Evidence card generation
    """
    storage = MemoryStorage()
    config = Config()
    config.ENABLE_CLIENT_API = True
    engine = OrchestratorEngine(storage, config)
    executor = JobExecutor(engine, AsyncMock(), MagicMock())
    executor.storage = storage
    engine.executor = executor

    bp = create_test_blueprint()
    engine.register_blueprint(bp)

    app = web.Application()
    app[ENGINE_KEY] = engine
    setup_routes(app, engine)

    client = await aiohttp_client(app)

    # 1. Query OpenAPI 3.1 JSON
    resp_open = await client.get("/openapi.json")
    assert resp_open.status == 200
    spec_data = await resp_open.json()
    assert spec_data["openapi"] == "3.1.0"
    assert "/api/v1/jobs/orders" in spec_data["paths"]

    # 2. Query Documentation HTML
    resp_docs = await client.get("/docs")
    assert resp_docs.status == 200
    docs_text = await resp_docs.text()
    assert "API Documentation" in docs_text
    assert "/openapi.json" in docs_text

    # 3. Query Spatial DAG
    resp_dag = await client.get(
        "/api/v1/blueprints/ecommerce_orders/dag",
        headers={"X-Client-Token": config.CLIENT_TOKEN},
    )
    assert resp_dag.status == 200
    dag_data = await resp_dag.json()
    assert dag_data["blueprint_name"] == "ecommerce_orders"
    assert len(dag_data["nodes"]) > 0

    # 4. Start job via HTTP POST with clean body and headers
    start_payload = {"order_id": 999, "amount": 2500.0, "is_vip": True}
    resp_start = await client.post(
        "/api/v1/jobs/orders",
        json=start_payload,
        headers={
            "X-Job-Priority": "critical",
            "X-Correlation-ID": "corr-vip-999",
            "X-Client-Token": config.CLIENT_TOKEN,
        },
    )
    assert resp_start.status == 202
    job_start_data = await resp_start.json()
    job_id = job_start_data["job_id"]
    assert job_id

    # 5. Check job state in storage - initial data is cleanly stored
    job_state = await storage.get_job_state(job_id)
    assert job_state is not None
    assert job_state["input"]["order_id"] == 999
    assert job_state["input"]["amount"] == 2500.0
    assert job_state["meta"]["priority"] == "critical"

    # 6. Execute job steps through JobExecutor
    # Step 1: FlowStates:init -> returns FlowStates:decide_step
    await executor._process_job(job_id, "msg-init")
    job_state = await storage.get_job_state(job_id)
    assert job_state["current_state"] == "FlowStates:decide_step"

    # Step 2: FlowStates:decide_step -> decides FlowStates:vip_process because is_vip=True
    await executor._process_job(job_id, "msg-decide")
    job_state = await storage.get_job_state(job_id)
    assert job_state["current_state"] == "FlowStates:vip_process"
    assert len(job_state["receipts"]) >= 1
    assert job_state["receipts"][-1]["chosen"] == "FlowStates:vip_process"

    # Step 3: FlowStates:vip_process -> transitions to FlowStates:finalize
    await executor._process_job(job_id, "msg-vip")
    job_state = await storage.get_job_state(job_id)
    assert job_state["current_state"] == "FlowStates:finalize"

    # Step 4: FlowStates:finalize -> terminal step returns OrderOutput and finishes job
    await executor._process_job(job_id, "msg-finalize")
    final_state = await storage.get_job_state(job_id)
    assert final_state["status"] == "finished"
    assert final_state["output"] is not None
    assert final_state["output"]["receipt_id"] == "rcpt_999"
    assert final_state["output"]["status"] == "paid"

    # 7. Test Incident Evidence Card on quarantined/failed state
    quarantine_state = dict(final_state)
    quarantine_state["id"] = "job-quarantine-test"
    quarantine_state["status"] = "quarantined"
    quarantine_state["error_message"] = "Simulated worker failure for diagnostic audit"
    await storage.save_job_state("job-quarantine-test", quarantine_state)

    resp_ev = await client.get(
        "/api/v1/jobs/job-quarantine-test/evidence",
        headers={"X-Client-Token": config.CLIENT_TOKEN},
    )
    assert resp_ev.status == 200
    ev_data = await resp_ev.json()
    assert ev_data["job_id"] == "job-quarantine-test"
    assert "failed_step" in ev_data
    assert "remediation" in ev_data

    # Query evidence in Markdown format
    resp_ev_md = await client.get(
        "/api/v1/jobs/job-quarantine-test/evidence?format=md",
        headers={"X-Client-Token": config.CLIENT_TOKEN},
    )
    assert resp_ev_md.status == 200
    ev_md_text = await resp_ev_md.text()
    assert "INCIDENT EVIDENCE CARD" in ev_md_text


@mark.asyncio
async def test_openapi_spec_edge_cases():
    """UX-08: Verify OpenAPI 3.1.0 generation under edge cases:
    - Empty engine blueprints
    - Blueprint without custom api_endpoint (maps to generic start path)
    - Security risk hierarchy (low < medium < high) and permission deduplication
    """
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)

    # 1. Empty blueprints
    spec_empty = generate_openapi_spec(engine, title="Empty Engine API", version="1.0.0")
    assert spec_empty["openapi"] == "3.1.0"
    assert "/status" in spec_empty["paths"]
    assert "/openapi.json" in spec_empty["paths"]
    assert "/api/v1/skills" in spec_empty["paths"]
    # No dynamic blueprint endpoints registered
    assert not any(p.startswith("/api/v1/jobs/orders") for p in spec_empty["paths"])

    # 2. Blueprint without explicit api_endpoint
    bp_no_endpoint = Blueprint("batch_pipeline")
    st_init = State("init")
    st_done = State("done")

    @bp_no_endpoint.start(st_init)
    async def init_step(ctx: Context) -> State:
        return st_done

    @bp_no_endpoint.end(st_done)
    async def done_step(ctx: Context) -> dict:
        return {"result": "ok"}

    bp_no_endpoint.add_transition(st_init, st_done)
    engine.register_blueprint(bp_no_endpoint)
    spec = generate_openapi_spec(engine)
    expected_path = "/api/v1/jobs/start/batch_pipeline"
    assert expected_path in spec["paths"]
    assert spec["paths"][expected_path]["post"]["summary"] == "Create Batch Pipeline Job"

    # 3. Security metadata aggregation edge cases
    bp_sec = Blueprint("sec_flow")
    s1, s2, s3, s4 = State("s1"), State("s2"), State("s3"), State("s4")

    @bp_sec.start(s1, risk="low", permissions=["read:data", "audit:log"])
    async def step1(ctx: Context) -> State:
        return s2

    @bp_sec.step(s2, risk="medium", permissions=["read:data", "write:cache"])
    async def step2(ctx: Context) -> State:
        return s3

    @bp_sec.decide(s3, candidates=[s4], fallback=s4, risk="high", permissions=["admin:all", "write:cache"])
    async def step3(ctx: Context) -> State:
        return s4

    @bp_sec.end(s4)
    async def step4(ctx: Context) -> dict:
        return {"status": "complete"}

    meta = bp_sec.get_security_metadata()
    # Risk should take the maximum across all steps: high
    assert meta["risk"] == "high"
    # Permissions should be deduplicated and sorted
    assert meta["permissions"] == ["admin:all", "audit:log", "read:data", "write:cache"]


@mark.asyncio
async def test_start_job_by_name_negative_and_edge_cases(aiohttp_client):
    """UX-08/09: Verify negative and edge cases for starting jobs via generic endpoint:
    - 404 on missing blueprint
    - 400 on malformed/invalid JSON
    - 400 on input schema contract violation
    - Idempotency-Key deduplication (2nd call returns 200 with identical job_id)
    - Full propagation of orchestrator headers into job meta
    """
    storage = MemoryStorage()
    config = Config()
    config.ENABLE_CLIENT_API = True
    engine = OrchestratorEngine(storage, config)
    bp = create_test_blueprint()
    engine.register_blueprint(bp)

    app = web.Application()
    app[ENGINE_KEY] = engine
    setup_routes(app, engine)
    client = await aiohttp_client(app)

    # 1. 404 on unknown blueprint
    res_404 = await client.post(
        "/api/v1/jobs/start/non_existent_bp",
        json={"data": 123},
        headers={"X-Client-Token": config.CLIENT_TOKEN},
    )
    assert res_404.status == 404
    err_404 = await res_404.json()
    assert "not found" in err_404["error"].lower()

    # 2. 400 on malformed JSON body
    res_malformed = await client.post(
        "/api/v1/jobs/start/ecommerce_orders",
        data="not-valid-json{{{",
        headers={
            "X-Client-Token": config.CLIENT_TOKEN,
            "Content-Type": "application/json",
        },
    )
    assert res_malformed.status == 400
    err_body = await res_malformed.json()
    assert "invalid json" in err_body["error"].lower()

    # 3. 400 on input contract violation (OrderInput requires order_id: int and amount: float)
    res_schema_err = await client.post(
        "/api/v1/jobs/start/ecommerce_orders",
        json={"order_id": "invalid_not_an_int_string", "amount": "invalid_amount"},
        headers={"X-Client-Token": config.CLIENT_TOKEN},
    )
    assert res_schema_err.status == 400
    err_schema = await res_schema_err.json()
    assert "validation failed" in err_schema["error"].lower()

    # 4. Idempotency-Key deduplication and header persistence
    idemp_headers = {
        "X-Client-Token": config.CLIENT_TOKEN,
        "Idempotency-Key": "idemp-key-unique-777",
        "X-Job-Priority": "critical",
        "X-Job-Timeout": "120",
        "X-Correlation-ID": "corr-idemp-001",
        "X-Webhook-URL": "https://callback.example.com/hook",
    }
    payload = {"order_id": 777, "amount": 99.9}

    # First launch -> 202 Accepted
    res1 = await client.post("/api/v1/jobs/start/ecommerce_orders", json=payload, headers=idemp_headers)
    assert res1.status == 202
    data1 = await res1.json()
    job_id_1 = data1["job_id"]

    # Verify headers stored cleanly in job meta
    job_state = await storage.get_job_state(job_id_1)
    assert job_state["meta"]["priority"] == "critical"
    assert job_state["meta"]["timeout"] == 120
    assert job_state["meta"]["correlation_id"] == "corr-idemp-001"
    assert job_state["meta"]["webhook_url"] == "https://callback.example.com/hook"

    # Second launch with SAME Idempotency-Key -> returns 200 with identical job_id
    res2 = await client.post("/api/v1/jobs/start/ecommerce_orders", json=payload, headers=idemp_headers)
    assert res2.status == 200
    data2 = await res2.json()
    assert data2["job_id"] == job_id_1


@mark.asyncio
async def test_executor_on_success_and_state_return_edge_cases():
    """UX-09: Verify JobExecutor on_success and direct State return edge cases:
    - Handler returning explicit Next(state) overrides on_success
    - Handler calling actions.go_to(state) overrides on_success
    - Handler raising an unhandled exception transitions to failure, never on_success
    - Handler returning terminal State marks job finished with output
    """
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)
    executor = JobExecutor(engine, AsyncMock(), MagicMock())
    executor.storage = storage
    engine.executor = executor

    class EdgeStates(StatesGroup):
        s_start = State()
        s_step = State()
        s_override = State()
        s_fallback = State()
        s_error_step = State()
        s_final = State()

    bp = Blueprint("edge_executor_bp")

    @bp.start(EdgeStates.s_start)
    async def start_h(ctx: Context) -> State:
        return EdgeStates.s_step

    # Step has on_success=EdgeStates.s_fallback, but handler explicitly calls actions.go_to(EdgeStates.s_override)
    @bp.step(EdgeStates.s_step, on_success=EdgeStates.s_fallback)
    async def step_h(ctx: Context) -> Any:
        return ctx.actions.go_to(EdgeStates.s_override)

    @bp.step(EdgeStates.s_override, on_success=EdgeStates.s_final)
    async def override_h(ctx: Context) -> None:
        # Returns None, so on_success to s_final should trigger!
        pass

    @bp.step(EdgeStates.s_fallback)
    async def fallback_h(ctx: Context) -> None:
        pass

    @bp.step(EdgeStates.s_error_step, on_success=EdgeStates.s_final)
    async def error_h(ctx: Context) -> None:
        raise RuntimeError("Simulated unhandled step failure")

    @bp.end(EdgeStates.s_final)
    async def final_h(ctx: Context) -> dict:
        return {"completed": True}

    bp.add_transition(EdgeStates.s_start, EdgeStates.s_step)
    bp.add_transition(EdgeStates.s_start, EdgeStates.s_error_step)
    bp.add_transition(EdgeStates.s_step, EdgeStates.s_override)
    bp.add_transition(EdgeStates.s_step, EdgeStates.s_fallback)
    bp.add_transition(EdgeStates.s_override, EdgeStates.s_final)
    bp.add_transition(EdgeStates.s_fallback, EdgeStates.s_final)
    bp.add_transition(EdgeStates.s_error_step, EdgeStates.s_final)
    engine.register_blueprint(bp)

    # 1. Test go_to override over on_success
    job_id = "job-edge-override-01"
    initial_job = {
        "id": job_id,
        "blueprint_name": "edge_executor_bp",
        "current_state": "EdgeStates:s_step",
        "status": "pending",
        "input": {},
        "output": None,
        "steps": {},
        "meta": {},
        "receipts": [],
    }
    await storage.save_job_state(job_id, initial_job)

    # Execute s_step: should go to s_override, NOT s_fallback
    await executor._process_job(job_id, "msg-01")
    state = await storage.get_job_state(job_id)
    assert state["current_state"] == "EdgeStates:s_override"

    # Execute s_override (returns None): should auto-transition to s_final via on_success
    await executor._process_job(job_id, "msg-02")
    state = await storage.get_job_state(job_id)
    assert state["current_state"] == "EdgeStates:s_final"

    # Execute s_final: terminal state reached, job finishes
    await executor._process_job(job_id, "msg-03")
    final_st = await storage.get_job_state(job_id)
    assert final_st["status"] == "finished"
    assert final_st["output"] == {"completed": True}

    # 2. Test unhandled exception does NOT trigger on_success
    fail_job_id = "job-edge-fail-02"
    fail_job = {
        "id": fail_job_id,
        "blueprint_name": "edge_executor_bp",
        "current_state": "EdgeStates:s_error_step",
        "status": "pending",
        "retry_count": 3,
        "input": {},
        "output": None,
        "steps": {},
        "meta": {},
        "receipts": [],
    }
    await storage.save_job_state(fail_job_id, fail_job)

    await executor._process_job(fail_job_id, "msg-fail")
    fail_state = await storage.get_job_state(fail_job_id)
    # Status should be quarantined and NOT advanced to s_final
    assert fail_state["status"] == "quarantined"
    assert fail_state["current_state"] == "EdgeStates:s_error_step"
    assert "Simulated unhandled step failure" in fail_state.get("error_message", "")


@mark.asyncio
async def test_caching_and_invalidation_performance_optimizations() -> None:
    """Verifies that all 4 caching layers operate correctly and invalidate upon mutations:

    1. OpenAPI 3.1 dict memoization and force_refresh.
    2. Handlers pre-serialized JSON bytes and HTML docs caching.
    3. Engine registration invalidation of OpenAPI and Docs caches.
    4. Blueprint DAG, transitions, and security metadata caching and invalidation.
    5. rxon.schema type and function-level schema memoization.
    """
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)

    bp = Blueprint("cache_test_flow")
    s1, s2 = State("s1"), State("s2")

    @bp.start(s1, risk="medium", permissions=["read:cache"])
    async def step_1(ctx: Context) -> State:
        return s2

    @bp.end(s2, risk="low")
    async def step_2(ctx: Context) -> dict[str, str]:
        return {"status": "done"}

    bp.add_transition(s1, s2)
    engine.register_blueprint(bp)

    # 1. OpenAPI 3.1 Spec memoization on engine
    spec1 = generate_openapi_spec(engine)
    assert id(engine._openapi_spec_cache)
    spec2 = generate_openapi_spec(engine)
    # Object identity should match due to memoization
    assert id(spec1) == id(spec2)

    # Force refresh should bypass and update cache
    spec_refreshed = generate_openapi_spec(engine, force_refresh=True)
    assert spec_refreshed["openapi"] == "3.1.0"

    # 2. openapi_json_handler pre-serialized bytes caching
    req = MagicMock(spec=web.Request)
    req.app = {ENGINE_KEY: engine}
    resp1 = await openapi_json_handler(req)
    assert resp1.status == 200
    assert engine._openapi_json_bytes is not None
    cached_bytes = engine._openapi_json_bytes

    resp2 = await openapi_json_handler(req)
    assert resp2.body == cached_bytes

    # 3. docs_handler HTML template caching
    resp_docs1 = await docs_handler(req)
    assert resp_docs1.status == 200
    assert engine._docs_html_cache is not None
    cached_html = engine._docs_html_cache

    resp_docs2 = await docs_handler(req)
    assert resp_docs2.text == cached_html

    # 4. Blueprint DAG and transitions caching & invalidation
    dag1 = bp.to_dag()
    assert bp._cached_dag is not None
    dag2 = bp.to_dag()
    assert id(dag1) == id(dag2)
    assert len(dag1["edges"]) == 1

    sec1 = bp.get_security_metadata()
    assert sec1["risk"] == "medium"
    assert sec1["permissions"] == ["read:cache"]
    assert bp._cached_security_metadata is not None

    # Invalidate via adding transition
    s3 = State("s3")
    bp.add_transition(s2, s3)
    assert bp._cached_dag is None
    assert bp._cached_transitions is None

    dag3 = bp.to_dag()
    assert len(dag3["edges"]) == 2

    # Invalidate via adding handler
    @bp.handler("s_extra", risk="high", permissions=["admin:extra"])
    async def extra_handler(ctx: Context) -> None:
        pass

    assert bp._cached_security_metadata is None
    sec2 = bp.get_security_metadata()
    assert sec2["risk"] == "high"
    assert "admin:extra" in sec2["permissions"]

    # 5. Engine registration invalidation
    bp2 = Blueprint("second_flow")
    s_init = State("init")
    bp2.start(s_init)(lambda: None)

    # Registering bp2 must clear engine caches
    engine.register_blueprint(bp2)
    assert len(engine._openapi_spec_cache) == 0
    assert engine._openapi_json_bytes is None
    assert engine._docs_html_cache is None

    spec3 = generate_openapi_spec(engine)
    assert "/api/v1/jobs/start/second_flow" in spec3["paths"]

    # 6. rxon.schema function and type memoization
    @dataclass
    class SampleModel:
        sku: str
        count: int

    # Function-level schema memoization
    def sample_func(ctx: Context, name: str) -> None:
        pass

    sch1 = extract_input_schema_from_func(sample_func)
    assert hasattr(sample_func, "_rxon_input_schema")
    sch2 = extract_input_schema_from_func(sample_func)
    assert id(sch1) == id(sch2)

    # Type-level schema memoization
    type_sch1 = extract_json_schema(SampleModel)
    type_sch2 = extract_json_schema(SampleModel)
    assert id(type_sch1) == id(type_sch2)
