"""
Centralized constants for the Holarchy protocol.
Use these constants instead of hardcoded strings to ensure consistency.
"""

# --- Auth Headers ---
AUTH_HEADER_CLIENT = "X-Holarchy-Token"
AUTH_HEADER_WORKER = "X-Worker-Token"

# --- Error Codes ---
# Error codes returned by workers in the result payload
ERROR_CODE_TRANSIENT = "TRANSIENT_ERROR"
ERROR_CODE_PERMANENT = "PERMANENT_ERROR"
ERROR_CODE_INVALID_INPUT = "INVALID_INPUT_ERROR"

# --- Task Statuses ---
# Standard statuses for task results
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_FAILURE = "failure"
TASK_STATUS_CANCELLED = "cancelled"

# --- Job Statuses ---
JOB_STATUS_PENDING = "pending"
JOB_STATUS_WAITING_FOR_WORKER = "waiting_for_worker"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_QUARANTINED = "quarantined"
JOB_STATUS_CANCELLED = "cancelled"
JOB_STATUS_WAITING_FOR_HUMAN = "waiting_for_human"
JOB_STATUS_WAITING_FOR_PARALLEL = "waiting_for_parallel_tasks"
