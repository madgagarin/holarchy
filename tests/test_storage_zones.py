# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from pytest import mark

from holarchy.api.handlers import _filter_job_state
from holarchy.context import ActionFactory
from holarchy.data_types import ClientConfig, JobContext, ensure_storage_zones
from holarchy.fsm import Next, State, StatesGroup
from holarchy.storage.memory import MemoryStorage


class Flow(StatesGroup):
    first = State()
    second = State()


def test_ensure_storage_zones_clean_slate():
    """Verifies that ensure_storage_zones ensures 5 pure memory zones without legacy aliases."""
    state_modern = {
        "input": {"user_id": "u1"},
        "steps": {"first": {"code": 200}},
        "output": {"status": "ok"},
        "history": [{"step": "first"}],
        "params": {"timeout": 10},
        "meta": {"source": "test"},
    }
    ensure_storage_zones(state_modern)
    assert state_modern["input"] == {"user_id": "u1"}
    assert state_modern["steps"] == {"first": {"code": 200}}
    assert state_modern["output"] == {"status": "ok"}
    assert state_modern["history"] == [{"step": "first"}]
    assert state_modern["params"] == {"timeout": 10}
    assert state_modern["meta"] == {"source": "test"}

    # In v1.0.0 clean slate, legacy aliases are NOT created
    assert "initial_data" not in state_modern
    assert "state_history" not in state_modern


@mark.asyncio
async def test_memory_storage_preserves_all_5_zones():
    storage = MemoryStorage()
    job_id = "test-job-zones"

    original_state = {
        "id": job_id,
        "blueprint_name": "test_bp",
        "current_state": "start",
        "status": "running",
        "input": {"payload": 42},
        "steps": {"start": "done"},
        "history": [{"from": "init", "to": "start"}],
        "output": None,
        "params": {"tier": "gold"},
        "meta": {"priority": "high"},
    }

    await storage.save_job_state(job_id, original_state)
    retrieved = await storage.get_job_state(job_id)
    assert retrieved is not None
    assert retrieved["input"] == {"payload": 42}
    assert retrieved["steps"] == {"start": "done"}
    assert retrieved["history"] == [{"from": "init", "to": "start"}]
    assert retrieved["params"] == {"tier": "gold"}
    assert retrieved["meta"] == {"priority": "high"}
    assert "initial_data" not in retrieved
    assert "state_history" not in retrieved

    # Test update_job_state
    await storage.update_job_state(job_id, {"output": {"result_code": 0}})
    updated = await storage.get_job_state(job_id)
    assert updated["output"] == {"result_code": 0}

    # Test update_job_state_atomic
    def _modify(s):
        s["steps"]["next_step"] = "computed"
        return s

    await storage.update_job_state_atomic(job_id, _modify)
    atomic_updated = await storage.get_job_state(job_id)
    assert atomic_updated["steps"]["next_step"] == "computed"
    assert "state_history" not in atomic_updated


def test_job_context_clean_attributes_and_helpers():
    actions = ActionFactory(job_id="ctx-job")
    client = ClientConfig(token="tok", plan="pro", params={"max": 100})

    ctx = JobContext(
        job_id="ctx-job",
        current_state="step1",
        input={"foo": "bar"},
        steps={"step0": "ok"},
        output={"val": 42},
        history=[{"event": "start"}],
        params={"max": 100},
        client=client,
        actions=actions,
        meta={"env": "test"},
    )

    # Clean attributes
    assert ctx.input == {"foo": "bar"}
    assert ctx.steps == {"step0": "ok"}
    assert ctx.history == [{"event": "start"}]
    assert ctx.output == {"val": 42}
    assert ctx.params == {"max": 100}
    assert ctx.meta == {"env": "test"}

    # Legacy attributes do not exist
    assert not hasattr(ctx, "initial_data")
    assert not hasattr(ctx, "state_history")

    # Helper methods
    next_inst = ctx.go_to(Flow.second, data={"msg": "hello"})
    assert isinstance(next_inst, Next)
    assert next_inst.state == Flow.second
    assert next_inst.data == {"msg": "hello"}
    assert actions.next_state == str(Flow.second)

    ctx.save_result({"custom": 123})
    assert actions.step_result == {"custom": 123}


def test_filter_job_state_output_and_result_security():
    # Non-terminal job: output and result must NOT leak
    running_job = {
        "id": "j1",
        "status": "running",
        "result": "secret_result",
        "output": "secret_output",
        "client_config": {"token": "secret"},
    }

    # Compact filter
    compact = _filter_job_state(running_job, detailed_allowed=False)
    assert "result" not in compact
    assert "output" not in compact

    # Detailed filter
    detailed = _filter_job_state(running_job, detailed_allowed=True)
    assert "result" not in detailed
    assert "output" not in detailed
    assert "client_config" not in detailed  # Sensitive system field stripped

    # Terminal job: output and result ARE allowed
    finished_job = {
        "id": "j2",
        "status": "finished",
        "result": {"data": 123},
        "output": {"data": 123},
        "client_config": {"token": "secret"},
    }

    compact_term = _filter_job_state(finished_job, detailed_allowed=False)
    assert compact_term["result"] == {"data": 123}
    assert compact_term["output"] == {"data": 123}

    detailed_term = _filter_job_state(finished_job, detailed_allowed=True)
    assert detailed_term["result"] == {"data": 123}
    assert detailed_term["output"] == {"data": 123}


@mark.asyncio
async def test_redis_storage_preserves_all_5_zones(redis_storage):
    job_id = "test-redis-zones"
    original_state = {
        "id": job_id,
        "blueprint_name": "test_redis_bp",
        "current_state": "init",
        "status": "running",
        "input": {"order_id": 999},
        "steps": {"init": {"status": "started"}},
        "history": [{"step": "init", "ts": 12345}],
        "output": None,
        "params": {"api_key": "k-123"},
        "meta": {"trace_id": "tr-456"},
    }

    await redis_storage.save_job_state(job_id, original_state)
    retrieved = await redis_storage.get_job_state(job_id)
    assert retrieved is not None
    assert retrieved["input"] == {"order_id": 999}
    assert retrieved["steps"] == {"init": {"status": "started"}}
    assert retrieved["history"] == [{"step": "init", "ts": 12345}]
    assert retrieved["params"] == {"api_key": "k-123"}
    assert retrieved["meta"] == {"trace_id": "tr-456"}
    assert "initial_data" not in retrieved
    assert "state_history" not in retrieved

    # Atomic update in Redis
    def _add_step(s):
        s["steps"]["second"] = "done"
        s["output"] = {"final": True}
        return s

    await redis_storage.update_job_state_atomic(job_id, _add_step)
    updated = await redis_storage.get_job_state(job_id)
    assert updated["steps"]["second"] == "done"
    assert updated["output"] == {"final": True}
    assert "state_history" not in updated


def test_ensure_storage_zones_corrupted_and_empty_inputs():
    # 1. Completely empty dictionary
    state = {}
    ensure_storage_zones(state)
    assert state["input"] == {}
    assert state["steps"] == {}
    assert state["history"] == []
    assert state["output"] is None
    assert state["params"] == {}
    assert state["meta"] == {}
    assert "initial_data" not in state
    assert "state_history" not in state

    # 2. Corrupted data types (strings or integers where dicts or lists expected)
    corrupted = {
        "input": "not_a_dict",
        "steps": "corrupted_steps",
        "history": "not_a_list",
        "params": 99.9,
        "meta": 100,
    }
    ensure_storage_zones(corrupted)
    assert isinstance(corrupted["input"], dict)
    assert isinstance(corrupted["steps"], dict)
    assert isinstance(corrupted["history"], list)
    assert isinstance(corrupted["params"], dict)
    assert isinstance(corrupted["meta"], dict)

    # 3. Idempotency test: calling ensure_storage_zones multiple times
    first_pass = dict(corrupted)
    ensure_storage_zones(corrupted)
    ensure_storage_zones(corrupted)
    assert corrupted == first_pass
