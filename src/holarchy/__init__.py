"""Holarchy Library
=======================

This module exposes the primary classes for building and running state-driven automations.
"""

from importlib.metadata import version

__version__ = version("holarchy")

from .blueprint import StateMachineBlueprint
from .context import ActionFactory
from .data_types import JobContext
from .engine import OrchestratorEngine
from .storage.base import StorageBackend
from .storage.redis import RedisStorage

__all__ = [
    "ActionFactory",
    "JobContext",
    "OrchestratorEngine",
    "RedisStorage",
    "StateMachineBlueprint",
    "StorageBackend",
]
