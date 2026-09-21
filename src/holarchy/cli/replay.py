# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import argparse
import sys
from importlib import import_module

from holarchy.blueprint import Blueprint
from holarchy.testing.replay import ReplayTestRunner


def run_replay(args: argparse.Namespace) -> None:
    """CLI handler for 'holarchy replay evaluate'."""
    app_str = args.app
    cases_path = args.cases or ".holarchy/replay/cases.jsonl"

    try:
        mod_name, obj_name = app_str.split(":")
        mod = import_module(mod_name)
        bp = getattr(mod, obj_name)
    except Exception as e:
        print(f"Error loading blueprint from '{app_str}': {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(bp, Blueprint):
        print(f"Error: '{app_str}' is not a Blueprint instance", file=sys.stderr)
        sys.exit(1)

    runner = ReplayTestRunner(bp)
    report = runner.evaluate(cases_path)

    print("════════════════════════════════════════════════════════════")
    print(f" 📊 REPLAY EVALUATION REPORT: {bp.name}")
    print("════════════════════════════════════════════════════════════")
    print(f" • Total Evaluated Cases:  {report.total_cases}")
    print(f" • Matched Decisions:      {report.matched_cases}")
    print(f" • Drifted Decisions:      {report.drift_cases} ({report.drift_rate:.1%})")
    print(f" • Fallbacks Triggered:    {report.fallback_cases} ({report.fallback_rate:.1%})")
    print("════════════════════════════════════════════════════════════")

    if report.drift_cases > 0:
        print("\n⚠️ Drift details:")
        for d in report.details:
            if d.get("is_drift"):
                h_ch = d.get('historical_chosen')
                r_ch = d.get('replayed_chosen')
                print(f"   - Step '{d.get('step')}': historical='{h_ch}' -> replayed='{r_ch}'")

    if report.drift_cases > 0 and getattr(args, "strict", False):
        sys.exit(1)
