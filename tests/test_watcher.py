# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import create_task, sleep
from time import time
from unittest.mock import AsyncMock, MagicMock

from pytest import mark
from rxon.constants import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_FINISHED,
    JOB_STATUS_QUARANTINED,
    JOB_STATUS_RUNNING,
)

from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage
from holarchy.watcher import Watcher


@mark.asyncio
async def test_watcher_run():
    """Tests that the watcher correctly identifies and handles timed out jobs."""
    engine = MagicMock(spec=OrchestratorEngine)
    engine.storage = AsyncMock()
    engine.config = Config()
    engine.config.WATCHER_LIMIT = 500

    job_1_state = {
        "id": "job-1",
        "status": "waiting_for_worker",
        "blueprint_name": "test_bp",
    }

    engine.storage.get_timed_out_jobs.return_value = ["job-1"]
    engine.storage.get_job_state.return_value = job_1_state
    engine.storage.acquire_lock = AsyncMock(return_value=True)
    engine.storage.release_lock = AsyncMock(return_value=True)
    engine.handle_job_timeout = AsyncMock()

    watcher = Watcher(engine)
    watcher.watch_interval_seconds = 0.05

    task = create_task(watcher.run())
    await sleep(0.1)
    watcher.stop()
    await task

    engine.storage.get_timed_out_jobs.assert_called()
    engine.storage.get_job_state.assert_called_with("job-1")
    engine.handle_job_timeout.assert_called()
    called_state = engine.handle_job_timeout.call_args[0][0]
    assert called_state["id"] == "job-1"
    assert called_state["status"] == "waiting_for_worker"


@mark.asyncio
async def test_watcher_timeout_preserves_terminal_states():
    """Verifies handle_job_timeout does not overwrite terminal states."""
    storage = MemoryStorage()
    cfg = Config()
    cfg.ORCHESTRATOR_SECRET_KEY = "test-secret"
    engine = OrchestratorEngine(storage, cfg)

    for terminal_status in [
        JOB_STATUS_FINISHED,
        JOB_STATUS_FAILED,
        JOB_STATUS_QUARANTINED,
        JOB_STATUS_CANCELLED,
    ]:
        job_id = f"job-terminal-{terminal_status}"
        job_state = {
            "id": job_id,
            "status": terminal_status,
            "error_message": None,
            "blueprint_name": "bp_test",
        }
        await storage.save_job_state(job_id, job_state)
        await engine.handle_job_timeout(job_state)

        current = await storage.get_job_state(job_id)
        assert current["status"] == terminal_status
        assert current.get("error_message") is None


@mark.asyncio
async def test_watcher_timeout_transitions_running_job_to_failed():
    """Verifies handle_job_timeout transitions a running job to failed."""
    storage = MemoryStorage()
    cfg = Config()
    cfg.ORCHESTRATOR_SECRET_KEY = "test-secret"
    engine = OrchestratorEngine(storage, cfg)

    job_id = "job-running-timeout"
    job_state = {
        "id": job_id,
        "status": JOB_STATUS_RUNNING,
        "error_message": None,
        "blueprint_name": "bp_test",
        "dispatch_deadline": time() - 10,
    }
    await storage.save_job_state(job_id, job_state)
    await engine.handle_job_timeout(job_state)

    current = await storage.get_job_state(job_id)
    assert current["status"] == JOB_STATUS_FAILED
    assert "Worker task timed out" in current["error_message"]
