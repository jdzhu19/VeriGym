"""Verifier-only Synopsys Formality RTL equivalence plugin."""

from __future__ import annotations

import hashlib
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
    licensed_environment,
    redact,
    resolve_executable,
    safe_executable,
    safe_relative_path,
)

FLOW_TEMPLATE_ID = "synopsys-formality-rtl-equivalence-v1"
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
_MAX_RESULT_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_VERSION = re.compile(r"\b([A-Z]-\d{4}\.\d{2}(?:-[A-Za-z0-9._-]+)?)\b")
_RESULT_KEYS = {"status", "reference_top", "implementation_top", "script_sha256"}


class FormalityEquivalenceRequest(StrictModel):
    reference_sources: list[str] = Field(min_length=1, max_length=64)
    implementation_sources: list[str] = Field(min_length=1, max_length=64)
    reference_top: str
    implementation_top: str | None = None
    executable: str = "fm_shell"
    timeout_s: int = Field(default=600, ge=1, le=7200)

    @field_validator("reference_sources", "implementation_sources")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        normalized = [safe_relative_path(item) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Formality source lists must not contain duplicates")
        if any(Path(item).suffix.lower() not in {".v", ".sv"} for item in normalized):
            raise ValueError("Formality sources must use .v or .sv filenames")
        return normalized

    @field_validator("reference_top", "implementation_top")
    @classmethod
    def validate_top(cls, value: str | None) -> str | None:
        if value is not None and _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("invalid Formality top-module identifier")
        return value

    @field_validator("executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        return safe_executable(value)

    @model_validator(mode="after")
    def source_sets_are_distinct(self) -> FormalityEquivalenceRequest:
        if set(self.reference_sources) & set(self.implementation_sources):
            raise ValueError("reference and implementation sources must be distinct paths")
        if self.implementation_top is None:
            self.implementation_top = self.reference_top
        return self


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="synopsys.formality.equivalence",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-synopsys",
        capabilities=["formal_equivalence", "systemverilog", "licensed", "structured_errors"],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )


def _read_command(container: str, relative: str) -> str:
    command = "read_sverilog" if Path(relative).suffix.lower() == ".sv" else "read_verilog"
    standard = "-12" if command == "read_sverilog" else "-05"
    return f"{command} -container {container} -libname WORK {standard} [list {relative}]\n"


def _script(request: FormalityEquivalenceRequest) -> str:
    assert request.implementation_top is not None
    reference = "".join(
        _read_command("r", f"reference/{index:03d}{Path(source).suffix.lower()}")
        for index, source in enumerate(request.reference_sources)
    )
    implementation = "".join(
        _read_command("i", f"implementation/{index:03d}{Path(source).suffix.lower()}")
        for index, source in enumerate(request.implementation_sources)
    )
    prefix = (
        "set_app_var sh_continue_on_error false\n"
        "file mkdir out\n"
        f"{reference}"
        f"set_top r:/WORK/{request.reference_top}\n"
        f"{implementation}"
        f"set_top i:/WORK/{request.implementation_top}\n"
        "match\n"
        "redirect -file out/unmatched.rpt { report_unmatched_points }\n"
        "set vg_verified [verify]\n"
        "redirect -file out/failing.rpt { report_failing_points }\n"
    )
    script_hash = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    return (
        prefix
        + "set vg_metrics [open out/equivalence.kv w]\n"
        + 'puts $vg_metrics "VERIGYM_FORMALITY_RESULT_V1"\n'
        + 'puts $vg_metrics "status=[expr {$vg_verified ? {equivalent} : {non_equivalent}}]"\n'
        + f'puts $vg_metrics "reference_top={request.reference_top}"\n'
        + f'puts $vg_metrics "implementation_top={request.implementation_top}"\n'
        + f'puts $vg_metrics "script_sha256={script_hash}"\n'
        + "close $vg_metrics\n"
        + "exit\n"
    )


def _script_identity(script: str) -> str:
    marker = "set vg_metrics [open out/equivalence.kv w]\n"
    prefix, separator, _suffix = script.partition(marker)
    if not separator:
        raise ValueError("generated Formality script has no result section")
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()


class FormalityEquivalenceTool(ToolPlugin):
    descriptor = _descriptor()

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        requested = os.environ.get("VERIGYM_FORMALITY_EXECUTABLE", "fm_shell")
        executable = resolve_executable(requested)
        if shutil.which(executable) is None and not Path(executable).is_file():
            return HealthCheckResult(healthy=False, message="Synopsys Formality was not found")
        try:
            completed = subprocess.run(
                [executable, "-version"],
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
        except (OSError, subprocess.SubprocessError):
            return HealthCheckResult(
                healthy=False,
                message="Formality identity probe failed",
                executable=executable,
            )
        output = redact(completed.stdout + "\n" + completed.stderr)
        match = _VERSION.search(output)
        version = match.group(1) if match is not None else None
        healthy = completed.returncode == 0 and version is not None and not license_failure(output)
        return HealthCheckResult(
            healthy=healthy,
            message="available" if healthy else "Formality returned no supported identity",
            version=version,
            executable=executable,
        )

    def validate_request(self, request: dict[str, Any]) -> FormalityEquivalenceRequest:
        return FormalityEquivalenceRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        assert isinstance(request, FormalityEquivalenceRequest)
        if context.session is None:
            raise ValueError("Formality equivalence requires a runtime session")
        stage = ".verigym_internal/formality"
        total = 0
        for role, sources in (
            ("reference", request.reference_sources),
            ("implementation", request.implementation_sources),
        ):
            for index, relative in enumerate(sources):
                payload = _bounded_source(context.session.root, relative)
                total += len(payload)
                if total > _MAX_TOTAL_SOURCE_BYTES:
                    raise ValueError("Formality sources exceed the aggregate byte limit")
                suffix = Path(relative).suffix.lower()
                context.session.write_file(f"{stage}/{role}/{index:03d}{suffix}", payload)
        script = _script(request)
        context.session.write_file(f"{stage}/flow.tcl", script.encode("utf-8"))
        context.session.write_file(f"{stage}/out/.verigym_keep", b"")
        requested = (
            os.environ.get("VERIGYM_FORMALITY_EXECUTABLE", request.executable)
            if request.executable == "fm_shell"
            else request.executable
        )
        executable = resolve_executable(requested)
        return CommandSpec(
            argv=[executable, "-no_gui", "-f", "flow.tcl"],
            cwd=stage,
            env=licensed_environment(),
            timeout_s=request.timeout_s,
            artifact_globs=[f"{stage}/flow.tcl", f"{stage}/out/equivalence.kv"],
        )

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        assert isinstance(request, FormalityEquivalenceRequest)
        if context.session is None:
            raise ValueError("Formality equivalence requires a runtime session")
        stage = ".verigym_internal/formality"
        log = redact(completed.stdout + "\n" + completed.stderr)
        artifacts = _collect_artifacts(context, stage)
        metadata: dict[str, Any] = {
            "equivalence": {
                "status": "error",
                "equivalent": False,
                "reference_top": request.reference_top,
                "implementation_top": request.implementation_top,
                "flow_template_id": FLOW_TEMPLATE_ID,
            },
            "candidate_failure": False,
        }
        failure = _execution_failure(completed, log)
        if failure is not None:
            category, message = failure
            if category == ErrorCategory.COMPILE_FAILED:
                metadata["candidate_failure"] = "implementation/" in log
            return _result(completed, category, message, artifacts, metadata)
        payload = _optional_file(
            context.session.root, f"{stage}/out/equivalence.kv", _MAX_RESULT_BYTES
        )
        try:
            if payload is None:
                raise ValueError("Formality produced no structured equivalence result")
            parsed = _parse_result_file(payload)
            script_payload = _optional_file(
                context.session.root, f"{stage}/flow.tcl", _MAX_ARTIFACT_BYTES
            )
            if script_payload is None:
                raise ValueError("generated Formality script is unavailable")
            expected_identity = _script_identity(script_payload.decode("utf-8"))
            if parsed["script_sha256"] != expected_identity:
                raise ValueError("Formality result does not match the generated script")
            if parsed["reference_top"] != request.reference_top or (
                parsed["implementation_top"] != request.implementation_top
            ):
                raise ValueError("Formality result top modules differ from the request")
        except (UnicodeDecodeError, ValueError) as exc:
            return _result(
                completed,
                ErrorCategory.PARSER_ERROR,
                str(exc),
                artifacts,
                metadata,
            )
        equivalent = parsed["status"] == "equivalent"
        metadata["equivalence"] = {
            **metadata["equivalence"],
            "status": parsed["status"],
            "equivalent": equivalent,
            "script_sha256": parsed["script_sha256"],
        }
        metadata["candidate_failure"] = not equivalent
        return _result(
            completed,
            ErrorCategory.SUCCESS if equivalent else ErrorCategory.TEST_FAILED,
            "Formality proved equivalence"
            if equivalent
            else "Formality found non-equivalent points",
            artifacts,
            metadata,
            success=equivalent,
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


def _bounded_source(root: Path, relative: str) -> bytes:
    path = root / safe_relative_path(relative)
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Formality input escapes the runtime session")
    if not path.is_file() or path.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError(f"Formality input is missing or too large: {relative}")
    return path.read_bytes()


def _optional_file(root: Path, relative: str, limit: int) -> bytes | None:
    try:
        path = root / safe_relative_path(relative)
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return None
    if path.is_symlink() or not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Formality artifact escapes the runtime session")
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"Formality artifact is invalid or too large: {relative}")
    return path.read_bytes()


def _collect_artifacts(context: ToolContext, stage: str) -> list[str]:
    entries = (
        ("flow.tcl", f"{stage}/flow.tcl", None),
        ("equivalence.kv", f"{stage}/out/equivalence.kv", None),
    )
    artifacts: list[str] = []
    assert context.session is not None
    for name, relative, replacement in entries:
        payload = replacement or _optional_file(context.session.root, relative, _MAX_ARTIFACT_BYTES)
        if not payload:
            continue
        if context.artifact_dir is not None:
            context.artifact_dir.mkdir(parents=True, exist_ok=True)
            (context.artifact_dir / name).write_bytes(payload)
        artifacts.append(name)
    return artifacts


def _execution_failure(
    completed: CompletedCommand, combined: str
) -> tuple[ErrorCategory, str] | None:
    if completed.error:
        category = (
            ErrorCategory.TOOL_NOT_FOUND
            if "not found" in completed.error.lower()
            else ErrorCategory.SANDBOX_ERROR
        )
        return category, redact(completed.error)
    if completed.oom_killed:
        return ErrorCategory.OUT_OF_MEMORY, "Formality was killed by the runtime memory limit"
    if completed.timed_out:
        return ErrorCategory.TIMEOUT, "Formality exceeded the command timeout"
    if completed.output_truncated:
        return ErrorCategory.OUTPUT_LIMIT, "Formality output exceeded the runtime limit"
    if license_failure(combined):
        return ErrorCategory.LICENSE_UNAVAILABLE, "Formality could not obtain a license"
    if completed.exit_code != 0 or re.search(r"^Error:", combined, flags=re.MULTILINE):
        return ErrorCategory.COMPILE_FAILED, "Formality could not load or match the designs"
    return None


def _parse_result_file(payload: bytes) -> dict[str, str]:
    if len(payload) > _MAX_RESULT_BYTES:
        raise ValueError("Formality result exceeds the parser limit")
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Formality result is not ASCII") from exc
    if not lines or lines[0] != "VERIGYM_FORMALITY_RESULT_V1":
        raise ValueError("Formality result sentinel is missing")
    parsed: dict[str, str] = {}
    for line in lines[1:]:
        if line.count("=") != 1:
            raise ValueError("Formality result contains a malformed line")
        key, value = line.split("=", 1)
        if key not in _RESULT_KEYS or key in parsed or not value:
            raise ValueError("Formality result contains unknown, duplicate, or empty fields")
        parsed[key] = value
    if set(parsed) != _RESULT_KEYS or parsed["status"] not in {"equivalent", "non_equivalent"}:
        raise ValueError("Formality result is incomplete or has an invalid status")
    if re.fullmatch(r"[0-9a-f]{64}", parsed["script_sha256"]) is None:
        raise ValueError("Formality result has an invalid script identity")
    return parsed


def _result(
    completed: CompletedCommand,
    category: ErrorCategory,
    message: str,
    artifacts: list[str],
    metadata: dict[str, Any],
    *,
    success: bool = False,
) -> ToolResult:
    return ToolResult(
        tool="synopsys.formality.equivalence",
        success=success,
        category=category,
        message=message,
        exit_code=completed.exit_code,
        stdout="",
        stderr="",
        duration_s=completed.duration_s,
        output_truncated=completed.output_truncated,
        artifacts=artifacts,
        metadata=metadata,
    )


__all__ = [
    "FLOW_TEMPLATE_ID",
    "FormalityEquivalenceRequest",
    "FormalityEquivalenceTool",
]
