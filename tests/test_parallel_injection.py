# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock, MagicMock

import pytest
from rxon.constants import IGNORED_REASON_MISMATCH, JOB_STATUS_WAITING_FOR_PARALLEL

from holarchy.services.worker_service import WorkerService


@pytest.mark.asyncio
async def test_parallel_task_injection_rejected():
    storage = AsyncMock()
    history_storage = AsyncMock()
    config = MagicMock()
    engine = MagicMock()
    engine.app = {}
    metrics = MagicMock()

    service = WorkerService(storage, history_storage, config, engine, metrics)
    service._verify_zero_trust = AsyncMock()

    # Job waiting for parallel branches [branch-1, branch-2]
    job_state = {
        "id": "job-100",
        "status": JOB_STATUS_WAITING_FOR_PARALLEL,
        "active_branches": ["branch-1", "branch-2"],
    }
    storage.get_job_state.return_value = job_state
    storage.get_worker_info.return_value = None

    # Fake result payload with fake_task_id
    fake_result = {
        "job_id": "job-100",
        "task_id": "fake-branch-id",
        "worker_id": "worker-1",
        "status": "success",
        "timestamp": 123456,
    }

    res = await service.process_task_result(fake_result, "worker-1")

    assert res["status"] == "ignored"
    assert res["reason"] == IGNORED_REASON_MISMATCH
    assert "not an active parallel branch" in res["message"]
