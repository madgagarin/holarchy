# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from os.path import join
from shutil import rmtree
from tempfile import mkdtemp

from pytest import mark

from holarchy.config import Config
from holarchy.engine import OrchestratorEngine
from holarchy.storage.memory import MemoryStorage

BLUEPRINT_CONTENT = """
from holarchy.blueprint import Blueprint

dynamic_bp = Blueprint(name="dynamic_test_blueprint", api_endpoint="/jobs/dynamic_test")

@dynamic_bp.start("start")
async def start_handler(actions):
    actions.go_to("end")

@dynamic_bp.end("end")
async def end_handler():
    pass
"""


@mark.asyncio
async def test_dynamic_blueprint_loading():
    # Create a temporary directory for blueprints
    tmp_dir = mkdtemp()
    try:
        bp_file_path = join(tmp_dir, "test_bp.py")
        with open(bp_file_path, "w") as f:
            f.write(BLUEPRINT_CONTENT)

        config = Config()
        config.BLUEPRINTS_DIR = tmp_dir

        storage = MemoryStorage()
        engine = OrchestratorEngine(storage, config)

        # This should trigger the loader
        engine.setup()

        assert "dynamic_test_blueprint" in engine.blueprints
        bp = engine.blueprints["dynamic_test_blueprint"]
        assert bp.name == "dynamic_test_blueprint"
        assert bp.start_state == "start"
        assert "end" in bp.end_states

    finally:
        rmtree(tmp_dir)


@mark.asyncio
async def test_blueprint_loader_ignores_non_blueprints():
    tmp_dir = mkdtemp()
    try:
        # Create a file with NO blueprints
        bp_file_path = join(tmp_dir, "not_a_bp.py")
        with open(bp_file_path, "w") as f:
            f.write("x = 10\ndef foo(): pass")

        config = Config()
        config.BLUEPRINTS_DIR = tmp_dir
        storage = MemoryStorage()
        engine = OrchestratorEngine(storage, config)

        engine.setup()

        # Should remain empty (or at least not contain anything from that file)
        assert len(engine.blueprints) == 0

    finally:
        rmtree(tmp_dir)
