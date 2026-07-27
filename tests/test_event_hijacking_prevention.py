# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock, MagicMock

import pytest
from rxon.models import WorkerEventPayload
from rxon.utils import to_dict

from holarchy.services.worker_service import WorkerService


@pytest.mark.asyncio
async def test_job_event_hijacking_prevention_rejects_unassigned_worker():
    storage = AsyncMock()
    history_storage = AsyncMock()
    config = MagicMock()
    engine = MagicMock()
    metrics = MagicMock()

    service = WorkerService(storage, history_storage, config, engine, metrics)
    service._verify_zero_trust = AsyncMock()

    job_state = {
        "id": "job-sec-1",
        "assigned_worker_id": "legit-worker",
        "blueprint_name": "bp1",
    }
    storage.get_job_state.return_value = job_state

    event = WorkerEventPayload(
        event_id="ev-1",
        worker_id="attacker-worker",
        origin_worker_id="attacker-worker",
        event_type="progress",
        payload={"msg": "fake"},
        target_job_id="job-sec-1",
        timestamp=12345,
    )
    raw_event = to_dict(event)

    # Attacker worker tries to send event for job assigned to 'legit-worker'
    with pytest.raises(PermissionError) as exc_info:
        await service.process_worker_event("attacker-worker", raw_event)

    assert "is not assigned to job" in str(exc_info.value)


@pytest.mark.asyncio
async def test_job_event_hijacking_prevention_allows_assigned_worker():
    storage = AsyncMock()
    history_storage = AsyncMock()
    config = MagicMock()
    engine = MagicMock()
    metrics = MagicMock()

    service = WorkerService(storage, history_storage, config, engine, metrics)
    service._verify_zero_trust = AsyncMock()

    job_state = {
        "id": "job-sec-1",
        "assigned_worker_id": "legit-worker",
        "blueprint_name": "bp1",
    }
    storage.get_job_state.return_value = job_state
    storage.get_worker_info.return_value = None

    event = WorkerEventPayload(
        event_id="ev-1",
        worker_id="legit-worker",
        origin_worker_id="legit-worker",
        event_type="progress",
        payload={"msg": "ok"},
        target_job_id="job-sec-1",
        timestamp=12345,
    )
    raw_event = to_dict(event)

    # Legit worker -> event accepted
    resp = await service.process_worker_event("legit-worker", raw_event)
    assert resp["status"] == "event_accepted"


@pytest.mark.asyncio
async def test_job_event_sender_id_mismatch_raises():
    storage = AsyncMock()
    service = WorkerService(storage, AsyncMock(), MagicMock(), MagicMock(), MagicMock())
    service._verify_zero_trust = AsyncMock()

    event = WorkerEventPayload(
        event_id="ev-2",
        worker_id="worker-stated-in-payload",
        origin_worker_id="worker-stated-in-payload",
        event_type="progress",
        payload={},
        timestamp=123,
    )
    raw_event = to_dict(event)

    # Authenticated header worker-123 != payload worker_id
    with pytest.raises(PermissionError) as exc_info:
        await service.process_worker_event("authenticated-header-worker", raw_event)

    assert "Immediate sender ID mismatch" in str(exc_info.value)


@pytest.mark.asyncio
async def test_job_event_ghost_worker_allowed():
    storage = AsyncMock()
    engine = MagicMock()
    engine.webhook_sender.send = AsyncMock()
    engine.on_worker_event = []
    service = WorkerService(storage, AsyncMock(), MagicMock(), engine, MagicMock())
    service._verify_zero_trust = AsyncMock()
    storage.get_worker_info.return_value = None

    event = WorkerEventPayload(
        event_id="ev-ghost",
        worker_id="ghost",
        origin_worker_id="ghost",
        event_type="custom_event",
        payload={"a": 1},
        target_job_id="any-job",
        timestamp=123,
    )
    raw_event = to_dict(event)

    # "ghost" worker ID is system internal emitter -> accepted
    resp = await service.process_worker_event("ghost", raw_event)
    assert resp["status"] == "event_accepted"


@pytest.mark.asyncio
async def test_job_event_branch_worker_allowed():
    storage = AsyncMock()
    engine = MagicMock()
    engine.webhook_sender.send = AsyncMock()
    engine.on_worker_event = []
    service = WorkerService(storage, AsyncMock(), MagicMock(), engine, MagicMock())
    service._verify_zero_trust = AsyncMock()
    storage.get_worker_info.return_value = None

    job_state = {
        "id": "job-parallel",
        "branch_worker_ids": {"branch-1": "worker-branch-1", "branch-2": "worker-branch-2"},
    }
    storage.get_job_state.return_value = job_state

    event = WorkerEventPayload(
        event_id="ev-branch",
        worker_id="worker-branch-1",
        origin_worker_id="worker-branch-1",
        event_type="progress",
        payload={"msg": "branch working"},
        target_job_id="job-parallel",
        timestamp=123,
    )
    raw_event = to_dict(event)

    resp = await service.process_worker_event("worker-branch-1", raw_event)
    assert resp["status"] == "event_accepted"
