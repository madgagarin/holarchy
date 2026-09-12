# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from os import remove
from os.path import exists
from unittest.mock import AsyncMock

from pytest import mark, raises
from src.holarchy.client_config_loader import load_client_configs_to_redis
from src.holarchy.config import Config
from src.holarchy.worker_config_loader import load_worker_configs_to_redis


@mark.asyncio
async def test_client_config_loader_invalid_toml():
    """Verifies that client config loader raises ValueError on invalid TOML."""
    storage = AsyncMock()
    path = "invalid_clients.toml"
    with open(path, "w") as f:
        f.write("this is [not] valid toml = = =")

    try:
        with raises(ValueError, match="Invalid client configuration file"):
            await load_client_configs_to_redis(storage, path)
    finally:
        if exists(path):
            remove(path)


@mark.asyncio
async def test_client_config_loader_invalid_quota_type():
    """Verifies that client config loader validates monthly_attempts type."""
    storage = AsyncMock()
    path = "invalid_quota.toml"
    with open(path, "w") as f:
        f.write("""
[client]
token = "abc"
monthly_attempts = "not-an-int"
""")

    try:
        with raises(ValueError, match="Invalid quota type for client 'client'"):
            await load_client_configs_to_redis(storage, path)
    finally:
        if exists(path):
            remove(path)


@mark.asyncio
async def test_worker_config_loader_invalid_structure():
    """Verifies that worker config loader validates that config is a table."""
    storage = AsyncMock()
    path = "invalid_struct.toml"
    with open(path, "w") as f:
        f.write("""
worker_id = "not-a-table"
""")

    try:
        with raises(ValueError, match="Invalid configuration for worker 'worker_id'"):
            await load_worker_configs_to_redis(storage, path)
    finally:
        if exists(path):
            remove(path)


def test_production_config_validation_fails_on_defaults(monkeypatch):
    """Verifies that Config raises ValueError in production when default tokens are used."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CLIENT_TOKEN", raising=False)
    monkeypatch.delenv("GLOBAL_WORKER_TOKEN", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_SECRET_KEY", raising=False)

    with raises(ValueError, match="Insecure production configuration"):
        Config()


def test_production_config_validation_succeeds_with_explicit_tokens(monkeypatch):
    """Verifies that Config succeeds in production when explicit tokens and secret are set."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CLIENT_TOKEN", "prod-custom-client-token")
    monkeypatch.setenv("GLOBAL_WORKER_TOKEN", "prod-custom-worker-token")
    monkeypatch.setenv("ORCHESTRATOR_SECRET_KEY", "prod-custom-secret-key")

    cfg = Config()
    assert cfg.CLIENT_TOKEN == "prod-custom-client-token"
    assert cfg.GLOBAL_WORKER_TOKEN == "prod-custom-worker-token"
    assert cfg.ORCHESTRATOR_SECRET_KEY == "prod-custom-secret-key"


def test_production_config_rejects_default_client_token(monkeypatch):
    """Negative: Rejects default CLIENT_TOKEN even if other settings are valid."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CLIENT_TOKEN", "secure-orchestrator-token")
    monkeypatch.setenv("GLOBAL_WORKER_TOKEN", "custom-worker-token")
    monkeypatch.setenv("ORCHESTRATOR_SECRET_KEY", "custom-secret-key")

    with raises(ValueError, match="CLIENT_TOKEN must be set explicitly"):
        Config()


def test_production_config_rejects_default_worker_token(monkeypatch):
    """Negative: Rejects default GLOBAL_WORKER_TOKEN even if other settings are valid."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CLIENT_TOKEN", "custom-client-token")
    monkeypatch.setenv("GLOBAL_WORKER_TOKEN", "secure-worker-token")
    monkeypatch.setenv("ORCHESTRATOR_SECRET_KEY", "custom-secret-key")

    with raises(ValueError, match="GLOBAL_WORKER_TOKEN must be set explicitly"):
        Config()


def test_production_config_rejects_missing_secret_key(monkeypatch):
    """Negative: Rejects missing ORCHESTRATOR_SECRET_KEY in production."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CLIENT_TOKEN", "custom-client-token")
    monkeypatch.setenv("GLOBAL_WORKER_TOKEN", "custom-worker-token")
    monkeypatch.delenv("ORCHESTRATOR_SECRET_KEY", raising=False)

    with raises(ValueError, match="ORCHESTRATOR_SECRET_KEY must be set explicitly"):
        Config()


def test_production_config_supports_env_alias_prod(monkeypatch):
    """Boundary / Alias: Checks ENV=prod alias activates production validation."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("CLIENT_TOKEN", raising=False)

    with raises(ValueError, match="Insecure production configuration"):
        Config()
