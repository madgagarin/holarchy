# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import Task
from unittest.mock import AsyncMock, MagicMock, patch

from pytest import fixture, mark

from holarchy import engine as engine_mod
from holarchy.blueprint import Blueprint
from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.history.noop import NoOpHistoryStorage


def create_task_side_effect(coro, *args, **kwargs):
    coro.close()
    return MagicMock(spec=Task)


@fixture
def config():
    c = Config()
    c.HISTORY_DATABASE_URI = ""
    return c


@fixture
def storage():
    return AsyncMock()


@fixture
def engine(storage, config):
    return OrchestratorEngine(storage, config)


@mark.asyncio
async def test_register_blueprint(engine):
    bp = Blueprint(name="test_bp")

    @bp.start
    async def start():
        pass

    engine.register_blueprint(bp)
    assert engine.blueprints["test_bp"] == bp
    assert engine.blueprint_contracts["test_bp"] is not None


# The test_setup and test_on_shutdown tests were removed due to the refactoring of service initializations.


@mark.asyncio
async def test_setup_history_storage_postgres(engine, monkeypatch):
    engine.config.HISTORY_DATABASE_URI = "postgresql://user:pass@host:port/db"

    mock_storage_class = MagicMock()
    mock_initialize = AsyncMock()
    mock_storage_class.return_value.initialize = mock_initialize
    mock_module = MagicMock(PostgresHistoryStorage=mock_storage_class)

    with patch("importlib.import_module", return_value=mock_module) as mock_import:
        monkeypatch.setattr(engine_mod, "import_module", mock_import)
        await engine._setup_history_storage()
        assert mock_import.called
        mock_initialize.assert_awaited_once()


@mark.asyncio
async def test_setup_history_storage_unsupported_scheme(engine):
    engine.config.HISTORY_DATABASE_URI = "mysql://user:pass@host:port/db"
    await engine._setup_history_storage()
    assert isinstance(engine.history_storage, NoOpHistoryStorage)


@mark.asyncio
async def test_setup_history_storage_initialization_failure(engine, monkeypatch):
    engine.config.HISTORY_DATABASE_URI = "sqlite:/:memory:"

    mock_storage_class = MagicMock()
    mock_storage_class.__name__ = "MockStorage"
    mock_storage_class.return_value.initialize = AsyncMock(side_effect=Exception("Boom!"))
    mock_module = MagicMock(SQLiteHistoryStorage=mock_storage_class)

    with patch("importlib.import_module", return_value=mock_module) as mock_import:
        monkeypatch.setattr(engine_mod, "import_module", mock_import)
        await engine._setup_history_storage()
        assert isinstance(engine.history_storage, NoOpHistoryStorage)


@mark.asyncio
async def test_create_job_initializes_clean_zones(engine):
    bp = Blueprint("clean_bp")

    @bp.start
    async def start(actions):
        pass

    engine.register_blueprint(bp)

    job_id = await engine.create_job("clean_bp", input={"msg": "hello", "count": 10})
    engine.storage.save_job_state.assert_awaited_once()
    called_job_id, saved_state = engine.storage.save_job_state.await_args[0]

    assert called_job_id == job_id
    assert saved_state is not None
    assert saved_state["input"] == {"msg": "hello", "count": 10}
    assert saved_state["output"] is None
    assert saved_state["steps"] == {}
    assert saved_state["history"] == []
    assert isinstance(saved_state["params"], dict)
    assert "initial_data" not in saved_state
    assert saved_state["blueprint"] == "clean_bp"
