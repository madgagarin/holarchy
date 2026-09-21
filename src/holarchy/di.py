# Copyright (c) 2025-2026 Dmitry Gagarin aka madgagarin
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import types
from typing import Annotated, Any, Union, get_args, get_origin

from rxon.schema import Header


def is_header_annotation(ann: Any) -> bool:
    """Checks whether an annotation or default value has a Header marker."""
    if isinstance(ann, Header) or getattr(ann, "is_header", False):
        return True
    if get_origin(ann) is Annotated:
        for meta in get_args(ann)[1:]:
            if isinstance(meta, Header) or getattr(meta, "is_header", False):
                return True
    return False


def extract_header_marker(ann: Any, default_name: str | None = None) -> tuple[str, type, Any] | None:
    """Extracts (header_name, target_type, default_val) from an annotation or Header instance.

    Returns:
        tuple (header_name, target_type, default_val) or None
    """
    if isinstance(ann, Header) or getattr(ann, "is_header", False):
        header_name = getattr(ann, "name", None) or (default_name.replace("_", "-") if default_name else "")
        return header_name, Any, getattr(ann, "default", ...)

    if get_origin(ann) is Annotated:
        args = get_args(ann)
        target_type = args[0]
        for meta in args[1:]:
            if isinstance(meta, Header) or getattr(meta, "is_header", False):
                header_name = getattr(meta, "name", None) or (default_name.replace("_", "-") if default_name else "")
                return header_name, target_type, getattr(meta, "default", ...)
    return None


def find_header_in_dict(headers: dict[str, Any] | None, header_name: str) -> Any | None:
    """Case-insensitive lookup for header in a dict of headers."""
    if not headers or not header_name:
        return None
    if header_name in headers:
        return headers[header_name]

    target_lower = header_name.lower()
    for k, v in headers.items():
        if k.lower() == target_lower:
            return v

    target_alt = target_lower.replace("-", "_")
    for k, v in headers.items():
        if k.lower().replace("-", "_") == target_alt:
            return v

    return None


def cast_header_value(val: Any, target_type: Any, default: Any = ...) -> Any:
    """Casts raw header string value to target type."""
    if val is None:
        return None if default is ... else default

    # Handle Union types (e.g. str | None, int | None, Union[int, None])
    origin = get_origin(target_type)
    if origin in (Union, types.UnionType):
        args = [arg for arg in get_args(target_type) if arg is not type(None)]
        if len(args) == 1:
            target_type = args[0]
        else:
            return val

    if target_type is int:
        try:
            return int(val)
        except (ValueError, TypeError):
            return default if default is not ... else val
    elif target_type is float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return default if default is not ... else val
    elif target_type is bool:
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        return default if default is not ... else bool(val)
    elif target_type is str or target_type is Any:
        return str(val)

    return val


__all__ = [
    "Header",
    "cast_header_value",
    "extract_header_marker",
    "find_header_in_dict",
    "is_header_annotation",
]
