"""Narrow runtime-only bridge exposed to external coding-agent plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from verigym.schemas.external_agent import (
    ExternalAgentAccounting,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalReadOnlyMountIdentity,
)
from verigym.schemas.options import JsonValue
from verigym.schemas.tool import CommandSpec, CompletedCommand, ToolResult


class ExternalAgentBridge(Protocol):
    @property
    def workspace_root(self) -> Path: ...

    @property
    def artifact_root(self) -> Path: ...

    @property
    def isolation_level(self) -> str: ...

    @property
    def editable_globs(self) -> tuple[str, ...]: ...

    @property
    def readonly_globs(self) -> tuple[str, ...]: ...

    @property
    def execution_backend(self) -> str: ...

    @property
    def logical_workspace_root(self) -> str: ...

    @property
    def read_only_mounts(self) -> list[ExternalReadOnlyMountIdentity]: ...

    def execute_process(self, request: ExternalProcessRequest) -> ExternalProcessResult: ...

    def invoke_workspace_tool(
        self, tool_name: str, request: dict[str, JsonValue]
    ) -> ToolResult: ...

    def execute_command(self, command: CommandSpec) -> CompletedCommand: ...

    def execute_public_test(self, test_id: str) -> CompletedCommand: ...

    def emit_event(self, event_type: str, payload: dict[str, JsonValue]) -> None: ...

    def record_accounting(self, accounting: ExternalAgentAccounting) -> None: ...


__all__ = ["ExternalAgentBridge"]
