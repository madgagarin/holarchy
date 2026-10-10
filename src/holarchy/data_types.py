# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, NamedTuple

from msgspec import to_builtins
from rxon.models import InstalledArtifact, Resources

from .fsm import Next

if TYPE_CHECKING:
    from .context import ActionFactory


class ClientConfig(NamedTuple):
    """Static client configuration, obtained from `clients.toml`."""

    token: str
    plan: str
    params: dict[str, Any]


class JobContext(NamedTuple):
    """Job execution context, passed to each handler."""

    job_id: str
    current_state: str
    input: dict[str, Any]
    steps: dict[str, Any]
    output: Any | None
    history: list[dict[str, Any]]
    params: dict[str, Any]
    client: ClientConfig
    actions: "ActionFactory"
    data_stores: Any | None = None
    tracing_context: dict[str, Any] | None = None
    aggregation_results: dict[str, Any] | None = None
    webhook_url: str | None = None
    task_files: Any | None = None
    policy: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None

    def go_to(self, state: Any, data: Any = None) -> Any:
        self.actions.go_to(str(state))
        return Next(state, data=data)

    def await_human_approval(self, *args: Any, **kwargs: Any) -> Any:
        return self.actions.await_human_approval(*args, **kwargs)

    def dispatch_task(self, *args: Any, **kwargs: Any) -> Any:
        return self.actions.dispatch_task(*args, **kwargs)

    def dispatch_parallel(self, *args: Any, **kwargs: Any) -> Any:
        return self.actions.dispatch_parallel(*args, **kwargs)

    @property
    def headers(self) -> dict[str, Any]:
        if isinstance(self.meta, dict):
            h = self.meta.get("headers")
            if isinstance(h, dict):
                return h
        return {}

    def run_blueprint(
        self,
        blueprint_name: str,
        input: Any = None,  # noqa: A002
        transitions: dict[str, str] | None = None,
        dispatch_timeout: int | None = None,
        result_timeout: int | None = None,
    ) -> None:
        payload = input
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        elif hasattr(payload, "dict") and callable(payload.dict):
            payload = payload.dict()
        elif hasattr(payload, "__struct_fields__"):
            payload = to_builtins(payload)
        elif hasattr(payload, "__dataclass_fields__"):
            payload = asdict(payload)

        return self.actions.run_blueprint(
            blueprint_name=blueprint_name,
            input=payload if isinstance(payload, dict) else (payload or {}),
            transitions=transitions or {},
            dispatch_timeout=dispatch_timeout,
            result_timeout=result_timeout,
        )

    def save_result(self, result: Any) -> None:
        self.actions.save_result(result)

    async def decide(
        self,
        candidates: list[Any],
        fallback: Any,
        timeout_seconds: float = 3.0,
        intent: str | None = None,
        evaluator: Any = None,
    ) -> Any:
        return await self.actions.decide(
            candidates=candidates,
            fallback=fallback,
            timeout_seconds=timeout_seconds,
            intent=intent,
            evaluator=evaluator,
            context=self,
        )


# Context is the primary clean developer-facing alias for JobContext
Context = JobContext


def ensure_storage_zones(state: dict[str, Any]) -> None:
    """Ensures presence and structure of the 5 pure storage zones in job state."""
    if not isinstance(state, dict):
        return

    if not isinstance(state.get("input"), dict):
        state["input"] = {}

    if not isinstance(state.get("steps"), dict):
        state["steps"] = {}

    if "output" not in state:
        state["output"] = None

    if not isinstance(state.get("history"), list):
        state["history"] = []

    if not isinstance(state.get("params"), dict):
        state["params"] = {}

    if not isinstance(state.get("meta"), dict):
        state["meta"] = {}


class WorkerInfo(NamedTuple):
    """Complete information about the worker, transmitted upon registration."""

    worker_id: str
    worker_type: str
    supported_skills: list[Any]  # list[SkillInfo]
    resources: Resources
    installed_software: dict[str, str]
    installed_artifacts: list[InstalledArtifact]
    capabilities: Any  # WorkerCapabilities
    skills_hash: str | None = None
