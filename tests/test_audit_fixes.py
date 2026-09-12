# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from logging import DEBUG
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pytest import mark, raises
from rxon.security import sign_payload

from holarchy.api.handlers import get_quarantined_jobs_handler
from holarchy.api.routes import setup_routes
from holarchy.app_keys import CLIENT_CONFIG_KEY, ENGINE_KEY
from holarchy.engine import OrchestratorEngine
from holarchy.s3 import TaskFiles
from holarchy.services.worker_service import WorkerService


@mark.asyncio
async def test_debug_flush_db_endpoint_removed():
    """AVT-SEC-1: Verify that POST /_public/debug/flush_db does not exist."""
    app = web.Application()
    engine = MagicMock()
    engine.config.CLIENT_API_PREFIX = ""
    engine.config.ENABLE_CLIENT_API = False
    engine.blueprints = {}

    setup_routes(app, engine)

    # Search routes in app and subapps
    all_routes = list(app.router.routes())
    for resource in app.router.resources():
        all_routes.extend(resource)

    route_paths = [r.canonical for r in all_routes if hasattr(r, "canonical")]
    assert not any("flush_db" in p for p in route_paths)


@mark.asyncio
async def test_quarantined_jobs_requires_auth():
    """AVT-SEC-1: Verify quarantined jobs endpoint requires authentication."""
    engine = MagicMock()
    engine.config.DETAILED_API_RESPONSES = True
    app = {ENGINE_KEY: engine}

    # 1. Unauthenticated request -> 401
    req_unauth = make_mocked_request("GET", "/jobs/quarantined", app=app)
    resp_unauth = await get_quarantined_jobs_handler(req_unauth)
    assert resp_unauth.status == 401

    # 2. Authenticated request -> 200
    engine.storage.get_quarantined_jobs = AsyncMock(return_value=["job-1"])
    engine.storage.get_job_state = AsyncMock(
        return_value={"id": "job-1", "status": "quarantined", "client_config": {"token": "client-123"}}
    )
    req_auth = make_mocked_request("GET", "/jobs/quarantined", app=app, headers={"X-Client-Token": "client-123"})
    req_auth[CLIENT_CONFIG_KEY] = {"token": "client-123"}
    resp_auth = await get_quarantined_jobs_handler(req_auth)
    assert resp_auth.status == 200


@mark.asyncio
async def test_worker_service_replay_attack_prevention():
    """AVT-SEC-2: Replay attack prevention via timestamp and nonce cache."""
    engine = MagicMock()
    storage = MagicMock()
    history_storage = MagicMock()
    metrics = MagicMock()
    # Mock storage nonce cache using an in-memory set
    seen_nonces = set()

    def fake_set_nx_ttl(key: str, value: str, ttl: int) -> bool:
        if key in seen_nonces:
            return False
        seen_nonces.add(key)
        return True

    storage.set_nx_ttl = AsyncMock(side_effect=fake_set_nx_ttl)
    storage.find_worker_token = AsyncMock(return_value="worker-secret-token")

    config = MagicMock()
    config.REDIS_ENCRYPTION_KEY = None
    config.encrypt_worker_tokens = False

    service = WorkerService(
        storage=storage,
        history_storage=history_storage,
        config=config,
        engine=engine,
        metrics=metrics,
    )

    now = int(time())
    token = "worker-secret-token"

    # 1. First event with valid timestamp and event_id -> Success
    event_payload = {
        "worker_id": "worker-1",
        "event_type": "progress",
        "event_id": "unique-event-001",
        "target_job_id": "j1",
        "payload": {"pct": 50},
        "timestamp": now,
    }
    sig = sign_payload(event_payload, token, ignore_fields=["security"])
    event_payload["security"] = {"signature": sig, "signer_id": "worker-1"}

    await service._verify_zero_trust(event_payload, "worker-1")

    # 2. Replay of the exact same event within valid timestamp window -> Must raise PermissionError
    with raises(PermissionError, match="Duplicate message detected \\(replay attack\\)"):
        await service._verify_zero_trust(event_payload, "worker-1")

    # 3. Expired timestamp (> 60s) -> Must raise PermissionError
    expired_payload = dict(event_payload)
    expired_payload["event_id"] = "unique-event-002"
    expired_payload["timestamp"] = now - 65
    sig_exp = sign_payload(expired_payload, token, ignore_fields=["security"])
    expired_payload["security"] = {"signature": sig_exp, "signer_id": "worker-1"}

    with raises(PermissionError, match="Message timestamp expired"):
        await service._verify_zero_trust(expired_payload, "worker-1")

    # 4. Missing timestamp -> Must raise PermissionError
    missing_ts_payload = dict(event_payload)
    missing_ts_payload["event_id"] = "unique-event-003"
    missing_ts_payload.pop("timestamp", None)
    sig_no_ts = sign_payload(missing_ts_payload, token, ignore_fields=["security"])
    missing_ts_payload["security"] = {"signature": sig_no_ts, "signer_id": "worker-1"}

    with raises(PermissionError, match="Missing required timestamp"):
        await service._verify_zero_trust(missing_ts_payload, "worker-1")


def test_task_files_path_traversal_prevention_server():
    """AVT-SEC-S3: Server-side TaskFiles path traversal prevention."""
    with TemporaryDirectory() as tmp_dir:
        provider = MagicMock()
        task_files = TaskFiles(provider=provider, bucket="test-bucket", job_id="job_456", base_local_dir=tmp_dir)

        # 1. Positive: Valid file
        safe_path = task_files.path("report.pdf")
        assert safe_path.is_relative_to(Path(tmp_dir) / "job_456")

        # 2. Negative: Path traversal attempts
        bad_paths = ["../../etc/passwd", "../../../root/.bashrc", "subdir/../../outside.txt"]
        for bad in bad_paths:
            with raises(PermissionError, match="Path traversal attempt detected"):
                task_files.path(bad)


@mark.asyncio
async def test_token_not_leaked_in_logs(caplog):
    """AVT-SEC-3: Secret token is never leaked in debug/info logs."""
    # 1. Test worker service verify logging
    engine = MagicMock()
    storage = MagicMock()
    storage.set_nx_ttl = AsyncMock(return_value=True)
    secret_token = "secret-super-sensitive-token-12345"
    storage.find_worker_token = AsyncMock(return_value=secret_token)

    config = MagicMock()
    config.REDIS_ENCRYPTION_KEY = None
    config.encrypt_worker_tokens = False

    service = WorkerService(
        storage=storage,
        history_storage=MagicMock(),
        config=config,
        engine=engine,
        metrics=MagicMock(),
    )

    now = int(time())
    payload = {
        "worker_id": "worker-1",
        "timestamp": now,
        "event_id": "evt-1",
    }
    sig = sign_payload(payload, secret_token, ignore_fields=["security"])
    payload["security"] = {"signature": sig, "signer_id": "worker-1"}

    with caplog.at_level(DEBUG):
        await service._verify_zero_trust(payload, "worker-1")
        # Ensure secret token prefix is not printed
        for record in caplog.records:
            assert "secret[:4]" not in record.message
            assert "secr..." not in record.message
            assert secret_token not in record.message


@mark.asyncio
async def test_job_timeout_decrements_worker_load():
    """AVT-CNC-1: Engine decrements worker load upon job timeout."""
    config = MagicMock()
    config.TZ = "UTC"
    config.LOG_LEVEL = "INFO"
    config.LOG_FORMAT = "text"
    config.S3_AUTO_CLEANUP = False
    config.DETAILED_API_RESPONSES = True

    storage = MagicMock()
    storage.decrement_worker_load = AsyncMock()
    storage.save_job_state = AsyncMock()
    history_storage = MagicMock()
    history_storage.log_job_event = AsyncMock()

    engine = OrchestratorEngine(
        storage=storage,
        config=config,
    )
    engine.history_storage = history_storage
    engine.metrics = MagicMock()

    job_state = {
        "id": "job-123",
        "status": "waiting_for_worker",
        "task_worker_id": "worker-abc",
        "task_picked_up_at": None,
        "dispatch_deadline": time() - 10,
    }

    await engine.handle_job_timeout(job_state)

    storage.decrement_worker_load.assert_called_once_with("worker-abc")
    assert job_state["status"] == "failed"
