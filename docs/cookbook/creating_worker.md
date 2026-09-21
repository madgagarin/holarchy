**EN** | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/creating_worker.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/creating_worker.md)

# Cookbook: Creating a Worker

Workers are independent executors performing domain tasks dispatched by the Orchestrator. This guide shows how to build and configure a worker using the `holonode` SDK.

---

## 1. Installation

```bash
# Recommended: Includes Pydantic schema validation and S3 file streaming
pip install "holonode[pydantic,s3]"
```

---

## 2. Defining Skills with Pydantic & Security Metadata

Declare your skills using the `@worker.skill` decorator with risk levels and permissions:

```python
import asyncio
from pydantic import BaseModel, Field
from holonode import Worker


class InventoryCheckParams(BaseModel):
    sku: str = Field(..., description="Stock Keeping Unit identifier")
    quantity: int = Field(..., gt=0, description="Quantity requested")


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
    """The SDK validates incoming task parameters against InventoryCheckParams."""
    task_id = kwargs.get("task_id")
    print(f"Checking SKU {params.sku} for task {task_id}")

    # Domain logic
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

## 3. Cooperative Cancellation for Long Tasks

For tasks that take several seconds or minutes to complete, poll `check_for_cancellation` periodically to abort work gracefully if the client or orchestrator cancels the job:

```python
@worker.skill("render_video", risk="high", permissions=["media:render"])
async def render_video(params: dict, **kwargs) -> dict:
    task_id = kwargs["task_id"]

    for frame in range(1000):
        if await worker.check_for_cancellation(task_id):
            print(f"Cancellation requested for task {task_id}. Cleaning up...")
            return {"status": "cancelled", "message": "Render halted by orchestrator"}

        await asyncio.sleep(0.01)

    return {"status": "success", "data": {"frames_rendered": 1000}}
```

---

## 4. Configuration

Configure your worker through environment variables or a `.env` file:

```dotenv
# Worker Identity
WORKER_ID=inventory-worker-01
WORKER_TYPE=inventory-service

# Orchestrator URL
ORCHESTRATOR_URL=http://localhost:8080

# Shared Worker Token
WORKER_TOKEN=secure-worker-token

# Instant cancellation via WebSocket
ENABLE_WEBSOCKET=true
POLL_INTERVAL=1.0

# Concurrency Limit
MAX_CONCURRENT_TASKS=8
```

---

## 5. Running the Worker

```python
if __name__ == "__main__":
    worker.run()
```

When started, the worker connects to the Orchestrator, automatically announces its registered skills, and begins pulling tasks.

> For in-depth testing without a running orchestrator, see the [Local Worker Development](local_worker_development.md) recipe.
