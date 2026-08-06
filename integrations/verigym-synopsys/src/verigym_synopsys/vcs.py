"""Verifier-only Synopsys VCS simulation plugin."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
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

_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_SOURCE_BYTES = 32 * 1024 * 1024
_MAX_LOG_BYTES = 8 * 1024 * 1024
_VERSION = re.compile(
    r"(?:Compiler version|VCS)[^\n]*?([A-Z]-\d{4}\.\d{2}(?:-[A-Za-z0-9._-]+)?)",
    flags=re.IGNORECASE,
)


class VcsSimulationRequest(StrictModel):
    sources: list[str] = Field(min_length=1, max_length=64)
    testbench: str
    top: str | None = None
    pass_marker: str = "VERIGYM_PASS"
    fail_marker: str = "VERIGYM_FAIL"
    executable: str = "vcs"
    timeout_s: int = Field(default=120, ge=1, le=3600)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        normalized = [safe_relative_path(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("VCS sources must not contain duplicates")
        if any(Path(item).suffix.lower() not in {".v", ".sv"} for item in normalized):
            raise ValueError("VCS sources must use .v or .sv filenames")
        return normalized

    @field_validator("testbench")
    @classmethod
    def validate_testbench(cls, value: str) -> str:
        normalized = safe_relative_path(value)
        if Path(normalized).suffix.lower() not in {".v", ".sv"}:
            raise ValueError("the VCS testbench must use a .v or .sv filename")
        return normalized

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value):
            raise ValueError("invalid VCS top-module identifier")
        return value

    @field_validator("pass_marker", "fail_marker")
    @classmethod
    def validate_marker(cls, value: str) -> str:
        if not value or len(value) > 256 or "\x00" in value:
            raise ValueError("simulation markers must contain 1-256 safe characters")
        return value

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        return safe_executable(value)

    @model_validator(mode="after")
    def testbench_is_distinct(self) -> VcsSimulationRequest:
        if self.testbench in self.sources:
            raise ValueError("testbench must be separate from candidate sources")
        if self.pass_marker == self.fail_marker:
            raise ValueError("pass and fail markers must differ")
        return self


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="synopsys.vcs.simulate",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-synopsys",
        capabilities=["simulation", "systemverilog", "licensed", "structured_errors"],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


def _bounded_file(root: Path, relative: str) -> bytes:
    path = root / safe_relative_path(relative)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)) or path.is_symlink():
        raise ValueError("VCS input escapes the runtime session")
    if not path.is_file() or path.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError(f"VCS input is missing or too large: {relative}")
    return path.read_bytes()


def _version_from_output(value: str) -> str | None:
    matches = _VERSION.findall(redact(value))
    return max(matches, key=len) if matches else None


class VcsSimulationTool(ToolPlugin):
    descriptor = _descriptor()

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        requested = os.environ.get("VERIGYM_VCS_EXECUTABLE", "vcs")
        executable = resolve_executable(requested, home_variable="VCS_HOME")
        if shutil.which(executable) is None and not Path(executable).is_file():
            return HealthCheckResult(
                healthy=False,
                message="Synopsys VCS was not found on PATH or under VCS_HOME",
            )
        try:
            completed = subprocess.run(
                [executable, "-full64", "-ID"],
                capture_output=True,
                check=False,
                env={
                    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    **vcs_environment(executable),
                },
                shell=False,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return HealthCheckResult(
                healthy=False,
                message="Synopsys VCS identity probe failed",
                executable=executable,
            )
        output = redact(completed.stdout + "\n" + completed.stderr)
        version = _version_from_output(output)
        return HealthCheckResult(
            healthy=completed.returncode == 0 and version is not None,
            message=("available" if completed.returncode == 0 else "VCS identity probe failed"),
            version=version,
            executable=executable,
        )

    def validate_request(self, request: dict[str, Any]) -> VcsSimulationRequest:
        return VcsSimulationRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, VcsSimulationRequest)
        if context.session is None:
            raise ValueError("VCS simulation requires a runtime session")
        stage = ".verigym_internal/vcs"
        total = 0
        ordered = [request.testbench, *request.sources]
        staged: list[str] = []
        for index, relative in enumerate(ordered):
            payload = _bounded_file(context.session.root, relative)
            total += len(payload)
            if total > _MAX_TOTAL_SOURCE_BYTES:
                raise ValueError("VCS inputs exceed the aggregate byte limit")
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
        argv = [
            executable,
            "-full64",
            "-sverilog",
            "-Mdir=csrc",
            "-o",
            "out/simv",
            "-l",
            "out/vcs.log",
        ]
        if request.top is not None:
            argv.extend(["-top", request.top])
        argv.extend([*staged, "-R"])
        return CommandSpec(
            argv=argv,
            cwd=stage,
            env=vcs_environment(executable),
            timeout_s=request.timeout_s,
            artifact_globs=[f"{stage}/out/vcs.log"],
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, VcsSimulationRequest)
        log = ""
        if context.session is not None:
            path = context.session.root / ".verigym_internal/vcs/out/vcs.log"
            if path.is_file() and path.stat().st_size <= _MAX_LOG_BYTES:
                log = path.read_text(encoding="utf-8", errors="replace")
        stdout = redact(completed.stdout)
        stderr = redact(completed.stderr)
        sanitized_log = redact(log)
        artifacts: list[str] = []
        if sanitized_log and context.artifact_dir is not None:
            context.artifact_dir.mkdir(parents=True, exist_ok=True)
            (context.artifact_dir / "vcs.log").write_text(sanitized_log, encoding="utf-8")
            artifacts.append("vcs.log")
        combined = "\n".join((stdout, stderr, sanitized_log))
        category: ErrorCategory | None = None
        message = ""
        candidate_failure = False
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error.lower()
                else ErrorCategory.SANDBOX_ERROR
            )
            message = redact(completed.error)
        elif completed.oom_killed:
            category = ErrorCategory.OUT_OF_MEMORY
            message = "VCS was killed by the runtime memory limit"
        elif completed.timed_out:
            category = ErrorCategory.TIMEOUT
            message = "VCS compilation or simulation exceeded the command timeout"
        elif completed.output_truncated:
            category = ErrorCategory.OUTPUT_LIMIT
            message = "VCS command output exceeded the runtime limit"
        elif license_failure(combined):
            category = ErrorCategory.LICENSE_UNAVAILABLE
            message = "Synopsys VCS could not obtain a license"
        elif completed.exit_code != 0:
            category = ErrorCategory.COMPILE_FAILED
            message = "candidate RTL or the pinned testbench could not be compiled by VCS"
            candidate_failure = True
        elif request.fail_marker in combined or request.pass_marker not in combined:
            category = ErrorCategory.TEST_FAILED
            message = "VCS simulation did not report the required passing sentinel"
            candidate_failure = True
        if category is not None:
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=category,
                message=message,
                exit_code=completed.exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_s=completed.duration_s,
                output_truncated=completed.output_truncated,
                artifacts=artifacts,
                metadata={"candidate_failure": candidate_failure},
            )
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="VCS regression passed",
            exit_code=completed.exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=completed.duration_s,
            artifacts=artifacts,
        )

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        try:
            return super().execute(raw_request, context)
        except Exception as exc:
            message = redact(str(exc))
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.INVALID_REQUEST,
                message=message,
                stderr=message,
                duration_s=time.monotonic() - started,
                metadata={"candidate_failure": False},
            )


__all__ = ["VcsSimulationRequest", "VcsSimulationTool"]
