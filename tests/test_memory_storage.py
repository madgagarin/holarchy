# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from pytest import fixture

from holarchy.storage.memory import MemoryStorage

from .storage_test_suite import StorageTestSuite


@fixture
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
