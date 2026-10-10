# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ..engine import OrchestratorEngine


def invalidate_openapi_spec_cache(engine: OrchestratorEngine) -> None:
    """Invalidates the memoized OpenAPI 3.1 specification and pre-serialized JSON on the engine."""
    cache = getattr(engine, "_openapi_spec_cache", None)
    if isinstance(cache, dict):
        cache.clear()
    if hasattr(engine, "_openapi_json_bytes"):
        engine._openapi_json_bytes = None
    if hasattr(engine, "_docs_html_cache"):
        engine._docs_html_cache = None


def generate_openapi_spec(
    engine: OrchestratorEngine,
    title: str = "Holarchy Orchestrator API",
    version: str = "1.0.0",
    description: str = (
        "High-performance distributed workflow orchestration engine with FSM, "
        "Advisory Routing, and Zero-Trust Evidence Cards."
    ),
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Dynamically generates an OpenAPI 3.1.0 specification dictionary from the engine's blueprints and routes.

    Uses engine-level memoization for high-throughput serving, returning cached specs
    unless invalidated by blueprint registration or forced refresh.
    """
    cache_key = (title, version, description)
    spec_cache = getattr(engine, "_openapi_spec_cache", None)
    if not force_refresh and isinstance(spec_cache, dict):
        cached = spec_cache.get(cache_key)
        if cached is not None:
            return cast(dict[str, Any], cached)

    paths: dict[str, Any] = {}

    # Common parameters for orchestrator headers
    orchestrator_header_params = [
        {
            "name": "X-Webhook-URL",
            "in": "header",
            "required": False,
            "description": "Callback webhook URL triggered upon job completion or failure.",
            "schema": {"type": "string", "format": "uri"},
        },
        {
            "name": "X-Job-Timeout",
            "in": "header",
            "required": False,
            "description": "Execution timeout in seconds for this job.",
            "schema": {"type": "integer", "default": 300},
        },
        {
            "name": "X-Job-Priority",
            "in": "header",
            "required": False,
            "description": "Job execution priority.",
            "schema": {
                "type": "string",
                "enum": ["critical", "high", "normal", "low"],
                "default": "normal",
            },
        },
        {
            "name": "X-Correlation-ID",
            "in": "header",
            "required": False,
            "description": "End-to-end distributed tracing correlation ID.",
            "schema": {"type": "string"},
        },
        {
            "name": "Idempotency-Key",
            "in": "header",
            "required": False,
            "description": "Unique client token to prevent duplicate task execution.",
            "schema": {"type": "string"},
        },
    ]

    # Standard system endpoints
    paths["/status"] = {
        "get": {
            "summary": "Health Status",
            "description": "Returns operational health status of the orchestrator service.",
            "tags": ["System"],
            "responses": {
                "200": {
                    "description": "Service is healthy",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string", "example": "ok"}},
                            }
                        }
                    },
                }
            },
        }
    }

    paths["/openapi.json"] = {
        "get": {
            "summary": "OpenAPI 3.1 Specification",
            "description": "Returns this OpenAPI 3.1 JSON specification.",
            "tags": ["System"],
            "responses": {
                "200": {
                    "description": "OpenAPI JSON document",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            },
        }
    }

    paths["/api/v1/jobs/start/{blueprint_name}"] = {
        "post": {
            "summary": "Start Job by Blueprint Name",
            "description": "Generic entry point to create and start a job for any registered blueprint.",
            "tags": ["Jobs"],
            "parameters": [
                {
                    "name": "blueprint_name",
                    "in": "path",
                    "required": True,
                    "description": "Name of the registered blueprint to execute.",
                    "schema": {"type": "string"},
                },
                *orchestrator_header_params,
            ],
            "requestBody": {
                "required": True,
                "description": "Pure business payload for the job (input).",
                "content": {
                    "application/json": {"schema": {"type": "object", "description": "Arbitrary business payload"}}
                },
            },
            "responses": {
                "202": {
                    "description": "Job successfully accepted for execution",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string", "example": "accepted"},
                                    "job_id": {"type": "string", "example": "job_01j7..."},
                                    "id": {"type": "string", "example": "job_01j7..."},
                                },
                            }
                        }
                    },
                },
                "404": {"description": "Blueprint not found"},
            },
        }
    }

    paths["/api/v1/jobs/{job_id}"] = {
        "get": {
            "summary": "Get Job State and Status",
            "description": (
                "Retrieves the full job state split into 5 clean zones: input, output, steps, history, meta."
            ),
            "tags": ["Jobs"],
            "parameters": [
                {
                    "name": "job_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique identifier of the job.",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": {
                    "description": "Job state retrieved",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JobState"}}},
                },
                "404": {"description": "Job not found"},
            },
        }
    }

    paths["/api/v1/jobs/{job_id}/cancel"] = {
        "post": {
            "summary": "Cancel Job",
            "description": "Initiates cooperative cancellation of a running job across workers.",
            "tags": ["Jobs"],
            "parameters": [
                {
                    "name": "job_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique identifier of the job.",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": {
                    "description": "Cancellation initiated",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string", "example": "cancellation_request_sent"}},
                            }
                        }
                    },
                }
            },
        }
    }

    paths["/api/v1/jobs/{job_id}/evidence"] = {
        "get": {
            "summary": "Get Incident Evidence Card",
            "description": (
                "Retrieves the tamper-proof Incident Evidence Card for a quarantined or failed job, "
                "available in structured JSON or human-readable Markdown."
            ),
            "tags": ["Jobs", "Diagnostics"],
            "parameters": [
                {
                    "name": "job_id",
                    "in": "path",
                    "required": True,
                    "description": "Unique identifier of the job.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "format",
                    "in": "query",
                    "required": False,
                    "description": "Requested output format: 'json' or 'markdown'/'md'.",
                    "schema": {"type": "string", "enum": ["json", "markdown", "md"], "default": "json"},
                },
            ],
            "responses": {
                "200": {
                    "description": "Incident Evidence Card",
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/IncidentEvidence"}},
                        "text/markdown": {"schema": {"type": "string"}},
                    },
                },
                "404": {"description": "Job not found"},
            },
        }
    }

    paths["/api/v1/jobs/{job_id}/history"] = {
        "get": {
            "summary": "Get Job Event History",
            "description": "Retrieves the chronological audit log of all transitions, steps, and worker executions.",
            "tags": ["Jobs"],
            "parameters": [
                {
                    "name": "job_id",
                    "in": "path",
                    "required": True,
                    "description": "Job ID.",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": {
                    "description": "Event history list",
                    "content": {"application/json": {"schema": {"type": "array", "items": {"type": "object"}}}},
                }
            },
        }
    }

    paths["/api/v1/jobs"] = {
        "get": {
            "summary": "List Jobs",
            "description": "Lists recent jobs with pagination support.",
            "tags": ["Jobs"],
            "parameters": [
                {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 50}},
                {"name": "offset", "in": "query", "required": False, "schema": {"type": "integer", "default": 0}},
            ],
            "responses": {
                "200": {
                    "description": "List of jobs",
                    "content": {
                        "application/json": {
                            "schema": {"type": "array", "items": {"$ref": "#/components/schemas/JobState"}}
                        }
                    },
                }
            },
        }
    }

    paths["/api/v1/jobs/quarantined"] = {
        "get": {
            "summary": "List Quarantined Jobs",
            "description": "Returns list of job IDs currently placed in quarantine for forensic investigation.",
            "tags": ["Jobs", "Diagnostics"],
            "responses": {
                "200": {
                    "description": "Quarantined job IDs",
                    "content": {"application/json": {"schema": {"type": "array", "items": {"type": "string"}}}},
                }
            },
        }
    }

    paths["/api/v1/blueprints/{blueprint_name}/dag"] = {
        "get": {
            "summary": "Get Blueprint Spatial DAG Graph Topology",
            "description": (
                "Returns the spatial graph nodes, transitions, deciders, and risk metadata for 2D visualization."
            ),
            "tags": ["Blueprints"],
            "parameters": [
                {
                    "name": "blueprint_name",
                    "in": "path",
                    "required": True,
                    "description": "Blueprint name.",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": {
                    "description": "DAG topology object",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DAGTopology"}}},
                },
                "404": {"description": "Blueprint not found"},
            },
        }
    }

    paths["/api/v1/skills"] = {
        "get": {
            "summary": "Get Two-Tier Lazy Skill Catalog Index",
            "description": "Returns the ultra-compact index (<5 KB) of all available worker skills across the network.",
            "tags": ["Skills"],
            "responses": {
                "200": {
                    "description": "Skill catalog index",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "skills": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/SkillIndexItem"},
                                    }
                                },
                            }
                        }
                    },
                }
            },
        }
    }

    paths["/api/v1/skills/{skill_name}"] = {
        "get": {
            "summary": "Get On-Demand Skill Schema",
            "description": "Fetches the full argument JSON schema and permission requirements for a specific skill.",
            "tags": ["Skills"],
            "parameters": [
                {
                    "name": "skill_name",
                    "in": "path",
                    "required": True,
                    "description": "Unique skill name.",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": {
                    "description": "Detailed skill schema",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "404": {"description": "Skill not found"},
            },
        }
    }

    paths["/api/v1/workers"] = {
        "get": {
            "summary": "List Active Workers",
            "description": "Returns connected worker instances, node types, and current health status.",
            "tags": ["Workers"],
            "responses": {
                "200": {
                    "description": "Worker instances list",
                    "content": {"application/json": {"schema": {"type": "array", "items": {"type": "object"}}}},
                }
            },
        }
    }

    # Dynamic Blueprint Endpoints
    for bp_name, bp in getattr(engine, "blueprints", {}).items():
        ver_prefix = f"/{bp.api_version}" if bp.api_version else ""
        if bp.api_endpoint:
            endpoint_path = bp.api_endpoint if bp.api_endpoint.startswith("/") else f"/{bp.api_endpoint}"
            route_path = f"/api{ver_prefix}{endpoint_path}"
        else:
            route_path = f"/api/v1/jobs/start/{bp_name}"

        contract = getattr(engine, "blueprint_contracts", {}).get(bp_name, {})
        input_schema = contract.get("input_schema") or {"type": "object", "description": "Business payload"}
        output_schema = contract.get("output_schema") or {"type": "object"}

        sec_meta = (
            bp.get_security_metadata() if hasattr(bp, "get_security_metadata") else {"risk": "low", "permissions": []}
        )

        paths[route_path] = {
            "post": {
                "summary": f"Create {bp_name.replace('_', ' ').title()} Job",
                "description": f"Creates and executes a new instance of the `{bp_name}` blueprint.",
                "tags": ["Blueprints", bp_name],
                "parameters": list(orchestrator_header_params),
                "requestBody": {
                    "required": True,
                    "description": "Pure business input payload validated against the blueprint's start step contract.",
                    "content": {"application/json": {"schema": input_schema}},
                },
                "responses": {
                    "202": {
                        "description": "Job successfully accepted",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "example": "accepted"},
                                        "job_id": {"type": "string", "example": "job_01j7..."},
                                        "id": {"type": "string", "example": "job_01j7..."},
                                    },
                                }
                            }
                        },
                    }
                },
                "x-holarchy-risk": sec_meta.get("risk", "low"),
                "x-holarchy-permissions": sec_meta.get("permissions", []),
                "x-holarchy-start-state": str(bp.start_state) if bp.start_state else None,
                "x-holarchy-end-states": [str(s) for s in getattr(bp, "end_states", [])],
                "x-holarchy-deciders": [str(d) for d in getattr(bp, "_deciders", {})],
                "x-holarchy-output-schema": output_schema,
            }
        }

    components: dict[str, Any] = {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "Token",
                "description": "Client authentication token passed in the Authorization header.",
            },
            "ClientTokenAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Client-Token",
                "description": "Client authentication token passed in the X-Client-Token header.",
            },
        },
        "schemas": {
            "JobState": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "example": "job_01j7v66..."},
                    "blueprint": {"type": "string", "example": "order_flow"},
                    "status": {
                        "type": "string",
                        "enum": ["running", "finished", "failed", "quarantined", "waiting_for_human"],
                    },
                    "input": {"type": "object", "description": "Immutable business input payload"},
                    "output": {"type": "object", "description": "Final business result from terminal step"},
                    "steps": {
                        "type": "object",
                        "description": "Blackboard of intermediate step and worker outputs",
                    },
                    "history": {"type": "array", "items": {"type": "object"}},
                    "params": {"type": "object"},
                    "meta": {"type": "object"},
                    "error": {"type": "string", "nullable": True},
                    "created_at": {"type": "number"},
                    "finished_at": {"type": "number", "nullable": True},
                },
            },
            "IncidentEvidence": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "classification": {
                        "type": "string",
                        "enum": ["transient_network", "schema_violation", "crash", "worker_timeout"],
                    },
                    "remediation": {"type": "string"},
                    "incident_card": {"type": "string", "description": "ASCII formatted evidence card"},
                },
            },
            "DAGTopology": {
                "type": "object",
                "properties": {
                    "blueprint_name": {"type": "string"},
                    "start_state": {"type": "string"},
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": ["step", "decider", "subgraph"]},
                                "is_start": {"type": "boolean"},
                                "is_end": {"type": "boolean"},
                                "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                            },
                        },
                    },
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "is_fallback": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
            "SkillIndexItem": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "version": {"type": "string"},
                    "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                    "permissions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }

    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": version,
            "description": description,
            "contact": {"name": "Holarchy Engineering", "url": "https://github.com/madgagarin/rxon"},
        },
        "servers": [{"url": "/", "description": "Local orchestrator instance"}],
        "paths": paths,
        "components": components,
    }

    if isinstance(spec_cache, dict):
        spec_cache[cache_key] = spec

    return spec
