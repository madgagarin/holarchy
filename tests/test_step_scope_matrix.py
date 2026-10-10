# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from dataclasses import dataclass
from typing import Any, TypedDict
from unittest.mock import MagicMock

from msgspec import Struct
from pydantic import BaseModel, computed_field

from holarchy import F, StepScope


class DummyContext:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


# --- 1. Cascade Priority Tests (O(1)) ---


class TestStepScopeCascadePriority:
    def test_current_data_takes_priority_over_input_and_context(self) -> None:
        ctx = DummyContext(
            status="ctx_status",
            input={"status": "input_status"},
        )
        scope = StepScope(context=ctx, current_data={"status": "current_status"})

        assert scope.status == "current_status"
        assert scope["status"] == "current_status"
        assert (F.status == "current_status").resolve(scope) is True
        assert (F["status"] == "current_status").resolve(scope) is True

    def test_input_takes_priority_over_context(self) -> None:
        ctx = DummyContext(
            tier="ctx_tier",
            input={"tier": "input_tier"},
        )
        scope = StepScope(context=ctx, current_data={})

        assert scope.tier == "input_tier"
        assert scope["tier"] == "input_tier"
        assert (F.tier == "input_tier").resolve(scope) is True
        assert (F["tier"] == "input_tier").resolve(scope) is True

    def test_context_fallback_when_not_in_current_or_input(self) -> None:
        ctx = DummyContext(
            job_id="job-uuid-1234",
            current_state="processing",
            input={"payload_field": "val"},
        )
        scope = StepScope(context=ctx, current_data={"step_res": 99})

        assert scope.job_id == "job-uuid-1234"
        assert scope["job_id"] == "job-uuid-1234"
        assert scope.current_state == "processing"
        assert (F.job_id == "job-uuid-1234").resolve(scope) is True
        assert (F["job_id"] == "job-uuid-1234").resolve(scope) is True

    def test_explicit_prefixes_bypass_current_data(self) -> None:
        ctx = DummyContext(
            input={"status": "original_status", "user_id": 42},
            steps={
                "fetch_step": {"items_count": 10},
                "calc_step": {"result": 100},
            },
            meta={"headers": {"x-request-id": "req-999"}},
        )
        scope = StepScope(context=ctx, current_data={"status": "updated_status"})

        # Implicit resolution picks current_data
        assert (F.status == "updated_status").resolve(scope) is True

        # Explicit prefix F.input for dictionary input
        assert (F.input["status"] == "original_status").resolve(scope) is True
        assert (F.input["user_id"] == 42).resolve(scope) is True

        # Explicit prefix F.input for model/object input
        ctx_obj = DummyContext(
            input=CustomerRecord(cust_id=77, name="Agent", vip=False),
        )
        scope_obj = StepScope(context=ctx_obj, current_data={"name": "Overridden"})
        assert (F.name == "Overridden").resolve(scope_obj) is True
        assert (F.input.name == "Agent").resolve(scope_obj) is True
        assert (F.input.cust_id == 77).resolve(scope_obj) is True

        # Explicit prefix F.steps / F.step(name)
        assert (F.steps["fetch_step"]["items_count"] == 10).resolve(scope) is True
        assert (F.steps["calc_step"]["result"] == 100).resolve(scope) is True
        assert (F.step("fetch_step")["items_count"] == 10).resolve(scope) is True

        # Explicit prefix F.headers
        assert (F.headers["x-request-id"] == "req-999").resolve(scope) is True

    def test_missing_keys_return_none_safely(self) -> None:
        ctx = DummyContext(input={"a": 1})
        scope = StepScope(context=ctx)

        assert scope.non_existent is None
        assert (F.non_existent == None).resolve(scope) is True  # noqa: E711
        assert (F.non_existent > 10).resolve(scope) is False


# --- 2. Data Structure Compatibility Matrix ---


class OrderModel(BaseModel):
    order_id: str
    amount: float
    items: list[str]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_large(self) -> bool:
        return self.amount > 1000.0


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    cust_id: int
    name: str
    vip: bool


class DeviceStruct(Struct):
    device_id: str
    battery: int
    online: bool


class UserTypedDict(TypedDict):
    username: str
    score: int


class TestStepScopeModelMatrix:
    def test_pydantic_v2_as_current_data_and_input(self) -> None:
        order = OrderModel(order_id="ord-1", amount=1500.0, items=["laptop", "mouse"])

        # As input
        scope1 = StepScope(DummyContext(input=order))
        assert (F.order_id == "ord-1").resolve(scope1) is True
        assert (F.amount == 1500.0).resolve(scope1) is True
        assert (F.is_large == True).resolve(scope1) is True  # noqa: E712

        # As current_data
        scope2 = StepScope(DummyContext(input={}), current_data=order)
        assert (F.order_id == "ord-1").resolve(scope2) is True
        assert (F.is_large == True).resolve(scope2) is True  # noqa: E712

    def test_dataclass_slots_and_frozen(self) -> None:
        cust = CustomerRecord(cust_id=101, name="Dmitry", vip=True)

        scope = StepScope(DummyContext(input=cust))
        assert (F.cust_id == 101).resolve(scope) is True
        assert (F.name == "Dmitry").resolve(scope) is True
        assert (F.vip == True).resolve(scope) is True  # noqa: E712

    def test_msgspec_struct(self) -> None:
        dev = DeviceStruct(device_id="sensor-01", battery=88, online=True)

        scope = StepScope(DummyContext(input={}), current_data=dev)
        assert (F.device_id == "sensor-01").resolve(scope) is True
        assert (F.battery > 50).resolve(scope) is True
        assert (F.online == True).resolve(scope) is True  # noqa: E712

    def test_typed_dict(self) -> None:
        user_td: UserTypedDict = {"username": "alice", "score": 95}
        scope = StepScope(user_td)

        assert (F.username == "alice").resolve(scope) is True
        assert (F.score >= 90).resolve(scope) is True

    def test_magic_mock_compatibility(self) -> None:
        # StepScope explicitly inspects type(context).__name__.endswith("Mock")
        mock_ctx = MagicMock()
        mock_ctx.input = {"role": "moderator"}
        mock_ctx.steps = {"step_a": {"ok": True}}
        mock_ctx.current_state = "pending"

        scope = StepScope(mock_ctx)
        assert (F.role == "moderator").resolve(scope) is True
        assert (F.steps["step_a"]["ok"] == True).resolve(scope) is True  # noqa: E712


# --- 3. Step History and Nested Access Boundaries ---


class TestStepHistoryAndBoundaryCases:
    def test_step_helper_method_variations(self) -> None:
        ctx = DummyContext(
            steps={
                "alpha": {"data": 123},
                "beta": {"data": 456},
            }
        )
        scope = StepScope(ctx)

        # Access via scope.step(name)
        assert scope.step("alpha") == {"data": 123}
        assert scope.step("beta") == {"data": 456}
        assert scope.step("nonexistent") is None

        # Filter resolution
        assert (F.step("alpha")["data"] == 123).resolve(scope) is True
        assert (F.step("nonexistent") == None).resolve(scope) is True  # noqa: E711

    def test_headers_edge_cases(self) -> None:
        # Context without meta
        scope_no_meta = StepScope(DummyContext())
        assert scope_no_meta.headers == {}
        assert (F.headers["any"] == None).resolve(scope_no_meta) is True  # noqa: E711
        assert (F.headers["any"] != None).resolve(scope_no_meta) is False  # noqa: E711

        # Context with non-dict meta
        scope_invalid_meta = StepScope(DummyContext(meta="not_a_dict"))
        assert scope_invalid_meta.headers == {}

        # Context with headers dict
        scope_valid = StepScope(DummyContext(meta={"headers": {"auth": "Bearer tok"}}))
        assert (F.headers["auth"] == "Bearer tok").resolve(scope_valid) is True

    def test_special_characters_in_keys_via_getitem(self) -> None:
        ctx = {"content-type": "application/json", "x.custom.key": "value-1"}
        scope = StepScope(ctx)

        assert scope["content-type"] == "application/json"
        assert scope["x.custom.key"] == "value-1"
        assert (F["content-type"] == "application/json").resolve(scope) is True
        assert (F["x.custom.key"] == "value-1").resolve(scope) is True
