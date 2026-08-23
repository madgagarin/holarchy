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
