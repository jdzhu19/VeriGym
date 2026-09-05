"""Yosys synthesis ToolPlugin using deterministic private staging."""

from __future__ import annotations

import math
import os
import stat
import time
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel

from verigym.core.hashing import hash_bytes
from verigym.core.workspace import normalize_relative_path
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.runtimes.base import Runtime
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import (
    ArtifactDescriptor,
    ErrorCategory,
    ToolchainProfile,
    ToolDescriptor,
    ToolVisibility,
)
from verigym.schemas.synthesis import SynthesisArtifactRef, SynthesisMetrics
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.tools.base import SynthesisBackendPlugin, ToolContext, ToolPlugin
from verigym.tools.yosys.diagnostics import diagnostics_from_log
from verigym.tools.yosys.identity import local_yosys_health
from verigym.tools.yosys.opensta import (
    FLOW_TEMPLATE_IDS as OPENSTA_FLOW_TEMPLATE_IDS,
)
from verigym.tools.yosys.opensta import (
    LATCH_MAPPING_FLOW_TEMPLATE_ID as OPENSTA_LATCH_MAPPING_FLOW_TEMPLATE_ID,
)
from verigym.tools.yosys.opensta import (
    LATCH_MAPPING_SOURCE,
    build_opensta_script,
    parse_opensta_metrics,
    parse_opensta_power_json,
    power_activity_identity,
)
from verigym.tools.yosys.opensta import (
    LEGACY_FLOW_TEMPLATE_ID as OPENSTA_LEGACY_FLOW_TEMPLATE_ID,
)
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


class YosysSynthesisTool(SynthesisBackendPlugin):
    artifact_namespace = "yosys"

    def __init__(self, name: str = "yosys.synth") -> None:
        if name not in {"yosys.synth", "yosys.stat"}:
            raise ValueError(f"unsupported built-in Yosys capability: {name}")
        self.descriptor = _descriptor(name)

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        return local_yosys_health()

    def validate_profile_contract(self, profile: ToolchainProfile) -> Any:
        from verigym.profiles.validation import validate_yosys_profile

        return validate_yosys_profile(profile)

    def resolve_profile(
        self,
        profile: ToolchainProfile,
        runtime: Runtime,
        *,
        source_paths: list[str],
        top_module: str,
        reference_candidate_hash: str | None,
        expected: ResolvedToolchainProfile | None = None,
    ) -> ResolvedToolchainProfile:
        from verigym.profiles.resolver import resolve_yosys_toolchain_profile

        return resolve_yosys_toolchain_profile(
            profile,
            runtime,
            source_paths=source_paths,
            top_module=top_module,
            reference_candidate_hash=reference_candidate_hash,
            expected=expected,
        )

    def build_synthesis_request(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        *,
        run_label: str,
    ) -> dict[str, Any]:
        from verigym.profiles.resolver import synthesis_request_from_profile

        if run_label not in {"candidate", "reference"}:
            raise ValueError("synthesis run label must be candidate or reference")
        label = cast(Literal["candidate", "reference"], run_label)
        return synthesis_request_from_profile(profile, resolved, run_label=label)

    def stage_profile_assets(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        staging: Path,
    ) -> None:
        from verigym.profiles.validation import read_artifact_bytes

        del resolved
        libraries = [
            item for item in profile.libraries if item.media_type == "application/x-liberty"
        ]
        if len(libraries) != 1:
            raise ValueError("Yosys synthesis requires exactly one Liberty asset")
        target = staging / ".verigym_profile" / "cells.lib"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_artifact_bytes(libraries[0]))
        if profile.flow is not None and profile.flow.template_id in OPENSTA_FLOW_TEMPLATE_IDS:
            constraints = [
                item
                for item in profile.constraints
                if isinstance(item, ArtifactDescriptor) and item.media_type == "application/x-sdc"
            ]
            if len(constraints) != 1:
                raise ValueError("Yosys/OpenSTA synthesis requires exactly one SDC asset")
            (target.parent / "constraints.sdc").write_bytes(read_artifact_bytes(constraints[0]))

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
        if request.flow_template_id == OPENSTA_LATCH_MAPPING_FLOW_TEMPLATE_ID:
            session.write_file(f"{stage}/profile/latch_map.v", LATCH_MAPPING_SOURCE.encode("utf-8"))
        script = build_yosys_script(request)
        script_hash = generated_script_hash(request)
        if (
            request.expected_flow_script_hash is not None
            and script_hash != request.expected_flow_script_hash
        ):
            raise ValueError("generated Yosys script hash does not match the resolved profile")
        synthesis_script_name = (
            "synthesis.ys" if request.flow_template_id in OPENSTA_FLOW_TEMPLATE_IDS else "flow.ys"
        )
        session.write_file(f"{stage}/{synthesis_script_name}", script.encode("utf-8"))
        session.write_file(f"{stage}/out/.verigym_keep", b"")
        artifacts = [f"{stage}/{synthesis_script_name}", f"{stage}/out/yosys.log"]
        if request.emit_stat_json:
            artifacts.append(f"{stage}/out/stat.json")
        if request.emit_netlist_json:
            artifacts.append(f"{stage}/out/netlist.json")
        if request.emit_netlist_verilog:
            artifacts.append(f"{stage}/out/netlist.v")
        if request.flow_template_id in OPENSTA_FLOW_TEMPLATE_IDS:
            if (
                request.constraints_path is None
                or request.constraints_sha256 is None
                or request.opensta_executable is None
                or request.opensta_executable_sha256 is None
            ):
                raise ValueError("Yosys/OpenSTA request has no complete execution contract")
            if request.tool_identity.get("runtime_image_id") is None:
                executable = Path(request.opensta_executable)
                if executable.is_symlink() or not executable.is_file():
                    raise ValueError("OpenSTA executable is missing or is a symlink")
                if hash_bytes(executable.read_bytes()) != request.opensta_executable_sha256:
                    raise ValueError("OpenSTA executable hash mismatch")
            constraints_path = normalize_relative_path(request.constraints_path)
            constraints = _read_bounded(session.root, constraints_path, _MAX_SOURCE_BYTES)
            if hash_bytes(constraints) != request.constraints_sha256:
                raise ValueError("SDC asset hash mismatch")
            session.write_file(f"{stage}/profile/constraints.sdc", constraints)
            opensta_script = build_opensta_script(request)
            session.write_file(f"{stage}/flow.tcl", opensta_script.encode("utf-8"))
            artifacts.extend(
                [
                    f"{stage}/flow.tcl",
                    f"{stage}/out/opensta.log",
                    f"{stage}/out/opensta_metrics.kv",
                    f"{stage}/out/timing.rpt",
                    f"{stage}/out/slack.rpt",
                    f"{stage}/out/power.json",
                    f"{stage}/out/power.rpt",
                    f"{stage}/out/check_setup.rpt",
                ]
            )
            if request.flow_template_id != OPENSTA_LEGACY_FLOW_TEMPLATE_ID:
                artifacts.extend(
                    [
                        f"{stage}/out/units.rpt",
                        f"{stage}/out/activity_annotation.rpt",
                    ]
                )
            argv = [
                request.opensta_executable,
                "-no_init",
                "-no_splash",
                "-exit",
                "flow.tcl",
            ]
        else:
            argv = ["yosys", "-Q", "-T", "-l", "out/yosys.log", "-s", "flow.ys"]
        return CommandSpec(
            argv=argv,
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
        if request.flow_template_id in OPENSTA_FLOW_TEMPLATE_IDS:
            opensta_log = (completed.stdout + "\n" + completed.stderr).encode(
                "utf-8", errors="replace"
            )
            context.session.write_file(f"{stage}/out/opensta.log", opensta_log)
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
            elif (
                request.flow_template_id in OPENSTA_FLOW_TEMPLATE_IDS
                and "yosys failed" not in combined
            ):
                category = ErrorCategory.TOOL_FAILED
                candidate_failure = False
                message = "OpenSTA could not evaluate the mapped netlist under the profile"
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
        delay: float | None = None
        slack: float | None = None
        period: float | None = None
        total_power: float | None = None
        timing_unit: str | None = None
        constraints_hash: str | None = None
        activity_mode: str | None = None
        if request.flow_template_id in OPENSTA_FLOW_TEMPLATE_IDS:
            try:
                metrics_payload = _read_bounded(
                    context.session.root,
                    f"{stage}/out/opensta_metrics.kv",
                    64 * 1024,
                )
                opensta_metrics = parse_opensta_metrics(metrics_payload)
                delay = _finite_float(
                    opensta_metrics["critical_path_delay"], "critical_path_delay", positive=True
                )
                slack = _finite_float(
                    opensta_metrics["worst_negative_slack"], "worst_negative_slack"
                )
                period = _finite_float(
                    opensta_metrics["clock_period"], "clock_period", positive=True
                )
                if opensta_metrics["timing_unit"] != request.timing_unit:
                    raise ValueError("OpenSTA timing unit differs from the profile")
                if opensta_metrics["constraints_sha256"] != request.constraints_sha256:
                    raise ValueError("OpenSTA constraints identity differs from the profile")
                if opensta_metrics["wire_load_model"] != request.wire_load_model:
                    raise ValueError("OpenSTA wire-load model differs from the profile")
                if opensta_metrics["power_unit"] != request.power_unit:
                    raise ValueError("OpenSTA power unit differs from the profile")
                activity_mode = power_activity_identity(request)
                if opensta_metrics["power_activity_mode"] != activity_mode:
                    raise ValueError("OpenSTA activity identity differs from the profile")
                if request.clock_period is None or not math.isclose(
                    period, request.clock_period, rel_tol=0.0, abs_tol=1.0e-9
                ):
                    raise ValueError("OpenSTA clock period differs from the profile")
                if request.power_unit is None:
                    raise ValueError("OpenSTA profile has no power unit")
                power_payload = _read_bounded(
                    context.session.root,
                    f"{stage}/out/power.json",
                    _MAX_ARTIFACT_BYTES,
                )
                total_power = parse_opensta_power_json(
                    power_payload, target_unit=request.power_unit
                )
                if request.flow_template_id != OPENSTA_LEGACY_FLOW_TEMPLATE_ID:
                    for diagnostic_name in ("units.rpt", "activity_annotation.rpt"):
                        diagnostic_payload = _read_bounded(
                            context.session.root,
                            f"{stage}/out/{diagnostic_name}",
                            _MAX_ARTIFACT_BYTES,
                        )
                        if not diagnostic_payload.strip():
                            raise ValueError(f"OpenSTA {diagnostic_name} is empty")
                timing_unit = request.timing_unit
                constraints_hash = request.constraints_sha256
            except (FileNotFoundError, UnicodeError, ValueError) as exc:
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
            critical_path_delay_raw=delay,
            worst_negative_slack_raw=slack,
            timing_unit=timing_unit,
            clock_period=period,
            timing_constraints_hash=constraints_hash,
            total_power_raw=total_power,
            power_unit=request.power_unit if total_power is not None else None,
            power_activity_mode=activity_mode,
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
            message=(
                "Yosys synthesis and OpenSTA area/timing/power analysis passed"
                if request.flow_template_id in OPENSTA_FLOW_TEMPLATE_IDS
                else "Yosys synthesis and machine-readable statistics passed"
            ),
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
            ("synthesis.ys", f"{stage}/synthesis.ys", "generated_script"),
            ("flow.tcl", f"{stage}/flow.tcl", "generated_script"),
            ("yosys.log", f"{stage}/out/yosys.log", "tool_log"),
            ("opensta.log", f"{stage}/out/opensta.log", "tool_log"),
            ("stat.json", f"{stage}/out/stat.json", "statistics"),
            ("opensta_metrics.kv", f"{stage}/out/opensta_metrics.kv", "statistics"),
            ("timing.rpt", f"{stage}/out/timing.rpt", "statistics"),
            ("slack.rpt", f"{stage}/out/slack.rpt", "statistics"),
            ("power.json", f"{stage}/out/power.json", "statistics"),
            ("power.rpt", f"{stage}/out/power.rpt", "statistics"),
            ("units.rpt", f"{stage}/out/units.rpt", "statistics"),
            (
                "activity_annotation.rpt",
                f"{stage}/out/activity_annotation.rpt",
                "statistics",
            ),
            ("check_setup.rpt", f"{stage}/out/check_setup.rpt", "statistics"),
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


def _finite_float(value: str, name: str, *, positive: bool = False) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"OpenSTA {name} is not numeric") from exc
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        qualifier = "finite and positive" if positive else "finite"
        raise ValueError(f"OpenSTA {name} must be {qualifier}")
    return parsed


def builtin_yosys_tools() -> list[ToolPlugin]:
    return [YosysSynthesisTool("yosys.synth"), YosysSynthesisTool("yosys.stat")]


__all__ = ["YosysSynthesisTool", "builtin_yosys_tools"]
