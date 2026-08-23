# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from pytest import fixture, mark, raises

from holarchy.api.handlers import get_job_status_handler
from holarchy.app_keys import ENGINE_KEY


@fixture
def mock_engine():
    engine = MagicMock()
    engine.storage = AsyncMock()
    engine.config = MagicMock()
    return engine


@fixture
def mock_request(mock_engine):
    req = MagicMock()
    app_mock = MagicMock()
    app_dict = {ENGINE_KEY: mock_engine}
    app_mock.__getitem__.side_effect = app_dict.__getitem__
    req.app = app_mock
    req.match_info = {"job_id": "test-job"}
    req.query = {}
    return req


@mark.asyncio
async def test_access_granted_to_owner(mock_engine, mock_request):
    """Owner should have access to their job."""
    token = "correct-token"
    mock_request.__getitem__.side_effect = lambda k: {"token": token} if k == "client_config" else None
    mock_request.get.side_effect = lambda k, default=None: {"token": token} if k == "client_config" else default

    mock_engine.storage.get_job_state.return_value = {
        "id": "test-job",
        "status": "finished",
        "client_config": {"token": token},
    }

    response = await get_job_status_handler(mock_request)
    assert response.status == 200


@mark.asyncio
async def test_access_denied_to_stranger(mock_engine, mock_request):
    """Access denied for jobs owned by others."""
    my_token = "my-token"
    stranger_token = "stranger-token"

    mock_request.get.side_effect = lambda k, default=None: {"token": my_token} if k == "client_config" else default

    mock_engine.storage.get_job_state.return_value = {
        "id": "test-job",
        "status": "finished",
        "client_config": {"token": stranger_token},
    }

    with raises(web.HTTPForbidden) as excinfo:
        await get_job_status_handler(mock_request)

    assert "Access denied: You do not own this job" in str(excinfo.value.text)


@mark.asyncio
async def test_access_denied_if_job_has_no_owner_info(mock_engine, mock_request):
    """Access denied if job has no owner metadata."""
    mock_request.get.side_effect = lambda k, default=None: {"token": "any"} if k == "client_config" else default

    mock_engine.storage.get_job_state.return_value = {
        "id": "test-job",
        "status": "finished",
    }

    with raises(web.HTTPForbidden):
        await get_job_status_handler(mock_request)
