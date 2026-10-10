# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from os import remove
from os.path import exists
from unittest.mock import AsyncMock

from pytest import mark, raises

from holarchy.worker_config_loader import load_worker_configs_to_redis


@mark.asyncio
async def test_load_worker_configs_to_redis():
    """Tests that worker configs are correctly loaded into Redis."""
    storage = AsyncMock()
    config_path = "test_workers.toml"

    with open(config_path, "w") as f:
        f.write("""
[worker-1]
token = "token-1"

[worker-2]
token = "token-2"
""")

    await load_worker_configs_to_redis(storage, config_path)

    assert storage.set_worker_token.call_count == 2
    storage.set_worker_token.assert_any_call("worker-1", "token-1")
    storage.set_worker_token.assert_any_call("worker-2", "token-2")
    remove(config_path)


@mark.asyncio
async def test_load_worker_configs_file_not_found(caplog):
    """Tests that a warning is logged when the config file is not found."""
    storage = AsyncMock()
    await load_worker_configs_to_redis(storage, "non_existent_file.toml")
    assert "Worker config file not found" in caplog.text


@mark.asyncio
async def test_load_worker_configs_parse_error(caplog):
    """Tests that an error is logged and ValueError is raised when the config file is invalid."""
    storage = AsyncMock()
    config_path = "invalid_workers.toml"

    with open(config_path, "w") as f:
        f.write("invalid toml")

    try:
        with raises(ValueError, match="Invalid worker configuration file"):
            await load_worker_configs_to_redis(storage, config_path)
    finally:
        if exists(config_path):
            remove(config_path)

    assert "Failed to load or parse worker config file" in caplog.text
