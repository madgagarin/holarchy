from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from src.holarchy.executor import JobExecutor


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.storage = AsyncMock()
    engine.history_storage = AsyncMock()
    engine.dispatcher = AsyncMock()
    engine.blueprints = {}
    return engine


@pytest.fixture
def job_executor(mock_engine):
    return JobExecutor(mock_engine, mock_engine.history_storage)


@pytest.mark.asyncio
async def test_process_job_not_found(job_executor, caplog):
    job_executor.storage.get_job_state.return_value = None
    await job_executor._process_job("test-job")
    assert "Job test-job not found in storage" in caplog.text


@pytest.mark.asyncio
async def test_process_job_in_terminal_state(job_executor, caplog):
    job_executor.storage.get_job_state.return_value = {
        "status": "finished",
        "blueprint_name": "test-bp",
        "current_state": "start",
    }
    await job_executor._process_job("test-job")
    assert "Job test-job is already in a terminal state" in caplog.text


@pytest.mark.asyncio
async def test_process_job_blueprint_not_found(job_executor):
    job_executor.engine.config.JOB_MAX_RETRIES = 3
    job_state = {"id": "test-job", "blueprint_name": "test-bp", "current_state": "start", "initial_data": {}}
    job_executor.storage.get_job_state.return_value = job_state
    await job_executor._process_job("test-job")
    job_executor.storage.save_job_state.assert_called_with(
        "test-job",
        {
            "id": "test-job",
            "blueprint_name": "test-bp",
            "current_state": "start",
            "initial_data": {},
            "retry_count": 1,
            "status": "awaiting_retry",
            "error_message": "Blueprint 'test-bp' not found",
            "tracing_context": ANY,
        },
    )


@pytest.mark.asyncio
async def test_process_job_handler_not_found(job_executor):
    bp = MagicMock()
    bp.find_handler.side_effect = ValueError("Handler not found")
    job_executor.engine.blueprints["test-bp"] = bp
    job_executor.engine.config.JOB_MAX_RETRIES = 3
    job_state = {"id": "test-job", "blueprint_name": "test-bp", "current_state": "start", "initial_data": {}}
    job_executor.storage.get_job_state.return_value = job_state
    await job_executor._process_job("test-job")
    job_executor.storage.save_job_state.assert_called_with(
        "test-job",
        {
            "id": "test-job",
            "blueprint_name": "test-bp",
            "current_state": "start",
            "initial_data": {},
            "retry_count": 1,
            "status": "awaiting_retry",
            "error_message": "Handler not found",
            "tracing_context": ANY,
        },
    )
