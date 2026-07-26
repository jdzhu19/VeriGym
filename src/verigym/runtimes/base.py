"""Runtime and isolated session interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.external_agent import ExternalProcessRequest, ExternalProcessResult
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec, WorkspaceDiff
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

    def freeze(self) -> None:
        """Prevent further mutation before the canonical candidate handoff."""

        return None

    @property
    def external_process_backend(self) -> str:
        """Stable execution-owner label for external-agent bridges."""

        return "host_local_trusted"

    @property
    def logical_workspace_root(self) -> str:
        """Path vocabulary exposed to an external process."""

        return str(self.root)

    def execute_external_process(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        """Execute through the runtime when the backend supports external agents."""

        del request
        raise ValueError("this runtime does not execute external-agent processes")

    @abstractmethod
    def close(self) -> None:
        """Destroy all ephemeral session state."""


class Runtime(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> RuntimeDescriptor:
        """Stable runtime plugin and effective run descriptor."""

    @abstractmethod
    def health_check(self) -> HealthCheckResult:
        """Return runtime availability without creating a session."""

    @abstractmethod
    def create_session(self, spec: SessionSpec) -> RuntimeSession:
        """Create one isolated episode or verifier session."""

    def configure(self, config: DockerRuntimeConfig | None) -> Runtime:
        """Return a per-run runtime instance configured through a strict schema."""

        if config is not None:
            raise ValueError(f"runtime {self.descriptor.name!r} does not accept Docker options")
        return self

    def configure_for_replay(self, descriptor: RuntimeDescriptor) -> Runtime:
        """Return a runtime constrained by a stored descriptor."""

        if descriptor.name != self.descriptor.name:
            raise ValueError("stored runtime descriptor does not match the selected plugin")
        return self

    def prepare(self, run_id: str) -> None:
        """Resolve immutable run-level state before an agent or model action."""

        return None

    def environment_summary(self) -> dict[str, Any]:
        """Return credential-free runtime provenance for a run manifest."""

        return {}

    def close(self) -> None:
        """Release run-level resources; implementations must be idempotent."""

        return None
