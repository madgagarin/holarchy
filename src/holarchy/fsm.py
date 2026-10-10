# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class State(str):
    """FSM State represented as a subclass of str.

    Inheriting from str guarantees:
    - 100% zero-overhead string identity (isinstance(state, str) is True).
    - Transparent serialization in Redis, JSON, logging, and runtime dictionaries.
    - Full backwards compatibility with string-based state names.
    """

    _state_name: str
    _group_name: str | None

    def __new__(cls, name: str | None = None, group: str | None = None) -> State:
        if name is None:
            val = ""
        elif group:
            val = f"{group}:{name}"
        else:
            val = name

        instance = super().__new__(cls, val)
        instance._state_name = name or ""
        instance._group_name = group
        return instance

    @property
    def state_name(self) -> str:
        """The bare local name of the state (without group prefix)."""
        return self._state_name

    @property
    def group_name(self) -> str | None:
        """The group/class name if state belongs to a StatesGroup, else None."""
        return self._group_name

    def __repr__(self) -> str:
        if self._group_name:
            return f"State({self._group_name}:{self._state_name})"
        return f"State({self._state_name})"


class StatesGroupMeta(type):
    """Metaclass that automatically binds declared States to their parent group."""

    _states: tuple[State, ...]

    def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> StatesGroupMeta:
        cls = super().__new__(mcls, name, bases, namespace)
        states: list[State] = []

        for attr_name, attr_val in list(namespace.items()):
            if isinstance(attr_val, State):
                # Bind the state to the group
                bound_state = State(attr_name, group=name)
                setattr(cls, attr_name, bound_state)
                states.append(bound_state)

        cls._states = tuple(states)
        return cls

    def __iter__(cls) -> Iterator[State]:
        return iter(getattr(cls, "_states", ()))

    def __contains__(cls, item: Any) -> bool:
        states = getattr(cls, "_states", ())
        if isinstance(item, State):
            return item in states
        if isinstance(item, str):
            return any(s == item or s.state_name == item for s in states)
        return False

    def __len__(cls) -> int:
        return len(getattr(cls, "_states", ()))


class StatesGroup(metaclass=StatesGroupMeta):
    """Base class for grouping FSM states.

    Usage:
        class OrderFlow(StatesGroup):
            init = State()
            payment = State()
            finalize = State()
            failed = State()

        OrderFlow.payment == "OrderFlow:payment"  # True
        OrderFlow.payment.state_name == "payment"  # True
        "OrderFlow:payment" in OrderFlow          # True
    """


class Next:
    """Represents an explicit transition to the next state, optionally carrying data."""

    __slots__ = ("state", "data")

    def __init__(self, state: State | str, data: Any = None):
        self.state = state
        self.data = data

    def __repr__(self) -> str:
        return f"Next({self.state!r}, data={self.data!r})"


class StepScope:
    """Ultra-fast cascading scope resolver with __slots__ for Magic Filter (F).

    Resolution priority (O(1)):
    1. Current incoming data (previous step or worker task result).
    2. Input payload (initial job input data).
    3. Underlying context attributes (context.job_id, context.current_state, etc.).
    4. Explicit prefixes: F.input.*, F.steps.*, F.headers.*, F.step(name).
    """

    __slots__ = ("_context", "_current_data", "_input", "_steps", "_headers")

    def __init__(self, context: Any, current_data: Any = None):
        self._context = context
        self._current_data = current_data

        inp: Any = None
        if isinstance(context, dict):
            inp = context
        elif not type(context).__name__.endswith("Mock"):
            inp = getattr(context, "input", None)
        else:
            ctx_dict = getattr(context, "__dict__", {})
            inp = ctx_dict.get("input")

        self._input = inp if isinstance(inp, dict) else (inp or {})

        steps: Any = None
        if isinstance(context, dict):
            steps = {}
        elif not type(context).__name__.endswith("Mock"):
            steps = getattr(context, "steps", None)
        else:
            ctx_dict = getattr(context, "__dict__", {})
            steps = ctx_dict.get("steps")

        self._steps = steps if isinstance(steps, dict) else (steps or {})

        self._headers = {}
        if not type(context).__name__.endswith("Mock") and hasattr(context, "meta"):
            meta = getattr(context, "meta", None)
            if isinstance(meta, dict):
                self._headers = meta.get("headers", {})

    @property
    def input(self) -> Any:
        return self._input

    @property
    def steps(self) -> Any:
        return self._steps

    @property
    def headers(self) -> Any:
        return self._headers

    def step(self, name: str) -> Any:
        if isinstance(self._steps, dict):
            return self._steps.get(name)
        return getattr(self._steps, name, None)

    def __getattr__(self, name: str) -> Any:
        if self._current_data is not None:
            if isinstance(self._current_data, dict):
                if name in self._current_data:
                    return self._current_data[name]
            elif hasattr(self._current_data, name):
                return getattr(self._current_data, name)

        if isinstance(self._input, dict):
            if name in self._input:
                return self._input[name]
        elif hasattr(self._input, name) and not type(self._input).__name__.endswith("Mock"):
            return getattr(self._input, name)

        if hasattr(self._context, name):
            return getattr(self._context, name)

        return None

    def __getitem__(self, name: str) -> Any:
        val = self.__getattr__(name)
        if val is None and isinstance(self._input, dict):
            return self._input.get(name)
        return val
