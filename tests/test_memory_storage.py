import pytest
from src.holarchy.storage.memory import MemoryStorage

from .storage_test_suite import StorageTestSuite


@pytest.fixture
def storage():
    """
    Provides a MemoryStorage instance for the test suite.
    The fixture is named 'storage' to match the base class's expectations.
    """
    return MemoryStorage()


class TestMemoryStorage(StorageTestSuite):
    """
    Runs the common storage test suite for MemoryStorage, plus any
    MemoryStorage-specific tests.
    """

    pass
