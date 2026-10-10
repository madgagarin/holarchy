# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from datetime import UTC, datetime
from os import environ
from traceback import format_exception
from typing import Any


def _classify_remediation(error_str: str) -> list[str]:
    """Generates actionable remediation advice based on error semantics."""
    s = error_str.lower()
    advice: list[str] = []

    if any(k in s for k in ("oom", "memory", "cuda", "allocation failed", "out of memory")):
        advice.append("Resource Exhaustion: VRAM/RAM capacity exceeded on host worker.")
        advice.append("Action: Re-queue task to a worker with larger memory or reduce payload batch size.")
    elif any(k in s for k in ("connection", "network", "timeout", "timed out")):
        advice.append("Network / Timeout Disruption: Connection failed or step exceeded allotted execution window.")
        advice.append("Action: Retry with exponential backoff or verify worker network connectivity.")
    elif any(k in s for k in ("validation", "contract", "schema", "invalid")):
        advice.append("Contract Mismatch: Payload failed input or output schema validation.")
        advice.append("Action: Verify schema types and argument names in step handler.")
    elif any(k in s for k in ("depth", "holarchy")):
        advice.append("Holarchy Limit: Max holarchy depth exceeded.")
        advice.append("Action: Ensure child blueprints do not enter recursive cycles.")
    elif any(k in s for k in ("policy", "permission", "forbidden", "unauthorized")):
        advice.append("Security Violation: Action disallowed by Zero Trust policy.")
        advice.append("Action: Review client permissions and allowed_skills policy.")
    else:
        advice.append("Step Execution Failure: Unhandled exception during handler execution.")
        advice.append("Action: Review handler traceback and ensure all external dependencies are available.")

    return advice


def _sanitize_secrets(data: Any) -> Any:
    """Recursively redacts sensitive keys (passwords, tokens, secrets) from diagnostic payloads."""
    if isinstance(data, dict):
        sanitized = {}
        sensitive_patterns = ("password", "token", "secret", "api_key", "authorization", "auth", "private_key")
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in sensitive_patterns):
                sanitized[k] = "***REDACTED***"

            else:
                sanitized[k] = _sanitize_secrets(v)
        return sanitized
    elif isinstance(data, list):
        return [_sanitize_secrets(item) for item in data]
    return data


def generate_evidence_card(
    job_state: dict[str, Any],
    error: Exception | str | None = None,
    current_state: str | None = None,
) -> dict[str, Any]:
    """Generates an Incident Evidence Card (Markdown + JSON) under strict read-only isolation.

    Ensures HOLARCHY_INTERNAL_AUDIT=1 is active to prevent recursive execution.
    """
    old_audit_env = environ.get("HOLARCHY_INTERNAL_AUDIT")
    environ["HOLARCHY_INTERNAL_AUDIT"] = "1"
    try:
        job_id = str(job_state.get("id") or "unknown_job")
        blueprint_name = str(job_state.get("blueprint_name") or "unknown_blueprint")
        status = str(job_state.get("status") or "failed")
        failed_step = str(current_state or job_state.get("current_state") or "unknown_step")
        worker_id = str(job_state.get("worker_id") or job_state.get("last_worker_id") or "local_orchestrator")
        timestamp = datetime.now(UTC).isoformat()

        if isinstance(error, Exception):
            root_cause = f"{type(error).__name__}: {error}"
            tb_lines = format_exception(type(error), error, error.__traceback__)
            stack_snippet = "".join(tb_lines[-4:]).strip()
        elif error:
            root_cause = str(error)
            stack_snippet = ""
        else:
            root_cause = str(job_state.get("error_message") or "Unknown failure")
            stack_snippet = ""

        remediation_steps = _classify_remediation(root_cause)

        steps_data = job_state.get("steps")
        completed_steps = list(steps_data.keys()) if isinstance(steps_data, dict) else []
        raw_input = job_state.get("input") or {}
        step_snapshot = {
            "input": _sanitize_secrets(raw_input),
            "completed_steps": completed_steps,
            "attempt": job_state.get("retries", 0) + 1,
        }

        d_dna_hash = str(job_state.get("current_hash") or job_state.get("parent_hash") or "genesis")

        md_card = (
            f"```\n"
            f"┌────────────────────────────────────────────────────────────────────────┐\n"
            f"│ 🛑 INCIDENT EVIDENCE CARD: Job {job_id} ({status})\n"
            f"├────────────────────────────────────────────────────────────────────────┤\n"
            f"│ • Blueprint:     {blueprint_name}\n"
            f"│ • Failed Step:   {failed_step} (Attempt {step_snapshot['attempt']})\n"
            f"│ • Worker Node:   {worker_id}\n"
            f"│ • Timestamp:     {timestamp}\n"
            f"│ • D-DNA Hash:    {d_dna_hash}\n"
            f"├────────────────────────────────────────────────────────────────────────┤\n"
            f"│ 🔍 ROOT CAUSE:\n"
            f"│    {root_cause}\n"
        )
        if stack_snippet:
            clean_stack = "\n│    ".join(stack_snippet.splitlines()[:3])
            md_card += f"│    Stack:\n│    {clean_stack}\n"

        md_card += (
            f"├────────────────────────────────────────────────────────────────────────┤\n"
            f"│ 📦 STEP SNAPSHOT:\n"
            f"│    Input: {step_snapshot['input']}\n"
            f"│    Completed: {step_snapshot['completed_steps']}\n"
            f"├────────────────────────────────────────────────────────────────────────┤\n"
            f"│ 💡 REMEDIATION:\n"
        )
        for r in remediation_steps:
            md_card += f"│    • {r}\n"

        md_card += "└────────────────────────────────────────────────────────────────────────┘\n```"

        json_data = {
            "job_id": job_id,
            "blueprint": blueprint_name,
            "status": status,
            "failed_step": failed_step,
            "worker_id": worker_id,
            "timestamp": timestamp,
            "root_cause": root_cause,
            "remediation": remediation_steps,
            "d_dna_hash": d_dna_hash,
            "step_snapshot": step_snapshot,
        }

        return {
            "markdown": md_card,
            "markdown_card": md_card,
            "json": json_data,
            "job_id": job_id,
            "failed_step": failed_step,
            "root_cause": root_cause,
            "remediation": remediation_steps,
            "remediation_steps": remediation_steps,
            "d_dna_hash": d_dna_hash,
            "step_snapshot": step_snapshot,
        }
    finally:
        if old_audit_env is None:
            environ.pop("HOLARCHY_INTERNAL_AUDIT", None)
        else:
            environ["HOLARCHY_INTERNAL_AUDIT"] = old_audit_env


__all__ = [
    "generate_evidence_card",
    "_classify_remediation",
]
