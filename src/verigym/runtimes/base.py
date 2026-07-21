"""Runtime and isolated session interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.runtime import SessionSpec, WorkspaceDiff
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult


class RuntimeSession(ABC):
    @property
    @abstractmethod
    def root(self) -> Path:
        """Private session workspace root."""

    @abstractmethod
    def execute(self, command: CommandSpec) -> CompletedCommand:
        """Execute an argument-array command inside the session."""

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read a path after enforcing the session boundary."""

    @abstractmethod
    def write_file(self, path: str, data: bytes) -> None:
        """Write a path after enforcing the session boundary."""

    @abstractmethod
    def snapshot_diff(self) -> WorkspaceDiff:
        """Compare the session to its initial source snapshot."""

    @abstractmethod
    def close(self) -> None:
        """Destroy all ephemeral session state."""


class Runtime(ABC):
    descriptor: RuntimeDescriptor

    @abstractmethod
    def health_check(self) -> HealthCheckResult:
        """Return runtime availability without creating a session."""

    @abstractmethod
    def create_session(self, spec: SessionSpec) -> RuntimeSession:
        """Create one isolated episode or verifier session."""
