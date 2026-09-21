# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import asyncio
import inspect
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from msgspec.json import encode as msgspec_encode
from orjson import dumps as orjson_dumps
from orjson import loads as orjson_loads

from holarchy.blueprint import Blueprint


@dataclass
class ReplayEvaluationReport:
    total_cases: int = 0
    matched_cases: int = 0
    drift_cases: int = 0
    fallback_cases: int = 0
    drift_rate: float = 0.0
    fallback_rate: float = 0.0
    details: list[dict[str, Any]] = field(default_factory=list)


def record_execution_receipt(
    receipt_or_path: Any,
    file_path_or_receipt: Any = None,
) -> None:
    """Appends an execution receipt to the local replay cases store."""
    if isinstance(receipt_or_path, (str, Path)):
        path_val = Path(receipt_or_path)
        receipt_val = file_path_or_receipt
    elif isinstance(file_path_or_receipt, (str, Path)):
        path_val = Path(file_path_or_receipt)
        receipt_val = receipt_or_path
    else:
        path_val = Path(".holarchy/replay/cases.jsonl")
        receipt_val = receipt_or_path

    path_val.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(receipt_val, "__struct_fields__"):
        line = msgspec_encode(receipt_val).decode("utf-8") + "\n"
    elif isinstance(receipt_val, dict):
        line = orjson_dumps(receipt_val).decode("utf-8") + "\n"
    elif is_dataclass(receipt_val):
        line = orjson_dumps(asdict(receipt_val)).decode("utf-8") + "\n"
    else:
        line = orjson_dumps(dict(receipt_val)).decode("utf-8") + "\n"

    with open(path_val, "a", encoding="utf-8") as f:
        f.write(line)


class MockReplayContext:
    """Mock context providing snapshot variables and inputs for decider replays."""

    def __init__(self, snapshot: dict[str, Any], job_id: str = "replay-job", step: str = "step"):
        self.input = snapshot.get("input", {})
        self.vars = snapshot.get("vars", {})
        self.job_id = job_id
        self.step = step

    def get(self, key: str, default: Any = None) -> Any:
        return self.input.get(key, default)


class ReplayTestRunner:
    """Deterministic in-memory evaluation runner for blueprint advisory routing."""

    def __init__(self, blueprint: Blueprint, cases_path: str | None = None):
        self.blueprint = blueprint
        self.cases_path = cases_path

    async def _evaluate_case(
        self,
        case: dict[str, Any],
    ) -> tuple[str, bool]:
        step = case.get("step")
        decider_name = case.get("decider_name") or step
        candidates = case.get("candidates") or []
        fallback = case.get("fallback")

        decider_info = self.blueprint._deciders.get(decider_name) or self.blueprint._deciders.get(step, {})
        if not candidates and "candidates" in decider_info:
            candidates = decider_info["candidates"]
        if not fallback and "fallback" in decider_info:
            fallback = decider_info["fallback"]

        fallback_str = str(fallback) if fallback else (candidates[0] if candidates else "unknown")

        func = decider_info.get("func") if isinstance(decider_info, dict) else None
        if not func:
            handlers = self.blueprint.handlers.get(step, [])
            if handlers:
                func = handlers[0].func

        if not func:
            return fallback_str, True

        timeout = decider_info.get("timeout_seconds", 3.0) if isinstance(decider_info, dict) else 3.0
        snapshot = case.get("context_snapshot") or {}
        ctx_mock = MockReplayContext(
            snapshot=snapshot,
            job_id=str(case.get("job_id") or case.get("correlation_id") or "replay"),
            step=str(step),
        )

        sig = inspect.signature(func)
        kwargs = {}
        if "candidates" in sig.parameters:
            kwargs["candidates"] = candidates
        if "ctx" in sig.parameters:
            kwargs["ctx"] = ctx_mock
        elif "context" in sig.parameters:
            kwargs["context"] = ctx_mock

        try:
            if kwargs:
                res = func(**kwargs)
            else:
                try:
                    res = func(candidates, ctx_mock)
                except TypeError:
                    res = func(ctx_mock)

            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=timeout)
            res_str = str(res)
            if res_str in [str(c) for c in candidates]:
                return res_str, False
            return fallback_str, True
        except Exception:
            return fallback_str, True

    def evaluate(self, cases_file_path: str | None = None) -> ReplayEvaluationReport:
        """Evaluates historical cases from JSONL file in memory synchronously."""
        path = cases_file_path or self.cases_path or ".holarchy/replay/cases.jsonl"
        if not os.path.exists(path):
            return ReplayEvaluationReport()

        cases: list[dict[str, Any]] = []
        with open(path, "rb") as f:
            for line in f:
                line = line.strip()
                if line:
                    cases.append(orjson_loads(line))

        if not cases:
            return ReplayEvaluationReport()

        report = ReplayEvaluationReport(total_cases=len(cases))

        async def _run_all() -> None:
            for case in cases:
                hist_chosen = case.get("chosen")
                eval_chosen, is_fallback = await self._evaluate_case(case)

                is_drift = eval_chosen != hist_chosen
                if is_drift:
                    report.drift_cases += 1
                else:
                    report.matched_cases += 1

                if is_fallback or case.get("fallback_triggered"):
                    report.fallback_cases += 1

                report.details.append({
                    "correlation_id": case.get("correlation_id"),
                    "step": case.get("step"),
                    "historical_chosen": hist_chosen,
                    "replayed_chosen": eval_chosen,
                    "is_drift": is_drift,
                    "is_fallback": is_fallback,
                })

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(asyncio.run, _run_all()).result()
        else:
            asyncio.run(_run_all())

        if report.total_cases > 0:
            report.drift_rate = report.drift_cases / report.total_cases
            report.fallback_rate = report.fallback_cases / report.total_cases

        return report


__all__ = [
    "ReplayEvaluationReport",
    "ReplayTestRunner",
    "record_execution_receipt",
]
