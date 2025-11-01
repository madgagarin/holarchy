from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from src.holarchy.ratelimit import rate_limit_middleware_factory


@pytest.mark.asyncio
async def test_rate_limit_middleware():
    """Tests that the rate limit middleware correctly blocks requests."""
    storage = AsyncMock()
    limit = 5
    period = 60

    async def handler(request):
        return web.Response(text="OK")

    middleware = rate_limit_middleware_factory(storage, limit, period)
    app = web.Application(middlewares=[middleware])
    app.router.add_get("/test", handler)

    # Simulate requests
    request = MagicMock()
    request.match_info.get.return_value = "test_worker"
    request.path = "/test"

    # First 5 requests should succeed
    storage.increment_key_with_ttl.return_value = 1
    response = await middleware(request, handler)
    assert response.status == 200

    storage.increment_key_with_ttl.return_value = 2
    response = await middleware(request, handler)
    assert response.status == 200

    storage.increment_key_with_ttl.return_value = 3
    response = await middleware(request, handler)
    assert response.status == 200

    storage.increment_key_with_ttl.return_value = 4
    response = await middleware(request, handler)
    assert response.status == 200

    storage.increment_key_with_ttl.return_value = 5
    response = await middleware(request, handler)
    assert response.status == 200

    # 6th request should be blocked
    storage.increment_key_with_ttl.return_value = 6
    response = await middleware(request, handler)
    assert response.status == 429


@pytest.mark.asyncio
async def test_rate_limit_storage_failure():
    """Tests that the rate limit middleware lets requests through when storage fails."""
    storage = AsyncMock()
    storage.increment_key_with_ttl.side_effect = Exception("Storage failed")
    limit = 5
    period = 60

    async def handler(request):
        return web.Response(text="OK")

    middleware = rate_limit_middleware_factory(storage, limit, period)
    app = web.Application(middlewares=[middleware])
    app.router.add_get("/test", handler)

    request = MagicMock()
    request.match_info.get.return_value = "test_worker"
    request.path = "/test"

    response = await middleware(request, handler)
    assert response.status == 200
