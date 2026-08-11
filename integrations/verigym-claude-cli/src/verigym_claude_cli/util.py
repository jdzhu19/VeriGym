"""Deterministic serialization, atomic writes, and secret redaction."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from verigym.plugin_api import content_hash

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_API_KEY = re.compile(r"\b(?:sk|ds)-[A-Za-z0-9_-]{12,}\b")
_AUTH_HEADER = re.compile(r"(?i)(authorization[\"'=:\s]+)[^\s,\"'}]+")
_PROXY_CREDENTIAL = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
_SAFE_TOKEN_METADATA_KEYS = {
    "context_window_tokens",
    "expected_context_window_tokens",
    "input_tokens",
    "max_mcp_output_tokens",
    "model_token_limit",
    "model_token_limit_configured",
    "no_model_token_limit_configured",
    "output_tokens",
    "per_response_max_output_tokens",
    "total_tokens",
}


def stable_hash(value: Any) -> str:
    return content_hash(value)


def redact_text(text: str, *, roots: tuple[Path, ...] = ()) -> str:
    clean = _BEARER.sub("<redacted-bearer>", text)
    clean = _API_KEY.sub("<redacted-api-key>", clean)
    clean = _AUTH_HEADER.sub(r"\1<redacted>", clean)
    clean = _PROXY_CREDENTIAL.sub(r"\1<redacted>@", clean)
    for root in (Path.home(), *roots):
        clean = clean.replace(str(root), "<redacted-root>")
    return _CONTROL.sub(" ", clean)


def redact_value(value: Any, *, roots: tuple[Path, ...] = ()) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("secret", "password", "api_key")):
                clean[str(key)] = "<redacted>"
            elif "token" in lowered and lowered not in _SAFE_TOKEN_METADATA_KEYS:
                clean[str(key)] = "<redacted>"
            elif "reasoning" in lowered and isinstance(item, str) and item != "max":
                clean[str(key)] = "<discarded-reasoning>"
            else:
                clean[str(key)] = redact_value(item, roots=roots)
        return clean
    if isinstance(value, list):
        return [redact_value(item, roots=roots) for item in value]
    if isinstance(value, str):
        return redact_text(value, roots=roots)
    return value


def atomic_json(path: Path, value: Any) -> None:
    payload = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            default=_json_default,
        )
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ValueError("refusing to replace a symlink artifact")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"cannot serialize {type(value).__name__}")


__all__ = ["atomic_json", "redact_text", "redact_value", "stable_hash"]
