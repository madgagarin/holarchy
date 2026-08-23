# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from pytest import mark

from holarchy.api.handlers import _filter_job_state, create_job_handler_factory
from holarchy.app_keys import ENGINE_KEY
from holarchy.blueprint import Blueprint


@mark.asyncio
async def test_api_policy_parsing_happy_path(aiohttp_client):
    engine = MagicMock()
    engine.config.MAX_POLICY_SIZE_BYTES = 4096
    engine.config.MAX_TRANSITIONS_PER_JOB = 100
    engine.blueprint_contracts = {}
    engine.storage.save_job_state = AsyncMock()
    engine.storage.enqueue_job = AsyncMock()
    engine.history_storage.log_job_event = AsyncMock()

    bp = Blueprint("test_bp")

    @bp.handler("start", is_start=True, is_end=True)
    async def start():
        pass

    bp.validate()
    handler = create_job_handler_factory(bp)

    app = web.Application()
    app[ENGINE_KEY] = engine
    app.router.add_post("/jobs", handler)

    client = await aiohttp_client(app)

    valid_payload = {
        "initial_data": {"x": 1},
        "policy": {"allowed_skills": ["skill_a", "skill_b"], "rate_limit": 10},
        "max_transitions": 50,
    }
    resp = await client.post("/jobs", json=valid_payload)
    assert resp.status == 202
    body = await resp.json()
    assert body["status"] == "accepted"

    # Verify that engine.storage.save_job_state received policy and max_transitions
    saved_state = engine.storage.save_job_state.call_args[0][1]
    assert saved_state["policy"] == {"allowed_skills": ["skill_a", "skill_b"], "rate_limit": 10}
    assert saved_state["max_transitions"] == 50


@mark.asyncio
async def test_api_policy_parsing_invalid_policy_type(aiohttp_client):
    engine = MagicMock()
    engine.blueprint_contracts = {}
    engine.config.MAX_POLICY_SIZE_BYTES = 4096
    engine.config.MAX_TRANSITIONS_PER_JOB = 100
    engine.storage.save_job_state = AsyncMock()
    engine.storage.enqueue_job = AsyncMock()
    engine.history_storage.log_job_event = AsyncMock()
    engine.metrics = MagicMock()

    bp = Blueprint("test_bp")

    @bp.handler("start", is_start=True, is_end=True)
    async def start():
        pass

    bp.validate()

    handler = create_job_handler_factory(bp)
    app = web.Application()
    app[ENGINE_KEY] = engine
    app.router.add_post("/jobs", handler)

    client = await aiohttp_client(app)

    # Non-dict policy
    resp = await client.post("/jobs", json={"policy": "invalid_string_policy"})
    assert resp.status == 400
    body = await resp.json()
    assert "'policy' must be a dictionary" in body["error"]


@mark.asyncio
async def test_api_policy_parsing_invalid_allowed_skills(aiohttp_client):
    engine = MagicMock()
    engine.blueprint_contracts = {}
    engine.config.MAX_POLICY_SIZE_BYTES = 4096
    engine.config.MAX_TRANSITIONS_PER_JOB = 100
    engine.storage.save_job_state = AsyncMock()
    engine.storage.enqueue_job = AsyncMock()
    engine.history_storage.log_job_event = AsyncMock()
    engine.metrics = MagicMock()

    bp = Blueprint("test_bp")

    @bp.handler("start", is_start=True, is_end=True)
    async def start():
        pass

    bp.validate()

    handler = create_job_handler_factory(bp)
    app = web.Application()
    app[ENGINE_KEY] = engine
    app.router.add_post("/jobs", handler)

    client = await aiohttp_client(app)

    # Allowed skills as empty list or non-strings
    resp = await client.post("/jobs", json={"policy": {"allowed_skills": []}})
    assert resp.status == 400
    body = await resp.json()
    assert "'policy.allowed_skills' must be a non-empty list of strings" in body["error"]

    resp2 = await client.post("/jobs", json={"policy": {"allowed_skills": [123, 456]}})
    assert resp2.status == 400


@mark.asyncio
async def test_api_policy_parsing_oversized_policy(aiohttp_client):
    engine = MagicMock()
    engine.blueprint_contracts = {}
    engine.config.MAX_POLICY_SIZE_BYTES = 50  # Small threshold
    engine.config.MAX_TRANSITIONS_PER_JOB = 100
    engine.storage.save_job_state = AsyncMock()
    engine.storage.enqueue_job = AsyncMock()
    engine.history_storage.log_job_event = AsyncMock()
    engine.metrics = MagicMock()

    bp = Blueprint("test_bp")

    @bp.handler("start", is_start=True, is_end=True)
    async def start():
        pass

    bp.validate()

    handler = create_job_handler_factory(bp)
    app = web.Application()
    app[ENGINE_KEY] = engine
    app.router.add_post("/jobs", handler)

    client = await aiohttp_client(app)

    large_policy = {"allowed_skills": ["a" * 100]}
    resp = await client.post("/jobs", json={"policy": large_policy})
    assert resp.status == 400
    body = await resp.json()
    assert "Policy size exceeds MAX_POLICY_SIZE_BYTES limit" in body["error"]


@mark.asyncio
async def test_api_policy_parsing_invalid_max_transitions(aiohttp_client):
    engine = MagicMock()
    engine.blueprint_contracts = {}
    engine.config.MAX_POLICY_SIZE_BYTES = 4096
    engine.config.MAX_TRANSITIONS_PER_JOB = 100
    engine.storage.save_job_state = AsyncMock()
    engine.storage.enqueue_job = AsyncMock()
    engine.history_storage.log_job_event = AsyncMock()
    engine.metrics = MagicMock()

    bp = Blueprint("test_bp")

    @bp.handler("start", is_start=True, is_end=True)
    async def start():
        pass

    bp.validate()

    handler = create_job_handler_factory(bp)
    app = web.Application()
    app[ENGINE_KEY] = engine
    app.router.add_post("/jobs", handler)

    client = await aiohttp_client(app)

    # Exceeds max_transitions limit
    resp = await client.post("/jobs", json={"max_transitions": 500})
    assert resp.status == 400
    body = await resp.json()
    assert "'max_transitions' must be an integer between 1 and 100" in body["error"]

    # 0 or negative
    resp_zero = await client.post("/jobs", json={"max_transitions": 0})
    assert resp_zero.status == 400

    resp_neg = await client.post("/jobs", json={"max_transitions": -5})
    assert resp_neg.status == 400

    # Non-integer (float, string, bool)
    resp_float = await client.post("/jobs", json={"max_transitions": 10.5})
    assert resp_float.status == 400

    resp_str = await client.post("/jobs", json={"max_transitions": "10"})
    assert resp_str.status == 400

    # Boundary Min (1) -> Accepted
    resp_min = await client.post("/jobs", json={"max_transitions": 1})
    assert resp_min.status == 202

    # Boundary Max (100) -> Accepted
    resp_max = await client.post("/jobs", json={"max_transitions": 100})
    assert resp_max.status == 202


def test_filter_job_state_policy_and_limits():
    state = {
        "id": "j1",
        "status": "running",
        "policy": {"allowed_skills": ["s1"]},
        "step": 5,
        "depth": 1,
        "max_transitions": 20,
    }

    # Compact mode: includes step, depth, max_transitions
    filtered_compact = _filter_job_state(state, detailed_allowed=False)
    assert filtered_compact["id"] == "j1"
    assert filtered_compact["step"] == 5
    assert filtered_compact["depth"] == 1
    assert filtered_compact["max_transitions"] == 20
    assert "policy" not in filtered_compact

    # Detailed mode: includes policy
    filtered_detailed = _filter_job_state(state, detailed_allowed=True)
    assert filtered_detailed["policy"] == {"allowed_skills": ["s1"]}
