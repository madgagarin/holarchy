[EN](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/creating_worker.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/creating_worker.md)

# Libro de recetas: Creación de un Worker

Los workers son ejecutores independientes encargados de realizar las tareas de dominio encomendadas por el Orquestador.

---

## 1. Instalación

```bash
pip install "holonode[pydantic,s3]"
```

---

## 2. Definición de habilidades con modelos de dominio

Declare sus habilidades con el decorador `@worker.skill`. Se admiten `@dataclass`, `msgspec.Struct` o modelos Pydantic:

```python
from asyncio import sleep
from dataclasses import asdict, dataclass

from holonode import Worker


@dataclass
class InventoryCheckParams:
    sku: str
    quantity: int


@dataclass
class InventoryCheckResult:
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
    task_id = kwargs.get("task_id")
    print(f"Comprobando SKU {params.sku} para la tarea {task_id}")

    available = 42
    in_stock = available >= params.quantity

    return {
        "status": "success",
        "data": asdict(
            InventoryCheckResult(
                in_stock=in_stock,
                available_quantity=available,
                warehouse_code="WH-US-EAST",
            )
        ),
    }
```

---

## 3. Cancelación cooperativa

```python
@worker.skill("render_video", risk="high", permissions=["media:render"])
async def render_video(params: dict, **kwargs) -> dict:
    task_id = kwargs["task_id"]

    for frame in range(1000):
        if await worker.check_for_cancellation(task_id):
            print(f"Cancelación recibida para {task_id}. Limpiando...")
            return {"status": "cancelled", "message": "Render detenido por el orquestador"}

        await sleep(0.01)

    return {"status": "success", "data": {"frames_rendered": 1000}}
```

---

## 4. Configuración vía `.env`

```dotenv
WORKER_ID=inventory-worker-01
WORKER_TYPE=inventory-service
ORCHESTRATOR_URL=http://localhost:8080
WORKER_TOKEN=secure-worker-token
ENABLE_WEBSOCKET=true
POLL_INTERVAL=1.0
MAX_CONCURRENT_TASKS=8
```

---

## 5. Ejecución del Worker

```python
if __name__ == "__main__":
    worker.run()
```

> Para pruebas locales detalladas sin un orquestador activo, consulte el [Libro de recetas: Desarrollo local de workers](local_worker_development.md).
