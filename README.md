# Holarchy Orchestrator

Holarchy is a powerful, state-driven engine for managing complex asynchronous workflows in Python. It provides a robust framework for building scalable and resilient applications by separating process logic from execution logic.

This document serves as a comprehensive guide for developers looking to build pipelines (blueprints) and embed the Orchestrator into their applications.

## Table of Contents
- [Core Concept: Orchestrator, Blueprints, and Workers](#core-concept-orchestrator-blueprints-and-workers)
- [Installation](#installation)
- [Quick Start: Usage as a Library](#quick-start-usage-as-a-library)
- [Key Concepts: JobContext and Actions](#key-concepts-jobcontext-and-actions)
- [Blueprint Cookbook: Key Features](#blueprint-cookbook-key-features)
  - [Conditional Transitions (.when())](#conditional-transitions-when)
  - [Delegating Tasks to Workers (dispatch_task)](#delegating-tasks-to-workers-dispatch_task)
  - [Parallel Execution and Aggregation (Fan-out/Fan-in)](#parallel-execution-and-aggregation-fan-outfan-in)
  - [Dependency Injection (DataStore)](#dependency-injection-datastore)
- [Production Configuration](#production-configuration)
  - [Fault Tolerance](#fault-tolerance)
  - [Storage Backend](#storage-backend)
  - [Observability](#observability)
- [Contributor Guide](#contributor-guide)
  - [Setup Environment](#setup-environment)
  - [Running Tests](#running-tests)

## Core Concept: Orchestrator, Blueprints, and Workers

The project is based on a simple yet powerful architectural pattern that separates process logic from execution logic.

*   **Orchestrator (OrchestratorEngine)** — The Director. It manages the entire process from start to finish, tracks state, handles errors, and decides what should happen next. It does not perform business tasks itself.
*   **Blueprints (Blueprint)** — The Script. Each blueprint is a detailed plan (a state machine) for a specific business process. It describes the steps (states) and the rules for transitioning between them.
*   **Workers (Worker)** — The Team of Specialists. These are independent, specialized executors. Each worker knows how to perform a specific set of tasks (e.g., "process video," "send email") and reports back to the Orchestrator.## Installation

*   **Install the core engine only:**
    ```bash
    pip install holarchy
    ```

*   **Install with Redis support (recommended for production):**
    ```bash
    pip install "holarchy[redis]"
    ```

*   **Install with history storage support (SQLite, PostgreSQL):**
    ```bash
    pip install "holarchy[history]"
    ```

*   **Install with telemetry support (Prometheus, OpenTelemetry):**
    ```bash
    pip install "holarchy[telemetry]"
    ```

*   **Install all dependencies, including for testing:**
    ```bash
    pip install "holarchy[all,test]"
    ```
## Quick Start: Usage as a Library

You can easily integrate and run the orchestrator engine within your own application.

```python
# my_app.py
import asyncio
from holarchy import OrchestratorEngine, StateMachineBlueprint
from holarchy.storage import MemoryStorage
from holarchy.config import Config

# 1. Define your pipeline (Blueprint)
my_blueprint = StateMachineBlueprint(
    name="my_first_blueprint",
    api_version="v1",
    api_endpoint="/jobs/my_flow"
)

@my_blueprint.handler_for("start", is_start=True)
async def start_handler(context):
    """The initial state for each new job."""
    print(f"Job {context.job_id} | Start: {context.initial_data}")
    # Tell the orchestrator what to do next
    context.actions.transition_to("end")

@my_blueprint.handler_for("end", is_end=True)
async def end_handler(context):
    """The final state. The pipeline ends here."""
    print(f"Job {context.job_id} | Complete.")

# 2. Configure and run the engine
async def main():
    # Using in-memory storage for this example
    storage = MemoryStorage()
    config = Config() # Loads configuration from environment variables

    engine = OrchestratorEngine(storage, config)
    engine.register_blueprint(my_blueprint)
    
    print("Starting Orchestrator engine...")
    # engine.run() is a blocking call that starts the web server.
    # For integration into an existing asyncio app, use engine.start()
    engine.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopping server.")
```
## Key Concepts: JobContext and Actions

Each state handler receives one argument: `context` (**JobContext**). This object contains all information about the current job and the methods to control the workflow.

*   `context.job_id`: The ID of the current job.
*   `context.initial_data`: The data the job was created with.
*   `context.state_history`: A dictionary for storing and passing data between steps.
*   `context.actions`: An object used to tell the orchestrator what to do next. Only one actions method can be called per handler.
    *   `context.actions.transition_to("next_state")`: Moves the job to a new state.
    *   `context.actions.dispatch_task(...)`: Delegates work to a Worker.## Blueprint Cookbook: Key Features

### 1. Conditional Transitions (`.when()`)

Use `.when()` to create conditional logic branches without `if/else` inside your handler. The first handler whose `.when()` condition evaluates to `True` will be executed.

```python
# Will only run if initial_data had a field "type" with value "urgent"
@my_blueprint.handler_for("decision_step").when("context.initial_data.type == 'urgent'")
async def handle_urgent(context):
    context.actions.transition_to("urgent_processing")

# Default handler for the "decision_step" state if no .when() matches
@my_blueprint.handler_for("decision_step")
async def handle_normal(context):
    context.actions.transition_to("normal_processing")
```

### 2. Delegating Tasks to Workers (`dispatch_task`)

This is the primary function for delegating work. The orchestrator will queue the task and wait for a worker to pick it up and return a result.

```python
@my_blueprint.handler_for("transcode_video")
async def transcode_handler(context):
    context.actions.dispatch_task(
        task_type="video_transcoding",
        params={"input_path": context.initial_data.get("path")},
        # Define the next step based on the worker's response status
        transitions={
            "success": "publish_video",
            "failure": "transcoding_failed",
            "needs_review": "manual_review" # Example of a custom status
        }
    )
```
If the worker returns a status not listed in `transitions`, the job will automatically transition to a failed state.

### 3. Parallel Execution and Aggregation (Fan-out/Fan-in)

Run multiple tasks simultaneously and gather their results.

```python
# 1. Fan-out: Dispatch multiple tasks leading to one aggregation state
@my_blueprint.handler_for("process_files")
async def fan_out_handler(context):
    for file in context.initial_data.get("files", []):
        context.actions.dispatch_task(
            task_type="file_analysis",
            params={"file": file},
            transitions={"success": "aggregate_results"}
        )

# 2. Fan-in: Collect results using the @aggregator_for decorator
@my_blueprint.aggregator_for("aggregate_results")
async def aggregator_handler(context):
    # This handler will only execute AFTER ALL tasks
    # leading to "aggregate_results" are complete.

    all_results = context.aggregation_results
    # all_results is a dictionary of {task_id: result_dict}

    summary = [res.get("data") for res in all_results.values()]
    context.state_history["summary"] = summary
    context.actions.transition_to("processing_complete")
```

### 4. Dependency Injection (DataStore)

Provide handlers with access to external resources (like a cache or DB client).

```python
import redis.asyncio as redis

# 1. Initialize and register your DataStore
redis_client = redis.Redis(decode_responses=True)
bp = StateMachineBlueprint(
    "blueprint_with_datastore",
    data_stores={"cache": redis_client}
)

# 2. Use it in a handler via the context
@bp.handler_for("get_from_cache")
async def cache_handler(context):
    # Access the redis_client by the name "cache"
    user_data = await context.data_stores.cache.get("user:123")
    print(f"User from cache: {user_data}")
```
## Production Configuration

### Fault Tolerance

The orchestrator has built-in mechanisms for handling failures based on the `error.code` field in a worker's response.

*   **TRANSIENT_ERROR**: A temporary error (e.g., network failure, rate limit). The orchestrator will automatically retry the task several times.
*   **PERMANENT_ERROR**: A permanent error (e.g., a corrupted file). The task will be immediately sent to quarantine for manual investigation.
*   **INVALID_INPUT_ERROR**: An error in the input data. The entire pipeline (Job) will be immediately moved to the failed state.

### Storage Backend

By default, the engine uses in-memory storage. For production, you must configure persistent storage via environment variables.

*   **Redis (StorageBackend)**: For storing current job states.
    *   Install:
        ```bash
        pip install "holarchy[redis]"
        ```
    *   Configure:
        ```bash
        export REDIS_HOST=your_redis_host
        ```

*   **PostgreSQL/SQLite (HistoryStorage)**: For archiving completed job history.
    *   Install:
        ```bash
        pip install "holarchy[history]"
        ```
    *   Configure:
        ```bash
        export HISTORY_DATABASE_URI=...
        ```
        *   SQLite: `sqlite:///path/to/history.db`
        *   PostgreSQL: `postgresql://user:pass@host/db`

### Observability

When installed with the telemetry dependency, the system automatically provides:

*   **Prometheus Metrics**: Available at the `/_public/metrics` endpoint.
*   **Distributed Tracing**: Compatible with OpenTelemetry and systems like Jaeger or Zipkin.
## Contributor Guide

### Setup Environment

*   Clone the repository.
*   Install the package in editable mode with all dependencies:
    ```bash
    pip install -e ".[all,test]"
    ```
*   Ensure you have system dependencies installed, such as `graphviz`.
    *   Debian/Ubuntu:
        ```bash
        sudo apt-get install graphviz
        ```
    *   macOS (Homebrew):
        ```bash
        brew install graphviz
        ```

### Running Tests

To run the `holarchy` test suite:
```bash
pytest holarchy/tests/
```
