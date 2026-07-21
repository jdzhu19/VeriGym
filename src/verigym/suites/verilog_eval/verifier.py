"""Namespaced verifier-only tools preserving VerilogEval V2 semantics."""

from __future__ import annotations

import shutil
import time
from typing import Any

from pydantic import BaseModel, Field, model_validator

from verigym.core.workspace import normalize_relative_path
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ErrorCategory, ToolDescriptor, ToolVisibility
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.suites.verilog_eval.normalization import declared_modules
from verigym.suites.verilog_eval.result_parser import parse_native_result
from verigym.suites.verilog_eval.toolchain import detect_icarus
from verigym.tools.base import ToolContext, ToolPlugin


class VerilogEvalCompileRequest(StrictModel):
    sources: list[str] = Field(min_length=3)
    candidate: str = "rtl/TopModule.sv"
    top: str = "tb"
    output: str = ".verigym_internal/verilog_eval/simv"
    language: str = "2012"
    timeout_s: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def candidate_must_be_last(self) -> VerilogEvalCompileRequest:
        if self.sources[-1] != self.candidate:
            raise ValueError("candidate source must be last in VerilogEval compilation order")
        return self


class VerilogEvalRegressionRequest(StrictModel):
    executable: str | None = None
    executable_from: str | None = None
    timeout_s: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def require_executable(self) -> VerilogEvalRegressionRequest:
        if self.executable is None and self.executable_from is None:
            raise ValueError("either executable or executable_from is required")
        return self


def _descriptor(name: str, capability: str) -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name=name,
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[capability, "verilog_eval_v2", "structured_errors"],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


class VerilogEvalCompileTool(ToolPlugin):
    descriptor = _descriptor("verilog_eval.v2.compile", "compile")

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        info = detect_icarus("iverilog")
        return HealthCheckResult(
            healthy=info.executable is not None,
            message=(
                f"available ({info.compatibility.value})"
                if info.executable
                else "iverilog was not found on PATH"
            ),
            version=info.version,
            executable=info.executable,
        )

    def validate_request(self, request: dict[str, Any]) -> VerilogEvalCompileRequest:
        return VerilogEvalCompileRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, VerilogEvalCompileRequest)
        if context.session is None:
            raise ValueError("VerilogEval compilation requires a runtime session")
        sources = [normalize_relative_path(source) for source in request.sources]
        for source in sources:
            context.session.read_file(source)
        output = normalize_relative_path(request.output)
        (context.session.root / output).parent.mkdir(parents=True, exist_ok=True)
        executable = shutil.which("iverilog") or "iverilog"
        return CommandSpec(
            argv=[
                executable,
                "-Wall",
                "-Winfloop",
                "-Wno-timescale",
                f"-g{request.language}",
                "-s",
                request.top,
                "-o",
                output,
                *sources,
            ],
            timeout_s=request.timeout_s,
            artifact_globs=[output],
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, VerilogEvalCompileRequest)
        info = detect_icarus("iverilog")
        metadata: dict[str, Any] = {
            "compile_ok": False,
            "tool_version": info.version,
            "tool_executable": info.executable,
            "compatibility_status": info.compatibility.value,
            "command_argv": completed.argv,
            "candidate_last": request.sources[-1] == request.candidate,
        }
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error
                else ErrorCategory.SANDBOX_ERROR
            )
            return _failure(self.descriptor.name, category, completed, metadata=metadata)
        if completed.timed_out:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.TIMEOUT,
                completed,
                message="VerilogEval compilation timed out",
                metadata=metadata,
            )
        if completed.output_truncated:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.OUTPUT_LIMIT,
                completed,
                metadata=metadata,
            )
        if completed.exit_code != 0:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.COMPILE_FAILED,
                completed,
                message="candidate failed VerilogEval elaboration",
                metadata=metadata,
            )
        output = normalize_relative_path(request.output)
        if context.session is None or not (context.session.root / output).is_file():
            return _failure(
                self.descriptor.name,
                ErrorCategory.PARSER_ERROR,
                completed,
                message="iverilog produced no VerilogEval executable",
                metadata=metadata,
            )
        metadata.update({"compile_ok": True, "executable": output})
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="VerilogEval compilation passed",
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=completed.duration_s,
            artifacts=[output],
            metadata=metadata,
        )

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        request = self.validate_request(raw_request)
        if context.session is None:
            raise ValueError("VerilogEval compilation requires a runtime session")
        candidate_path = normalize_relative_path(request.candidate)
        candidate = context.session.read_file(candidate_path).decode("utf-8", errors="replace")
        modules = declared_modules(candidate)
        if modules.count("TopModule") != 1:
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.COMPILE_FAILED,
                message="candidate must declare exactly one TopModule",
                duration_s=time.monotonic() - started,
                metadata={
                    "compile_ok": False,
                    "candidate_failure": True,
                    "candidate_top_found": False,
                },
            )
        reserved = sorted(set(modules) & {"RefModule", "tb"})
        if reserved:
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.COMPILE_FAILED,
                message=f"candidate declares reserved verifier module(s): {', '.join(reserved)}",
                duration_s=time.monotonic() - started,
                metadata={
                    "compile_ok": False,
                    "candidate_failure": True,
                    "reserved_module_collision": reserved,
                },
            )
        command = self.build_command(request, context)
        completed = context.session.execute(command)
        return self.parse_result(request, completed, context)


class VerilogEvalRegressionTool(ToolPlugin):
    descriptor = _descriptor("verilog_eval.v2.regression", "native_regression")

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        info = detect_icarus("vvp")
        return HealthCheckResult(
            healthy=info.executable is not None,
            message=(
                f"available ({info.compatibility.value})"
                if info.executable
                else "vvp was not found on PATH"
            ),
            version=info.version,
            executable=info.executable,
        )

    def validate_request(self, request: dict[str, Any]) -> VerilogEvalRegressionRequest:
        return VerilogEvalRegressionRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, VerilogEvalRegressionRequest)
        if request.executable is None:
            raise ValueError("executable_from must be resolved by the verifier DAG")
        executable_path = normalize_relative_path(request.executable)
        if context.session is None:
            raise ValueError("VerilogEval regression requires a runtime session")
        context.session.read_file(executable_path)
        executable = shutil.which("vvp") or "vvp"
        return CommandSpec(
            argv=[executable, executable_path],
            timeout_s=request.timeout_s,
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, VerilogEvalRegressionRequest)
        info = detect_icarus("vvp")
        parsed = parse_native_result(
            completed,
            tool_version=info.version,
            compatibility=info.compatibility,
        )
        metadata = parsed.model_dump(mode="json")
        metadata.update(
            {
                "tool_executable": info.executable,
                "command_argv": completed.argv,
            }
        )
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error
                else ErrorCategory.SANDBOX_ERROR
            )
            return _failure(self.descriptor.name, category, completed, metadata=metadata)
        if completed.timed_out:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.TIMEOUT,
                completed,
                message="candidate exceeded the VerilogEval simulation timeout",
                metadata=metadata,
            )
        if completed.output_truncated:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.OUTPUT_LIMIT,
                completed,
                message="candidate exceeded the VerilogEval output limit",
                metadata=metadata,
            )
        if parsed.native_timeout:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.TEST_FAILED,
                completed,
                message="VerilogEval native timeout marker was emitted",
                metadata=metadata,
            )
        if completed.exit_code != 0:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.TEST_FAILED,
                completed,
                message="candidate simulation exited before a valid result",
                metadata=metadata,
            )
        if not parsed.native_result_marker_found:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.TEST_FAILED,
                completed,
                message="candidate simulation produced no native mismatch summary",
                metadata=metadata,
            )
        if not parsed.resolved:
            metadata["candidate_failure"] = True
            return _failure(
                self.descriptor.name,
                ErrorCategory.TEST_FAILED,
                completed,
                message=f"candidate has {parsed.mismatches} mismatches",
                metadata=metadata,
            )
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="VerilogEval native regression passed",
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=completed.duration_s,
            metadata={
                **metadata,
                "tests_passed": parsed.samples_checked,
                "tests_total": parsed.samples_checked,
            },
        )


def _failure(
    tool_name: str,
    category: ErrorCategory,
    completed: CompletedCommand,
    *,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    values = metadata or {}
    samples = values.get("samples_checked")
    mismatches = values.get("mismatches")
    if isinstance(samples, int):
        values["tests_total"] = samples
        values["tests_passed"] = max(0, samples - mismatches) if isinstance(mismatches, int) else 0
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
        metadata=values,
    )


def builtin_verilog_eval_tools() -> list[ToolPlugin]:
    return [VerilogEvalCompileTool(), VerilogEvalRegressionTool()]


__all__ = [
    "VerilogEvalCompileRequest",
    "VerilogEvalCompileTool",
    "VerilogEvalRegressionRequest",
    "VerilogEvalRegressionTool",
    "builtin_verilog_eval_tools",
]
