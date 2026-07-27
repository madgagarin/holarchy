# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock, MagicMock

import pytest

from holarchy.executor import JobExecutor


@pytest.mark.asyncio
async def test_holarchy_depth_exceeded_quarantines():
    engine = MagicMock()
    engine.blueprint_contracts = {}
    engine.config.MAX_HOLARCHY_DEPTH = 3
    storage = AsyncMock()
    history_storage = AsyncMock()
    metrics = MagicMock()

    executor = JobExecutor(engine, history_storage, metrics)
    executor.storage = storage

    parent_job_state = {
        "id": "parent-1",
        "depth": 3,
        "blueprint_name": "parent_bp",
    }
    sub_info = {
        "blueprint_name": "child_bp",
        "initial_data": {},
    }

    await executor._handle_run_blueprint(parent_job_state, sub_info, 10)

    assert parent_job_state["status"] == "quarantined"
    assert "Holarchy depth limit exceeded" in parent_job_state["error_message"]
    storage.quarantine_job.assert_called_once_with("parent-1")


@pytest.mark.asyncio
async def test_holarchy_depth_at_limit_allowed():
    engine = MagicMock()
    engine.blueprint_contracts = {}
    engine.config.MAX_HOLARCHY_DEPTH = 3
    engine.create_background_job = AsyncMock(return_value="child-job-ok")
    storage = AsyncMock()
    history_storage = AsyncMock()
    metrics = MagicMock()

    executor = JobExecutor(engine, history_storage, metrics)
    executor.storage = storage

    # Parent depth = 2 -> child depth = 3 (MAX_HOLARCHY_DEPTH = 3, allowed)
    parent_job_state = {
        "id": "parent-2",
        "depth": 2,
        "blueprint_name": "parent_bp",
        "status": "running",
    }
    sub_info = {
        "blueprint_name": "child_bp",
        "initial_data": {"x": 1},
    }

    await executor._handle_run_blueprint(parent_job_state, sub_info, 10)

    # Job is NOT quarantined
    assert parent_job_state.get("status") != "quarantined"
    engine.create_background_job.assert_called_once()
    assert engine.create_background_job.call_args[1]["depth"] == 3
