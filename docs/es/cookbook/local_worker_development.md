[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/local_worker_development.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/local_worker_development.md)

# Libro de recetas: Desarrollo y pruebas locales de Workers

Los workers en el ecosistema de Holarchy son nodos de ejecución independientes que reciben tareas asignadas por el Orquestador, ejecutan código de dominio y reportan los resultados.

Esta receta describe cómo configurar, desarrollar, probar y depurar un worker en su entorno local utilizando el SDK `holonode`.

---

## 1. Instalación y preparación

Instale `holonode` con soporte para validación automática con Pydantic y almacenamiento S3:

```bash
pip install "holonode[pydantic,s3]"
```

---

## 2. Definición de habilidades fuertemente tipadas

Un worker registra sus habilidades mediante el decorador `@worker.skill`. Se admiten modelos `@dataclass`, `msgspec.Struct` o Pydantic:

```python
from asyncio import sleep
from dataclasses import asdict, dataclass

from holonode import Worker


@dataclass
class ImageResizeParams:
    image_url: str
    width: int = 800
    height: int = 600
    format: str = "webp"


@dataclass
class ImageResizeResult:
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
    """Manejador de redimensionamiento de imagen. params se valida contra ImageResizeParams."""
    task_id = kwargs.get("task_id")
    print(f"[{task_id}] Redimensionando {params.image_url} a {params.width}x{params.height}")

    await sleep(0.5)

    return {
        "status": "success",
        "data": asdict(
            ImageResizeResult(
                processed_url=f"{params.image_url}_resized.{params.format}",
                original_size_kb=1024.0,
                compressed_size_kb=312.5,
            )
        ),
    }


if __name__ == "__main__":
    worker.run()
```

---

## 3. Cancelación cooperativa para tareas de larga duración

Para tareas intensivas en cómputo, consulte periódicamente si el orquestador ha solicitado cancelar la tarea:

```python
@worker.skill("video_transcode")
async def handle_transcode(params: dict, **kwargs) -> dict:
    task_id = kwargs["task_id"]

    for chunk_idx in range(100):
        if await worker.check_for_cancellation(task_id):
            print(f"Cancelación solicitada para {task_id}. Liberando recursos...")
            return {"status": "cancelled", "message": f"Detenido en el fragmento {chunk_idx}"}

        await asyncio.sleep(0.1)

    return {"status": "success", "data": {"transcoded_chunks": 100}}
```

---

## 4. Configuración local vía `.env`

```dotenv
# Identidad del Worker
WORKER_ID=local-image-worker-01
WORKER_TYPE=image-processor

# Dirección del Orquestador
ORCHESTRATOR_URL=http://127.0.0.1:8080

# Token de autenticación
WORKER_TOKEN=secure-worker-token

# Modo WebSocket para cancelación instantánea
ENABLE_WEBSOCKET=true
POLL_INTERVAL=1.0

# Concurrencia
MAX_CONCURRENT_TASKS=4
```

---

## 5. Pruebas unitarias sin un Orquestador activo

Pruebe sus habilidades en `pytest` directamente:

```python
from pytest import mark

from my_worker import ImageResizeParams, handle_resize


@mark.asyncio
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

## 6. Ejecución conjunta

**Terminal 1 (Orquestador):**
```bash
python -m holarchy run --port 8080
```

**Terminal 2 (Worker):**
```bash
python my_worker.py
```

El worker registrará sus habilidades, haciéndolas visibles de inmediato en `GET /api/v1/skills` y en la interfaz interactiva `http://127.0.0.1:8080/docs`.
