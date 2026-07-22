"""Yosys synthesis ToolPlugin using deterministic private staging."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from verigym.core.hashing import hash_bytes
from verigym.core.workspace import normalize_relative_path
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import ErrorCategory, ToolDescriptor, ToolVisibility
from verigym.schemas.synthesis import SynthesisArtifactRef, SynthesisMetrics
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.tools.base import ToolContext, ToolPlugin
from verigym.tools.yosys.diagnostics import diagnostics_from_log
from verigym.tools.yosys.identity import local_yosys_health
from verigym.tools.yosys.parser import YosysStatParseError, parse_yosys_stat_json
from verigym.tools.yosys.schemas import YosysSynthesisRequest
from verigym.tools.yosys.script_builder import (
    build_yosys_script,
    generated_script_hash,
    safe_source_names,
)

_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_SOURCE_TOTAL_BYTES = 16 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


def _descriptor(name: str) -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name=name,
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "synthesis",
            "stat_json",
            "liberty_area",
            "deterministic_script",
            "structured_errors",
        ],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


class YosysSynthesisTool(ToolPlugin):
    def __init__(self, name: str = "yosys.synth") -> None:
        if name not in {"yosys.synth", "yosys.stat"}:
            raise ValueError(f"unsupported built-in Yosys capability: {name}")
        self.descriptor = _descriptor(name)

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        return local_yosys_health()

    def validate_request(self, request: dict[str, Any]) -> YosysSynthesisRequest:
        return YosysSynthesisRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, YosysSynthesisRequest)
        if context.session is None:
            raise ValueError("Yosys synthesis requires a runtime session")
        session = context.session
        stage = f".verigym_internal/yosys/{request.run_label}"
        total = 0
        for original, safe in zip(request.sources, safe_source_names(request), strict=True):
            normalized = normalize_relative_path(original)
            payload = _read_bounded(session.root, normalized, _MAX_SOURCE_BYTES)
            total += len(payload)
            if total > _MAX_SOURCE_TOTAL_BYTES:
                raise ValueError("approved Yosys sources exceed the aggregate byte limit")
            session.write_file(f"{stage}/{safe}", payload)
        if request.liberty_path is None or request.liberty_sha256 is None:
            raise ValueError("the canonical Yosys flow requires a hashed Liberty asset")
        liberty_path = normalize_relative_path(request.liberty_path)
        liberty = _read_bounded(session.root, liberty_path, _MAX_SOURCE_BYTES)
        if hash_bytes(liberty) != request.liberty_sha256:
            raise ValueError("Liberty asset hash mismatch")
        session.write_file(f"{stage}/profile/cells.lib", liberty)
        script = build_yosys_script(request)
        script_hash = hash_bytes(script.encode("utf-8"))
        if (
            request.expected_flow_script_hash is not None
            and script_hash != request.expected_flow_script_hash
        ):
            raise ValueError("generated Yosys script hash does not match the resolved profile")
        session.write_file(f"{stage}/flow.ys", script.encode("utf-8"))
        session.write_file(f"{stage}/out/.verigym_keep", b"")
        artifacts = [f"{stage}/flow.ys", f"{stage}/out/yosys.log"]
        if request.emit_stat_json:
            artifacts.append(f"{stage}/out/stat.json")
        if request.emit_netlist_json:
            artifacts.append(f"{stage}/out/netlist.json")
        if request.emit_netlist_verilog:
            artifacts.append(f"{stage}/out/netlist.v")
        return CommandSpec(
            argv=["yosys", "-Q", "-T", "-l", "out/yosys.log", "-s", "flow.ys"],
            cwd=stage,
            timeout_s=request.timeout_s,
            artifact_globs=artifacts,
            requires_shell=False,
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, YosysSynthesisRequest)
        assert context.session is not None
        stage = f".verigym_internal/yosys/{request.run_label}"
        artifacts = self._collect_artifacts(request, context, stage)
        log = _optional_bounded_read(
            context.session.root,
            f"{stage}/out/yosys.log",
            _MAX_ARTIFACT_BYTES,
        )
        log_text = log.decode("utf-8", errors="replace") if log is not None else ""
        warnings, unsupported = diagnostics_from_log(log_text)
        if completed.error:
            category = (
                ErrorCategory.TOOL_NOT_FOUND
                if "not found" in completed.error.lower()
                else ErrorCategory.SANDBOX_ERROR
            )
            return self._failure(
                request, completed, category, completed.error, artifacts, warnings, unsupported
            )
        if completed.oom_killed:
            return self._failure(
                request,
                completed,
                ErrorCategory.OUT_OF_MEMORY,
                "Yosys synthesis was killed by the memory limit",
                artifacts,
                warnings,
                unsupported,
                candidate_failure=completed.failure_origin == "candidate_process",
            )
        if completed.timed_out:
            return self._failure(
                request,
                completed,
                ErrorCategory.TIMEOUT,
                "Yosys synthesis exceeded the command timeout",
                artifacts,
                warnings,
                unsupported,
                candidate_failure=completed.failure_origin == "candidate_process",
            )
        if completed.output_truncated:
            return self._failure(
                request,
                completed,
                ErrorCategory.OUTPUT_LIMIT,
                "Yosys command output exceeded the runtime limit",
                artifacts,
                warnings,
                unsupported,
            )
        if completed.exit_code != 0:
            combined = (completed.stdout + "\n" + completed.stderr + "\n" + log_text).lower()
            if "can't find abc" in combined or "cannot find abc" in combined:
                category = ErrorCategory.TOOL_NOT_FOUND
                candidate_failure = False
                message = "Yosys could not execute the required ABC mapper"
            elif any(
                marker in combined
                for marker in (
                    "liberty parser error",
                    "syntax error in liberty file",
                    "failed to parse liberty",
                )
            ):
                category = ErrorCategory.PARSER_ERROR
                candidate_failure = False
                message = "the profile Liberty asset could not be parsed"
            else:
                category = ErrorCategory.COMPILE_FAILED
                candidate_failure = True
                message = "candidate RTL could not be synthesized under the resolved profile"
            return self._failure(
                request,
                completed,
                category,
                message,
                artifacts,
                warnings,
                unsupported,
                candidate_failure=candidate_failure,
            )
        stat_path = f"{stage}/out/stat.json"
        try:
            stat_json = _read_bounded(
                context.session.root,
                stat_path,
                request.max_stat_json_bytes,
            )
            parsed = parse_yosys_stat_json(
                stat_json,
                top=request.top,
                max_bytes=request.max_stat_json_bytes,
                expected_yosys_version=request.expected_yosys_version,
            )
            if request.require_mapped_area and parsed.area is None:
                raise YosysStatParseError(
                    "the exact profile Liberty mapping produced no mapped area"
                )
        except (FileNotFoundError, ValueError, YosysStatParseError) as exc:
            return self._failure(
                request,
                completed,
                ErrorCategory.PARSER_ERROR,
                str(exc),
                artifacts,
                warnings,
                unsupported,
            )
        metrics = SynthesisMetrics(
            status="passed",
            synthesis_ok=True,
            role=request.run_label,
            top=request.top,
            num_wires=parsed.num_wires,
            num_wire_bits=parsed.num_wire_bits,
            num_memories=parsed.num_memories,
            num_memory_bits=parsed.num_memory_bits,
            num_processes=parsed.num_processes,
            num_cells=parsed.num_cells,
            cells_by_type=parsed.cells_by_type,
            mapped_area_raw=parsed.area,
            mapped_area_unit=request.area_unit if parsed.area is not None else None,
            mapped_area_source_hash=(request.liberty_sha256 if parsed.area is not None else None),
            warnings=warnings,
            unsupported_constructs=unsupported,
            tool_identity=request.tool_identity,
            resolved_profile_hash=request.resolved_profile_hash,
            generated_script_hash=generated_script_hash(request),
            artifacts=artifacts,
        )
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="Yosys synthesis and machine-readable statistics passed",
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=completed.duration_s,
            artifacts=[artifact.path for artifact in artifacts],
            diagnostics=[diagnostic.message for diagnostic in warnings + unsupported],
            metadata={"synthesis": metrics.model_dump(mode="json")},
        )

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        try:
            return super().execute(raw_request, context)
        except Exception as exc:
            return ToolResult(
                tool=self.descriptor.name,
                success=False,
                category=ErrorCategory.INVALID_REQUEST,
                message=str(exc),
                stderr=str(exc),
                duration_s=time.monotonic() - started,
                metadata={"candidate_failure": False},
            )

    def _collect_artifacts(
        self,
        request: YosysSynthesisRequest,
        context: ToolContext,
        stage: str,
    ) -> list[SynthesisArtifactRef]:
        assert context.session is not None
        entries = [
            ("flow.ys", f"{stage}/flow.ys", "generated_script"),
            ("yosys.log", f"{stage}/out/yosys.log", "tool_log"),
            ("stat.json", f"{stage}/out/stat.json", "statistics"),
            ("netlist.json", f"{stage}/out/netlist.json", "netlist_json"),
            ("netlist.v", f"{stage}/out/netlist.v", "netlist_verilog"),
        ]
        refs: list[SynthesisArtifactRef] = []
        visibility = "public" if request.run_label == "candidate" else "verifier_private"
        for name, session_path, role in entries:
            payload = _optional_bounded_read(
                context.session.root,
                session_path,
                _MAX_ARTIFACT_BYTES,
            )
            if payload is None:
                continue
            if context.artifact_dir is not None:
                context.artifact_dir.mkdir(parents=True, exist_ok=True)
                (context.artifact_dir / name).write_bytes(payload)
            refs.append(
                SynthesisArtifactRef(
                    path=name,
                    content_hash=hash_bytes(payload),
                    size_bytes=len(payload),
                    role=role,  # type: ignore[arg-type]
                    visibility=visibility,  # type: ignore[arg-type]
                )
            )
        return refs

    def _failure(
        self,
        request: YosysSynthesisRequest,
        completed: CompletedCommand,
        category: ErrorCategory,
        message: str,
        artifacts: list[SynthesisArtifactRef],
        warnings: list[Any],
        unsupported: list[Any],
        *,
        candidate_failure: bool = False,
    ) -> ToolResult:
        metrics = SynthesisMetrics(
            status="failed" if candidate_failure else "error",
            synthesis_ok=False,
            role=request.run_label,
            top=request.top,
            warnings=warnings,
            unsupported_constructs=unsupported,
            tool_identity=request.tool_identity,
            resolved_profile_hash=request.resolved_profile_hash,
            generated_script_hash=generated_script_hash(request),
            artifacts=artifacts,
            failure_category=category.value,
            failure_message=message,
        )
        metadata: dict[str, Any] = {
            "candidate_failure": candidate_failure,
            "synthesis": metrics.model_dump(mode="json"),
        }
        if completed.failure_origin is not None:
            metadata["resource_origin"] = completed.failure_origin
        if completed.failure_reason is not None:
            metadata["runtime_subreason"] = completed.failure_reason
        return ToolResult(
            tool=self.descriptor.name,
            success=False,
            category=category,
            message=message,
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=completed.duration_s,
            output_truncated=completed.output_truncated,
            artifacts=[artifact.path for artifact in artifacts],
            diagnostics=[diagnostic.message for diagnostic in warnings + unsupported],
            metadata=metadata,
        )


def _read_bounded(root: Path, relative: str, limit: int) -> bytes:
    normalized = normalize_relative_path(relative)
    candidate = root / normalized
    metadata = os.lstat(candidate)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Yosys input is not a regular file: {normalized}")
    if metadata.st_nlink != 1:
        raise ValueError(f"Yosys input has an unverified hard-link alias: {normalized}")
    if metadata.st_size > limit:
        raise ValueError(f"Yosys file exceeds the configured byte limit: {normalized}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Yosys file escapes the runtime session")
    return candidate.read_bytes()


def _optional_bounded_read(root: Path, relative: str, limit: int) -> bytes | None:
    try:
        return _read_bounded(root, relative, limit)
    except FileNotFoundError:
        return None


def builtin_yosys_tools() -> list[ToolPlugin]:
    return [YosysSynthesisTool("yosys.synth"), YosysSynthesisTool("yosys.stat")]


__all__ = ["YosysSynthesisTool", "builtin_yosys_tools"]
