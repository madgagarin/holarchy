# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, Field
from rxon.schema import extract_skill_contract

from holarchy.blueprint import Blueprint
from holarchy.executor import JobExecutor
from holarchy.fsm import Next, State, StatesGroup


class OrderFlow(StatesGroup):
    start = State()
    calc = State()
    done = State()


class OrderInput(BaseModel):
    item: str
    price: float = Field(gt=0)
    quantity: int = Field(default=1, ge=1)


class OrderReceipt(BaseModel):
    item: str
    total: float
    confirmed: bool


@pytest.fixture
def stage1_executor():
    engine = MagicMock()
    history = AsyncMock()
    storage = AsyncMock()
    engine.storage = storage
    engine.history_storage = history
    engine.blueprints = {}
    engine.blueprint_contracts = {}
    engine.config.JOB_MAX_RETRIES = 3
    engine.config.S3_AUTO_CLEANUP = False
    engine.app = {}
    engine.worker_service = None
    engine.on_job_finished = []
    engine.send_job_webhook = AsyncMock()
    metrics = MagicMock()
    executor = JobExecutor(engine, history, metrics=metrics)
    executor.dispatcher = AsyncMock()
    return executor


@pytest.mark.asyncio
async def test_stage1_full_lifecycle_e2e(stage1_executor):
    """
    End-to-End verification of Stage 1 DX/UX modernization:
    1. StatesGroup declaration
    2. Input schema extracted from Pydantic model in handler signature
    3. Input model injected into handler
    4. Next() with step data returned
    5. Step return captured in 5 clean zones
    6. Output schema extracted from return type hint and validated
    7. All 5 zones populated with complete audit trail
    """
    bp = Blueprint(name="stage1_order_bp")

    @bp.start(OrderFlow.start)
    async def process_order(order: OrderInput):
        assert isinstance(order, OrderInput)
        assert order.item == "laptop"
        subtotal = order.price * order.quantity
        return Next(OrderFlow.calc, data={"subtotal": subtotal, "item": order.item})

    @bp.step(OrderFlow.calc)
    async def calculate_tax(subtotal: float, item: str):
        tax = subtotal * 0.2
        return Next(OrderFlow.done, data={"item": item, "total": subtotal + tax, "confirmed": True})

    @bp.end(OrderFlow.done)
    async def finalize_order(total: float, item: str, confirmed: bool) -> OrderReceipt:
        return OrderReceipt(item=item, total=total, confirmed=confirmed)

    bp.validate()
    stage1_executor.engine.blueprints["stage1_order_bp"] = bp

    # Contract extraction
    contract = extract_skill_contract(bp)
    stage1_executor.engine.blueprint_contracts["stage1_order_bp"] = contract

    assert contract["input_schema"] is not None
    assert "item" in contract["input_schema"]["properties"]
    assert contract["output_schema"] is not None
    assert "total" in contract["output_schema"]["properties"]

    job_id = "job-stage1-e2e"
    job_state = {
        "id": job_id,
        "blueprint_name": "stage1_order_bp",
        "current_state": str(OrderFlow.start),
        "status": "running",
        "input": {"item": "laptop", "price": 1000.0, "quantity": 2},
        "steps": {},
        "history": [],
        "output": None,
        "params": {"discount": 0.0},
        "meta": {"priority": "high"},
        "initial_data": {"item": "laptop", "price": 1000.0, "quantity": 2},
        "state_history": {},
    }
    stage1_executor.storage.get_job_state.return_value = job_state
    stage1_executor.storage.ack_job = AsyncMock()

    # Step 1: Execute start handler
    await stage1_executor._process_job(job_id, "msg-step-1")
    assert job_state["current_state"] == str(OrderFlow.calc)
    assert job_state["steps"][str(OrderFlow.start)] == {"subtotal": 2000.0, "item": "laptop"}
    assert len(job_state["history"]) == 1
    assert job_state["history"][0]["from_state"] == str(OrderFlow.start)
    assert job_state["history"][0]["to_state"] == str(OrderFlow.calc)

    # Step 2: Execute calc handler
    await stage1_executor._process_job(job_id, "msg-step-2")
    assert job_state["current_state"] == str(OrderFlow.done)
    assert job_state["steps"][str(OrderFlow.calc)] == {"item": "laptop", "total": 2400.0, "confirmed": True}
    assert len(job_state["history"]) == 2

    # Step 3: Execute finalize_order end handler
    await stage1_executor._process_job(job_id, "msg-step-3")
    assert job_state["status"] == "finished"
    expected_output = {"item": "laptop", "total": 2400.0, "confirmed": True}
    assert job_state["output"] == expected_output
    assert job_state["result"] == expected_output
    assert len(job_state["history"]) == 3
    assert job_state["history"][2]["status"] == "finished"

    # Backward compatibility checks
    assert job_state["initial_data"] == job_state["input"]
    assert job_state["state_history"] == job_state["steps"]
