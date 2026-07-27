# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import wait_for
from logging import getLogger
from typing import Any

logger = getLogger(__name__)


class MiddlewareError(Exception):
    """Raised when a middleware fails or rejects an operation."""

    pass


class BaseMiddleware:
    """Abstract base class for custom trust boundary middlewares."""

    async def process_handler_request(self, context: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Intercepts parameters right before executing a local blueprint handler."""
        return params

    async def process_handler_response(self, context: Any, result: Any) -> Any:
        """Intercepts return value after local handler completion."""
        return result

    async def process_outbound_task(self, context: Any, task_payload: dict[str, Any]) -> dict[str, Any]:
        """Intercepts task payload before enqueuing for worker execution."""
        return task_payload

    async def process_inbound_result(self, context: Any, result_payload: dict[str, Any]) -> dict[str, Any]:
        """Intercepts task result received from worker before processing."""
        return result_payload

    async def process_inbound_event(self, context: Any, event_payload: dict[str, Any]) -> dict[str, Any]:
        """Intercepts spontaneous worker event before applying to job state."""
        return event_payload


class MiddlewareChain:
    """Manages an ordered sequence of middlewares executed in FIFO order."""

    def __init__(self) -> None:
        self._middlewares: list[BaseMiddleware] = []

    def add(self, middleware: BaseMiddleware) -> None:
        if middleware not in self._middlewares:
            self._middlewares.append(middleware)

    def remove(self, middleware: BaseMiddleware) -> None:
        if middleware in self._middlewares:
            self._middlewares.remove(middleware)

    async def run_process_handler_request(
        self, context: Any, params: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any]:
        current_params = params
        for mw in self._middlewares:
            try:
                current_params = await wait_for(mw.process_handler_request(context, current_params), timeout=timeout)
            except MiddlewareError:
                raise
            except Exception as e:
                logger.error(f"Middleware {mw.__class__.__name__} failed in process_handler_request: {e}")
                raise MiddlewareError(f"Middleware execution failed: {e}") from e
        return current_params

    async def run_process_handler_response(self, context: Any, result: Any, timeout: float = 5.0) -> Any:
        current_result = result
        for mw in self._middlewares:
            try:
                current_result = await wait_for(mw.process_handler_response(context, current_result), timeout=timeout)
            except MiddlewareError:
                raise
            except Exception as e:
                logger.error(f"Middleware {mw.__class__.__name__} failed in process_handler_response: {e}")
                raise MiddlewareError(f"Middleware execution failed: {e}") from e
        return current_result

    async def run_process_outbound_task(
        self, context: Any, task_payload: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any]:
        current_task = task_payload
        for mw in self._middlewares:
            try:
                current_task = await wait_for(mw.process_outbound_task(context, current_task), timeout=timeout)
            except MiddlewareError:
                raise
            except Exception as e:
                logger.error(f"Middleware {mw.__class__.__name__} failed in process_outbound_task: {e}")
                raise MiddlewareError(f"Middleware execution failed: {e}") from e
        return current_task

    async def run_process_inbound_result(
        self, context: Any, result_payload: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any]:
        current_result = result_payload
        for mw in self._middlewares:
            try:
                current_result = await wait_for(mw.process_inbound_result(context, current_result), timeout=timeout)
            except MiddlewareError:
                raise
            except Exception as e:
                logger.error(f"Middleware {mw.__class__.__name__} failed in process_inbound_result: {e}")
                raise MiddlewareError(f"Middleware execution failed: {e}") from e
        return current_result

    async def run_process_inbound_event(
        self, context: Any, event_payload: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any]:
        current_event = event_payload
        for mw in self._middlewares:
            try:
                current_event = await wait_for(mw.process_inbound_event(context, current_event), timeout=timeout)
            except MiddlewareError:
                raise
            except Exception as e:
                logger.error(f"Middleware {mw.__class__.__name__} failed in process_inbound_event: {e}")
                raise MiddlewareError(f"Middleware execution failed: {e}") from e
        return current_event
