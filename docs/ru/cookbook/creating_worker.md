[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/creating_worker.md) | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/creating_worker.md) | **RU**

# Рецепт: Создание Воркера

Воркеры (Workers) — это независимые исполнители, выполняющие прикладные задачи, порученные Оркестратором. Данное руководство демонстрирует разработку воркера с использованием SDK `holonode`.

---

## 1. Установка

```bash
# Рекомендуется: включает валидацию схем Pydantic и потоковую работу с файлами S3
pip install "holonode[pydantic,s3]"
```

---

## 2. Определение навыков (Skills) с валидацией Pydantic

Объявляйте навыки через декоратор `@worker.skill` с указанием уровня риска и требуемых прав доступа:

```python
import asyncio
from pydantic import BaseModel, Field
from holonode import Worker


class InventoryCheckParams(BaseModel):
    sku: str = Field(..., description="Артикул товара")
    quantity: int = Field(..., gt=0, description="Запрашиваемое количество")


class InventoryCheckResult(BaseModel):
    in_stock: bool
    available_quantity: int
    warehouse_code: str


worker = Worker(worker_type="inventory-service")


@worker.skill(
    "check_inventory",
    risk="low",
    permissions=["inventory:read"],
)
async def check_inventory(params: InventoryCheckParams, **kwargs) -> dict:
    """SDK автоматически валидирует входные параметры в InventoryCheckParams."""
    task_id = kwargs.get("task_id")
    print(f"Проверка артикула {params.sku} для задачи {task_id}")

    # Прикладная логика
    available = 42
    in_stock = available >= params.quantity

    return {
        "status": "success",
        "data": InventoryCheckResult(
            in_stock=in_stock,
            available_quantity=available,
            warehouse_code="WH-US-EAST",
        ).model_dump(),
    }
```

---

## 3. Кооперативная отмена длительных задач

Если задача выполняется несколько секунд или минут, периодически опрашивайте метод `check_for_cancellation` для корректного освобождения ресурсов в случае отмены:

```python
@worker.skill("render_video", risk="high", permissions=["media:render"])
async def render_video(params: dict, **kwargs) -> dict:
    task_id = kwargs["task_id"]

    for frame in range(1000):
        if await worker.check_for_cancellation(task_id):
            print(f"Поступил сигнал отмены для задачи {task_id}. Очистка ресурсов...")
            return {"status": "cancelled", "message": "Рендеринг остановлен оркестратором"}

        await asyncio.sleep(0.01)

    return {"status": "success", "data": {"frames_rendered": 1000}}
```

---

## 4. Конфигурация воркера

Задавайте параметры через переменные окружения или файл `.env`:

```dotenv
# Идентификация
WORKER_ID=inventory-worker-01
WORKER_TYPE=inventory-service

# Адрес Оркестратора
ORCHESTRATOR_URL=http://localhost:8080

# Общий токен доступа
WORKER_TOKEN=secure-worker-token

# Мгновенная доставка сигналов отмены через WebSocket
ENABLE_WEBSOCKET=true
POLL_INTERVAL=1.0

# Лимит параллельных задач
MAX_CONCURRENT_TASKS=8
```

---

## 5. Запуск воркера

```python
if __name__ == "__main__":
    worker.run()
```

При запуске воркер подключается к Оркестратору, объявляет список своих навыков и приступает к обработке поступающих задач.

> Подробное руководство по изолированному тестированию см. в рецепте [Локальная разработка воркеров](local_worker_development.md).
