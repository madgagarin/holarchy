[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/creating_blueprint.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/creating_blueprint.md)

# Libro de recetas: Creación de un Blueprint (Pipeline) moderno

Un `Blueprint` en Holarchy define la lógica del proceso de negocio como una máquina de estados finitos (Finite State Machine, FSM). Cada blueprint especifica estados, transiciones, políticas de seguridad, enrutamiento consultivo y contratos de datos.

---

## 1. Definición de estados con `StatesGroup`

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

---

## 2. Modelos de dominio e inicialización de Blueprint

```python
from pydantic import BaseModel, Field
from holarchy import Blueprint, Context, Next, Skill


class OrderInput(BaseModel):
    order_id: int
    customer_id: str
    amount: float = Field(..., gt=0)
    items: list[str]


class OrderOutput(BaseModel):
    order_id: int
    receipt_id: str
    status: str
    amount: float


order_bp = Blueprint(
    name="order_processing_flow",
    api_version="v1",
    api_endpoint="/jobs/orders",
)
```

---

## 3. Definición de pasos y las 5 zonas de almacenamiento

Holarchy segmenta el estado del trabajo en **5 zonas limpias**:
- `input`: Datos de la petición del cliente (`OrderInput`).
- `steps`: Resultados intermedios de cada paso (`steps["validate"]`).
- `history`: Registro cronológico de transiciones de estado.
- `meta`: Metadatos, prioridades, tiempos límite y cabeceras (`meta["priority"]`).
- `output`: Resultado devuelto por el paso terminal (`OrderOutput`).

### Punto de entrada (`@bp.start`)

```python
@order_bp.start(OrderFlow.init)
async def init_step(order: OrderInput, ctx: Context) -> State:
    return OrderFlow.validate
```

### Paso intermedio con transición automática (`@bp.step`)

```python
@order_bp.step(
    OrderFlow.validate,
    on_success=OrderFlow.fraud_check,
    risk="low",
    permissions=["orders:read"],
)
async def validate_order(order: OrderInput):
    if not order.items:
        raise ValueError("El pedido debe contener al menos un elemento")
    return {"valid": True, "item_count": len(order.items)}
```

### Enrutamiento consultivo con IA (`@bp.decide`)

```python
@order_bp.decide(
    OrderFlow.fraud_check,
    candidates=[OrderFlow.payment, OrderFlow.failed],
    fallback=OrderFlow.payment,
    timeout_seconds=2.0,
    risk="medium",
)
async def check_fraud(order: OrderInput, steps: dict) -> State:
    if order.amount > 50_000:
        return OrderFlow.failed
    return OrderFlow.payment
```

### Distribución de tareas a workers mediante Skills

```python
charge_skill = Skill("stripe_charge", timeout=10.0, fallback=OrderFlow.failed)


@order_bp.step(OrderFlow.payment, risk="high", permissions=["billing:charge"])
async def process_payment(order: OrderInput):
    return charge_skill(
        amount=order.amount,
        customer_id=order.customer_id,
        next=OrderFlow.fulfill,
        on_failure=OrderFlow.failed,
    )
```

### Estados terminales (`@bp.end`)

```python
@order_bp.end(OrderFlow.fulfill, status="finished")
async def fulfill_order(order: OrderInput, steps: dict) -> OrderOutput:
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

## 4. Validación de integridad

```python
order_bp.validate()
```

---

## 5. Documentación interactiva y OpenAPI 3.1

- **UI interactiva**: `http://localhost:8080/docs`
- **OpenAPI 3.1 JSON**: `http://localhost:8080/openapi.json`
- **Topología DAG**: `GET /api/v1/blueprints/{blueprint_name}/dag`
