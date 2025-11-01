"""This module previously contained an active HealthChecker.
In the new architecture with heartbeat messages from workers,
the orchestrator no longer needs to actively poll workers.

Redis automatically deletes worker keys when their TTL expires,
and `storage.get_available_workers()` only retrieves active keys.

This file is left as a placeholder in case passive health-check
logic is needed in the future (e.g., for logging expired workers).
"""

from asyncio import CancelledError, sleep
from logging import getLogger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import OrchestratorEngine

logger = getLogger(__name__)


class HealthChecker:
    def __init__(self, engine: "OrchestratorEngine"):
        self._running = False

    async def run(self):
        logger.info("HealthChecker is now passive and will not perform active checks.")
        self._running = True
        while self._running:
            try:
                # Sleep for a long time, as this checker is passive.
                # The loop exists to allow for a clean shutdown.
                await sleep(3600)
            except CancelledError:
                break
        logger.info("HealthChecker stopped.")

    def stop(self):
        self._running = False
