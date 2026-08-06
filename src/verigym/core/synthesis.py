"""Verifier-only synthesis and reference-normalization execution."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.loaders import dump_json
from verigym.core.workspace import normalize_relative_path
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.schemas.base import SCHEMA_VERSION
from verigym.schemas.common import ErrorCategory, ToolchainProfile
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.schemas.task import Candidate, VeriTask
from verigym.schemas.verifier import VerifierResult, VerifierStatus
from verigym.suites.base import SuiteAdapter
from verigym.tools.base import SynthesisBackendPlugin, ToolContext


@dataclass(frozen=True)
class SynthesisEvaluation:
    results: list[VerifierResult]
    candidate: SynthesisMetrics
    reference: SynthesisMetrics


def _skipped(role: str, top: str, reason: str) -> SynthesisMetrics:
    return SynthesisMetrics(
        status="skipped",
        synthesis_ok=False,
        role=role,  # type: ignore[arg-type]
        top=top,
        failure_category="skipped",
        failure_message=reason,
    )


def _safe_source(root: Path, relative: str) -> bytes:
    normalized = normalize_relative_path(relative)
    candidate = root / normalized
    metadata = os.lstat(candidate)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"synthesis source is not a regular file: {normalized}")
    if metadata.st_nlink != 1:
        raise ConfigurationError(
            f"synthesis source has an unverified hard-link alias: {normalized}"
        )
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root):
        raise ConfigurationError("synthesis source escapes the frozen candidate")
    return candidate.read_bytes()


def _stage_candidate(
    staging: Path,
    source_root: Path,
    source_paths: list[str],
) -> None:
    for relative in source_paths:
        normalized = normalize_relative_path(relative)
        destination = staging / normalized
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_safe_source(source_root, normalized))


def _stage_reference(
    staging: Path,
    reference: Candidate,
    source_paths: list[str],
) -> None:
    for relative in source_paths:
        normalized = normalize_relative_path(relative)
        try:
            content = reference.files[normalized]
        except KeyError as exc:
            raise ConfigurationError(
                f"suite reference does not provide required synthesis source {normalized!r}"
            ) from exc
        destination = staging / normalized
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _profile_environment(profile: ToolchainProfile) -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in profile.environment_allowlist:
        value = os.environ.get(name)
        if value is None:
            raise ConfigurationError(f"required profile environment variable {name!r} is unset")
        if "\x00" in value:
            raise ConfigurationError(f"profile environment variable {name!r} is invalid")
        environment[name] = value
    return environment


def _result_from_tool(
    node_id: str,
    tool_result: Any,
    *,
    reference: bool,
) -> tuple[VerifierResult, SynthesisMetrics]:
    payload = tool_result.metadata.get("synthesis")
    if not isinstance(payload, dict):
        metrics = SynthesisMetrics(
            status="error",
            synthesis_ok=False,
            role="reference" if reference else "candidate",
            top="unknown",
            failure_category=ErrorCategory.PARSER_ERROR.value,
            failure_message="synthesis backend returned no typed synthesis metrics",
        )
        return (
            VerifierResult(
                node_id=node_id,
                plugin=tool_result.tool,
                status=VerifierStatus.ERROR,
                error_category=ErrorCategory.PARSER_ERROR,
                message=metrics.failure_message or "missing synthesis metrics",
            ),
            metrics,
        )
    metrics = SynthesisMetrics.model_validate(payload)
    if tool_result.success:
        status = VerifierStatus.PASSED
    elif reference:
        status = VerifierStatus.ERROR
    elif tool_result.metadata.get("candidate_failure") is True:
        status = VerifierStatus.FAILED
    else:
        status = VerifierStatus.ERROR
    return (
        VerifierResult(
            node_id=node_id,
            plugin=tool_result.tool,
            status=status,
            error_category=tool_result.category,
            message=tool_result.message,
            exit_code=tool_result.exit_code,
            diagnostics=tool_result.diagnostics,
            metadata={"synthesis": metrics.model_dump(mode="json")},
        ),
        metrics,
    )


def _execute_one(
    *,
    runtime: Runtime,
    plugin: SynthesisBackendPlugin,
    source_staging: Path,
    artifact_dir: Path,
    request: dict[str, Any],
    environment: dict[str, str],
    role: str,
    max_output_bytes: int,
) -> tuple[VerifierResult, SynthesisMetrics]:
    session: RuntimeSession | None = None
    try:
        session = runtime.create_session(
            SessionSpec(
                source_dir=str(source_staging),
                label="verifier",
                max_output_bytes=max_output_bytes,
                environment=environment,
            )
        )
        tool_result = plugin.execute(
            request,
            ToolContext(
                session=session,
                max_output_bytes=max_output_bytes,
                artifact_dir=artifact_dir,
            ),
        )
        return _result_from_tool(f"{role}_synthesis", tool_result, reference=role == "reference")
    except Exception as exc:
        metrics = SynthesisMetrics(
            status="error",
            synthesis_ok=False,
            role=role,  # type: ignore[arg-type]
            top=str(request.get("top", "unknown")),
            failure_category=ErrorCategory.SANDBOX_ERROR.value,
            failure_message=str(exc),
        )
        return (
            VerifierResult(
                node_id=f"{role}_synthesis",
                plugin=plugin.descriptor.name,
                status=VerifierStatus.ERROR,
                error_category=ErrorCategory.SANDBOX_ERROR,
                message=str(exc),
                metadata={"synthesis": metrics.model_dump(mode="json")},
            ),
            metrics,
        )
    finally:
        if session is not None:
            session.close()


def execute_synthesis_quality(
    *,
    suite: SuiteAdapter,
    task: VeriTask,
    candidate_dir: Path,
    runtime: Runtime,
    profile: ToolchainProfile,
    resolved: ResolvedToolchainProfile,
    artifact_root: Path,
    plugin: SynthesisBackendPlugin,
    correctness_passed: bool,
) -> SynthesisEvaluation:
    top = resolved.top_module
    if not correctness_passed:
        reason = "correctness_gate_failed"
        candidate = _skipped("candidate", top, reason)
        reference = _skipped("reference", top, reason)
        skipped = [
            VerifierResult(
                node_id="candidate_synthesis",
                plugin=plugin.descriptor.name,
                status=VerifierStatus.SKIPPED,
                message=reason,
                metadata={"synthesis": candidate.model_dump(mode="json")},
            ),
            VerifierResult(
                node_id="reference_synthesis",
                plugin=plugin.descriptor.name,
                status=VerifierStatus.SKIPPED,
                message=reason,
                metadata={"synthesis": reference.model_dump(mode="json")},
            ),
            VerifierResult(
                node_id="quality_projection",
                plugin="verigym.quality_projection",
                status=VerifierStatus.SKIPPED,
                message=reason,
            ),
        ]
        return SynthesisEvaluation(skipped, candidate, reference)
    reference_candidate = suite.reference_solution(task)
    if reference_candidate is None:
        candidate = _skipped("candidate", top, "reference_solution_missing")
        reference = _skipped("reference", top, "reference_solution_missing")
        result = VerifierResult(
            node_id="reference_synthesis",
            plugin=plugin.descriptor.name,
            status=VerifierStatus.ERROR,
            error_category=ErrorCategory.INVALID_REQUEST,
            message="profile requires a suite reference solution, but none is available",
        )
        return SynthesisEvaluation([result], candidate, reference)
    reference_hash = content_hash(reference_candidate)
    if reference_hash != resolved.reference_candidate_hash:
        candidate = _skipped("candidate", top, "reference_identity_mismatch")
        reference = _skipped("reference", top, "reference_identity_mismatch")
        result = VerifierResult(
            node_id="reference_synthesis",
            plugin=plugin.descriptor.name,
            status=VerifierStatus.ERROR,
            error_category=ErrorCategory.INVALID_REQUEST,
            message="suite reference identity differs from the resolved profile",
        )
        return SynthesisEvaluation([result], candidate, reference)
    environment = _profile_environment(profile)
    backend_root = artifact_root / plugin.artifact_namespace
    candidate_artifacts = backend_root / "candidate"
    reference_summary_path = backend_root / "reference_summary.json"
    with tempfile.TemporaryDirectory(prefix="verigym-synthesis-candidate-") as temporary:
        candidate_staging = Path(temporary)
        _stage_candidate(candidate_staging, candidate_dir, resolved.source_paths)
        plugin.stage_profile_assets(profile, resolved, candidate_staging)
        candidate_result, candidate_metrics = _execute_one(
            runtime=runtime,
            plugin=plugin,
            source_staging=candidate_staging,
            artifact_dir=candidate_artifacts,
            request=plugin.build_synthesis_request(
                profile,
                resolved,
                run_label="candidate",
            ),
            environment=environment,
            role="candidate",
            max_output_bytes=task.budget.max_output_bytes_per_tool,
        )
    if candidate_result.status != VerifierStatus.PASSED:
        reference_metrics = _skipped("reference", top, "candidate_synthesis_did_not_pass")
        results = [
            candidate_result,
            VerifierResult(
                node_id="reference_synthesis",
                plugin=plugin.descriptor.name,
                status=VerifierStatus.SKIPPED,
                message="candidate_synthesis_did_not_pass",
                metadata={"synthesis": reference_metrics.model_dump(mode="json")},
            ),
            VerifierResult(
                node_id="quality_projection",
                plugin="verigym.quality_projection",
                status=VerifierStatus.SKIPPED,
                message="candidate_synthesis_did_not_pass",
            ),
        ]
        return SynthesisEvaluation(results, candidate_metrics, reference_metrics)
    with (
        tempfile.TemporaryDirectory(prefix="verigym-synthesis-reference-") as temporary,
        tempfile.TemporaryDirectory(prefix="verigym-reference-artifacts-") as artifacts,
    ):
        reference_staging = Path(temporary)
        _stage_reference(reference_staging, reference_candidate, resolved.source_paths)
        plugin.stage_profile_assets(profile, resolved, reference_staging)
        reference_result, reference_metrics = _execute_one(
            runtime=runtime,
            plugin=plugin,
            source_staging=reference_staging,
            artifact_dir=Path(artifacts),
            request=plugin.build_synthesis_request(
                profile,
                resolved,
                run_label="reference",
            ),
            environment=environment,
            role="reference",
            max_output_bytes=task.budget.max_output_bytes_per_tool,
        )
        private_artifact_hashes = [
            artifact.model_dump(mode="json") for artifact in reference_metrics.artifacts
        ]
    reference_metrics = reference_metrics.model_copy(update={"artifacts": []})
    backend_root.mkdir(parents=True, exist_ok=True)
    dump_json(
        reference_summary_path,
        {
            "schema_version": SCHEMA_VERSION,
            "reference_candidate_hash": reference_hash,
            "resolved_profile_hash": resolved.resolved_profile_hash,
            "visibility": "summary_only",
            "reference_rtl_exported": False,
            "reference_netlist_exported": False,
            "metrics": reference_metrics.model_dump(mode="json"),
            "private_artifact_identities": private_artifact_hashes,
        },
    )
    projection_status = (
        VerifierStatus.PASSED
        if reference_result.status == VerifierStatus.PASSED
        else VerifierStatus.ERROR
    )
    projection = VerifierResult(
        node_id="quality_projection",
        plugin="verigym.quality_projection",
        status=projection_status,
        error_category=(
            ErrorCategory.SUCCESS
            if projection_status == VerifierStatus.PASSED
            else ErrorCategory.INVALID_REQUEST
        ),
        message=(
            "candidate and reference synthesis are eligible for correctness-gated projection"
            if projection_status == VerifierStatus.PASSED
            else "reference synthesis failed under the resolved profile"
        ),
    )
    return SynthesisEvaluation(
        [candidate_result, reference_result, projection],
        candidate_metrics,
        reference_metrics,
    )


__all__ = ["SynthesisEvaluation", "execute_synthesis_quality"]
