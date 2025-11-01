from asyncio import CancelledError, sleep
from logging import getLogger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import OrchestratorEngine

logger = getLogger(__name__)


class Watcher:
    """A background process that monitors for "stuck" jobs."""

    def __init__(self, engine: "OrchestratorEngine"):
        self.engine = engine
        self.storage = engine.storage
        self.config = engine.config
        self._running = False
        self.watch_interval_seconds = self.config.WATCHER_INTERVAL_SECONDS

    async def run(self):
        """The main loop of the watcher."""
        logger.info("Watcher started.")
        self._running = True
        while self._running:
            try:
                await sleep(self.watch_interval_seconds)
                logger.info("Watcher running check for timed out jobs...")

                timed_out_job_ids = await self.storage.get_timed_out_jobs()

                for job_id in timed_out_job_ids:
                    logger.warning(f"Job {job_id} timed out. Moving to failed state.")
                    try:
                        # Get the latest version to avoid overwriting
                        job_state = await self.storage.get_job_state(job_id)
                        if job_state and job_state["status"] == "waiting_for_worker":
                            job_state["status"] = "failed"
                            job_state["error_message"] = "Worker task timed out."
                            await self.storage.save_job_state(job_id, job_state)

                            # Increment the metric
                            from . import metrics

                            metrics.jobs_failed_total.inc(
                                {
                                    metrics.LABEL_BLUEPRINT: job_state.get(
                                        "blueprint_name",
                                        "unknown",
                                    ),
                                },
                            )
                    except Exception:
                        logger.exception(
                            f"Failed to update state for timed out job {job_id}",
                        )

            except CancelledError:
                logger.info("Watcher received cancellation request.")
                break
            except Exception:
                logger.exception("Error in Watcher main loop.")

        logger.info("Watcher stopped.")

    def stop(self):
        """Stops the watcher."""
        self._running = False
