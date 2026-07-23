"""Explicit compatibility dispatch for persistent top-level schemas."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from verigym.core.errors import SchemaCompatibilityError
from verigym.schemas.base import SCHEMA_VERSION

_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_CURRENT_MAJOR, _CURRENT_MINOR = (int(part) for part in SCHEMA_VERSION.split("."))


def validate_schema_version(
    payload: Any,
    model_type: type[BaseModel],
    *,
    artifact: str,
) -> None:
    """Validate a raw persistent object before Pydantic consumes it.

    Only models that declare a top-level ``schema_version`` participate. This
    keeps ordinary nested model parsing unchanged while ensuring persistent
    readers never accept a version through a Pydantic default or silently drop
    fields from a supposedly compatible future format.
    """

    if "schema_version" not in model_type.model_fields:
        return
    if not isinstance(payload, dict):
        raise SchemaCompatibilityError(
            f"{artifact} must be a JSON object with an explicit schema_version",
            category="schema_shape",
        )
    if "schema_version" not in payload:
        raise SchemaCompatibilityError(
            f"{artifact} is missing required schema_version",
            category="schema_version_missing",
        )
    raw_version = payload["schema_version"]
    if not isinstance(raw_version, str) or _VERSION.fullmatch(raw_version) is None:
        raise SchemaCompatibilityError(
            f"{artifact} has malformed schema_version {raw_version!r}",
            category="schema_version_malformed",
        )
    major, minor = (int(part) for part in raw_version.split("."))
    if major != _CURRENT_MAJOR:
        raise SchemaCompatibilityError(
            f"{artifact} uses unsupported schema major {major}; "
            f"this reader supports {_CURRENT_MAJOR}.x",
            category="schema_major_unsupported",
        )
    # No earlier or later 1.x writer has shipped. Accepting one would require
    # an explicit migration/dispatch branch here, even if its fields look valid.
    if minor != _CURRENT_MINOR:
        raise SchemaCompatibilityError(
            f"{artifact} uses unsupported schema minor {raw_version}; "
            f"this reader supports {SCHEMA_VERSION}",
            category="schema_minor_unsupported",
        )


__all__ = ["validate_schema_version"]
