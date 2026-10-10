# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from pytest import raises

from holarchy.blueprint import Blueprint


def test_valid_blueprint_integrity():
    """Tests that a correctly defined blueprint passes integrity validation."""
    bp = Blueprint("valid_bp")

    @bp.start
    async def start(actions):
        actions.go_to("next")

    @bp.step("next")
    async def next_handler(actions):
        actions.dispatch_task("task", params={}, transitions={"success": "end"})

    @bp.end("end")
    async def end():
        pass

    # This should not raise any exception
    bp.validate()


def test_dangling_transition():
    """Tests that a transition to a non-existent state raises ValueError."""
    bp = Blueprint("dangling_bp")

    @bp.start
    async def start(actions):
        actions.go_to("non_existent_state")

    with raises(ValueError) as excinfo:
        bp.validate()

    assert "has a dangling transition" in str(excinfo.value)
    assert "leads to non-existent state 'non_existent_state'" in str(excinfo.value)


def test_unreachable_state():
    """Tests that a state that cannot be reached from 'start' raises ValueError."""
    bp = Blueprint("unreachable_bp")

    @bp.start
    async def start(actions):
        actions.go_to("end")

    @bp.end("end")
    async def end():
        pass

    @bp.step("dead_code")
    async def dead_code():
        pass

    with raises(ValueError) as excinfo:
        bp.validate()

    assert "has unreachable states: dead_code" in str(excinfo.value)


def test_aggregator_reachability():
    """Tests that aggregator states are correctly identified as reachable."""
    bp = Blueprint("aggregator_bp")

    @bp.start
    async def start(actions):
        actions.dispatch_parallel(tasks=[], aggregate_into="aggregator")

    @bp.aggregator("aggregator")
    async def agg(actions):
        actions.go_to("end")

    @bp.end("end")
    async def end():
        pass

    # Should pass
    bp.validate()


def test_complex_transitions_reachability():
    """Tests run_blueprint and await_human_approval transitions."""
    bp = Blueprint("complex_bp")

    @bp.start
    async def start(actions):
        actions.run_blueprint("other", input={}, transitions={"success": "step2"})

    @bp.step("step2")
    async def step2(actions):
        actions.await_human_approval("email", "Verify", transitions={"approved": "end"})

    @bp.end("end")
    async def end():
        pass

    # Should pass
    bp.validate()
