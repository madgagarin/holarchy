[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/ai_routing_and_replay.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/ai_routing_and_replay.md)

# Libro de recetas: Enrutamiento consultivo de IA y pruebas de reproducción deterministas

Holarchy adopta los principios de **Host-Owned Choice** (elección controlada por el anfitrión) y **Fail-Open Guarantee** (garantía de tolerancia a fallos) para flujos de trabajo impulsados por IA:
1. **Decisión consultiva**: El LLM o modelo heurístico únicamente recomienda una ruta; el orquestador anfitrión restringe estrictamente las transiciones al conjunto preaprobado de estados candidatos (`candidates`).
2. **Garantía de recuperación segura (Fail-Open)**: Si el enrutador agota el tiempo de espera, lanza una excepción o devuelve un estado inválido, el motor realiza automáticamente una transición a un estado de respaldo (`fallback`) predecible sin interrumpir el trabajo.
3. **Comprobantes de ejecución (Execution Receipts) y reproducción**: Cada decisión se audita y registra como un `ExecutionReceipt`. Las decisiones guardadas se pueden reproducir sin conexión para evaluar la deriva de prompts y actualizaciones de modelos sin invocar servicios externos.

---

## 1. Definición de enrutamiento consultivo en un Blueprint

Utilice `@bp.decide` para declarar un paso de enrutamiento inteligente:

```python
from pydantic import BaseModel
from holarchy import Blueprint, Context, State, StatesGroup


class OrderFlow(StatesGroup):
    init = State()
    routing = State()
    vip_fulfillment = State()
    standard_fulfillment = State()
    fraud_quarantine = State()
    finalize = State()


class OrderInput(BaseModel):
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
    """Enrutador inteligente: puede invocar un LLM, clasificador o reglas heurísticas.

    Si este manejador falla, supera el tiempo de espera (>2.5s) o devuelve un estado no candidato,
    Holarchy transiciona automáticamente al estado de respaldo (standard_fulfillment).
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

## 2. Enrutamiento dinámico en el paso con `ActionFactory.decide`

Si la decisión se toma dentro del cuerpo de un manejador de paso, utilice `actions.decide`:

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

Holarchy genera automáticamente un `ExecutionReceipt` y lo anexa a `job_state["receipts"]`.

---

## 3. Comprobantes de ejecución y auditoría

Cada decisión genera un comprobante con el siguiente esquema:

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

Los comprobantes se pueden inspeccionar a través de la API en `GET /api/v1/jobs/{job_id}` o guardarse localmente en formato `.jsonl` para pruebas de regresión.

---

## 4. Pruebas de reproducción (Replay Testing) deterministas

Las pruebas de reproducción evalúan modelos de decisión contra registros históricos sin necesidad de volver a ejecutar los workers ni llamar a APIs externas.

### Ejecución programática

```python
from pathlib import Path
from holarchy.testing.replay import ReplayTestRunner, record_execution_receipt

cases_file = Path("test_cases/order_routing.jsonl")

runner = ReplayTestRunner(blueprint=order_bp, cases_file=str(cases_file))
report = await runner.run()

print(f"Total de casos: {report.total_cases}")
print(f"Precisión respecto al patrón: {report.accuracy_rate:.2%}")
print(f"Activaciones de Fallback: {report.fallback_count}")
print(f"Latencia media de decisión: {report.avg_latency_ms} ms")

assert report.accuracy_rate >= 0.98
```

### Herramienta CLI de Replay

```bash
holarchy replay --blueprint intelligent_orders --cases test_cases/order_routing.jsonl --tolerance 0.05
```
