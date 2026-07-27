# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from holarchy.metrics import create_metrics


def test_create_metrics():
    """Tests that metrics are initialized correctly using OTel."""
    cache = {}
    metrics = create_metrics(instrument_cache=cache)

    assert metrics.jobs_total is not None
    assert "orchestrator_jobs_total" in cache


def test_metrics_idempotency():
    """Verifies that create_metrics uses the provided cache for idempotency."""
    cache = {}
    metrics1 = create_metrics(instrument_cache=cache)
    metrics2 = create_metrics(instrument_cache=cache)

    assert metrics1.jobs_total == metrics2.jobs_total


def test_set_gauge():
    """Tests the manual gauge update helper."""
    metrics = create_metrics(instrument_cache={})
    metrics.set_gauge("task_queue_length", 42.0)
    assert metrics._gauge_values["task_queue_length"] == 42.0
