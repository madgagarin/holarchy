# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from aiohttp import web
from orjson import loads as orjson_loads
from pytest import fixture, mark, raises

from holarchy.api.handlers import create_job_handler_factory, get_job_status_handler
from holarchy.app_keys import CLIENT_CONFIG_KEY, ENGINE_KEY
from holarchy.blueprint import Blueprint
from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage
from holarchy.storage.redis import RedisStorage


@fixture
def config():
    cfg = Config()
    cfg.DETAILED_API_RESPONSES = True
    return cfg


@fixture
def storage():
    return MemoryStorage()


@fixture
def engine(storage, config):
    eng = OrchestratorEngine(storage, config)
    eng.ws_manager = AsyncMock()
    eng.webhook_sender = AsyncMock()
    return eng


def make_request(
    engine,
    method="POST",
    json_body=None,
    headers=None,
    token="client-token-1",
    path_params=None,
    query=None,
):
    req = MagicMock(spec=web.Request)
    req.method = method
    req.app = {ENGINE_KEY: engine}
    req.headers = headers or {}
    req.match_info = path_params or {}
    req.query = query or {}
    req.json = AsyncMock(return_value=json_body if json_body is not None else {})

    client_cfg = {"token": token, "client_id": f"id-{token}", "params": {"tier": "gold"}}
    req.get.side_effect = lambda k, default=None: client_cfg if k in (CLIENT_CONFIG_KEY, "client_config") else default
    return req


@mark.asyncio
async def test_headers_extraction_and_meta(engine):
    bp = Blueprint("order_flow")

    @bp.start("init", is_end=True)
    async def init(actions):
        actions.save_result({"status": "ok"})

    engine.register_blueprint(bp)
    handler = create_job_handler_factory(bp)

    req = make_request(
        engine,
        headers={
            "X-Webhook-URL": "https://callback.example.com/hook",
            "X-Job-Timeout": "120",
            "X-Job-Priority": "high",
            "X-Correlation-ID": "corr-uuid-12345",
        },
        json_body={"order_id": 999},
    )

    resp = await handler(req)
    assert resp.status == 202
    data = orjson_loads(resp.body)
    assert data["status"] == "accepted"
    assert "job_id" in data
    assert "id" in data
    assert data["job_id"] == data["id"]

    job_id = data["job_id"]
    job_state = await engine.storage.get_job_state(job_id)
    assert job_state is not None
    assert job_state["input"] == {"order_id": 999}
    assert job_state["meta"]["priority"] == "high"
    assert job_state["meta"]["timeout"] == 120
    assert job_state["meta"]["webhook_url"] == "https://callback.example.com/hook"
    assert job_state["meta"]["correlation_id"] == "corr-uuid-12345"
    assert job_state["meta"]["headers"]["X-Correlation-ID"] == "corr-uuid-12345"


@mark.asyncio
async def test_idempotency_key_prevents_duplicate_jobs(engine):
    bp = Blueprint("payment_flow")

    @bp.start("pay", is_end=True)
    async def pay(actions):
        actions.save_result({"paid": True})

    engine.register_blueprint(bp)
    handler = create_job_handler_factory(bp)

    # 1. First request with Idempotency-Key
    req1 = make_request(
        engine,
        headers={"Idempotency-Key": "idemp-key-abc-123"},
        json_body={"amount": 500},
        token="client-A",
    )
    resp1 = await handler(req1)
    assert resp1.status == 202
    data1 = orjson_loads(resp1.body)
    job_id_1 = data1["job_id"]
    assert job_id_1

    # 2. Second request with same key and same client token -> returns status 200 and SAME job_id
    req2 = make_request(
        engine,
        headers={"Idempotency-Key": "idemp-key-abc-123"},
        json_body={"amount": 500},
        token="client-A",
    )
    resp2 = await handler(req2)
    assert resp2.status == 200
    data2 = orjson_loads(resp2.body)
    assert data2["job_id"] == job_id_1
    assert data2["id"] == job_id_1
    assert data2["status"] == "accepted"

    # 3. Third request with different client token -> creates NEW job (isolation)
    req3 = make_request(
        engine,
        headers={"Idempotency-Key": "idemp-key-abc-123"},
        json_body={"amount": 500},
        token="client-B",
    )
    resp3 = await handler(req3)
    assert resp3.status == 202
    data3 = orjson_loads(resp3.body)
    assert data3["job_id"] != job_id_1

    # 4. Fourth request with different Idempotency-Key -> creates NEW job
    req4 = make_request(
        engine,
        headers={"Idempotency-Key": "idemp-key-different"},
        json_body={"amount": 500},
        token="client-A",
    )
    resp4 = await handler(req4)
    assert resp4.status == 202
    data4 = orjson_loads(resp4.body)
    assert data4["job_id"] != job_id_1


@mark.asyncio
async def test_clean_request_body_input_variations(engine):
    bp = Blueprint("variations_flow")

    @bp.start("start", is_end=True)
    async def start(actions):
        pass

    engine.register_blueprint(bp)
    handler = create_job_handler_factory(bp)

    # A: Flat body becomes input
    req_flat = make_request(engine, json_body={"user": "alice", "score": 100})
    resp_flat = await handler(req_flat)
    job_id = orjson_loads(resp_flat.body)["job_id"]
    state = await engine.storage.get_job_state(job_id)
    assert state["input"] == {"user": "alice", "score": 100}

    # B: Explicit "input" key
    req_input = make_request(engine, json_body={"input": {"nested": "value"}})
    resp_input = await handler(req_input)
    job_id = orjson_loads(resp_input.body)["job_id"]
    state = await engine.storage.get_job_state(job_id)
    assert state["input"] == {"nested": "value"}

    # C: Explicit "input" with multiple fields
    req_multi = make_request(engine, json_body={"input": {"order_id": 1, "dry_run": True}})
    resp_multi = await handler(req_multi)
    job_id = orjson_loads(resp_multi.body)["job_id"]
    state = await engine.storage.get_job_state(job_id)
    assert state["input"] == {"order_id": 1, "dry_run": True}
    assert "initial_data" not in state

    # D: Empty body
    req_empty = make_request(engine, json_body={})
    resp_empty = await handler(req_empty)
    job_id = orjson_loads(resp_empty.body)["job_id"]
    state = await engine.storage.get_job_state(job_id)
    assert state["input"] == {}


@mark.asyncio
async def test_get_job_status_5_zones_response(engine):
    job_id = f"job-{uuid4()}"
    job_state = {
        "id": job_id,
        "blueprint_name": "checkout_bp",
        "current_state": "done",
        "status": "finished",
        "input": {"items": ["item1", "item2"]},
        "output": {"total": 42.0},
        "steps": {"verify": {"ok": True}},
        "history": [{"step": "verify"}],
        "params": {"discount": 0.1},
        "meta": {"priority": "normal", "correlation_id": "c-99"},
        "client_config": {"token": "client-token-1"},
    }
    await engine.storage.save_job_state(job_id, job_state)

    # Detailed response returns 5 zones
    req = make_request(engine, method="GET", token="client-token-1", path_params={"job_id": job_id})
    resp = await get_job_status_handler(req)
    assert resp.status == 200
    data = orjson_loads(resp.body)

    assert data["id"] == job_id
    assert data["blueprint"] == "checkout_bp"
    assert data["status"] == "finished"
    assert data["input"] == {"items": ["item1", "item2"]}
    assert data["output"] == {"total": 42.0}
    assert data["steps"] == {"verify": {"ok": True}}
    assert data["history"] == [{"step": "verify"}]
    assert data["params"] == {"discount": 0.1}
    assert data["meta"]["correlation_id"] == "c-99"

    # Specific fields filtering
    req_filtered = make_request(
        engine,
        method="GET",
        token="client-token-1",
        path_params={"job_id": job_id},
        query={"fields": "id,blueprint,output,meta"},
    )
    resp_filtered = await get_job_status_handler(req_filtered)
    data_filtered = orjson_loads(resp_filtered.body)
    assert set(data_filtered.keys()) == {"id", "blueprint", "output", "meta"}
    assert data_filtered["output"] == {"total": 42.0}


@mark.asyncio
async def test_idempotency_purged_job_creates_new(engine):
    bp = Blueprint("purge_test_bp")

    @bp.start("start", is_end=True)
    async def start(actions):
        pass

    engine.register_blueprint(bp)
    handler = create_job_handler_factory(bp)

    # 1. Simulate an idempotency key referencing a non-existent / deleted job
    await engine.storage.set_idempotent_job_id("client-A", "idemp-purged", "dead-job-id")

    req = make_request(
        engine,
        headers={"Idempotency-Key": "idemp-purged"},
        json_body={"amount": 100},
        token="client-A",
    )
    resp = await handler(req)
    # Must create a fresh job with 202 instead of returning 200 with dead-job-id
    assert resp.status == 202
    data = orjson_loads(resp.body)
    new_job_id = data["job_id"]
    assert new_job_id != "dead-job-id"

    # Verify idempotency key was updated
    current_key_val = await engine.storage.get_idempotent_job_id("client-A", "idemp-purged")
    assert current_key_val == new_job_id


@mark.asyncio
async def test_invalid_header_types_graceful_fallback(engine):
    bp = Blueprint("malformed_headers_bp")

    @bp.start("step", is_end=True)
    async def step(actions):
        pass

    engine.register_blueprint(bp)
    handler = create_job_handler_factory(bp)

    req = make_request(
        engine,
        headers={
            "X-Job-Timeout": "not-an-integer",
            "X-Job-Priority": "",
            "X-Correlation-ID": "",
        },
        json_body={"foo": "bar"},
    )
    resp = await handler(req)
    assert resp.status == 202
    data = orjson_loads(resp.body)
    job_id = data["job_id"]

    job_state = await engine.storage.get_job_state(job_id)
    assert job_state["input"] == {"foo": "bar"}
    # Priority falls back to normal
    assert job_state["meta"]["priority"] == "normal"


@mark.asyncio
async def test_job_status_not_found_and_isolation(engine):
    # 1. Non-existent job
    req_not_found = make_request(
        engine,
        method="GET",
        token="client-1",
        path_params={"job_id": "non-existent-uuid"},
    )
    resp_not_found = await get_job_status_handler(req_not_found)
    assert resp_not_found.status == 404

    # 2. Client token mismatch
    job_id = f"job-{uuid4()}"
    await engine.storage.save_job_state(
        job_id,
        {
            "id": job_id,
            "blueprint_name": "isolated_bp",
            "status": "running",
            "client_config": {"token": "owner-client-token"},
        },
    )
    req_other_client = make_request(
        engine,
        method="GET",
        token="attacker-token",
        path_params={"job_id": job_id},
    )
    with raises(web.HTTPForbidden):
        await get_job_status_handler(req_other_client)


@mark.asyncio
async def test_redis_storage_idempotency_unit():
    mock_redis = AsyncMock()
    storage = RedisStorage(mock_redis)

    # get_idempotent_job_id
    mock_redis.get.return_value = b"job-12345"
    res = await storage.get_idempotent_job_id("tok", "key1")
    assert res == "job-12345"
    mock_redis.get.assert_called_with("orchestrator:idempotency:tok:key1")

    # get_idempotent_job_id None
    mock_redis.get.return_value = None
    res_none = await storage.get_idempotent_job_id("tok", "key2")
    assert res_none is None

    # set_idempotent_job_id
    await storage.set_idempotent_job_id("tok", "key1", "job-999", ttl=3600)
    mock_redis.set.assert_called_with("orchestrator:idempotency:tok:key1", "job-999", ex=3600)
