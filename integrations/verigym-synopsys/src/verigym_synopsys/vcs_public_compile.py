"""Compile-only Synopsys VCS backend for sanitized iterative feedback."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    CommandSpec,
    CompletedCommand,
    ErrorCategory,
    HealthCheckResult,
    StrictModel,
    ToolContext,
    ToolDescriptor,
    ToolPlugin,
    ToolResult,
    ToolVisibility,
)

from .common import (
    license_failure,
    redact,
    resolve_executable,
    safe_executable,
    safe_relative_path,
    vcs_environment,
)
from .vcs import probe_vcs

_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_SOURCE_BYTES = 32 * 1024 * 1024
_MAX_LOG_BYTES = 8 * 1024 * 1024
_ERROR_CODE = re.compile(r"Error-\[([A-Za-z0-9_-]{1,64})\]")
_STAGED_LOCATION = re.compile(
    r"input/(?P<index>[0-9]{3})\.(?:sv|v)[\"']?\s*(?:,|:)\s*(?P<line>[0-9]{1,9})"
)


class VcsPublicCompileRequest(StrictModel):
    test_id: Literal["compile"] = "compile"
    sources: list[str] = Field(min_length=1, max_length=64)
    top: str
    executable: str = "vcs"
    timeout_s: int = Field(default=30, ge=1, le=300)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        normalized = [safe_relative_path(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("VCS public compile sources must be unique")
        if any(Path(item).suffix.lower() not in {".v", ".sv"} for item in normalized):
            raise ValueError("VCS public compile sources must use Verilog filenames")
        return normalized

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value) is None:
            raise ValueError("invalid VCS public compile top module")
        return value

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        return safe_executable(value)


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="synopsys.vcs.public-compile",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-synopsys",
        capabilities=["compile", "systemverilog", "licensed", "structured_errors"],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


def _bounded_file(root: Path, relative: str) -> bytes:
    path = root / safe_relative_path(relative)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)) or path.is_symlink():
        raise ValueError("VCS public compile input escapes the runtime session")
    if not path.is_file() or path.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError("VCS public compile input is missing or too large")
    return path.read_bytes()


def _project_diagnostics(log: str, sources: list[str]) -> list[str]:
    """Return only controlled source names, line numbers, and VCS diagnostic codes."""

    diagnostics: list[str] = []
    last_code: str | None = None
    for raw_line in log.splitlines():
        code_match = _ERROR_CODE.search(raw_line)
        if code_match is not None:
            last_code = code_match.group(1)
        location = _STAGED_LOCATION.search(raw_line)
        if location is None:
            continue
        index = int(location.group("index"))
        if index >= len(sources):
            continue
        code = last_code or "COMPILE"
        item = f"{sources[index]}:{int(location.group('line'))}: VCS Error-[{code}]"
        if item not in diagnostics:
            diagnostics.append(item)
        if len(diagnostics) >= 32:
            break
    return diagnostics


class VcsPublicCompileTool(ToolPlugin):
    descriptor = _descriptor()

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        return probe_vcs(os.environ.get("VERIGYM_VCS_EXECUTABLE", "vcs"))

    def validate_request(self, request: dict[str, object]) -> VcsPublicCompileRequest:
        return VcsPublicCompileRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, VcsPublicCompileRequest)
        if context.session is None:
            raise ValueError("VCS public compile requires a runtime session")
        stage = ".verigym_internal/vcs-public-compile"
        staged: list[str] = []
        total = 0
        for index, relative in enumerate(request.sources):
            payload = _bounded_file(context.session.root, relative)
            total += len(payload)
            if total > _MAX_TOTAL_SOURCE_BYTES:
                raise ValueError("VCS public compile inputs exceed the aggregate byte limit")
            suffix = Path(relative).suffix.lower()
            target = f"{stage}/input/{index:03d}{suffix}"
            context.session.write_file(target, payload)
            staged.append(f"input/{index:03d}{suffix}")
        context.session.write_file(f"{stage}/out/.verigym_keep", b"")
        requested = (
            os.environ.get("VERIGYM_VCS_EXECUTABLE", request.executable)
            if request.executable == "vcs"
            else request.executable
        )
        executable = resolve_executable(requested, home_variable="VCS_HOME")
        return CommandSpec(
            argv=[
                executable,
                "-full64",
                "-sverilog",
                "-Mdir=csrc",
                "-o",
                "out/simv",
                "-l",
                "out/vcs.log",
                "-top",
                request.top,
                *staged,
            ],
            cwd=stage,
            env=vcs_environment(executable),
            timeout_s=request.timeout_s,
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, VcsPublicCompileRequest)
        log = ""
        if context.session is not None:
            path = context.session.root / ".verigym_internal/vcs-public-compile/out/vcs.log"
            if path.is_file() and path.stat().st_size <= _MAX_LOG_BYTES:
                log = path.read_text(encoding="utf-8", errors="replace")
        combined = redact("\n".join((completed.stdout, completed.stderr, log)))
        diagnostics = _project_diagnostics(combined, request.sources)
        category: ErrorCategory | None = None
        message = ""
        candidate_failure = False
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error.lower()
                else ErrorCategory.SANDBOX_ERROR
            )
            message = "the approved VCS public compiler could not be launched"
        elif completed.oom_killed:
            category = ErrorCategory.OUT_OF_MEMORY
            message = "VCS public compilation exceeded its memory bound"
        elif completed.timed_out:
            category = ErrorCategory.TIMEOUT
            message = "VCS public compilation exceeded its time bound"
        elif completed.output_truncated:
            category = ErrorCategory.OUTPUT_LIMIT
            message = "VCS public compilation exceeded its output bound"
        elif license_failure(combined):
            category = ErrorCategory.LICENSE_UNAVAILABLE
            message = "Synopsys VCS could not obtain a license"
        elif completed.exit_code != 0:
            category = ErrorCategory.COMPILE_FAILED
            message = "candidate RTL could not be compiled by VCS"
            candidate_failure = True
        if category is not None:
            if candidate_failure and not diagnostics:
                diagnostics = ["VCS compile rejected candidate RTL"]
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=category,
                message=message,
                exit_code=completed.exit_code,
                duration_s=completed.duration_s,
                output_truncated=completed.output_truncated,
                diagnostics=diagnostics,
                metadata={"candidate_failure": candidate_failure},
            )
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="VCS public compile passed",
            exit_code=completed.exit_code,
            duration_s=completed.duration_s,
            metadata={"candidate_failure": False},
        )

    def execute(self, raw_request: dict[str, object], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        try:
            return super().execute(raw_request, context)
        except Exception:
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.INVALID_REQUEST,
                message="the fixed VCS public compile request was invalid",
                duration_s=time.monotonic() - started,
                metadata={"candidate_failure": False},
            )


__all__ = ["VcsPublicCompileRequest", "VcsPublicCompileTool", "_project_diagnostics"]
