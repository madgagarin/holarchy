# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from unittest.mock import MagicMock

from fast_filter import F
from pytest import fixture, raises

from holarchy.blueprint import Blueprint, ConditionalHandler
from holarchy.context import ActionFactory
from holarchy.data_types import ClientConfig, JobContext


@fixture
def mock_blueprint():
    return MagicMock()


@fixture
def conditional_handler(mock_blueprint):
    """Handler that passes when input.status == 'completed'."""
    condition = F.input["status"] == "completed"
    return ConditionalHandler(mock_blueprint, "start", lambda: None, condition)


def test_conditional_handler_evaluate_true(conditional_handler):
    context = MagicMock()
    context.input = {"status": "completed"}
    assert conditional_handler.evaluate(context) is True


def test_conditional_handler_evaluate_false(conditional_handler):
    context = MagicMock()
    context.input = {"status": "pending"}
    assert conditional_handler.evaluate(context) is False


def test_conditional_handler_evaluate_missing_area(conditional_handler):
    """Missing attribute must return False gracefully, not raise."""
    context = MagicMock(spec=[])  # no attributes at all
    assert conditional_handler.evaluate(context) is False


def test_conditional_handler_evaluate_missing_field(conditional_handler):
    context = MagicMock()
    context.input = {}
    assert conditional_handler.evaluate(context) is False


def test_conditional_handler_evaluate_complex_condition(mock_blueprint):
    """FastF allows arbitrary expressions impossible with old string syntax."""
    condition = (F.data["score"] >= 80) & (F.data["active"] == True)  # noqa: E712
    handler = ConditionalHandler(mock_blueprint, "check", lambda: None, condition)

    context_ok = MagicMock()
    context_ok.data = {"score": 90, "active": True}
    assert handler.evaluate(context_ok) is True

    context_fail = MagicMock()
    context_fail.data = {"score": 70, "active": True}
    assert handler.evaluate(context_fail) is False


@fixture
def blueprint():
    return Blueprint("test_bp")


def test_handler_decorator_condition_with_fastf(blueprint):
    @blueprint.handler("start", F.input["status"] == "completed")
    def handler(context, actions):
        pass

    assert len(blueprint.conditional_handlers) == 1
    assert blueprint.conditional_handlers[0].state == "start"


def test_handler_decorator_condition_evaluates_correctly(blueprint):
    @blueprint.handler("start", F.result["ok"] == True)  # noqa: E712
    def handler(context, actions):
        pass

    ctx_true = MagicMock()
    ctx_true.result = {"ok": True}
    assert blueprint.conditional_handlers[0].evaluate(ctx_true) is True

    ctx_false = MagicMock()
    ctx_false.result = {"ok": False}
    assert blueprint.conditional_handlers[0].evaluate(ctx_false) is False


def test_handler_decorator_condition_invert(blueprint):
    @blueprint.handler("start", ~(F.error["code"] == 404))
    def handler(context, actions):
        pass

    ctx = MagicMock()
    ctx.error = {"code": 404}
    assert blueprint.conditional_handlers[0].evaluate(ctx) is False

    ctx2 = MagicMock()
    ctx2.error = {"code": 500}
    assert blueprint.conditional_handlers[0].evaluate(ctx2) is True


def test_handler_decorator_duplicate_handler(blueprint):
    @blueprint.handler("start")
    def handler1(context, actions):
        pass

    with raises(ValueError, match="Default handler for state 'start' is already registered."):

        @blueprint.handler("start")
        def handler2(context, actions):
            pass


def test_handler_decorator_duplicate_start_state(blueprint):
    @blueprint.start("start")
    def handler1(context, actions):
        pass

    with raises(ValueError, match="Blueprint 'test_bp' already has a start state: 'start'."):

        @blueprint.start("another_start")
        def handler2(context, actions):
            pass


def test_add_data_store_duplicate(blueprint):
    blueprint.add_data_store("my_store", {})
    with raises(ValueError, match="Data store with name 'my_store' already exists."):
        blueprint.add_data_store("my_store", {})


def test_aggregator_duplicate(blueprint):
    @blueprint.aggregator("start")
    def aggregator1(context, actions):
        pass

    with raises(ValueError, match="Aggregator for state 'start' is already registered."):

        @blueprint.aggregator("start")
        def aggregator2(context, actions):
            pass


def test_validate_no_start_state(blueprint):
    with raises(ValueError, match="Blueprint 'test_bp' must have exactly one start state."):
        blueprint.validate()


def test_find_handler_no_handler(blueprint):
    with raises(
        ValueError, match="No suitable handler found for state 'start' in blueprint 'test_bp' for the given context."
    ):
        blueprint.find_handler("start", MagicMock())


def test_render_graph_with_filename(blueprint, tmp_path):
    @blueprint.start("start")
    def handler(context, actions):
        actions.go_to("end")

    @blueprint.end("end")
    def end_handler(context, actions):
        pass

    filename = tmp_path / "graph"
    blueprint.render_graph(output_filename=str(filename))
    assert (tmp_path / "graph.png").exists()


def test_render_graph_no_filename(blueprint):
    @blueprint.start("start")
    def handler(context, actions):
        actions.go_to("end")

    @blueprint.end("end")
    def end_handler(context, actions):
        pass

    source = blueprint.render_graph()
    assert "digraph" in source


def test_handler_decorator_direct_condition_with_state_name(blueprint):
    @blueprint.step("start", F.input["status"] == "completed")
    def handler(context, actions):
        pass

    assert len(blueprint.conditional_handlers) == 1
    assert blueprint.conditional_handlers[0].state == "start"

    ctx_true = MagicMock()
    ctx_true.output = {}
    ctx_true.input = {"status": "completed"}
    assert blueprint.conditional_handlers[0].evaluate(ctx_true) is True


def test_handler_decorator_direct_condition_inferred_name(blueprint):
    @blueprint.step(condition=F.input["status"] == "completed")
    def my_custom_state(context, actions):
        pass

    assert len(blueprint.conditional_handlers) == 1
    assert blueprint.conditional_handlers[0].state == "my_custom_state"

    ctx_true = MagicMock()
    ctx_true.input = {"status": "completed"}
    assert blueprint.conditional_handlers[0].evaluate(ctx_true) is True


def test_handler_decorator_direct_condition_keyword_arg(blueprint):
    @blueprint.step(condition=F.input["status"] == "completed")
    def my_custom_state(context, actions):
        pass

    assert len(blueprint.conditional_handlers) == 1
    assert blueprint.conditional_handlers[0].state == "my_custom_state"


def test_handler_decorator_direct_condition_with_is_start(blueprint):
    @blueprint.start(condition=F.input["status"] == "completed")
    def start_handler(context, actions):
        pass

    assert len(blueprint.conditional_handlers) == 1
    assert blueprint.start_state == "start_handler"


def test_step_decorator_with_condition_and_explicit_transitions(blueprint):
    @blueprint.step("validate", F.score >= 80, on_success="vip_processing", on_error="reject")
    def vip_validator(context, actions):
        pass

    assert len(blueprint.conditional_handlers) == 1
    ch = blueprint.conditional_handlers[0]
    assert ch.state == "validate"
    assert vip_validator._on_success == "vip_processing"
    assert vip_validator._on_error == "reject"
    assert "vip_processing" in blueprint._explicit_transitions["validate"]
    assert "reject" in blueprint._explicit_transitions["validate"]

    # Verify to_dag contains the edges generated by on_success/on_error
    dag = blueprint.to_dag()
    edge_pairs = {(e["from"], e["to"]) for e in dag["edges"]}
    assert ("validate", "vip_processing") in edge_pairs
    assert ("validate", "reject") in edge_pairs


def test_first_match_wins_precedence_order(blueprint):
    @blueprint.handler("route", F.score >= 50)
    def handle_medium(actions):
        return "medium"

    @blueprint.handler("route", F.score >= 80)
    def handle_high(actions):
        return "high"

    @blueprint.handler("route")
    def handle_fallback(actions):
        return "fallback"

    # Score 90 matches both F.score >= 50 and F.score >= 80
    # First-match-wins ensures the first registered handler is chosen
    ctx_high = MagicMock()
    ctx_high.score = 90
    assert blueprint.find_handler("route", ctx_high) is handle_medium

    # Score 60 matches only first handler
    ctx_med = MagicMock()
    ctx_med.score = 60
    assert blueprint.find_handler("route", ctx_med) is handle_medium

    # Score 30 matches neither handler -> falls back to default handler
    ctx_low = MagicMock()
    ctx_low.score = 30
    assert blueprint.find_handler("route", ctx_low) is handle_fallback


def test_conditional_handlers_with_real_job_context(blueprint):
    @blueprint.handler("eval_step", F.input["amount"] > 1000)
    def handle_large(context, actions):
        return "large"

    @blueprint.handler("eval_step", F.steps["prev_task"]["passed"] == True)  # noqa: E712
    def handle_passed(context, actions):
        return "passed"

    client_cfg = ClientConfig(token="tok-1", plan="enterprise", params={})
    actions = ActionFactory("job-42")

    job_ctx_large = JobContext(
        job_id="job-42",
        current_state="eval_step",
        input={"amount": 2000},
        steps={},
        output=None,
        history=[],
        params={},
        client=client_cfg,
        actions=actions,
    )
    assert blueprint.find_handler("eval_step", job_ctx_large) is handle_large

    job_ctx_passed = JobContext(
        job_id="job-42",
        current_state="eval_step",
        input={"amount": 500},
        steps={"prev_task": {"passed": True}},
        output=None,
        history=[],
        params={},
        client=client_cfg,
        actions=actions,
    )
    assert blueprint.find_handler("eval_step", job_ctx_passed) is handle_passed
