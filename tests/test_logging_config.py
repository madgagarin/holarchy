# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

import logging
from unittest.mock import patch

import pytest

from holarchy.logging_config import LogManager


@pytest.fixture
def log_manager():
    manager = LogManager()
    yield manager
    manager.stop()


def test_setup_logging_json(log_manager):
    """Tests that logging is set up correctly with LogManager."""
    with patch("logging.StreamHandler"):
        log_manager.setup_logging(log_level="DEBUG", log_format="json")
        logger = logging.getLogger("holarchy")
        assert logger.level == logging.DEBUG
        # In LogManager, it adds QueueHandler
        assert any(isinstance(h, logging.handlers.QueueHandler) for h in logger.handlers)


def test_setup_logging_text(log_manager):
    """Tests that logging is set up correctly with LogManager in text mode."""
    with patch("logging.StreamHandler"):
        log_manager.setup_logging(log_level="INFO", log_format="text")
        logger = logging.getLogger("holarchy")
        assert logger.level == logging.INFO
        assert any(isinstance(h, logging.handlers.QueueHandler) for h in logger.handlers)
