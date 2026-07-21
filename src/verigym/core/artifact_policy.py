"""Small deterministic persistence bounds for model-visible trace content."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def bound_text(value: str, max_bytes: int) -> tuple[str, bool]:
    """Return a UTF-8-safe prefix and whether content was truncated."""

    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def bound_value(value: Any, max_bytes: int) -> tuple[Any, bool]:
    """Bound a JSON-compatible value, preserving only safe identity fields when oversized."""

    if isinstance(value, str):
        return bound_text(value, max_bytes)
    serialized = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    if len(serialized) <= max_bytes:
        return value, False
    summary: dict[str, Any] = {
        "content_omitted": True,
        "serialized_bytes": len(serialized),
    }
    if isinstance(value, Mapping):
        for key in ("schema_version", "type", "tool"):
            if key not in value:
                continue
            identity = value.get(key)
            if isinstance(identity, (str, int, float, bool)) or identity is None:
                summary[key] = identity
    return summary, True


__all__ = ["bound_text", "bound_value"]
