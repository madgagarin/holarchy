# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

"""Holarchy Library
=======================

This module exposes the primary classes for building and running state-driven automations.
"""

from contextlib import suppress

try:
    from importlib.metadata import distribution

    __version__ = distribution("holarchy").metadata.get("Version") or "0.0.0-dev"  # type: ignore[attr-defined]
except Exception:
    __version__ = "1.0.0"

from fast_filter import F, FastF
from rxon.validators import is_valid_identifier, validate_identifier

from . import telemetry
from .blueprint import Blueprint
from .context import ActionFactory
from .data_types import Context, JobContext, ensure_storage_zones
from .di import Header
from .engine import OrchestratorEngine
from .fsm import Next, State, StatesGroup, StepScope
from .skill import Skill, SkillInvocation
from .storage.base import StorageBackend

__all__ = [
    "ActionFactory",
    "Blueprint",
    "Context",
    "F",
    "FastF",
    "Header",
    "JobContext",
    "Next",
    "OrchestratorEngine",
    "Skill",
    "SkillInvocation",
    "State",
    "StatesGroup",
    "StepScope",
    "StorageBackend",
    "ensure_storage_zones",
    "is_valid_identifier",
    "validate_identifier",
    "telemetry",
]

with suppress(ImportError):
    from .storage.redis import RedisStorage  # noqa: F401

    __all__.append("RedisStorage")
