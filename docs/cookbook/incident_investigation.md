**EN** | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/cookbook/incident_investigation.md) | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/incident_investigation.md)

# Cookbook: Incident Investigation & Evidence Cards

When mission-critical distributed pipelines encounter failures, diagnosing the exact root cause quickly without exposing sensitive customer data is paramount.

Holarchy provides built-in **Deterministic DNA (D-DNA)** audit hashing and **Zero-Trust Incident Evidence Cards** for instant post-mortem analysis.

---

## 1. Deterministic DNA & Cryptographic Chain of Custody

Every job in Holarchy maintains a cryptographic hash chain of state transitions:
- Each state transition calculates a hash over the prior state hash, current step name, inputs, and step results (`d_dna`).
- If an attacker, rogue worker, or storage corruption alters history retroactively, the verification hash diverges from `d_dna_hash`, immediately flagging the job as tampered.

---

## 2. Retrieving Incident Evidence Cards via API

When a job enters a `failed` or `quarantined` state, Holarchy automatically synthesizes an **Incident Evidence Card**.

### Requesting Human-Readable Markdown

```bash
curl -H "X-Client-Token: YOUR_TOKEN" \
     "http://localhost:8080/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/evidence?format=md"
```

**Sample Output:**
```markdown
# 🚨 INCIDENT EVIDENCE CARD

**Job ID:** `550e8400-e29b-41d4-a716-446655440000`
**Blueprint:** `ecommerce_orders`
**Failed Step:** `FlowStates:payment`
**D-DNA Hash:** `genesis:7f83b165...`
**Timestamp:** `2026-09-27T14:30:00Z`

---

### Root Cause
> Connection timeout: Failed to connect to payment gateway provider within 5.0s

### Automated Remediation Suggestions
- [ ] **Transient Network Issue**: Retry the job with exponential backoff.
- [ ] Verify outbound network connectivity and security groups to `api.payment.internal`.

### State Snapshot (Sanitized)
- **Input:** `{"order_id": 9921, "amount": 150.0}`
- **Steps Completed:**
  - `init`: `{"validated": true}`
```

### Requesting Structured JSON

```bash
curl -H "X-Client-Token: YOUR_TOKEN" \
     "http://localhost:8080/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000/evidence"
```

Returns the full incident payload formatted for consumption by alerting pipelines (PagerDuty, Slack, OpsGenie, or Datadog):

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "blueprint": "ecommerce_orders",
  "failed_step": "FlowStates:payment",
  "d_dna_hash": "genesis:7f83b165...",
  "error_message": "Connection timeout: Failed to connect...",
  "remediation": [
    "Transient network timeout detected. Recommended action: retry with exponential backoff."
  ]
}
```

---

## 3. Zero-Trust Sanitization

Incident cards automatically redact sensitive security tokens and credentials:
- `X-Client-Token`, `Authorization`, and `ORCHESTRATOR_SECRET_KEY` are stripped.
- Passwords, secret keys, and credentials matching known security patterns are masked with `[REDACTED]`.
- Internal worker environment memory dumps are isolated.

---

## 4. Root Cause Classification Categories

Holarchy's automated classifier categorizes incidents into actionable operational buckets:

| Category | Typical Cause | Suggested Remediation |
|---|---|---|
| **Transient / Network** | Connection timeouts, DNS blips, 502/503/504 gateway errors | Trigger job retry or check worker networking. |
| **Contract / Schema** | Missing required fields, Pydantic `ValidationError` | Verify worker skill version matches blueprint contract. |
| **Resource Quota** | Out of Memory (OOM), client token rate-limits | Scale worker replicas or adjust client concurrency quota. |
| **Business Logic** | State decider non-candidate or uncaught exception | Inspect step code logic or check decider fallback state. |

---

## 5. Visualizing Execution History with Graphviz DAG

To pinpoint where the failure occurred in relation to the pipeline's overall state machine:

```bash
# Get interactive graph topology
curl -H "X-Client-Token: YOUR_TOKEN" \
     "http://localhost:8080/api/v1/blueprints/ecommerce_orders/dag"
```

Use the interactive spatial graph inside the Holarchy web UI at `/docs` to visually trace the exact path leading to the failed state.
