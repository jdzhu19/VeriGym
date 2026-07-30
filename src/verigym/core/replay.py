"""Offline trace validation and optional verifier-only re-execution."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from verigym.core.errors import ArtifactIntegrityError, ReplayError
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.loaders import dump_json, load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.repository_candidate import (
    repository_plan_identity,
    verify_frozen_repository_candidate_offline,
)
from verigym.core.synthesis import execute_synthesis_quality
from verigym.core.trace import read_trace
from verigym.core.verifier_dag import has_infrastructure_error
from verigym.core.workspace import normalize_relative_path
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.provenance import get_build_provenance
from verigym.schemas.common import ToolchainProfile
from verigym.schemas.integrity import IntegrityValidation
from verigym.schemas.replay import ReplayEvidence
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.schemas.task import VeriTask
from verigym.schemas.trace import EpisodeEvent
from verigym.schemas.verifier import VerifierResult, VerifierStatus


@dataclass(frozen=True)
class ReplaySummary:
    manifest: RunManifest
    scorecard: ScoreCard
    events: list[EpisodeEvent]
    integrity: IntegrityValidation
    reverified_results: list[VerifierResult] | None = None
    reverified_candidate_synthesis: SynthesisMetrics | None = None
    reverified_reference_synthesis: SynthesisMetrics | None = None

    @property
    def reverified_resolved(self) -> bool | None:
        if self.reverified_results is None:
            return None
        return all(result.status == VerifierStatus.PASSED for result in self.reverified_results)


def replay_run(
    run_dir: Path,
    *,
    verify: bool = False,
    service: VeriGym | None = None,
) -> ReplaySummary:
    """Validate stored hashes and events; never invoke an agent or model."""

    run_dir = run_dir.expanduser().resolve()
    required = [
        "run_manifest.json",
        "task_snapshot.json",
        "trace.jsonl",
        "scorecard.json",
        "workspace_diff.patch",
        "candidate",
        "logs",
        "artifacts",
    ]
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        raise ReplayError(f"run directory is incomplete; missing: {', '.join(missing)}")
    try:
        integrity = verify_artifact_manifest(run_dir, expected_scope="run")
    except ArtifactIntegrityError as exc:
        if "candidate/" in str(exc):
            raise ArtifactIntegrityError(
                f"candidate snapshot failed artifact integrity: {exc}"
            ) from exc
        raise
    manifest = load_model(run_dir / "run_manifest.json", RunManifest)
    if (manifest.prompt_policy is None) != (manifest.prompt_policy_hash is None):
        raise ReplayError("run manifest prompt descriptor and hash are inconsistent")
    if (
        manifest.prompt_policy is not None
        and manifest.prompt_policy_hash != manifest.prompt_policy.configuration_fingerprint
    ):
        raise ReplayError("run manifest prompt policy hash is inconsistent")
    if (
        manifest.prompt_policy is not None
        and manifest.prompt_policy.resolver_id == "agent_execution_prompt_policy_v1"
        and manifest.agent_configuration_hash is None
    ):
        raise ReplayError("resolved agent prompt lacks its execution configuration identity")
    task = load_model(run_dir / "task_snapshot.json", VeriTask)
    try:
        task_payload = json.loads((run_dir / "task_snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("task snapshot is not valid JSON") from exc
    scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
    if scorecard.run_id != manifest.run_id or scorecard.task_id != manifest.task_id:
        raise ReplayError("scorecard identity does not match the run manifest")
    if content_hash(task_payload) != manifest.task_hash:
        raise ReplayError("task_snapshot.json does not match the manifest task hash")
    if repository_plan_identity(task) != manifest.repository_task_identity:
        raise ReplayError("repository task identity does not match the run manifest")
    candidate_hash = hash_directory(run_dir / "candidate")
    if manifest.candidate_hash is None or candidate_hash != manifest.candidate_hash:
        raise ReplayError("candidate snapshot does not match the manifest candidate hash")
    if scorecard.reproducibility.candidate_hash != candidate_hash:
        raise ReplayError("scorecard candidate hash does not match the frozen candidate")
    if scorecard.reproducibility.task_hash != manifest.task_hash:
        raise ReplayError("scorecard task hash does not match the run manifest")
    if scorecard.reproducibility.run_config_hash != manifest.run_config_hash:
        raise ReplayError("scorecard run-config hash does not match the run manifest")
    if content_hash(task_payload.get("verifier")) != manifest.verifier_hash:
        raise ReplayError("verifier graph does not match the manifest verifier hash")
    if scorecard.reproducibility.verifier_hash != manifest.verifier_hash:
        raise ReplayError("scorecard verifier hash does not match the run manifest")
    if manifest.repository_candidate is not None:
        try:
            raw_repository = task.metadata.get("repository_repair")
            if not isinstance(raw_repository, dict) or not isinstance(
                raw_repository.get("workspace_contract"),
                dict,
            ):
                raise ValueError("repository task snapshot lacks its workspace contract")
            from verigym.schemas.repository import RepositoryWorkspaceContract

            contract = RepositoryWorkspaceContract.model_validate(
                raw_repository["workspace_contract"]
            )
            verify_frozen_repository_candidate_offline(
                candidate_repository=run_dir / "candidate" / contract.repository_root,
                patch_file=run_dir / "repository.patch",
                record=manifest.repository_candidate,
                contract=contract,
            )
        except Exception as exc:
            raise ReplayError(f"repository candidate replay failed: {exc}") from exc
    profile_path = run_dir / "artifacts" / "toolchain_profile.json"
    stored_profile: ToolchainProfile | None = None
    stored_resolved_profile: ResolvedToolchainProfile | None = None
    if profile_path.is_file() and manifest.toolchain_profiles:
        stored_profile = load_model(profile_path, ToolchainProfile)
        try:
            profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayError("stored toolchain profile is not valid JSON") from exc
        profile_ref = manifest.toolchain_profiles[0]
        if (
            stored_profile.id != profile_ref.id
            or stored_profile.version != profile_ref.version
            or content_hash(profile_payload) != profile_ref.content_hash
        ):
            raise ReplayError("stored toolchain profile does not match its manifest reference")
    resolved_profile_path = run_dir / "artifacts" / "resolved_toolchain_profile.json"
    if manifest.resolved_profile_hash is not None:
        if stored_profile is None or not resolved_profile_path.is_file():
            raise ReplayError("profile-enabled run lacks its declared or resolved profile artifact")
        stored_resolved_profile = load_model(resolved_profile_path, ResolvedToolchainProfile)
        if (
            stored_resolved_profile.resolved_profile_hash != manifest.resolved_profile_hash
            or stored_resolved_profile.declared_profile_hash != manifest.declared_profile_hash
            or content_hash(stored_resolved_profile.identity_payload())
            != stored_resolved_profile.resolved_profile_hash
            or content_hash(stored_profile) != stored_resolved_profile.declared_profile_hash
        ):
            raise ReplayError("resolved toolchain profile identity does not match the manifest")
        if (
            manifest.resolved_toolchain_profile is not None
            and manifest.resolved_toolchain_profile != stored_resolved_profile
        ):
            raise ReplayError("inline and artifact resolved toolchain profiles differ")
        _validate_stored_synthesis_artifacts(run_dir, manifest, scorecard)
    elif resolved_profile_path.exists():
        raise ReplayError("run has a resolved profile artifact but no manifest identity")
    events = read_trace(run_dir / "trace.jsonl", expected_run_id=manifest.run_id)
    if not events or events[0].event_type != "episode_started":
        raise ReplayError("trace does not begin with episode_started")
    if events[-1].event_type != "episode_terminated":
        raise ReplayError("trace does not end with episode_terminated")

    reverified: list[VerifierResult] | None = None
    replay_candidate_synthesis: SynthesisMetrics | None = None
    replay_reference_synthesis: SynthesisMetrics | None = None
    if verify:
        service = service or VeriGym()
        suite_id = manifest.task_id.split("/", 1)[0]
        suite = service.registries.suites.get(suite_id)
        if manifest.suite_source is not None:
            frozen_source = manifest.suite_source
            suite = suite.with_source(
                SuiteSourceConfig(
                    source_root=Path(frozen_source.source_root),
                    variant=frozen_source.variant,
                    strict_compatibility=frozen_source.strict_compatibility,
                )
            )
            current_source = suite.source_snapshot()
            if (
                current_source is None
                or current_source.dataset_content_hash != frozen_source.dataset_content_hash
                or current_source.configuration_fingerprint
                != frozen_source.configuration_fingerprint
            ):
                raise ReplayError("external suite source differs from the frozen manifest")
        assets = suite.resolve_assets(task)
        runtime_plugin = service.registries.runtimes.get(manifest.runtime.name)
        runtime = runtime_plugin.configure_for_replay(manifest.runtime)
        runtime.prepare(f"{manifest.run_id}-replay-{uuid.uuid4().hex[:8]}")
        try:
            replay_resolved_profile: ResolvedToolchainProfile | None = None
            if stored_resolved_profile is not None:
                assert stored_profile is not None
                reference = suite.reference_solution(task)
                replay_resolved_profile = resolve_toolchain_profile(
                    stored_profile,
                    runtime,
                    source_paths=list(task.workspace.entrypoints),
                    top_module=stored_resolved_profile.top_module,
                    reference_candidate_hash=(
                        content_hash(reference) if reference is not None else None
                    ),
                    expected=stored_resolved_profile,
                )
            reverified = service._verify_candidate(
                task=task,
                assets=assets,
                runtime=runtime,
                candidate_dir=run_dir / "candidate",
                artifact_root=run_dir / "artifacts" / "replay-verification",
            )
            if replay_resolved_profile is not None:
                assert stored_profile is not None
                by_id = {result.node_id: result for result in reverified}
                correctness_passed = all(
                    by_id.get(node_id) is not None
                    and by_id[node_id].status == VerifierStatus.PASSED
                    for node_id in task.scoring.correctness_required_nodes
                ) and not has_infrastructure_error(reverified)
                synthesis = execute_synthesis_quality(
                    suite=suite,
                    task=task,
                    candidate_dir=run_dir / "candidate",
                    runtime=runtime,
                    profile=stored_profile,
                    resolved=replay_resolved_profile,
                    artifact_root=run_dir / "artifacts" / "replay-verification",
                    plugin=service.registries.tools.get("yosys.synth"),
                    correctness_passed=correctness_passed,
                )
                reverified.extend(synthesis.results)
                replay_candidate_synthesis = synthesis.candidate
                replay_reference_synthesis = synthesis.reference
                _validate_replayed_quality(
                    scorecard,
                    replay_candidate_synthesis,
                    replay_reference_synthesis,
                )
        finally:
            runtime.close()
        dump_json(
            run_dir / "artifacts" / "replay-verification" / "runtime_descriptor.json",
            runtime.descriptor,
        )
        dump_json(
            run_dir / "artifacts" / "replay-verification" / "replay_evidence.json",
            ReplayEvidence(
                run_id=manifest.run_id,
                created_at_utc=datetime.now(UTC),
                verifier_reexecuted=True,
                stored_integrity_status=integrity.status,
                original_artifact_manifest_hash=integrity.manifest_hash,
                reverified_result_hash=(
                    content_hash(reverified) if reverified is not None else None
                ),
                runtime=runtime.descriptor,
                build_provenance=get_build_provenance(),
            ),
        )
    return ReplaySummary(
        manifest=manifest,
        scorecard=scorecard,
        events=events,
        integrity=integrity,
        reverified_results=reverified,
        reverified_candidate_synthesis=replay_candidate_synthesis,
        reverified_reference_synthesis=replay_reference_synthesis,
    )


def _normalized_synthesis(metrics: SynthesisMetrics | None) -> dict[str, object] | None:
    if metrics is None:
        return None
    return {
        "status": metrics.status,
        "synthesis_ok": metrics.synthesis_ok,
        "top": metrics.top,
        "num_wires": metrics.num_wires,
        "num_wire_bits": metrics.num_wire_bits,
        "num_memories": metrics.num_memories,
        "num_memory_bits": metrics.num_memory_bits,
        "num_processes": metrics.num_processes,
        "num_cells": metrics.num_cells,
        "cells_by_type": metrics.cells_by_type,
        "mapped_area_raw": metrics.mapped_area_raw,
        "mapped_area_unit": metrics.mapped_area_unit,
        "mapped_area_source_hash": metrics.mapped_area_source_hash,
        "resolved_profile_hash": metrics.resolved_profile_hash,
        "generated_script_hash": metrics.generated_script_hash,
        "failure_category": metrics.failure_category,
    }


def _validate_stored_synthesis_artifacts(
    run_dir: Path,
    manifest: RunManifest,
    scorecard: ScoreCard,
) -> None:
    candidate = scorecard.quality.synthesis
    if candidate is None:
        raise ReplayError("profile-enabled scorecard has no candidate synthesis record")
    artifact_root = run_dir / "artifacts" / "yosys" / "candidate"
    for artifact in candidate.artifacts:
        if artifact.visibility != "public":
            raise ReplayError("candidate synthesis artifact has an invalid visibility")
        relative = normalize_relative_path(artifact.path)
        path = artifact_root / relative
        if not path.is_file():
            raise ReplayError(f"stored candidate synthesis artifact is missing: {relative}")
        payload = path.read_bytes()
        if len(payload) != artifact.size_bytes or hash_bytes(payload) != artifact.content_hash:
            raise ReplayError(f"stored candidate synthesis artifact changed: {relative}")
    flow = next(
        (artifact for artifact in candidate.artifacts if artifact.role == "generated_script"),
        None,
    )
    if candidate.synthesis_ok:
        if flow is None or flow.content_hash != candidate.generated_script_hash:
            raise ReplayError("stored candidate synthesis script identity is inconsistent")
        if manifest.synthesis_flow_script_hash != candidate.generated_script_hash:
            raise ReplayError("manifest and candidate synthesis script hashes differ")
    if scorecard.quality.reference_synthesis is not None:
        if scorecard.quality.reference_synthesis.artifacts:
            raise ReplayError("hidden reference synthesis artifacts were exported")
    summary_path = run_dir / "artifacts" / "yosys" / "reference_summary.json"
    if manifest.reference_summary_hash is None:
        if summary_path.exists():
            raise ReplayError("reference summary exists without a manifest hash")
        return
    if not summary_path.is_file():
        raise ReplayError("manifest reference summary is missing")
    summary_bytes = summary_path.read_bytes()
    if hash_bytes(summary_bytes) != manifest.reference_summary_hash:
        raise ReplayError("reference summary changed after the original run")
    try:
        summary = json.loads(summary_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayError("reference summary is not valid JSON") from exc
    if not isinstance(summary, dict):
        raise ReplayError("reference summary is not a JSON object")
    # Milestone 8 summaries predate the additive explicit version field.
    if (
        summary.get("schema_version") not in {None, "1.0"}
        or summary.get("resolved_profile_hash") != manifest.resolved_profile_hash
        or summary.get("reference_candidate_hash") != manifest.reference_candidate_hash
        or summary.get("reference_rtl_exported") is not False
        or summary.get("reference_netlist_exported") is not False
    ):
        raise ReplayError("reference summary identity or visibility contract is invalid")


def _validate_replayed_quality(
    scorecard: ScoreCard,
    candidate: SynthesisMetrics,
    reference: SynthesisMetrics,
) -> None:
    if _normalized_synthesis(scorecard.quality.synthesis) != _normalized_synthesis(candidate):
        raise ReplayError("replayed candidate synthesis metrics differ from the stored scorecard")
    if _normalized_synthesis(scorecard.quality.reference_synthesis) != _normalized_synthesis(
        reference
    ):
        raise ReplayError("replayed reference synthesis metrics differ from the stored scorecard")
    ppa = scorecard.quality.ppa
    if ppa is None:
        raise ReplayError("profile-enabled scorecard has no PPA eligibility record")
    if ppa.eligible:
        if candidate.mapped_area_raw is None or reference.mapped_area_raw is None:
            raise ReplayError("eligible stored PPA could not be reproduced")
        ratio = reference.mapped_area_raw / candidate.mapped_area_raw
        if (
            ppa.area != candidate.mapped_area_raw
            or ppa.reference_area != reference.mapped_area_raw
            or ppa.area_ratio != ratio
        ):
            raise ReplayError("replayed correctness-gated area projection differs")
    elif any(value is not None for value in (ppa.area, ppa.reference_area, ppa.area_ratio)):
        raise ReplayError("stored ineligible PPA unexpectedly contains ranked values")
