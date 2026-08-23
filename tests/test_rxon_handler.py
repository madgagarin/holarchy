# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from unittest.mock import AsyncMock

from pytest import fixture, mark, raises
from rxon.models import TaskPayload

from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage


@fixture
def engine():
    storage = MemoryStorage()
    config = Config()
    engine = OrchestratorEngine(storage, config)
    engine.worker_service = AsyncMock()
    return engine


@mark.asyncio
async def test_handle_rxon_register(engine):
    payload = {"worker_id": "w1", "worker_type": "t1"}
    context = {"token": engine.config.GLOBAL_WORKER_TOKEN}

    await engine.handle_rxon_message("register", payload, context)
    engine.worker_service.register_worker.assert_called_once_with(payload, "w1")


@mark.asyncio
async def test_handle_rxon_poll(engine):
    worker_id = "w1"
    context = {"token": engine.config.GLOBAL_WORKER_TOKEN}

    task = TaskPayload(job_id="j1", task_id="t1", type="type1", params={}, tracing_context={})
    engine.worker_service.get_next_task.return_value = task

    result = await engine.handle_rxon_message("poll", worker_id, context)
    assert result == task
    engine.worker_service.get_next_task.assert_called_once_with(worker_id)


@mark.asyncio
async def test_handle_rxon_result(engine):
    payload = {"job_id": "j1", "task_id": "t1", "worker_id": "w1", "status": "success"}
    context = {"token": engine.config.GLOBAL_WORKER_TOKEN}

    await engine.handle_rxon_message("result", payload, context)
    engine.worker_service.process_task_result.assert_called_once_with(payload, "w1")


@mark.asyncio
async def test_handle_rxon_auth_failure(engine):
    payload = {"worker_id": "w1"}
    context = {"token": "wrong-token"}

    with raises(PermissionError):
        await engine.handle_rxon_message("register", payload, context)
