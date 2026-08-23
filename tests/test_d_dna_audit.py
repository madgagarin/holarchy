# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from holarchy.cli.audit import calculate_d_dna_hash, verify_d_dna_integrity


def test_d_dna_chain_verification_success():
    salt = "secret_audit_salt"
    events = [
        {"job_id": "j1", "event_type": "job_created", "timestamp": 100},
        {"job_id": "j1", "event_type": "state_started", "timestamp": 101},
        {"job_id": "j1", "event_type": "job_finished", "timestamp": 102},
    ]

    prev_hash = ""
    for ev in events:
        h = calculate_d_dna_hash(ev, salt, prev_hash)
        ev["prev_d_dna_hash"] = prev_hash
        ev["d_dna_hash"] = h
        prev_hash = h

    is_valid, err = verify_d_dna_integrity(events, salt)
    assert is_valid is True
    assert err is None


def test_d_dna_empty_and_single_event():
    salt = "salt123"
    # Empty events list
    is_valid, err = verify_d_dna_integrity([], salt)
    assert is_valid is True
    assert err is None

    # Single event
    event = {"job_id": "j1", "event_type": "job_created"}
    h = calculate_d_dna_hash(event, salt, "")
    event["d_dna_hash"] = h

    is_valid_single, err_single = verify_d_dna_integrity([event], salt)
    assert is_valid_single is True
    assert err_single is None


def test_d_dna_chain_verification_detects_tampering():
    salt = "secret_audit_salt"
    events = [
        {"job_id": "j1", "event_type": "job_created", "timestamp": 100},
        {"job_id": "j1", "event_type": "state_started", "timestamp": 101},
    ]

    prev_hash = ""
    for ev in events:
        h = calculate_d_dna_hash(ev, salt, prev_hash)
        ev["prev_d_dna_hash"] = prev_hash
        ev["d_dna_hash"] = h
        prev_hash = h

    # Tamper with event 1
    events[1]["event_type"] = "hacked_event"

    is_valid, err = verify_d_dna_integrity(events, salt)
    assert is_valid is False
    assert "Integrity failure at event index 1" in err


def test_d_dna_first_index_tampering_and_wrong_salt():
    salt = "secret_salt"
    events = [
        {"job_id": "j1", "event_type": "job_created", "timestamp": 100},
        {"job_id": "j1", "event_type": "job_finished", "timestamp": 102},
    ]

    prev_hash = ""
    for ev in events:
        h = calculate_d_dna_hash(ev, salt, prev_hash)
        ev["prev_d_dna_hash"] = prev_hash
        ev["d_dna_hash"] = h
        prev_hash = h

    # Tamper with event at index 0
    events[0]["timestamp"] = 999
    is_valid, err = verify_d_dna_integrity(events, salt)
    assert is_valid is False
    assert "Integrity failure at event index 0" in err

    # Restore event 0 and verify with wrong salt
    events[0]["timestamp"] = 100
    is_valid_wrong_salt, err_wrong_salt = verify_d_dna_integrity(events, "wrong_salt")
    assert is_valid_wrong_salt is False
    assert "Integrity failure at event index 0" in err_wrong_salt


def test_d_dna_previous_hash_linkage_mismatch():
    salt = "salt1"
    ev0 = {"job_id": "j1", "event_type": "job_created"}
    h0 = calculate_d_dna_hash(ev0, salt, "")
    ev0["d_dna_hash"] = h0
    ev0["prev_d_dna_hash"] = ""

    ev1 = {"job_id": "j1", "event_type": "state_started"}
    h1 = calculate_d_dna_hash(ev1, salt, h0)
    ev1["d_dna_hash"] = h1
    # Corrupt prev_d_dna_hash pointer
    ev1["prev_d_dna_hash"] = "broken_link_hash"

    is_valid, err = verify_d_dna_integrity([ev0, ev1], salt)
    assert is_valid is False
    assert "previous hash mismatch" in err
