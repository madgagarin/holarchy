# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from asyncio import CancelledError, create_task, sleep
from contextlib import suppress

from aiohttp import ClientSession, web
from pytest import importorskip, mark

importorskip("holonode")

from holonode.config import WorkerConfig
from holonode.worker import Worker
from rxon.constants import AUTH_HEADER_CLIENT

from holarchy.blueprint import Blueprint
from holarchy.config import Config as OrchestratorConfig
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage


@mark.asyncio
async def test_e2e_orchestrator_and_worker_execution(monkeypatch):
    secret_key = "e2e-secret-key-12345"
    worker_token = "e2e-worker-token-67890"
    client_token = "e2e-client-token"

    monkeypatch.setenv("ORCHESTRATOR_SECRET_KEY", secret_key)
    monkeypatch.setenv("GLOBAL_WORKER_TOKEN", worker_token)
    monkeypatch.setenv("CLIENT_TOKEN", client_token)

    orch_config = OrchestratorConfig()
    orch_config.ORCHESTRATOR_SECRET_KEY = secret_key
    orch_config.GLOBAL_WORKER_TOKEN = worker_token
    orch_config.CLIENT_TOKEN = client_token
    orch_config.POLL_TIMEOUT_SECONDS = 0.5
    orch_config.WORKER_POLL_TIMEOUT_SECONDS = 0.5

    storage = MemoryStorage()
    engine = OrchestratorEngine(storage, orch_config)

    bp = Blueprint("e2e_math_flow", api_endpoint="/jobs/e2e_math_flow", api_version="v1")

    @bp.handler("init", is_start=True)
    async def init_step(actions, initial_data):
        actions.dispatch_task(
            "multiply_skill",
            {"x": initial_data["x"], "y": initial_data["y"]},
            transitions={"success": "finished"},
        )

    @bp.handler("finished", is_end=True)
    async def finish_step(actions, context):
        pass

    engine.register_blueprint(bp)
    engine.setup()

    runner = web.AppRunner(engine.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    orch_url = f"http://127.0.0.1:{port}"

    worker_cfg = WorkerConfig()
    worker_cfg.WORKER_ID = "e2e-test-worker"
    worker_cfg.WORKER_TOKEN = worker_token
    worker_cfg.ORCHESTRATORS = [{"url": orch_url, "token": worker_token, "weight": 1.0}]
    worker_cfg.HEARTBEAT_INTERVAL = 0.5
    worker_cfg.IDLE_POLL_DELAY = 0.05
    worker_cfg.TASK_POLL_TIMEOUT = 1.0
    worker_cfg.MAX_CONCURRENT_TASKS = 5
    worker_cfg.REQUIRE_TASK_SIGNATURE = True
    worker_cfg.SECRET_KEY = secret_key

    worker = Worker(config=worker_cfg)

    @worker.skill(name="multiply_skill")
    async def multiply(params: dict) -> dict:
        return {"status": "success", "data": {"result": params["x"] * params["y"]}}

    worker_task = create_task(worker.main())

    try:
        registered_workers = []
        for _ in range(50):
            registered_workers = await storage.get_workers(["e2e-test-worker"])
            if registered_workers:
                break
            await sleep(0.1)
        assert len(registered_workers) == 1, "Worker did not register with orchestrator"

        async with (
            ClientSession() as session,
            session.post(
                f"{orch_url}/api/v1/jobs/e2e_math_flow",
                json={"initial_data": {"x": 6, "y": 7}},
                headers={AUTH_HEADER_CLIENT: client_token},
            ) as resp,
        ):
            assert resp.status == 202, f"Failed to start job: {resp.status} {await resp.text()}"
            body = await resp.json()
            job_id = body["job_id"]

        assert job_id is not None

        final_state = None
        for _ in range(60):
            final_state = await storage.get_job_state(job_id)
            if final_state and final_state.get("status") in ("finished", "failed"):
                break
            await sleep(0.1)

        assert final_state is not None
        assert final_state.get("status") == "finished", f"Job failed or did not finish: {final_state}"
        assert "state_history" in final_state
        assert final_state["state_history"].get("result") == 42

    finally:
        worker._shutdown_event.set()
        with suppress(Exception, CancelledError):
            await worker_task
        await runner.cleanup()
