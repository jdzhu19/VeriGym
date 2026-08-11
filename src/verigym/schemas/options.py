"""Bounded JSON-compatible options for external plugins."""

from __future__ import annotations

import json
import math
import re
from typing import Any, TypeAlias

from pydantic import JsonValue

JsonScalar: TypeAlias = str | int | float | bool | None

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_SECRET_KEY_PARTS = ("token", "secret", "password", "credential", "api_key", "auth")
_NON_SECRET_AUTH_IDENTITY_KEYS = {
    "expected_requested_auth_mode",
    "expected_resolved_auth_mode",
    "expected_auth_semantic_id",
    "max_output_tokens",
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@"),
)
_MAX_DEPTH = 8
_MAX_ITEMS = 256
_MAX_STRING_BYTES = 4096
_MAX_ENCODED_BYTES = 16 * 1024


def validate_plugin_options(value: Any) -> dict[str, JsonValue]:
    """Return a detached, bounded, secret-free JSON option mapping."""

    if not isinstance(value, dict):
        raise ValueError("plugin options must be a JSON object")
    count = [0]
    normalized = _validate_value(value, depth=0, count=count, key=None)
    assert isinstance(normalized, dict)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    if len(encoded) > _MAX_ENCODED_BYTES:
        raise ValueError(f"plugin options exceed {_MAX_ENCODED_BYTES} encoded bytes")
    return normalized


def _validate_value(
    value: Any,
    *,
    depth: int,
    count: list[int],
    key: str | None,
) -> JsonValue:
    if depth > _MAX_DEPTH:
        raise ValueError(f"plugin options exceed nesting depth {_MAX_DEPTH}")
    count[0] += 1
    if count[0] > _MAX_ITEMS:
        raise ValueError(f"plugin options exceed {_MAX_ITEMS} total values")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("plugin options require finite JSON numbers")
        return value
    if isinstance(value, str):
        return _validate_string(value, key=key)
    if isinstance(value, list):
        return [_validate_value(item, depth=depth + 1, count=count, key=key) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for nested_key, item in value.items():
            if not isinstance(nested_key, str) or not _KEY.fullmatch(nested_key):
                raise ValueError("plugin option keys must be 1-64 character safe ASCII identifiers")
            lowered = nested_key.lower()
            secret_key = (
                any(part in lowered for part in _SECRET_KEY_PARTS)
                and lowered not in _NON_SECRET_AUTH_IDENTITY_KEYS
            )
            if secret_key and not lowered.endswith("_env"):
                raise ValueError(
                    f"secret-bearing plugin option key {nested_key!r} is not permitted"
                )
            if secret_key and (not isinstance(item, str) or not _ENVIRONMENT_NAME.fullmatch(item)):
                raise ValueError(
                    f"plugin option {nested_key!r} may contain only an environment-variable name"
                )
            result[nested_key] = _validate_value(
                item,
                depth=depth + 1,
                count=count,
                key=nested_key,
            )
        return result
    raise ValueError("plugin options permit only JSON-compatible values")


def _validate_string(value: str, *, key: str | None) -> str:
    if len(value.encode("utf-8")) > _MAX_STRING_BYTES:
        raise ValueError(f"plugin option strings exceed {_MAX_STRING_BYTES} bytes")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("plugin option strings cannot contain control characters")
    if value.startswith(("/", "~/", "../", "./")) or _WINDOWS_ABSOLUTE.match(value):
        raise ValueError("plugin options cannot persist host or relative filesystem paths")
    if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
        raise ValueError("plugin options cannot contain credential-shaped values")
    if key is not None and key.lower().endswith("_env"):
        if not _ENVIRONMENT_NAME.fullmatch(value):
            raise ValueError(f"plugin option {key!r} requires an environment-variable name")
    return value


__all__ = ["JsonScalar", "JsonValue", "validate_plugin_options"]
