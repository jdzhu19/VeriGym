"""Secret-key redaction for any future environment/config summaries."""

from __future__ import annotations

import fnmatch
from collections.abc import Mapping
from typing import Any

DEFAULT_SECRET_PATTERNS = ("*_API_KEY", "*_TOKEN", "*_PASSWORD", "*SECRET*")


def redact_mapping(
    values: Mapping[str, Any], patterns: tuple[str, ...] = DEFAULT_SECRET_PATTERNS
) -> dict[str, Any]:
    """Recursively redact values whose keys match case-insensitive secret patterns."""

    redacted: dict[str, Any] = {}
    upper_patterns = tuple(pattern.upper() for pattern in patterns)
    for key, value in values.items():
        if any(fnmatch.fnmatchcase(key.upper(), pattern) for pattern in upper_patterns):
            redacted[key] = "<redacted>"
        elif isinstance(value, Mapping):
            redacted[key] = redact_mapping(value, patterns)
        elif isinstance(value, list):
            redacted[key] = [
                redact_mapping(item, patterns) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted
