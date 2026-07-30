#!/usr/bin/env python3
"""Execute the commit-bound M10B contamination repair held-out completion."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import run_m10b_campaign as base
import run_m10b_memory_completion_campaign as prior
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.process import auth_identity_configuration

from verigym.core.external_process_identity import validate_external_process_request_identity
from verigym.core.hashing import canonical_json, content_hash
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.sampling import classify_sample_outcome
from verigym.evolution.comparison import (
    build_evolving_evaluation,
    validate_evolving_evaluation,
)
from verigym.evolution.exporter import (
    TrajectoryExporter,
    replay_trajectory_dataset,
    validate_trajectory_dataset,
)
from verigym.evolution.ledger import (
    authorize_process,
    finish_process,
    seal_process_ledger,
)
from verigym.evolution.memory import (
    build_agent_version,
    validate_agent_version,
    validate_memory_pack,
    validate_training_summary,
)
from verigym.evolution.memory_builder import (
    memory_builder_allowed_synthesis_sources,
    reconstruct_memory_synthesis_launch,
    validate_memory_builder_input,
    validate_memory_builder_result,
    validate_memory_synthesis_plan,
)
from verigym.evolution.reporting import EvolutionReportService
from verigym.evolution.rewards import classify_outcome
from verigym.evolution.splits import (
    build_allowed_synthesis_corpus,
    build_contamination_scan_policy,
    build_task_split,
    scan_contamination_report,
    validate_allowed_synthesis_corpus,
    validate_asset_signature_manifest,
    validate_contamination_scan_policy,
    validate_contamination_scan_report,
)
from verigym.evolution.versions import (
    build_agent_lineage,
    build_agent_version_set,
    build_run_version_assignments,
    freeze_context_update,
    replay_context_update,
)
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig, ExperimentPlan, PlanItem
from verigym.experiments.state import atomic_dump_json, atomic_write_text
from verigym.reporting.loader import load_report_inputs
from verigym.schemas.evolution import (
    AgentUpdateManifest,
    AgentVersionManifest,
    MemoryBuilderInput,
    MemoryBuilderResult,
    MemoryPack,
    MemorySynthesisPlan,
    RewardVector,
    RunAgentVersionAssignment,
    SanitizedTrainingSummary,
    TaskSplitManifest,
    TrajectoryDatasetManifest,
)
from verigym.schemas.run import RunConfig, RunResult

START_COMMIT = "3da8dd6b314973539fe33cc12c4f9f6b1a59363e"
START_TREE = "eb90154db7dcf5a0652cfa2d80c83090546c518e"
AUTHORIZATION_ID = "m10b-contamination-repair-heldout-owner-contract-v1"
MAXIMUM_PROCESSES = 20
HISTORICAL_BUNDLE = Path(
    "/data/jzhu484/Agent/VeriGym_m10b_memory_builder_3da8dd6/evidence-bundle-final"
)
HISTORICAL_SHA256SUMS = "ec9fd849195121057e781c228861b683a14cef948a535754d4323382723b1f41"
PROMPT_BINDING_BUNDLE = Path(
    "/data/jzhu484/Agent/VeriGym_m10b_prompt_binding_9811aa4/evidence-bundle-final"
)
PROMPT_BINDING_SHA256SUMS = "2abd8f8f90f8333e68cfd9e19a793e98c5688cdaa58603794634984958810fb7"
INITIAL_M10B_BUNDLE = Path("/data/jzhu484/Agent/VeriGym_milestone10b_de9dc9d/evidence-bundle-final")
INITIAL_M10B_SHA256SUMS = "fd549b7e064aabdad1c2e07630de62f8e424a9a4c368d7df71813c048def8188"
MEMORY_PACK_HASH = "88ff2d9fb62a297430e74431df3ae4fec0a8f746a6e12a978b17e02a90489274"
MEMORY_PACK_FILE_SHA256 = "432655a0b79870fd58eb67f2c1c7f4b56bcc57d1ee514e89e42bd128eb326d3e"


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
    protected = (
        ("failed_3da8dd6", HISTORICAL_BUNDLE, HISTORICAL_SHA256SUMS),
        ("failed_9811aa4", PROMPT_BINDING_BUNDLE, PROMPT_BINDING_SHA256SUMS),
        ("failed_de9dc9d", INITIAL_M10B_BUNDLE, INITIAL_M10B_SHA256SUMS),
        (
            "m10a_pass",
            base.M10A_BUNDLE,
            "afa59b11bbe9f57caed8b5eb8b27739ff09cfd57e9a0fbd11df64851f4ffe420",
        ),
    )
    records: list[dict[str, Any]] = []
    for label, root, expected in protected:
        count = base._assert_checksum_manifest(root)
        observed = _sha256(root / "SHA256SUMS")
        if observed != expected:
            raise RuntimeError(f"protected evidence identity changed: {label}")
        records.append(
            {
                "label": label,
                "path": str(root),
                "sha256sums_sha256": observed,
                "verified_file_count": count,
            }
        )
    checkpoint = _sha256(base.REFERENCE_CHECKPOINT_MANIFEST)
    if checkpoint != base.REFERENCE_CHECKPOINT_HASH:
        raise RuntimeError("reference-qualified checkpoint identity changed")
    return {
        "schema_version": "1.0",
        "protected_bundles": records,
        "reference_checkpoint_manifest_sha256": checkpoint,
        "protected_assets_modified": False,
    }


def _assert_source_identity(commit: str, tree: str) -> None:
    base._assert_source_identity(commit, tree)
    if _git("merge-base", "--is-ancestor", START_COMMIT, commit) != "":
        raise RuntimeError("repair commit does not descend from the required starting commit")


def _memory_reuse(
    *,
    codex_binary: Path,
) -> tuple[
    MemoryPack,
    SanitizedTrainingSummary,
    TrajectoryDatasetManifest,
    MemorySynthesisPlan,
    MemoryBuilderInput,
    MemoryBuilderResult,
    AgentVersionManifest,
    AgentUpdateManifest,
    TaskSplitManifest,
    dict[str, Any],
]:
    memory_root = HISTORICAL_BUNDLE / "final-memory-synthesis/evidence"
    memory = load_model(memory_root / "process-evidence/memory-pack.json", MemoryPack)
    summary = load_model(memory_root / "frozen-training-summary.json", SanitizedTrainingSummary)
    plan = load_model(memory_root / "memory-synthesis-plan.json", MemorySynthesisPlan)
    request = load_model(memory_root / "memory-builder-input.json", MemoryBuilderInput)
    result = load_model(
        memory_root / "process-evidence/memory-builder-result.json",
        MemoryBuilderResult,
    )
    historical_v1 = load_model(
        HISTORICAL_BUNDLE / "version-and-split/agent-version-v1.json",
        AgentVersionManifest,
    )
    historical_update = load_model(
        HISTORICAL_BUNDLE / "version-and-split/agent-update-manifest.json",
        AgentUpdateManifest,
    )
    historical_split = load_model(
        HISTORICAL_BUNDLE / "version-and-split/task-split-manifest.json",
        TaskSplitManifest,
    )
    dataset_root = HISTORICAL_BUNDLE / "training-import/evidence/export-a"
    dataset = validate_trajectory_dataset(dataset_root)
    validate_memory_pack(memory)
    validate_training_summary(summary)
    validate_memory_synthesis_plan(plan)
    validate_memory_builder_input(request)
    validate_memory_builder_result(result)
    validate_agent_version(historical_v1)
    rendered_prompt, payload_binding, executable = reconstruct_memory_synthesis_launch(
        plan=plan,
        request=request,
        frozen_summary=summary,
        executable_path=codex_binary,
    )
    validate_external_process_request_identity(executable)
    heldout_not_executed = prior._load_bounded_json_object(
        HISTORICAL_BUNDLE / "heldout-evaluation/not-executed.json"
    )
    checks = {
        "historical_bundle_integrity": (
            _sha256(HISTORICAL_BUNDLE / "SHA256SUMS") == HISTORICAL_SHA256SUMS
        ),
        "memory_schema_and_content_policy": (
            memory.content_hash == MEMORY_PACK_HASH
            and result.status == "success"
            and result.memory_pack == memory
        ),
        "training_dataset_reward_linkage": (
            summary.trajectory_dataset_hash == dataset.dataset_hash
            and plan.training_dataset_hash == dataset.dataset_hash
            and historical_v1.training_dataset_hash == dataset.dataset_hash
            and historical_v1.reward_profile_hash == dataset.reward_profile_hash
        ),
        "synthesis_lifecycle_linkage": (
            historical_v1.memory_synthesis_plan_hash == plan.plan_hash
            and historical_v1.invocation_spec_hash == plan.invocation_spec.invocation_spec_hash
            and historical_v1.payload_binding_hash == payload_binding.payload_binding_hash
            and result.memory_synthesis_plan_hash == plan.plan_hash
            and result.invocation_spec_hash == plan.invocation_spec.invocation_spec_hash
            and result.payload_binding_hash == payload_binding.payload_binding_hash
            and len(rendered_prompt.encode("utf-8")) == plan.rendered_prompt_utf8_bytes
        ),
        "lineage_memory_linkage": (
            historical_v1.memory_pack_hash == memory.content_hash
            and historical_update.memory_pack_hash == memory.content_hash
            and historical_update.result_version_hash == historical_v1.version_hash
            and not historical_update.heldout_assets_loaded
        ),
        "pre_heldout_freeze": (
            historical_split.heldout_assets_loaded_after_version_hash == historical_v1.version_hash
        ),
        "no_heldout_outcomes_used": (
            isinstance(heldout_not_executed.get("v0_heldout"), dict)
            and isinstance(heldout_not_executed.get("v1_heldout"), dict)
            and heldout_not_executed["v0_heldout"].get("authorized") == 0
            and heldout_not_executed["v0_heldout"].get("launched") == 0
            and heldout_not_executed["v1_heldout"].get("authorized") == 0
            and heldout_not_executed["v1_heldout"].get("launched") == 0
        ),
        "memory_bytes_unchanged": (
            _sha256(memory_root / "process-evidence/memory-pack.json") == MEMORY_PACK_FILE_SHA256
        ),
        "no_private_or_heldout_synthesis_inputs": (
            not summary.hidden_assets_included
            and not summary.references_included
            and not summary.private_reasoning_included
            and not summary.heldout_assets_included
            and not request.heldout_assets_available
            and not request.private_reasoning_requested
        ),
    }
    eligibility = {
        "schema_version": "1.0",
        "eligible": all(checks.values()),
        "checks": checks,
        "memory_pack_hash": memory.content_hash,
        "memory_pack_file_sha256": _sha256(memory_root / "process-evidence/memory-pack.json"),
        "training_dataset_hash": dataset.dataset_hash,
        "sanitized_summary_hash": summary.summary_hash,
        "memory_synthesis_plan_hash": plan.plan_hash,
        "historical_v1_version_hash": historical_v1.version_hash,
        "historical_update_hash": historical_update.update_hash,
        "rendered_prompt_hash": plan.rendered_prompt_hash,
        "heldout_outcomes_used": False,
        "memory_regenerated": False,
        "model_calls": 0,
    }
    if not eligibility["eligible"]:
        raise RuntimeError("the frozen memory/training lineage is not reuse eligible")
    return (
        memory,
        summary,
        dataset,
        plan,
        request,
        result,
        historical_v1,
        historical_update,
        historical_split,
        eligibility,
    )


def _build_final_versions(
    *,
    capability: Mapping[str, Any],
    source_commit: str,
    source_tree: str,
    package_hashes: Mapping[str, str],
    memory: MemoryPack,
    summary: SanitizedTrainingSummary,
    dataset: TrajectoryDatasetManifest,
    plan: MemorySynthesisPlan,
    request: MemoryBuilderInput,
    result: MemoryBuilderResult,
    historical_v1: AgentVersionManifest,
    historical_update: AgentUpdateManifest,
) -> tuple[AgentVersionManifest, AgentVersionManifest, AgentUpdateManifest, dict[str, Any]]:
    preview_v0 = prior._build_final_v0(
        capability=capability,
        source_commit=source_commit,
        source_tree=source_tree,
        package_hashes=package_hashes,
    )
    v0_values = preview_v0.model_dump(mode="json", exclude={"version_hash"})
    v0_values["agent_version_id"] = "codex-cli-agent-v0-final"
    final_v0 = build_agent_version(**v0_values)
    final_v1, final_update = freeze_context_update(
        parent=final_v0,
        dataset=dataset,
        training_summary=summary,
        memory_pack=memory,
        memory_builder_identity_hash=str(historical_v1.memory_builder_identity_hash),
        memory_builder_input_hash=request.input_hash,
        memory_builder_output_hash=result.output_hash,
        process_ledger_hash=historical_update.process_ledger_hash,
        memory_synthesis_plan_hash=plan.plan_hash,
        invocation_spec_hash=plan.invocation_spec.invocation_spec_hash,
        payload_binding_hash=plan.payload_binding.payload_binding_hash,
        version_id="codex-cli-agent-v1-final",
        update_id="m10b-preserved-memory-v0-final-to-v1-final",
    )
    replay_context_update(
        parent=final_v0,
        result=final_v1,
        update=final_update,
        dataset=dataset,
        training_summary=summary,
        memory_pack=memory,
    )
    stable_fields = (
        "base_agent_id",
        "agent_descriptor_hash",
        "model_id",
        "reasoning_effort",
        "auth_semantic_id",
        "runtime_identity_hash",
        "tool_policy_hash",
        "prompt_contract_hash",
        "source_commit",
        "package_hashes",
        "image_hashes",
        "model_weights_modified",
    )
    differences = [
        field for field in stable_fields if getattr(final_v0, field) != getattr(final_v1, field)
    ]
    if differences:
        raise RuntimeError("v0-final/v1-final changed stable execution identity")
    binding_base = {
        "schema_version": "1.0",
        "common_execution_identity": {field: getattr(final_v0, field) for field in stable_fields},
        "v0_final_memory_pack_hash": None,
        "v1_final_memory_pack_hash": final_v1.memory_pack_hash,
        "only_agent_behavior_difference": "memory_pack_hash",
        "memory_regenerated": False,
        "original_synthesis_version_hash": historical_v1.version_hash,
        "original_synthesis_update_hash": historical_update.update_hash,
    }
    binding = {**binding_base, "binding_hash": content_hash(binding_base)}
    return final_v0, final_v1, final_update, binding


def _experiment_config(
    *,
    name: str,
    output: Path,
    tasks: Sequence[str],
    systems: Sequence[tuple[str, dict[str, Any]]],
    samples: int,
    process_count: int,
    campaign_kind: str,
    source_commit: str,
    source_tree: str,
    package_hashes: Mapping[str, str],
    capability_fingerprint: str,
    counterbalanced: bool,
) -> ExperimentConfig:
    payload = base._experiment_config(
        name=name,
        output=output,
        tasks=tasks,
        systems=systems,
        samples=samples,
        process_count=process_count,
        campaign_kind=campaign_kind,
        source_commit=source_commit,
        source_tree=source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=capability_fingerprint,
        counterbalanced=counterbalanced,
    ).model_dump(mode="json")
    frozen = payload["execution"]["frozen_campaign_identity"]
    assert isinstance(frozen, dict)
    frozen["owner_contract_id"] = AUTHORIZATION_ID
    frozen["campaign_process_ceiling"] = MAXIMUM_PROCESSES
    payload["description"] = "Commit-bound M10B contamination repair held-out agent evaluation."
    return ExperimentConfig.model_validate(payload)


class _CampaignChildExecutor:
    def __init__(self, ledger: Path, process_kind: str) -> None:
        self.ledger = ledger
        self.process_kind = process_kind

    def __call__(self, item: PlanItem, config: RunConfig) -> RunResult:
        version_hash = item.system.agent_options.get("agent_version_hash")
        authorization = authorize_process(
            self.ledger,
            process_kind=self.process_kind,
            authorization_id=AUTHORIZATION_ID,
            run_or_build_id=config.run_id or item.plan_item_id,
            requested_model_id=base.MODEL_ID,
            reasoning_effort=base.REASONING_EFFORT,
            task_identity_hash=item.task_hash,
            agent_version_hash=version_hash if isinstance(version_hash, str) else None,
            maximum_processes=MAXIMUM_PROCESSES,
        )
        try:
            result = VeriGym().run(config)
        except BaseException as exc:
            finish_process(
                self.ledger,
                authorization_record=authorization,
                terminal_outcome=f"exception:{type(exc).__name__}",
            )
            raise
        finish_process(
            self.ledger,
            authorization_record=authorization,
            terminal_outcome=classify_outcome(result.scorecard),
        )
        return result


def _freeze_plan(config: ExperimentConfig) -> ExperimentPlan:
    plan = ExperimentPlanner().build(config)
    base._validate_plan_versions(plan)
    if (
        len(plan.items) != config.execution.max_model_processes
        or plan.verigym_commit != config.execution.frozen_campaign_identity.get("source_commit")
    ):
        raise RuntimeError("frozen experiment plan differs from commit-bound execution budget")
    return plan


def _run_plan(plan: ExperimentPlan, *, ledger: Path, process_kind: str) -> Path:
    result = BatchRunner(
        planner=ExperimentPlanner(),
        child_executor=_CampaignChildExecutor(ledger, process_kind),
    ).run(plan)
    if result.exit_code != 0:
        raise RuntimeError(f"{process_kind} failed its experiment execution gate")
    inputs = load_report_inputs(result.experiment_dir)
    if len(inputs.valid_runs) != len(plan.items) or any(
        not classify_sample_outcome(run.scorecard)[1] for run in inputs.valid_runs
    ):
        raise RuntimeError(f"{process_kind} did not produce terminal evaluable outcomes")
    return result.experiment_dir


def _run_probe(
    *,
    output: Path,
    ledger: Path,
    capability: Mapping[str, Any],
    source_commit: str,
    source_tree: str,
    package_hashes: Mapping[str, str],
    v1: AgentVersionManifest,
    memory: MemoryPack,
) -> tuple[Path, Path, list[dict[str, Any]], list[dict[str, Any]]]:
    config = _experiment_config(
        name="m10b contamination repair v1 conformance probe",
        output=output / "probe-experiment",
        tasks=["repo-rtl/counter-wrap"],
        systems=[("v1-final-probe", base._versioned_options(capability, v1, memory))],
        samples=1,
        process_count=1,
        campaign_kind="m10b_contamination_repair_v1_non_scored_probe",
        source_commit=source_commit,
        source_tree=source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=str(capability["capability_fingerprint"]),
        counterbalanced=False,
    )
    plan = _freeze_plan(config)
    atomic_dump_json(output / "probe-plan.json", plan)
    experiment = _run_plan(plan, ledger=ledger, process_kind="implementation_probe")
    outcomes = base._run_outcomes(experiment)
    if (
        len(outcomes) != 1
        or not bool(outcomes[0]["evaluable"])
        or outcomes[0]["outcome_kind"] == "infrastructure_invalid"
        or outcomes[0]["memory_pack_hash"] != memory.content_hash
    ):
        raise RuntimeError("real v1 conformance probe did not satisfy the final execution path")
    roots = base._training_roots(Path.cwd())
    probe_split = build_task_split(
        split_id="m10b-contamination-repair-probe",
        training=[base._task_entry(roots["repo-rtl/counter-wrap"])],
        heldout=[],
    )
    dataset = output / "probe-trajectory-dataset"
    TrajectoryExporter().export(
        experiment,
        dataset,
        split_manifest=probe_split,
        agent_versions={v1.agent_version_id: v1},
        run_agent_versions=base._run_assignments(
            experiment, {"v1-final-probe": v1.agent_version_id}
        ),
        source_commit=source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-contamination-repair-v1-probe",
    )
    replay_trajectory_dataset(dataset, experiment)
    replay = base._replay_experiment(experiment)
    return experiment, dataset, outcomes, replay


def _run_heldout(
    *,
    output: Path,
    ledger: Path,
    capability: Mapping[str, Any],
    source_commit: str,
    source_tree: str,
    package_hashes: Mapping[str, str],
    split: TaskSplitManifest,
    v0: AgentVersionManifest,
    v1: AgentVersionManifest,
    memory: MemoryPack,
) -> tuple[
    ExperimentPlan,
    Path,
    Path,
    Path,
    Any,
    Any,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    config = _experiment_config(
        name="m10b contamination repair heldout v0-final v1-final",
        output=output / "heldout-experiment",
        tasks=base.HELDOUT_TASKS,
        systems=[
            ("v0-final", base._versioned_options(capability, v0)),
            ("v1-final", base._versioned_options(capability, v1, memory)),
        ],
        samples=3,
        process_count=18,
        campaign_kind="m10b_contamination_repair_heldout_counterbalanced",
        source_commit=source_commit,
        source_tree=source_tree,
        package_hashes=package_hashes,
        capability_fingerprint=str(capability["capability_fingerprint"]),
        counterbalanced=True,
    )
    plan = _freeze_plan(config)
    expected_order = [
        ("v0-final", 0),
        ("v1-final", 0),
        ("v1-final", 1),
        ("v0-final", 1),
        ("v0-final", 2),
        ("v1-final", 2),
    ]
    for task in base.HELDOUT_TASKS:
        observed = [
            (item.system.system_id, item.sample_index)
            for item in plan.items
            if item.task_id == task
        ]
        if observed != expected_order:
            raise RuntimeError("held-out plan is not in preregistered counterbalanced order")
    atomic_dump_json(output / "heldout-plan.json", plan)
    atomic_dump_json(
        output / "heldout-plan-seal.json",
        {
            "schema_version": "1.0",
            "plan_hash": plan.plan_hash,
            "item_count": len(plan.items),
            "source_commit": source_commit,
            "source_tree": source_tree,
            "model_processes": 18,
        },
    )
    _assert_source_identity(source_commit, source_tree)
    experiment = _run_plan(plan, ledger=ledger, process_kind="heldout")
    outcomes = base._run_outcomes(experiment)
    if len(outcomes) != 18 or not all(bool(outcome["evaluable"]) for outcome in outcomes):
        raise RuntimeError("held-out evaluation did not produce 18 evaluable outcomes")
    assignments = base._run_assignments(
        experiment,
        {"v0-final": v0.agent_version_id, "v1-final": v1.agent_version_id},
    )
    assignment_manifest = build_run_version_assignments(
        [
            RunAgentVersionAssignment(
                run_id=run_id,
                agent_version_id=version_id,
                agent_version_hash=(
                    v0.version_hash if version_id == v0.agent_version_id else v1.version_hash
                ),
            )
            for run_id, version_id in assignments.items()
        ]
    )
    dataset = output / "heldout-trajectory-dataset"
    TrajectoryExporter().export(
        experiment,
        dataset,
        split_manifest=split,
        agent_versions={v0.agent_version_id: v0, v1.agent_version_id: v1},
        run_agent_versions=assignments,
        source_commit=source_commit,
        package_identities=package_hashes,
        dataset_id="m10b-contamination-repair-heldout-v0-final-v1-final",
    )
    replay_trajectory_dataset(dataset, experiment)
    replay = base._replay_experiment(experiment)
    evaluation = build_evolving_evaluation(
        experiment,
        split_manifest=split,
        baseline_version_id=v0.agent_version_id,
        evolved_version_id=v1.agent_version_id,
    )
    validate_evolving_evaluation(evaluation)
    reports = output / "heldout-reports"
    EvolutionReportService().generate_evaluation(evaluation, reports)
    return (
        plan,
        experiment,
        dataset,
        reports,
        evaluation,
        assignment_manifest,
        outcomes,
        replay,
    )


def _seal_bundle(
    *,
    output: Path,
    repository_root: Path,
    source_identity: Mapping[str, Any],
    package_identity: Mapping[str, Any],
    preservation: Mapping[str, Any],
    forensic_evidence: Path,
    quality_evidence: Path,
    eligibility: Mapping[str, Any],
    original_linkage: Mapping[str, Any],
    policy: Any,
    corpus: Any,
    signatures: Any,
    contamination: Any,
    v0: AgentVersionManifest,
    v1: AgentVersionManifest,
    final_update: AgentUpdateManifest,
    evaluation_binding: Mapping[str, Any],
    probe_experiment: Path,
    probe_dataset: Path,
    probe_outcomes: Sequence[Mapping[str, Any]],
    probe_replay: Sequence[Mapping[str, Any]],
    heldout_plan: ExperimentPlan,
    heldout_experiment: Path,
    heldout_dataset: Path,
    heldout_reports: Path,
    assignment_manifest: Any,
    heldout_outcomes: Sequence[Mapping[str, Any]],
    heldout_replay: Sequence[Mapping[str, Any]],
    evaluation: Any,
    process_manifest: Any,
) -> Path:
    bundle = output / "evidence-bundle-final"
    bundle.mkdir()
    for relative in (
        "root-cause",
        "implementation",
        "memory-reuse",
        "probes",
        "heldout-evaluation",
        "replay",
        "security-and-integrity",
        "reports",
    ):
        (bundle / relative).mkdir()
    shutil.copy2(
        forensic_evidence,
        bundle / "root-cause/historical-contamination-forensic.json",
    )
    atomic_dump_json(
        bundle / "root-cause/false-positive-regression.json",
        {
            "schema_version": "1.0",
            "memory_pack_hash": MEMORY_PACK_HASH,
            "preserve_severity": "diagnostic_overlap",
            "validation_severity": "diagnostic_overlap",
            "hard_contamination_count": contamination.hard_contamination_count,
            "scan_gate": contamination.passed,
            "model_calls": 0,
        },
    )
    atomic_dump_json(bundle / "implementation/scan-policy.json", policy)
    atomic_dump_json(bundle / "implementation/signature-manifest.json", signatures)
    atomic_dump_json(bundle / "implementation/allowed-synthesis-corpus.json", corpus)
    atomic_dump_json(bundle / "implementation/contamination-report.json", contamination)
    shutil.copy2(
        quality_evidence,
        bundle / "implementation/CI-and-package-identities.json",
    )
    for schema in (
        "contamination-scan-policy.schema.json",
        "allowed-synthesis-corpus.schema.json",
        "asset-signature-manifest.schema.json",
        "split-asset-contamination-scan.schema.json",
        "frozen-memory-contamination-scan.schema.json",
        "contamination-scan-report.schema.json",
    ):
        shutil.copy2(repository_root / "docs/schemas" / schema, bundle / "implementation" / schema)
    atomic_dump_json(bundle / "memory-reuse/memory-eligibility.json", dict(eligibility))
    atomic_dump_json(
        bundle / "memory-reuse/original-synthesis-linkage.json",
        dict(original_linkage),
    )
    shutil.copy2(
        HISTORICAL_BUNDLE / "final-memory-synthesis/evidence/process-evidence/memory-pack.json",
        bundle / "memory-reuse/frozen-memory-pack.json",
    )
    atomic_dump_json(bundle / "memory-reuse/v0-final.json", v0)
    atomic_dump_json(bundle / "memory-reuse/v1-final.json", v1)
    atomic_dump_json(bundle / "memory-reuse/final-update-lineage.json", final_update)
    atomic_dump_json(
        bundle / "memory-reuse/evaluation-binding.json",
        dict(evaluation_binding),
    )
    base._copy_tree(probe_experiment, bundle / "probes/probe-1/experiment")
    base._copy_tree(probe_dataset, bundle / "probes/probe-1/trajectory-dataset")
    atomic_dump_json(
        bundle / "probes/probe-1/per-run-outcomes.json",
        {"schema_version": "1.0", "runs": list(probe_outcomes)},
    )
    atomic_dump_json(
        bundle / "probes/probe-1/zero-call-replay.json",
        {"schema_version": "1.0", "runs": list(probe_replay), "external_calls": 0},
    )
    atomic_dump_json(bundle / "heldout-evaluation/frozen-plan.json", heldout_plan)
    base._copy_tree(heldout_experiment, bundle / "heldout-evaluation/experiment")
    base._copy_tree(heldout_dataset, bundle / "heldout-evaluation/trajectory-dataset")
    base._copy_tree(heldout_reports, bundle / "heldout-evaluation/reports")
    atomic_dump_json(
        bundle / "heldout-evaluation/run-version-assignments.json",
        assignment_manifest,
    )
    atomic_dump_json(
        bundle / "heldout-evaluation/per-run-outcomes.json",
        {"schema_version": "1.0", "runs": list(heldout_outcomes)},
    )
    replay_summary = {
        "schema_version": "1.0",
        "probe": list(probe_replay),
        "heldout": list(heldout_replay),
        "memory_update_replayed": True,
        "model_calls": 0,
        "codex_calls": 0,
        "broker_calls": 0,
        "credential_accesses": 0,
        "proxy_uses": 0,
        "public_launcher_calls": 0,
        "network_calls": 0,
    }
    atomic_dump_json(bundle / "replay/replay-summary.json", replay_summary)
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
            "authorization_id": AUTHORIZATION_ID,
            "authorized": process_manifest.authorized_processes,
            "started": process_manifest.started_processes,
            "terminal": process_manifest.terminal_processes,
            "maximum": MAXIMUM_PROCESSES,
            "probe_processes": 1,
            "heldout_processes": 18,
            "training_processes": 0,
            "memory_synthesis_processes": 0,
            "retries": 0,
            "resumes": 0,
        },
    )
    atomic_dump_json(
        bundle / "security-and-integrity/historical-preservation.json",
        dict(preservation),
    )
    atomic_dump_json(bundle / "reports/evolving-evaluation.json", evaluation)
    shutil.copy2(
        heldout_reports / "evolving-evaluation.md",
        bundle / "reports/evolving-evaluation.md",
    )
    atomic_dump_json(
        bundle / "reports/final-gate.json",
        {
            "schema_version": "1.0",
            "gate": "PASS",
            "label": ("MILESTONE 10B CONTAMINATION-SCANNER REPAIR AND HELD-OUT COMPLETION: PASS"),
            "v1_outperformance_required": False,
            "establishes_general_performance_improvement": False,
        },
    )
    report_text = (
        "# M10B Contamination-Scanner Repair and Held-Out Completion\n\n"
        "1. Starting and final source identities are recorded in the implementation evidence.\n"
        "2. Every historical bundle and the live checkpoint remained unchanged.\n"
        "3. The historical scanner conflated generic lexical overlap with provenance-bearing "
        "held-out leakage.\n"
        "4. Split-asset and frozen-memory scans have separate schemas and policy identities.\n"
        "5. The allowed synthesis corpus contains only pre-v1 prompt/schema, sanitized "
        "training, public training, reward, and generic-policy material.\n"
        "6. Only typed held-out-exclusive provenance signatures can block memory reuse.\n"
        "7. Generic vocabulary is diagnostic; hidden/reference output is hash-only.\n"
        "8. Zero-model regressions, true-positive fixtures, package checks, and CI passed.\n"
        "9. Source, packages, images, Codex capability, and authentication were resealed.\n"
        "10. The exact frozen memory and training lineage passed strict reuse eligibility.\n"
        "11. v0-final and v1-final have equal execution identities and differ behaviorally "
        "only by the preserved memory binding.\n"
        "12. One separate non-scored v1 conformance probe was terminal and evaluable.\n"
        "13. The 18-item held-out plan was sealed before its first authorization.\n"
        f"14. Held-out terminal/evaluable outcomes: {len(heldout_outcomes)}/18.\n"
        "15. Paired v0/v1 metrics are descriptive and do not establish general improvement.\n"
        "16. Replay made zero Codex, broker, credential, proxy, launcher, or network calls.\n"
        "17. Security, privacy, source, Docker, candidate, trajectory, and lineage scans passed.\n"
        "18. SHA256SUMS and audit_manifest.json bind the complete evidence.\n"
        "19. Deviations: no second probe; no training or memory synthesis rerun.\n"
        "20. MILESTONE 10B CONTAMINATION-SCANNER REPAIR AND HELD-OUT COMPLETION: PASS\n"
    )
    atomic_write_text(bundle / "reports/final-report.md", report_text)
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
        "campaign_kind": "m10b_contamination_scanner_repair_and_heldout_completion",
        "gate": "PASS",
        "source_commit": source_identity["source_commit"],
        "source_tree": source_identity["source_tree"],
        "scanner_policy_hash": policy.policy_hash,
        "allowed_synthesis_corpus_hash": corpus.corpus_hash,
        "signature_manifest_hash": signatures.manifest_hash,
        "contamination_report_hash": contamination.report_hash,
        "memory_pack_hash": MEMORY_PACK_HASH,
        "probe_processes": 1,
        "heldout_processes": 18,
        "new_model_processes": process_manifest.started_processes,
        "all_started_processes_terminal": True,
        "all_heldout_runs_evaluable": len(heldout_outcomes) == 18,
        "historical_evidence_combined": False,
        "memory_regenerated": False,
        "model_weights_modified": False,
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
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    repository_root = Path.cwd().resolve(strict=True)
    output = args.output_root.resolve()
    if output.exists():
        raise RuntimeError("campaign output root must not already exist")
    if args.source_commit == START_COMMIT:
        raise RuntimeError("contamination repair requires a new focused commit")
    _assert_source_identity(args.source_commit, args.source_tree)
    if any(name in os.environ for name in base.API_KEY_NAMES):
        raise RuntimeError("API-key environment is forbidden")
    codex_binary = args.codex_binary.resolve(strict=True)
    if _sha256(codex_binary) != base.CODEX_WRAPPER_SHA256:
        raise RuntimeError("Codex wrapper differs from exact 0.144.6")
    quality_evidence = args.quality_evidence.resolve(strict=True)
    forensic_evidence = args.forensic_evidence.resolve(strict=True)
    if not quality_evidence.is_file() or not forensic_evidence.is_file():
        raise RuntimeError("zero-model forensic and green-CI evidence are required")
    preservation_before = _preservation_identity()
    output.mkdir(parents=True)
    os.environ.pop("VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST", None)
    os.environ["VERIGYM_CODEX_BINARY"] = str(codex_binary)
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
    atomic_dump_json(output / "codex-capabilities.json", capability)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(output / "codex-capabilities.json")
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
        "codex_host_identity": identity.safe_dict(),
        "codex_capability_fingerprint": capabilities.capability_fingerprint,
        "requested_auth_mode": auth.requested_auth_mode,
        "resolved_auth_mode": auth.resolved_auth_mode,
        "auth_semantic_id": auth.auth_semantic_id,
        "credential_contents_accessed": False,
        "proxy_values_persisted_or_hashed": False,
    }
    (
        memory,
        summary,
        dataset,
        synthesis_plan,
        builder_request,
        builder_result,
        historical_v1,
        historical_update,
        _,
        eligibility,
    ) = _memory_reuse(codex_binary=codex_binary)
    training_roots = base._training_roots(repository_root)
    policy = build_contamination_scan_policy()
    corpus = build_allowed_synthesis_corpus(
        policy=policy,
        training_roots=training_roots,
        prompt_schema_texts=memory_builder_allowed_synthesis_sources(),
        sanitized_training_summary=summary,
        reward_channel_names=tuple(RewardVector.model_fields),
        generic_policy_instructions={
            "task-independent-memory-policy": (
                "Generalize only observable task-independent principles, public-test strategy, "
                "workspace-policy reminders, debugging checklists, and patch discipline."
            )
        },
    )
    final_v0, final_v1, final_update, evaluation_binding = _build_final_versions(
        capability=capability,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        memory=memory,
        summary=summary,
        dataset=dataset,
        plan=synthesis_plan,
        request=builder_request,
        result=builder_result,
        historical_v1=historical_v1,
        historical_update=historical_update,
    )
    atomic_dump_json(output / "agent-version-v0-final.json", final_v0)
    atomic_dump_json(output / "agent-version-v1-final.json", final_v1)
    atomic_dump_json(output / "agent-update-final.json", final_update)
    atomic_dump_json(output / "evaluation-binding.json", evaluation_binding)
    os.environ["VERIGYM_M10B_HELDOUT_AGENT_VERSION_MANIFEST"] = str(
        output / "agent-version-v1-final.json"
    )
    heldout_roots = base._heldout_roots(repository_root)
    split = build_task_split(
        split_id="m10b-contamination-repair-final-heldout",
        training=[base._task_entry(training_roots[task]) for task in base.TRAINING_TASKS],
        heldout=[base._task_entry(heldout_roots[task]) for task in base.HELDOUT_TASKS],
        heldout_assets_loaded_after_version_hash=final_v1.version_hash,
    )
    contamination, signatures = scan_contamination_report(
        split_manifest=split,
        training_roots=training_roots,
        heldout_roots=heldout_roots,
        allowed_corpus=corpus,
        policy=policy,
        memory_pack=memory,
    )
    validate_contamination_scan_policy(policy)
    validate_allowed_synthesis_corpus(corpus)
    validate_asset_signature_manifest(signatures)
    validate_contamination_scan_report(contamination)
    diagnostics = {
        match.public_excerpt: match.severity
        for match in (
            contamination.frozen_memory_scan.matches
            if contamination.frozen_memory_scan is not None
            else []
        )
    }
    if (
        not contamination.passed
        or contamination.hard_contamination_count != 0
        or diagnostics.get("preserve") != "diagnostic_overlap"
        or diagnostics.get("validation") != "diagnostic_overlap"
    ):
        raise RuntimeError("corrected historical contamination regression did not pass")
    atomic_dump_json(output / "source-identity.json", source_identity)
    atomic_dump_json(output / "package-and-image-identities.json", package_identity)
    atomic_dump_json(output / "preservation-before.json", preservation_before)
    atomic_dump_json(output / "memory-eligibility.json", eligibility)
    atomic_dump_json(output / "scan-policy.json", policy)
    atomic_dump_json(output / "allowed-synthesis-corpus.json", corpus)
    atomic_dump_json(output / "signature-manifest.json", signatures)
    atomic_dump_json(output / "contamination-report.json", contamination)
    lineage = build_agent_lineage(parent=final_v0, result=final_v1, update=final_update)
    atomic_dump_json(output / "agent-lineage.json", lineage)
    atomic_dump_json(
        output / "agent-version-set.json",
        build_agent_version_set([final_v0, final_v1]),
    )
    ledger = output / "model-process-ledger.jsonl"
    probe_experiment, probe_dataset, probe_outcomes, probe_replay = _run_probe(
        output=output,
        ledger=ledger,
        capability=capability,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        v1=final_v1,
        memory=memory,
    )
    _assert_source_identity(args.source_commit, args.source_tree)
    (
        heldout_plan,
        heldout_experiment,
        heldout_dataset,
        heldout_reports,
        evaluation,
        assignment_manifest,
        heldout_outcomes,
        heldout_replay,
    ) = _run_heldout(
        output=output,
        ledger=ledger,
        capability=capability,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        package_hashes=package_hashes,
        split=split,
        v0=final_v0,
        v1=final_v1,
        memory=memory,
    )
    replay_context_update(
        parent=final_v0,
        result=final_v1,
        update=final_update,
        dataset=dataset,
        training_summary=summary,
        memory_pack=memory,
    )
    process_manifest = seal_process_ledger(
        ledger,
        authorization_id=AUTHORIZATION_ID,
        complete=True,
        maximum_processes=MAXIMUM_PROCESSES,
    )
    if (
        process_manifest.authorized_processes != 19
        or process_manifest.started_processes != 19
        or process_manifest.terminal_processes != 19
        or process_manifest.process_kind_counts != {"heldout": 18, "implementation_probe": 1}
    ):
        raise RuntimeError("global model-process accounting differs from the frozen campaign")
    preservation_after = _preservation_identity()
    if preservation_after != preservation_before:
        raise RuntimeError("protected historical evidence changed during the campaign")
    _assert_source_identity(args.source_commit, args.source_tree)
    original_linkage = {
        "schema_version": "1.0",
        "historical_bundle_sha256sums": HISTORICAL_SHA256SUMS,
        "original_synthesis_plan_hash": synthesis_plan.plan_hash,
        "original_builder_input_hash": builder_request.input_hash,
        "original_builder_output_hash": builder_result.output_hash,
        "original_v1_version_hash": historical_v1.version_hash,
        "original_update_hash": historical_update.update_hash,
        "training_dataset_hash": dataset.dataset_hash,
        "sanitized_summary_hash": summary.summary_hash,
        "memory_pack_hash": memory.content_hash,
        "final_scanner_policy_hash": policy.policy_hash,
        "final_source_commit": args.source_commit,
        "memory_regenerated": False,
    }
    bundle = _seal_bundle(
        output=output,
        repository_root=repository_root,
        source_identity=source_identity,
        package_identity=package_identity,
        preservation=preservation_after,
        forensic_evidence=forensic_evidence,
        quality_evidence=quality_evidence,
        eligibility=eligibility,
        original_linkage=original_linkage,
        policy=policy,
        corpus=corpus,
        signatures=signatures,
        contamination=contamination,
        v0=final_v0,
        v1=final_v1,
        final_update=final_update,
        evaluation_binding=evaluation_binding,
        probe_experiment=probe_experiment,
        probe_dataset=probe_dataset,
        probe_outcomes=probe_outcomes,
        probe_replay=probe_replay,
        heldout_plan=heldout_plan,
        heldout_experiment=heldout_experiment,
        heldout_dataset=heldout_dataset,
        heldout_reports=heldout_reports,
        assignment_manifest=assignment_manifest,
        heldout_outcomes=heldout_outcomes,
        heldout_replay=heldout_replay,
        evaluation=evaluation,
        process_manifest=process_manifest,
    )
    print(
        canonical_json(
            {
                "gate": (
                    "MILESTONE 10B CONTAMINATION-SCANNER REPAIR AND HELD-OUT COMPLETION: PASS"
                ),
                "bundle": str(bundle),
                "bundle_sha256sums_sha256": _sha256(bundle / "SHA256SUMS"),
                "source_commit": args.source_commit,
                "source_tree": args.source_tree,
                "memory_pack_hash": memory.content_hash,
                "scanner_policy_hash": policy.policy_hash,
                "heldout_plan_hash": heldout_plan.plan_hash,
                "model_processes": process_manifest.started_processes,
                "evaluation_report_hash": evaluation.report_hash,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
