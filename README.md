**EN** | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/README.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/README.md)

# Holarchy Orchestrator

[![License: MPL 2.0](https://img.shields.io/badge/License-MPL%202.0-brightgreen.svg)](https://opensource.org/licenses/MPL-2.0)
[![PyPI Version](https://img.shields.io/pypi/v/holarchy.svg)](https://pypi.org/project/holarchy/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)

**Holarchy** is a high-performance, state-machine based orchestrator for long-running AI workflows and distributed tasks. It serves as the core of a **Holarchical Logic Network (HLN)**, coordinating **Holons** (workers) via the **RXON** protocol.

## 🚀 Key Features

- **Modern Type-Safe FSM**: Declarative `@bp.start`, `@bp.step`, `@bp.decide`, `@bp.end` decorators, `StatesGroup`, `State`, and native `@dataclass` / `msgspec.Struct` models (with transparent duck-typing for Pydantic).
- **5 Clean Storage Zones**: Explicit domain boundaries separating `input`, `steps`, `history`, `meta`, and `output`.
- **Advisory AI Routing & Deterministic Replay**: Host-Owned Choice and fail-open routing with auditable `ExecutionReceipt` and offline drift evaluation CLI (`holarchy replay evaluate`).
- **Auto-Generated OpenAPI 3.1 & Branded Docs**: Machine-readable specification at `/openapi.json` and custom dark-mode test harness UI at `/docs`.
- **4-Tier In-Memory Caching & Memoization**: Sub-millisecond serving with thread-safe LRU/FIFO schema cache in `rxon`, spatial DAG topological caching in `Blueprint`, pre-serialized OpenAPI 3.1 JSON bytes and pre-rendered docs HTML in `OrchestratorEngine` with automatic revision-based invalidation.
- **Zero-Trust Incident Evidence Cards**: Instant diagnostic post-mortems via `GET /jobs/{id}/evidence?format=md` with automated root cause classification.
- **High-Performance**: **ZSET-based** queue indexing, **Work Stealing** mechanism (Lua), and atomic state transitions.
- **Zero Trust Security & Policy Enforcement**: Full `SecurityContext` implementation, cryptographic HMAC-SHA256 task signing (`sig`) via `ORCHESTRATOR_SECRET_KEY`, identity chain verification, and granular skill execution policies (`allowed_skills`).
- **Human-in-the-Loop Scoped Approval**: Secure single-use approval tokens (`approval_token`) for external approval webhooks (Email, Slack, Telegram) without exposing master client tokens.
- **Atomic CAS Watcher & Concurrency Safety**: CAS-based atomic state transitions (`update_job_state_atomic`) protecting against race conditions and guarding terminal states against timeout overwrites.
- **Strict Production Configuration**: Fail-safe startup validation in production (`ENVIRONMENT=production`), blocking execution if insecure default tokens or missing secrets are detected.
- **Holarchy Depth Guard**: Configurable limit (`MAX_HOLARCHY_DEPTH`) to prevent infinite recursion in sub-blueprints with automatic process quarantine.
- **Middleware Infrastructure**: Flexible `MiddlewareChain` for intercepting handlers, worker results, and outbound tasks.
- **D-DNA Crypto-Audit**: CLI verification tools (`holarchy.cli.audit`) ensuring tamper-proof event history integrity.
- **Data Protection**: **Envelope Encryption** for tokens in Redis, strict client isolation, and Replay Protection.
- **File Management**: High-performance Async S3 streaming via the `obstore` library.
- **Observability**: **End-to-End** distributed tracing with **OpenTelemetry**, spatial DAG graph visualization (`/dag`), and real-time metrics.

This document serves as a comprehensive guide for developers looking to build pipelines (blueprints) and embed the Orchestrator into their applications.

## Table of Contents

- [Core Architecture: Orchestrator, Blueprints, and Workers](#core-architecture-orchestrator-blueprints-and-workers)
- [Installation](#installation)
- [Quick Start: Usage as a Library](#quick-start-usage-as-a-library)
- [Key Concepts: JobContext and Actions](#key-concepts-jobcontext-and-actions)
- [Blueprint Cookbook: Key Features](#blueprint-cookbook-key-features)
  - [Conditional Transitions](#conditional-transitions)
  - [Delegating Tasks to Workers (dispatch_task)](#delegating-tasks-to-workers-dispatch_task)
  - [Parallel Execution and Aggregation (Fan-out/Fan-in)](#parallel-execution-and-aggregation-fan-outfan-in)
  - [Dependency Injection (DataStore)](#dependency-injection-datastore)
  - [Native Scheduler](#native-scheduler)
  - [S3 Payload Offloading](#s3-payload-offloading)
  - [Webhook Notifications](#webhook-notifications)
- [Production Configuration](#production-configuration)
  - [Fault Tolerance](#fault-tolerance)
  - [Storage Backend](#storage-backend)
  - [Observability](#observability)
- [Contributor Guide](#contributor-guide)
  - [Setup Environment](#setup-environment)
  - [Running Tests](#running-tests)

## Core Architecture: Orchestrator, Blueprints, and Workers

Holarchy decouples process orchestration from distributed computational execution across three primary components:

- **Orchestrator (`OrchestratorEngine`)**: Central coordinator maintaining persistent job states, resolving routing decisions, validating schemas, handling retries, and dispatching work over Redis streams.
- **Blueprints (`Blueprint`)**: Declarative state machines defining execution graphs, transition policies, data aggregation strategies, and handler routines for business workflows.
- **Workers (`Worker`)**: Autonomous execution nodes connecting to the orchestrator via reverse polling over HTTP. Workers register supported capabilities, pull assigned tasks, execute compute-intensive or domain-specific logic, and report results back.

Under the Holarchical Logic Network (HLN) architecture, orchestrators handle workflow state management while workers provide standardized execution wrappers. Through recursive composition, an orchestrator instance can execute behind a worker interface, enabling nested multi-tier hierarchical clusters.

## Ecosystem

Holarchy is part of a larger ecosystem:

- **[RXON Protocol](https://github.com/madgagarin/rxon)**: Shared lightweight reverse-connection protocol powering inter-node communication across the HLN ecosystem.
- **[Holonode SDK](https://github.com/madgagarin/holonode)**: The official Python SDK for building workers that connect to this engine.
- **[HLN (Holarchical Logic Network)](https://github.com/madgagarin/hln)**: The architectural pattern, manifesto, and design specification for self-similar holarchies.
- **[Full Example](https://github.com/madgagarin/holarchy-full-example)**: A complete reference project demonstrating the engine and workers in action.

## Installation

- **Install the core engine only:**

  ```bash
  pip install holarchy
  ```

- **Install with Redis support (recommended for production):**

  ```bash
  pip install "holarchy[redis]"
  ```

- **Install with history storage support (SQLite, PostgreSQL):**

  ```bash
  pip install "holarchy[history]"
  ```

- **Install with telemetry support (OpenTelemetry):**

  ```bash
  pip install "holarchy[telemetry]"
  ```

- **Install with S3 support (Payload Offloading):**

  ```bash
  pip install "holarchy[s3]"
  ```

- **Install all dependencies, including for testing:**
  ```bash
  pip install "holarchy[all,test]"
  ```

## Job Statuses

Holarchy jobs move through various states:

| Status                 | Type         | Description                                                |
| :--------------------- | :----------- | :--------------------------------------------------------- |
| `pending`              | Intermediate | Job created, waiting for queue.                            |
| `running`              | Intermediate | Active execution of blueprint logic or tasks.              |
| `waiting_for_worker`   | Intermediate | Task dispatched, waiting for a worker to pick it up.       |
| `waiting_for_human`    | Intermediate | Paused, awaiting manual approval via webhook.              |
| `waiting_for_parallel` | Intermediate | Waiting for completion of all parallel sub-tasks.          |
| `finished`             | **Terminal** | Successfully completed. **Result is visible.**             |
| `failed`               | **Terminal** | Logic or worker failure. **Result is visible.**            |
| `cancelled`            | **Terminal** | Manually cancelled by user or system.                      |
| `error`                | **Terminal** | Critical system or infrastructure error.                   |
| `quarantined`          | **Terminal** | Flagged for manual review (e.g., data contract violation). |

### Modern Observability

Holarchy is built with deep observability in mind using the **OpenTelemetry** standard. It provides:

- **Distributed Tracing**: Track requests across the entire HLN network (Orchestrator ↔ Worker).
- **Real-time Metrics**: Monitor queue lengths, worker health, and job latencies.
- **OTLP Native**: Push telemetry data directly to Jaeger, Prometheus, or Grafana.

To enable telemetry support during installation:

```bash
pip install "holarchy[telemetry]"
```

See the [**Observability Guide**](https://github.com/madgagarin/holarchy/blob/main/docs/observability.md) for configuration details.

## Quick Start: Usage as a Library

You can easily integrate and run the orchestrator engine within your own application.

```python
# my_app.py
from asyncio import Event, run
from dataclasses import dataclass

from holarchy import Blueprint, OrchestratorEngine
from holarchy.config import Config
from holarchy.context import ActionFactory
from holarchy.fsm import State, StatesGroup
from holarchy.storage import MemoryStorage


@dataclass
class OrderInput:
    order_id: int
    amount: float


class OrderFlow(StatesGroup):
    start = State()
    finalize = State()


storage = MemoryStorage()
config = Config()
config.CLIENT_TOKEN = "my-secret-client-token"
config.GLOBAL_WORKER_TOKEN = "my-secret-worker-token"

bp = Blueprint(name="order_pipeline", api_version="v1", api_endpoint="/jobs/order")


@bp.start(OrderFlow.start)
async def process_start(data: OrderInput, actions: ActionFactory) -> State:
    """The initial state for each new job."""
    print(f"Order #{data.order_id} received, amount: {data.amount}")
    return OrderFlow.finalize


@bp.end(OrderFlow.finalize)
async def process_finalize(context) -> dict[str, str]:
    """The final state. The pipeline ends here."""
    print(f"Job {context.job_id} | Complete.")
    return {"status": "completed"}


engine = OrchestratorEngine(storage, config)
engine.register_blueprint(bp)


async def main() -> None:
    await engine.start()
    try:
        await Event().wait()
    finally:
        await engine.stop()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        print("\nStopping server.")
```

### Engine Lifecycle: `run()` vs. `start()`

The `OrchestratorEngine` offers two ways to start the server:

- **`engine.run()`**: This is a simple, **blocking** method. It's useful for dedicated scripts where the orchestrator is the only major component. It handles starting and stopping the server for you. You should not use this inside an `async def` function that is part of a larger application, as it can conflict with the event loop.

- **`await engine.start()`** and **`await engine.stop()`**: These are the non-blocking methods for integrating the engine into a larger `asyncio` application.
  - `start()` sets up and starts the web server in the background.
  - `stop()` gracefully shuts down the server and cleans up resources.
    The "Quick Start" example above demonstrates the correct way to use these methods.

## Handler Arguments & Dependency Injection

State handlers are the core of your workflow logic. Holarchy provides a powerful dependency injection system to make writing handlers clean and efficient.

Instead of receiving a single, large `context` object, your handler can ask for exactly what it needs as function arguments. The engine will automatically provide them.

> **Tip:** In v1.0.0, use declarative `@bp.start(State)`, `@bp.step(State, condition=...)`, and `@bp.end(State)`. The legacy `@bp.handler(state_name)` decorator remains fully supported for backward compatibility.

### 5 Clean Storage Zones (Pure Data Architecture)

Holarchy v1.0.0 replaces monolithic state blobs with 5 cleanly partitioned storage zones:
- **`input`** (dict or typed model): The immutable business data the job was started with.
- **`output`** (Any): The final business outcome returned by the `@bp.end` handler.
- **`steps`** (dict): Intermediate results returned by preceding steps (`steps[step_name]`) and worker task outcomes.
- **`history`** (list): Chronological execution audit events with latencies and timestamps.
- **`params`** (dict): Client plan parameters and static configuration.

*(Clean Slate Architecture: Zero legacy aliases or backward compatibility bridges; the 5 storage zones are the sole canonical memory model).*

The following arguments can be injected by name, type, or decorator:

- **By Type:** Any Pydantic v2 `BaseModel`, `msgspec.Struct`, or `@dataclass` matching the input or a previous step's return value.
- **From the core job context:**
  - `ctx` (Context): The full runtime context with `ctx.actions`, `ctx.input`, `ctx.steps`, and `ctx.decide()`.
  - `actions` (ActionFactory): Control object for transitions and task dispatch.
  - `input` (dict): The job's input payload.
  - `job_id` (str): The ID of the current job.
  - `task_files`: Access to S3/local workspace files for the job.
- **From HTTP Headers:**
  - `Annotated[T, Header("Header-Name")]`: Automatically extracts and converts HTTP request headers.

### Example: Dependency Injection

This is the recommended modern way to write handlers:

```python
@bp.step(OrderFlow.process)
async def publish_video(
    job_id: str,
    output_path: str,  # Injected by name or from preceding steps
    ctx: Context,
):
    print(f"Job {job_id}: Publishing video at {output_path}.")
    ctx.actions.go_to(OrderFlow.complete)
```

Available arguments for injection:

- `actions`: The `ActionFactory` (required for control).
- `job_id`, `current_state`, `input`, `steps`, `output`, `history`, `params`: Core job fields.
- `data_stores`: Access to shared memory/database stores.
- `task_files`: Access to S3/Local files for the job.
- `aggregation_results`: Results from parallel tasks.
- `client`: Client configuration and plan info.
- `tracing_context`: Distributed tracing metadata.

## Key Concepts: JobContext and Actions

### High Performance Architecture

Holarchy is engineered for high-load environments with thousands of concurrent workers.

- **Standardized Holon Matching (RXON)**:
  - **Unified Matching**: Migrated to the formalized `rxon` matching logic. All resource checks (CPU, RAM, GPU, custom properties) are now strictly governed by the HLN protocol standard.
  - **Smart Numeric Comparison**: Automatically performs **GE (Greater or Equal)** checks for numbers (e.g., minimum VRAM or RAM), ensuring flexible but reliable dispatching.
  - **Hot Cache & Skill Awareness**: Prioritizes workers that already have specific AI models loaded.
  - **Overflow Strategy**: Automatically spills load to more expensive workers if cheaper ones are saturated.
  - **Work Stealing**: Idle workers can atomically steal tasks from heavily loaded colleagues at O(1) speed.
- **Self-Regulating Reputation**:
  - **Penalty System**: Immediate reputation slashing for contract violations (-0.2) or permanent task failures (-0.05).
  - **Recovery Loop**: Small reputation rewards for every successful task completion (+0.001), encouraging consistent quality.
- **Contract-First & Zero Trust**:
  - **Identity Chain Verification**: Validates the entire bubbling path for events in deep holarchies.
  - **mTLS & STS**: Mutual authentication and short-lived token rotation for secure communication.
  - **Signature Support**: Ready for protocol-level digital signatures for end-to-end task verification.
  - **Atomic State Management**: Uses Redis transactions and Lua scripts to ensure consistency under extreme parallel loads.

## Blueprint Cookbook: Key Features

### 1. Conditional Transitions

Pass conditions directly to `@bp.step()` (or `@bp.handler()`) to create conditional logic branches. Conditions are declarative **`FastF` expressions** from the `fast-magic-filter` library, resolving through the 4-tier `StepScope` cascade (current scope $\rightarrow$ `input` $\rightarrow$ `steps`).

```python
from holarchy import Blueprint, Context, F, State, StatesGroup


class Flow(StatesGroup):
    decision = State()
    urgent_processing = State()
    priority_lane = State()
    normal_processing = State()


# Direct property matching on input payload via StepScope
@bp.step(Flow.decision, condition=F.type == "urgent")
async def handle_urgent(ctx: Context):
    ctx.actions.go_to(Flow.urgent_processing)


# Compound condition with logical AND
@bp.step(Flow.decision, condition=(F.priority >= 8) & (F.active == True))
async def handle_priority(ctx: Context):
    ctx.actions.go_to(Flow.priority_lane)


# Fallback step if no prior condition matches
@bp.step(Flow.decision)
async def handle_default(ctx: Context):
    ctx.actions.go_to(Flow.normal_processing)
```

**Supported condition syntax:**

| Pattern                   | Example                             |
| ------------------------- | ----------------------------------- |
| Attribute access          | `F.status == "done"`                |
| Dict/item access          | `F.data["key"] == 42`               |
| Logical AND / OR / NOT    | `(F.x > 0) & (F.y < 10)`, `~F.flag` |
| Comparison operators      | `F.score >= 80`, `F.retries < 3`    |
| `in` / `not_in`           | `F.role.in_(["admin", "mod"])`      |
| Regexp (uses `re.search`) | `F.text.regexp(r"^done")`           |
| List aggregators          | `(F.tags[...] == "vip").any()`      |
| Custom function           | `F.value.func(my_predicate)`        |

> **Note:** Missing attributes and `None` intermediate values are handled safely — they return `False` instead of raising `AttributeError`. This is a deliberate improvement over `magic-filter`.

### 2. Delegating Tasks to Workers (`dispatch_task`)

This is the primary function for delegating work. The orchestrator will queue the task and wait for a worker to pick it up and return a result.

```python
@bp.step
async def transcode_video(input: dict, actions: ActionFactory):
    actions.dispatch_task(
        task_type="video_transcoding",
        params={"input_path": input.get("path")},
        # Define the next step based on the worker's response status
        transitions={
            "success": "publish_video",
            "failure": "transcoding_failed",
            "needs_review": "manual_review",  # Example of a custom status
        },
    )
```

If the worker returns a status not listed in `transitions`, the job will automatically transition to a failed state.

### 3. Parallel Execution and Aggregation (Fan-out/Fan-in)

Run multiple tasks simultaneously and gather their results. **Isolated branch state** prevents race conditions when multiple branches report results simultaneously.

```python
# 1. Fan-out: Dispatch multiple tasks to be aggregated into a single state
@bp.step
async def process_files(input: dict, actions: ActionFactory):
    tasks_to_dispatch = [{"task_type": "file_analysis", "params": {"file": file}} for file in input.get("files", [])]
    # Use dispatch_parallel to send all tasks at once.
    # All successful tasks will implicitly lead to the 'aggregate_into' state.
    actions.dispatch_parallel(tasks=tasks_to_dispatch, aggregate_into="aggregate_results")


# 2. Fan-in: Collect results using the @aggregator decorator
@bp.aggregator
async def aggregate_results(aggregation_results, steps, actions):
    # This handler will only execute AFTER ALL tasks
    # dispatched by dispatch_parallel are complete.

    # aggregation_results is a dictionary of {task_id: result_dict}
    summary = [res.get("data") for res in aggregation_results.values()]
    steps["summary"] = summary
    actions.go_to("processing_complete")
```

### 4. Dependency Injection (DataStore)

Provide handlers with access to external resources (like a cache or DB client).

```python
from redis.asyncio import Redis

# 1. Initialize and register your DataStore
redis_client = Redis(decode_responses=True)
bp = Blueprint("blueprint_with_datastore", data_stores={"cache": redis_client})


# 2. Use it in a handler via dependency injection
@bp.step
async def get_from_cache(data_stores):
    # Access the redis_client by the name "cache"
    user_data = await data_stores.cache.get("user:123")
    print(f"User from cache: {user_data}")
```

### 5. Native Scheduler

Holarchy includes a built-in distributed scheduler. It allows you to trigger blueprints periodically (interval, daily, weekly, monthly) without external tools like cron.

- **Configuration:** Defined in `schedules.toml`.
- **Timezone Aware:** Supports global timezone configuration (e.g., `TZ="Europe/Moscow"`).
- **Expiration Support:** Supports `dispatch_timeout` and `result_timeout` to ensure tasks don't run or complete too late.
- **Distributed Locking:** Safe to run with multiple orchestrator instances; jobs are guaranteed to run only once per interval using distributed locks (Redis/Memory).

```toml
# schedules.toml example
[nightly_backup]
blueprint = "backup_flow"
daily_at = "02:00"
dispatch_timeout = 60 # Fail if no worker picks it up within 1 minute
```

### 6. Webhook Notifications

The orchestrator can send asynchronous notifications to an external system when a job completes, fails, or is quarantined. This eliminates the need for clients to constantly poll the API for status updates.

### 7. S3 Payload Offloading

Orchestrator provides first-class support for handling large files via S3-compatible storage, powered by the high-performance `obstore` library (Rust bindings).

- **Memory Safe (Streaming)**: Uses streaming for uploads and downloads, allowing processing of files larger than available RAM without OOM errors.
- **Managed Mode**: The Orchestrator manages file lifecycle (automatic cleanup of S3 objects and local temporary files on job completion).
- **Dependency Injection**: Use the `task_files` argument in your handlers to easily read/write data.
- **Directory Support**: Supports recursive download and upload of entire directories.

```python
@bp.step
async def process_data(task_files, actions):
    # Streaming download of a large file
    local_path = await task_files.download("large_dataset.csv")

    # ... process data ...

    # Upload results
    await task_files.write_json("results.json", {"status": "done"})

    actions.go_to("finished")
```


## API Groups & Versioning

All external API endpoints are strictly versioned and prefixed with `/api/v1/`.

- **Events:**
  - `job_finished`: The job reached a final success state.
  - `job_failed`: The job failed (e.g., due to an error or invalid input).
  - `job_quarantined`: The job was moved to quarantine after repeated failures.

**Example Request:**

```http
POST /api/v1/jobs/my_flow
{
    "input": {
        "video_url": "..."
    },
    "webhook_url": "https://my-app.com/webhooks/holarchy",
    "dispatch_timeout": 30,
    "result_timeout": 120
}
```

**Example Webhook Payload:**

```json
{
  "event": "job_finished",
  "job_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "finished",
  "result": {
    "output_path": "/videos/result.mp4"
  },
  "error": null
}
```

## Production Configuration

The orchestrator's behavior can be configured through environment variables. Additionally, any configuration parameter loaded from environment variables can be programmatically overridden in your application code after the `Config` object has been initialized.

**Important:** The system employs **strict validation** for configuration files (`clients.toml`, `workers.toml`) at startup.

### Configuration Files

- **`clients.toml`**: Defines API clients, their tokens, plans, and quotas.
- **`workers.toml`**: Defines individual tokens for workers to enhance security. Supports **fnmatch patterns** (e.g., `cpu-worker-*`) for dynamic scaling.
- **`schedules.toml`**: Defines periodic tasks (CRON-like) for the native scheduler.

For detailed specifications and examples, please refer to the [**Configuration Guide**](https://github.com/madgagarin/holarchy/blob/main/docs/configuration.md).

### Fault Tolerance

The orchestrator handles failures based on the `error.code` field in a worker's response.

- **TRANSIENT_ERROR**: Temporary errors (network, timeouts). Automatic retries.
- **PERMANENT_ERROR**: Permanent errors (logic, security). Immediate quarantine.
- **INVALID_INPUT_ERROR**: Data errors. Job fails immediately.

### Security & Stability Guardrails

- **Exponential Backoff:** Core loops (`JobExecutor`, `Watcher`) automatically implement exponential backoff on infrastructure failures.
- **Job Hijacking Protection:** Only the assigned worker can submit task results.
- **Infinite Loop Protection:** `MAX_TRANSITIONS_PER_JOB` (default 100) terminates cycling blueprints.
- **Stale Result Protection:** Ignores results for timed-out or re-dispatched tasks.

### Concurrency & Performance

- **`EXECUTOR_MAX_CONCURRENT_JOBS`**: Limits internal job handlers (default: `1000`).
- **`WATCHER_LIMIT`**: Number of timeouts checked per cycle (default: `500`).
- **`DISPATCHER_MAX_CANDIDATES`**: Limits worker compliance checks (default: `50`).

### High Availability & Distributed Locking

Multiple Orchestrator instances can run behind a load balancer.

- **Stateless API:** All state is persisted in Redis.
- **Distributed Locking:** `Watcher` and `ReputationCalculator` use Redis `SET NX` locks.

### Logging & Observability

- **Structured JSON Logging**: Easy to parse and index.
- **Asynchronous processing**: Non-blocking `QueueHandler` prevents event loop blocking.
- **Deep Observability**: OpenTelemetry-based tracing and metrics (via OTLP).

### Security & Data Protection

- **Zero Trust Security**: Mutual authentication (mTLS) and mandatory **HMAC SHA256** message signing for Redis state integrity and worker identity verification.
- **Granular Skill Policy (`policy`)**: Restrict permitted worker skills for a job via `policy: {"allowed_skills": ["skill_a", "skill_b"]}`.
- **Holarchy Depth Guard (`MAX_HOLARCHY_DEPTH`)**: Configurable limit (default 10) preventing infinite recursion in sub-blueprints with automatic process quarantine.
- **Middleware Infrastructure (`MiddlewareChain`)**: Intercept handler requests/responses, outbound tasks, and inbound worker events.
- **D-DNA Crypto-Audit (`holarchy.cli.audit`)**: Verify event history log integrity via cryptographic hash chains.
- **Replay Protection**: Strict validation of `timestamp` with a 60-second window.
- **Identity Chain Integrity**: Mathematical verification of identity chains in holarchies (signature covers the entire signal path).
- **Envelope Encryption**: When `REDIS_ENCRYPTION_KEY` is provided, worker tokens are stored encrypted in Redis (AES-GCM).
- **Auth Modes**: Support for `WORKER_AUTH_MODE` (`mixed`, `mtls-only`, `token-only`).
- **Strict Client Isolation**: Jobs are strictly tied to the `client_token`. A client can only access, manage, or download files for jobs they created.
- **API Detail Policy**: By default, API returns minimal fields for security. Full detail enabled via `DETAILED_API_RESPONSES="true"`.

#### Skill Policy Example (`policy`):

```http
POST /api/v1/jobs/my_flow
{
    "input": {"input_val": 42},
    "policy": {
        "allowed_skills": ["data_extractor", "pdf_generator"]
    },
    "max_transitions": 50
}
```

#### Custom Middleware Example (`MiddlewareChain`):

```python
from holarchy.middleware import BaseMiddleware


class AuditLogMiddleware(BaseMiddleware):
    async def process_outbound_task(self, context, task_payload):
        task_payload["audit_tag"] = "monitored"
        return task_payload


engine.middleware_chain.add(AuditLogMiddleware())
```

#### D-DNA Crypto-Audit Verification Example (`holarchy.cli.audit`):

```python
from holarchy.cli.audit import verify_d_dna_integrity

is_valid, error = verify_d_dna_integrity(job_history_events, audit_salt="my_secret_salt")
if not is_valid:
    print(f"History tampering detected: {error}")
```

#### Deterministic Replay CLI (`holarchy replay evaluate`):

Evaluate historical advisory execution receipts offline against updated blueprint routing logic to catch decision drift before production deployment:

```bash
# Evaluate historical execution receipts
holarchy replay evaluate --app my_module:bp --cases .holarchy/replay/cases.jsonl

# Enforce zero drift in CI pipelines (exits with code 1 if drift detected)
holarchy replay evaluate --app my_module:bp --cases .holarchy/replay/cases.jsonl --strict
```

### Rate Limiting

Granular, context-aware Redis-based rate limiter (Heartbeats: 120/min, Polling: 60/min, General: 100/min).

> **Note:** Workers receive a standard **`Retry-After`** header on block to manage smart backoff strategies.

### Dynamic Blueprint Loading

Automatic loading from `BLUEPRINTS_DIR`. Scans, imports, and registers `.py` files on startup.

### Pure Holon Mode

Disable public API with `ENABLE_CLIENT_API="false"` to only accept tasks via RXON from parent holons.

## Contributor Guide

### Setup Environment

```bash
pip install -e ../rxon
pip install -e ".[all,test]"
```

### Running Tests

```bash
pytest tests/
```

### Interactive API Documentation

Available at `/_public/docs`. Features dynamic blueprint documentation and interactive testing.

## Detailed Documentation

- [**Architecture Guide**](https://github.com/madgagarin/holarchy/blob/main/docs/architecture.md)
- [**API Reference**](https://github.com/madgagarin/holarchy/blob/main/docs/api_reference.md)
- [**Configuration Guide**](https://github.com/madgagarin/holarchy/blob/main/docs/configuration.md)
- [**Observability Guide**](https://github.com/madgagarin/holarchy/blob/main/docs/observability.md)
- [**Tracing Protocol**](https://github.com/madgagarin/holarchy/blob/main/docs/observability_protocol.md)
- [**Deployment Guide**](https://github.com/madgagarin/holarchy/blob/main/docs/deployment.md)
- [**Cookbook**](https://github.com/madgagarin/holarchy/blob/main/docs/cookbook/README.md)
