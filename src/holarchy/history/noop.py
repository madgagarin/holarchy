from typing import Any, Dict, List

from .base import HistoryStorageBase


class NoOpHistoryStorage(HistoryStorageBase):
    """A "null" implementation of the history store that performs no actions.
    Used when history storage is not configured.
    """

    async def initialize(self):
        # Do nothing
        pass

    async def log_job_event(self, event_data: Dict[str, Any]):
        # Do nothing
        pass

    async def log_worker_event(self, event_data: Dict[str, Any]):
        # Do nothing
        pass

    async def get_job_history(self, job_id: str) -> List[Dict[str, Any]]:
        # Always return an empty list
        return []

    async def get_jobs(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        return []

    async def get_job_summary(self) -> Dict[str, int]:
        return {}

    async def get_worker_history(
        self,
        worker_id: str,
        since_days: int,
    ) -> List[Dict[str, Any]]:
        return []
