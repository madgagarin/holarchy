# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from dataclasses import dataclass
from unittest.mock import MagicMock

from aiohttp import web
from orjson import loads
from pytest import mark

from holarchy import Context
from holarchy.api.handlers import docs_handler, openapi_json_handler
from holarchy.api.openapi import generate_openapi_spec
from holarchy.app_keys import ENGINE_KEY
from holarchy.blueprint import Blueprint
from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.fsm import State, StatesGroup
from holarchy.storage.memory import MemoryStorage


class ProcessStates(StatesGroup):
    start_node = State()
    step_a = State()
    step_b = State()
    decide_node = State()
    branch_x = State()
    branch_y = State()
    aggregate_node = State()
    final_node = State()


@dataclass
class RequestPayload:
    account_id: str
    value: int


@dataclass
class ResponsePayload:
    status: str
    confirmation: str


def make_engine() -> OrchestratorEngine:
    storage = MemoryStorage()
    config = Config()
    return OrchestratorEngine(storage, config)


def test_positive_blueprint_dag_and_transitions_caching():
    """Verify that to_dag and _get_all_transitions return cached instances on repeated calls."""
    bp = Blueprint("caching_flow")

    @bp.start(ProcessStates.start_node)
    async def handle_start(req: RequestPayload, ctx: Context) -> State:
        return ProcessStates.step_a

    @bp.step(ProcessStates.step_a, on_success=ProcessStates.final_node)
    async def handle_step_a(req: RequestPayload, ctx: Context) -> State:
        return ProcessStates.final_node

    @bp.end(ProcessStates.final_node)
    async def handle_end(req: RequestPayload) -> ResponsePayload:
        return ResponsePayload(status="ok", confirmation="done")

    # First access builds and caches DAG and transitions
    dag1 = bp.to_dag()
    assert bp._cached_dag is not None
    dag2 = bp.to_dag()
    assert id(dag1) == id(dag2)

    tr1, _ = bp._get_all_transitions()
    assert bp._cached_transitions is not None
    tr2, _ = bp._get_all_transitions()
    assert tr1 == tr2

    sec1 = bp.get_security_metadata()
    assert bp._cached_security_metadata is not None
    sec2 = bp.get_security_metadata()
    assert id(sec1) == id(sec2)


@mark.asyncio
async def test_positive_openapi_spec_memoization_and_force_refresh():
    """Verify OpenAPI memoization across (title, version) tuples and force_refresh."""
    engine = make_engine()
    bp = Blueprint("order_service")

    @bp.start(ProcessStates.start_node)
    async def start_fn(req: RequestPayload) -> None:
        pass

    engine.register_blueprint(bp)

    # Initial generation caches under default (title, version)
    spec_v1 = generate_openapi_spec(engine, title="Api A", version="1.0.0")
    assert any(k[0] == "Api A" and k[1] == "1.0.0" for k in engine._openapi_spec_cache)
    spec_v1_cached = generate_openapi_spec(engine, title="Api A", version="1.0.0")
    assert id(spec_v1) == id(spec_v1_cached)

    # Distinct cache entry for different title or version
    spec_v2 = generate_openapi_spec(engine, title="Api B", version="2.0.0")
    assert id(spec_v1) != id(spec_v2)
    assert len(engine._openapi_spec_cache) == 2

    # Force refresh bypasses memoization
    spec_v1_refreshed = generate_openapi_spec(engine, title="Api A", version="1.0.0", force_refresh=True)
    assert id(spec_v1) != id(spec_v1_refreshed)


@mark.asyncio
async def test_positive_pre_serialized_bytes_and_docs_caching():
    """Verify openapi_json_handler serves cached bytes directly and docs_handler caches HTML."""
    engine = make_engine()
    bp = Blueprint("catalog")

    @bp.start(ProcessStates.start_node)
    async def catalog_start(req: RequestPayload) -> None:
        pass

    engine.register_blueprint(bp)

    req1 = MagicMock(spec=web.Request)
    req1.app = {ENGINE_KEY: engine}
    req1.headers = {}

    resp1 = await openapi_json_handler(req1)
    assert resp1.status == 200
    assert engine._openapi_json_bytes is not None
    assert resp1.body == engine._openapi_json_bytes

    # Second request serves pre-serialized cached bytes directly
    resp2 = await openapi_json_handler(req1)
    assert resp2.status == 200
    assert resp2.body == engine._openapi_json_bytes

    # docs_handler returns cached HTML
    docs_resp = await docs_handler(req1)
    assert docs_resp.status == 200
    assert engine._docs_html_cache is not None
    docs_resp2 = await docs_handler(req1)
    assert docs_resp2.text == docs_resp.text


def test_negative_invalidate_openapi_spec_cache_on_empty_engine():
    """Invalidating cache when already empty or uninitialized should not raise."""
    engine = make_engine()
    assert len(engine._openapi_spec_cache) == 0
    assert engine._openapi_json_bytes is None
    assert engine._docs_html_cache is None

    # Should run cleanly without raising exceptions
    engine.invalidate_openapi_spec_cache()
    engine.invalidate_openapi_spec_cache()


def test_negative_invalidate_on_bare_object():
    """Calling invalidate_openapi_spec_cache on mock or bare object without attributes."""

    class BareMock:
        pass

    bare = BareMock()
    OrchestratorEngine.invalidate_openapi_spec_cache(bare)  # type: ignore
    assert getattr(bare, "_openapi_json_bytes", None) is None


@mark.asyncio
async def test_negative_etag_mismatch_returns_200():
    """Verify mismatched ETag sends fresh 200 response with full body."""
    engine = make_engine()
    bp = Blueprint("pricing")
    bp.start(ProcessStates.start_node)(lambda: None)
    engine.register_blueprint(bp)

    req = MagicMock(spec=web.Request)
    req.app = {ENGINE_KEY: engine}
    req.headers = {"If-None-Match": '"outdated-etag-12345"'}

    resp = await openapi_json_handler(req)
    assert resp.status == 200
    parsed = loads(resp.body)
    assert "openapi" in parsed


def test_edge_case_invalidation_via_step_decorator():
    """Registering a step dynamically invalidates existing cached DAG and security metadata."""
    bp = Blueprint("dynamic_step_flow")
    bp.to_dag()
    assert bp._cached_dag is not None

    @bp.step(ProcessStates.step_a, risk="high", permissions=["perm:a"])
    async def dynamic_step(ctx: Context) -> None:
        pass

    assert bp._cached_dag is None
    assert bp._cached_security_metadata is None

    sec = bp.get_security_metadata()
    assert sec["risk"] == "high"
    assert "perm:a" in sec["permissions"]


def test_edge_case_invalidation_via_decide_decorator():
    """Registering a decider dynamically invalidates existing cached DAG and security metadata."""
    bp = Blueprint("dynamic_decide_flow")
    bp.to_dag()
    assert bp._cached_dag is not None

    @bp.decide(
        ProcessStates.decide_node,
        candidates=[ProcessStates.branch_x, ProcessStates.branch_y],
        fallback=ProcessStates.branch_x,
        risk="medium",
        permissions=["decide:perm"],
    )
    async def dynamic_decider(ctx: Context) -> State:
        return ProcessStates.branch_x

    assert bp._cached_dag is None
    assert bp._cached_security_metadata is None

    dag = bp.to_dag()
    assert bp._cached_dag is not None
    assert any("decide_node" in str(n["id"]) for n in dag["nodes"])


def test_edge_case_invalidation_via_aggregator_decorator():
    """Registering an aggregator dynamically invalidates existing cached DAG."""
    bp = Blueprint("dynamic_aggregator_flow")
    bp.to_dag()
    assert bp._cached_dag is not None

    @bp.aggregator("agg_node")
    async def dynamic_agg(ctx: Context) -> None:
        pass

    assert bp._cached_dag is None
    dag = bp.to_dag()
    assert bp._cached_dag is not None
    assert any("agg_node" in str(n["id"]) for n in dag["nodes"])


def test_edge_case_invalidation_via_end_decorator():
    """Registering an end step dynamically invalidates cached DAG and metadata."""
    bp = Blueprint("dynamic_end_flow")
    bp.to_dag()
    assert bp._cached_dag is not None

    @bp.end(ProcessStates.final_node, status="completed", risk="low")
    async def dynamic_end() -> ResponsePayload:
        return ResponsePayload(status="completed", confirmation="done")

    assert bp._cached_dag is None
    assert bp._cached_security_metadata is None


def test_edge_case_invalidation_via_add_transition():
    """Adding transitions dynamically clears cached DAG and cached transitions."""
    bp = Blueprint("transition_flow")
    bp.to_dag()
    bp._get_all_transitions()
    assert bp._cached_dag is not None
    assert bp._cached_transitions is not None

    bp.add_transition(ProcessStates.step_a, ProcessStates.step_b)
    assert bp._cached_dag is None
    assert bp._cached_transitions is None


@mark.asyncio
async def test_edge_case_register_blueprint_invalidates_engine_and_reflects_changes():
    """Registering new blueprints on OrchestratorEngine clears cached OpenAPI specs and bytes."""
    engine = make_engine()
    bp1 = Blueprint("bp_one")
    bp1.start(ProcessStates.start_node)(lambda: None)
    engine.register_blueprint(bp1)

    generate_openapi_spec(engine)
    assert len(engine._openapi_spec_cache) == 1
    engine._openapi_json_bytes = b"cached_bytes"
    engine._docs_html_cache = "cached_html"

    # Register second blueprint
    bp2 = Blueprint("bp_two")
    bp2.start(ProcessStates.start_node)(lambda: None)
    engine.register_blueprint(bp2)

    # All engine caches must be invalidated
    assert len(engine._openapi_spec_cache) == 0
    assert engine._openapi_json_bytes is None
    assert engine._docs_html_cache is None

    # Regenerating spec includes bp_two
    spec2 = generate_openapi_spec(engine)
    assert "/api/v1/jobs/start/bp_two" in spec2["paths"]
