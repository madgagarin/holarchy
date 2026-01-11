import logging
from unittest.mock import patch

import pytest

from holarchy.logging_config import TimezoneFormatter, TimezoneJsonFormatter, setup_logging


@pytest.fixture(autouse=True)
def clear_handlers():
    logger = logging.getLogger("holarchy")
    root = logging.getLogger()
    logger.handlers = []
    root.handlers = []
    yield
    logger.handlers = []
    root.handlers = []


def test_setup_logging_json():
    """Tests that logging is set up correctly with the JSON formatter."""
    with patch("logging.StreamHandler"):
        setup_logging(log_level="DEBUG", log_format="json")
        logger = logging.getLogger("holarchy")
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) > 0
        assert isinstance(logger.handlers[0].formatter, TimezoneJsonFormatter)


def test_setup_logging_text():
    """Tests that logging is set up correctly with the text formatter."""
    with patch("logging.StreamHandler"):
        setup_logging(log_level="INFO", log_format="text")
        logger = logging.getLogger("holarchy")
        assert logger.level == logging.INFO
        assert len(logger.handlers) > 0
        assert isinstance(logger.handlers[0].formatter, TimezoneFormatter)
