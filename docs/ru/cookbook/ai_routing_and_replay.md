[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/ai_routing_and_replay.md) | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/ai_routing_and_replay.md) | **RU**

# Рецепт: Консультативная AI-маршрутизация и детерминированное Replay-тестирование

Holarchy реализует принципы **Host-Owned Choice** (выбор контролируется хостом) и **Fail-Open Guarantee** (гарантия отказоустойчивости при сбоях) для конвейеров с искусственным интеллектом:
1. **Консультативное решение**: LLM или эвристическая модель лишь рекомендует путь; оркестратор строго ограничивает доступные переходы заранее утвержденным списком кандидатов (`candidates`).
2. **Безопасный Fallback**: Если маршрутизатор завершается по тайм-ауту, выбрасывает исключение или галлюцинирует несуществующее состояние, движок автоматически переходит в детерминированное безопасное состояние (`fallback`), не прерывая выполнение задачи.
3. **Чеки выполнения (Execution Receipts) и Replay**: Каждое решение фиксируется в виде аудируемого чека `ExecutionReceipt`. Записанные чеки можно воспроизводить офлайн для оценки дрейфа промптов, обновления моделей и регрессионного тестирования без вызова реальных внешних сервисов.

---

## 1. Определение консультативной маршрутизации в Blueprint

Используйте декоратор `@bp.decide` для объявления шага интеллектуальной маршрутизации:

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
    """Интеллектуальный маршрутизатор: вызывает LLM, классификатор или правила.

    Если обработчик выбросит исключение, превысит тайм-аут (>2.5 с) или вернет некорректный статус,
    Holarchy автоматически выполнит переход в fallback (standard_fulfillment).
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

## 2. Динамическая маршрутизация внутри шага через `ActionFactory.decide`

Если выбор стратегии происходит внутри произвольного обработчика шага, используйте `actions.decide`:

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

Holarchy автоматически генерирует `ExecutionReceipt` и добавляет его в `job_state["receipts"]`.

---

## 3. Чеки выполнения и прозрачный аудит

Каждое решение генерирует чек следующей структуры:

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

Чеки доступны по API через `GET /api/v1/jobs/{job_id}` или сохраняются локально в `.jsonl` для последующего анализа.

---

## 4. Детерминированное Replay-тестирование

Replay-тестирование позволяет проверять модели принятия решений на исторических production-кейсах без повторного запуска воркеров и без обращения к платным LLM API.

### Программный запуск Replay-тестов

```python
from pathlib import Path
from holarchy.testing.replay import ReplayTestRunner, record_execution_receipt

# 1. Запись кейсов из продакшена или синтетического датасета
cases_file = Path("test_cases/order_routing.jsonl")

# 2. Запуск реплей-тестов для обновленного блупринта
runner = ReplayTestRunner(blueprint=order_bp, cases_file=str(cases_file))
report = await runner.run()

print(f"Всего кейсов: {report.total_cases}")
print(f"Совпадение с эталоном: {report.accuracy_rate:.2%}")
print(f"Срабатываний Fallback: {report.fallback_count}")
print(f"Средняя задержка решения: {report.avg_latency_ms} мс")

# Контроль регрессий
assert report.accuracy_rate >= 0.98
```

### Использование CLI инструмента Replay

Запуск replay-проверок в терминале или CI/CD пайплайне:

```bash
holarchy replay --blueprint intelligent_orders --cases test_cases/order_routing.jsonl --tolerance 0.05
```
