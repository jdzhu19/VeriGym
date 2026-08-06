"""Shared validation and redaction helpers for licensed host tools."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path, PurePosixPath

_ENVIRONMENT_NAMES = ("SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE", "VCS_HOME")
_EXECUTABLE = re.compile(r"(?:[A-Za-z0-9._+-]+|/[A-Za-z0-9._+/-]+)")


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def safe_executable(value: str) -> str:
    if not _EXECUTABLE.fullmatch(value) or ".." in Path(value).parts:
        raise ValueError("tool executable must be a simple name or canonical absolute path")
    return value


def resolve_executable(value: str, *, home_variable: str | None = None) -> str:
    safe_executable(value)
    if value.startswith("/"):
        return value
    found = shutil.which(value)
    if found is not None:
        return found
    if home_variable is not None:
        home = os.environ.get(home_variable)
        if home:
            candidate = Path(home) / "bin" / value
            if candidate.is_file():
                return str(candidate)
    return value


def licensed_environment() -> dict[str, str]:
    return {name: value for name in _ENVIRONMENT_NAMES if (value := os.environ.get(name))}


def vcs_environment(executable: str) -> dict[str, str]:
    environment = licensed_environment()
    path = Path(executable)
    if "VCS_HOME" not in environment and path.is_absolute() and path.parent.name == "bin":
        environment["VCS_HOME"] = str(path.parent.parent)
    return environment


def redact(text: str) -> str:
    cleaned = text
    for value in licensed_environment().values():
        if value:
            cleaned = cleaned.replace(value, "<redacted-license>")
            for component in value.split(":"):
                if "@" in component and len(component) >= 4:
                    cleaned = cleaned.replace(component, "<redacted-license>")
    cleaned = re.sub(r"\b[0-9]{2,6}@[A-Za-z0-9_.-]+\b", "<redacted-license>", cleaned)
    cleaned = re.sub(
        r"((?:SNPSLMD|LM)_LICENSE_FILE\s*[=:]\s*)\S+",
        r"\1<redacted-license>",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def license_failure(text: str) -> bool:
    lowered = text.lower()
    return (
        "license checkout failed" in lowered
        or "unable to checkout" in lowered
        or ("license" in lowered and any(word in lowered for word in ("denied", "unavailable")))
    )


__all__ = [
    "license_failure",
    "licensed_environment",
    "redact",
    "resolve_executable",
    "safe_executable",
    "safe_relative_path",
    "vcs_environment",
]
