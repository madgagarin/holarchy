# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import argparse
import sys

from holarchy.cli.replay import run_replay


def main() -> None:
    parser = argparse.ArgumentParser(prog="holarchy", description="Holarchy Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # replay subcommand
    replay_parser = subparsers.add_parser("replay", help="Offline deterministic replay commands")
    replay_sub = replay_parser.add_subparsers(dest="subcommand", help="Replay subcommands")

    eval_parser = replay_sub.add_parser("evaluate", help="Evaluate offline cases against blueprint")
    eval_parser.add_argument("--app", required=True, help="Target blueprint path (e.g. 'my_flow:bp')")
    eval_parser.add_argument("--cases", default=".holarchy/replay/cases.jsonl", help="Path to cases.jsonl")
    eval_parser.add_argument("--strict", action="store_true", help="Exit with non-zero code on any drift")

    args = parser.parse_args()

    if args.command == "replay" and getattr(args, "subcommand", None) == "evaluate":
        run_replay(args)
    else:
        parser.print_help()
        sys.exit(0 if args.command is None else 1)


if __name__ == "__main__":
    main()
