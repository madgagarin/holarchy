**EN** | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/api_reference.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/api_reference.md)

# Orchestrator API Reference

This document describes all HTTP endpoints provided by the Orchestrator server. The API is divided into three logical groups: Public, Client, and Internal (for Workers).

## Authentication

- **Client -> Orchestrator:** All requests to client endpoints (default prefix `/api/v1/*`) must contain the `X-Client-Token` header. The `/api` part is configurable via `CLIENT_API_PREFIX`.
- **Worker -> Orchestrator:** All requests to `/_worker/*` endpoints must contain the `X-Worker-Token` header with a valid worker token (individual or global).

---

## 1. Public Endpoints (`/_public`)

These endpoints do not require authentication and always use the fixed `/_public` prefix.

### Service Status Check

- **Endpoint:** `GET /_public/status`
- **Description:** Returns a simple response confirming that the service is running.
- **Response (`200 OK`):** `{"status": "ok"}`

### Webhook for "Human Approval"

- **Endpoint:** `POST /_public/webhooks/approval/{job_id}`
- **Description:** Allows an external system or operator to approve, reject, or decide the next branch for a step in the pipeline when a job is in `waiting_for_human` state.
- **Authentication & Security:**
  - **Scoped Approval Token:** A single-use, time-bound cryptographic token generated when entering `waiting_for_human`. Can be passed either as a URL query parameter (`?token=<approval_token>`) or inside the JSON payload (`{"token": "<approval_token>", ...}`). Once consumed, the token is permanently invalidated to prevent replay attacks.
  - **Fallback Client Token:** If no approval token is provided, requests must include the valid `X-Client-Token` of the job's owner. Unauthorized or unauthenticated attempts return `401 Unauthorized`.
- **Request Body:**
  ```json
  {
    "decision": "approved",
    "token": "optional_token_if_not_in_query"
  }
  ```
  - `decision` (string, required): Decision outcome matching one of the configured approval step branches (e.g., `"approved"`, `"rejected"`).
  - `token` (string, optional): Scoped approval token (if not supplied via URL query parameter).
- **Responses:**
  - `200 OK`: `{"status": "approval_received", "job_id": "..."}`
  - `400 Bad Request`: Missing body, malformed JSON, or missing `decision`.
  - `401 Unauthorized`: Missing or invalid `token` and missing/invalid `X-Client-Token`.
  - `409 Conflict`: Job is not in `waiting_for_human` state or cannot accept decision.

### Debug Endpoint for DB Flushing

- **Endpoint:** `POST /_public/debug/flush_db`
- **Description:** **(Development only!)** Clears the entire Redis database.
- **Response (`200 OK`):** `{"status": "db_flushed"}`

### Interactive API Documentation

- **Endpoint:** `GET /docs` (or `GET /_public/docs`)
- **Description:** Returns an interactive branded HTML page with API documentation, live test harness runner, 5 storage zones inspector, and security risk/permission badges.
- **Response (`200 OK`):** HTML page (`text/html`).

### Dynamic OpenAPI 3.1.0 Specification

- **Endpoint:** `GET /openapi.json` (or `GET /_public/openapi.json`)
- **Description:** Dynamically generates the complete OpenAPI 3.1.0 specification including all registered blueprints, spatial DAGs, skill marketplace endpoints, and orchestrator headers.
- **Response (`200 OK`):** JSON object (`application/json`) with OpenAPI 3.1.0 schema.

---

## 2. Client Endpoints (`/{CLIENT_API_PREFIX}/v1`)

These endpoints are designed for external systems that initiate and monitor workflows. Requires `X-Client-Token` header.
The base path for these endpoints is configurable via the `CLIENT_API_PREFIX` environment variable (default is `api`). If set to an empty string, these endpoints will be available at the root (e.g. `/v1/...`).

### Orchestrator Request Headers

When creating jobs, orchestrator execution parameters are supplied via standard HTTP headers to maintain pure domain payloads:

- `X-Client-Token` (string, required): Client authentication token.
- `X-Job-Priority` (string, optional): Job priority (`critical`, `high`, `normal` [default], `low`, `background`).
- `X-Job-Timeout` (integer, optional): Maximum execution timeout in seconds.
- `X-Correlation-ID` (string, optional): Tracing correlation ID propagated across all distributed steps and workers.
- `Idempotency-Key` (string, optional): Deduplication key preventing accidental duplicate job executions on network retries.
- `X-Webhook-URL` (string, optional): Callback URL notified asynchronously when the job reaches a terminal state.

### Create New Job (Custom Blueprint Endpoint)

- **Endpoint:** `POST /{CLIENT_API_PREFIX}/v1/{blueprint_api_endpoint}`
- **Example:** `POST /api/v1/jobs/orders`
- **Description:** Creates and starts a new instance (Job) using the custom route configured on the blueprint.
- **Headers:** See Orchestrator Request Headers above.
- **Request Body:** Clean domain input payload matching the blueprint's start step schema:
  ```json
  {
    "order_id": 42,
    "amount": 150.0,
    "is_vip": true
  }
  ```
- **Response (`202 Accepted`):**
  ```json
  {
    "status": "accepted",
    "job_id": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```

### Create New Job (Generic Blueprint Starter)

- **Endpoint:** `POST /{CLIENT_API_PREFIX}/v1/jobs/start/{blueprint_name}`
- **Example:** `POST /api/v1/jobs/start/ecommerce_orders`
- **Description:** Generic endpoint to start any registered blueprint by its name, even without a custom endpoint assigned.
- **Headers:** See Orchestrator Request Headers above.
- **Request Body:** Clean domain input payload matching the blueprint's start step schema.
- **Response (`202 Accepted`):**
  ```json
  {
    "status": "accepted",
    "job_id": "123e4567-e89b-12d3-a456-426614174000"
  }
  ```
- **Response (`404 Not Found`):** Blueprint name is not registered in the orchestrator.

### Get Job Status

- **Endpoint:** `GET /api/v1/jobs/{job_id}`
- **Description:** Returns the current state of the specified job structured across 5 clean storage zones (`input`, `steps`, `history`, `meta`, `output`).

#### Job Statuses

The system uses the following statuses to manage the job lifecycle:

**Intermediate States:**

- `pending`: Job created and waiting to be queued.
- `running`: Job is actively being processed.
- `waiting_for_worker`: Waiting for a suitable worker to pick up the task.
- `waiting_for_human`: Awaiting manual approval or action (Human-in-the-loop).
- `waiting_for_parallel`: Waiting for all sub-tasks in a parallel branch to complete.

**Terminal States:**

- `finished`: Job completed successfully. Final output is available in the `output` zone.
- `failed`: Logic or worker error. Error details are available in the error fields.
- `cancelled`: Job was cancelled by a user or the system.
- `error`: Critical system error during execution.
- `quarantined`: Job placed in quarantine for manual review (e.g., contract violation or unhandled worker error).

* **Query Parameters:**
  - `fields` (string, optional): Comma-separated list of fields to return. In compact mode, only essential fields can be requested.

**Security Note:** The `output` field is only populated and visible when the job reaches a terminal state (`finished`). For jobs in intermediate states (`running`, `waiting`), the output is hidden to protect sensitive in-progress data.

**Data Isolation:** Access is strictly limited to the client who created the job. You must provide the same `X-Client-Token` that was used to start the job. Any attempt to access a job ID belonging to another client will return a `404 Not Found` for security reasons (to avoid job ID enumeration).

**Compact Response (Default):**

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "finished",
  "blueprint_name": "ecommerce_orders",
  "current_state": "FlowStates:finalize"
}
```

**Detailed Response (with 5 Storage Zones):**

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "finished",
  "blueprint_name": "ecommerce_orders",
  "current_state": "FlowStates:finalize",
  "input": {
    "order_id": 42,
    "amount": 150.0,
    "is_vip": true
  },
  "steps": {
    "check_inventory": {
      "in_stock": true,
      "warehouse_code": "WH-US-EAST"
    },
    "charge_card": {
      "transaction_id": "tx_9988",
      "authorized": true
    }
  },
  "history": [
    {
      "state": "FlowStates:init",
      "status": "success",
      "duration_ms": 12.4,
      "timestamp": 1715280001.0
    },
    {
      "state": "FlowStates:finalize",
      "status": "success",
      "duration_ms": 5.1,
      "timestamp": 1715280002.0
    }
  ],
  "meta": {
    "priority": "normal",
    "timeout": 300,
    "correlation_id": "corr-order-42",
    "headers": {
      "x-correlation-id": "corr-order-42"
    },
    "created_at": 1715280000.0,
    "finished_at": 1715280004.2
  },
  "output": {
    "receipt_id": "rcpt_42",
    "status": "paid",
    "amount": 150.0
  }
}
```

### Incident Evidence Card

- **Endpoint:** `GET /api/v1/jobs/{job_id}/evidence`
- **Description:** Generates a comprehensive forensic diagnostic card for jobs in `failed` or `quarantined` state. Essential for post-mortem analysis and incident remediation.
- **Query Parameters:**
  - `format` (string, optional): Response format, either `json` (default) or `md` (Markdown).
- **JSON Response (`200 OK`):**
  ```json
  {
    "job_id": "123e4567-e89b-12d3-a456-426614174000",
    "blueprint_name": "ecommerce_orders",
    "status": "quarantined",
    "failed_step": "FlowStates:charge_card",
    "error_message": "Payment gateway timeout after 3 retries",
    "remediation": "Check gateway API availability or replay job via /jobs/start/ecommerce_orders.",
    "receipts": [...]
  }
  ```
- **Markdown Response (`200 OK` when `?format=md`):** Formatted text document (`text/markdown; charset=utf-8`) ready for Slack, Jira, or GitHub issue reporting.

### Get S3 Upload URL

- **Endpoint:** `GET /api/v1/jobs/{job_id}/files/upload`
- **Description:** Generates a temporary S3 presigned URL for uploading a file directly.
- **Query Parameters:**
  - `filename` (string, required): Name of the file.
  - `expires_in` (integer, optional): Link validity in seconds.
- **Response (`200 OK`):** `{"url": "...", "expires_in": 3600, "method": "PUT"}`

### Upload File (Direct Streaming)

- **Endpoint:** `PUT /api/v1/jobs/{job_id}/files/content/{filename}`
- **Description:** Uploads a file directly to S3 via Orchestrator streaming proxy.
- **Response (`200 OK`):** `{"status": "uploaded", "s3_uri": "..."}`

### Download File (Stable Link)

- **Endpoint:** `GET /api/v1/jobs/{job_id}/files/download/{filename}`
- **Description:** A stable link that redirects to a fresh S3 presigned URL.
- **Response (`302 Found`):** Redirects to the S3 URL.

### Cancel Running Task

- **Endpoint**: `POST /api/v1/jobs/{job_id}/cancel`
- **Description**: Initiates cancellation of a task being executed by a worker.
- **Response (`200 OK`):** `{"status": "cancellation_request_sent"}`

### Get Job History

- **Endpoint:** `GET /api/v1/jobs/{job_id}/history`
- **Description:** Returns the full event history for the specified job. In compact mode, `context_snapshot` fields in events are filtered.

### Get Jobs List

- **Endpoint:** `GET /api/v1/jobs`
- **Description:** Returns a list of all jobs. In compact mode, `context_snapshot` for each job is filtered.
- **Response (`200 OK`):** Array of event objects.

### Get Quarantined Jobs List

- **Endpoint:** `GET /api/v1/jobs/quarantined`
- **Description:** Returns a list of jobs currently in quarantine for manual review. Requires client authentication.
- **Response (`200 OK`):** Array of quarantined job state objects.

### Get Blueprint Graph (DOT)

- **Endpoint:** `GET /api/v1/blueprints/{blueprint_name}/graph`
- **Description:** Returns the blueprint structure in Graphviz DOT format for structural visualization.
- **Response (`200 OK`):** Text response in `text/vnd.graphviz` format.

### Get Blueprint Spatial DAG

- **Endpoint:** `GET /api/v1/blueprints/{blueprint_name}/dag`
- **Description:** Returns the 2D spatial layout and topological graph of the blueprint, including node coordinates, step kinds (`start`, `step`, `decide`, `parallel`, `human`, `end`), candidate branches, transition edges, and aggregated security metadata (`risk` level and `permissions`).
- **Response (`200 OK`):** JSON object:
  ```json
  {
    "blueprint_name": "ecommerce_orders",
    "nodes": [
      {
        "id": "FlowStates:init",
        "label": "init",
        "kind": "start",
        "x": 0.0,
        "y": 0.0,
        "risk": "low",
        "permissions": []
      },
      {
        "id": "FlowStates:decide_step",
        "label": "decide_route",
        "kind": "decide",
        "x": 240.0,
        "y": 0.0,
        "risk": "high",
        "permissions": ["billing:vip"],
        "candidates": ["FlowStates:vip_process", "FlowStates:std_process"]
      }
    ],
    "edges": [
      {"from": "FlowStates:init", "to": "FlowStates:decide_step", "label": "next"}
    ],
    "security": {
      "risk": "high",
      "permissions": ["billing:charge", "billing:vip"]
    }
  }
  ```

### Get Active Workers List

- **Endpoint:** `GET /api/v1/workers`
- **Description:** Returns a list of all currently active workers connected to the orchestrator.
- **Response (`200 OK`):** Array of worker objects.

### Get Dashboard Data

- **Endpoint:** `GET /api/v1/dashboard`
- **Description:** Returns aggregated statistics about the system state, job counts, and worker health.
- **Response (`200 OK`):** JSON object with statistics.

### Get Skill Catalog (Marketplace)

- **Endpoint:** `GET /api/v1/skills` (also legacy `GET /api/v1/workers/catalog`)
- **Description:** Returns an aggregated catalog of unique worker skills across the cluster, including input/output contracts, risk levels, and permissions. Cached for high throughput.
- **Response (`200 OK`):** JSON object with registered skill definitions.

### Get Skill Contract Detail

- **Endpoint:** `GET /api/v1/skills/{skill_name}`
- **Description:** Returns the full specification and schema contract for a specific worker skill.
- **Response (`200 OK`):**
  ```json
  {
    "name": "billing:charge",
    "version": "1.0.0",
    "risk": "medium",
    "permissions": ["billing:charge"],
    "input_schema": { ... },
    "output_schema": { ... }
  }
  ```
- **Response (`404 Not Found`):** Skill is not registered in the cluster catalog.

---

## 3. Internal Endpoints for Workers (`/_worker`)

These endpoints are used by workers to register, receive tasks, and submit results. Requires `X-Worker-Token` header.

### Register Worker

- **Endpoint:** `POST /_worker/workers/register`
- **Description:** Registers a worker in the system.
- **Request Body:**
  ```json
  {
    "worker_id": "worker-123",
    "supported_skills": [
      {"name": "transcribe", "input_schema": {...}, "output_schema": {...}}
    ],
    "capabilities": {"gpu": true, "vram_gb": 16}
  }
  ```
- **Response (`200 OK`):** `{"status": "registered"}`

### Heartbeat / Status Update

- **Endpoint:** `PATCH /_worker/workers/{worker_id}`
- **Description:** Confirms activity and updates state. Supports Jitter to distribute load.
- **Response (`200 OK`):** `{"status": "ok", "next_heartbeat_jitter_ms": 1500}`

### Get Next Task (Long-Polling)

- **Endpoint:** `GET /_worker/workers/{worker_id}/tasks/next`
- **Description:** Worker requests the next task. Connection is held open if no tasks are available. Uses optimized Task Stealing.
- **Response (`200 OK`):** JSON object with task data.
- **Response (`204 No Content`):** Returned on timeout if no new tasks appeared.

### Submit Task Result

- **Endpoint:** `POST /_worker/tasks/result`
- **Description:** Worker submits the result of a completed task.
- **Request Body:**
  ```json
  {
    "job_id": "...",
    "task_id": "...",
    "worker_id": "...",
    "status": "success",
    "data": { ... }
  }
  ```
- **Response (`200 OK`):** `{"status": "accepted"}`

### Emit Generic Event (Bottom-Up)

- **Endpoint:** `POST /_worker/events`
- **Description:** Allows a worker to send signals (progress, alerts).
- **Response (`200 OK`):** `{"status": "event_accepted"}`

### Establish WebSocket Connection

- **Endpoint**: `GET /_worker/ws/{worker_id}`
- **Description**: Real-time command channel.
- **Protocol**: `WebSocket`
