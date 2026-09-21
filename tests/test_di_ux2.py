# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

import pytest
from pydantic import BaseModel

from holarchy import Blueprint, Context, Header, JobContext
from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage


class PaymentResult(BaseModel):
    transaction_id: str
    amount: float
    status: str


class ShippingResult(BaseModel):
    tracking_number: str
    carrier: str


@pytest.fixture
def engine():
    storage = MemoryStorage()
    config = Config()
    return OrchestratorEngine(storage, config)


@pytest.mark.asyncio
async def test_header_injection_primitives_and_defaults(engine):
    bp = Blueprint("header_test_bp")

    captured = {}

    @bp.handler("start", is_start=True, is_end=True)
    async def start(
        corr_id: Annotated[str | None, Header("X-Correlation-ID")] = None,
        job_timeout: Annotated[int, Header("X-Job-Timeout")] = 30,
        rate: Annotated[float, Header("X-Exchange-Rate")] = 1.0,
        debug_mode: Annotated[bool, Header("X-Debug-Mode")] = False,
        missing_header: Annotated[str, Header("X-Missing", default="default_val")] = "sig_default",
    ):
        captured["corr_id"] = corr_id
        captured["job_timeout"] = job_timeout
        captured["rate"] = rate
        captured["debug_mode"] = debug_mode
        captured["missing_header"] = missing_header

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    # 1. Provide all headers with exact or mixed case
    job_id = await engine.create_background_job(
        "header_test_bp",
        {},
        tracing_context={
            "x-correlation-id": "cid-98765",
            "X-Job-Timeout": "60",
            "x-exchange-rate": "1.25",
            "X-Debug-Mode": "true",
        },
    )

    await engine.executor._process_job(job_id, str(uuid4()))

    assert captured["corr_id"] == "cid-98765"
    assert captured["job_timeout"] == 60
    assert captured["rate"] == 1.25
    assert captured["debug_mode"] is True
    assert captured["missing_header"] == "default_val"

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_context_and_ctx_aliases(engine):
    bp = Blueprint("context_test_bp")

    captured = {}

    @bp.handler("start", is_start=True)
    async def step1(ctx: Context, actions):
        assert isinstance(ctx, JobContext)
        captured["step1_job_id"] = ctx.job_id
        actions.go_to("step2")

    @bp.handler("step2", is_end=True)
    async def step2(context: JobContext, my_ctx: Context):
        assert isinstance(context, JobContext)
        assert isinstance(my_ctx, JobContext)
        captured["step2_job_id"] = context.job_id
        captured["my_ctx_job_id"] = my_ctx.job_id

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job("context_test_bp", {"init": 1})
    await engine.executor._process_job(job_id, str(uuid4()))
    await engine.executor._process_job(job_id, str(uuid4()))

    assert captured["step1_job_id"] == job_id
    assert captured["step2_job_id"] == job_id
    assert captured["my_ctx_job_id"] == job_id

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_blackboard_type_matching_from_steps(engine):
    bp = Blueprint("type_matching_bp")

    captured = {}

    @bp.handler("process_payment", is_start=True)
    async def process_payment(actions):
        # Step 1 returns dict matching PaymentResult
        actions.save_result({"transaction_id": "tx_42", "amount": 199.99, "status": "approved"})
        actions.go_to("ship_order")

    @bp.handler("ship_order")
    async def ship_order(
        payment: PaymentResult,  # Name is 'payment', step name was 'process_payment' -> matched by type!
        actions,
    ):
        assert isinstance(payment, PaymentResult)
        captured["payment_tx"] = payment.transaction_id
        captured["payment_amount"] = payment.amount
        actions.save_result({"tracking_number": "TRACK_777", "carrier": "DHL"})
        actions.go_to("finalize")

    @bp.handler("finalize", is_end=True)
    async def finalize(
        shipping: ShippingResult,  # Name 'shipping', step 'ship_order' -> matched by type!
        process_payment: PaymentResult,  # Name matches step name 'process_payment' -> matched by name & coerced!
    ):
        assert isinstance(shipping, ShippingResult)
        assert isinstance(process_payment, PaymentResult)
        captured["shipping_track"] = shipping.tracking_number
        captured["final_tx"] = process_payment.transaction_id

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job("type_matching_bp", {})
    await engine.executor._process_job(job_id, str(uuid4()))  # process_payment
    await engine.executor._process_job(job_id, str(uuid4()))  # ship_order
    await engine.executor._process_job(job_id, str(uuid4()))  # finalize

    assert captured["payment_tx"] == "tx_42"
    assert captured["payment_amount"] == 199.99
    assert captured["shipping_track"] == "TRACK_777"
    assert captured["final_tx"] == "tx_42"

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_header_injection_edge_cases(engine):
    bp = Blueprint("header_edge_cases_bp")
    captured = {}

    @bp.handler("step", is_start=True, is_end=True)
    async def step(
        invalid_int: Annotated[int, Header("X-Bad-Int")] = 999,
        bool_str: Annotated[bool, Header("X-Bool-Str")] = False,
        optional_missing: Annotated[str | None, Header("X-Opt-Missing")] = None,
    ):
        captured["invalid_int"] = invalid_int
        captured["bool_str"] = bool_str
        captured["optional_missing"] = optional_missing

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    # X-Bad-Int is not a number -> fallback to default 999
    # X-Bool-Str is "0" -> cast to False
    job_id = await engine.create_background_job(
        "header_edge_cases_bp",
        {},
        tracing_context={"X-Bad-Int": "not-a-number", "X-Bool-Str": "0"},
    )
    await engine.executor._process_job(job_id, str(uuid4()))

    assert captured["invalid_int"] == 999
    assert captured["bool_str"] is False
    assert captured["optional_missing"] is None

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_header_injection_missing_required_no_default(engine):
    bp = Blueprint("missing_req_bp")
    captured = {}

    @bp.handler("step", is_start=True, is_end=True)
    async def step(
        required_auth: Annotated[str, Header("X-Required-Auth")],
    ):
        captured["required_auth"] = required_auth

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job("missing_req_bp", {}, tracing_context={})
    await engine.executor._process_job(job_id, str(uuid4()))

    # When header is missing and no default is provided, it safely injects None
    assert captured["required_auth"] is None

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_header_boolean_variants_and_delimiters(engine):
    bp = Blueprint("bool_variants_bp")
    captured = {}

    @bp.handler("step", is_start=True, is_end=True)
    async def step(
        b_true1: Annotated[bool, Header("x-flag-true1")],
        b_true2: Annotated[bool, Header("x-flag-true2")],
        b_false1: Annotated[bool, Header("x-flag-false1")],
        b_false2: Annotated[bool, Header("x-flag-false2")],
        delim_test: Annotated[str, Header("my-custom-header")],
    ):
        captured["b_true1"] = b_true1
        captured["b_true2"] = b_true2
        captured["b_false1"] = b_false1
        captured["b_false2"] = b_false2
        captured["delim_test"] = delim_test

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job(
        "bool_variants_bp",
        {},
        tracing_context={
            "X-FLAG-TRUE1": "yes",
            "x_flag_true2": "1",
            "X_FLAG_FALSE1": "off",
            "X-Flag-False2": "no",
            "MY_CUSTOM_HEADER": "found-by-underscore",
        },
    )
    await engine.executor._process_job(job_id, str(uuid4()))

    assert captured["b_true1"] is True
    assert captured["b_true2"] is True
    assert captured["b_false1"] is False
    assert captured["b_false2"] is False
    assert captured["delim_test"] == "found-by-underscore"

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_blackboard_incompatible_model_negative(engine):
    bp = Blueprint("incompatible_model_bp")
    captured = {}

    @bp.handler("step1", is_start=True)
    async def step1(actions):
        # Step returns dict that lacks required fields for PaymentResult
        actions.save_result({"random_field": "unrelated"})
        actions.go_to("step2")

    @bp.handler("step2", is_end=True)
    async def step2(
        payment: PaymentResult | None = None,
    ):
        captured["payment"] = payment

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job("incompatible_model_bp", {})
    await engine.executor._process_job(job_id, str(uuid4()))
    await engine.executor._process_job(job_id, str(uuid4()))

    # Incompatible dict does not coerce to PaymentResult, parameter falls back to default None
    assert captured["payment"] is None

    await engine.on_shutdown(engine.app)


@pytest.mark.asyncio
async def test_blackboard_dataclass_injection(engine):
    @dataclass
    class InventoryItem:
        sku: str
        quantity: int

    bp = Blueprint("dataclass_di_bp")
    captured = {}

    @bp.handler("step1", is_start=True)
    async def step1(actions):
        actions.save_result({"sku": "WIDGET-01", "quantity": 15})
        actions.go_to("step2")

    @bp.handler("step2", is_end=True)
    async def step2(item: InventoryItem):
        captured["item"] = item

    engine.register_blueprint(bp)
    await engine.on_startup(engine.app)

    job_id = await engine.create_background_job("dataclass_di_bp", {})
    await engine.executor._process_job(job_id, str(uuid4()))
    await engine.executor._process_job(job_id, str(uuid4()))

    assert isinstance(captured["item"], InventoryItem)
    assert captured["item"].sku == "WIDGET-01"
    assert captured["item"].quantity == 15

    await engine.on_shutdown(engine.app)

