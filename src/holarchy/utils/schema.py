# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin

from contextlib import suppress
from typing import Any, cast


def orchestrator_extract_json_schema(schema_type: Any) -> dict[str, Any] | None:
    """Orchestrator-side schema extractor with duck-typing support for Pydantic models."""
    if isinstance(schema_type, type):
        if hasattr(schema_type, "model_json_schema") and callable(schema_type.model_json_schema):
            with suppress(Exception):
                return cast(dict[str, Any], schema_type.model_json_schema())
        if hasattr(schema_type, "schema") and callable(schema_type.schema):
            with suppress(Exception):
                return cast(dict[str, Any], schema_type.schema())
    return None
