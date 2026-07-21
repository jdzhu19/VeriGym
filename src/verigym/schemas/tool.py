"""Tool requests, command descriptions, and normalized results."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ErrorCategory, ToolDescriptor


class CommandSpec(StrictModel):
    argv: list[str]
    cwd: str = "."
    env: dict[str, str] = Field(default_factory=dict)
    timeout_s: int = Field(default=60, ge=1)
    stdin: str | None = None
    artifact_globs: list[str] = Field(default_factory=list)
    requires_shell: bool = False

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("argv cannot be empty")
        if any("\x00" in part for part in value):
            raise ValueError("argv cannot contain NUL bytes")
        return value


class CompletedCommand(StrictModel):
    argv: list[str]
    cwd: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_s: float = Field(default=0.0, ge=0.0)
    timed_out: bool = False
    output_truncated: bool = False
    error: str | None = None


class ToolResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    tool: str
    success: bool
    category: ErrorCategory
    message: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_s: float = Field(default=0.0, ge=0.0)
    output_truncated: bool = False
    artifacts: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthCheckResult(StrictModel):
    healthy: bool
    message: str
    version: str | None = None
    executable: str | None = None


__all__ = [
    "CommandSpec",
    "CompletedCommand",
    "HealthCheckResult",
    "ToolDescriptor",
    "ToolResult",
]
