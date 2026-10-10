**EN** | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/local_worker_development.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/local_worker_development.md)

# Cookbook: Local Worker Development & Testing

Workers in the Holarchy ecosystem are independent execution agents that consume tasks dispatched by the Orchestrator, execute domain code, and report results back.

This recipe guides you through setting up, developing, testing, and debugging a worker locally using the `holonode` SDK.

---

## 1. Quick Setup & Installation

Install `holonode` with optional Pydantic and S3 extensions:

```bash
# Recommended installation with Pydantic auto-validation and S3 file support
pip install "holonode[pydantic,s3]"
```

---

## 2. Defining Strongly Typed Worker Skills

A worker registers one or more "skills" using the `@worker.skill` decorator. Use standard `@dataclass`, `msgspec.Struct`, or Pydantic models for type safety and automatic contract generation.

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
    """Processes image resizing. `params` is auto-validated into ImageResizeParams."""
    task_id = kwargs.get("task_id")
    print(f"[{task_id}] Resizing {params.image_url} to {params.width}x{params.height}")

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

## 3. Cooperative Cancellation for Long-Running Tasks

For compute-heavy or long-running tasks, regularly check if the orchestrator cancelled or timed out the task:

```python
@worker.skill("video_transcode")
async def handle_transcode(params: dict, **kwargs) -> dict:
    task_id = kwargs["task_id"]

    for chunk_idx in range(100):
        # 1. Non-blocking cancellation check
        if await worker.check_for_cancellation(task_id):
            print(f"Cancellation requested for {task_id}. Cleaning up temporary files...")
            return {"status": "cancelled", "message": f"Halted at chunk {chunk_idx}"}

        # 2. Transcode chunk
        await asyncio.sleep(0.1)

    return {"status": "success", "data": {"transcoded_chunks": 100}}
```

---

## 4. Local Configuration via `.env`

Configure worker settings locally without hardcoding tokens in code:

```dotenv
# Worker Identification
WORKER_ID=local-image-worker-01
WORKER_TYPE=image-processor

# Orchestrator Target
ORCHESTRATOR_URL=http://127.0.0.1:8080

# Authentication (must match orchestrator's GLOBAL_WORKER_TOKEN or registered worker token)
WORKER_TOKEN=secure-worker-token

# Communication Mode: WebSocket provides instant cancellation notifications
ENABLE_WEBSOCKET=true
POLL_INTERVAL=1.0

# Concurrency
MAX_CONCURRENT_TASKS=4
```

---

## 5. Unit Testing Skills Without a Running Orchestrator

Test your worker skills locally in `pytest` by invoking the handler function directly or using `Worker.execute_task_locally`:

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

## 6. Running Orchestrator & Worker in Pair

Run the orchestrator and worker in separate terminal windows:

**Terminal 1 (Orchestrator):**
```bash
python -m holarchy run --port 8080
```

**Terminal 2 (Worker):**
```bash
python my_worker.py
```

The worker registers its skills with the orchestrator, and you will see the skills appear dynamically in `GET /api/v1/skills` and in the interactive API documentation at `http://127.0.0.1:8080/docs`.
