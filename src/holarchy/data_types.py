# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

import dataclasses
from typing import TYPE_CHECKING, Any, NamedTuple

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
    initial_data: dict[str, Any]
    state_history: dict[str, Any]
    client: ClientConfig
    actions: "ActionFactory"
    data_stores: Any | None = None
    tracing_context: dict[str, Any] | None = None
    aggregation_results: dict[str, Any] | None = None
    webhook_url: str | None = None
    task_files: Any | None = None
    policy: dict[str, Any] | None = None
    input: dict[str, Any] | None = None
    steps: dict[str, Any] | None = None
    history: list[dict[str, Any]] | None = None
    output: Any | None = None
    params: dict[str, Any] | None = None
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
            return self.meta.get("headers", {})
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
        elif hasattr(payload, "__dataclass_fields__"):
            payload = dataclasses.asdict(payload)

        return self.actions.run_blueprint(
            blueprint_name=blueprint_name,
            initial_data=payload if isinstance(payload, dict) else (payload or {}),
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
    """Ensures bidirectional synchronization between modern 5 zones and legacy aliases."""
    if not isinstance(state, dict):
        return

    # 1. input <-> initial_data
    inp = state.get("input")
    init = state.get("initial_data")
    if isinstance(inp, dict) and isinstance(init, dict):
        init.update({k: v for k, v in inp.items() if k not in init or init[k] is None})
        inp.update({k: v for k, v in init.items() if k not in inp or inp[k] is None})
        state["input"] = inp
        state["initial_data"] = init
    elif isinstance(inp, dict):
        state["initial_data"] = inp
    elif isinstance(init, dict):
        state["input"] = init
    else:
        state["input"] = {}
        state["initial_data"] = {}

    # 2. steps <-> state_history
    steps = state.get("steps")
    sh = state.get("state_history")
    if isinstance(steps, dict) and isinstance(sh, dict):
        sh.update({k: v for k, v in steps.items() if k not in sh or sh[k] is None})
        steps.update({k: v for k, v in sh.items() if k not in steps or steps[k] is None})
        state["steps"] = steps
        state["state_history"] = sh
    elif isinstance(steps, dict):
        state["state_history"] = steps
    elif isinstance(sh, dict):
        state["steps"] = sh
    else:
        state["steps"] = {}
        state["state_history"] = {}

    # 3. output <-> result
    if state.get("output") is not None:
        state["result"] = state["output"]
    elif state.get("result") is not None:
        state["output"] = state["result"]
    else:
        if "output" not in state:
            state["output"] = None

    # 4. history
    if not isinstance(state.get("history"), list):
        state["history"] = []

    # 5. params <-> client_config["params"]
    if not isinstance(state.get("params"), dict):
        cc = state.get("client_config")
        if isinstance(cc, dict) and isinstance(cc.get("params"), dict):
            state["params"] = cc["params"]
        else:
            state["params"] = {}

    # 6. meta <-> metadata
    if not isinstance(state.get("meta"), dict):
        meta = state.get("metadata")
        if isinstance(meta, dict):
            state["meta"] = meta
        else:
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
