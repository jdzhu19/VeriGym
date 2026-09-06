"""Verilator compile/lint plugin with a fixed, shell-free request surface."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from verigym.core.workspace import WorkspacePolicy, normalize_relative_path
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ErrorCategory, ToolDescriptor, ToolVisibility
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.tools.base import ToolContext, ToolPlugin

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_DIAGNOSTIC = re.compile(
    r"%(?P<severity>Error|Warning)(?:-(?P<code>[A-Z0-9_]+))?:\s*"
    r"(?P<path>[^:\r\n]+):(?P<line>[0-9]{1,9})(?::(?P<column>[0-9]{1,9}))?"
)
_LANGUAGE_FLAGS = {"2005": "1364-2005", "2012": "1800-2012"}


class VerilatorCompileRequest(StrictModel):
    """Candidate-controlled paths plus a fixed Verilator lint policy."""

    sources: list[str] = Field(min_length=1, max_length=64)
    top: str
    language: Literal["2005", "2012"] = "2012"
    timeout_s: int = Field(default=30, ge=1, le=300)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, values: list[str]) -> list[str]:
        normalized = [normalize_relative_path(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Verilator compile sources must be unique")
        if any(PurePosixPath(value).suffix.lower() not in {".v", ".sv"} for value in normalized):
            raise ValueError("Verilator compile sources must use Verilog filenames")
        return normalized

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid Verilator top module")
        return value


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="verilator.compile",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "compile",
            "lint",
            "verilog",
            "systemverilog",
            "structured_errors",
            "shell_free",
        ],
        visibility=ToolVisibility.BOTH,
    )


def _health() -> HealthCheckResult:
    executable = shutil.which("verilator")
    if executable is None:
        return HealthCheckResult(
            healthy=False,
            message="verilator was not found on PATH",
        )
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return HealthCheckResult(
            healthy=False,
            message="verilator version probe failed",
            executable=executable,
        )
    version = next(
        (
            line.strip()
            for line in (completed.stdout + "\n" + completed.stderr).splitlines()
            if line.strip()
        ),
        None,
    )
    return HealthCheckResult(
        healthy=completed.returncode == 0 and version is not None,
        message="available" if completed.returncode == 0 else "verilator version probe failed",
        version=version,
        executable=executable,
    )


def _project_diagnostics(output: str, sources: list[str]) -> list[str]:
    by_name = {PurePosixPath(source).name: source for source in sources}
    diagnostics: list[str] = []
    for match in _DIAGNOSTIC.finditer(output):
        source = by_name.get(PurePosixPath(match.group("path").strip()).name)
        if source is None:
            continue
        code = match.group("code") or match.group("severity").upper()
        location = f"{source}:{int(match.group('line'))}"
        column = match.group("column")
        if column is not None:
            location += f":{int(column)}"
        item = f"{location}: Verilator {match.group('severity')}-[{code}]"
        if item not in diagnostics:
            diagnostics.append(item)
        if len(diagnostics) >= 32:
            break
    return diagnostics


class VerilatorCompileTool(ToolPlugin):
    """Run Verilator's parser/elaborator/linter without C++ generation or simulation."""

    descriptor = _descriptor()

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        return _health()

    def validate_request(self, request: dict[str, Any]) -> VerilatorCompileRequest:
        return VerilatorCompileRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, VerilatorCompileRequest)
        if context.session is None:
            raise ValueError("Verilator compile requires a runtime session")
        sources: list[str] = []
        for raw_source in request.sources:
            source = normalize_relative_path(raw_source)
            if isinstance(context.workspace_policy, WorkspacePolicy):
                source = context.workspace_policy.check_read(source)
            context.session.read_file(source)
            sources.append(source)
        return CommandSpec(
            argv=[
                "verilator",
                "--lint-only",
                "--timing",
                "-Wno-fatal",
                "-Wno-BLKANDNBLK",
                "--bbox-unsup",
                "--language",
                _LANGUAGE_FLAGS[request.language],
                "--top-module",
                request.top,
                *sources,
            ],
            cwd=".",
            timeout_s=request.timeout_s,
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        del context
        assert isinstance(request, VerilatorCompileRequest)
        diagnostics = _project_diagnostics(
            "\n".join((completed.stdout, completed.stderr)),
            request.sources,
        )
        category: ErrorCategory | None = None
        message = ""
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error.lower()
                else ErrorCategory.SANDBOX_ERROR
            )
            message = "Verilator could not be launched"
        elif completed.oom_killed:
            category = ErrorCategory.OUT_OF_MEMORY
            message = "Verilator compile exceeded its memory bound"
        elif completed.timed_out:
            category = ErrorCategory.TIMEOUT
            message = "Verilator compile exceeded its time bound"
        elif completed.output_truncated:
            category = ErrorCategory.OUTPUT_LIMIT
            message = "Verilator compile exceeded its output bound"
        elif completed.exit_code != 0:
            category = ErrorCategory.COMPILE_FAILED
            message = "candidate RTL could not be compiled by Verilator"
        if category is not None:
            if category == ErrorCategory.COMPILE_FAILED and not diagnostics:
                diagnostics = ["Verilator compile rejected candidate RTL"]
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=category,
                message=message,
                exit_code=completed.exit_code,
                duration_s=completed.duration_s,
                output_truncated=completed.output_truncated,
                diagnostics=diagnostics,
                metadata={"mode": "lint_only", "top": request.top},
            )
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="Verilator compile/lint passed",
            exit_code=completed.exit_code,
            duration_s=completed.duration_s,
            diagnostics=diagnostics,
            metadata={"mode": "lint_only", "top": request.top},
        )


def builtin_verilator_tools() -> list[ToolPlugin]:
    return [VerilatorCompileTool()]


__all__ = [
    "VerilatorCompileRequest",
    "VerilatorCompileTool",
    "builtin_verilator_tools",
]
