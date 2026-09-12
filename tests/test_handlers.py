# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.web import HTTPUnauthorized
from orjson import loads as orjson_loads
from pytest import fixture, mark, raises
from rxon.constants import JOB_STATUS_FINISHED, JOB_STATUS_WAITING_FOR_HUMAN

from holarchy.api.handlers import (
    cancel_job_handler,
    docs_handler,
    get_blueprint_graph_handler,
    get_job_status_handler,
    get_jobs_handler,
    get_worker_catalog_handler,
    human_approval_webhook_handler,
)
from holarchy.app_keys import ENGINE_KEY
from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage


@fixture
def config():
    return Config()


@fixture
def storage():
    return MemoryStorage()


@fixture
def engine(storage, config):
    engine = OrchestratorEngine(storage, config)
    # Mock components that are usually set up in on_startup
    engine.ws_manager = AsyncMock()
    engine.ws_manager.register = AsyncMock()
    engine.ws_manager.unregister = AsyncMock()
    engine.ws_manager.handle_message = AsyncMock()
    engine.ws_manager.send_command = AsyncMock(return_value=True)

    engine.webhook_sender = AsyncMock()
    engine.webhook_sender.send = AsyncMock()
    engine.webhook_sender.start = MagicMock()

    return engine


@fixture
def request_mock(engine):
    req = MagicMock(spec=web.Request)
    req.json = AsyncMock(return_value={})

    # app needs to be accessible via []
    app_mock = MagicMock()
    app_dict = {
        ENGINE_KEY: engine,
    }
    app_mock.__getitem__.side_effect = app_dict.__getitem__
    app_mock.get.side_effect = app_dict.get
    req.app = app_mock

    req.headers = {}
    # Authenticate the request
    token = "test-token"
    req.get.return_value = {"token": token, "client_id": "test-client"}

    # Use a dictionary to avoid lazy behavior
    req.match_info = {}
    req.query = {}
    req.can_read_body = True
    return req


@mark.asyncio
async def test_cancel_job_not_found(engine, request_mock):
    request_mock.match_info = {"job_id": "non-existent-job"}
    response = await cancel_job_handler(request_mock)
    assert response.status == 404


@mark.asyncio
async def test_cancel_job_wrong_state(engine, request_mock):
    job_id = "job-in-wrong-state"
    token = request_mock.get("client_config")["token"]
    await engine.storage.save_job_state(job_id, {"id": job_id, "status": "running", "client_config": {"token": token}})
    request_mock.match_info = {"job_id": job_id}
    response = await cancel_job_handler(request_mock)
    assert response.status == 200


@mark.asyncio
async def test_cancel_job_no_worker_id(engine, request_mock):
    job_id = "job-no-worker-id"
    token = request_mock.get("client_config")["token"]
    await engine.storage.save_job_state(
        job_id, {"id": job_id, "status": "waiting_for_worker", "client_config": {"token": token}}
    )
    request_mock.match_info = {"job_id": job_id}
    response = await cancel_job_handler(request_mock)
    assert response.status == 200


@mark.asyncio
async def test_cancel_job_no_task_id(engine, request_mock):
    job_id = "job-no-task-id"
    token = request_mock.get("client_config")["token"]
    await engine.storage.save_job_state(
        job_id,
        {"id": job_id, "status": "waiting_for_worker", "task_worker_id": "worker-1", "client_config": {"token": token}},
    )
    request_mock.match_info = {"job_id": job_id}
    response = await cancel_job_handler(request_mock)
    assert response.status == 200


@mark.asyncio
async def test_cancel_job_ws_fails(engine, request_mock, caplog):
    job_id = "job-ws-fails"
    worker_id = "worker-1"
    task_id = "task-1"
    token = request_mock.get("client_config")["token"]
    await engine.storage.save_job_state(
        job_id,
        {
            "id": job_id,
            "status": "waiting_for_worker",
            "task_worker_id": worker_id,
            "current_task_id": task_id,
            "client_config": {"token": token},
        },
    )
    await engine.storage.register_worker(worker_id, {"worker_id": worker_id, "capabilities": {"websockets": True}}, 60)

    engine.ws_manager.send_command.return_value = False

    request_mock.match_info = {"job_id": job_id}
    response = await cancel_job_handler(request_mock)
    assert response.status == 200
    assert "Failed to send cancellation command via WebSocket" in caplog.text


@mark.asyncio
async def test_get_blueprint_graph_not_found(engine, request_mock):
    request_mock.match_info = {"blueprint_name": "non-existent-blueprint"}
    response = await get_blueprint_graph_handler(request_mock)
    assert response.status == 404


@mark.asyncio
async def test_get_blueprint_graph_file_not_found(engine, request_mock):
    bp = MagicMock()
    bp.name = "test_bp"
    bp.render_graph.side_effect = FileNotFoundError
    engine.register_blueprint(bp)
    request_mock.match_info = {"blueprint_name": "test_bp"}
    response = await get_blueprint_graph_handler(request_mock)
    assert response.status == 501


@mark.asyncio
async def test_human_approval_job_not_found(engine, request_mock):
    request_mock.match_info = {"job_id": "non-existent-job"}
    request_mock.json.return_value = {"decision": "approve"}
    response = await human_approval_webhook_handler(request_mock)
    assert response.status == 404


@mark.asyncio
async def test_human_approval_invalid_body(engine, request_mock):
    job_id = "j1"
    request_mock.match_info = {"job_id": job_id}
    request_mock.json = AsyncMock(side_effect=ValueError)
    response = await human_approval_webhook_handler(request_mock)
    assert response.status == 400


@mark.asyncio
@mark.asyncio
async def test_human_approval_wrong_state(engine, request_mock):
    job_id = "job-in-wrong-state"
    token = request_mock.get("client_config")["token"]

    async def mock_get_job_state(jid):
        if jid == job_id:
            return {"id": job_id, "status": "running", "client_config": {"token": token}}
        return None

    engine.storage.get_job_state = mock_get_job_state
    request_mock.match_info = {"job_id": job_id}
    request_mock.json = AsyncMock(return_value={"decision": "approved"})
    response = await human_approval_webhook_handler(request_mock)
    # Return Conflict (409) if job is not in 'waiting_for_human' state
    assert response.status == 409


@mark.asyncio
async def test_human_approval_invalid_decision(engine, request_mock):
    job_id = "job-invalid-decision"
    token = request_mock.get("client_config")["token"]

    async def mock_get_job_state(jid):
        return {"id": job_id, "status": "waiting_for_human", "client_config": {"token": token}}

    engine.storage.get_job_state = mock_get_job_state
    request_mock.match_info = {"job_id": job_id}
    request_mock.json = AsyncMock(return_value={"decision": "rejected"})
    response = await human_approval_webhook_handler(request_mock)
    assert response.status == 400


@mark.asyncio
async def test_get_worker_catalog_cached(engine, request_mock):
    """Checks that the worker catalog is cached."""
    engine.worker_catalog_cache["data"] = [{"skill": "cached"}]
    engine.worker_catalog_cache["expires_at"] = 9999999999.0

    response = await get_worker_catalog_handler(request_mock)
    assert response.status == 200
    data = orjson_loads(response.body)
    assert data == [{"skill": "cached"}]


@mark.asyncio
async def test_get_jobs_handler(engine, request_mock):
    """Checks the jobs listing handler."""
    engine.history_storage = AsyncMock()
    engine.history_storage.get_jobs.return_value = [{"id": "j1"}]
    request_mock.query = {"limit": "10", "offset": "0"}

    response = await get_jobs_handler(request_mock)
    assert response.status == 200


@mark.asyncio
async def test_get_jobs_handler_invalid_params(engine, request_mock):
    """Checks the jobs listing handler with invalid query params."""
    request_mock.query = {"limit": "abc"}
    response = await get_jobs_handler(request_mock)
    assert response.status == 400


@mark.asyncio
async def test_api_field_filtering(engine, request_mock):
    """Checks that GET /api/v1/jobs/{id}?fields=... filters the response."""

    job_id = "j1"
    token = request_mock.get("client_config")["token"]
    await engine.storage.save_job_state(
        job_id,
        {"id": job_id, "status": "finished", "result": "data", "secret": "hide-me", "client_config": {"token": token}},
    )

    request_mock.match_info = {"job_id": job_id}
    request_mock.query = {"fields": "status,result"}

    response = await get_job_status_handler(request_mock)
    assert response.status == 200
    data = orjson_loads(response.body)

    assert "id" in data
    assert "status" in data
    assert "result" in data
    assert "secret" not in data


@mark.asyncio
async def test_docs_handler_file_not_found(engine, request_mock):
    """Checks that docs_handler returns 500 when docs file is missing."""
    with patch("importlib.resources.read_text", side_effect=FileNotFoundError):
        response = await docs_handler(request_mock)
        assert response.status == 500


@mark.asyncio
async def test_human_approval_with_scoped_token(engine, request_mock):
    """Checks that approval_token allows approving without X-Client-Token header."""
    job_id = "job-approval-1"
    approval_token = "valid-secret-approval-token"
    job_state = {
        "id": job_id,
        "status": "waiting_for_human",
        "approval_token": approval_token,
        "current_task_transitions": {"approved": "next_step"},
        "client_config": {"token": "owner-token"},
    }
    await engine.storage.save_job_state(job_id, job_state)

    request_mock.get.side_effect = lambda k, default=None: None
    request_mock.match_info = {"job_id": job_id}
    request_mock.query = {"token": approval_token}
    request_mock.json = AsyncMock(return_value={"decision": "approved"})

    response = await human_approval_webhook_handler(request_mock)
    assert response.status == 200
    res_data = orjson_loads(response.body)
    assert res_data["status"] == "approval_received"

    updated = await engine.storage.get_job_state(job_id)
    assert updated["current_state"] == "next_step"
    assert updated["status"] == "running"
    assert updated["approval_token"] is None


@mark.asyncio
async def test_human_approval_with_body_token(engine, request_mock):
    """Verifies human approval works when token is supplied in body."""
    job_id = "job-approval-body-1"
    token = "token-in-body-xyz"
    job_state = {
        "id": job_id,
        "status": JOB_STATUS_WAITING_FOR_HUMAN,
        "approval_token": token,
        "current_task_transitions": {"proceed": "step_next"},
    }
    await engine.storage.save_job_state(job_id, job_state)

    request_mock.get.side_effect = lambda k, default=None: None
    request_mock.match_info = {"job_id": job_id}
    request_mock.query = {}
    request_mock.json = AsyncMock(return_value={"decision": "proceed", "token": token})

    resp = await human_approval_webhook_handler(request_mock)
    assert resp.status == 200
    updated = await engine.storage.get_job_state(job_id)
    assert updated["current_state"] == "step_next"


@mark.asyncio
async def test_human_approval_single_use_token_replay_rejected(engine, request_mock):
    """Verifies that consuming an approval token invalidates it for subsequent requests."""
    job_id = "job-approval-replay-1"
    token = "secure-unique-token-123"
    job_state = {
        "id": job_id,
        "status": JOB_STATUS_WAITING_FOR_HUMAN,
        "approval_token": token,
        "current_task_transitions": {"approve": "step_accepted"},
    }
    await engine.storage.save_job_state(job_id, job_state)

    request_mock.get.side_effect = lambda k, default=None: None
    request_mock.match_info = {"job_id": job_id}
    request_mock.query = {"token": token}
    request_mock.json = AsyncMock(return_value={"decision": "approve"})

    resp1 = await human_approval_webhook_handler(request_mock)
    assert resp1.status == 200

    with raises(HTTPUnauthorized):
        await human_approval_webhook_handler(request_mock)


@mark.asyncio
async def test_human_approval_invalid_inputs_rejected(engine, request_mock):
    """Verifies rejection of wrong tokens, missing decision, unknown decision, and malformed JSON."""
    job_id = "job-approval-neg-1"
    valid_token = "good-token"
    job_state = {
        "id": job_id,
        "status": JOB_STATUS_WAITING_FOR_HUMAN,
        "approval_token": valid_token,
        "current_task_transitions": {"allow": "ok_step"},
    }
    await engine.storage.save_job_state(job_id, job_state)

    request_mock.get.side_effect = lambda k, default=None: None
    request_mock.match_info = {"job_id": job_id}

    request_mock.query = {"token": "wrong-token"}
    request_mock.json = AsyncMock(return_value={"decision": "allow"})
    with raises(HTTPUnauthorized):
        await human_approval_webhook_handler(request_mock)

    request_mock.query = {"token": valid_token}
    request_mock.json = AsyncMock(return_value={"decision": "unknown"})
    resp = await human_approval_webhook_handler(request_mock)
    assert resp.status == 400

    request_mock.json = AsyncMock(return_value={"no_decision": 1})
    resp = await human_approval_webhook_handler(request_mock)
    assert resp.status == 400

    request_mock.json = AsyncMock(side_effect=Exception("Malformed JSON"))
    resp = await human_approval_webhook_handler(request_mock)
    assert resp.status == 400


@mark.asyncio
async def test_human_approval_cas_conflict(engine, request_mock):
    """Verifies that approval returns 409 if state changes during CAS."""
    job_id = "job-cas-conflict-1"
    token = "token-conflict-123"
    job_state = {
        "id": job_id,
        "status": JOB_STATUS_WAITING_FOR_HUMAN,
        "approval_token": token,
        "current_task_transitions": {"approve": "next_step"},
    }
    await engine.storage.save_job_state(job_id, job_state)

    async def simulated_racing_update(jid, callback):
        racing_state = {"id": jid, "status": JOB_STATUS_FINISHED, "approval_token": None}
        return await callback(racing_state)

    engine.storage.update_job_state_atomic = simulated_racing_update

    request_mock.get.side_effect = lambda k, default=None: None
    request_mock.match_info = {"job_id": job_id}
    request_mock.query = {"token": token}
    request_mock.json = AsyncMock(return_value={"decision": "approve"})

    resp = await human_approval_webhook_handler(request_mock)
    assert resp.status == 409
    body = orjson_loads(resp.body)
    assert "Job is not in a state that can be approved" in body["error"]
