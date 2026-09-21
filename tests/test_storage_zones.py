# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from holarchy.api.handlers import _filter_job_state
from holarchy.context import ActionFactory
from holarchy.data_types import ClientConfig, JobContext, ensure_storage_zones
from holarchy.fsm import Next, State, StatesGroup
from holarchy.storage.memory import MemoryStorage


class Flow(StatesGroup):
    first = State()
    second = State()


def test_ensure_storage_zones_bidirectional_sync():
    # 1. State with only modern zones gets legacy aliases
    state_modern = {
        "input": {"user_id": "u1"},
        "steps": {"first": {"code": 200}},
        "output": {"status": "ok"},
        "history": [{"step": "first"}],
        "params": {"timeout": 10},
        "meta": {"source": "test"},
    }
    ensure_storage_zones(state_modern)
    assert state_modern["initial_data"] == {"user_id": "u1"}
    assert state_modern["state_history"] == {"first": {"code": 200}}
    assert state_modern["result"] == {"status": "ok"}
    assert state_modern["history"] == [{"step": "first"}]
    assert state_modern["params"] == {"timeout": 10}
    assert state_modern["meta"] == {"source": "test"}

    # 2. State with only legacy aliases gets modern zones
    state_legacy = {
        "initial_data": {"order_id": 123},
        "state_history": {"start": {"success": True}},
        "result": {"final": 999},
        "client_config": {"token": "t1", "params": {"env": "prod"}},
        "metadata": {"correlation": "xyz"},
    }
    ensure_storage_zones(state_legacy)
    assert state_legacy["input"] == {"order_id": 123}
    assert state_legacy["steps"] == {"start": {"success": True}}
    assert state_legacy["output"] == {"final": 999}
    assert state_legacy["history"] == []
    assert state_legacy["params"] == {"env": "prod"}
    assert state_legacy["meta"] == {"correlation": "xyz"}

    # 3. Partial merge: both exist with distinct keys
    state_mixed = {
        "input": {"a": 1},
        "initial_data": {"b": 2},
        "steps": {"s1": 10},
        "state_history": {"s2": 20},
    }
    ensure_storage_zones(state_mixed)
    assert state_mixed["input"] == {"a": 1, "b": 2}
    assert state_mixed["initial_data"] == {"a": 1, "b": 2}
    assert state_mixed["steps"] == {"s1": 10, "s2": 20}
    assert state_mixed["state_history"] == {"s1": 10, "s2": 20}


@pytest.mark.asyncio
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
    assert retrieved["initial_data"] == {"payload": 42}
    assert retrieved["steps"] == {"start": "done"}
    assert retrieved["state_history"] == {"start": "done"}
    assert retrieved["history"] == [{"from": "init", "to": "start"}]
    assert retrieved["params"] == {"tier": "gold"}
    assert retrieved["meta"] == {"priority": "high"}

    # Test update_job_state
    await storage.update_job_state(job_id, {"output": {"result_code": 0}})
    updated = await storage.get_job_state(job_id)
    assert updated["output"] == {"result_code": 0}
    assert updated["result"] == {"result_code": 0}

    # Test update_job_state_atomic
    def _modify(s):
        s["steps"]["next_step"] = "computed"
        return s

    await storage.update_job_state_atomic(job_id, _modify)
    atomic_updated = await storage.get_job_state(job_id)
    assert atomic_updated["steps"]["next_step"] == "computed"
    assert atomic_updated["state_history"]["next_step"] == "computed"


def test_job_context_clean_attributes_and_helpers():
    actions = ActionFactory(job_id="ctx-job")
    client = ClientConfig(token="tok", plan="pro", params={"max": 100})

    ctx = JobContext(
        job_id="ctx-job",
        current_state="step1",
        initial_data={"foo": "bar"},
        state_history={"step0": "ok"},
        client=client,
        actions=actions,
        input={"foo": "bar"},
        steps={"step0": "ok"},
        history=[{"event": "start"}],
        output={"val": 42},
        params={"max": 100},
        meta={"env": "test"},
    )

    # Clean attributes
    assert ctx.input == {"foo": "bar"}
    assert ctx.steps == {"step0": "ok"}
    assert ctx.history == [{"event": "start"}]
    assert ctx.output == {"val": 42}
    assert ctx.params == {"max": 100}
    assert ctx.meta == {"env": "test"}

    # Legacy attributes
    assert ctx.initial_data == {"foo": "bar"}
    assert ctx.state_history == {"step0": "ok"}

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


# --- NEGATIVE & BOUNDARY CASES ---


@pytest.mark.asyncio
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
    assert retrieved["initial_data"] == {"order_id": 999}
    assert retrieved["steps"] == {"init": {"status": "started"}}
    assert retrieved["state_history"] == {"init": {"status": "started"}}
    assert retrieved["history"] == [{"step": "init", "ts": 12345}]
    assert retrieved["params"] == {"api_key": "k-123"}
    assert retrieved["meta"] == {"trace_id": "tr-456"}

    # Atomic update in Redis
    def _add_step(s):
        s["steps"]["second"] = "done"
        s["output"] = {"final": True}
        return s

    await redis_storage.update_job_state_atomic(job_id, _add_step)
    updated = await redis_storage.get_job_state(job_id)
    assert updated["steps"]["second"] == "done"
    assert updated["state_history"]["second"] == "done"
    assert updated["output"] == {"final": True}
    assert updated["result"] == {"final": True}


def test_ensure_storage_zones_corrupted_and_empty_inputs():
    # 1. Completely empty dictionary
    state = {}
    ensure_storage_zones(state)
    assert state["input"] == {}
    assert state["initial_data"] == {}
    assert state["steps"] == {}
    assert state["state_history"] == {}
    assert state["history"] == []
    assert state["output"] is None
    assert state["params"] == {}
    assert state["meta"] == {}

    # 2. Corrupted data types (strings or integers where dicts or lists expected)
    corrupted = {
        "input": "not_a_dict",
        "initial_data": 12345,
        "steps": "corrupted_steps",
        "state_history": True,
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


def test_job_context_shared_dictionary_references():
    shared_input = {"key": "val"}
    shared_steps = {"st1": "res1"}

    ctx = JobContext(
        job_id="test-shared",
        current_state="st1",
        initial_data=shared_input,
        state_history=shared_steps,
        client=ClientConfig(token="t", plan="free", params={}),
        actions=ActionFactory(job_id="test-shared"),
        input=shared_input,
        steps=shared_steps,
    )

    # Both properties point to the exact same object in memory
    assert ctx.input is ctx.initial_data
    assert ctx.steps is ctx.state_history

    # Mutation via one alias is instantly reflected in the other
    ctx.steps["st2"] = "res2"
    assert ctx.state_history["st2"] == "res2"

    ctx.input["new_param"] = 123
    assert ctx.initial_data["new_param"] == 123

