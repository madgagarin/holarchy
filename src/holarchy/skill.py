# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from typing import Any, Literal

from holarchy.fsm import State


class SkillInvocation:
    """Represents an invocation of an external/worker skill returned from a step."""

    __slots__ = ("skill_name", "params", "next_state", "on_failure", "timeout", "retries", "risk", "permissions")

    def __init__(
        self,
        skill_name: str,
        params: dict[str, Any],
        next_state: State | str | None = None,
        on_failure: State | str | None = None,
        timeout: float | None = None,
        retries: int = 0,
        risk: Literal["low", "medium", "high"] = "low",
        permissions: list[str] | None = None,
    ):
        self.skill_name = skill_name
        self.params = params
        self.next_state = next_state
        self.on_failure = on_failure
        self.timeout = timeout
        self.retries = retries
        self.risk = risk
        self.permissions = list(permissions or [])

    def __repr__(self) -> str:
        return (
            f"SkillInvocation(skill_name={self.skill_name!r}, next={self.next_state!r}, on_failure={self.on_failure!r})"
        )


class Skill:
    """Factory for distributed skill invocations.

    Usage:
        ocr = Skill("document-ocr", timeout=30, fallback=OrderFlow.failed, risk="medium", permissions=["doc:read"])

        @bp.step(OrderFlow.processing)
        async def handle(order: OrderDetails):
            return ocr(image_url=order.url, next=OrderFlow.finalize)
    """

    def __init__(
        self,
        name: str,
        timeout: float | None = None,
        fallback: State | str | None = None,
        retries: int = 0,
        risk: Literal["low", "medium", "high"] = "low",
        permissions: list[str] | None = None,
    ):
        self.name = name
        self.timeout = timeout
        self.fallback = fallback
        self.retries = retries
        self.risk = risk
        self.permissions = list(permissions or [])

    def __call__(
        self,
        next: State | str | None = None,  # noqa: A002
        on_failure: State | str | None = None,
        **kwargs: Any,
    ) -> SkillInvocation:
        return SkillInvocation(
            skill_name=self.name,
            params=kwargs,
            next_state=next,
            on_failure=on_failure or self.fallback,
            timeout=self.timeout,
            retries=self.retries,
            risk=self.risk,
            permissions=self.permissions,
        )

    def __repr__(self) -> str:
        return f"Skill({self.name!r}, timeout={self.timeout!r}, fallback={self.fallback!r})"
