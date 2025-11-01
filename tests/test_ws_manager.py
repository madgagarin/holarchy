from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from src.holarchy.ws_manager import WebSocketManager


@pytest.mark.asyncio
async def test_ws_manager_register_and_unregister():
    """Tests that the WebSocketManager can register and unregister connections."""
    manager = WebSocketManager()
    ws = AsyncMock(spec=web.WebSocketResponse)

    await manager.register("worker-1", ws)
    assert "worker-1" in manager._connections

    await manager.unregister("worker-1")
    assert "worker-1" not in manager._connections


@pytest.mark.asyncio
async def test_ws_manager_send_command():
    """Tests that the WebSocketManager can send commands to workers."""
    manager = WebSocketManager()
    ws = AsyncMock(spec=web.WebSocketResponse)
    ws.closed = False

    await manager.register("worker-1", ws)

    command = {"command": "test"}
    result = await manager.send_command("worker-1", command)

    assert result is True
    ws.send_json.assert_called_with(command)


@pytest.mark.asyncio
async def test_ws_manager_send_command_fails():
    """Tests that send_command returns False when the connection is closed."""
    manager = WebSocketManager()
    ws = AsyncMock(spec=web.WebSocketResponse)
    ws.closed = True

    await manager.register("worker-1", ws)

    command = {"command": "test"}
    result = await manager.send_command("worker-1", command)

    assert result is False
    ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_ws_manager_handle_message():
    """Tests that the WebSocketManager can handle incoming messages."""
    manager = WebSocketManager()

    message = {"event": "progress_update", "job_id": "job-1", "progress": 0.5}
    await manager.handle_message("worker-1", message)

    # Just check that it doesn't raise an exception


@pytest.mark.asyncio
async def test_ws_manager_close_all():
    """Tests that the WebSocketManager can close all connections."""
    manager = WebSocketManager()
    ws1 = AsyncMock(spec=web.WebSocketResponse)
    ws2 = AsyncMock(spec=web.WebSocketResponse)

    await manager.register("worker-1", ws1)
    await manager.register("worker-2", ws2)

    await manager.close_all()

    ws1.close.assert_called_with(code=1001, message=b"Server shutdown")
    ws2.close.assert_called_with(code=1001, message=b"Server shutdown")
    assert not manager._connections
