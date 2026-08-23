# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import sleep

from pytest import mark, raises

from holarchy.middleware.base import BaseMiddleware, MiddlewareChain, MiddlewareError


class CustomHeaderMiddleware(BaseMiddleware):
    async def process_outbound_task(self, context, task_payload):
        task_payload["injected"] = True
        return task_payload

    async def process_handler_request(self, context, params):
        params["mw_req"] = True
        return params

    async def process_handler_response(self, context, result):
        if isinstance(result, dict):
            result["mw_resp"] = True
        return result

    async def process_inbound_result(self, context, result_payload):
        result_payload["mw_in_res"] = True
        return result_payload

    async def process_inbound_event(self, context, event_payload):
        event_payload["mw_in_ev"] = True
        return event_payload


class ChainedMiddlewareA(BaseMiddleware):
    async def process_handler_request(self, context, params):
        params["order"] = params.get("order", "") + "A"
        return params


class ChainedMiddlewareB(BaseMiddleware):
    async def process_handler_request(self, context, params):
        params["order"] = params.get("order", "") + "B"
        return params


class HangingMiddleware(BaseMiddleware):
    async def process_handler_request(self, context, params):
        await sleep(10.0)
        return params


class FailingMiddleware(BaseMiddleware):
    async def process_handler_request(self, context, params):
        raise MiddlewareError("Security rule violation")


@mark.asyncio
async def test_middleware_chain_all_methods():
    chain = MiddlewareChain()
    mw = CustomHeaderMiddleware()
    chain.add(mw)

    # 1. Outbound Task
    task = await chain.run_process_outbound_task({}, {"type": "t1"})
    assert task["injected"] is True

    # 2. Handler Request
    req = await chain.run_process_handler_request({}, {"arg": 1})
    assert req["mw_req"] is True

    # 3. Handler Response
    resp = await chain.run_process_handler_response({}, {"ret": "ok"})
    assert resp["mw_resp"] is True

    # 4. Inbound Result
    in_res = await chain.run_process_inbound_result({}, {"status": "success"})
    assert in_res["mw_in_res"] is True

    # 5. Inbound Event
    in_ev = await chain.run_process_inbound_event({}, {"event": "ev1"})
    assert in_ev["mw_in_ev"] is True


@mark.asyncio
async def test_middleware_chain_fifo_order_and_add_remove():
    chain = MiddlewareChain()
    mw_a = ChainedMiddlewareA()
    mw_b = ChainedMiddlewareB()

    chain.add(mw_a)
    chain.add(mw_b)
    assert len(chain._middlewares) == 2

    res = await chain.run_process_handler_request({}, {})
    assert res["order"] == "AB"

    # Remove MW A
    chain.remove(mw_a)
    assert len(chain._middlewares) == 1

    res2 = await chain.run_process_handler_request({}, {})
    assert res2["order"] == "B"


@mark.asyncio
async def test_middleware_chain_error_propagation():
    chain = MiddlewareChain()
    chain.add(FailingMiddleware())

    with raises(MiddlewareError) as exc_info:
        await chain.run_process_handler_request({}, {"param": 1})

    assert "Security rule violation" in str(exc_info.value)


@mark.asyncio
async def test_middleware_chain_timeout_handling():
    chain = MiddlewareChain()
    chain.add(HangingMiddleware())

    with raises(MiddlewareError) as exc_info:
        await chain.run_process_handler_request({}, {}, timeout=0.1)

    assert "Middleware execution failed" in str(exc_info.value)
