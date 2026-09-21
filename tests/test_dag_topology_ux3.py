# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from typing import Any

import pytest

from holarchy.blueprint import Blueprint


def test_blueprint_to_dag_linear_and_decider() -> None:
    bp = Blueprint("linear_decide_bp")

    @bp.start("start_step")
    async def start_step(actions: Any) -> None:
        actions.go_to("decide_step")

    @bp.decide(["fast", "slow"], fallback="slow", name="decide_step")
    async def decide_step() -> str:
        return "fast"

    @bp.handler("fast")
    async def fast_step(actions: Any) -> None:
        actions.go_to("end_step")

    @bp.handler("slow")
    async def slow_step(actions: Any) -> None:
        actions.go_to("end_step")

    @bp.end("end_step")
    async def end_step() -> None:
        pass

    bp.validate()
    dag = bp.to_dag()

    # Check DAG metadata
    assert dag["blueprint_name"] == "linear_decide_bp"
    assert dag["start_state"] == "start_step"

    node_ids = {n["id"] for n in dag["nodes"]}
    assert "start_step" in node_ids
    assert "decide_step" in node_ids
    assert "fast" in node_ids
    assert "slow" in node_ids
    assert "end_step" in node_ids

    # Verify decider node type and properties
    decide_node = next(n for n in dag["nodes"] if n["id"] == "decide_step")
    assert decide_node["type"] == "decider"
    assert set(decide_node["candidates"]) == {"fast", "slow"}
    assert decide_node["fallback"] == "slow"

    # Verify edges
    edge_pairs = {(e["from"], e["to"]) for e in dag["edges"]}
    assert ("start_step", "decide_step") in edge_pairs
    assert ("decide_step", "fast") in edge_pairs
    assert ("decide_step", "slow") in edge_pairs
    assert ("fast", "end_step") in edge_pairs
    assert ("slow", "end_step") in edge_pairs

    # Verify fallback edge property
    fallback_edge = next(e for e in dag["edges"] if e["from"] == "decide_step" and e["to"] == "slow")
    assert fallback_edge.get("is_fallback") is True


def test_blueprint_to_dag_single_step() -> None:
    bp = Blueprint("single_step_bp")

    @bp.handler("start_end", is_start=True, is_end=True)
    async def start_end() -> None:
        pass

    bp.validate()
    dag = bp.to_dag()
    assert len(dag["nodes"]) == 1
    assert dag["nodes"][0]["id"] == "start_end"
    assert dag["nodes"][0]["is_start"] is True
    assert dag["nodes"][0]["is_end"] is True
    assert len(dag["edges"]) == 0


def create_dag_test_bp() -> Blueprint:
    bp = Blueprint("api_dag_bp", api_endpoint="/api_dag", api_version="v1")

    @bp.start("step_1")
    async def step_1(actions: Any) -> None:
        actions.go_to("step_2")

    @bp.end("step_2")
    async def step_2() -> None:
        pass

    bp.validate()
    return bp


@pytest.mark.parametrize("app", [{"extra_blueprints": [create_dag_test_bp()]}], indirect=True)
@pytest.mark.asyncio
async def test_api_get_blueprint_dag(aiohttp_client, app) -> None:
    client = await aiohttp_client(app)
    headers = {"X-Client-Token": "user_token_vip"}

    # 1. Existing blueprint DAG
    resp = await client.get("/api/v1/blueprints/api_dag_bp/dag", headers=headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["blueprint_name"] == "api_dag_bp"
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["edges"][0]["from"] == "step_1"
    assert data["edges"][0]["to"] == "step_2"

    # 2. Unknown blueprint returns 404
    resp_404 = await client.get("/api/v1/blueprints/unknown_non_existent/dag", headers=headers)
    assert resp_404.status == 404
