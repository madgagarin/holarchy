# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import asyncio
import sys
import types
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rxon.models import ExecutionReceipt

from holarchy.blueprint import Blueprint
from holarchy.cli.replay import run_replay
from holarchy.context import ActionFactory
from holarchy.data_types import JobContext
from holarchy.executor import JobExecutor
from holarchy.testing.replay import ReplayEvaluationReport, ReplayTestRunner, record_execution_receipt


@pytest.fixture
def mock_executor():
    engine = MagicMock()
    history = AsyncMock()
    storage = AsyncMock()
    engine.storage = storage
    engine.history_storage = history
    engine.blueprints = {}
    engine.blueprint_contracts = {}
    engine.config.JOB_MAX_RETRIES = 3
    engine.config.S3_AUTO_CLEANUP = False
    engine.app = {}
    engine.worker_service = None
    engine.on_job_finished = []
    engine.send_job_webhook = AsyncMock()
    metrics = MagicMock()
    executor = JobExecutor(engine, history, metrics=metrics)
    executor.dispatcher = AsyncMock()
    return executor


@pytest.mark.asyncio
async def test_decide_positive_selection(tmp_path: Path) -> None:
    cases_file = tmp_path / "cases.jsonl"
    bp = Blueprint("test_decide_pos")

    @bp.decide("pick_strategy")
    async def decider_fn(candidates: list[str], ctx: Any) -> str:
        return "fast_lane"

    af = ActionFactory(job_id="job-101", blueprint=bp)
    chosen = await af.decide("pick_strategy", candidates=["fast_lane", "deep_lane"], fallback="deep_lane")
    assert chosen == "fast_lane"

    receipt = af.last_receipt
    assert receipt is not None
    assert receipt.decider_name == "pick_strategy"
    assert receipt.chosen == "fast_lane"
    assert receipt.fallback_triggered is False
    assert receipt.reason == "decider_selection"

    # Record and verify persistence
    record_execution_receipt(receipt, str(cases_file))
    assert cases_file.exists()
    lines = cases_file.read_text().strip().split("\n")
    assert len(lines) == 1
    assert "fast_lane" in lines[0]


@pytest.mark.asyncio
async def test_decide_timeout_fail_open() -> None:
    bp = Blueprint("test_decide_timeout")

    @bp.decide("slow_decider", timeout_seconds=0.05)
    async def slow_decider(candidates: list[str], ctx: Any) -> str:
        await asyncio.sleep(0.5)
        return "fast"

    af = ActionFactory(job_id="job-102", blueprint=bp)
    chosen = await af.decide("slow_decider", candidates=["fast", "slow"], fallback="slow")
    assert chosen == "slow"

    receipt = af.last_receipt
    assert receipt is not None
    assert receipt.fallback_triggered is True
    assert receipt.reason == "timeout"
    assert receipt.chosen == "slow"


@pytest.mark.asyncio
async def test_decide_exception_fail_open() -> None:
    bp = Blueprint("test_decide_exc")

    @bp.decide("buggy_decider")
    async def buggy_decider(candidates: list[str], ctx: Any) -> str:
        raise ValueError("Model unavailable")

    af = ActionFactory(job_id="job-103", blueprint=bp)
    chosen = await af.decide("buggy_decider", candidates=["a", "b"], fallback="b")
    assert chosen == "b"

    receipt = af.last_receipt
    assert receipt is not None
    assert receipt.fallback_triggered is True
    assert receipt.reason == "exception"
    assert "Model unavailable" in (receipt.error or "")


@pytest.mark.asyncio
async def test_decide_invalid_candidate_fail_open() -> None:
    bp = Blueprint("test_decide_invalid")

    @bp.decide("hallucinating_decider")
    async def hallucinating_decider(candidates: list[str], ctx: Any) -> str:
        return "non_existent_option"

    af = ActionFactory(job_id="job-104", blueprint=bp)
    chosen = await af.decide("hallucinating_decider", candidates=["a", "b"], fallback="a")
    assert chosen == "a"

    receipt = af.last_receipt
    assert receipt is not None
    assert receipt.fallback_triggered is True
    assert receipt.reason == "invalid_choice"


@pytest.mark.asyncio
async def test_decide_unregistered_decider_fail_open() -> None:
    bp = Blueprint("test_decide_unreg")

    af = ActionFactory(job_id="job-105", blueprint=bp)
    chosen = await af.decide("missing_decider", candidates=["x", "y"], fallback="y")
    assert chosen == "y"

    receipt = af.last_receipt
    assert receipt is not None
    assert receipt.fallback_triggered is True
    assert receipt.reason == "unregistered_decider"


@pytest.mark.asyncio
async def test_decide_via_job_executor(mock_executor) -> None:
    bp = Blueprint(name="executor_decide_bp")

    @bp.decide("route_calc")
    async def route_calc(candidates: list[str], ctx: Any) -> str:
        return "step_b"

    @bp.start("step_a")
    async def step_a(actions: ActionFactory, context: JobContext) -> Any:
        chosen = await context.decide(candidates=["step_b", "step_c"], fallback="step_c", intent="route_calc")
        if chosen == "step_b":
            actions.go_to("step_b")
        else:
            actions.go_to("step_c")
        return {"chosen": chosen}

    @bp.end("step_b")
    async def step_b() -> Any:
        return {"status": "ok_b"}

    @bp.end("step_c")
    async def step_c() -> Any:
        return {"status": "ok_c"}

    bp.add_transition("step_a", "step_b")
    bp.add_transition("step_a", "step_c")
    bp.validate()
    mock_executor.engine.blueprints["executor_decide_bp"] = bp

    job_id = "job-decide-01"
    job_state = {
        "id": job_id,
        "blueprint_name": "executor_decide_bp",
        "current_state": "step_a",
        "status": "running",
        "steps": {},
        "state_history": {},
        "input": {},
        "initial_data": {},
    }
    mock_executor.storage.get_job_state.return_value = job_state
    mock_executor.storage.ack_job = AsyncMock()

    await mock_executor._process_job(job_id, "msg-1")

    # Step a should transition to step_b as chosen by decider
    assert job_state["steps"]["step_a"]["chosen"] == "step_b"


def test_replay_runner_evaluation(tmp_path: Path) -> None:
    cases_file = tmp_path / "replay_cases.jsonl"
    bp = Blueprint("eval_bp")

    @bp.decide("route_step")
    async def route_step(candidates: list[str], ctx: Any) -> str:
        job_input = getattr(ctx, "input", {}) or {}
        return "alt" if job_input.get("bias") == "alt" else "main"

    # Write 3 historical cases
    receipt1 = ExecutionReceipt(
        correlation_id="j1",
        step="step_1",
        decider_name="route_step",
        candidates=["main", "alt"],
        fallback="main",
        chosen="main",
        fallback_triggered=False,
        reason="decider_selection",
        context_snapshot={"input": {"bias": "default"}},
    )
    receipt2 = ExecutionReceipt(
        correlation_id="j2",
        step="step_1",
        decider_name="route_step",
        candidates=["main", "alt"],
        fallback="main",
        chosen="alt",
        fallback_triggered=False,
        reason="decider_selection",
        context_snapshot={"input": {"bias": "alt"}},
    )
    # Drift case: historical recorded 'main', but replayed logic will output 'alt'
    receipt3 = ExecutionReceipt(
        correlation_id="j3",
        step="step_1",
        decider_name="route_step",
        candidates=["main", "alt"],
        fallback="main",
        chosen="main",
        fallback_triggered=False,
        reason="decider_selection",
        context_snapshot={"input": {"bias": "alt"}},
    )

    record_execution_receipt(receipt1, str(cases_file))
    record_execution_receipt(receipt2, str(cases_file))
    record_execution_receipt(receipt3, str(cases_file))

    runner = ReplayTestRunner(blueprint=bp, cases_path=str(cases_file))
    report: ReplayEvaluationReport = runner.evaluate()

    assert report.total_cases == 3
    assert report.matched_cases == 2
    assert report.drift_cases == 1
    assert abs(report.drift_rate - (1 / 3)) < 0.01
    assert report.fallback_cases == 0


def test_replay_cli_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases_file = tmp_path / "replay_cases.jsonl"
    receipt = ExecutionReceipt(
        correlation_id="j1",
        step="step_1",
        decider_name="route_step",
        candidates=["main", "alt"],
        fallback="main",
        chosen="main",
        fallback_triggered=False,
        reason="decider_selection",
        context_snapshot={"input": {"bias": "default"}},
    )
    record_execution_receipt(receipt, str(cases_file))

    mod = types.ModuleType("dummy_cli_test_mod")
    cli_bp = Blueprint("cli_test_bp")

    @cli_bp.decide("route_step")
    def route_fn(candidates: list[str], ctx: Any) -> str:
        return "main"

    mod.test_bp = cli_bp  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dummy_cli_test_mod", mod)

    args = Namespace(
        app="dummy_cli_test_mod:test_bp",
        cases=str(cases_file),
        strict=False,
    )
    run_replay(args)
