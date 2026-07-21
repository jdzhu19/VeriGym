"""Icarus Verilog compile, run, and visible-simulation plugins."""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from pydantic import BaseModel, Field, model_validator

from verigym.core.workspace import WorkspacePolicy, normalize_relative_path
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ErrorCategory, ToolDescriptor, ToolVisibility
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.tools.base import ToolContext, ToolPlugin


class IverilogCompileRequest(StrictModel):
    sources: list[str] = Field(min_length=1)
    top: str
    output: str = ".verigym_internal/compile/simv"
    language: str = "2012"
    timeout_s: int = Field(default=30, ge=1)


class IverilogRunRequest(StrictModel):
    executable: str | None = None
    executable_from: str | None = None
    pass_marker: str = "VERIGYM_PASS"
    fail_marker: str = "VERIGYM_FAIL"
    timeout_s: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def require_executable_reference(self) -> IverilogRunRequest:
        if self.executable is None and self.executable_from is None:
            raise ValueError("either executable or executable_from is required")
        return self


class IverilogSimulateRequest(StrictModel):
    sources: list[str] = Field(min_length=1)
    top: str
    pass_marker: str = "VERIGYM_PASS"
    fail_marker: str = "VERIGYM_FAIL"
    timeout_s: int = Field(default=30, ge=1)


def _descriptor(name: str, visibility: ToolVisibility, capability: str) -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name=name,
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[capability, "structured_errors", "artifacts"],
        visibility=visibility,
    )


def _health(executable: str) -> HealthCheckResult:
    resolved = shutil.which(executable)
    version: str | None = None
    if resolved is not None:
        try:
            completed = subprocess.run(
                [resolved, "-V"],
                capture_output=True,
                check=False,
                shell=False,
                text=True,
                timeout=5,
            )
            lines = [
                line.strip()
                for line in (completed.stdout + "\n" + completed.stderr).splitlines()
                if line.strip()
            ]
            version = lines[0] if lines else None
        except (OSError, subprocess.SubprocessError):
            version = None
    return HealthCheckResult(
        healthy=resolved is not None,
        message="available" if resolved else f"{executable} was not found on PATH",
        version=version,
        executable=resolved,
    )


def _validate_sources(request: IverilogCompileRequest, context: ToolContext) -> None:
    if context.session is None:
        raise ValueError("Icarus tools require a runtime session")
    policy = context.workspace_policy
    for source in request.sources:
        relative = normalize_relative_path(source)
        if isinstance(policy, WorkspacePolicy):
            relative = policy.check_read(relative)
        context.session.read_file(relative)


class IverilogCompileTool(ToolPlugin):
    descriptor = _descriptor("iverilog.compile", ToolVisibility.BOTH, "compile")

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        return _health("iverilog")

    def validate_request(self, request: dict[str, Any]) -> IverilogCompileRequest:
        return IverilogCompileRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, IverilogCompileRequest)
        _validate_sources(request, context)
        output = normalize_relative_path(request.output)
        assert context.session is not None
        (context.session.root / output).parent.mkdir(parents=True, exist_ok=True)
        executable = shutil.which("iverilog") or "iverilog"
        return CommandSpec(
            argv=[
                executable,
                f"-g{request.language}",
                "-s",
                request.top,
                "-o",
                output,
                *[normalize_relative_path(source) for source in request.sources],
            ],
            cwd=".",
            timeout_s=request.timeout_s,
            artifact_globs=[output],
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, IverilogCompileRequest)
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error
                else ErrorCategory.SANDBOX_ERROR
            )
            return _command_failure(self.descriptor.name, category, completed)
        if completed.timed_out:
            return _command_failure(self.descriptor.name, ErrorCategory.TIMEOUT, completed)
        if completed.output_truncated:
            return _command_failure(self.descriptor.name, ErrorCategory.OUTPUT_LIMIT, completed)
        if completed.exit_code != 0:
            return _command_failure(self.descriptor.name, ErrorCategory.COMPILE_FAILED, completed)
        output = normalize_relative_path(request.output)
        if context.session is None or not (context.session.root / output).is_file():
            return _command_failure(
                self.descriptor.name,
                ErrorCategory.PARSER_ERROR,
                completed,
                message="iverilog exited successfully but produced no executable",
            )
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="compilation passed",
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=completed.duration_s,
            artifacts=[output],
            metadata={"executable": output, "top": request.top},
        )


class IverilogRunTool(ToolPlugin):
    descriptor = _descriptor("iverilog.run", ToolVisibility.VERIFIER_ONLY, "simulation")

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        return _health("vvp")

    def validate_request(self, request: dict[str, Any]) -> IverilogRunRequest:
        return IverilogRunRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, IverilogRunRequest)
        if request.executable is None:
            raise ValueError("executable_from must be resolved by the verifier DAG")
        executable_path = normalize_relative_path(request.executable)
        if context.session is None:
            raise ValueError("Icarus tools require a runtime session")
        context.session.read_file(executable_path)
        executable = shutil.which("vvp") or "vvp"
        return CommandSpec(
            argv=[executable, executable_path],
            cwd=".",
            timeout_s=request.timeout_s,
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, IverilogRunRequest)
        return _parse_simulation(self.descriptor.name, request, completed)


class IverilogSimulateVisibleTool(ToolPlugin):
    descriptor = _descriptor(
        "iverilog.simulate_visible", ToolVisibility.AGENT_VISIBLE, "visible_simulation"
    )

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        compiler = _health("iverilog")
        runner = _health("vvp")
        if not compiler.healthy:
            return compiler
        if not runner.healthy:
            return runner
        return HealthCheckResult(
            healthy=True,
            message="iverilog and vvp are available",
            executable=compiler.executable,
        )

    def validate_request(self, request: dict[str, Any]) -> IverilogSimulateRequest:
        return IverilogSimulateRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, IverilogSimulateRequest)
        compile_request = IverilogCompileRequest(
            sources=request.sources,
            top=request.top,
            output=".verigym_internal/visible/simv",
            timeout_s=request.timeout_s,
        )
        return IverilogCompileTool().build_command(compile_request, context)

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        raise RuntimeError("visible simulation parses its compile and run stages separately")

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        try:
            request = self.validate_request(raw_request)
            compile_request = IverilogCompileRequest(
                sources=request.sources,
                top=request.top,
                output=".verigym_internal/visible/simv",
                timeout_s=request.timeout_s,
            )
            compiler = IverilogCompileTool()
            compile_result = compiler.execute(compile_request.model_dump(), context)
            if not compile_result.success:
                compile_result.tool = self.descriptor.name
                compile_result.duration_s = time.monotonic() - started
                return compile_result
            run_request = IverilogRunRequest(
                executable=compile_request.output,
                pass_marker=request.pass_marker,
                fail_marker=request.fail_marker,
                timeout_s=request.timeout_s,
            )
            runner = IverilogRunTool()
            command = runner.build_command(run_request, context)
            assert context.session is not None
            completed = context.session.execute(command)
            result = _parse_simulation(self.descriptor.name, run_request, completed)
            result.duration_s = time.monotonic() - started
            result.metadata["compile_stdout"] = compile_result.stdout
            result.metadata["compile_stderr"] = compile_result.stderr
            return result
        except Exception as exc:
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.INVALID_REQUEST,
                message=str(exc),
                stderr=str(exc),
                duration_s=time.monotonic() - started,
            )


def _parse_simulation(
    tool_name: str,
    request: IverilogRunRequest,
    completed: CompletedCommand,
) -> ToolResult:
    if completed.error:
        category = (
            ErrorCategory.TOOL_NOT_FOUND
            if "not found" in completed.error
            else ErrorCategory.SANDBOX_ERROR
        )
        return _command_failure(tool_name, category, completed)
    if completed.timed_out:
        return _command_failure(tool_name, ErrorCategory.TIMEOUT, completed)
    if completed.output_truncated:
        return _command_failure(tool_name, ErrorCategory.OUTPUT_LIMIT, completed)
    combined = completed.stdout + "\n" + completed.stderr
    passed = request.pass_marker in combined and request.fail_marker not in combined
    if completed.exit_code == 0 and passed:
        return ToolResult(
            tool=tool_name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="simulation passed",
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=completed.duration_s,
            metadata={"tests_passed": 1, "tests_total": 1},
        )
    message = (
        "simulation emitted a failure marker"
        if request.fail_marker in combined
        else "simulation did not emit the required pass marker"
    )
    return _command_failure(
        tool_name,
        ErrorCategory.TEST_FAILED,
        completed,
        message=message,
        metadata={"tests_passed": 0, "tests_total": 1},
    )


def _command_failure(
    tool_name: str,
    category: ErrorCategory,
    completed: CompletedCommand,
    *,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        tool=tool_name,
        success=False,
        category=category,
        message=message or completed.error or category.value,
        exit_code=completed.exit_code,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_s=completed.duration_s,
        output_truncated=completed.output_truncated,
        metadata=metadata or {},
    )


def builtin_iverilog_tools() -> list[ToolPlugin]:
    return [IverilogCompileTool(), IverilogRunTool(), IverilogSimulateVisibleTool()]
