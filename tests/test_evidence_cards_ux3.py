# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from os import environ

from pytest import mark
from rxon.constants import (
    ERROR_CODE_CONTRACT_VIOLATION,
)

from holarchy.blueprint import Blueprint
from holarchy.diagnostic import _classify_remediation, generate_evidence_card
from holarchy.engine import ENGINE_KEY


def test_classify_remediation() -> None:
    # Transient / network
    rem = _classify_remediation("Connection timeout to remote worker")
    assert any("retry" in s.lower() for s in rem)

    # Permanent / contract
    rem2 = _classify_remediation(f"Contract mismatch: {ERROR_CODE_CONTRACT_VIOLATION}")
    assert any("contract" in s.lower() or "schema" in s.lower() for s in rem2)

    # Resource
    rem3 = _classify_remediation("Memory quota exceeded: out of memory")
    assert any("resource" in s.lower() or "scale" in s.lower() for s in rem3)

    # Generic
    rem4 = _classify_remediation("Unexpected internal flaw")
    assert len(rem4) > 0


def test_generate_evidence_card_structure_and_zero_trust_isolation() -> None:
    job_state = {
        "id": "job-evidence-test-01",
        "current_state": "step_payment",
        "input": {"amount": 100, "user_id": "usr_99"},
        "steps": {"step_cart": {"items": ["book"]}},
        "retries": 1,
        "current_hash": "hash_abc_123",
        "d_dna": "dna_seq_456",
    }

    # Ensure HOLARCHY_INTERNAL_AUDIT is not set initially
    environ.pop("HOLARCHY_INTERNAL_AUDIT", None)

    # Simulate error
    err = RuntimeError("Temporary network failure when contacting payment gateway")
    card = generate_evidence_card(job_state=job_state, error=err, current_state="step_payment")

    # Verify audit flag was cleaned up
    assert environ.get("HOLARCHY_INTERNAL_AUDIT") is None

    # Check Markdown Card structure
    assert "INCIDENT EVIDENCE CARD" in card["markdown"]
    assert "job-evidence-test-01" in card["markdown"]
    assert "step_payment" in card["markdown"]
    assert "Temporary network failure" in card["markdown"]
    assert "REMEDIATION" in card["markdown"]

    # Check JSON structured details
    assert card["job_id"] == "job-evidence-test-01"
    assert card["failed_step"] == "step_payment"
    assert "Temporary network failure" in card["root_cause"]
    assert card["step_snapshot"]["input"] == {"amount": 100, "user_id": "usr_99"}
    assert card["step_snapshot"]["completed_steps"] == ["step_cart"]
    assert card["step_snapshot"]["attempt"] == 2
    assert len(card["remediation_steps"]) > 0


def test_generate_evidence_card_redacts_sensitive_credentials() -> None:
    job_state = {
        "id": "job-secret-leak-test",
        "current_state": "step_auth",
        "input": {
            "user": "alice",
            "password": "super-secret-password-123",
            "auth_token": "bearer eyJhbGciOiJIUzI1Ni...",
            "nested": {
                "api_key": "sk-proj-xyz987",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----...",
                "safe_info": "visible_value",
            },
            "items_list": [{"token": "tok_abc"}, "normal_string"],
            "tokens_list": ["secret1", "secret2"],
        },
    }

    card = generate_evidence_card(job_state=job_state, error="Authentication error", current_state="step_auth")

    # In JSON
    snapshot_input = card["step_snapshot"]["input"]
    assert snapshot_input["user"] == "alice"
    assert snapshot_input["password"] == "***REDACTED***"
    assert snapshot_input["auth_token"] == "***REDACTED***"
    assert snapshot_input["nested"]["api_key"] == "***REDACTED***"
    assert snapshot_input["nested"]["private_key"] == "***REDACTED***"
    assert snapshot_input["nested"]["safe_info"] == "visible_value"
    assert snapshot_input["tokens_list"] == "***REDACTED***"
    assert snapshot_input["items_list"][0]["token"] == "***REDACTED***"
    assert snapshot_input["items_list"][1] == "normal_string"

    # In Markdown card
    md = card["markdown"]
    assert "super-secret-password-123" not in md
    assert "sk-proj-xyz987" not in md
    assert "bearer eyJhbGciOiJIUzI1Ni" not in md
    assert "tok_abc" not in md
    assert "***REDACTED***" in md


def create_dummy_bp() -> Blueprint:
    bp = Blueprint("dummy", api_endpoint="/dummy", api_version="v1")

    @bp.start("start")
    async def start(actions):
        pass

    return bp


@mark.parametrize("app", [{"extra_blueprints": [create_dummy_bp()]}], indirect=True)
@mark.asyncio
async def test_api_get_job_evidence(aiohttp_client, app) -> None:
    engine = app[ENGINE_KEY]
    client = await aiohttp_client(app)
    headers = {"X-Client-Token": "user_token_vip"}

    job_id = "job-evidence-01"
    card_dict = {
        "markdown": "### INCIDENT CARD",
        "markdown_card": "### INCIDENT CARD",
        "json": {"job_id": job_id, "root_cause": "Timeout"},
    }
    await engine.storage.save_job_state(
        job_id,
        {
            "id": job_id,
            "status": "failed",
            "evidence": card_dict,
            "client_config": {"token": "user_token_vip"},
        },
    )

    # A) Existing card
    resp = await client.get(f"/api/v1/jobs/{job_id}/evidence", headers=headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["job_id"] == job_id

    # B) Markdown format
    resp_md = await client.get(f"/api/v1/jobs/{job_id}/evidence?format=md", headers=headers)
    assert resp_md.status == 200
    text_md = await resp_md.text()
    assert "### INCIDENT CARD" in text_md

    # C) Auto-generated card on quarantined job
    job_id_2 = "job-quarantine-02"
    await engine.storage.save_job_state(
        job_id_2,
        {
            "id": job_id_2,
            "status": "quarantined",
            "error_message": "Network dropped",
            "current_state": "step_net",
            "client_config": {"token": "user_token_vip"},
        },
    )
    resp2 = await client.get(f"/api/v1/jobs/{job_id_2}/evidence", headers=headers)
    assert resp2.status == 200
    data2 = await resp2.json()
    assert data2["job_id"] == job_id_2

    # D) Unknown job returns 404
    resp3 = await client.get("/api/v1/jobs/non-existent-job/evidence", headers=headers)
    assert resp3.status == 404
