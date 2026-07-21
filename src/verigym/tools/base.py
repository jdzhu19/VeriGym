"""Tool plugin contract and execution context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from verigym.runtimes.base import RuntimeSession
from verigym.schemas.common import ToolDescriptor
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult


@dataclass(frozen=True)
class ToolContext:
    session: RuntimeSession | None = None
    workspace_policy: Any | None = None
    max_output_bytes: int = 1_000_000
    artifact_dir: Path | None = None


class ToolPlugin(ABC):
    descriptor: ToolDescriptor

    @abstractmethod
    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        """Check external dependencies and configuration."""

    @abstractmethod
    def validate_request(self, request: dict[str, Any]) -> BaseModel:
        """Validate an untrusted structured request."""

    @abstractmethod
    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        """Render a safe argument-array command."""

    @abstractmethod
    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        """Normalize command output into the stable error taxonomy."""

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate_request(raw_request)
        command = self.build_command(request, context)
        if command.requires_shell:
            raise ValueError(f"tool {self.descriptor.name} requested a shell unexpectedly")
        if context.session is None:
            raise ValueError(f"tool {self.descriptor.name} requires a runtime session")
        completed = context.session.execute(command)
        return self.parse_result(request, completed, context)
