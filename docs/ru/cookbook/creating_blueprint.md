[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/creating_blueprint.md) | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/creating_blueprint.md) | **RU**

# Рецепт: Создание современного Blueprint (Конвейера)

`Blueprint` в Holarchy описывает бизнес-процесс в виде конечного автомата (Finite State Machine, FSM). Каждый блупринт определяет состояния, переходы, политики безопасности, правила маршрутизации и контракты данных.

В этом руководстве показано, как создать надежный, строго типизированный конвейер с использованием современных возможностей Holarchy.

---

## 1. Определение состояний через `StatesGroup`

Объединяйте состояния конвейера в именованный класс `StatesGroup`:

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

Каждое состояние автоматически наследует строковый идентификатор без накладных расходов (`"OrderFlow:init"`), гарантируя прозрачную сериализацию в JSON/Redis и исключая ошибки в именах состояний.

---

## 2. Модели предметной области и инициализация Blueprint

Holarchy нативно валидирует входящие запросы и выходы шагов через модели **Pydantic**:

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


# Создание экземпляра блупринта с привязкой к API
order_bp = Blueprint(
    name="order_processing_flow",
    api_version="v1",
    api_endpoint="/jobs/orders",
)
```

---

## 3. Определение шагов и 5 чистых зон хранения

Holarchy разделяет состояние задачи на **5 изолированных зон**:
- `input`: Исходные данные запроса (`OrderInput`).
- `steps`: Результаты выполнения отдельных шагов (`steps["validate"]`).
- `history`: Хронологическая последовательность переходов с таймстемпами.
- `meta`: Метаданные задачи, приоритеты, тайм-ауты и заголовки (`meta["priority"]`).
- `output`: Финальный результат терминального шага (`OrderOutput`).

### Точка входа (`@bp.start`)

```python
@order_bp.start(OrderFlow.init)
async def init_step(order: OrderInput, ctx: Context) -> State:
    """Точка входа автоматически получает валидированную модель OrderInput."""
    print(f"Запуск заказа {order.order_id} для клиента {order.customer_id}")
    return OrderFlow.validate
```

### Промежуточный шаг с автопереходом (`@bp.step`)

```python
@order_bp.step(
    OrderFlow.validate,
    on_success=OrderFlow.fraud_check,
    risk="low",
    permissions=["orders:read"],
)
async def validate_order(order: OrderInput):
    """Выполняет валидацию. При успехе автоматически переходит в on_success."""
    if not order.items:
        raise ValueError("В заказе должен присутствовать хотя бы один товар")
    return {"valid": True, "item_count": len(order.items)}
```

### Консультативная AI-маршрутизация (`@bp.decide`)

```python
@order_bp.decide(
    OrderFlow.fraud_check,
    candidates=[OrderFlow.payment, OrderFlow.failed],
    fallback=OrderFlow.payment,
    timeout_seconds=2.0,
    risk="medium",
)
async def check_fraud(order: OrderInput, steps: dict) -> State:
    """Консультативная проверка: выбор ограничен списком кандидатов candidates."""
    if order.amount > 50_000:
        return OrderFlow.failed
    return OrderFlow.payment
```

### Распределение задач на воркеры через навыки (Skills)

```python
# Объявление навыка с тайм-аутом и fallback
charge_skill = Skill("stripe_charge", timeout=10.0, fallback=OrderFlow.failed)


@order_bp.step(OrderFlow.payment, risk="high", permissions=["billing:charge"])
async def process_payment(order: OrderInput):
    """Отправляет задачу на исполнение зарегистрированному воркеру."""
    return charge_skill(
        amount=order.amount,
        customer_id=order.customer_id,
        next=OrderFlow.fulfill,
        on_failure=OrderFlow.failed,
    )
```

### Терминальное состояние (`@bp.end`)

```python
@order_bp.end(OrderFlow.fulfill, status="finished")
async def fulfill_order(order: OrderInput, steps: dict) -> OrderOutput:
    """Терминальный обработчик, возвращающий финализированную схему."""
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

## 4. Проверка целостности графа (Validate Integrity)

Проверяйте отсутствие изолированных состояний и висячих переходов:

```python
# Проверка графа при старте приложения или в юнит-тестах
order_bp.validate()
```

---

## 5. Автоматическая генерация OpenAPI 3.1 и интерактивная документация

После регистрации блупринта в оркестраторе документация формируется на лету:
- **Интерактивный UI**: `http://localhost:8080/docs` отображает схему запроса, бейджи рисков, права доступа и интерактивную панель тестирования.
- **Спецификация OpenAPI 3.1 JSON**: `http://localhost:8080/openapi.json` для Swagger UI, Scalar, Postman и кодогенераторов.
- **Топология DAG**: `GET /api/v1/blueprints/{blueprint_name}/dag` для визуализации графа состояний.
