import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.holarchy.history.postgres import PostgresHistoryStorage


class PostgresHistoryStorageImpl(PostgresHistoryStorage):
    async def get_worker_history(self, worker_id: str, since_days: int) -> list:
        return []


@pytest.fixture
def dsn():
    return os.environ.get("TEST_POSTGRES_DSN", "postgresql://user:password@localhost:5432/test_db")


@pytest.fixture
def postgres_storage(dsn):
    """
    This fixture provides an instance of PostgresHistoryStorage with a mocked
    `asyncpg.create_pool` to avoid actual DB connections.
    """
    storage = PostgresHistoryStorageImpl(dsn=dsn)

    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_acquire
    mock_pool.close = AsyncMock()

    with patch(
        "src.holarchy.history.postgres.create_pool", new=AsyncMock(return_value=mock_pool)
    ) as mock_create_pool:
        yield storage, mock_conn, mock_create_pool, mock_pool


@pytest.mark.asyncio
async def test_initialize(postgres_storage):
    storage, mock_conn, mock_create_pool, _ = postgres_storage
    await storage.initialize()
    mock_create_pool.assert_awaited_once()
    assert mock_conn.execute.call_count >= 1


@pytest.mark.asyncio
async def test_log_job_event(postgres_storage):
    storage, mock_conn, _, _ = postgres_storage
    await storage.initialize()
    mock_conn.reset_mock()
    await storage.log_job_event({"job_id": "test-job"})
    mock_conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_log_worker_event(postgres_storage):
    storage, mock_conn, _, _ = postgres_storage
    await storage.initialize()
    mock_conn.reset_mock()
    await storage.log_worker_event({"worker_id": "test-worker"})
    mock_conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_job_history(postgres_storage):
    storage, mock_conn, _, _ = postgres_storage
    await storage.initialize()
    mock_conn.fetch.return_value = [{"event_id": "123"}]
    history = await storage.get_job_history("test-job")
    mock_conn.fetch.assert_called_once()
    assert history == [{"event_id": "123"}]


@pytest.mark.asyncio
async def test_get_jobs(postgres_storage):
    storage, mock_conn, _, _ = postgres_storage
    await storage.initialize()
    mock_conn.fetch.return_value = [{"job_id": "123"}]
    jobs = await storage.get_jobs(10, 0)
    mock_conn.fetch.assert_called_once()
    assert jobs == [{"job_id": "123"}]


@pytest.mark.asyncio
async def test_get_job_summary(postgres_storage):
    storage, mock_conn, _, _ = postgres_storage
    await storage.initialize()
    mock_conn.fetch.return_value = [{"status": "running", "count": 1}]
    summary = await storage.get_job_summary()
    mock_conn.fetch.assert_called_once()
    assert summary == {"running": 1}


@pytest.mark.asyncio
async def test_close(postgres_storage):
    storage, _, _, mock_pool = postgres_storage
    await storage.initialize()
    await storage.close()
    mock_pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_db_connection_error(dsn):
    storage = PostgresHistoryStorageImpl(dsn)
    with patch("asyncpg.create_pool", new=AsyncMock(side_effect=OSError("Connection failed"))), pytest.raises(OSError):
        await storage.initialize()
