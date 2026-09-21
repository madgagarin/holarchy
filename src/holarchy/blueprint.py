# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from ast import (
    AsyncFunctionDef,
    Attribute,
    Call,
    Constant,
    Dict,
    FunctionDef,
    Name,
    parse,
    walk,
)
from collections.abc import Callable
from contextlib import suppress
from inspect import getsource, signature
from logging import getLogger
from textwrap import dedent
from typing import Any, cast

from fast_filter import FastF
from graphviz import Digraph
from rxon.schema import extract_json_schema

from holarchy.fsm import State, StepScope

from .datastore import AsyncDictStore

logger = getLogger(__name__)


def _PLACEHOLDER():
    return None


class ConditionalHandler:
    def __init__(self, blueprint: "Blueprint", state: str, func: Callable, condition: FastF):
        self.blueprint = blueprint
        self.state = state
        self.func = func
        self._filter = condition

    def evaluate(self, context: Any) -> bool:
        if isinstance(context, StepScope):
            try:
                return bool(self._filter.resolve(context))
            except Exception:
                return False

        if type(context).__name__.endswith("Mock"):
            try:
                return bool(self._filter.resolve(context))
            except Exception:
                return False

        try:
            scope = StepScope(context)
            return bool(self._filter.resolve(scope))
        except Exception:
            try:
                return bool(self._filter.resolve(context))
            except Exception:
                return False


class HandlerDecorator:
    def __init__(
        self,
        blueprint: "Blueprint",
        state: str | None = None,
        is_start: bool = False,
        is_end: bool = False,
        condition: FastF | None = None,
        risk: str = "low",
        permissions: list[str] | None = None,
    ):
        self._blueprint = blueprint
        self._state = state
        self._is_start = is_start
        self._is_end = is_end
        self._condition = condition
        self._risk = risk
        self._permissions = list(permissions or [])

    def __call__(self, func: Callable) -> Callable:
        state_name = self._state or func.__name__

        if self._condition is not None:
            if state_name not in self._blueprint.handlers:
                self._blueprint.handlers[state_name] = _PLACEHOLDER

            handler = ConditionalHandler(self._blueprint, state_name, func, self._condition)
            self._blueprint.conditional_handlers.append(handler)
        else:
            existing_handler = self._blueprint.handlers.get(state_name)
            if existing_handler and existing_handler is not _PLACEHOLDER:
                raise ValueError(f"Default handler for state '{state_name}' is already registered.")
            self._blueprint.handlers[state_name] = func

        if self._is_start:
            if self._blueprint.start_state is not None and self._blueprint.start_state != state_name:
                raise ValueError(
                    f"Blueprint '{self._blueprint.name}' already has a start state: '{self._blueprint.start_state}'."
                )
            self._blueprint.start_state = state_name

        if self._is_end:
            self._blueprint.end_states.add(state_name)

        self._state = state_name
        func._risk = getattr(func, "_risk", self._risk)
        func._permissions = getattr(func, "_permissions", self._permissions)
        return func


class Blueprint:
    def __init__(
        self,
        name: str,
        api_endpoint: str | None = None,
        api_version: str | None = None,
        data_stores: dict[str, Any] | None = None,
    ):
        """Initializes a new blueprint.

        Args:
            name: A unique name for the blueprint.
            api_endpoint: The path for the API endpoint, e.g., "/jobs/my_flow".
            api_version: An optional API version (e.g., "v1"). If not specified,
                         the endpoint will be unversioned.
            data_stores: An optional dictionary of data stores.

        """
        self.name = name
        self.api_endpoint = api_endpoint
        self.api_version = api_version
        self.data_stores: dict[str, AsyncDictStore] = {}
        if data_stores:
            for ds_name, ds_data in data_stores.items():
                if isinstance(ds_data, AsyncDictStore):
                    self.data_stores[ds_name] = ds_data
                else:
                    self.data_stores[ds_name] = AsyncDictStore(ds_data)

        self.handlers: dict[str, Callable] = {}
        self.aggregator_handlers: dict[str, Callable] = {}
        self.conditional_handlers: list[ConditionalHandler] = []
        self.start_state: str | None = None
        self.end_states: set[str] = set()
        self._handler_params: dict[Callable, tuple[str, ...]] = {}
        self._handler_signatures: dict[Callable, Any] = {}
        self.events_schema: dict[str, dict[str, Any]] = {}
        self._explicit_transitions: dict[str, set[str]] = {}
        self.terminal_statuses: dict[str, str] = {}
        self._deciders: dict[str, dict[str, Any]] = {}

    def add_data_store(self, name: str, initial_data: dict[str, Any]) -> None:
        """Adds a named data store to the blueprint."""
        if name in self.data_stores:
            raise ValueError(f"Data store with name '{name}' already exists.")
        self.data_stores[name] = AsyncDictStore(initial_data)

    def handler(
        self,
        *args: Any,
        is_start: bool = False,
        is_end: bool = False,
        condition: FastF | None = None,
        risk: str = "low",
        permissions: list[str] | None = None,
    ) -> Any:
        """Decorator for registering a state handler.

        If the state name is not provided, it will be inferred from the
        decorated function's name.

        Args:
            *args: Can be (state_name: str), (condition: FastF), or (state_name: str, condition: FastF).
            is_start: Whether this is the initial state of the blueprint.
            is_end: Whether this is a terminal state.
            condition: An optional FastF condition.
            risk: Risk level ('low', 'medium', 'high').
            permissions: Optional list of required permissions.

        Examples:
            @bp.handler("start_state", is_start=True)
            async def my_handler(actions): ...

            @bp.handler(is_start=True)
            async def start(actions): ...  # state name is "start"

            @bp.handler
            async def process(actions): ...  # state name is "process"

            # With conditions:
            @bp.handler("process", F.initial_data["x"] == 1)
            async def process_special(actions): ...

            @bp.handler(F.initial_data["x"] == 1)
            async def process_special(actions): ...  # state name is "process_special"
        """
        state_name = None
        cond = condition

        if len(args) == 1:
            arg = args[0]
            if isinstance(arg, FastF):
                cond = arg
            elif callable(arg):
                # Used as @bp.handler without parens
                decorator = HandlerDecorator(
                    self,
                    state=arg.__name__,
                    is_start=is_start,
                    is_end=is_end,
                    condition=cond,
                    risk=risk,
                    permissions=permissions,
                )
                return decorator(arg)
            elif isinstance(arg, str):
                state_name = arg
            elif arg is not None:
                raise TypeError(f"Invalid handler argument type: {type(arg)}")
        elif len(args) == 2:
            if isinstance(args[0], str) and isinstance(args[1], FastF):
                state_name = args[0]
                cond = args[1]
            else:
                raise TypeError(
                    f"Invalid handler arguments: expected (str, FastF), got ({type(args[0])}, {type(args[1])})"
                )
        elif len(args) > 2:
            raise TypeError(f"handler() takes at most 2 positional arguments but {len(args)} were given")

        return HandlerDecorator(
            self,
            state=state_name,
            is_start=is_start,
            is_end=is_end,
            condition=cond,
            risk=risk,
            permissions=permissions,
        )

    def add_transition(self, from_state: Any, to_state: Any) -> None:
        """Explicitly registers a valid transition between states."""
        src = str(from_state)
        dst = str(to_state)
        if src not in self._explicit_transitions:
            self._explicit_transitions[src] = set()
        self._explicit_transitions[src].add(dst)

    def start(
        self,
        state: Any = None,
        risk: str = "low",
        permissions: list[str] | None = None,
    ) -> Any:
        """Decorator for registering the entry point (start step) of the blueprint.

        Examples:
            @bp.start(OrderFlow.init)
            async def init(order: OrderDetails, ctx: Context): ...

            @bp.start
            async def init(order: OrderDetails): ...
        """
        if callable(state) and not isinstance(state, State):
            return self.handler(state, is_start=True, risk=risk, permissions=permissions)
        return self.handler(state, is_start=True, risk=risk, permissions=permissions)

    def step(
        self,
        *args: Any,
        condition: FastF | None = None,
        on_success: Any = None,
        on_error: Any = None,
        risk: str = "low",
        permissions: list[str] | None = None,
    ) -> Any:
        """Decorator for registering an intermediate step in the blueprint.

        Args:
            *args: State or state name, and optional condition.
            condition: An optional FastF condition.
            on_success: Target state upon successful completion.
            on_error: Target state upon error.
            risk: Risk level ('low', 'medium', 'high').
            permissions: Required permissions list.

        Examples:
            @bp.step(OrderFlow.payment)
            async def pay(order: OrderDetails): ...

            @bp.step(OrderFlow.payment, F.amount > 50_000)
            async def vip_pay(order: OrderDetails): ...
        """
        decorator = self.handler(
            *args,
            is_start=False,
            is_end=False,
            condition=condition,
            risk=risk,
            permissions=permissions,
        )
        if callable(decorator):
            orig_call = decorator.__call__

            def wrapped_decorator(func: Callable) -> Callable:
                func._risk = risk
                func._permissions = list(permissions or [])
                if on_success:
                    func._on_success = str(on_success)
                if on_error:
                    func._on_error = str(on_error)
                res = orig_call(func)
                st_name = getattr(decorator, "_state", None) or func.__name__
                if on_success:
                    self.add_transition(st_name, str(on_success))
                if on_error:
                    self.add_transition(st_name, str(on_error))
                return res

            return wrapped_decorator
        return decorator

    def end(
        self,
        state: Any = None,
        status: str = "finished",
        risk: str = "low",
        permissions: list[str] | None = None,
    ) -> Any:
        """Decorator for registering a terminal step in the blueprint.

        Args:
            state: The terminal state.
            status: Final status of the job (default 'finished').
            risk: Risk level ('low', 'medium', 'high').
            permissions: Required permissions list.

        Examples:
            @bp.end(OrderFlow.finalize)
            async def finalize(payment: PaymentResult) -> OrderReceipt: ...

            @bp.end(OrderFlow.failed, status="failed")
            async def on_failure(error: dict): ...
        """
        if callable(state) and not isinstance(state, State):
            st_name = state.__name__
            self.terminal_statuses[st_name] = status
            return self.handler(state, is_end=True, risk=risk, permissions=permissions)

        decorator = self.handler(state, is_end=True, risk=risk, permissions=permissions)
        orig_call = decorator.__call__

        def wrapped_decorator(func: Callable) -> Callable:
            res = orig_call(func)
            st_name = getattr(decorator, "_state", None) or func.__name__
            self.terminal_statuses[st_name] = status
            return res

        return wrapped_decorator

    def decide(
        self,
        candidates_or_name: Any = None,
        fallback: Any = None,
        timeout_seconds: float = 3.0,
        candidates: list[Any] | None = None,
        name: Any = None,
        risk: str = "low",
        permissions: list[str] | None = None,
    ) -> Any:
        """Decorator for registering an advisory decision routing handler.

        Principles (howdeploy/jev-layer):
        - Host-Owned Choice: The router (e.g. LLM or heuristic) may only select from 'candidates'.
        - Fail-Open Guarantee: If the handler times out, fails, or returns an invalid candidate,
          the host automatically transitions to 'fallback'.
        """
        if isinstance(candidates_or_name, str):
            decider_name = candidates_or_name
            actual_cands = candidates or []
            actual_fallback = fallback or (actual_cands[0] if actual_cands else "fallback")
        elif isinstance(candidates_or_name, (list, tuple, set)):
            decider_name = str(name) if name else None
            actual_cands = list(candidates_or_name)
            actual_fallback = fallback or (actual_cands[0] if actual_cands else "fallback")
        else:
            decider_name = str(name) if name else None
            actual_cands = candidates or []
            actual_fallback = fallback or (actual_cands[0] if actual_cands else "fallback")

        candidates_str = [str(c) for c in actual_cands]
        fallback_str = str(actual_fallback)

        def decorator(func: Callable) -> Callable:
            state_name = decider_name or func.__name__
            func._risk = risk
            func._permissions = list(permissions or [])
            self._deciders[state_name] = {
                "candidates": candidates_str,
                "fallback": fallback_str,
                "timeout_seconds": timeout_seconds,
                "func": func,
                "risk": risk,
                "permissions": list(permissions or []),
            }
            func._is_decider = True
            func._decide_meta = self._deciders[state_name]

            # Only register as an FSM transition state if candidates and fallback are explicitly specified
            if candidates_str and fallback is not None:
                for c in candidates_str:
                    self.add_transition(state_name, c)
                self.add_transition(state_name, fallback_str)
                dec = self.handler(state_name, is_start=False, is_end=False, risk=risk, permissions=permissions)
                return dec(func)

            return func

        return decorator

    def to_dag(self) -> dict[str, Any]:
        """Exports the blueprint's state machine graph topology for spatial visualization."""
        transitions, _ = self._get_all_transitions()
        nodes = []
        all_states = set(self.handlers.keys()) | set(self.end_states)
        if self.start_state:
            all_states.add(self.start_state)
        for state_name in sorted(all_states):
            h_func = self.handlers.get(state_name)
            is_start = state_name == self.start_state
            is_end = state_name in self.end_states
            is_decider = state_name in self._deciders
            risk = getattr(h_func, "_risk", "low") if h_func else "low"
            dec_meta = self._deciders.get(state_name) or {}
            node_type = "decider" if is_decider else ("subgraph" if getattr(h_func, "_is_subgraph", False) else "step")
            node = {
                "id": state_name,
                "name": state_name,
                "type": node_type,
                "is_start": is_start,
                "is_end": is_end,
                "is_decider": is_decider,
                "risk": risk,
            }
            if is_decider:
                node["candidates"] = dec_meta.get("candidates", [])
                node["fallback"] = dec_meta.get("fallback")
                node["timeout_seconds"] = dec_meta.get("timeout_seconds", 3.0)
            nodes.append(node)

        edges = []
        for src, dsts in sorted(transitions.items()):
            dec_meta = self._deciders.get(src, {})
            fallback_target = dec_meta.get("fallback")
            for dst in sorted(dsts):
                edge: dict[str, Any] = {
                    "from": src,
                    "to": dst,
                }
                if src in self._deciders and dst == fallback_target:
                    edge["is_fallback"] = True
                edges.append(edge)

        return {
            "blueprint_name": self.name,
            "start_state": self.start_state,
            "nodes": nodes,
            "edges": edges,
        }

    def get_security_metadata(self) -> dict[str, Any]:
        """Calculates aggregated risk and permissions across all steps and skills in the blueprint."""
        risk_levels = {"low": 1, "medium": 2, "high": 3}
        inv_risk = {1: "low", 2: "medium", 3: "high"}
        max_risk_val = 1
        all_permissions: set[str] = set()

        for handler in self.handlers.values():
            if not callable(handler):
                continue
            r = getattr(handler, "_risk", "low")
            max_risk_val = max(max_risk_val, risk_levels.get(r, 1))
            perms = getattr(handler, "_permissions", [])
            if isinstance(perms, (list, tuple, set)):
                all_permissions.update(perms)

        for decider in self._deciders.values():
            if not isinstance(decider, dict):
                continue
            r = decider.get("risk", "low")
            max_risk_val = max(max_risk_val, risk_levels.get(r, 1))
            perms = decider.get("permissions", [])
            if isinstance(perms, (list, tuple, set)):
                all_permissions.update(perms)

        return {
            "risk": inv_risk.get(max_risk_val, "low"),
            "permissions": sorted(all_permissions),
        }

    def aggregator(self, state_or_func: str | Callable | None = None) -> Any:
        """Decorator for registering an aggregator handler.

        If the state name is not provided, it will be inferred from the
        decorated function's name.

        Args:
            state_or_func: The name of the state or the function being decorated.

        Examples:
            @bp.aggregator("aggregate_results")
            async def my_aggregator(aggregation_results, actions): ...

            @bp.aggregator
            async def collect_results(aggregation_results, actions): ...  # state name is "collect_results"
        """

        def decorator(func: Callable) -> Callable:
            state_name = state_or_func if isinstance(state_or_func, str) else func.__name__
            if state_name in self.aggregator_handlers:
                raise ValueError(f"Aggregator for state '{state_name}' is already registered.")
            self.aggregator_handlers[state_name] = func
            return func

        if callable(state_or_func):
            return decorator(state_or_func)

        return decorator

    def event(self, name: str, schema: Any) -> Callable:
        """Decorator or method to register an event schema for the blueprint."""
        self.events_schema[name] = extract_json_schema(schema) or {}

        def decorator(func: Callable) -> Callable:
            return func

        return decorator

    def get_contract(self) -> dict[str, Any]:
        """Returns the public contract of the blueprint."""
        return {
            "name": self.name,
            "api_endpoint": self.api_endpoint,
            "api_version": self.api_version,
            "start_state": self.start_state,
            "end_states": list(self.end_states),
            "handlers": list(self.handlers.keys()),
            "aggregators": list(self.aggregator_handlers.keys()),
            "conditional_handlers": [
                {"state": ch.state, "condition": repr(ch._filter)} for ch in self.conditional_handlers
            ],
            "events_schema": self.events_schema,
        }

    def validate(self) -> None:
        """Validates that the blueprint is configured correctly."""
        if self.start_state is None:
            raise ValueError(f"Blueprint '{self.name}' must have exactly one start state.")
        self._analyze_handlers()
        self.validate_integrity()

    def validate_integrity(self) -> None:
        """Checks for dangling transitions and unreachable states."""
        transitions, parse_errors = self._get_all_transitions()
        defined_states = (
            set(self.handlers.keys())
            | set(self.aggregator_handlers.keys())
            | {ch.state for ch in self.conditional_handlers}
        )

        for source_state, targets in transitions.items():
            for target_state in targets:
                if target_state not in defined_states:
                    raise ValueError(
                        f"Blueprint '{self.name}' has a dangling transition: "
                        f"state '{source_state}' leads to non-existent state '{target_state}'."
                    )

        if self.start_state:
            reachable = {self.start_state}
            stack = [self.start_state]
            while stack:
                current = stack.pop()
                for target in transitions.get(current, set()):
                    if target not in reachable:
                        reachable.add(target)
                        stack.append(target)

            unreachable = defined_states - reachable
            if unreachable:
                msg = (
                    f"Blueprint '{self.name}' has unreachable states: {', '.join(unreachable)}. "
                    "All states must be reachable from the start state."
                )
                if parse_errors > 0:
                    logger.warning(
                        f"{msg} (Validation was based on incomplete data due to {parse_errors} parse errors)"
                    )
                else:
                    raise ValueError(msg)

    def _get_all_transitions(self) -> tuple[dict[str, set[str]], int]:
        """Parses handler source code and explicit annotations to find all possible transitions.

        Returns a tuple of (transitions_map, parse_error_count).
        """
        transitions: dict[str, set[str]] = {k: set(v) for k, v in self._explicit_transitions.items()}
        parse_errors = 0

        defined_states = (
            set(self.handlers.keys())
            | set(self.aggregator_handlers.keys())
            | {ch.state for ch in self.conditional_handlers}
        )

        scope_vars: dict[str, Any] = {}

        def _resolve_target(arg_node: Any) -> str | None:
            if isinstance(arg_node, Call) and arg_node.args:
                return _resolve_target(arg_node.args[0])
            if isinstance(arg_node, Constant):
                return str(arg_node.value)
            if isinstance(arg_node, Attribute):
                attr_name = arg_node.attr
                for s in defined_states:
                    if s == attr_name or s.endswith(f":{attr_name}"):
                        return s
                if isinstance(arg_node.value, Name):
                    candidate = f"{arg_node.value.id}:{attr_name}"
                    if candidate in defined_states:
                        return candidate
                return attr_name
            if isinstance(arg_node, Name):
                if scope_vars and arg_node.id in scope_vars:
                    val = scope_vars[arg_node.id]
                    val_str = str(val)
                    if val_str in defined_states:
                        return val_str
                for s in defined_states:
                    if s == arg_node.id or s.endswith(f":{arg_node.id}"):
                        return s
                return arg_node.id
            return None

        all_handlers = (
            list(self.handlers.items())
            + list(self.aggregator_handlers.items())
            + [(ch.state, ch.func) for ch in self.conditional_handlers]
        )

        for state, func in all_handlers:
            if state not in transitions:
                transitions[state] = set()
            if func is _PLACEHOLDER:
                continue
            try:
                source = dedent(getsource(func))
                tree = parse(source)
                scope_vars.clear()
                scope_vars.update(getattr(func, "__globals__", {}))
                closure = getattr(func, "__closure__", None)
                code = getattr(func, "__code__", None)
                if closure and code and hasattr(code, "co_freevars"):
                    for var_name, cell in zip(code.co_freevars, closure, strict=False):
                        with suppress(ValueError):
                            scope_vars[var_name] = cell.cell_contents

                fn_nodes = []
                for stmt in getattr(tree, "body", []):
                    if isinstance(stmt, (FunctionDef, AsyncFunctionDef)):
                        for body_stmt in stmt.body:
                            fn_nodes.extend(walk(body_stmt))
                    else:
                        fn_nodes.extend(walk(stmt))

                for node in fn_nodes:
                    if not isinstance(node, Call):
                        continue

                    func_name = ""
                    if isinstance(node.func, Attribute):
                        func_name = node.func.attr
                    elif isinstance(node.func, Name):
                        func_name = node.func.id

                    # Check if calling a Skill object with defined fallback
                    if func_name and func_name in scope_vars:
                        obj = scope_vars[func_name]
                        if type(obj).__name__ == "Skill" and getattr(obj, "fallback", None):
                            for s in defined_states:
                                if s == str(obj.fallback) or s.endswith(f":{obj.fallback}"):
                                    transitions[state].add(s)
                                    break
                            else:
                                transitions[state].add(str(obj.fallback))

                    if func_name in ("go_to", "Next") and node.args:
                        target = _resolve_target(node.args[0])
                        if target:
                            transitions[state].add(target)

                    elif func_name in ("dispatch_task", "await_human_approval", "run_blueprint"):
                        for keyword in node.keywords:
                            if keyword.arg == "transitions" and isinstance(keyword.value, Dict):
                                for val_node in keyword.value.values:
                                    target = _resolve_target(val_node)
                                    if target:
                                        transitions[state].add(target)

                    elif func_name == "dispatch_parallel":
                        for keyword in node.keywords:
                            if keyword.arg == "aggregate_into":
                                target = _resolve_target(keyword.value)
                                if target:
                                    transitions[state].add(target)

                    for keyword in node.keywords:
                        if keyword.arg in ("next", "next_state", "on_success", "on_error", "on_failure", "fallback"):
                            target = _resolve_target(keyword.value)
                            if target:
                                transitions[state].add(target)

            except (TypeError, OSError, SyntaxError) as e:
                logger.warning(f"Could not parse handler for state '{state}' in blueprint '{self.name}': {e}")
                parse_errors += 1

        return transitions, parse_errors

    def _analyze_handlers(self) -> None:
        """Analyzes and caches parameters for all registered handlers."""
        all_funcs = (
            list(self.handlers.values())
            + list(self.aggregator_handlers.values())
            + [ch.func for ch in self.conditional_handlers]
        )

        for func in all_funcs:
            sig = signature(func)
            self._handler_params[func] = tuple(sig.parameters.keys())
            self._handler_signatures[func] = sig

    def get_handler_params(self, func: Callable) -> tuple[str, ...]:
        """Returns the cached parameters for a handler function."""
        return self._handler_params.get(func, ())

    def get_handler_signature(self, func: Callable) -> Any | None:
        """Returns the cached signature for a handler function."""
        return self._handler_signatures.get(func)

    def find_handler(self, state: str, context: Any) -> Callable:
        for handler in self.conditional_handlers:
            if handler.state == state and handler.evaluate(context):
                return handler.func
        default_handler = self.handlers.get(state)
        if default_handler and default_handler is not _PLACEHOLDER:
            return default_handler

        aggregator = self.aggregator_handlers.get(state)
        if aggregator:
            return aggregator

        raise ValueError(
            f"No suitable handler found for state '{state}' in blueprint '{self.name}' for the given context. "
            "(All conditions failed and no default handler registered)"
        )

    def render_graph(self, output_filename: str | None = None, output_format: str = "png") -> str | None:
        dot = Digraph(comment=f"State Machine for {self.name}")
        dot.attr("node", shape="box", style="rounded")

        transitions, _ = self._get_all_transitions()
        defined_states = (
            set(self.handlers.keys())
            | set(self.aggregator_handlers.keys())
            | {ch.state for ch in self.conditional_handlers}
        )
        states = defined_states.copy()

        for source, targets in transitions.items():
            for target in targets:
                states.add(target)
                dot.edge(source, target)

        for state in states:
            dot.node(state, state)

        if not output_filename:
            return cast(str, dot.source)
        dot.render(output_filename, format=output_format, cleanup=True)
        logger.info(f"Graph rendered to {output_filename}.{output_format}")
        return None
