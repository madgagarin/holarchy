# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from logging import DEBUG, INFO, getLogger, handlers
from unittest.mock import patch

from pytest import fixture

from holarchy.logging_config import LogManager


@fixture
def log_manager():
    manager = LogManager()
    yield manager
    manager.stop()


def test_setup_logging_json(log_manager):
    """Tests that logging is set up correctly with LogManager."""
    with patch("logging.StreamHandler"):
        log_manager.setup_logging(log_level="DEBUG", log_format="json")
        logger = getLogger("holarchy")
        assert logger.level == DEBUG
        # In LogManager, it adds QueueHandler
        assert any(isinstance(h, handlers.QueueHandler) for h in logger.handlers)


def test_setup_logging_text(log_manager):
    """Tests that logging is set up correctly with LogManager in text mode."""
    with patch("logging.StreamHandler"):
        log_manager.setup_logging(log_level="INFO", log_format="text")
        logger = getLogger("holarchy")
        assert logger.level == INFO
        assert any(isinstance(h, handlers.QueueHandler) for h in logger.handlers)
