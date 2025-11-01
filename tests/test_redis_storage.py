import pytest

try:
    from .storage_test_suite import StorageTestSuite

    redis_installed = True
except ImportError:
    redis_installed = False

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not redis_installed,
        reason="redis package not installed, skipping redis-specific tests",
    ),
]


@pytest.fixture
def storage(redis_storage):
    """Binds the `redis_storage` fixture from conftest to the `storage` name."""
    return redis_storage


class TestRedisStorage(StorageTestSuite):
    """
    Runs the common storage test suite for RedisStorage.
    """

    pass
