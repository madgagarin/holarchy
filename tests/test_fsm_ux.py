# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from json import dumps, loads
from typing import Any

from fast_filter import F
from pytest import raises

from holarchy import Blueprint, Next, Skill, SkillInvocation, State, StatesGroup, StepScope


class OrderFlow(StatesGroup):
    init = State()
    payment = State()
    manual_review = State()
    finalize = State()
    failed = State()


def test_state_str_identity():
    s = State("my_state")
    assert isinstance(s, str)
    assert s == "my_state"
    assert str(s) == "my_state"
    assert s.state_name == "my_state"
    assert s.group_name is None


def test_states_group_auto_binding():
    assert OrderFlow.init == "OrderFlow:init"
    assert OrderFlow.init.state_name == "init"
    assert OrderFlow.init.group_name == "OrderFlow"
    assert isinstance(OrderFlow.init, State)
    assert isinstance(OrderFlow.init, str)

    # Membership tests
    assert "OrderFlow:payment" in OrderFlow
    assert "payment" in OrderFlow
    assert "unknown" not in OrderFlow

    # Iteration and len
    states = list(OrderFlow)
    assert len(states) == 5
    assert len(OrderFlow) == 5
    assert states[0] == OrderFlow.init


def test_skill_factory():
    ocr = Skill("document-ocr", timeout=30, fallback=OrderFlow.failed)
    assert repr(ocr) == "Skill('document-ocr', timeout=30, fallback=State(OrderFlow:failed))"

    inv = ocr(image_url="https://s3/doc.pdf", next=OrderFlow.finalize)
    assert isinstance(inv, SkillInvocation)
    assert inv.skill_name == "document-ocr"
    assert inv.params == {"image_url": "https://s3/doc.pdf"}
    assert inv.next_state == OrderFlow.finalize
    assert inv.on_failure == OrderFlow.failed
    assert inv.timeout == 30


def test_step_scope_cascading():
    context = type(
        "Ctx",
        (),
        {
            "input": {"order_id": 42, "amount": 150.0},
            "steps": {"verify": {"is_valid": True, "score": 95}},
            "job_id": "job-123",
        },
    )()

    current_data = {"score": 99, "extra": "foo"}

    scope = StepScope(context, current_data=current_data)

    # 1. Current data takes highest precedence
    assert scope.score == 99
    assert scope.extra == "foo"

    # 2. Input data fallback
    assert scope.amount == 150.0
    assert scope.order_id == 42

    # 3. Context attribute fallback
    assert scope.job_id == "job-123"

    # 4. Explicit prefixes
    assert scope.input["order_id"] == 42
    assert scope.steps["verify"]["score"] == 95
    assert scope.step("verify")["is_valid"] is True


def test_step_scope_with_fast_filter():
    context = type(
        "Ctx",
        (),
        {
            "input": {"amount": 500, "is_vip": True},
            "steps": {"score_step": {"risk": "low"}},
        },
    )()

    scope = StepScope(context)

    f1 = F.amount > 100
    assert bool(f1.resolve(scope)) is True

    f2 = F.is_vip & (F.amount > 1000)
    assert bool(f2.resolve(scope)) is False

    f3 = F.step("score_step")["risk"] == "low"
    assert bool(f3.resolve(scope)) is True


def test_blueprint_fsm_decorators_and_integrity():
    bp = Blueprint("ecommerce_flow")

    @bp.start(OrderFlow.init)
    async def init_step(ctx: Any):
        return Next(OrderFlow.payment)

    @bp.step(OrderFlow.payment, condition=F.amount > 50_000, on_success=OrderFlow.finalize, on_error=OrderFlow.failed)
    async def vip_pay(ctx: Any):
        return {"paid": True}

    @bp.step(OrderFlow.payment, on_success=OrderFlow.finalize, on_error=OrderFlow.failed)
    async def standard_pay(ctx: Any):
        return {"paid": True}

    @bp.end(OrderFlow.finalize, status="finished")
    async def finish(ctx: Any):
        return {"result": "success"}

    @bp.end(OrderFlow.failed, status="failed")
    async def fail(ctx: Any):
        return {"result": "failed"}

    assert bp.start_state == OrderFlow.init
    assert bp.end_states == {OrderFlow.finalize, OrderFlow.failed}
    assert bp.terminal_statuses[OrderFlow.finalize] == "finished"
    assert bp.terminal_statuses[OrderFlow.failed] == "failed"

    # Validate integrity does not raise!
    bp.validate_integrity()


def test_blueprint_step_without_args_uses_function_name():
    bp = Blueprint("simple_flow")

    @bp.start
    async def start(ctx: Any):
        return Next("done")

    @bp.end
    async def done(ctx: Any):
        return {"status": "ok"}

    assert bp.start_state == "start"
    assert bp.end_states == {"done"}
    bp.validate_integrity()


# --- NEGATIVE & BOUNDARY CASES ---


def test_state_json_serialization_and_hashability():
    s = OrderFlow.init
    serialized = dumps({"state": s})
    assert serialized == '{"state": "OrderFlow:init"}'
    deserialized = loads(serialized)
    assert deserialized["state"] == s
    assert deserialized["state"] == "OrderFlow:init"

    state_set = {OrderFlow.init, OrderFlow.payment, OrderFlow.init}
    assert len(state_set) == 2
    assert OrderFlow.init in state_set

    state_dict = {OrderFlow.init: "first", "OrderFlow:init": "second"}
    assert len(state_dict) == 1
    assert state_dict[OrderFlow.init] == "second"


def test_states_group_multiple_and_comparison():
    class PaymentFlow(StatesGroup):
        init = State()
        done = State()

    assert PaymentFlow.init == "PaymentFlow:init"
    assert OrderFlow.init != PaymentFlow.init
    assert PaymentFlow.init.group_name == "PaymentFlow"
    assert PaymentFlow.init.state_name == "init"


def test_blueprint_integrity_negative_missing_start():
    bp = Blueprint("no_start_bp")

    @bp.step("step1")
    async def s1(ctx: Any):
        pass

    with raises(ValueError, match="must have exactly one start state"):
        bp.validate()


def test_blueprint_integrity_negative_unknown_transition_target():
    bp = Blueprint("broken_transition_bp")

    @bp.start("start")
    async def start(ctx: Any):
        return Next("non_existent_destination")

    with raises(ValueError, match="non_existent_destination"):
        bp.validate()


def test_blueprint_integrity_negative_unreachable_orphaned_state():
    bp = Blueprint("unreachable_bp")

    @bp.start("start")
    async def start(ctx: Any):
        return Next("done")

    @bp.end("done")
    async def done(ctx: Any):
        pass

    @bp.step("orphaned_state")
    async def orphaned(ctx: Any):
        pass

    with raises(ValueError, match="unreachable states"):
        bp.validate()


def test_step_scope_negative_and_none_handling():
    # 1. Scope initialized with None
    scope = StepScope(None)
    assert scope.any_missing_prop is None
    assert scope["any_missing_key"] is None
    assert scope.input == {}
    assert scope.steps == {}

    # 2. Scope with empty dicts and None values
    empty_context = type("EmptyCtx", (), {"input": None, "steps": None, "meta": None})()
    scope2 = StepScope(empty_context, current_data=None)
    assert scope2.non_existent is None

    # 3. Fast filter resolving missing property returns False safely without crash
    f = F.missing_number > 100
    assert bool(f.resolve(scope2)) is False

    # 4. Fast filter comparing None value
    context_with_none = type("NoneCtx", (), {"input": {"val": None}})()
    scope3 = StepScope(context_with_none)
    f_none = F.val == 42
    assert bool(f_none.resolve(scope3)) is False


def test_skill_edge_cases_falsy_params_and_repr():
    # 1. Skill with no fallback
    simple_skill = Skill("simple-worker")
    assert repr(simple_skill) == "Skill('simple-worker', timeout=None, fallback=None)"

    # 2. Falsy parameters (0, False, empty string, None) must be preserved exactly
    inv = simple_skill(count=0, active=False, note="", tag=None)
    assert inv.params == {"count": 0, "active": False, "note": "", "tag": None}
    assert inv.next_state is None
    assert inv.on_failure is None
    assert inv.timeout is None
