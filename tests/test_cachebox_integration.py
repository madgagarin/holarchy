# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import gather, sleep
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock

from cachebox import LRUCache, TTLCache
from pytest import mark, raises

from holarchy.dispatcher import Dispatcher
from holarchy.engine import OrchestratorEngine
from holarchy.security import verify_worker_auth


def test_engine_cachebox_initialization():
    storage = MagicMock()
    config = MagicMock()
    config.BLUEPRINTS_DIR = None
    config.LOG_LEVEL = "INFO"
    config.LOG_FORMAT = "json"
    config.TZ = "UTC"

    engine = OrchestratorEngine(storage, config)

    assert isinstance(engine.token_hash_cache, TTLCache)
    assert isinstance(engine.instrument_cache, LRUCache)
    assert isinstance(engine.fernet_cache, LRUCache)
    assert isinstance(engine.worker_catalog_cache, TTLCache)

    assert engine.token_hash_cache.maxsize == 10000
    assert engine.instrument_cache.maxsize == 1000
    assert engine.fernet_cache.maxsize == 1000
    assert engine.worker_catalog_cache.maxsize == 10


@mark.asyncio
async def test_dispatcher_worker_cache_ttl():
    storage = AsyncMock()
    config = MagicMock()
    metrics = MagicMock()

    dispatcher = Dispatcher(storage, config, metrics)
    assert isinstance(dispatcher._worker_cache, TTLCache)
    assert dispatcher._worker_cache.maxsize == 5000

    worker_id = "test-worker-1"
    worker_data = {"worker_id": worker_id, "supported_skills": []}
    storage.get_workers.return_value = [worker_data]

    res1 = await dispatcher._get_workers_cached([worker_id])
    assert len(res1) == 1
    assert res1[0]["worker_id"] == worker_id
    storage.get_workers.assert_called_once_with([worker_id])

    storage.get_workers.reset_mock()
    res2 = await dispatcher._get_workers_cached([worker_id])
    assert len(res2) == 1
    assert res2[0]["worker_id"] == worker_id
    storage.get_workers.assert_not_called()

    await sleep(2.1)

    storage.get_workers.reset_mock()
    res3 = await dispatcher._get_workers_cached([worker_id])
    assert len(res3) == 1
    assert res3[0]["worker_id"] == worker_id
    storage.get_workers.assert_called_once_with([worker_id])


@mark.asyncio
async def test_security_token_hash_cache_ttl():
    storage = AsyncMock()
    config = MagicMock()
    config.WORKER_AUTH_MODE = "token-only"
    metrics = MagicMock()

    token_hash_cache = TTLCache(maxsize=10, global_ttl=1.0)
    token = "secret-token"

    hashed_token = sha256(token.encode()).hexdigest()
    storage.verify_worker_access_token.return_value = "worker-123"

    wid1, cred_hash1 = await verify_worker_auth(
        storage=storage,
        config=config,
        token=token,
        cert_identity=None,
        worker_id_hint="worker-123",
        metrics=metrics,
        token_hash_cache=token_hash_cache,
    )
    assert wid1 == "worker-123"
    assert cred_hash1 == hashed_token
    assert token_hash_cache.get(token) == hashed_token
    storage.verify_worker_access_token.assert_called_once_with(hashed_token)

    storage.verify_worker_access_token.reset_mock()
    wid2, cred_hash2 = await verify_worker_auth(
        storage=storage,
        config=config,
        token=token,
        cert_identity=None,
        worker_id_hint="worker-123",
        metrics=metrics,
        token_hash_cache=token_hash_cache,
    )
    assert wid2 == "worker-123"
    storage.verify_worker_access_token.assert_called_once()

    await sleep(1.1)
    assert token_hash_cache.get(token) is None


def test_cachebox_capacity_eviction():
    cache = TTLCache(maxsize=5, global_ttl=10.0)

    for i in range(5):
        cache[f"key-{i}"] = f"value-{i}"

    assert len(cache) == 5

    cache["key-5"] = "value-5"

    assert len(cache) == 5
    assert "key-0" not in cache
    assert "key-5" in cache


def test_cachebox_invalid_and_none_keys():
    cache = TTLCache(maxsize=10, global_ttl=10.0)

    cache[None] = "none-val"
    assert cache[None] == "none-val"

    cache[123] = "int-val"
    cache[True] = "bool-val"

    assert cache[123] == "int-val"
    assert cache[True] == "bool-val"


@mark.asyncio
async def test_cachebox_concurrency():
    cache = TTLCache(maxsize=100, global_ttl=5.0)

    async def writer(task_id):
        for i in range(20):
            cache[f"task-{task_id}-key-{i}"] = f"val-{i}"
            await sleep(0.001)

    async def reader(task_id):
        for i in range(20):
            _ = cache.get(f"task-{task_id}-key-{i}")
            await sleep(0.001)

    tasks = []
    for t in range(5):
        tasks.append(writer(t))
        tasks.append(reader(t))

    await gather(*tasks)

    for t in range(5):
        assert cache[f"task-{t}-key-19"] == "val-19"


@mark.asyncio
async def test_security_token_hash_cache_missing_token():
    storage = AsyncMock()
    config = MagicMock()
    config.WORKER_AUTH_MODE = "token-only"
    metrics = MagicMock()

    token_hash_cache = TTLCache(maxsize=10, global_ttl=10.0)

    with raises(PermissionError, match="Unauthorized: Missing"):
        await verify_worker_auth(
            storage=storage,
            config=config,
            token=None,
            cert_identity=None,
            worker_id_hint="worker-123",
            metrics=metrics,
            token_hash_cache=token_hash_cache,
        )
    assert len(token_hash_cache) == 0

    with raises(PermissionError, match="Unauthorized: Missing"):
        await verify_worker_auth(
            storage=storage,
            config=config,
            token="",
            cert_identity=None,
            worker_id_hint="worker-123",
            metrics=metrics,
            token_hash_cache=token_hash_cache,
        )
    assert len(token_hash_cache) == 0
