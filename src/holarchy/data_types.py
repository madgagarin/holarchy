from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Optional

if TYPE_CHECKING:
    from .context import ActionFactory


class ClientConfig(NamedTuple):
    """Static client configuration, obtained from `clients.toml`."""

    token: str
    plan: str
    # Use Dict to support any custom fields
    params: Dict[str, Any]


class JobContext(NamedTuple):
    """Job execution context, passed to each handler."""

    job_id: str
    current_state: str
    initial_data: Dict[str, Any]
    state_history: Dict[str, Any]
    client: ClientConfig
    actions: "ActionFactory"
    data_stores: Any = None
    tracing_context: Dict[str, Any] = {}
    aggregation_results: Optional[Dict[str, Any]] = None


class GPUInfo(NamedTuple):
    """Information about the graphics processor."""

    model: str
    vram_gb: int


class Resources(NamedTuple):
    """Information about worker resources."""

    max_concurrent_tasks: int
    gpu_info: GPUInfo | None
    cpu_cores: int


class InstalledModel(NamedTuple):
    """Information about the installed ML model."""

    name: str
    version: str


class WorkerInfo(NamedTuple):
    """Complete information about the worker, transmitted upon registration."""

    worker_id: str
    address: str
    dynamic_token: str
    worker_type: str
    supported_tasks: list[str]
    resources: Resources
    installed_software: dict[str, str]
    installed_models: list[InstalledModel]
