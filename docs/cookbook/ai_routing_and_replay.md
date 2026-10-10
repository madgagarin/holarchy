**EN** | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/ai_routing_and_replay.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/ai_routing_and_replay.md)

# Cookbook: Advisory AI Routing & Deterministic Replay Testing

Holarchy embraces the **Host-Owned Choice** and **Fail-Open Guarantee** principles for AI-driven pipelines:
1. **Advisory Decision**: The LLM or heuristic model only recommends a path; the host orchestrator strictly confines transitions to pre-approved candidate states.
2. **Fail-Open Safety**: If the router times out, raises an exception, or hallucinates an invalid state, the engine automatically falls back to a deterministic, safe state without crashing the job.
3. **Execution Receipts & Replay**: Every decision is auditable and persisted as an `ExecutionReceipt`. Recorded decisions can be replayed offline to evaluate prompt drift, model upgrades, and regressions without executing live side effects.

---

## 1. Defining Advisory Routing in a Blueprint

Use `@bp.decide` to declare an intelligent routing step:

```python
from dataclasses import dataclass
from holarchy import Blueprint, Context, State, StatesGroup


class OrderFlow(StatesGroup):
    init = State()
    routing = State()
    vip_fulfillment = State()
    standard_fulfillment = State()
    fraud_quarantine = State()
    finalize = State()


@dataclass
class OrderInput:
    order_id: int
    amount: float
    user_tier: str
    risk_score: float = 0.0


order_bp = Blueprint("intelligent_orders", api_endpoint="/jobs/orders", api_version="v1")


@order_bp.start(OrderFlow.init)
async def init(order: OrderInput, ctx: Context) -> State:
    return OrderFlow.routing


@order_bp.decide(
    OrderFlow.routing,
    candidates=[
        OrderFlow.vip_fulfillment,
        OrderFlow.standard_fulfillment,
        OrderFlow.fraud_quarantine,
    ],
    fallback=OrderFlow.standard_fulfillment,
    timeout_seconds=2.5,
    risk="medium",
    permissions=["orders:route"],
)
async def route_order(order: OrderInput, ctx: Context) -> State:
    """Intelligent router: can call an LLM, classifier, or heuristic rule.

    If this handler raises an exception, times out (>2.5s), or returns an invalid state,
    Holarchy automatically transitions to fallback (standard_fulfillment).
    """
    if order.risk_score > 0.85:
        return OrderFlow.fraud_quarantine
    if order.amount > 1000.0 or order.user_tier == "vip":
        return OrderFlow.vip_fulfillment
    return OrderFlow.standard_fulfillment


@order_bp.step(OrderFlow.vip_fulfillment, on_success=OrderFlow.finalize)
async def vip_fulfillment(order: OrderInput):
    return {"priority": "express", "status": "processed"}


@order_bp.step(OrderFlow.standard_fulfillment, on_success=OrderFlow.finalize)
async def standard_fulfillment(order: OrderInput):
    return {"priority": "standard", "status": "processed"}


@order_bp.end(OrderFlow.finalize)
async def finalize(ctx: Context):
    return {"status": "completed"}
```

---

## 2. In-Step Dynamic Routing with `ActionFactory.decide`

If routing occurs inside an existing step handler, use `actions.decide`:

```python
@order_bp.step(OrderFlow.routing)
async def dynamic_routing_step(order: OrderInput, actions: ActionFactory):
    chosen = await actions.decide(
        decider_name="tier_selector",
        candidates=["fast_lane", "economy_lane"],
        fallback="economy_lane",
        timeout_seconds=1.5,
    )
    actions.go_to(chosen)
```

Holarchy automatically generates an `ExecutionReceipt` and appends it to `job_state["receipts"]`.

---

## 3. Execution Receipts & Auditability

Every decision generates a receipt with the following schema:

```json
{
  "correlation_id": "corr-order-9823",
  "step": "OrderFlow:routing",
  "candidates": [
    "OrderFlow:vip_fulfillment",
    "OrderFlow:standard_fulfillment",
    "OrderFlow:fraud_quarantine"
  ],
  "chosen": "OrderFlow:vip_fulfillment",
  "fallback_triggered": false,
  "duration_ms": 42,
  "error_message": null
}
```

Receipts can be inspected via API at `GET /api/v1/jobs/{job_id}` or saved locally to a `.jsonl` dataset for testing.

---

## 4. Deterministic Replay Testing

Replay testing evaluates decision models against historic production receipts without re-running workers or making external API calls.

### Programmatic Replay Evaluation

```python
from pathlib import Path

from holarchy.testing.replay import ReplayTestRunner, record_execution_receipt

# 1. Record production or synthetic cases
cases_file = Path("test_cases/order_routing.jsonl")

# 2. Run replay evaluation synchronously in memory
runner = ReplayTestRunner(order_bp)
report = runner.evaluate(str(cases_file))

print(f"Total Cases: {report.total_cases}")
print(f"Matched Decisions: {report.matched_cases}")
print(f"Drift Rate: {report.drift_rate:.1%}")
print(f"Fallback Invocations: {report.fallback_cases}")

# Ensure no regression drift
assert report.drift_cases == 0
```

### CLI Replay Tool

Run replay tests directly from your terminal or CI/CD pipeline:

```bash
# Evaluate historical execution receipts
holarchy replay evaluate --app my_module:order_bp --cases test_cases/order_routing.jsonl

# Fail CI if drift is detected
holarchy replay evaluate --app my_module:order_bp --cases test_cases/order_routing.jsonl --strict
```
