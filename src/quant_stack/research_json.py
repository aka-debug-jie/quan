"""Versioned, explicit JSON encoding for research artifacts (never default=str)."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import TypeAlias

import numpy as np

JSONValue: TypeAlias = bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None
SERIALIZER_VERSION = "1.0.0"


def normalize_json(value: object) -> JSONValue:
    """Encode supported types explicitly; reject naive timestamps and nonfinite numbers."""
    if isinstance(value, Enum):
        return normalize_json(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("research timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite Decimal")
        return str(value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (np.bool_, np.integer, np.floating)):
        return normalize_json(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON number; use a schema-defined metric status")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("research JSON keys must be strings")
        return {key: normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    raise TypeError(f"unsupported research JSON type: {type(value).__name__}")


def canonical_json(value: object) -> bytes:
    """Return deterministic UTF-8 JSON with no implicit conversions or nonstandard numbers."""
    return json.dumps(
        normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
