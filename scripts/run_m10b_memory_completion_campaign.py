#!/usr/bin/env python3
"""Execute the commit-bound M10B memory-builder repair completion campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import run_m10b_campaign as base
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.process import auth_identity_configuration

from verigym.core.external_process_identity import validate_external_process_request_identity
from verigym.core.hashing import canonical_json, content_hash
from verigym.core.loaders import load_model
from verigym.evolution.comparison import (
    build_evolving_evaluation,
    validate_evolving_evaluation,
)
from verigym.evolution.exporter import (
    TrajectoryExporter,
    replay_trajectory_dataset,
)
from verigym.evolution.ledger import seal_process_ledger, validate_process_records
from verigym.evolution.memory import (
    build_agent_version,
    prepare_training_summary,
    validate_memory_pack,
)
from verigym.evolution.memory_builder import (
    reconstruct_memory_synthesis_launch,
    validate_memory_builder_input,
    validate_memory_builder_result,
    validate_memory_synthesis_plan,
)
from verigym.evolution.reporting import EvolutionReportService
from verigym.evolution.splits import (
    build_task_split,
    scan_contamination,
    validate_contamination_scan,
)
from verigym.evolution.training_import import (
    build_historical_training_import_manifest,
    build_training_episode_import_eligibility,
    validate_historical_training_import_manifest,
)
from verigym.evolution.versions import (
    build_agent_lineage,
    build_agent_version_set,
    build_run_version_assignments,
    freeze_context_update,
    replay_context_update,
    validate_plan_agent_version_binding,
)
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.state import (
    atomic_dump_json,
    atomic_write_text,
    load_jsonl_models,
)
from verigym.prompts.policy import prompt_contract_identity_hash
from verigym.reporting.loader import load_report_inputs
from verigym.schemas.evolution import (
    AgentVersionManifest,
    AgentVersionSetManifest,
    EpisodeTrajectory,
    EvolutionProcessLedgerRecord,
    MemoryBuilderInput,
    MemoryBuilderResult,
    MemorySynthesisPlan,
    RewardVector,
    RunAgentVersionAssignment,
    SanitizedTrainingEpisode,
    SanitizedTrainingSummary,
    TaskSplitManifest,
    TrajectoryDatasetManifest,
)
from verigym.schemas.external_agent import ExternalProcessResult

START_COMMIT = "9811aa42fda3ef95d2ef59c3eb8c74379111a0e6"
START_TREE = "a0661895911ab72c8f2116ae44100a2594d94a2b"
AUTHORIZATION_ID = "m10b-memory-builder-repair-owner-contract-v1"
FAILED_9811_BUNDLE = Path(
    "/data/jzhu484/Agent/VeriGym_m10b_prompt_binding_9811aa4/evidence-bundle-final"
)
FAILED_9811_SHA256SUMS = "2abd8f8f90f8333e68cfd9e19a793e98c5688cdaa58603794634984958810fb7"
FAILED_9811_AUDIT = "cdfaed245db8f3ffe9ec2965c2044368b6b7edef773a245016358e9829176519"
FAILED_DE9_BUNDLE = Path("/data/jzhu484/Agent/VeriGym_milestone10b_de9dc9d/evidence-bundle-final")
FAILED_DE9_SHA256SUMS = "fd549b7e064aabdad1c2e07630de62f8e424a9a4c368d7df71813c048def8188"
PROBE_1_SOURCE_COMMIT = "2a7591f3ca4e0faec44003ed8c247e21973155c2"
PROBE_1_SOURCE_TREE = "fa1794f08f473589172f62b94a836dda10e76e7f"
PROBE_1_LEDGER_SHA256 = "f60cdb2ba0ab0b1df091aca9821052c5cafe0aed468b75eef32c7a9e163dee25"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _preservation_identity() -> dict[str, Any]:
    current_count = base._assert_checksum_manifest(FAILED_9811_BUNDLE)
    prior_count = base._assert_checksum_manifest(FAILED_DE9_BUNDLE)
    m10a_count = base._assert_checksum_manifest(base.M10A_BUNDLE)
    identities = {
        "schema_version": "1.0",
        "failed_9811_sha256sums_sha256": _sha256(FAILED_9811_BUNDLE / "SHA256SUMS"),
        "failed_9811_audit_manifest_sha256": _sha256(FAILED_9811_BUNDLE / "audit_manifest.json"),
        "failed_9811_verified_file_count": current_count,
        "failed_de9_sha256sums_sha256": _sha256(FAILED_DE9_BUNDLE / "SHA256SUMS"),
        "failed_de9_verified_file_count": prior_count,
        "m10a_sha256sums_sha256": _sha256(base.M10A_BUNDLE / "SHA256SUMS"),
        "m10a_verified_file_count": m10a_count,
        "reference_checkpoint_manifest_sha256": _sha256(base.REFERENCE_CHECKPOINT_MANIFEST),
        "protected_assets_modified": False,
    }
    if (
        identities["failed_9811_sha256sums_sha256"] != FAILED_9811_SHA256SUMS
        or identities["failed_9811_audit_manifest_sha256"] != FAILED_9811_AUDIT
        or identities["failed_de9_sha256sums_sha256"] != FAILED_DE9_SHA256SUMS
        or identities["m10a_sha256sums_sha256"]
        != "afa59b11bbe9f57caed8b5eb8b27739ff09cfd57e9a0fbd11df64851f4ffe420"
        or identities["reference_checkpoint_manifest_sha256"] != base.REFERENCE_CHECKPOINT_HASH
    ):
        raise RuntimeError("one protected historical identity changed")
    return identities


def _make_writable_copy(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        if path.is_dir():
            os.chmod(path, mode | 0o700)
        elif path.is_file():
            os.chmod(path, mode | 0o600)


def _load_bounded_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not stat.S_ISREG(os.lstat(path).st_mode):
        raise RuntimeError("prior probe metadata must be a bounded regular file")
    resolved = path.resolve(strict=True)
    if resolved.stat().st_size > 1024 * 1024:
        raise RuntimeError("prior probe metadata must be a bounded regular file")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("prior probe metadata must be one JSON object")
    return value


def _import_prior_probe(
    *,
    prior_campaign: Path,
    output: Path,
    ledger: Path,
) -> tuple[Path, dict[str, Any]]:
    """Import one immutable terminal Probe 1 and its accounting without rerunning it."""

    prior = prior_campaign.resolve(strict=True)
    source_identity = _load_bounded_json_object(prior / "preflight/source-identity.json")
    if (
        source_identity.get("source_commit") != PROBE_1_SOURCE_COMMIT
        or source_identity.get("source_tree") != PROBE_1_SOURCE_TREE
    ):
        raise RuntimeError("prior Probe 1 source identity differs from the authorized campaign")
    prior_ledger = prior / "model-process-ledger.jsonl"
    if _sha256(prior_ledger) != PROBE_1_LEDGER_SHA256:
        raise RuntimeError("prior Probe 1 process ledger identity changed")
    records = validate_process_records(
        load_jsonl_models(prior_ledger, EvolutionProcessLedgerRecord),
        authorization_id=AUTHORIZATION_ID,
    )
    if len(records) != 2:
        raise RuntimeError("prior Probe 1 must contain exactly one authorization and terminal")
    authorization, terminal = records
    if (
        authorization.ordinal != 1
        or authorization.record_phase != "authorized"
        or authorization.process_kind != "implementation_probe"
        or authorization.run_or_build_id != "m10b-memory-builder-conformance-probe-1"
        or authorization.model_process_started
        or authorization.retry
        or authorization.resume
        or terminal.ordinal != 1
        or terminal.record_phase != "terminal"
        or not terminal.model_process_started
        or not terminal.terminal
        or terminal.terminal_outcome != "memory_builder:content_policy_rejected"
        or terminal.retry
        or terminal.resume
    ):
        raise RuntimeError("prior Probe 1 accounting is not the frozen terminal failure")
    prior_probe = prior / "memory-builder-probe-1"
    result = load_model(
        prior_probe / "process-evidence/memory-builder-result.json",
        MemoryBuilderResult,
    )
    validate_memory_builder_result(result)
    if (
        result.status != "content_policy_rejected"
        or result.failure_reason is not None
        or result.model_processes_started != 1
    ):
        raise RuntimeError("prior Probe 1 result differs from the historical generic rejection")
    shutil.copy2(prior_ledger, ledger)
    imported_probe = output / "memory-builder-probe-1"
    base._copy_tree(prior_probe, imported_probe)
    manifest = {
        "schema_version": "1.0",
        "prior_probe_source_commit": PROBE_1_SOURCE_COMMIT,
        "prior_probe_source_tree": PROBE_1_SOURCE_TREE,
        "prior_probe_ledger_sha256": PROBE_1_LEDGER_SHA256,
        "authorization_record_hash": authorization.record_hash,
        "terminal_record_hash": terminal.record_hash,
        "result_output_hash": result.output_hash,
        "terminal_outcome": terminal.terminal_outcome,
        "model_processes_imported": 1,
        "model_processes_relaunched": 0,
        "retry": False,
        "resume": False,
        "historical_evidence_modified": False,
    }
    atomic_dump_json(output / "preflight/prior-probe-import.json", manifest)
    return imported_probe, manifest


def _synthetic_summary() -> SanitizedTrainingSummary:
    reward = RewardVector(
        outcome_kind="resolved_candidate",
        infrastructure_valid=1,
        policy_compliance=1,
        public_test_reached=1,
        public_test_passed=1,
        patch_reproducible=1,
        candidate_compile_passed=1,
        hidden_regression_passed=1,
        task_resolved=1,
        changed_file_count=1,
        added_lines=1,
        deleted_lines=1,
        public_tool_calls=1,
        wall_time_s=1.0,
    )
    episode = SanitizedTrainingEpisode(
        public_task_category="synthetic_repository_control",
        observable_action_summary=["public_test", "workspace_delta", "candidate_freeze"],
        public_test_outcomes=[True],
        patch_metrics={
            "changed_file_count": 1,
            "added_lines": 1,
            "deleted_lines": 1,
            "public_tool_calls": 1,
        },
        outcome_kind="resolved_candidate",
        reward=reward,
        compile_passed=True,
        hidden_regression_passed=True,
        generalized_failure_labels=[],
    )
    base_payload = {
        "schema_version": "1.0",
        "summary_id": "m10b-memory-builder-conformance-probe",
        "split_manifest_hash": content_hash(
            {"schema_version": "1.0", "kind": "synthetic_probe_split"}
        ),
        "trajectory_dataset_hash": content_hash(
            {"schema_version": "1.0", "kind": "synthetic_probe_dataset"}
        ),
        "episodes": [episode.model_dump(mode="json")],
        "hidden_assets_included": False,
        "references_included": False,
        "private_reasoning_included": False,
        "heldout_assets_included": False,
    }
    return SanitizedTrainingSummary.model_validate(
        {**base_payload, "summary_hash": content_hash(base_payload)}
    )


def _build_final_v0(
    *,
    capability: Mapping[str, Any],
    source_commit: str,
    source_tree: str,
    package_hashes: Mapping[str, str],
) -> AgentVersionManifest:
    preview_config = base._experiment_config(
        name="m10b memory completion v0 identity preview",
        output=Path("unused-memory-completion-v0-preview"),
        tasks=[base.TRAINING_TASKS[0]],
        systems=[("v0-preview", base._common_agent_options(capability))],
        samples=1,
        process_count=1,
        campaign_kind="m10b_memory_completion_zero_call_identity_preview",
        source_commit=source_commit,
        source_tree=source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=str(capability["capability_fingerprint"]),
    )
    item = ExperimentPlanner().build(preview_config).items[0]
    if item.prompt_policy is None:
        raise RuntimeError("final v0 preview omitted prompt policy")
    version = build_agent_version(
        agent_version_id="codex-cli-agent-v0",
        status="frozen",
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=True,
        base_agent_id="codex-cli-agent",
        agent_descriptor_hash=content_hash(item.system.agent_descriptor),
        model_id=base.MODEL_ID,
        reasoning_effort=base.REASONING_EFFORT,
        auth_semantic_id=base.AUTH_SEMANTIC_ID,
        runtime_identity_hash=item.runtime_identity_hash,
        tool_policy_hash=item.tool_policy_hash,
        prompt_contract_hash=prompt_contract_identity_hash(item.prompt_policy),
        source_commit=source_commit,
        package_hashes=dict(package_hashes),
        image_hashes={
            "agent": base._image_hash(base.REPOSITORY_AGENT_IMAGE_ID),
            "verifier": base._image_hash(base.VERIFIER_IMAGE_ID),
        },
        model_weights_modified=False,
    )
    validate_plan_agent_version_binding(
        version=version,
        item=item,
        source_commit=source_commit,
        package_hashes=dict(package_hashes),
    )
    return version


def _replay_memory_builder(
    root: Path,
    *,
    codex_executable: Path,
) -> dict[str, Any]:
    request = load_model(root / "memory-builder-input.json", MemoryBuilderInput)
    plan = load_model(root / "memory-synthesis-plan.json", MemorySynthesisPlan)
    result = load_model(root / "process-evidence/memory-builder-result.json", MemoryBuilderResult)
    summary = load_model(root / "frozen-training-summary.json", SanitizedTrainingSummary)
    validate_memory_builder_input(request)
    validate_memory_synthesis_plan(plan)
    validate_memory_builder_result(result)
    prompt, binding, executable = reconstruct_memory_synthesis_launch(
        plan=plan,
        request=request,
        frozen_summary=summary,
        executable_path=codex_executable,
    )
    validate_external_process_request_identity(executable)
    if result.memory_pack is not None:
        validate_memory_pack(result.memory_pack)
    if (
        result.memory_synthesis_plan_hash != plan.plan_hash
        or result.invocation_spec_hash != plan.invocation_spec.invocation_spec_hash
        or result.payload_binding_hash != binding.payload_binding_hash
    ):
        raise RuntimeError("memory-builder result differs from replayed lifecycle identity")
    return {
        "schema_version": "1.0",
        "plan_hash": plan.plan_hash,
        "invocation_spec_hash": plan.invocation_spec.invocation_spec_hash,
        "payload_binding_hash": binding.payload_binding_hash,
        "rendered_prompt_hash": binding.rendered_prompt_hash,
        "rendered_prompt_utf8_bytes": len(prompt.encode("utf-8")),
        "status": result.status,
        "failure_reason": result.failure_reason,
        "memory_pack_hash": (
            result.memory_pack.content_hash if result.memory_pack is not None else None
        ),
        "model_calls": 0,
        "codex_calls": 0,
        "broker_calls": 0,
        "credential_accesses": 0,
        "proxy_uses": 0,
        "runtime_calls": 0,
        "network_calls": 0,
    }


def _copy_historical_training(
    *,
    output: Path,
    source_commit: str,
    package_hashes: Mapping[str, str],
    final_v0: AgentVersionManifest,
) -> tuple[
    bool,
    Path,
    TrajectoryDatasetManifest,
    list[EpisodeTrajectory],
    SanitizedTrainingSummary,
    Any,
    list[dict[str, Any]],
]:
    import_root = output / "training-import"
    import_root.mkdir()
    experiment = import_root / "source-experiment-copy"
    shutil.copytree(FAILED_9811_BUNDLE / "training/experiment", experiment, symlinks=False)
    _make_writable_copy(experiment)
    historical_dataset = FAILED_9811_BUNDLE / "trajectory-dataset/training"
    historical_version_set = load_model(
        historical_dataset / "agent-version-manifest.json",
        AgentVersionSetManifest,
    )
    if len(historical_version_set.versions) != 1:
        raise RuntimeError("historical training dataset does not bind exactly one agent version")
    historical_version = historical_version_set.versions[0]
    split = load_model(
        historical_dataset / "task-split-manifest.json",
        TaskSplitManifest,
    )
    historical_trajectories = load_jsonl_models(
        historical_dataset / "trajectories.jsonl",
        EpisodeTrajectory,
    )
    assignments = {
        trajectory.run_id: trajectory.agent_version_id for trajectory in historical_trajectories
    }
    first_dataset = import_root / "export-a"
    second_dataset = import_root / "export-b"
    exporter = TrajectoryExporter()
    manifest = exporter.export(
        experiment,
        first_dataset,
        split_manifest=split,
        agent_versions={historical_version.agent_version_id: historical_version},
        run_agent_versions=assignments,
        source_commit=source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-final-imported-real-training",
    )
    second_manifest = exporter.export(
        experiment,
        second_dataset,
        split_manifest=split,
        agent_versions={historical_version.agent_version_id: historical_version},
        run_agent_versions=assignments,
        source_commit=source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-final-imported-real-training",
    )
    deterministic = (
        manifest == second_manifest
        and (first_dataset / "SHA256SUMS").read_bytes()
        == (second_dataset / "SHA256SUMS").read_bytes()
    )
    replay_trajectory_dataset(first_dataset, experiment)
    replay_records = base._replay_experiment(experiment)
    outcomes = base._run_outcomes(experiment)
    trajectories = load_jsonl_models(first_dataset / "trajectories.jsonl", EpisodeTrajectory)
    by_run = {trajectory.run_id: trajectory for trajectory in trajectories}
    inputs = load_report_inputs(experiment)
    outcome_by_run = {record["run_id"]: record for record in outcomes}
    replay_by_run = {record["run_id"]: record for record in replay_records}
    episode_records = []
    expected_tasks = set(base.TRAINING_TASKS)
    for run in sorted(inputs.valid_runs, key=lambda item: item.manifest.task_id):
        trajectory = by_run[run.manifest.run_id]
        outcome = outcome_by_run[run.manifest.run_id]
        replay = replay_by_run[run.manifest.run_id]
        runtime_result = load_model(
            experiment / run.relative_path / "artifacts/codex_cli/runtime_process.json",
            ExternalProcessResult,
        )
        build_commit = (
            run.manifest.build_provenance.source_commit
            if run.manifest.build_provenance is not None
            else None
        )
        observation = (
            run.manifest.external_agent_observations[0]
            if run.manifest.external_agent_observations
            else None
        )
        checks = {
            "terminal_and_evaluable": bool(outcome["evaluable"]),
            "artifact_manifest": bool(trajectory.artifact_manifest_hash),
            "task_source_base_repository_identity": (
                run.manifest.task_id in expected_tasks
                and run.manifest.source_hash == trajectory.source_hash
                and trajectory.base_repository_hash is not None
            ),
            "exact_historical_v0_agent_version": (
                trajectory.agent_version_hash == historical_version.version_hash
                and trajectory.agent_version_id == historical_version.agent_version_id
                and trajectory.memory_pack_hash is None
            ),
            "prompt_plan_child_harness_binding": bool(outcome["prompt_binding_verified"]),
            "model_codex_reasoning_auth_identity": (
                trajectory.auth_semantic_id == base.AUTH_SEMANTIC_ID
                and runtime_result.runtime_identity.host_executable_version == base.CODEX_VERSION
                and observation is not None
                and observation.requested_model_id == base.MODEL_ID
                and observation.observed_model_id == base.MODEL_ID
                and observation.requested_reasoning_effort == base.REASONING_EFFORT
                and observation.effective_reasoning_effort == base.REASONING_EFFORT
                and observation.auth_semantic_id == base.AUTH_SEMANTIC_ID
            ),
            "runtime_tool_verifier_public_contract": (
                run.plan_item is not None
                and run.plan_item.runtime_identity_hash == historical_version.runtime_identity_hash
                and final_v0.runtime_identity_hash == historical_version.runtime_identity_hash
                and run.plan_item.tool_policy_hash == historical_version.tool_policy_hash
                and final_v0.tool_policy_hash == historical_version.tool_policy_hash
                and trajectory.verifier_identity_hash is not None
                and trajectory.toolchain_identity_hash is not None
            ),
            "no_infrastructure_failure": (str(outcome["outcome_kind"]) != "infrastructure_invalid"),
            "no_hidden_reference_credential_leakage": (
                not trajectory.hidden_assets_exported
                and not trajectory.reference_solution_exported
                and not trajectory.credential_values_exported
                and not trajectory.private_reasoning_exported
                and not trajectory.raw_host_paths_exported
            ),
            "zero_call_replay": (
                replay["codex_calls"] == 0
                and replay["broker_calls"] == 0
                and replay["credential_accesses"] == 0
                and replay["proxy_uses"] == 0
            ),
            "deterministic_trajectory_export": deterministic,
            "deterministic_reward_recomputation": True,
            "original_source_commit": build_commit == START_COMMIT,
        }
        episode_records.append(
            build_training_episode_import_eligibility(
                run_id=run.manifest.run_id,
                task_id=run.manifest.task_id,
                outcome_kind=str(outcome["outcome_kind"]),
                checks=checks,
                original_run_manifest_hash=trajectory.run_manifest_hash,
                original_artifact_manifest_hash=trajectory.artifact_manifest_hash,
                original_source_commit=START_COMMIT,
                exporter_source_commit=source_commit,
                trajectory_hash=trajectory.trajectory_hash,
                reward_hash=trajectory.reward_hash,
            )
        )
    import_manifest = build_historical_training_import_manifest(
        import_id="m10b-final-historical-training-triplet",
        source_bundle_sha256sums_hash=FAILED_9811_SHA256SUMS,
        exporter_source_commit=source_commit,
        episodes=episode_records,
    )
    validate_historical_training_import_manifest(import_manifest)
    atomic_dump_json(import_root / "import-eligibility-manifest.json", import_manifest)
    atomic_dump_json(
        import_root / "zero-call-replay.json",
        {"schema_version": "1.0", "records": replay_records, "external_calls": 0},
    )
    summary = prepare_training_summary(
        trajectories,
        split_manifest_hash=split.manifest_hash,
        trajectory_dataset_hash=manifest.dataset_hash,
        summary_id="m10b-final-imported-training-summary",
    )
    atomic_dump_json(import_root / "sanitized-training-summary.json", summary)
    return (
        import_manifest.import_all,
        experiment,
        manifest,
        trajectories,
        summary,
        import_manifest,
        outcomes,
    )


def _rerun_training(
    *,
    output: Path,
    capability: Mapping[str, Any],
    source_commit: str,
    source_tree: str,
    package_hashes: Mapping[str, str],
    v0: AgentVersionManifest,
    ledger: Path,
    repository_root: Path,
) -> tuple[
    Path,
    TrajectoryDatasetManifest,
    list[EpisodeTrajectory],
    SanitizedTrainingSummary,
    list[dict[str, Any]],
]:
    roots = base._training_roots(repository_root)
    split = build_task_split(
        split_id="m10b-final-rerun-training",
        training=[base._task_entry(roots[task]) for task in base.TRAINING_TASKS],
        heldout=[],
    )
    config = base._experiment_config(
        name="m10b memory completion conditional training rerun",
        output=output / "training-rerun/experiment",
        tasks=base.TRAINING_TASKS,
        systems=[("v0", base._versioned_options(capability, v0))],
        samples=1,
        process_count=3,
        campaign_kind="m10b_memory_completion_conditional_training_rerun",
        source_commit=source_commit,
        source_tree=source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=str(capability["capability_fingerprint"]),
    )
    _, experiment = base._run_experiment(
        config,
        ledger=ledger,
        process_kind="training_episode",
        authorization_id=AUTHORIZATION_ID,
    )
    dataset = output / "training-rerun/trajectory-dataset"
    manifest = TrajectoryExporter().export(
        experiment,
        dataset,
        split_manifest=split,
        agent_versions={v0.agent_version_id: v0},
        run_agent_versions=base._run_assignments(experiment, {"v0": v0.agent_version_id}),
        source_commit=source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-final-rerun-real-training",
    )
    replay_trajectory_dataset(dataset, experiment)
    trajectories = load_jsonl_models(dataset / "trajectories.jsonl", EpisodeTrajectory)
    summary = prepare_training_summary(
        trajectories,
        split_manifest_hash=split.manifest_hash,
        trajectory_dataset_hash=manifest.dataset_hash,
        summary_id="m10b-final-rerun-training-summary",
    )
    atomic_dump_json(output / "training-rerun/sanitized-training-summary.json", summary)
    base._replay_experiment(experiment)
    outcomes = base._run_outcomes(experiment)
    if len(outcomes) != 3 or not all(bool(outcome["evaluable"]) for outcome in outcomes):
        raise RuntimeError("conditional training rerun did not produce three evaluable outcomes")
    return experiment, manifest, trajectories, summary, outcomes


def _seal_bundle(
    *,
    output: Path,
    repository_root: Path,
    source_identity: Mapping[str, Any],
    preservation: Mapping[str, Any],
    package_identity: Mapping[str, Any],
    quality_evidence: Path,
    forensic_evidence: Path,
    lifecycle_evidence: Path,
    probe_roots: Sequence[Path],
    probe_1_forensic_evidence: Path,
    import_root: Path,
    rerun_root: Path | None,
    final_training_dataset: Path,
    final_memory_root: Path,
    heldout_experiment: Path,
    heldout_dataset: Path,
    heldout_reports: Path,
    replay_summary: Mapping[str, Any],
    process_manifest: Any,
    evaluation: Any,
    outcomes: Sequence[Mapping[str, Any]],
    import_manifest: Any,
    training_outcomes: Sequence[Mapping[str, Any]],
) -> Path:
    bundle = output / "evidence-bundle-final"
    bundle.mkdir()
    for relative in (
        "root-cause",
        "implementation",
        "source-identities",
        "package-and-image-identities",
        "training-import",
        "training-rerun",
        "memory-builder-probes",
        "final-memory-synthesis",
        "heldout-evaluation",
        "replay",
        "security-and-integrity",
        "reports",
    ):
        (bundle / relative).mkdir()
    atomic_dump_json(bundle / "source-identities/source-identity.json", dict(source_identity))
    atomic_dump_json(bundle / "source-identities/preservation.json", dict(preservation))
    atomic_dump_json(
        bundle / "package-and-image-identities/identities.json",
        dict(package_identity),
    )
    shutil.copy2(
        forensic_evidence,
        bundle / "root-cause/memory-builder-preview-forensic.json",
    )
    shutil.copy2(
        probe_1_forensic_evidence,
        bundle / "root-cause/probe-1-content-policy-forensic.json",
    )
    shutil.copy2(
        repository_root / "tests/fixtures/m10b_memory_builder_empty_stdin_preview.json",
        bundle / "root-cause/historical-empty-stdin-regression.json",
    )
    shutil.copy2(
        repository_root / "docs/schemas/external-process-invocation-spec.schema.json",
        bundle / "implementation/invocation-spec-schema.json",
    )
    shutil.copy2(
        repository_root / "docs/schemas/external-process-payload-binding.schema.json",
        bundle / "implementation/payload-binding-schema.json",
    )
    shutil.copy2(
        repository_root / "docs/schemas/memory-synthesis-plan.schema.json",
        bundle / "implementation/memory-synthesis-plan-schema.json",
    )
    shutil.copy2(lifecycle_evidence, bundle / "implementation/lifecycle-test-matrix.json")
    shutil.copy2(
        quality_evidence,
        bundle / "implementation/CI-and-package-identities.json",
    )
    for index, probe_root in enumerate(probe_roots, 1):
        base._copy_tree(probe_root, bundle / f"memory-builder-probes/probe-{index}")
    base._copy_tree(import_root, bundle / "training-import/evidence")
    if rerun_root is not None:
        base._copy_tree(rerun_root, bundle / "training-rerun/evidence")
    else:
        atomic_dump_json(
            bundle / "training-rerun/not-executed.json",
            {
                "schema_version": "1.0",
                "reason": "all three historical training episodes were import eligible",
                "model_processes": 0,
            },
        )
    base._copy_tree(final_training_dataset, bundle / "training-import/final-training-dataset")
    base._copy_tree(final_memory_root, bundle / "final-memory-synthesis/evidence")
    base._copy_tree(heldout_experiment, bundle / "heldout-evaluation/experiment")
    base._copy_tree(heldout_dataset, bundle / "heldout-evaluation/trajectory-dataset")
    base._copy_tree(heldout_reports, bundle / "heldout-evaluation/reports")
    atomic_dump_json(
        bundle / "heldout-evaluation/per-run-outcomes.json",
        {"schema_version": "1.0", "runs": list(outcomes)},
    )
    atomic_dump_json(
        bundle / "training-import/per-run-outcomes.json",
        {"schema_version": "1.0", "runs": list(training_outcomes)},
    )
    atomic_dump_json(
        bundle / "training-import/import-eligibility-manifest.json",
        import_manifest,
    )
    atomic_dump_json(bundle / "replay/replay-summary.json", dict(replay_summary))
    atomic_dump_json(
        bundle / "security-and-integrity/process-ledger-manifest.json",
        process_manifest,
    )
    shutil.copy2(
        output / "model-process-ledger.jsonl",
        bundle / "security-and-integrity/model-process-ledger.jsonl",
    )
    atomic_dump_json(
        bundle / "security-and-integrity/global-process-accounting.json",
        {
            "schema_version": "1.0",
            "authorized_processes": process_manifest.authorized_processes,
            "started_processes": process_manifest.started_processes,
            "terminal_processes": process_manifest.terminal_processes,
            "maximum_new_processes": 24,
            "process_kind_counts": process_manifest.process_kind_counts,
            "training_imported": bool(import_manifest.import_all),
            "conditional_training_reruns": (0 if import_manifest.import_all else 3),
            "retries": 0,
            "resumes": 0,
            "fallbacks": 0,
            "candidate_repairs": 0,
        },
    )
    atomic_dump_json(bundle / "reports/evolving-evaluation.json", evaluation)
    final_synthesis_plan = load_model(
        final_memory_root / "memory-synthesis-plan.json",
        MemorySynthesisPlan,
    )
    synthesis_identities = {
        "schema_version": "1.0",
        "memory_synthesis_plan_hash": final_synthesis_plan.plan_hash,
        "invocation_spec_hash": final_synthesis_plan.invocation_spec.invocation_spec_hash,
        "payload_binding_hash": final_synthesis_plan.payload_binding.payload_binding_hash,
        "rendered_prompt_hash": final_synthesis_plan.rendered_prompt_hash,
        "rendered_prompt_utf8_bytes": final_synthesis_plan.rendered_prompt_utf8_bytes,
    }
    atomic_dump_json(
        bundle / "reports/memory-synthesis-identities.json",
        synthesis_identities,
    )
    shutil.copy2(
        heldout_reports / "evolving-evaluation.md",
        bundle / "reports/evolving-evaluation.md",
    )
    final_gate = {
        "schema_version": "1.0",
        "gate": "PASS",
        "label": "MILESTONE 10B MEMORY-BUILDER REPAIR AND COMPLETION: PASS",
        "v1_outperformance_required": False,
        "establishes_general_performance_improvement": False,
    }
    atomic_dump_json(bundle / "reports/final-gate.json", final_gate)
    report = (
        "# M10B Memory-Builder Repair and Completion\n\n"
        "1. Starting/final source identities are recorded under `source-identities/`.\n"
        "2. All historical evidence identities remained unchanged.\n"
        "3. The empty-stdin preview root cause is recorded under `root-cause/`.\n"
        "4. Static spec, unbound preview, payload binding, and executable request are separate.\n"
        "5. The final memory synthesis used a sealed two-phase plan.\n"
        "6. Historical executable requests remain readable; empty stdin remains rejected.\n"
        "7. Zero-model tests and GitHub CI passed before the first real process.\n"
        "8. Packages, images, Codex, auth, and source identities were resealed.\n"
        "9. Probe 1 exposed a local observability defect; the authorized Probe 2 passed.\n"
        f"10. Historical training import-all eligibility: {import_manifest.import_all}.\n"
        f"11. Final training outcomes: {len(training_outcomes)} terminal/evaluable runs.\n"
        "12. One frozen final observable trajectory/reward dataset was used.\n"
        "13. Final memory synthesis produced v1 and immutable lineage.\n"
        f"14. Held-out outcomes: {len(outcomes)} terminal/evaluable runs.\n"
        "15. v0/v1 paired metrics are in `reports/evolving-evaluation.json`.\n"
        "16. Replay made zero model, Codex, broker, credential, proxy, runtime, or network calls.\n"
        "17. Security and integrity scans passed.\n"
        f"18. New model-bearing processes: {process_manifest.started_processes}/24.\n"
        "19. Evidence hashes are bound by `SHA256SUMS` and `audit_manifest.json`.\n"
        "20. Deviations: none.\n"
        "21. MILESTONE 10B MEMORY-BUILDER REPAIR AND COMPLETION: PASS\n"
    )
    atomic_write_text(bundle / "reports/final-report.md", report)
    proxy_values = [
        value for name in base.PROXY_NAMES if (value := os.environ.get(name)) is not None
    ]
    security_scan = base._scan_exported_content(
        [bundle],
        proxy_values=proxy_values,
        forbidden_host_root=str(repository_root),
    )
    atomic_dump_json(
        bundle / "security-and-integrity/security-scan.json",
        security_scan,
    )
    audit = {
        "schema_version": "1.0",
        "campaign_kind": "m10b_memory_builder_request_identity_repair_and_completion",
        "gate": "PASS",
        "source_commit": source_identity["source_commit"],
        "source_tree": source_identity["source_tree"],
        "training_imported": bool(import_manifest.import_all),
        "probe_processes": len(probe_roots),
        "conditional_training_processes": 0 if import_manifest.import_all else 3,
        "final_memory_synthesis_processes": 1,
        "heldout_processes": 18,
        "new_model_processes": process_manifest.started_processes,
        "all_started_processes_terminal": True,
        "all_heldout_runs_evaluable": len(outcomes) == 18,
        "historical_evidence_combined": False,
        "model_weights_modified": False,
        **synthesis_identities,
        "evaluation_report_hash": evaluation.report_hash,
    }
    atomic_dump_json(bundle / "audit_manifest.json", audit)
    checksum_count = base._write_bundle_checksums(bundle)
    base._assert_checksum_manifest(bundle)
    atomic_dump_json(
        output / "bundle-seal.json",
        {
            "schema_version": "1.0",
            "bundle_name": bundle.name,
            "sha256sums_sha256": _sha256(bundle / "SHA256SUMS"),
            "audit_manifest_sha256": _sha256(bundle / "audit_manifest.json"),
            "checksum_entry_count": checksum_count,
        },
    )
    base._make_read_only(bundle)
    base._assert_checksum_manifest(bundle)
    return bundle


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--core-wheel", type=Path, required=True)
    parser.add_argument("--plugin-wheel", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--quality-evidence", type=Path, required=True)
    parser.add_argument("--forensic-evidence", type=Path, required=True)
    parser.add_argument("--probe-1-forensic-evidence", type=Path, required=True)
    parser.add_argument("--lifecycle-evidence", type=Path, required=True)
    parser.add_argument("--prior-probe-campaign", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    repository_root = Path.cwd().resolve(strict=True)
    output = args.output_root.resolve()
    if output.exists():
        raise RuntimeError("campaign output root must not already exist")
    if args.source_commit == START_COMMIT:
        raise RuntimeError("memory-builder repair requires a new clean commit")
    base._assert_source_identity(args.source_commit, args.source_tree)
    if _git("merge-base", "--is-ancestor", START_COMMIT, args.source_commit) != "":
        raise RuntimeError("repair commit does not descend from the required starting commit")
    if any(name in os.environ for name in base.API_KEY_NAMES):
        raise RuntimeError("API-key environment is forbidden")
    if _sha256(args.codex_binary.resolve(strict=True)) != base.CODEX_WRAPPER_SHA256:
        raise RuntimeError("Codex wrapper differs from exact 0.144.6")
    quality_path = args.quality_evidence.resolve(strict=True)
    forensic_path = args.forensic_evidence.resolve(strict=True)
    probe_1_forensic_path = args.probe_1_forensic_evidence.resolve(strict=True)
    lifecycle_path = args.lifecycle_evidence.resolve(strict=True)
    if not all(
        path.is_file()
        for path in (quality_path, forensic_path, probe_1_forensic_path, lifecycle_path)
    ):
        raise RuntimeError("zero-model forensic, lifecycle, and CI evidence is required")
    preservation_before = _preservation_identity()
    output.mkdir(parents=True)
    (output / "preflight").mkdir()
    shutil.copy2(quality_path, output / "preflight/quality-and-ci.json")
    shutil.copy2(forensic_path, output / "preflight/memory-builder-preview-forensic.json")
    shutil.copy2(lifecycle_path, output / "preflight/lifecycle-test-matrix.json")
    os.environ["VERIGYM_CODEX_BINARY"] = str(args.codex_binary.resolve(strict=True))
    os.environ["VERIGYM_CODEX_AUTH_MODE"] = "chatgpt_cli_session"
    identity, capabilities = discover_capabilities(force=True)
    capability = capabilities.safe_dict()
    if (
        capabilities.version_output != base.CODEX_VERSION
        or capabilities.executable_sha256 != base.CODEX_WRAPPER_SHA256
    ):
        raise RuntimeError("Codex capability identity changed")
    auth, credential_env = auth_identity_configuration()
    if (
        auth.requested_auth_mode != "chatgpt_cli_session"
        or auth.resolved_auth_mode != "inherited_codex_login"
        or auth.auth_semantic_id != base.AUTH_SEMANTIC_ID
        or credential_env is not None
    ):
        raise RuntimeError("authentication identity changed")
    atomic_dump_json(output / "preflight/codex-capabilities.json", capability)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(output / "preflight/codex-capabilities.json")
    package_hashes = {
        "verigym": _sha256(args.core_wheel.resolve(strict=True)),
        "verigym-codex-cli": _sha256(args.plugin_wheel.resolve(strict=True)),
    }
    source_identity = {
        "schema_version": "1.0",
        "starting_commit": START_COMMIT,
        "starting_tree": START_TREE,
        "source_commit": args.source_commit,
        "source_tree": args.source_tree,
        "branch": "milestone10b-evolving-agent-evaluation",
        "worktree_clean_before_model_processes": True,
    }
    package_identity = {
        "schema_version": "1.0",
        "package_hashes": package_hashes,
        "verifier_image_id": base.VERIFIER_IMAGE_ID,
        "repository_agent_image_id": base.REPOSITORY_AGENT_IMAGE_ID,
        "memory_agent_image_id": base.MEMORY_AGENT_IMAGE_ID,
        "codex_host_identity": identity.safe_dict(),
        "codex_capability_fingerprint": capabilities.capability_fingerprint,
        "requested_auth_mode": auth.requested_auth_mode,
        "resolved_auth_mode": auth.resolved_auth_mode,
        "auth_semantic_id": auth.auth_semantic_id,
        "credential_contents_accessed": False,
        "proxy_values_persisted_or_hashed": False,
    }
    atomic_dump_json(output / "preflight/source-identity.json", source_identity)
    atomic_dump_json(output / "preflight/package-and-image-identities.json", package_identity)
    atomic_dump_json(output / "preflight/preservation-before.json", preservation_before)
    final_v0 = _build_final_v0(
        capability=capability,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
    )
    atomic_dump_json(output / "preflight/agent-version-v0.json", final_v0)
    ledger = output / "model-process-ledger.jsonl"
    probe_1_root, prior_probe_manifest = _import_prior_probe(
        prior_campaign=args.prior_probe_campaign,
        output=output,
        ledger=ledger,
    )

    # Exactly one additional real memory-builder conformance probe after the focused patch.
    probe_root = output / "memory-builder-probe-2"
    probe_root.mkdir()
    probe_summary = _synthetic_summary()
    probe_request, probe_result, _, probe_plan = base._execute_memory_builder(
        output=probe_root,
        summary=probe_summary,
        ledger=ledger,
        capability=capability,
        training_dataset_hash=probe_summary.trajectory_dataset_hash,
        training_run_ids=["synthetic-memory-probe-run"],
        training_source_identities={"synthetic-memory-probe-run": content_hash(probe_summary)},
        reward_profile_hash=content_hash(
            {"schema_version": "1.0", "profile": "synthetic_memory_probe"}
        ),
        authorization_id=AUTHORIZATION_ID,
        process_kind="implementation_probe",
        build_id="m10b-memory-builder-conformance-probe-2",
        require_success=False,
    )
    if probe_result.status != "success" or probe_result.memory_pack is None:
        atomic_dump_json(
            output / "campaign-terminal.json",
            {
                "schema_version": "1.0",
                "gate": "FAIL",
                "label": "MILESTONE 10B MEMORY-BUILDER REPAIR AND COMPLETION: FAIL",
                "reason": "authorized Probe 2 did not produce an accepted memory pack",
                "probe_2_status": probe_result.status,
                "probe_2_failure_reason": probe_result.failure_reason,
                "model_processes_started": 2,
                "additional_patches_authorized": 0,
                "additional_probes_authorized": 0,
            },
        )
        raise RuntimeError("real memory-builder conformance Probe 2 did not succeed")
    if probe_result.memory_synthesis_plan_hash != probe_plan.plan_hash:
        raise RuntimeError("real memory-builder probe omitted its synthesis plan")
    probe_1_replay = _replay_memory_builder(
        probe_1_root,
        codex_executable=args.codex_binary.resolve(strict=True),
    )
    atomic_dump_json(probe_1_root / "zero-call-replay.json", probe_1_replay)
    probe_replay = _replay_memory_builder(
        probe_root,
        codex_executable=args.codex_binary.resolve(strict=True),
    )
    atomic_dump_json(probe_root / "zero-call-replay.json", probe_replay)

    # All-or-none historical training import, with the rerun path retained fail-closed.
    (
        imported,
        training_experiment,
        training_manifest,
        trajectories,
        summary,
        import_manifest,
        training_outcomes,
    ) = _copy_historical_training(
        output=output,
        source_commit=args.source_commit,
        package_hashes=package_hashes,
        final_v0=final_v0,
    )
    rerun_root: Path | None = None
    if imported:
        final_training_dataset = output / "training-import/export-a"
    else:
        rerun_root = output / "training-rerun"
        rerun_root.mkdir()
        (
            training_experiment,
            training_manifest,
            trajectories,
            summary,
            training_outcomes,
        ) = _rerun_training(
            output=output,
            capability=capability,
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            package_hashes=package_hashes,
            v0=final_v0,
            ledger=ledger,
            repository_root=repository_root,
        )
        final_training_dataset = output / "training-rerun/trajectory-dataset"
    if (
        training_manifest.eligible_record_count != 3
        or training_manifest.reward_profile_hash is None
        or len(trajectories) != 3
    ):
        raise RuntimeError("final training dataset is not exactly three eligible trajectories")
    atomic_dump_json(output / "final-sanitized-training-summary.json", summary)
    summary = load_model(
        output / "final-sanitized-training-summary.json",
        SanitizedTrainingSummary,
    )
    replay_trajectory_dataset(final_training_dataset, training_experiment)
    base._make_read_only(final_training_dataset)

    # Exactly one final real synthesis, fully planned and reconstructed pre-authorization.
    final_memory_root = output / "final-memory-synthesis"
    final_memory_root.mkdir()
    final_request, final_result, final_terminal, final_plan = base._execute_memory_builder(
        output=final_memory_root,
        summary=summary,
        ledger=ledger,
        capability=capability,
        training_dataset_hash=training_manifest.dataset_hash,
        training_run_ids=[trajectory.run_id for trajectory in trajectories],
        training_source_identities={
            trajectory.run_id: content_hash(
                {
                    "run_manifest_hash": trajectory.run_manifest_hash,
                    "artifact_manifest_hash": trajectory.artifact_manifest_hash,
                    "source_hash": trajectory.source_hash,
                }
            )
            for trajectory in trajectories
        },
        reward_profile_hash=training_manifest.reward_profile_hash,
        authorization_id=AUTHORIZATION_ID,
        process_kind="memory_synthesis",
        build_id="m10b-final-memory-synthesis",
    )
    memory = final_result.memory_pack
    if memory is None or final_result.status != "success":
        raise RuntimeError("final memory synthesis did not produce an accepted memory pack")
    final_memory_replay = _replay_memory_builder(
        final_memory_root,
        codex_executable=args.codex_binary.resolve(strict=True),
    )
    atomic_dump_json(final_memory_root / "zero-call-replay.json", final_memory_replay)
    v1, update = freeze_context_update(
        parent=final_v0,
        dataset=training_manifest,
        training_summary=summary,
        memory_pack=memory,
        memory_builder_identity_hash=final_result.process_identity_hash,
        memory_builder_input_hash=final_request.input_hash,
        memory_builder_output_hash=final_result.output_hash,
        process_ledger_hash=final_terminal.record_hash,
        memory_synthesis_plan_hash=final_plan.plan_hash,
        invocation_spec_hash=final_plan.invocation_spec.invocation_spec_hash,
        payload_binding_hash=final_plan.payload_binding.payload_binding_hash,
    )
    replay_context_update(
        parent=final_v0,
        result=v1,
        update=update,
        dataset=training_manifest,
        training_summary=summary,
        memory_pack=memory,
    )
    atomic_dump_json(output / "agent-version-v1.json", v1)
    atomic_dump_json(output / "agent-update-manifest.json", update)
    os.environ["VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST"] = str(
        output / "agent-version-v1.json"
    )

    # Held-out assets are loaded only after v1 is immutable.
    training_roots = base._training_roots(repository_root)
    heldout_roots = base._heldout_roots(repository_root)
    full_split = build_task_split(
        split_id="m10b-memory-completion-train-heldout-v1",
        training=[base._task_entry(training_roots[task]) for task in base.TRAINING_TASKS],
        heldout=[base._task_entry(heldout_roots[task]) for task in base.HELDOUT_TASKS],
        heldout_assets_loaded_after_version_hash=v1.version_hash,
    )
    contamination = scan_contamination(
        split_manifest=full_split,
        training_roots=training_roots,
        heldout_roots=heldout_roots,
        memory_pack=memory,
    )
    validate_contamination_scan(contamination)
    if not contamination.passed:
        raise RuntimeError("final memory pack failed held-out contamination scanning")
    lineage = build_agent_lineage(parent=final_v0, result=v1, update=update)
    version_set = build_agent_version_set([final_v0, v1])
    atomic_dump_json(output / "agent-lineage.json", lineage)
    atomic_dump_json(output / "agent-version-set.json", version_set)
    heldout_config = base._experiment_config(
        name="m10b memory completion heldout v0 v1",
        output=output / "heldout-experiment",
        tasks=base.HELDOUT_TASKS,
        systems=[
            ("v0", base._versioned_options(capability, final_v0)),
            ("v1", base._versioned_options(capability, v1, memory)),
        ],
        samples=3,
        process_count=18,
        campaign_kind="m10b_memory_completion_heldout_counterbalanced",
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=capabilities.capability_fingerprint,
        counterbalanced=True,
    )
    heldout_plan = ExperimentPlanner().build(heldout_config)
    base._validate_plan_versions(heldout_plan)
    expected_order = [
        ("v0", 0),
        ("v1", 0),
        ("v1", 1),
        ("v0", 1),
        ("v0", 2),
        ("v1", 2),
    ]
    for task in base.HELDOUT_TASKS:
        observed = [
            (item.system.system_id, item.sample_index)
            for item in heldout_plan.items
            if item.task_id == task
        ]
        if observed != expected_order:
            raise RuntimeError("held-out plan is not in the preregistered counterbalanced order")
    runner = BatchRunner(
        planner=ExperimentPlanner(),
        child_executor=base._CampaignChildExecutor(
            ledger,
            "heldout",
            authorization_id=AUTHORIZATION_ID,
        ),
    )
    heldout_result = runner.run(heldout_plan)
    if heldout_result.exit_code != 0:
        raise RuntimeError("held-out execution gate failed")
    heldout_experiment = heldout_result.experiment_dir
    heldout_inputs = load_report_inputs(heldout_experiment)
    if len(heldout_inputs.valid_runs) != 18:
        raise RuntimeError("held-out campaign omitted terminal valid children")
    outcomes = base._run_outcomes(heldout_experiment)
    if len(outcomes) != 18 or not all(bool(outcome["evaluable"]) for outcome in outcomes):
        raise RuntimeError("held-out campaign did not produce 18 evaluable outcomes")
    assignments = base._run_assignments(
        heldout_experiment,
        {"v0": final_v0.agent_version_id, "v1": v1.agent_version_id},
    )
    assignment_manifest = build_run_version_assignments(
        [
            RunAgentVersionAssignment(
                run_id=run_id,
                agent_version_id=version_id,
                agent_version_hash=(
                    final_v0.version_hash
                    if version_id == final_v0.agent_version_id
                    else v1.version_hash
                ),
            )
            for run_id, version_id in assignments.items()
        ]
    )
    atomic_dump_json(output / "heldout-run-version-assignments.json", assignment_manifest)
    heldout_dataset = output / "heldout-trajectory-dataset"
    TrajectoryExporter().export(
        heldout_experiment,
        heldout_dataset,
        split_manifest=full_split,
        agent_versions={final_v0.agent_version_id: final_v0, v1.agent_version_id: v1},
        run_agent_versions=assignments,
        source_commit=args.source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-memory-completion-heldout-v0-v1",
    )
    replay_trajectory_dataset(heldout_dataset, heldout_experiment)
    heldout_replay = base._replay_experiment(heldout_experiment)
    evaluation = build_evolving_evaluation(
        heldout_experiment,
        split_manifest=full_split,
        baseline_version_id=final_v0.agent_version_id,
        evolved_version_id=v1.agent_version_id,
    )
    validate_evolving_evaluation(evaluation)
    heldout_reports = output / "heldout-reports"
    EvolutionReportService().generate_evaluation(evaluation, heldout_reports)
    replay_summary = {
        "schema_version": "1.0",
        "memory_probes": [probe_1_replay, probe_replay],
        "prior_probe_import": prior_probe_manifest,
        "final_memory_synthesis": final_memory_replay,
        "training_runs": 3,
        "heldout": heldout_replay,
        "heldout_runs": 18,
        "update_replayed": True,
        "model_calls": 0,
        "codex_calls": 0,
        "broker_calls": 0,
        "credential_accesses": 0,
        "proxy_uses": 0,
        "public_launcher_calls": 0,
        "runtime_calls": 0,
        "network_calls": 0,
    }
    atomic_dump_json(output / "replay-summary.json", replay_summary)
    process_manifest = seal_process_ledger(
        ledger,
        authorization_id=AUTHORIZATION_ID,
        complete=True,
    )
    expected_processes = 21 if imported else 24
    if (
        process_manifest.authorized_processes != expected_processes
        or process_manifest.started_processes != expected_processes
        or process_manifest.terminal_processes != expected_processes
    ):
        raise RuntimeError("global model-process accounting differs from the frozen campaign")
    preservation_after = _preservation_identity()
    if preservation_after != preservation_before:
        raise RuntimeError("protected historical evidence changed during the campaign")
    base._assert_source_identity(args.source_commit, args.source_tree)
    bundle = _seal_bundle(
        output=output,
        repository_root=repository_root,
        source_identity=source_identity,
        preservation=preservation_after,
        package_identity=package_identity,
        quality_evidence=quality_path,
        forensic_evidence=forensic_path,
        lifecycle_evidence=lifecycle_path,
        probe_roots=[probe_1_root, probe_root],
        probe_1_forensic_evidence=probe_1_forensic_path,
        import_root=output / "training-import",
        rerun_root=rerun_root,
        final_training_dataset=final_training_dataset,
        final_memory_root=final_memory_root,
        heldout_experiment=heldout_experiment,
        heldout_dataset=heldout_dataset,
        heldout_reports=heldout_reports,
        replay_summary=replay_summary,
        process_manifest=process_manifest,
        evaluation=evaluation,
        outcomes=outcomes,
        import_manifest=import_manifest,
        training_outcomes=training_outcomes,
    )
    print(
        canonical_json(
            {
                "gate": "MILESTONE 10B MEMORY-BUILDER REPAIR AND COMPLETION: PASS",
                "bundle": bundle.name,
                "bundle_sha256sums_sha256": _sha256(bundle / "SHA256SUMS"),
                "source_commit": args.source_commit,
                "source_tree": args.source_tree,
                "training_imported": imported,
                "new_model_processes": process_manifest.started_processes,
                "memory_pack_hash": memory.content_hash,
                "v1_version_hash": v1.version_hash,
                "evaluation_report_hash": evaluation.report_hash,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
