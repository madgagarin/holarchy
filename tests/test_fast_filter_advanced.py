# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import create_task, gather
from copy import copy, deepcopy
from dataclasses import dataclass
from pickle import dumps, loads
from typing import Any, cast

from fast_filter import create_typed_f, extract_all
from msgspec import Struct
from pydantic import BaseModel, Field
from pytest import mark, raises

from holarchy import F, FastF, StepScope
from holarchy.blueprint import Blueprint


class Obj:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


# --- 1. Bitwise and Binary Operators ---


class TestLogicalAndArithmeticOperators:
    def test_logical_and(self) -> None:
        filt = (F.flags > 0) & (F.tag == "prod")
        assert filt.resolve(Obj(flags=2, tag="prod")) is True
        assert filt.resolve(Obj(flags=2, tag="dev")) is False
        assert filt.resolve(Obj(flags=0, tag="prod")) is False

    def test_logical_or(self) -> None:
        filt = (F.role == "admin") | (F.role == "root")
        assert filt.resolve(Obj(role="admin")) is True
        assert filt.resolve(Obj(role="root")) is True
        assert filt.resolve(Obj(role="guest")) is False

    def test_bitwise_xor(self) -> None:
        filt = (F.mask ^ 0b1111) == 0b0000
        assert filt.resolve(Obj(mask=0b1111)) is True
        assert filt.resolve(Obj(mask=0b1110)) is False

    def test_bitwise_invert(self) -> None:
        filt = ~F.flag
        assert filt.resolve(Obj(flag=True)) is False
        assert filt.resolve(Obj(flag=False)) is True

    def test_bitwise_shifts(self) -> None:
        f_left = (F.val << 2) == 16
        f_right = (F.val >> 1) == 4
        assert f_left.resolve(Obj(val=4)) is True
        assert f_right.resolve(Obj(val=8)) is True

    def test_arithmetic_precedence_and_operations(self) -> None:
        # (a + b) * c == 100
        filt = ((F.a + F.b) * F.c) == 100
        assert filt.resolve(Obj(a=10, b=15, c=4)) is True
        assert filt.resolve(Obj(a=10, b=10, c=4)) is False

        # Modulo and power
        f_mod = (F.val % 2) == 0
        f_pow = (F.base**3) == 27
        assert f_mod.resolve(Obj(val=10)) is True
        assert f_mod.resolve(Obj(val=11)) is False
        assert f_pow.resolve(Obj(base=3)) is True

    def test_unary_operators(self) -> None:
        f_neg = -F.delta < 0
        f_pos = +F.score > 0
        f_abs = abs(F.diff) == 5

        assert f_neg.resolve(Obj(delta=10)) is True
        assert f_neg.resolve(Obj(delta=-5)) is False
        assert f_pos.resolve(Obj(score=1)) is True
        assert f_abs.resolve(Obj(diff=-5)) is True
        assert f_abs.resolve(Obj(diff=5)) is True


# --- 2. Collections, Slices, Quantifiers, and Strings ---


class TestCollectionsAndQuantifiers:
    def test_slice_projection_and_all(self) -> None:
        data = {
            "users": [
                {"name": "Alice", "age": 25, "active": True},
                {"name": "Bob", "age": 30, "active": True},
            ]
        }
        scope = StepScope(data)

        f_all_adults = (F.users[...]["age"] >= 18).all()
        f_all_active = (F.users[...]["active"] == True).all()  # noqa: E712
        f_all_over_30 = (F.users[...]["age"] > 30).all()

        assert f_all_adults.resolve(scope) is True
        assert f_all_active.resolve(scope) is True
        assert f_all_over_30.resolve(scope) is False

    def test_slice_projection_and_any(self) -> None:
        data = {
            "orders": [
                {"id": 1, "price": 50, "priority": "low"},
                {"id": 2, "price": 1500, "priority": "critical"},
            ]
        }
        scope = StepScope(data)

        f_any_high_value = (F.orders[...]["price"] > 1000).any()
        f_any_urgent = (F.orders[...]["priority"] == "critical").any()
        f_any_refunded = (F.orders[...]["priority"] == "refunded").any()

        assert f_any_high_value.resolve(scope) is True
        assert f_any_urgent.resolve(scope) is True
        assert f_any_refunded.resolve(scope) is False

    def test_len_operator(self) -> None:
        scope = StepScope({"items": [1, 2, 3, 4], "empty_list": [], "text": "hello"})

        assert (F.items.len() == 4).resolve(scope) is True
        assert (F.empty_list.len() == 0).resolve(scope) is True
        assert (F.text.len() == 5).resolve(scope) is True
        assert (F.items.len() > 2).resolve(scope) is True

    def test_membership_and_identity(self) -> None:
        scope = StepScope({"role": "admin", "tags": ["prod", "us-east"], "token": None})

        assert F.role.in_(["admin", "superuser"]).resolve(scope) is True
        assert F.role.not_in(["guest", "anonymous"]).resolve(scope) is True
        assert F.tags.contains("prod").resolve(scope) is True
        assert F.tags.contains("staging").resolve(scope) is False

        assert F.token.is_(None).resolve(scope) is True
        assert F.role.is_not(None).resolve(scope) is True

    def test_regex_matching(self) -> None:
        scope = StepScope(
            {
                "email": "user.name+tag@example.com",
                "semver": "v2.14.3-alpha",
                "non_match": "not-an-email",
                "null_val": None,
            }
        )

        f_email = F.email.regexp(r"^[\w.+]+@example\.com$")
        f_semver = F.semver.regexp(r"^v\d+\.\d+\.\d+(-[a-z]+)?$")
        f_nomatch = F.non_match.regexp(r"^[\w.+]+@example\.com$")
        f_null = F.null_val.regexp(r"^.*$")

        assert f_email.resolve(scope) is True
        assert f_semver.resolve(scope) is True
        assert f_nomatch.resolve(scope) is False
        assert f_null.resolve(scope) is None
        assert bool(f_null.resolve(scope)) is False

    def test_cast_and_func(self) -> None:
        scope = StepScope({"str_num": "42", "raw_score": 87.65})

        f_cast = F.str_num.cast(int) == 42
        f_func = F.raw_score.func(lambda s: int(s) == 87)

        assert f_cast.resolve(scope) is True
        assert f_func.resolve(scope) is True


# --- 3. TypedF, Dataclasses, Pydantic, Msgspec Models ---


class UserModel(BaseModel):
    name: str
    age: int
    is_vip: bool = Field(default=False)
    roles: list[str] = Field(default_factory=list)


@dataclass
class JobRecord:
    job_id: str
    priority: int
    status: str


class MetricsStruct(Struct):
    cpu: float
    memory: float
    active: bool


class TestTypedFAndModels:
    def test_typed_f_with_pydantic_v2(self) -> None:
        UserF = create_typed_f(UserModel)
        f_adult_vip = cast(FastF, (UserF.age >= 18) & (UserF.is_vip == True))  # noqa: E712

        vip_user = UserModel(name="Alice", age=25, is_vip=True, roles=["admin"])
        regular_user = UserModel(name="Bob", age=16, is_vip=False)

        assert f_adult_vip.resolve(vip_user) is True
        assert f_adult_vip.resolve(regular_user) is False

        # In StepScope
        scope = StepScope(vip_user)
        assert f_adult_vip.resolve(scope) is True

    def test_typed_f_with_dataclass(self) -> None:
        JobF = create_typed_f(JobRecord)
        f_high_prio = cast(FastF, (JobF.priority >= 10) & (JobF.status == "queued"))

        rec1 = JobRecord(job_id="j1", priority=15, status="queued")
        rec2 = JobRecord(job_id="j2", priority=5, status="queued")

        assert f_high_prio.resolve(rec1) is True
        assert f_high_prio.resolve(rec2) is False

        scope = StepScope(rec1)
        assert f_high_prio.resolve(scope) is True

    def test_typed_f_with_msgspec_struct(self) -> None:
        MetricF = create_typed_f(MetricsStruct)
        f_overload = cast(FastF, (MetricF.cpu > 80.0) & (MetricF.active == True))  # noqa: E712

        m1 = MetricsStruct(cpu=92.5, memory=40.0, active=True)
        m2 = MetricsStruct(cpu=45.0, memory=90.0, active=True)

        assert f_overload.resolve(m1) is True
        assert f_overload.resolve(m2) is False

        scope = StepScope(m1)
        assert f_overload.resolve(scope) is True


# --- 4. Variable Capture and Extraction ---


class TestCaptureAndExtraction:
    def test_as_and_extract_dict(self) -> None:
        data = {"user": {"name": "Alice", "score": 99}, "status": "approved"}
        filt = (F.user["score"] >= 90) & F.user["name"].as_("matched_user")

        scope = StepScope(data)
        captured = filt.extract(scope)
        assert captured.get("matched_user") == "Alice"

    def test_as_and_extract_model(self) -> None:
        user = UserModel(name="Bob", age=30, is_vip=True)
        filt = (F.user.age >= 18) & F.user.name.as_("adult_name")

        scope = StepScope({"user": user})
        captured = filt.extract(scope)
        assert captured.get("adult_name") == "Bob"

    def test_as_and_extract_objects(self) -> None:
        class Task:
            name = "deploy_prod"
            owner = "admin"
            status = "ready"

        filt = (F.status == "ready") & F.owner.as_("task_owner") & F.name.as_("task_name")
        captured = filt.extract(Task())
        assert captured == {"task_owner": "admin", "task_name": "deploy_prod"}

    def test_extract_all_helper(self) -> None:
        scope = StepScope({"service": "payment", "cluster": "eu-central", "port": 8080})
        spec = {
            "svc": F.service,
            "region": F.cluster,
            "is_secure": F.port == 443,
        }
        res = extract_all(spec, scope)
        assert res == {"svc": "payment", "region": "eu-central", "is_secure": False}


# --- 5. Exception Resilience and Boundary Edge Cases ---


class ExplodingProperty:
    @property
    def kaboom(self) -> None:
        raise RuntimeError("Explosion inside property!")


class TestExceptionResilience:
    def test_division_by_zero_fails_safely(self) -> None:
        # F.num / F.denom == 1 when denom is 0 should return False without crashing
        f_div = (F.num / F.denom) == 1
        assert f_div.resolve(Obj(num=10, denom=0)) is False

    def test_type_mismatch_comparisons(self) -> None:
        # Comparing string with int
        f_gt = F.val > 10
        assert f_gt.resolve(Obj(val="not_a_number")) is False
        assert f_gt.resolve(Obj(val=None)) is False

    def test_exploding_property_in_scope(self) -> None:
        bp = Blueprint("test_resilience")

        @bp.handler("check", F.target.kaboom == "safe")
        def h1() -> str:
            return "safe"

        @bp.handler("check")
        def h_default() -> str:
            return "fallback"

        # find_handler should catch the error and route to default handler
        chosen = bp.find_handler("check", Obj(target=ExplodingProperty()))
        assert chosen is h_default

    def test_deeply_nested_missing_attributes(self) -> None:
        filt = F.a.b.c.d.e.f.g.h == 42
        assert filt.resolve(Obj()) is False
        assert filt.resolve(Obj(a={"b": None})) is False
        assert filt.resolve(None) is False

    def test_unhashable_items_in_membership(self) -> None:
        filt = F.dict_item.in_([{"a": 1}, {"b": 2}])
        assert filt.resolve(Obj(dict_item={"a": 1})) is True
        assert filt.resolve(Obj(dict_item={"c": 3})) is False


# --- 6. Concurrency and Asyncio Safety ---


class TestConcurrencyAndAsyncio:
    @mark.asyncio
    async def test_shared_filter_evaluated_across_500_concurrent_tasks(self) -> None:
        shared_filter = (F.score >= 50) & (F.tag.in_(["prod", "release"]))

        async def worker_task(i: int) -> bool:
            # Alternate match and mismatch
            score = 75 if i % 2 == 0 else 25
            tag = "prod" if i % 3 == 0 else "dev"
            obj = Obj(score=score, tag=tag)
            # resolve asynchronously
            return bool(shared_filter.resolve(obj))

        tasks = [create_task(worker_task(i)) for i in range(500)]
        results = await gather(*tasks)

        for i, res in enumerate(results):
            expected = (75 if i % 2 == 0 else 25) >= 50 and ("prod" if i % 3 == 0 else "dev") in ["prod", "release"]
            assert res == expected


# --- 7. Reflected Operators and Inter-Filter Expressions ---


class TestReflectedAndBinaryFilters:
    def test_reflected_operators(self) -> None:
        scope = StepScope({"price": 20, "power": 3, "shift": 2, "mult": 10, "mask": 0b1111})

        f_rsub = (100 - F.price) == 80
        f_rpow = (2**F.power) == 8
        f_rlshift = (1 << F.shift) == 4
        f_rmul = (5 * F.mult) == 50
        f_rxor = (0b1111 ^ F.mask) == 0

        assert f_rsub.resolve(scope) is True
        assert f_rpow.resolve(scope) is True
        assert f_rlshift.resolve(scope) is True
        assert f_rmul.resolve(scope) is True
        assert f_rxor.resolve(scope) is True

    def test_both_sides_fastf_expressions(self) -> None:
        scope = StepScope({"price": 25, "quantity": 4, "budget": 90, "first": "John", "last": "Doe"})

        f_arith = (F.price * F.quantity) > F.budget
        f_concat = (F.first + " " + F.last) == "John Doe"

        assert f_arith.resolve(scope) is True
        assert f_concat.resolve(scope) is True


# --- 8. attr_, Method Calling, not_, Multidimensional Slicing ---


class ServiceMock:
    def greet(self, prefix: str = "Hello", count: int = 1) -> str:
        return f"{prefix * count}!"


class TestSpecialMethodsAndChaining:
    def test_attr_access_reserved_and_dynamic_names(self) -> None:
        # attr_ allows accessing properties named after FastF methods or Python keywords
        data = {"resolve": "custom_endpoint", "items": 42, "class": "premium"}
        scope = StepScope(data)

        f_res = F.attr_("resolve") == "custom_endpoint"
        f_items = F.attr_("items") == 42
        f_class = F.attr_("class") == "premium"

        assert f_res.resolve(scope) is True
        assert f_items.resolve(scope) is True
        assert f_class.resolve(scope) is True

    def test_not_method_alternative(self) -> None:
        scope = StepScope({"flag": False, "score": 10})

        f_not_flag = F.flag.not_()
        f_not_score = (F.score > 20).not_()

        assert f_not_flag.resolve(scope) is True
        assert f_not_score.resolve(scope) is True

    def test_method_calls_with_args_and_kwargs(self) -> None:
        scope = StepScope({"service": ServiceMock()})

        f_method = F.service.greet("Hi", count=2) == "HiHi!"
        assert f_method.resolve(scope) is True

    def test_multidimensional_slicing(self) -> None:
        data = {
            "matrix": [
                [10, 20],
                [30, 40],
            ]
        }
        scope = StepScope(data)

        f_gt_zero = F.matrix[...][...] > 0
        f_eq_40 = F.matrix[...][...] == 40
        f_eq_100 = F.matrix[...][...] == 100

        # Multi-dimensional slicing produces nested mapped boolean matrices
        assert f_gt_zero.resolve(scope) == [[True, True], [True, True]]
        assert f_eq_40.resolve(scope) == [[False, False], [False, True]]
        assert f_eq_100.resolve(scope) == [[False, False], [False, False]]


# --- 9. Serialization, Copy, Protocols and Security ---


class TestSerializationAndPythonProtocols:
    def test_pickle_roundtrip(self) -> None:
        filt = (F.price * F.quantity > 50) & (F.tag == "promo")
        data = StepScope({"price": 10, "quantity": 10, "tag": "promo"})

        pickled = dumps(filt)
        unpickled: FastF = loads(pickled)

        assert unpickled.resolve(data) is True

    def test_copy_and_deepcopy(self) -> None:
        filt = (F.score >= 100) | (F.role == "admin")
        data = StepScope({"score": 50, "role": "admin"})

        shallow = copy(filt)
        deep = deepcopy(filt)

        assert shallow.resolve(data) is True
        assert deep.resolve(data) is True

    def test_hash_and_expression_equivalence(self) -> None:
        f1 = F.status == "ok"
        f2 = F.status == "ok"
        f3 = F.status == "err"

        # FastF defines __hash__ based on (expr, repr)
        assert hash(f1) == hash(f2)
        assert hash(f1) != hash(f3)
        assert f1._expr == f2._expr
        assert f1._expr != f3._expr

    def test_bool_operator_raises_informative_typeerror(self) -> None:
        filt = F.score > 0
        with raises(TypeError, match="Use & or \\| instead of and/or"):
            if filt:
                pass

    def test_invalid_attribute_and_keyword_name_security(self) -> None:
        with raises(ValueError, match="Invalid attribute name"):
            getattr(F, "invalid-attr;rm -rf")

        with raises(ValueError, match="Invalid keyword argument name"):
            F.method(**{"invalid-kwarg;": 1})
