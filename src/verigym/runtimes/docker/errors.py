"""Typed Docker control-plane, image, capability, and artifact errors."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from verigym.core.errors import RuntimeExecutionError

_SECRET_VALUE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH)[A-Z0-9_]*)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_DOCKER_SOCKET = re.compile(r"(?:unix://)?/(?:var/)?run/docker\.sock")


def sanitize_diagnostic(value: str, *, sensitive_paths: Iterable[str] = ()) -> str:
    """Remove secret-like values, socket locations, and private staging paths."""

    sanitized = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    sanitized = _DOCKER_SOCKET.sub("<docker-socket>", sanitized)
    private_paths = set(sensitive_paths)
    private_paths.add(str(Path.home()))
    for raw_path in sorted(private_paths, key=len, reverse=True):
        if raw_path:
            sanitized = sanitized.replace(raw_path, "<private-path>")
    return sanitized


class DockerRuntimeError(RuntimeExecutionError):
    """Base class retaining a structured Docker subreason and origin."""

    def __init__(
        self,
        message: str,
        *,
        subreason: str,
        origin: str = "control_plane",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.subreason = subreason
        self.origin = origin
        self.details = details or {}


class DockerUnavailableError(DockerRuntimeError):
    pass


class DockerDaemonError(DockerRuntimeError):
    pass


class DockerPermissionError(DockerRuntimeError):
    pass


class DockerImageError(DockerRuntimeError):
    pass


class DockerCapabilityError(DockerRuntimeError):
    pass


class DockerContainerError(DockerRuntimeError):
    pass


class DockerArtifactError(DockerRuntimeError):
    pass


__all__ = [
    "DockerArtifactError",
    "DockerCapabilityError",
    "DockerContainerError",
    "DockerDaemonError",
    "DockerImageError",
    "DockerPermissionError",
    "DockerRuntimeError",
    "DockerUnavailableError",
    "sanitize_diagnostic",
]
