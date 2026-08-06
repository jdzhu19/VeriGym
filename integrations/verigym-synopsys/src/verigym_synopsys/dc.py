"""Synopsys Design Compiler area/timing synthesis backend."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    ArtifactDescriptor,
    CommandSpec,
    CompletedCommand,
    ConfigurationError,
    ErrorCategory,
    HealthCheckResult,
    ProfileValidationResult,
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
    Runtime,
    StrictModel,
    SynthesisArtifactRef,
    SynthesisBackendPlugin,
    SynthesisMetrics,
    ToolchainProfile,
    ToolContext,
    ToolDescriptor,
    ToolResult,
    ToolVisibility,
)

from .common import license_failure, licensed_environment, redact, resolve_executable

LEGACY_FLOW_TEMPLATE_ID = "synopsys-dc-area-timing-v1"
_LEGACY_FLOW_TEMPLATE_SOURCE = "verigym-synopsys:dc-area-timing-template:v1"
LEGACY_FLOW_TEMPLATE_HASH = hashlib.sha256(_LEGACY_FLOW_TEMPLATE_SOURCE.encode()).hexdigest()
FLOW_TEMPLATE_ID = "synopsys-dc-area-timing-v2"
_FLOW_TEMPLATE_SOURCE = "verigym-synopsys:dc-area-timing-template:v2"
FLOW_TEMPLATE_HASH = hashlib.sha256(_FLOW_TEMPLATE_SOURCE.encode()).hexdigest()
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024
_MAX_PROFILE_ASSET_BYTES = 128 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
_MAX_METRICS_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_DC_VERSION = re.compile(r"\b([A-Z]-\d{4}\.\d{2}(?:-[A-Za-z0-9.-]+)?)\b")
_METRIC_KEYS_V1 = {
    "mapped_area",
    "critical_path_delay",
    "worst_negative_slack",
    "clock_period",
    "timing_unit",
    "constraints_sha256",
}
_METRIC_KEYS_V2 = {*_METRIC_KEYS_V1, "num_cells"}
_TEMPLATE_HASHES = {
    LEGACY_FLOW_TEMPLATE_ID: LEGACY_FLOW_TEMPLATE_HASH,
    FLOW_TEMPLATE_ID: FLOW_TEMPLATE_HASH,
}


def _canonical_hash(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_user_asset(descriptor: ArtifactDescriptor) -> bytes:
    if descriptor.source_kind != "user_path" or descriptor.uri is None:
        raise ValueError(f"Synopsys asset {descriptor.name!r} must use source_kind=user_path")
    path = Path(descriptor.uri).expanduser()
    if path.is_symlink():
        raise ValueError(f"Synopsys asset {descriptor.name!r} cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_PROFILE_ASSET_BYTES:
        raise ValueError(f"Synopsys asset {descriptor.name!r} is missing or too large")
    return resolved.read_bytes()


def _runtime_identity(runtime: Runtime) -> ResolvedRuntimeIdentity:
    descriptor = runtime.descriptor
    return ResolvedRuntimeIdentity(
        runtime_slug=descriptor.name,
        isolation_level=descriptor.isolation_level,
        deterministic=descriptor.deterministic,
        os=platform.system().lower(),
        architecture=platform.machine(),
        configuration_fingerprint=descriptor.configuration_fingerprint,
        network_policy=(descriptor.security.network_mode if descriptor.security else None),
        resource_controls=descriptor.resources is not None,
    )


def _normalize_version(output: str) -> str | None:
    match = _DC_VERSION.search(redact(output))
    return match.group(1) if match is not None else None


def _probe_dc(executable: str) -> tuple[str, str]:
    resolved = resolve_executable(executable)
    if shutil.which(resolved) is None and not Path(resolved).is_file():
        raise ConfigurationError("Synopsys Design Compiler executable was not found")
    try:
        completed = subprocess.run(
            [resolved, "-version"],
            capture_output=True,
            check=False,
            env={
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                **licensed_environment(),
            },
            shell=False,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigurationError("Design Compiler identity probe failed") from exc
    output = redact(completed.stdout + "\n" + completed.stderr)
    version = _normalize_version(output)
    if version is None or license_failure(output):
        raise ConfigurationError("Design Compiler returned no supported version identity")
    return resolved, version


class DesignCompilerRequest(StrictModel):
    sources: list[str] = Field(min_length=1, max_length=64)
    top: str
    executable: str
    library_path: str = ".verigym_profile/cells.db"
    library_sha256: str
    constraints_path: str = ".verigym_profile/constraints.sdc"
    constraints_sha256: str
    area_unit: str
    timing_unit: str
    clock_period: float = Field(gt=0)
    emit_netlist_verilog: bool = True
    expected_flow_script_hash: str
    flow_template_id: Literal["synopsys-dc-area-timing-v1", "synopsys-dc-area-timing-v2"] = (
        "synopsys-dc-area-timing-v2"
    )
    resolved_profile_hash: str
    tool_identity: dict[str, Any] = Field(default_factory=dict)
    run_label: Literal["candidate", "reference"]
    timeout_s: int = Field(default=600, ge=1, le=7200)

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        normalized = [_safe_relative(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Design Compiler sources must not contain duplicates")
        if any(Path(item).suffix.lower() not in {".v", ".sv"} for item in normalized):
            raise ValueError("Design Compiler sources must use .v or .sv filenames")
        return normalized

    @field_validator("top")
    @classmethod
    def validate_top(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid Design Compiler top-module identifier")
        return value

    @field_validator("library_path", "constraints_path")
    @classmethod
    def validate_asset_path(cls, value: str) -> str:
        return _safe_relative(value)

    @field_validator(
        "library_sha256",
        "constraints_sha256",
        "expected_flow_script_hash",
        "resolved_profile_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Design Compiler identities must be lowercase SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_units(self) -> DesignCompilerRequest:
        if not self.area_unit or not self.timing_unit:
            raise ValueError("Design Compiler area and timing units must be explicit")
        if not math.isfinite(self.clock_period):
            raise ValueError("clock period must be finite")
        return self


def _safe_relative(value: str) -> str:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def _script(
    *,
    sources: list[str],
    top: str,
    clock_period: float,
    timing_unit: str,
    constraints_hash: str,
    emit_netlist: bool,
    template_id: str = FLOW_TEMPLATE_ID,
) -> str:
    if template_id not in _TEMPLATE_HASHES:
        raise ValueError(f"unsupported Design Compiler template: {template_id}")
    source_list = " ".join(
        f"input/{index:03d}{Path(item).suffix.lower()}" for index, item in enumerate(sources)
    )
    write_netlist = (
        "write -format verilog -hierarchy -output out/netlist.v\n" if emit_netlist else ""
    )
    v2 = template_id == FLOW_TEMPLATE_ID
    cell_collection = (
        'set vg_mapped_cells [get_cells -hierarchical * -filter "is_hierarchical == false"]\n'
        if v2
        else ""
    )
    area_collection = "$vg_mapped_cells" if v2 else "[get_cells -hierarchical *]"
    cell_metric = "set vg_num_cells [sizeof_collection $vg_mapped_cells]\n" if v2 else ""
    metric_sentinel = "VERIGYM_DC_METRICS_V2" if v2 else "VERIGYM_DC_METRICS_V1"
    cell_metric_output = 'puts $vg_metrics "num_cells=$vg_num_cells"\n' if v2 else ""
    qor_report = "report_qor > out/qor.rpt\n" if v2 else ""
    return (
        "set_app_var sh_continue_on_error false\n"
        "file mkdir out\n"
        "file mkdir work\n"
        "define_design_lib WORK -path work\n"
        "set_app_var target_library [list profile/cells.db]\n"
        "set_app_var link_library [list * profile/cells.db]\n"
        f"analyze -format sverilog -library WORK [list {source_list}]\n"
        f"elaborate {top}\n"
        f"current_design {top}\n"
        "link\n"
        "uniquify\n"
        "check_design\n"
        "source profile/constraints.sdc\n"
        "compile_ultra\n"
        "set vg_paths [get_timing_paths -delay_type max -max_paths 1]\n"
        'if {[sizeof_collection $vg_paths] != 1} { error "no maximum timing path" }\n'
        "set vg_clocks [get_clocks *]\n"
        'if {[sizeof_collection $vg_clocks] < 1} { error "no clock was defined by SDC" }\n'
        f"{cell_collection}"
        "set vg_area 0.0\n"
        f"foreach_in_collection vg_cell {area_collection} {{\n"
        "  set vg_cell_area [get_attribute $vg_cell area]\n"
        "  if {$vg_cell_area ne {}} { set vg_area [expr {$vg_area + $vg_cell_area}] }\n"
        "}\n"
        "set vg_arrival [get_attribute $vg_paths arrival]\n"
        "set vg_slack [get_attribute $vg_paths slack]\n"
        "set vg_wns [expr {$vg_slack < 0.0 ? $vg_slack : 0.0}]\n"
        "set vg_period [get_attribute [index_collection $vg_clocks 0] period]\n"
        f"{cell_metric}"
        f"if {{abs($vg_period - {clock_period:.12g}) > 1.0e-9}} "
        '{ error "clock period differs from profile" }\n'
        "set vg_metrics [open out/metrics.kv w]\n"
        f'puts $vg_metrics "{metric_sentinel}"\n'
        'puts $vg_metrics "mapped_area=$vg_area"\n'
        'puts $vg_metrics "critical_path_delay=$vg_arrival"\n'
        'puts $vg_metrics "worst_negative_slack=$vg_wns"\n'
        'puts $vg_metrics "clock_period=$vg_period"\n'
        f"{cell_metric_output}"
        f'puts $vg_metrics "timing_unit={timing_unit}"\n'
        f'puts $vg_metrics "constraints_sha256={constraints_hash}"\n'
        "close $vg_metrics\n"
        "report_area > out/area.rpt\n"
        "report_timing -delay_type max -max_paths 1 > out/timing.rpt\n"
        f"{qor_report}"
        f"{write_netlist}"
        "exit\n"
    )


def _generated_script_hash(
    sources: list[str],
    top: str,
    clock_period: float,
    timing_unit: str,
    constraints_hash: str,
    emit_netlist: bool,
    template_id: str = FLOW_TEMPLATE_ID,
) -> str:
    return _hash_bytes(
        _script(
            sources=sources,
            top=top,
            clock_period=clock_period,
            timing_unit=timing_unit,
            constraints_hash=constraints_hash,
            emit_netlist=emit_netlist,
            template_id=template_id,
        ).encode("utf-8")
    )


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="synopsys.dc.synth",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-synopsys",
        capabilities=[
            "synthesis",
            "mapped_area",
            "static_timing",
            "licensed",
            "structured_errors",
        ],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


class DesignCompilerSynthesisTool(SynthesisBackendPlugin):
    descriptor = _descriptor()
    artifact_namespace = "synopsys_dc"

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        try:
            executable, version = _probe_dc(os.environ.get("VERIGYM_DC_EXECUTABLE", "dc_shell"))
        except ConfigurationError as exc:
            return HealthCheckResult(healthy=False, message=str(exc))
        return HealthCheckResult(
            healthy=True,
            message="available",
            version=version,
            executable=executable,
        )

    def validate_profile_contract(self, profile: ToolchainProfile) -> ProfileValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        if profile.flow is None or profile.metrics is None or profile.reference is None:
            return ProfileValidationResult(
                valid=False,
                errors=["profile has no complete synthesis, metric, and reference contract"],
            )
        if profile.flow.backend_plugin != self.descriptor.name:
            errors.append("profile selects a different synthesis backend")
        if profile.flow.template_id not in _TEMPLATE_HASHES:
            errors.append(f"unsupported Design Compiler template: {profile.flow.template_id}")
        if profile.metrics.scope != "synthesis_area_timing":
            errors.append("Design Compiler profiles must use the area/timing metric scope")
        if profile.reproducibility_scope == "public":
            errors.append("licensed host-tool profiles cannot claim public reproducibility")
        if profile.runtime.runtime != "local" or (
            profile.runtime.allowed_runtimes and profile.runtime.allowed_runtimes != ["local"]
        ):
            errors.append("this Design Compiler backend requires the trusted local runtime")
        libraries = [
            item for item in profile.libraries if item.media_type == "application/x-synopsys-db"
        ]
        constraints = [
            item
            for item in profile.constraints
            if isinstance(item, ArtifactDescriptor) and item.media_type == "application/x-sdc"
        ]
        generated = [
            item
            for item in profile.scripts
            if isinstance(item, ArtifactDescriptor) and item.source_kind == "generated"
        ]
        if len(libraries) != 1:
            errors.append("profile requires exactly one application/x-synopsys-db library")
        if len(constraints) != 1:
            errors.append("profile requires exactly one application/x-sdc constraint asset")
        expected_template_hash = _TEMPLATE_HASHES.get(profile.flow.template_id)
        if len(generated) != 1 or generated[0].content_hash != expected_template_hash:
            errors.append("profile generated-flow descriptor does not match this backend")
        for descriptor in [*libraries, *constraints]:
            if descriptor.content_hash is None:
                errors.append(f"asset {descriptor.name!r} has no SHA-256 identity")
                continue
            if descriptor.copy_permitted is not True:
                errors.append(f"asset {descriptor.name!r} is not approved for private staging")
            try:
                actual = _hash_bytes(_read_user_asset(descriptor))
            except Exception as exc:
                errors.append(str(exc))
                continue
            if actual != descriptor.content_hash:
                errors.append(f"asset hash mismatch for {descriptor.name!r}")
        tools = [item for item in profile.tools if item.name == "design-compiler"]
        if len(tools) != 1 or tools[0].executable is None:
            errors.append("profile requires one Design Compiler executable identity")
        if not isinstance(profile.metadata.get("clock_period"), (int, float)) or (
            float(profile.metadata.get("clock_period", 0)) <= 0
        ):
            errors.append("profile metadata requires a positive clock_period")
        timing_unit = profile.metrics.delay.unit
        if timing_unit != profile.metrics.worst_negative_slack.unit:
            errors.append("delay and worst-negative-slack units must match")
        if profile.environment_allowlist and not set(profile.environment_allowlist).issubset(
            {"SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE"}
        ):
            errors.append("profile environment allowlist contains unsupported names")
        warnings.append(
            "site-specific licensed-tool results are comparable only by resolved profile hash"
        )
        return ProfileValidationResult(valid=not errors, errors=errors, warnings=warnings)

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
        validation = self.validate_profile_contract(profile)
        if not validation.valid:
            raise ConfigurationError("; ".join(validation.errors))
        assert profile.flow is not None
        assert profile.metrics is not None
        assert profile.reference is not None
        if runtime.descriptor.name != "local":
            raise ConfigurationError("Design Compiler profiles require the local runtime")
        if source_paths != profile.flow.default_sources or top_module != profile.flow.top_module:
            raise ConfigurationError("task sources/top differ from the Design Compiler profile")
        requirement = next(item for item in profile.tools if item.name == "design-compiler")
        assert requirement.executable is not None
        executable, version = _probe_dc(requirement.executable)
        if requirement.accepted_version is not None:
            if requirement.accepted_version != f"=={version}":
                raise ConfigurationError(
                    f"profile requires {requirement.accepted_version}, observed {version}"
                )
        tool_identity = ResolvedToolIdentity(
            logical_name="design-compiler",
            executable=executable,
            version=version,
            version_output=version,
            capabilities=["synthesis", "mapped_area", "static_timing"],
            identity_kind="local_executable",
        )
        descriptors: list[ArtifactDescriptor] = [*profile.libraries]
        descriptors.extend(
            item for item in profile.constraints if isinstance(item, ArtifactDescriptor)
        )
        descriptors.extend(item for item in profile.scripts if isinstance(item, ArtifactDescriptor))
        assets: list[ResolvedArtifactIdentity] = []
        for descriptor in descriptors:
            if descriptor.content_hash is None or descriptor.source_kind is None:
                raise ConfigurationError(f"asset {descriptor.name!r} lacks an immutable identity")
            actual = (
                descriptor.content_hash
                if descriptor.source_kind == "generated"
                else _hash_bytes(_read_user_asset(descriptor))
            )
            if actual != descriptor.content_hash:
                raise ConfigurationError(f"asset hash mismatch for {descriptor.name!r}")
            assets.append(
                ResolvedArtifactIdentity(
                    logical_id=descriptor.name,
                    media_type=descriptor.media_type or "application/octet-stream",
                    source_kind=descriptor.source_kind,
                    content_hash=actual,
                    license=descriptor.license,
                    attribution=descriptor.attribution,
                    redistributable=descriptor.redistributable is True,
                    unit=descriptor.unit,
                    semantics=descriptor.semantics,
                    copy_permitted=descriptor.copy_permitted,
                    replay_locator=(
                        descriptor.uri if descriptor.source_kind == "user_path" else None
                    ),
                )
            )
        library = next(item for item in assets if item.media_type == "application/x-synopsys-db")
        constraints = next(item for item in assets if item.media_type == "application/x-sdc")
        if library.unit is None or profile.metrics.delay.unit is None:
            raise ConfigurationError("profile area/timing units are incomplete")
        clock_period = float(profile.metadata["clock_period"])
        script_hash = _generated_script_hash(
            source_paths,
            top_module,
            clock_period,
            profile.metrics.delay.unit,
            constraints.content_hash,
            profile.flow.emit_netlist_verilog,
            profile.flow.template_id,
        )
        unresolved = ResolvedToolchainProfile(
            profile_id=profile.id,
            profile_version=profile.version,
            declared_profile_hash=_canonical_hash(profile),
            resolved_profile_hash="",
            reproducibility_scope=profile.reproducibility_scope,
            deterministic=profile.deterministic,
            runtime_identity=_runtime_identity(runtime),
            tool_identities=[tool_identity],
            asset_identities=sorted(assets, key=lambda item: item.logical_id),
            flow_hash=_canonical_hash(profile.flow),
            metric_contract_hash=_canonical_hash(profile.metrics),
            reference_contract_hash=_canonical_hash(profile.reference),
            flow_template_id=profile.flow.template_id,
            generated_script_hash=script_hash,
            top_module=top_module,
            source_paths=source_paths,
            metric_scope="synthesis_area_timing",
            area_unit=library.unit,
            timing_unit=profile.metrics.delay.unit,
            reference_strategy=profile.reference.strategy,
            reference_candidate_hash=reference_candidate_hash,
            metadata={
                "library_sha256": library.content_hash,
                "constraints_sha256": constraints.content_hash,
                "clock_period": clock_period,
                "flow_template_hash": _TEMPLATE_HASHES[profile.flow.template_id],
            },
        )
        resolved = unresolved.model_copy(
            update={"resolved_profile_hash": _canonical_hash(unresolved.identity_payload())}
        )
        if (
            expected is not None
            and resolved.resolved_profile_hash != expected.resolved_profile_hash
        ):
            raise ConfigurationError(
                "resolved Design Compiler profile differs from replay identity"
            )
        return resolved

    def build_synthesis_request(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        *,
        run_label: str,
    ) -> dict[str, Any]:
        if run_label not in {"candidate", "reference"}:
            raise ValueError("synthesis run label must be candidate or reference")
        assert profile.flow is not None
        tool = next(
            item for item in resolved.tool_identities if item.logical_name == "design-compiler"
        )
        library = next(
            item
            for item in resolved.asset_identities
            if item.media_type == "application/x-synopsys-db"
        )
        constraints = next(
            item for item in resolved.asset_identities if item.media_type == "application/x-sdc"
        )
        request = DesignCompilerRequest(
            sources=resolved.source_paths,
            top=resolved.top_module,
            executable=tool.executable,
            library_sha256=library.content_hash,
            constraints_sha256=constraints.content_hash,
            area_unit=resolved.area_unit,
            timing_unit=resolved.timing_unit or "",
            clock_period=float(resolved.metadata["clock_period"]),
            emit_netlist_verilog=profile.flow.emit_netlist_verilog,
            expected_flow_script_hash=resolved.generated_script_hash,
            flow_template_id=resolved.flow_template_id,  # type: ignore[arg-type]
            resolved_profile_hash=resolved.resolved_profile_hash,
            tool_identity={"design_compiler_version": tool.version},
            run_label=run_label,  # type: ignore[arg-type]
        )
        return request.model_dump(mode="json")

    def stage_profile_assets(
        self,
        profile: ToolchainProfile,
        resolved: ResolvedToolchainProfile,
        staging: Path,
    ) -> None:
        del resolved
        library = next(
            item for item in profile.libraries if item.media_type == "application/x-synopsys-db"
        )
        constraints = next(
            item
            for item in profile.constraints
            if isinstance(item, ArtifactDescriptor) and item.media_type == "application/x-sdc"
        )
        target = staging / ".verigym_profile"
        target.mkdir(parents=True, exist_ok=True)
        (target / "cells.db").write_bytes(_read_user_asset(library))
        (target / "constraints.sdc").write_bytes(_read_user_asset(constraints))

    def validate_request(self, request: dict[str, Any]) -> DesignCompilerRequest:
        return DesignCompilerRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, DesignCompilerRequest)
        if context.session is None:
            raise ValueError("Design Compiler synthesis requires a runtime session")
        stage = f".verigym_internal/dc/{request.run_label}"
        total = 0
        for index, relative in enumerate(request.sources):
            payload = _read_session_file(context.session.root, relative, _MAX_SOURCE_BYTES)
            total += len(payload)
            if total > _MAX_SOURCE_TOTAL_BYTES:
                raise ValueError("Design Compiler sources exceed the aggregate byte limit")
            suffix = Path(relative).suffix.lower()
            context.session.write_file(f"{stage}/input/{index:03d}{suffix}", payload)
        for source, target, expected_hash in (
            (request.library_path, "profile/cells.db", request.library_sha256),
            (request.constraints_path, "profile/constraints.sdc", request.constraints_sha256),
        ):
            payload = _read_session_file(context.session.root, source, _MAX_PROFILE_ASSET_BYTES)
            if _hash_bytes(payload) != expected_hash:
                raise ValueError(f"Design Compiler profile asset hash mismatch: {source}")
            context.session.write_file(f"{stage}/{target}", payload)
        script = _script(
            sources=request.sources,
            top=request.top,
            clock_period=request.clock_period,
            timing_unit=request.timing_unit,
            constraints_hash=request.constraints_sha256,
            emit_netlist=request.emit_netlist_verilog,
            template_id=request.flow_template_id,
        )
        if _hash_bytes(script.encode("utf-8")) != request.expected_flow_script_hash:
            raise ValueError("generated Design Compiler script hash differs from resolved profile")
        context.session.write_file(f"{stage}/flow.tcl", script.encode("utf-8"))
        context.session.write_file(f"{stage}/out/.verigym_keep", b"")
        return CommandSpec(
            argv=[
                request.executable,
                "-no_gui",
                "-f",
                "flow.tcl",
                "-output_log_file",
                "out/dc.log",
            ],
            cwd=stage,
            env=licensed_environment(),
            timeout_s=request.timeout_s,
            artifact_globs=[f"{stage}/out/*", f"{stage}/flow.tcl"],
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, DesignCompilerRequest)
        assert context.session is not None
        stage = f".verigym_internal/dc/{request.run_label}"
        log_payload = _optional_session_file(
            context.session.root, f"{stage}/out/dc.log", _MAX_ARTIFACT_BYTES
        )
        log = redact(log_payload.decode("utf-8", errors="replace") if log_payload else "")
        stdout = redact(completed.stdout)
        stderr = redact(completed.stderr)
        combined = "\n".join((stdout, stderr, log))
        artifacts = self._collect_artifacts(request, context, stage, log)
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
            message = "Design Compiler was killed by the runtime memory limit"
        elif completed.timed_out:
            category = ErrorCategory.TIMEOUT
            message = "Design Compiler exceeded the command timeout"
        elif completed.output_truncated:
            category = ErrorCategory.OUTPUT_LIMIT
            message = "Design Compiler output exceeded the runtime limit"
        elif license_failure(combined):
            category = ErrorCategory.LICENSE_UNAVAILABLE
            message = "Design Compiler could not obtain a license"
        elif completed.exit_code != 0 or re.search(r"^Error:", combined, flags=re.MULTILINE):
            category = ErrorCategory.COMPILE_FAILED
            message = "candidate RTL could not be synthesized under the resolved DC profile"
            candidate_failure = True
        if category is not None:
            return self._failure(
                request,
                completed,
                category,
                message,
                artifacts,
                stdout,
                stderr,
                candidate_failure=candidate_failure,
            )
        metrics_payload = _optional_session_file(
            context.session.root, f"{stage}/out/metrics.kv", _MAX_METRICS_BYTES
        )
        try:
            if metrics_payload is None:
                raise ValueError("Design Compiler produced no metrics file")
            parsed = _parse_metrics(metrics_payload, template_id=request.flow_template_id)
            if parsed["timing_unit"] != request.timing_unit:
                raise ValueError("Design Compiler timing unit differs from the profile")
            if parsed["constraints_sha256"] != request.constraints_sha256:
                raise ValueError("Design Compiler metrics use a different constraints identity")
            area = _positive_float(parsed["mapped_area"], "mapped_area")
            delay = _positive_float(parsed["critical_path_delay"], "critical_path_delay")
            slack = _finite_float(parsed["worst_negative_slack"], "worst_negative_slack")
            num_cells = (
                _nonnegative_int(parsed["num_cells"], "num_cells")
                if request.flow_template_id == FLOW_TEMPLATE_ID
                else None
            )
            period = _positive_float(parsed["clock_period"], "clock_period")
            if not math.isclose(period, request.clock_period, rel_tol=0.0, abs_tol=1.0e-9):
                raise ValueError("Design Compiler clock period differs from the profile")
        except ValueError as exc:
            return self._failure(
                request,
                completed,
                ErrorCategory.PARSER_ERROR,
                str(exc),
                artifacts,
                stdout,
                stderr,
            )
        metrics = SynthesisMetrics(
            status="passed",
            synthesis_ok=True,
            role=request.run_label,
            top=request.top,
            num_cells=num_cells,
            mapped_area_raw=area,
            mapped_area_unit=request.area_unit,
            mapped_area_source_hash=request.library_sha256,
            critical_path_delay_raw=delay,
            worst_negative_slack_raw=slack,
            timing_unit=request.timing_unit,
            clock_period=period,
            timing_constraints_hash=request.constraints_sha256,
            tool_identity=request.tool_identity,
            resolved_profile_hash=request.resolved_profile_hash,
            generated_script_hash=request.expected_flow_script_hash,
            artifacts=artifacts,
        )
        return ToolResult(
            tool=self.descriptor.name,
            success=True,
            category=ErrorCategory.SUCCESS,
            message="Design Compiler area/timing synthesis passed",
            exit_code=completed.exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=completed.duration_s,
            artifacts=[item.path for item in artifacts],
            metadata={"synthesis": metrics.model_dump(mode="json")},
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

    def _collect_artifacts(
        self,
        request: DesignCompilerRequest,
        context: ToolContext,
        stage: str,
        sanitized_log: str,
    ) -> list[SynthesisArtifactRef]:
        entries: list[tuple[str, str, str, bytes | None]] = [
            ("flow.tcl", f"{stage}/flow.tcl", "generated_script", None),
            ("dc.log", f"{stage}/out/dc.log", "tool_log", sanitized_log.encode()),
            ("metrics.kv", f"{stage}/out/metrics.kv", "statistics", None),
            ("area.rpt", f"{stage}/out/area.rpt", "statistics", None),
            ("timing.rpt", f"{stage}/out/timing.rpt", "statistics", None),
            ("qor.rpt", f"{stage}/out/qor.rpt", "statistics", None),
            ("netlist.v", f"{stage}/out/netlist.v", "netlist_verilog", None),
        ]
        refs: list[SynthesisArtifactRef] = []
        visibility = "public" if request.run_label == "candidate" else "verifier_private"
        assert context.session is not None
        for name, relative, role, replacement in entries:
            payload = replacement
            if payload is None:
                payload = _optional_session_file(
                    context.session.root, relative, _MAX_ARTIFACT_BYTES
                )
            if payload is None:
                continue
            if context.artifact_dir is not None:
                context.artifact_dir.mkdir(parents=True, exist_ok=True)
                (context.artifact_dir / name).write_bytes(payload)
            refs.append(
                SynthesisArtifactRef(
                    path=name,
                    content_hash=_hash_bytes(payload),
                    size_bytes=len(payload),
                    role=role,  # type: ignore[arg-type]
                    visibility=visibility,  # type: ignore[arg-type]
                )
            )
        return refs

    def _failure(
        self,
        request: DesignCompilerRequest,
        completed: CompletedCommand,
        category: ErrorCategory,
        message: str,
        artifacts: list[SynthesisArtifactRef],
        stdout: str,
        stderr: str,
        *,
        candidate_failure: bool = False,
    ) -> ToolResult:
        metrics = SynthesisMetrics(
            status="failed" if candidate_failure else "error",
            synthesis_ok=False,
            role=request.run_label,
            top=request.top,
            tool_identity=request.tool_identity,
            resolved_profile_hash=request.resolved_profile_hash,
            generated_script_hash=request.expected_flow_script_hash,
            artifacts=artifacts,
            failure_category=category.value,
            failure_message=message,
        )
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
            artifacts=[item.path for item in artifacts],
            metadata={
                "candidate_failure": candidate_failure,
                "synthesis": metrics.model_dump(mode="json"),
            },
        )


def _read_session_file(root: Path, relative: str, limit: int) -> bytes:
    path = root / _safe_relative(relative)
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Design Compiler input escapes the runtime session")
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"Design Compiler input is missing or too large: {relative}")
    return path.read_bytes()


def _optional_session_file(root: Path, relative: str, limit: int) -> bytes | None:
    try:
        return _read_session_file(root, relative, limit)
    except FileNotFoundError:
        return None


def _parse_metrics(payload: bytes, *, template_id: str) -> dict[str, str]:
    if len(payload) > _MAX_METRICS_BYTES:
        raise ValueError("Design Compiler metrics exceed the parser limit")
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Design Compiler metrics are not ASCII") from exc
    expected_sentinel = (
        "VERIGYM_DC_METRICS_V2" if template_id == FLOW_TEMPLATE_ID else "VERIGYM_DC_METRICS_V1"
    )
    if not lines or lines[0] != expected_sentinel:
        raise ValueError("Design Compiler metrics sentinel is missing")
    expected_keys = _METRIC_KEYS_V2 if template_id == FLOW_TEMPLATE_ID else _METRIC_KEYS_V1
    parsed: dict[str, str] = {}
    for line in lines[1:]:
        if line.count("=") != 1:
            raise ValueError("Design Compiler metrics contain a malformed line")
        key, value = line.split("=", 1)
        if not value:
            raise ValueError(f"Design Compiler metric {key!r} is empty")
        if key not in expected_keys or key in parsed:
            raise ValueError("Design Compiler metrics contain unknown or duplicate fields")
        parsed[key] = value
    if set(parsed) != expected_keys:
        raise ValueError("Design Compiler metrics are incomplete")
    return parsed


def _finite_float(value: str, field: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"Design Compiler {field} is not numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"Design Compiler {field} is not finite")
    return result


def _positive_float(value: str, field: str) -> float:
    result = _finite_float(value, field)
    if result <= 0:
        raise ValueError(f"Design Compiler {field} is not positive")
    return result


def _nonnegative_int(value: str, field: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"Design Compiler {field} is not an integer") from exc
    if result < 0:
        raise ValueError(f"Design Compiler {field} is negative")
    return result


__all__ = [
    "DesignCompilerRequest",
    "DesignCompilerSynthesisTool",
    "FLOW_TEMPLATE_HASH",
    "FLOW_TEMPLATE_ID",
    "LEGACY_FLOW_TEMPLATE_HASH",
    "LEGACY_FLOW_TEMPLATE_ID",
]
