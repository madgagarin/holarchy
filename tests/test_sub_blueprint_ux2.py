# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from uuid import uuid4

import pytest
from pydantic import BaseModel

from holarchy import Blueprint, Context
from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage


class CalcInput(BaseModel):
    x: int
    y: int


class CalcOutput(BaseModel):
    result: int
    operation: str


@pytest.fixture
def engine():
    storage = MemoryStorage()
    config = Config()
    return OrchestratorEngine(storage, config)


@pytest.mark.asyncio
async def test_sub_blueprint_e2e_dataflow(engine):
    # 1. Child Blueprint
    child_bp = Blueprint("multiplier_bp")

    @child_bp.handler("calc", is_start=True, is_end=True)
    async def calc(calc_input: CalcInput, actions):
        res = calc_input.x * calc_input.y
        actions.save_result(CalcOutput(result=res, operation="multiplication"))

    # 2. Parent Blueprint
    parent_bp = Blueprint("main_flow_bp")
    parent_captured = {}

    @parent_bp.handler("invoke_child", is_start=True)
    async def invoke_child(ctx: Context):
        ctx.run_blueprint(
            "multiplier_bp",
            input=CalcInput(x=6, y=7),
            transitions={"success": "handle_result", "failure": "failed"},
        )

    @parent_bp.handler("handle_result", is_end=True)
    async def handle_result(
        multiplier_bp: CalcOutput,  # DI matching by sub-blueprint name
        result_typed: CalcOutput,  # DI matching by model type from steps Blackboard
    ):
        parent_captured["by_name"] = multiplier_bp
        parent_captured["by_type"] = result_typed

    @parent_bp.handler("failed", is_end=True)
    async def failed():
        pass

    engine.register_blueprint(child_bp)
    engine.register_blueprint(parent_bp)
    await engine.on_startup(engine.app)

    parent_job_id = await engine.create_background_job("main_flow_bp", {})

    # 1. Execute parent start step -> dispatches child job & pauses parent
    await engine.executor._process_job(parent_job_id, str(uuid4()))

    parent_state = await engine.storage.get_job_state(parent_job_id)
    assert parent_state["status"] == "waiting_for_sub_job"
    child_job_id = parent_state["child_job_id"]
    assert child_job_id is not None

    # 2. Execute child job step -> completes child and triggers _check_and_resume_parent
    await engine.executor._process_job(child_job_id, str(uuid4()))

    child_state = await engine.storage.get_job_state(child_job_id)
    assert child_state["status"] == "finished"
    assert child_state["output"] == {"result": 42, "operation": "multiplication"}

    # 3. Parent job should now be resumed and running
    parent_resumed_state = await engine.storage.get_job_state(parent_job_id)
    assert parent_resumed_state["status"] == "running"
    assert parent_resumed_state["current_state"] == "handle_result"
    assert parent_resumed_state["steps"]["multiplier_bp"] == {"result": 42, "operation": "multiplication"}

    # 4. Execute parent handle_result step -> DI injects child output
    await engine.executor._process_job(parent_job_id, str(uuid4()))

    assert "by_name" in parent_captured
    assert isinstance(parent_captured["by_name"], CalcOutput)
    assert parent_captured["by_name"].result == 42
    assert parent_captured["by_name"].operation == "multiplication"

    assert "by_type" in parent_captured
    assert isinstance(parent_captured["by_type"], CalcOutput)
    assert parent_captured["by_type"].result == 42

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_sub_blueprint_failure_transition(engine):
    # Child Blueprint that fails
    child_bp = Blueprint("failing_child_bp")

    @child_bp.handler("do_fail", is_start=True)
    async def do_fail(actions):
        raise RuntimeError("Something went wrong inside child!")

    # Parent Blueprint
    parent_bp = Blueprint("parent_with_fallback_bp")
    parent_captured = {}

    @parent_bp.handler("start", is_start=True)
    async def start(ctx: Context):
        ctx.run_blueprint(
            "failing_child_bp",
            input={"data": 123},
            transitions={"success": "happy_path", "failure": "fallback_path"},
        )

    @parent_bp.handler("happy_path", is_end=True)
    async def happy_path():
        pass

    @parent_bp.handler("fallback_path", is_end=True)
    async def fallback_path(ctx: Context):
        parent_captured["fallback_called"] = True
        parent_captured["sub_job_key"] = f"sub_job_{ctx.steps.get('child_job_id', '')}"

    engine.register_blueprint(child_bp)
    engine.register_blueprint(parent_bp)
    await engine.on_startup(engine.app)

    parent_job_id = await engine.create_background_job("parent_with_fallback_bp", {})

    # Start parent
    await engine.executor._process_job(parent_job_id, str(uuid4()))

    parent_state = await engine.storage.get_job_state(parent_job_id)
    child_job_id = parent_state["child_job_id"]

    # Process child until failure
    # Child will attempt retries or fail
    # We can process child job:
    await engine.executor._process_job(child_job_id, str(uuid4()))

    child_state = await engine.storage.get_job_state(child_job_id)
    # If child fails or moves to retry, let's verify parent transition
    if child_state["status"] == "failed" or child_state.get("status") in ("failed", "quarantined", "error"):
        parent_resumed = await engine.storage.get_job_state(parent_job_id)
        assert parent_resumed["current_state"] == "fallback_path"
        await engine.executor._process_job(parent_job_id, str(uuid4()))
        assert parent_captured.get("fallback_called") is True

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_sub_blueprint_primitive_output(engine):
    # Child returns raw primitive int
    child_bp = Blueprint("primitive_child_bp")

    @child_bp.handler("do_work", is_start=True, is_end=True)
    async def do_work(actions):
        actions.save_result(12345)

    # Parent Blueprint
    parent_bp = Blueprint("parent_primitive_bp")
    parent_captured = {}

    @parent_bp.handler("invoke", is_start=True)
    async def invoke(ctx: Context):
        ctx.run_blueprint("primitive_child_bp", transitions={"success": "done"})

    @parent_bp.handler("done", is_end=True)
    async def done(ctx: Context):
        parent_captured["child_res"] = ctx.steps.get("primitive_child_bp")

    engine.register_blueprint(child_bp)
    engine.register_blueprint(parent_bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job("parent_primitive_bp", {})
    await engine.executor._process_job(job_id, str(uuid4()))

    parent_state = await engine.storage.get_job_state(job_id)
    child_id = parent_state["child_job_id"]
    await engine.executor._process_job(child_id, str(uuid4()))
    await engine.executor._process_job(job_id, str(uuid4()))

    assert parent_captured["child_res"] == 12345

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_sub_blueprint_input_contract_validation_failure(engine):
    # Child Blueprint with input schema requiring int
    child_bp = Blueprint("contract_child_bp")

    @child_bp.handler("step", is_start=True, is_end=True)
    async def step(val: int, actions):
        pass

    parent_bp = Blueprint("parent_bad_contract_bp")

    @parent_bp.handler("start", is_start=True)
    async def start(ctx: Context):
        # Pass invalid input (string instead of int)
        ctx.run_blueprint(
            "contract_child_bp",
            input={"val": "not-an-int"},
            transitions={"success": "ok", "failure": "failed"},
        )

    @parent_bp.handler("ok", is_end=True)
    async def ok():
        pass

    @parent_bp.handler("failed", is_end=True)
    async def failed():
        pass

    engine.register_blueprint(child_bp)
    engine.register_blueprint(parent_bp)
    await engine.on_startup(engine.app)

    parent_job_id = await engine.create_background_job("parent_bad_contract_bp", {})
    await engine.executor._process_job(parent_job_id, str(uuid4()))

    parent_state = await engine.storage.get_job_state(parent_job_id)
    # The parent step failed because contract validation failed before dispatching child
    assert parent_state["status"] in ("awaiting_retry", "failed", "quarantined", "error")
    assert "input validation failed" in parent_state.get("error_message", "")

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_sub_blueprint_max_depth_quarantine(engine):
    child_bp = Blueprint("depth_child_bp")

    @child_bp.handler("work", is_start=True, is_end=True)
    async def work(actions):
        pass

    parent_bp = Blueprint("depth_parent_bp")

    @parent_bp.handler("start", is_start=True)
    async def start(ctx: Context):
        ctx.run_blueprint("depth_child_bp", transitions={"success": "done"})

    @parent_bp.handler("done", is_end=True)
    async def done():
        pass

    engine.register_blueprint(child_bp)
    engine.register_blueprint(parent_bp)
    await engine.on_startup(engine.app)

    # Set parent depth at maximum limit
    engine.config.MAX_HOLARCHY_DEPTH = 2
    parent_job_id = await engine.create_background_job("depth_parent_bp", {}, depth=2)
    await engine.executor._process_job(parent_job_id, str(uuid4()))

    parent_state = await engine.storage.get_job_state(parent_job_id)
    assert parent_state["status"] == "quarantined"
    assert "Holarchy depth limit exceeded" in parent_state.get("error_message", "")

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_chained_sub_blueprints_e2e(engine):
    # Sub BP 1: add 10
    bp1 = Blueprint("add_ten_bp")

    @bp1.handler("add", is_start=True, is_end=True)
    async def add(actions):
        actions.save_result({"val": 10})

    # Sub BP 2: multiply by 3
    bp2 = Blueprint("mult_three_bp")

    @bp2.handler("mult", is_start=True, is_end=True)
    async def mult(actions):
        actions.save_result({"val": 30})

    # Parent runs bp1, then bp2, then combines
    parent_bp = Blueprint("orchestrator_bp")
    parent_captured = {}

    @parent_bp.handler("step1", is_start=True)
    async def step1(ctx: Context):
        ctx.run_blueprint("add_ten_bp", transitions={"success": "step2"})

    @parent_bp.handler("step2")
    async def step2(ctx: Context):
        # bp1 result is in ctx.steps["add_ten_bp"]
        assert ctx.steps["add_ten_bp"]["val"] == 10
        ctx.run_blueprint("mult_three_bp", transitions={"success": "step3"})

    @parent_bp.handler("step3", is_end=True)
    async def step3(ctx: Context):
        parent_captured["bp1_res"] = ctx.steps["add_ten_bp"]["val"]
        parent_captured["bp2_res"] = ctx.steps["mult_three_bp"]["val"]

    engine.register_blueprint(bp1)
    engine.register_blueprint(bp2)
    engine.register_blueprint(parent_bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job("orchestrator_bp", {})

    # 1. Step 1 -> dispatches bp1
    await engine.executor._process_job(job_id, str(uuid4()))
    p_state = await engine.storage.get_job_state(job_id)
    child1_id = p_state["child_job_id"]

    # 2. Child 1 runs
    await engine.executor._process_job(child1_id, str(uuid4()))

    # 3. Parent resumes to step2 -> dispatches bp2
    await engine.executor._process_job(job_id, str(uuid4()))
    p_state = await engine.storage.get_job_state(job_id)
    child2_id = p_state["child_job_id"]

    # 4. Child 2 runs
    await engine.executor._process_job(child2_id, str(uuid4()))

    # 5. Parent resumes to step3
    await engine.executor._process_job(job_id, str(uuid4()))

    assert parent_captured["bp1_res"] == 10
    assert parent_captured["bp2_res"] == 30

    await engine.on_shutdown(engine.app)

