# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from msgspec import Struct
from pytest import fixture, mark

from holarchy.blueprint import Blueprint
from holarchy.context import ActionFactory
from holarchy.data_types import JobContext
from holarchy.executor import JobExecutor
from holarchy.fsm import Next, State, StatesGroup
from holarchy.skill import Skill


class TestFlow(StatesGroup):
    start = State()
    calc = State()
    done = State()
    rejected = State()


@dataclass
class ReceiptModel:
    receipt_id: str
    total: float


@dataclass
class OutputModel:
    result_code: int


@fixture
def test_executor():
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


@mark.asyncio
async def test_intermediate_step_return_saved_to_steps(test_executor):
    bp = Blueprint(name="ux_step_return_bp")

    @bp.start(TestFlow.start)
    async def handle_start(actions: ActionFactory):
        actions.go_to(str(TestFlow.calc))
        return {"amount": 100}

    @bp.end(TestFlow.calc)
    async def handle_calc(amount: int):
        return {"total": amount * 2}

    bp.validate()
    test_executor.engine.blueprints["ux_step_return_bp"] = bp

    job_id = "job-ux-01"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_step_return_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-1")

    # Step 1 should have saved its return value to steps
    assert job_state["steps"][str(TestFlow.start)] == {"amount": 100}
    assert "state_history" not in job_state
    assert job_state["current_state"] == str(TestFlow.calc)

    # Now execute step 2 (calc)
    await test_executor._process_job(job_id, "msg-2")

    assert job_state["steps"][str(TestFlow.calc)] == {"total": 200}
    assert job_state["output"] == {"total": 200}
    assert job_state["result"] == {"total": 200}
    assert job_state["status"] == "finished"


@mark.asyncio
async def test_next_with_data_saved_to_steps(test_executor):
    bp = Blueprint(name="ux_next_data_bp")

    @bp.start(TestFlow.start)
    async def handle_start():
        return Next(TestFlow.done, data={"status_code": 200, "message": "success"})

    @bp.end(TestFlow.done)
    async def handle_done(status_code: int):
        return {"final_code": status_code}

    bp.validate()
    test_executor.engine.blueprints["ux_next_data_bp"] = bp

    job_id = "job-ux-next"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_next_data_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-1")

    assert job_state["steps"][str(TestFlow.start)] == {"status_code": 200, "message": "success"}
    assert job_state["current_state"] == str(TestFlow.done)


@mark.asyncio
async def test_context_go_to_returns_next(test_executor):
    bp = Blueprint(name="ux_context_goto_bp")

    @bp.start(TestFlow.start)
    async def handle_start(context: JobContext):
        return context.go_to(TestFlow.done, data={"item": "book", "qty": 3})

    @bp.end(TestFlow.done)
    async def handle_done(item: str, qty: int):
        return {"receipt": f"{item} x{qty}"}

    bp.validate()
    test_executor.engine.blueprints["ux_context_goto_bp"] = bp

    job_id = "job-ux-goto"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_context_goto_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-1")
    assert job_state["current_state"] == str(TestFlow.done)
    assert job_state["steps"][str(TestFlow.start)] == {"item": "book", "qty": 3}

    await test_executor._process_job(job_id, "msg-2")
    assert job_state["output"] == {"receipt": "book x3"}
    assert job_state["status"] == "finished"


@mark.asyncio
async def test_model_return_value_serialization(test_executor):
    bp = Blueprint(name="ux_model_bp")

    @bp.start(TestFlow.start)
    async def handle_start():
        return Next(TestFlow.done)

    @bp.end(TestFlow.done)
    async def handle_done() -> ReceiptModel:
        return ReceiptModel(receipt_id="rec-999", total=49.99)

    bp.validate()
    test_executor.engine.blueprints["ux_model_bp"] = bp

    job_id = "job-ux-model"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_model_bp",
        "current_state": str(TestFlow.done),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-1")

    assert job_state["output"] == {"receipt_id": "rec-999", "total": 49.99}
    assert job_state["result"] == {"receipt_id": "rec-999", "total": 49.99}
    assert job_state["status"] == "finished"


@mark.asyncio
async def test_custom_terminal_status_from_bp_end(test_executor):
    bp = Blueprint(name="ux_custom_status_bp")

    @bp.start(TestFlow.start)
    async def handle_start():
        return Next(TestFlow.rejected)

    @bp.end(TestFlow.rejected, status="rejected")
    async def handle_rejected():
        return {"reason": "insufficient_funds"}

    bp.validate()
    test_executor.engine.blueprints["ux_custom_status_bp"] = bp

    job_id = "job-ux-status"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_custom_status_bp",
        "current_state": str(TestFlow.rejected),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-1")

    assert job_state["status"] == "rejected"
    assert job_state["output"] == {"reason": "insufficient_funds"}


@mark.asyncio
async def test_output_schema_validation_success_and_failure(test_executor):
    bp = Blueprint(name="ux_schema_val_bp")

    @bp.start(TestFlow.start)
    async def handle_start():
        return Next(TestFlow.done)

    @bp.end(TestFlow.done)
    async def handle_done() -> OutputModel:
        return OutputModel(result_code=42)

    bp.validate()
    test_executor.engine.blueprints["ux_schema_val_bp"] = bp
    test_executor.engine.blueprint_contracts["ux_schema_val_bp"] = {
        "output_schema": {
            "type": "object",
            "properties": {"result_code": {"type": "integer"}},
            "required": ["result_code"],
        }
    }

    job_id = "job-ux-val-ok"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_schema_val_bp",
        "current_state": str(TestFlow.done),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-1")
    assert job_state["status"] == "finished"
    assert job_state["output"] == {"result_code": 42}

    # Now test contract violation: invalid output
    bp_bad = Blueprint(name="ux_schema_val_bad_bp")

    @bp_bad.start(TestFlow.start)
    async def bad_start():
        return Next(TestFlow.done)

    @bp_bad.end(TestFlow.done)
    async def bad_done():
        return {"result_code": "not_an_int"}  # String instead of int

    bp_bad.validate()
    test_executor.engine.blueprints["ux_schema_val_bad_bp"] = bp_bad
    test_executor.engine.blueprint_contracts["ux_schema_val_bad_bp"] = {
        "output_schema": {
            "type": "object",
            "properties": {"result_code": {"type": "integer"}},
            "required": ["result_code"],
        }
    }

    job_id_bad = "job-ux-val-bad"
    job_state_bad = {
        "id": job_id_bad,
        "blueprint_name": "ux_schema_val_bad_bp",
        "current_state": str(TestFlow.done),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state_bad

    await test_executor._process_job(job_id_bad, "msg-2")
    assert job_state_bad["status"] == "failed"
    assert "contract violation" in job_state_bad["error_message"].lower()


@mark.asyncio
async def test_skill_invocation_dispatches_task(test_executor):
    ocr = Skill("document-ocr", timeout=25, fallback=TestFlow.rejected)
    bp = Blueprint(name="ux_skill_bp")

    @bp.start(TestFlow.start)
    async def handle_start():
        return ocr(image_url="https://example.com/doc.png", next=TestFlow.done)

    @bp.end(TestFlow.done)
    async def handle_done():
        pass

    @bp.end(TestFlow.rejected)
    async def handle_rejected():
        pass

    bp.validate()
    test_executor.engine.blueprints["ux_skill_bp"] = bp

    job_id = "job-ux-skill"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_skill_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-skill")

    # Should set status to waiting_for_worker and configure dispatch info
    assert job_state["status"] == "waiting_for_worker"
    assert job_state["current_task_info"]["type"] == "document-ocr"
    assert job_state["current_task_info"]["params"] == {"image_url": "https://example.com/doc.png"}
    assert job_state["current_task_info"]["transitions"]["success"] == str(TestFlow.done)
    assert job_state["current_task_info"]["transitions"]["failed"] == str(TestFlow.rejected)


@mark.asyncio
async def test_save_result_action_compatibility(test_executor):
    bp = Blueprint(name="ux_save_result_bp")

    @bp.start(TestFlow.start)
    async def handle_start(actions: ActionFactory):
        actions.save_result({"saved_manually": True})
        actions.go_to(str(TestFlow.done))

    @bp.end(TestFlow.done)
    async def handle_done():
        pass

    bp.validate()
    test_executor.engine.blueprints["ux_save_result_bp"] = bp

    job_id = "job-ux-manual"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_save_result_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-man")
    assert job_state["steps"][str(TestFlow.start)] == {"saved_manually": True}
    assert "state_history" not in job_state


# --- NEGATIVE & BOUNDARY CASES ---


@dataclass
class UserModel:
    user_id: str
    email: str


@mark.asyncio
async def test_step_raising_exception_records_history_and_fails(test_executor):
    bp = Blueprint(name="ux_exception_bp")

    @bp.start(TestFlow.start)
    async def crash_handler():
        if False:
            return Next(TestFlow.done)
        raise RuntimeError("Payment gateway timeout simulation")

    @bp.end(TestFlow.done)
    async def done_handler():
        pass

    bp.validate()
    test_executor.engine.blueprints["ux_exception_bp"] = bp

    job_id = "job-ux-crash"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_exception_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "retry_count": 5,  # Exceed max retries to force failure
        "steps": {},
        "input": {},
        "history": [],
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-crash")

    assert job_state["status"] in ("failed", "error", "quarantined")
    assert "Payment gateway timeout simulation" in job_state.get("error_message", "")
    assert len(job_state["history"]) > 0
    last_event = job_state["history"][-1]
    assert last_event["state"] == str(TestFlow.start)
    assert last_event["status"] in ("failed", "quarantined")


@mark.asyncio
async def test_output_schema_violation_missing_required_property(test_executor):
    bp = Blueprint(name="ux_missing_field_bp")

    @bp.start(TestFlow.start)
    async def handle_start():
        return Next(TestFlow.done)

    @bp.end(TestFlow.done)
    async def handle_done():
        return {}  # Missing required field 'result_code'

    bp.validate()
    test_executor.engine.blueprints["ux_missing_field_bp"] = bp
    test_executor.engine.blueprint_contracts["ux_missing_field_bp"] = {
        "output_schema": {
            "type": "object",
            "properties": {"result_code": {"type": "integer"}},
            "required": ["result_code"],
        }
    }

    job_id = "job-ux-missing-req"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_missing_field_bp",
        "current_state": str(TestFlow.done),
        "status": "running",
        "steps": {},
        "input": {},
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-miss")
    assert job_state["status"] == "failed"
    assert "contract violation" in job_state["error_message"].lower()


@mark.asyncio
async def test_composite_model_parameters_injection(test_executor):
    bp = Blueprint(name="ux_composite_inject_bp")

    @bp.start(TestFlow.start)
    async def start(user: UserModel, receipt: ReceiptModel):
        return Next(TestFlow.done, data={"summary": f"{user.email}:{receipt.receipt_id}"})

    @bp.end(TestFlow.done)
    async def done(context: JobContext):
        return context.steps[str(TestFlow.start)]

    bp.validate()
    test_executor.engine.blueprints["ux_composite_inject_bp"] = bp

    job_id = "job-ux-comp-inj"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_composite_inject_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {
            "user": {"user_id": "u-42", "email": "alice@corp.io"},
            "receipt": {"receipt_id": "rec-100", "total": 250.0},
        },
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    await test_executor._process_job(job_id, "msg-comp-1")
    assert job_state["current_state"] == str(TestFlow.done)
    assert job_state["steps"][str(TestFlow.start)] == {"summary": "alice@corp.io:rec-100"}

    await test_executor._process_job(job_id, "msg-comp-2")
    assert job_state["status"] == "finished"
    assert job_state["output"] == {"summary": "alice@corp.io:rec-100"}


@mark.asyncio
async def test_step_returns_primitive_and_history_audit_trail(test_executor):
    bp = Blueprint(name="ux_audit_primitive_bp")

    @bp.start(TestFlow.start)
    async def start():
        # Returns primitive integer
        return Next(TestFlow.calc, data=42)

    @bp.step(TestFlow.calc)
    async def calc(context: JobContext):
        prev = context.steps[str(TestFlow.start)]
        return Next(TestFlow.done, data={"doubled": prev * 2})

    @bp.end(TestFlow.done)
    async def done(context: JobContext):
        return context.steps[str(TestFlow.calc)]

    bp.validate()
    test_executor.engine.blueprints["ux_audit_primitive_bp"] = bp

    job_id = "job-ux-audit"
    job_state = {
        "id": job_id,
        "blueprint_name": "ux_audit_primitive_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {},
        "history": [],
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    # Step 1
    await test_executor._process_job(job_id, "msg-1")
    assert job_state["steps"][str(TestFlow.start)] == 42
    assert len(job_state["history"]) == 1
    assert job_state["history"][0]["state"] == str(TestFlow.start)
    assert job_state["history"][0]["status"] == "success"
    assert job_state["history"][0]["duration_ms"] >= 0

    # Step 2
    await test_executor._process_job(job_id, "msg-2")
    assert job_state["steps"][str(TestFlow.calc)] == {"doubled": 84}
    assert len(job_state["history"]) == 2
    assert job_state["history"][1]["state"] == str(TestFlow.calc)

    # Step 3 (terminal)
    await test_executor._process_job(job_id, "msg-3")
    assert job_state["status"] == "finished"
    assert job_state["output"] == {"doubled": 84}
    assert len(job_state["history"]) == 3
    assert job_state["history"][2]["state"] == str(TestFlow.done)


@mark.asyncio
async def test_duck_typed_pydantic_and_msgspec_struct_coercion(test_executor):
    # 1. Native msgspec.Struct
    class MsgspecModel(Struct):
        code: int
        title: str

    # 2. Duck-typed Pydantic model (with model_validate and model_dump)
    class DuckPydanticModel:
        def __init__(self, val: str):
            self.val = val

        @classmethod
        def model_validate(cls, data):
            if isinstance(data, dict):
                return cls(val=data["val"])
            raise ValueError()

        def model_dump(self):
            return {"val": self.val}

    bp = Blueprint(name="duck_msgspec_bp")

    captured = {}

    @bp.start(TestFlow.start)
    async def handle_start(actions: ActionFactory):
        actions.go_to(str(TestFlow.done))
        return DuckPydanticModel(val="pydantic_ok")

    @bp.end(TestFlow.done)
    async def handle_done(duck: DuckPydanticModel, m: MsgspecModel):
        captured["duck"] = duck
        captured["m"] = m
        return MsgspecModel(code=200, title="done")

    bp.validate()
    test_executor.engine.blueprints["duck_msgspec_bp"] = bp

    job_id = "job-duck-msgspec"
    job_state = {
        "id": job_id,
        "blueprint_name": "duck_msgspec_bp",
        "current_state": str(TestFlow.start),
        "status": "running",
        "steps": {},
        "input": {"m": {"code": 100, "title": "initial"}},
        "history": [],
    }
    test_executor.storage.get_job_state.return_value = job_state
    test_executor.storage.ack_job = AsyncMock()

    # Step 1: start returns DuckPydanticModel -> serialized via model_dump
    await test_executor._process_job(job_id, "msg-1")
    assert job_state["steps"][str(TestFlow.start)] == {"val": "pydantic_ok"}

    # Step 2: done receives DuckPydanticModel coerced from step, MsgspecModel coerced from input
    await test_executor._process_job(job_id, "msg-2")
    assert job_state["status"] == "finished"
    assert isinstance(captured["duck"], DuckPydanticModel)
    assert captured["duck"].val == "pydantic_ok"
    assert isinstance(captured["m"], MsgspecModel)
    assert captured["m"].code == 100
    assert captured["m"].title == "initial"
    assert job_state["output"] == {"code": 200, "title": "done"}
