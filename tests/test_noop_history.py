import pytest
from src.holarchy.history.noop import NoOpHistoryStorage


@pytest.mark.asyncio
async def test_noop_history_storage():
    """Tests that the NoOpHistoryStorage methods do nothing and return empty values."""
    storage = NoOpHistoryStorage()

    await storage.initialize()
    await storage.log_job_event({})
    await storage.log_worker_event({})

    assert await storage.get_job_history("job-1") == []
    assert await storage.get_jobs() == []
    assert await storage.get_job_summary() == {}
    assert await storage.get_worker_history("worker-1", 1) == []
