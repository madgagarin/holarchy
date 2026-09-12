# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from os import environ
from unittest.mock import AsyncMock

from pytest import mark, raises

from holarchy.storage.redis import RedisStorage


@mark.asyncio
async def test_redis_hmac_signature_happy_path_and_tamper_detection():
    secret_key = "test_secret_key_12345"
    environ["ORCHESTRATOR_SECRET_KEY"] = secret_key

    fake_redis_dict = {}

    async def mock_get(key):
        return fake_redis_dict.get(key)

    async def mock_set(key, val, **kwargs):
        fake_redis_dict[key] = val

    redis_client = AsyncMock()
    redis_client.get = mock_get
    redis_client.set = mock_set

    storage = RedisStorage(redis_client)

    job_state = {"id": "job-tamper-test", "status": "running", "step": 1}

    # 1. Save state (HMAC signature is generated)
    await storage.save_job_state("job-tamper-test", job_state)
    assert "_signature" in job_state

    # 2. Fetch state (Valid HMAC -> success)
    restored = await storage.get_job_state("job-tamper-test")
    assert restored["id"] == "job-tamper-test"
    assert restored["status"] == "running"

    # 3. Tamper with Redis raw data by modifying state content without updating signature
    unpacked_tampered = dict(restored)
    unpacked_tampered["status"] = "hacked_status"
    packed_tampered = await storage._pack_async(unpacked_tampered)
    fake_redis_dict["orchestrator:job:job-tamper-test"] = packed_tampered

    # 4. Fetch tampered state -> must raise PermissionError
    with raises(PermissionError) as exc_info:
        await storage.get_job_state("job-tamper-test")

    assert "Job state HMAC signature verification failed" in str(exc_info.value)


@mark.asyncio
async def test_redis_hmac_corrupted_signature_string():
    secret_key = "secret_abc"
    environ["ORCHESTRATOR_SECRET_KEY"] = secret_key

    fake_redis_dict = {}

    async def mock_get(key):
        return fake_redis_dict.get(key)

    async def mock_set(key, val, **kwargs):
        fake_redis_dict[key] = val

    redis_client = AsyncMock()
    redis_client.get = mock_get
    redis_client.set = mock_set

    storage = RedisStorage(redis_client)

    job_state = {"id": "job-sig-corrupt", "status": "pending"}
    await storage.save_job_state("job-sig-corrupt", job_state)

    # Corrupt signature directly
    restored = await storage.get_job_state("job-sig-corrupt")
    restored["_signature"] = "invalid_fake_signature"
    packed_corrupted = await storage._pack_async(restored)
    fake_redis_dict["orchestrator:job:job-sig-corrupt"] = packed_corrupted

    with raises(PermissionError) as exc_info:
        await storage.get_job_state("job-sig-corrupt")

    assert "Job state HMAC signature verification failed" in str(exc_info.value)


@mark.asyncio
async def test_redis_hmac_disabled_when_no_secret():
    if "ORCHESTRATOR_SECRET_KEY" in environ:
        del environ["ORCHESTRATOR_SECRET_KEY"]

    fake_redis_dict = {}

    async def mock_get(key):
        return fake_redis_dict.get(key)

    async def mock_set(key, val, **kwargs):
        fake_redis_dict[key] = val

    redis_client = AsyncMock()
    redis_client.get = mock_get
    redis_client.set = mock_set

    storage = RedisStorage(redis_client)

    job_state = {"id": "job-no-secret", "status": "running"}
    await storage.save_job_state("job-no-secret", job_state)

    assert "_signature" not in job_state

    fetched = await storage.get_job_state("job-no-secret")
    assert fetched["status"] == "running"
