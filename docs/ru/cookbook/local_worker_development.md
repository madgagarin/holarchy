[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/local_worker_development.md) | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/local_worker_development.md) | **RU**

# Рецепт: Локальная разработка и тестирование воркеров

Воркеры в экосистеме Holarchy — это независимые исполнительные агенты, получающие задачи от Оркестратора, исполняющие прикладной код и отправляющие результаты обратно.

Данный рецепт описывает процесс настройки, разработки, тестирования и отладки воркера на локальной машине с помощью SDK `holonode`.

---

## 1. Установка и подготовка окружения

Установите `holonode` с поддержкой валидации через Pydantic и работы с файловыми хранилищами S3:

```bash
# Рекомендуемая установка с автовалидацией Pydantic и поддержкой S3
pip install "holonode[pydantic,s3]"
```

---

## 2. Определение строго типизированных навыков (Skills)

Воркер регистрирует один или несколько навыков через декоратор `@worker.skill`. Использование моделей Pydantic обеспечивает проверку типов, валидацию входных данных и автоматическое формирование контрактов.

```python
import asyncio
from pydantic import BaseModel, Field
from holonode import Worker


class ImageResizeParams(BaseModel):
    image_url: str = Field(..., description="URL или S3-ключ исходного изображения")
    width: int = Field(default=800, ge=16, le=4096)
    height: int = Field(default=600, ge=16, le=4096)
    format: str = Field(default="webp", pattern="^(webp|jpeg|png)$")


class ImageResizeResult(BaseModel):
    processed_url: str
    original_size_kb: float
    compressed_size_kb: float


worker = Worker(worker_type="image-processor")


@worker.skill(
    "resize_image",
    risk="low",
    permissions=["media:read", "media:write"],
)
async def handle_resize(params: ImageResizeParams, **kwargs) -> dict:
    """Обработчик изменения размера изображения.

    Аргумент params автоматически валидируется в модель ImageResizeParams.
    """
    task_id = kwargs.get("task_id")
    print(f"[{task_id}] Изменение размера {params.image_url} до {params.width}x{params.height}")

    # Имитация обработки
    await asyncio.sleep(0.5)

    return {
        "status": "success",
        "data": ImageResizeResult(
            processed_url=f"{params.image_url}_resized.{params.format}",
            original_size_kb=1024.0,
            compressed_size_kb=312.5,
        ).model_dump(),
    }


if __name__ == "__main__":
    worker.run()
```

---

## 3. Кооперативная отмена длительных задач

Для вычислительно сложных или продолжительных операций обязательно проверяйте флаг отмены, поступающий от Оркестратора:

```python
@worker.skill("video_transcode")
async def handle_transcode(params: dict, **kwargs) -> dict:
    task_id = kwargs["task_id"]

    for chunk_idx in range(100):
        # 1. Неблокирующая проверка запроса на отмену
        if await worker.check_for_cancellation(task_id):
            print(f"Поступил запрос отмены для {task_id}. Удаление временных файлов...")
            return {"status": "cancelled", "message": f"Остановлено на фрагменте {chunk_idx}"}

        # 2. Обработка фрагмента
        await asyncio.sleep(0.1)

    return {"status": "success", "data": {"transcoded_chunks": 100}}
```

---

## 4. Локальная конфигурация через `.env`

Настройте параметры воркера без изменения исходного кода:

```dotenv
# Идентификация воркера
WORKER_ID=local-image-worker-01
WORKER_TYPE=image-processor

# Адрес локального оркестратора
ORCHESTRATOR_URL=http://127.0.0.1:8080

# Аутентификация (должна совпадать с GLOBAL_WORKER_TOKEN оркестратора)
WORKER_TOKEN=secure-worker-token

# Режим связи: WebSocket обеспечивает мгновенные уведомления об отмене
ENABLE_WEBSOCKET=true
POLL_INTERVAL=1.0

# Параллелизм
MAX_CONCURRENT_TASKS=4
```

---

## 5. Модульное тестирование навыков без запущенного Оркестратора

Тестируйте функции навыков в `pytest` напрямую без необходимости поднимать инфраструктуру:

```python
import pytest
from my_worker import ImageResizeParams, handle_resize


@pytest.mark.asyncio
async def test_resize_handler_success():
    params = ImageResizeParams(
        image_url="https://storage.example.com/banner.png",
        width=1200,
        height=630,
        format="webp",
    )

    result = await handle_resize(params, task_id="test-task-1")

    assert result["status"] == "success"
    assert result["data"]["compressed_size_kb"] < result["data"]["original_size_kb"]
    assert result["data"]["processed_url"].endswith(".webp")
```

---

## 6. Совместный запуск Оркестратора и Воркера

Запустите оркестратор и воркер в двух окнах терминала:

**Терминал 1 (Оркестратор):**
```bash
python -m holarchy run --port 8080
```

**Терминал 2 (Воркер):**
```bash
python my_worker.py
```

Воркер зарегистрирует свои навыки в каталоге, и они сразу появятся в списке `GET /api/v1/skills` и в интерактивной документации по адресу `http://127.0.0.1:8080/docs`.
