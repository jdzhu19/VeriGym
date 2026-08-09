"""Small deterministic hashing, JSON, validation, and redaction helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IDENTIFIER_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_API_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_AUTH_HEADER = re.compile(r"(?i)(authorization[\"'=:\s]+)[^\s,\"'}]+")
_PROXY_CREDENTIAL = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_SAFE_USAGE_KEYS = {
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "input_token_count",
    "output_token_count",
    "total_token_count",
}
_SAFE_REASONING_IDENTITIES = {
    "requested_reasoning_effort": {"max", "xhigh"},
    "effective_reasoning_effort": {"max", "xhigh"},
    "reasoning_effort_source": {"verigym_explicit_cli_override"},
}
_SAFE_SECURITY_BOOLEAN_KEYS = {
    "api_key_environment_forwarded",
    "credential_contents_accessed_by_verigym",
    "credential_files_mounted",
    "credential_values_persisted",
}
_SAFE_SECURITY_COUNT_KEYS = {
    "credential_files_copied",
}
_SAFE_ENVIRONMENT_NAME_KEYS = {
    "container_credential_environment_names",
    "credential_environment_names_in_container",
    "environment_names",
    "proxy_environment_names_in_container",
}


def stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"cannot encode {type(value).__name__}")


def clean_identifier(value: str, *, label: str, max_length: int = 256) -> str:
    if (
        not value
        or value != value.strip()
        or len(value) > max_length
        or _IDENTIFIER_CONTROL.search(value)
    ):
        raise ValueError(f"{label} must be a trimmed control-free identifier")
    return value


def redact_text(text: str, *, roots: tuple[Path, ...] = ()) -> str:
    clean = _BEARER.sub("<redacted-bearer>", text)
    clean = _API_KEY.sub("<redacted-api-key>", clean)
    clean = _AUTH_HEADER.sub(r"\1<redacted>", clean)
    clean = _PROXY_CREDENTIAL.sub(r"\1<redacted>@", clean)
    replacements = [Path.home(), *(root for root in roots if str(root))]
    for index, root in enumerate(replacements):
        label = "<home>" if index == 0 else "<runtime-root>"
        clean = clean.replace(str(root), label)
    return _CONTROL.sub(" ", clean)


def redact_value(value: Any, *, roots: tuple[Path, ...] = ()) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            safe_usage = lowered in _SAFE_USAGE_KEYS and (
                item is None or (isinstance(item, int) and not isinstance(item, bool) and item >= 0)
            )
            safe_security_boolean = lowered in _SAFE_SECURITY_BOOLEAN_KEYS and isinstance(
                item, bool
            )
            safe_security_count = (
                lowered in _SAFE_SECURITY_COUNT_KEYS
                and isinstance(item, int)
                and not isinstance(item, bool)
                and item >= 0
            )
            safe_environment_name_evidence = (
                lowered in _SAFE_ENVIRONMENT_NAME_KEYS
                and isinstance(item, list)
                and all(
                    isinstance(name, str) and _ENVIRONMENT_NAME.fullmatch(name) for name in item
                )
            )
            safe_reasoning_identity = (
                lowered in _SAFE_REASONING_IDENTITIES
                and isinstance(item, str)
                and item in _SAFE_REASONING_IDENTITIES[lowered]
            )
            if (
                not safe_usage
                and not safe_security_boolean
                and not safe_security_count
                and not safe_environment_name_evidence
                and not safe_reasoning_identity
                and any(
                    part in lowered
                    for part in ("token", "secret", "password", "credential", "api_key")
                )
            ):
                result[str(key)] = "<redacted>"
            elif not safe_reasoning_identity and "reasoning" in lowered and isinstance(item, str):
                result[str(key)] = "<discarded-reasoning>"
            else:
                result[str(key)] = redact_value(item, roots=roots)
        return result
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
    _atomic_text(path, payload)


def atomic_jsonl(path: Path, values: list[Any]) -> None:
    payload = "".join(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            default=_json_default,
        )
        + "\n"
        for value in values
    )
    _atomic_text(path, payload)


def atomic_text(path: Path, value: str) -> None:
    _atomic_text(path, value)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() and path.is_symlink():
            raise ValueError(f"refusing to replace symlink artifact: {path.name}")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def safe_regular_directory(path: Path, *, create: bool) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=False)
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("artifact destination must be a real directory")
    return path.resolve(strict=True)


__all__ = [
    "atomic_json",
    "atomic_jsonl",
    "atomic_text",
    "clean_identifier",
    "redact_text",
    "redact_value",
    "safe_regular_directory",
    "sha256_file",
    "stable_hash",
]
