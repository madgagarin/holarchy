# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from holarchy.blueprint import Blueprint

error_flow_bp = Blueprint(name="error_flow", api_endpoint="/jobs/error_flow", api_version="v1")


@error_flow_bp.start
async def start(input, actions):
    actions.dispatch_task(
        task_type="error_task",
        params={"error_type": input.get("error_type", "SUCCESS")},
        transitions={"success": "finished", "failure": "failed"},
    )


@error_flow_bp.end("finished")
async def finished(actions):
    pass


@error_flow_bp.end("failed")
async def failed(actions):
    pass
