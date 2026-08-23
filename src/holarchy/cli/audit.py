# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from hashlib import sha256
from json import dumps
from typing import Any


def calculate_d_dna_hash(event_data: dict[str, Any], salt: str, prev_hash: str = "") -> str:
    """Calculates D-DNA cryptographic hash for a history event chained to prev_hash."""
    clean = {k: v for k, v in event_data.items() if k not in ("d_dna_hash", "prev_d_dna_hash")}
    canonical = dumps(clean, sort_keys=True, default=str)
    raw = f"{canonical}:{salt}:{prev_hash}"
    return sha256(raw.encode("utf-8")).hexdigest()


def verify_d_dna_integrity(events: list[dict[str, Any]], audit_salt: str) -> tuple[bool, str | None]:
    """Verifies D-DNA cryptographic audit chain for a list of job history events."""
    prev_hash = ""
    for idx, event in enumerate(events):
        prev_d_dna = event.get("prev_d_dna_hash")
        if prev_d_dna is not None and prev_d_dna != prev_hash:
            return False, f"Integrity failure at event index {idx}: previous hash mismatch"
        expected_hash = calculate_d_dna_hash(event, audit_salt, prev_hash)
        actual_hash = event.get("d_dna_hash")
        if actual_hash != expected_hash:
            return False, f"Integrity failure at event index {idx} (event_type={event.get('event_type')})"
        prev_hash = actual_hash
    return True, None
