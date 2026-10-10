**EN** | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/creating_blueprint.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/creating_blueprint.md)

# Cookbook: Creating a Modern Blueprint (Pipeline)

A `Blueprint` in Holarchy defines the business process as a Finite State Machine (FSM). Each blueprint specifies states, transitions, security policies, advisory routing, and data contracts.

This guide demonstrates creating a robust, type-safe, production-ready pipeline using modern Holarchy constructs.

---

## 1. Defining FSM States with `StatesGroup`

Group your pipeline states into an enumerated `StatesGroup`:

```python
from holarchy import State, StatesGroup


class OrderFlow(StatesGroup):
    init = State()
    validate = State()
    fraud_check = State()
    payment = State()
    fulfill = State()
    finalize = State()
    failed = State()
```

Each state automatically inherits zero-overhead string identity (`"OrderFlow:init"`) for transparent serialization while preventing typo bugs.

---

## 2. Setting Up Domain Models & Blueprint

Holarchy natively validates incoming requests and step outputs against standard Python `@dataclass`, `msgspec.Struct`, or Pydantic models (via duck typing):

```python
from dataclasses import dataclass
from holarchy import Blueprint, Context, Next, Skill


@dataclass
class OrderInput:
    order_id: int
    customer_id: str
    amount: float
    items: list[str]


@dataclass
class OrderOutput:
    order_id: int
    receipt_id: str
    status: str
    amount: float


# Initialize blueprint with API endpoint
order_bp = Blueprint(
    name="order_processing_flow",
    api_version="v1",
    api_endpoint="/jobs/orders",
)
```

---

## 3. Defining Steps with Clean Storage Zones & Dependency Injection

Holarchy segments job state into **5 clean zones**:
- `input`: The original client payload (`OrderInput`).
- `steps`: Dictionary of individual step results (`steps["validate"]`).
- `history`: Sequential list of state transitions with execution timestamps.
- `meta`: Job metadata, priorities, timeouts, and headers (`meta["priority"]`).
- `output`: Final result of the terminal step (`OrderOutput`).

### Entry Point (`@bp.start`)

```python
@order_bp.start(OrderFlow.init)
async def init_step(order: OrderInput, ctx: Context) -> State:
    """The entry point receives the validated OrderInput model automatically."""
    print(f"Starting order {order.order_id} for customer {order.customer_id}")
    return OrderFlow.validate
```

### Intermediate Step with Auto-Transition (`@bp.step`)

```python
@order_bp.step(
    OrderFlow.validate,
    on_success=OrderFlow.fraud_check,
    risk="low",
    permissions=["orders:read"],
)
async def validate_order(order: OrderInput):
    """Executes validation. On completion, automatically transitions to on_success."""
    if not order.items:
        raise ValueError("Order must contain at least one item")
    return {"valid": True, "item_count": len(order.items)}
```

### Advisory Decision Routing (`@bp.decide`)

```python
@order_bp.decide(
    OrderFlow.fraud_check,
    candidates=[OrderFlow.payment, OrderFlow.failed],
    fallback=OrderFlow.payment,
    timeout_seconds=2.0,
    risk="medium",
)
async def check_fraud(order: OrderInput, steps: dict) -> State:
    """Advisory check: host restricts transition strictly to candidate states."""
    if order.amount > 50_000:
        return OrderFlow.failed
    return OrderFlow.payment
```

### Distributing Work to Workers via Skills

```python
# Declare skill with timeout and fallback
charge_skill = Skill("stripe_charge", timeout=10.0, fallback=OrderFlow.failed)


@order_bp.step(OrderFlow.payment, risk="high", permissions=["billing:charge"])
async def process_payment(order: OrderInput):
    """Dispatches a task to a registered remote worker skill."""
    return charge_skill(
        amount=order.amount,
        customer_id=order.customer_id,
        next=OrderFlow.fulfill,
        on_failure=OrderFlow.failed,
    )
```

### Terminal State (`@bp.end`)

```python
@order_bp.end(OrderFlow.fulfill, status="finished")
async def fulfill_order(order: OrderInput, steps: dict) -> OrderOutput:
    """Terminal handler returning the finalized schema."""
    payment_res = steps.get("OrderFlow:payment", {})
    return OrderOutput(
        order_id=order.order_id,
        receipt_id=payment_res.get("receipt_id", f"rcpt_{order.order_id}"),
        status="paid",
        amount=order.amount,
    )


@order_bp.end(OrderFlow.failed, status="failed")
async def on_failed_order(order: OrderInput):
    return {"status": "rejected", "order_id": order.order_id}
```

---

## 4. Validating Graph Integrity

Verify that all states are reachable and that there are no dangling transitions:

```python
# Validates state graph at initialization or in unit tests
order_bp.validate()
```

---

## 5. Automatic OpenAPI 3.1 & Interactive Docs

Once registered in the orchestrator, your blueprint is automatically documented:
- **Interactive UI**: `http://localhost:8080/docs` displays the input schema, risk level badges, permissions, and test harness.
- **OpenAPI 3.1 JSON**: `http://localhost:8080/openapi.json` exports machine-readable API specifications.
- **DAG Topology**: `GET /api/v1/blueprints/{blueprint_name}/dag` provides the spatial graph for visual monitoring.
