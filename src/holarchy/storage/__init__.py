# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from contextlib import suppress

from .base import StorageBackend
from .memory import MemoryStorage

__all__ = ["StorageBackend", "MemoryStorage"]

with suppress(ImportError):
    from .redis import RedisStorage  # noqa: F401

    __all__.append("RedisStorage")
