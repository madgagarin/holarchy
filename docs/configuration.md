# Configuration Files Reference

Holarchy uses [TOML](https://toml.io/en/) format files to manage access and settings for clients and workers.

The system implements the **Fail Fast** principle: if a TOML syntax error or missing mandatory fields is detected at startup, the Orchestrator **will not start** and will raise an exception. This ensures the system does not run in an incorrect or unsafe state.

---

## 1. clients.toml

This file defines the list of API clients authorized to create jobs.

**Default Path:** Can be set via `CLIENTS_CONFIG_PATH` environment variable. Usually located in the project root.

### Structure

The file consists of sections (tables), where the section name is the client's unique identifier (for logs and convenience).

| Field | Type | Mandatory | Description |
| :--- | :--- | :--- | :--- |
| `token` | String | **Yes** | Secret token the client must pass in `X-Holarchy-Token` header. |
| `plan` | String | No | Tariff plan name (e.g., "free", "premium"). Used in blueprints for logic. |
| `monthly_attempts` | Integer | No | Monthly request quota. If set, Orchestrator will track and block requests exceeding the limit. |
| `*` | Any | No | Any other fields (e.g., `languages`, `callback_url`) will be available in `context.client.params`. |

### Example

```toml
# Premium client
[client_premium_user]
token = "sec_vip_token_123"
plan = "premium"
monthly_attempts = 100000
# Custom parameters
languages = ["en", "de", "fr"]
priority_support = true

# Free client
[client_free_user]
token = "sec_free_token_456"
plan = "free"
monthly_attempts = 100
languages = ["en"]
```

---

## 2. workers.toml

This file is used to configure individual worker authentication. This is a safer alternative to using a single global token.

**Default Path:** Can be set via `WORKERS_CONFIG_PATH` environment variable.

### Structure

The file consists of sections, where the section name must **exactly match** the `worker_id` the worker uses when registering.

| Field | Type | Mandatory | Description |
| :--- | :--- | :--- | :--- |
| `token` | String | **Yes** | Individual secret token for this worker. |
| `description` | String | No | Worker description for administrators. |

### Security Features
*   At startup, Orchestrator calculates SHA-256 hash of the token and stores only the hash in memory (Redis). The original token is not stored anywhere.
*   Upon incoming request from a worker, the hash of the provided token is compared with the stored one.

### Example

```toml
# Section name must be the same as WORKER_ID on the worker side
[gpu-worker-01]
token = "super-secret-token-for-gpu-01"
description = "Primary GPU node for video rendering"

[cpu-worker-01]
token = "another-secret-token-for-cpu-01"
description = "General purpose CPU worker"
```

---

## Dynamic Reloading

You can update `workers.toml` without restarting the Orchestrator.
To do this, send a POST request (with a valid client token) to the endpoint:

`POST /api/v1/admin/reload-workers`

This forces the Orchestrator to re-read the file and update token hashes in Redis.