# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from rxon.constants import AUTH_HEADER_CLIENT

from holarchy.api.routes import setup_routes
from holarchy.blueprint import Blueprint
from holarchy.client_config_loader import load_client_configs_to_redis
from holarchy.config import Config
from holarchy.context import ActionFactory
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage


@pytest.mark.asyncio
async def test_quickstart_client_token_fallback_success(aiohttp_client):
    """Quick Start scenario: config.CLIENT_TOKEN enables API access without clients.toml."""
    storage = MemoryStorage()
    config = Config()
    config.CLIENT_API_PREFIX = "api"
    config.CLIENTS_CONFIG_PATH = ""
    config.CLIENT_TOKEN = "my-secret-client-token"
    config.GLOBAL_WORKER_TOKEN = "my-secret-worker-token"
    config.ENABLE_CLIENT_API = True

    bp = Blueprint(name="my_flow", api_version="v1", api_endpoint="/jobs/my_flow")

    @bp.handler("start", is_start=True)
    async def start(job_id: str, initial_data: dict, actions: ActionFactory):
        actions.go_to("end")

    @bp.handler("end", is_end=True)
    async def end(context):
        pass

    engine = OrchestratorEngine(storage, config)
    engine.register_blueprint(bp)
    engine.metrics = MagicMock()

    app = web.Application()
    setup_routes(app, engine)

    client = await aiohttp_client(app)

    # Send POST with valid X-Client-Token
    headers = {
        AUTH_HEADER_CLIENT: "my-secret-client-token",
        "Content-Type": "application/json",
    }
    resp = await client.post("/api/v1/jobs/my_flow", json={"initial_data": {}}, headers=headers)
    assert resp.status == 202
    data = await resp.json()
    assert "job_id" in data
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_quickstart_client_token_fallback_rejections(aiohttp_client):
    """Quick Start scenario: Invalid or missing token is strictly rejected (401)."""
    storage = MemoryStorage()
    config = Config()
    config.CLIENT_API_PREFIX = "api"
    config.CLIENTS_CONFIG_PATH = ""
    config.CLIENT_TOKEN = "my-secret-client-token"
    config.ENABLE_CLIENT_API = True

    bp = Blueprint(name="my_flow", api_version="v1", api_endpoint="/jobs/my_flow")

    @bp.handler("start", is_start=True)
    async def start(job_id: str, initial_data: dict, actions: ActionFactory):
        actions.go_to("end")

    @bp.handler("end", is_end=True)
    async def end(context):
        pass

    engine = OrchestratorEngine(storage, config)
    engine.register_blueprint(bp)
    engine.metrics = MagicMock()

    app = web.Application()
    setup_routes(app, engine)

    client = await aiohttp_client(app)

    # 1. Request with wrong token -> 401
    resp_wrong = await client.post(
        "/api/v1/jobs/my_flow",
        json={"initial_data": {}},
        headers={AUTH_HEADER_CLIENT: "wrong-token"},
    )
    assert resp_wrong.status == 401
    assert (await resp_wrong.json())["error"] == "Unauthorized: Invalid token"

    # 2. Request without token header -> 401
    resp_missing = await client.post(
        "/api/v1/jobs/my_flow",
        json={"initial_data": {}},
    )
    assert resp_missing.status == 401
    assert f"Missing {AUTH_HEADER_CLIENT} header" in (await resp_missing.json())["error"]


@pytest.mark.asyncio
async def test_clients_toml_has_highest_precedence(aiohttp_client):
    """Production scenario: clients.toml profiles take precedence over fallback."""
    storage = MemoryStorage()
    config = Config()
    config.CLIENT_API_PREFIX = "api"
    config.CLIENT_TOKEN = "global-fallback-token"
    config.ENABLE_CLIENT_API = True

    # Pre-populate custom client via clients.toml data
    with NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
        tmp.write("""
[client-enterprise]
token = "enterprise-token-xyz"
plan = "enterprise"
monthly_attempts = 500
allowed_languages = ["python", "rust"]
""")
        tmp_path = tmp.name

    try:
        await load_client_configs_to_redis(storage, tmp_path)

        bp = Blueprint(name="enterprise_flow", api_version="v1", api_endpoint="/jobs/enterprise_flow")

        @bp.handler("start", is_start=True)
        async def start(job_id: str, initial_data: dict, actions: ActionFactory):
            actions.go_to("end")

        @bp.handler("end", is_end=True)
        async def end(context):
            pass

        engine = OrchestratorEngine(storage, config)
        engine.register_blueprint(bp)
        engine.metrics = MagicMock()

        app = web.Application()
        setup_routes(app, engine)

        client = await aiohttp_client(app)

        # 1. Custom enterprise client from clients.toml
        resp = await client.post(
            "/api/v1/jobs/enterprise_flow",
            json={"initial_data": {}},
            headers={AUTH_HEADER_CLIENT: "enterprise-token-xyz"},
        )
        assert resp.status == 202

        # Verify client config was preserved in storage with custom plan
        conf = await storage.get_client_config("enterprise-token-xyz")
        assert conf is not None
        assert conf["plan"] == "enterprise"
        assert conf["allowed_languages"] == ["python", "rust"]

        # 2. Fallback token also works if needed
        resp_fallback = await client.post(
            "/api/v1/jobs/enterprise_flow",
            json={"initial_data": {}},
            headers={AUTH_HEADER_CLIENT: "global-fallback-token"},
        )
        assert resp_fallback.status == 202
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@pytest.mark.asyncio
async def test_strict_zero_trust_when_no_tokens_configured(aiohttp_client):
    """Strict Zero Trust: If no CLIENT_TOKEN and no clients.toml, all access is denied."""
    storage = MemoryStorage()
    config = Config()
    config.CLIENT_API_PREFIX = "api"
    config.CLIENTS_CONFIG_PATH = ""
    config.CLIENT_TOKEN = ""  # Explicitly empty
    config.ENABLE_CLIENT_API = True

    bp = Blueprint(name="secure_flow", api_version="v1", api_endpoint="/jobs/secure_flow")

    @bp.handler("start", is_start=True)
    async def start(job_id: str, initial_data: dict, actions: ActionFactory):
        actions.go_to("end")

    @bp.handler("end", is_end=True)
    async def end(context):
        pass

    engine = OrchestratorEngine(storage, config)
    engine.register_blueprint(bp)
    engine.metrics = MagicMock()

    app = web.Application()
    setup_routes(app, engine)

    client = await aiohttp_client(app)

    resp = await client.post(
        "/api/v1/jobs/secure_flow",
        json={"initial_data": {}},
        headers={AUTH_HEADER_CLIENT: "some-arbitrary-token"},
    )
    assert resp.status == 401
    assert (await resp.json())["error"] == "Unauthorized: Invalid token"
