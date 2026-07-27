# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock, MagicMock

import pytest

from holarchy.blueprint import Blueprint
from holarchy.context import ActionFactory
from holarchy.executor import JobExecutor


def test_action_factory_allowed_skills_policy():
    policy = {"allowed_skills": ["allowed_skill_1", "allowed_skill_2"]}
    actions = ActionFactory(job_id="job-1", policy=policy)

    # Allowed skill should succeed
    actions.dispatch_task("allowed_skill_1", {}, {"success": "end"})
    assert actions.task_to_dispatch["type"] == "allowed_skill_1"


def test_action_factory_empty_or_none_policy_allows_any_skill():
    # Unrestricted policy (None or empty dict)
    actions_none = ActionFactory(job_id="job-1", policy=None)
    actions_none.dispatch_task("any_skill", {}, {"success": "end"})
    assert actions_none.task_to_dispatch["type"] == "any_skill"

    actions_empty = ActionFactory(job_id="job-2", policy={})
    actions_empty.dispatch_task("another_skill", {}, {"success": "end"})
    assert actions_empty.task_to_dispatch["type"] == "another_skill"


def test_action_factory_disallowed_skill_policy_raises():
    policy = {"allowed_skills": ["allowed_skill_1"]}
    actions = ActionFactory(job_id="job-1", policy=policy)

    # Disallowed skill must raise PermissionError
    with pytest.raises(PermissionError) as exc_info:
        actions.dispatch_task("forbidden_skill", {}, {"success": "end"})

    assert "not permitted by job policy" in str(exc_info.value)


def test_action_factory_dispatch_parallel_policy():
    policy = {"allowed_skills": ["skill_a", "skill_b"]}
    actions = ActionFactory(job_id="job-1", policy=policy)

    # All skills allowed -> success
    actions.dispatch_parallel(
        tasks=[{"type": "skill_a", "params": {}}, {"type": "skill_b", "params": {}}],
        aggregate_into="agg",
    )
    assert len(actions.parallel_tasks_to_dispatch["tasks"]) == 2

    # One forbidden skill in parallel list -> raises PermissionError
    actions2 = ActionFactory(job_id="job-2", policy=policy)
    with pytest.raises(PermissionError) as exc_info:
        actions2.dispatch_parallel(
            tasks=[{"type": "skill_a", "params": {}}, {"type": "skill_c_forbidden", "params": {}}],
            aggregate_into="agg",
        )
    assert "skill_c_forbidden" in str(exc_info.value)


@pytest.mark.asyncio
async def test_job_executor_enforces_policy_end_to_end():
    engine = MagicMock()
    engine.send_job_webhook = AsyncMock()
    engine.on_job_finished = []
    bp = Blueprint("policy_bp")

    @bp.handler("start", is_start=True)
    async def start(actions):
        actions.dispatch_task("forbidden_skill", {}, {"success": "end"})

    bp.validate()
    engine.blueprints = {"policy_bp": bp}
    engine.app = {}
    engine.config.MAX_TRANSITIONS_PER_JOB = 100
    engine.config.JOB_MAX_RETRIES = 0

    storage = AsyncMock()
    history_storage = AsyncMock()
    metrics = MagicMock()

    executor = JobExecutor(engine, history_storage, metrics)
    executor.storage = storage

    job_state = {
        "id": "job-policy-e2e",
        "blueprint_name": "policy_bp",
        "current_state": "start",
        "status": "running",
        "policy": {"allowed_skills": ["allowed_skill"]},
    }
    storage.get_job_state.return_value = job_state

    await executor._process_job("job-policy-e2e", "msg-1")

    # Job should be quarantined with PermissionError because forbidden_skill was dispatched
    assert job_state["status"] == "quarantined"
    storage.quarantine_job.assert_called_once_with("job-policy-e2e")
    logged_events = [c[0][0] for c in history_storage.log_job_event.call_args_list]
    failed_event = next(e for e in logged_events if e["event_type"] == "state_failed")
    assert "not permitted by job policy" in failed_event["context_snapshot"]["error_message"]


@pytest.mark.asyncio
async def test_sub_blueprint_inherits_parent_policy():
    engine = MagicMock()
    engine.blueprint_contracts = {}
    engine.config.MAX_HOLARCHY_DEPTH = 5
    engine.create_background_job = AsyncMock(return_value="child-job-123")

    executor = JobExecutor(engine, AsyncMock(), MagicMock())
    executor.storage = AsyncMock()

    parent_job_state = {
        "id": "parent-job",
        "blueprint_name": "parent_bp",
        "depth": 1,
        "policy": {"allowed_skills": ["skill_x"]},
        "max_transitions": 25,
    }

    sub_info = {
        "blueprint_name": "child_bp",
        "initial_data": {"input": 42},
    }

    await executor._handle_run_blueprint(parent_job_state, sub_info, 100)

    # Ensure engine.create_background_job was called with parent's policy, depth + 1, parent_hash, and max_transitions
    kwargs = engine.create_background_job.call_args[1]
    assert kwargs["blueprint_name"] == "child_bp"
    assert kwargs["policy"] == {"allowed_skills": ["skill_x"]}
    assert kwargs["depth"] == 2
    assert kwargs["max_transitions"] == 25
