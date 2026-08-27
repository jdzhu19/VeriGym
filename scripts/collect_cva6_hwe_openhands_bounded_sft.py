#!/usr/bin/env python3
"""Collect the frozen 16/4 OpenHands HWE development-SFT pilot without retries."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from verigym_openhands.hwe_pilot import load_predecessor_qualification, seal_campaign_report
from verigym_openhands.hwe_sft_pilot import (
    OPENHANDS_BOUNDED_SFT_AGENT_VERSION_ID,
    OPENHANDS_BOUNDED_SFT_API_KEY_ENV,
    OPENHANDS_BOUNDED_SFT_BASE_URL_ENV,
    OPENHANDS_BOUNDED_SFT_OPT_IN_ENV,
    OPENHANDS_BOUNDED_SFT_PILOT_BASELINE_COMMIT,
    OPENHANDS_BOUNDED_SFT_PILOT_FORMAT,
    OPENHANDS_BOUNDED_SFT_TRAINING_TASKS,
    OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS,
    build_bounded_sft_agent_version,
    evaluate_bounded_sft_data_gate,
    load_bounded_sft_pilot_contract,
    validate_bounded_sft_source,
)
from verigym_openhands.trajectory import (
    OpenHandsTrajectoryError,
    materialize_openhands_decisions,
    validate_openhands_training_trajectory,
    write_openhands_decision_dataset,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.evolution.splits import validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.qwen_action_tokenizer import (
    QwenDecisionExampleTokenizer,
    dry_run_decision_record_v4,
)
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitEntry, TaskSplitManifest
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_legacy = importlib.import_module(
    "scripts.collect_cva6_hwe_openhands_pilot"
    if __package__
    else "collect_cva6_hwe_openhands_pilot"
)
_base_model_lock = _collection._base_model_lock
_docker_config = _collection._docker_config
_image_locks = _collection._image_locks
_infrastructure_invalid = _collection._infrastructure_invalid
_json = _collection._json
_load_tokenizer = _collection._load_tokenizer
_assert_provider_secret_absent = _legacy._assert_provider_secret_absent
_clean_source_commit = _legacy._clean_source_commit
_new_output = _legacy._new_output
_nonpositive_outcome = _legacy._nonpositive_outcome

_REPORT_FORMAT = "verigym_openhands_hwe_bounded_sft_collection_report_v1"
_DRY_RUN_FORMAT = "verigym_openhands_hwe_bounded_sft_loader_dry_run_v1"
_MODEL = "openai/deepseek-v4-flash"
_MODEL_IDENTITY = "deepseek-v4-flash"
_SDK_VERSION = "1.42.1"
_LITELLM_VERSION = "1.93.0"
_TIKTOKEN_VERSION = "0.7.0"
_MAX_CONTEXT_TOKENS = 65_536
_MAX_OUTPUT_TOKENS = 2_048
_MAX_ITERATIONS = 200


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--training-image-lock-dir", type=Path, required=True)
    parser.add_argument("--validation-image-lock-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--predecessor-root", type=Path, required=True)
    parser.add_argument("--predecessor-dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    return parser


def collect(
    *,
    contract_path: Path,
    qualification_root: Path,
    training_image_lock_dir: Path,
    validation_image_lock_dir: Path,
    tokenizer_root: Path,
    base_model_lock: Path,
    predecessor_root: Path,
    predecessor_dataset: Path,
    output: Path,
    campaign_id: str,
) -> dict[str, Any]:
    """Execute exactly the preregistered provider episodes and seal admitted datasets."""

    _require_runtime_opt_in(campaign_id)
    source_commit = _clean_source_commit()
    _require_baseline_ancestor(source_commit)
    contract = load_bounded_sft_pilot_contract(contract_path.resolve(strict=True))
    qualification = qualification_root.resolve(strict=True)
    tokenizer_directory = tokenizer_root.resolve(strict=True)
    split = validate_task_split(
        TaskSplitManifest.model_validate(_json(qualification / "task-split.json"))
    )
    try:
        validate_bounded_sft_source(
            contract,
            split=split,
            task_split_path=qualification / "task-split.json",
            qualification_progress_path=qualification / "qualification-progress.json",
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    qualification_progress = _json(qualification / "qualification-progress.json")
    source_by_task = _qualified_sources(qualification_progress)
    entries = {entry.task_id: entry for entry in (*split.training, *split.validation)}
    locks = {
        **_image_locks(training_image_lock_dir, set(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS)),
        **_image_locks(validation_image_lock_dir, set(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)),
    }
    for task_id, entry in entries.items():
        lock = locks[task_id]
        if lock.task_hash != entry.task_hash or lock.source_hash != entry.source_hash:
            raise ConfigurationError(f"bounded SFT image lock differs for {task_id}")

    model_lock = _base_model_lock(base_model_lock, tokenizer_directory)
    student = contract["student"]
    if (
        model_lock["snapshot_hash"] != student["base_model_snapshot_hash"]
        or model_lock["tokenizer_hash"] != student["tokenizer_hash"]
    ):
        raise ConfigurationError("bounded SFT base model or tokenizer lock changed")
    tokenizer, transformers_version = _load_tokenizer(tokenizer_directory)
    exact_tokenizer = QwenDecisionExampleTokenizer(
        tokenizer,
        tokenizer_root=tokenizer_directory,
    )
    if exact_tokenizer.tokenizer_hash != model_lock["tokenizer_hash"]:
        raise ConfigurationError("bounded SFT exact tokenizer differs from the model lock")

    predecessor_directory = predecessor_dataset.resolve(strict=True)
    predecessor_manifest = _predecessor_dataset_manifest(predecessor_directory, contract)
    predecessor_records = _predecessor_dataset_records(
        predecessor_directory,
        predecessor_manifest,
    )
    predecessor = load_predecessor_qualification(predecessor_root)
    predecessor_entry = entries[str(predecessor.report["task_id"])]
    if (
        predecessor.report.get("task_hash") != predecessor_entry.task_hash
        or predecessor.report.get("source_hash") != predecessor_entry.source_hash
    ):
        raise ConfigurationError("bounded SFT predecessor differs from the frozen split")
    agent_version = build_bounded_sft_agent_version(
        source_commit=source_commit,
        image_locks=locks,
    )
    _zero_call_preflight(locks)

    root = _new_output(output)
    runs = root / "runs"
    records_root = root / "trajectory-records"
    runs.mkdir(mode=0o700)
    records_root.mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", agent_version)
    image_receipt = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_bounded_sft_image_locks_v1",
        "locks": {
            task_id: {
                "lock_hash": lock.lock_hash,
                "derived_agent_image_id": lock.derived_agent_image_id,
                "verifier_base_image_id": lock.verifier_base_image_id,
            }
            for task_id, lock in sorted(locks.items())
        },
    }
    atomic_dump_json(
        root / "image-lock-receipt.json",
        {**image_receipt, "receipt_hash": content_hash(image_receipt)},
    )

    training_schedule = list(contract["collection"]["training_schedule"])
    validation_schedule = list(contract["collection"]["validation_schedule"])
    predecessor_episode = next(item for item in training_schedule if item.get("predecessor"))
    predecessor_dry_runs = [
        dry_run_decision_record_v4(record, tokenizer=exact_tokenizer)
        for record in predecessor_records
    ]
    predecessor_attempt = {
        "episode_id": predecessor_episode["episode_id"],
        "role": "training",
        "task_id": predecessor_entry.task_id,
        "sample_index": predecessor_episode["sample_index"],
        "seed": predecessor_episode["seed"],
        "run_id": predecessor.report["run_id"],
        "run_hash": content_hash(
            {
                "predecessor_report_hash": predecessor.report_hash,
                "trajectory_hash": predecessor.trajectory["transcript_hash"],
            }
        ),
        "status": "eligible_predecessor",
        "historical_predecessor": True,
        "source_commit": predecessor.report["source_commit"],
        "infrastructure_valid": True,
        "ordinary_verifier_resolved": True,
        "exact_64k_eligible": True,
        "truncation_applied": False,
        "transcript_hash": predecessor.trajectory["transcript_hash"],
        "decision_record_count": len(predecessor_records),
        "max_decision_record_tokens": max(
            int(record["token_count"]) for record in predecessor_records
        ),
        "model_call_count": predecessor.report["agent_model_calls"],
        "whole_episode_retries": 0,
    }
    _write_trajectory_records(
        records_root / f"{predecessor_episode['episode_id']}.jsonl",
        predecessor_records,
        episode_id=str(predecessor_episode["episode_id"]),
        role="training",
        task_id=predecessor_entry.task_id,
        transcript_hash=str(predecessor.trajectory["transcript_hash"]),
        run_hash=str(predecessor_attempt["run_hash"]),
    )
    attempts: list[dict[str, Any]] = [predecessor_attempt]
    records_by_role: dict[str, list[dict[str, Any]]] = {
        "training": list(predecessor_records),
        "validation": [],
    }
    dry_runs_by_role: dict[str, list[dict[str, Any]]] = {
        "training": predecessor_dry_runs,
        "validation": [],
    }
    base_report = {
        "schema_version": "1.0",
        "format_id": _REPORT_FORMAT,
        "pilot_format": OPENHANDS_BOUNDED_SFT_PILOT_FORMAT,
        "contract_hash": contract["contract_hash"],
        "campaign_id": campaign_id,
        "status": "collection_running",
        "source_commit": source_commit,
        "source_baseline_commit": OPENHANDS_BOUNDED_SFT_PILOT_BASELINE_COMMIT,
        "task_split_hash": split.manifest_hash,
        "training_schedule": training_schedule,
        "validation_schedule": validation_schedule,
        "heldout_task_ids": contract["collection"]["heldout_task_ids"],
        "heldout_episodes_collected": 0,
        "predecessor_report_hash": predecessor.report_hash,
        "predecessor_dataset_hash": predecessor_manifest["dataset_hash"],
        "predecessor_reused": True,
        "predecessor_resampled": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "best_of_k": False,
        "model_substitution": False,
        "model_transport_id": _MODEL,
        "model_identity": _MODEL_IDENTITY,
        "openhands_sdk_version": _SDK_VERSION,
        "litellm_version": _LITELLM_VERSION,
        "tiktoken_version": _TIKTOKEN_VERSION,
        "agent_version_id": OPENHANDS_BOUNDED_SFT_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "temperature": 0,
        "top_p": 1,
        "thinking": "disabled",
        "max_context_tokens": _MAX_CONTEXT_TOKENS,
        "max_output_tokens": _MAX_OUTPUT_TOKENS,
        "max_iterations": _MAX_ITERATIONS,
        "tool_contract": "hwe_native_shell_v2",
        "tool_schema_count": 6,
        "capture_training_transcript": True,
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "chat_template_hash": exact_tokenizer.chat_template_hash,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "transformers_version": transformers_version,
        "attempts": attempts,
        "benchmark_score_claimed": False,
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "hpc_jobs_submitted": False,
        "new_hpc_jobs_submitted": False,
        "gpu_seconds": 0,
    }
    atomic_dump_json(root / "preregistration.json", seal_campaign_report(base_report))
    atomic_dump_json(root / "campaign-progress.json", seal_campaign_report(base_report))

    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "openhands-hwe-agent" not in registries.agents.names():
        from verigym_openhands.hwe_agent import OpenHandsHweAgentAdapter

        registries.agents.register(OpenHandsHweAgentAdapter())
    service = VeriGym(registries)
    manifest_json = json.dumps(
        agent_version.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )

    scheduled = [
        *(dict(item, role="training") for item in training_schedule if not item.get("predecessor")),
        *(dict(item, role="validation") for item in validation_schedule),
    ]
    for episode in scheduled:
        attempt, records, dry_runs = _run_episode(
            service=service,
            episode=episode,
            campaign_id=campaign_id,
            qualification=qualification,
            source_by_task=source_by_task,
            entry=entries[str(episode["task_id"])],
            lock=locks[str(episode["task_id"])],
            runs=runs,
            records_root=records_root,
            exact_tokenizer=exact_tokenizer,
            agent_version_manifest_json=manifest_json,
            agent_version_hash=agent_version.version_hash,
            source_commit=source_commit,
            root=root,
            base_report=base_report,
            attempts=attempts,
        )
        attempts.append(attempt)
        role = str(episode["role"])
        records_by_role[role].extend(records)
        dry_runs_by_role[role].extend(dry_runs)
        progress = {**base_report, "attempts": attempts, "status": "collection_running"}
        atomic_dump_json(root / "campaign-progress.json", seal_campaign_report(progress))

    training_manifest, training_security = _write_dataset(
        records=records_by_role["training"],
        dry_runs=dry_runs_by_role["training"],
        tokenizer=exact_tokenizer,
        output=root / "training-dataset",
        role="training",
        qualification=qualification,
        tokenizer_directory=tokenizer_directory,
    )
    validation_manifest: dict[str, Any] | None = None
    validation_security: Any | None = None
    if records_by_role["validation"]:
        validation_manifest, validation_security = _write_dataset(
            records=records_by_role["validation"],
            dry_runs=dry_runs_by_role["validation"],
            tokenizer=exact_tokenizer,
            output=root / "validation-dataset",
            role="validation",
            qualification=qualification,
            tokenizer_directory=tokenizer_directory,
        )
    _assert_provider_secret_absent(root)
    ordered_attempts = _ordered_attempts(attempts, training_schedule, validation_schedule)
    gate = evaluate_bounded_sft_data_gate(ordered_attempts)
    gate_payload = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_bounded_sft_data_gate_v1",
        **asdict(gate),
        "target_training_trajectories": 16,
        "scheduled_training_episodes": 16,
        "scheduled_validation_episodes": 4,
        "heldout_episodes_collected": 0,
    }
    atomic_dump_json(
        root / "data-gate.json",
        {**gate_payload, "gate_hash": content_hash(gate_payload)},
    )
    final = {
        **base_report,
        "status": (
            "collection_completed_data_gate_passed"
            if gate.satisfied
            else "collection_completed_data_gate_not_met"
        ),
        "attempts": ordered_attempts,
        "attempt_count": len(ordered_attempts),
        "new_provider_episode_count": len(ordered_attempts) - 1,
        "infrastructure_valid_attempt_count": sum(
            bool(item["infrastructure_valid"]) for item in ordered_attempts
        ),
        "training_verifier_pass_count": gate.eligible_training_trajectories,
        "training_distinct_task_count": gate.distinct_training_tasks,
        "validation_verifier_pass_count": gate.eligible_validation_trajectories,
        "validation_distinct_task_count": gate.distinct_validation_tasks,
        "training_dataset_hash": training_manifest["dataset_hash"],
        "training_decision_record_count": training_manifest["record_count"],
        "training_max_decision_record_tokens": training_manifest["max_observed_token_count"],
        "validation_dataset_hash": (
            validation_manifest["dataset_hash"] if validation_manifest else None
        ),
        "validation_decision_record_count": (
            validation_manifest["record_count"] if validation_manifest else 0
        ),
        "validation_max_decision_record_tokens": (
            validation_manifest["max_observed_token_count"] if validation_manifest else None
        ),
        "training_dataset_security_scan": training_security.gate,
        "validation_dataset_security_scan": (
            validation_security.gate if validation_security is not None else None
        ),
        "loader_ready": validation_manifest is not None,
        "collector_ready": True,
        "data_gate_satisfied": gate.satisfied,
        "data_gate_failure_reason": gate.reason,
        "gpu_submission_allowed": gate.satisfied,
        "heldout_episodes_collected": 0,
        "benchmark_score_claimed": False,
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "hpc_jobs_submitted": False,
        "new_hpc_jobs_submitted": False,
        "gpu_seconds": 0,
    }
    sealed = seal_campaign_report(final)
    atomic_dump_json(root / "campaign-progress.json", sealed)
    atomic_dump_json(root / "campaign-report.json", sealed)
    return cast(dict[str, Any], sealed)


def _run_episode(
    *,
    service: VeriGym,
    episode: dict[str, Any],
    campaign_id: str,
    qualification: Path,
    source_by_task: dict[str, str],
    entry: TaskSplitEntry,
    lock: Any,
    runs: Path,
    records_root: Path,
    exact_tokenizer: QwenDecisionExampleTokenizer,
    agent_version_manifest_json: str,
    agent_version_hash: str,
    source_commit: str,
    root: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    task_id = str(episode["task_id"])
    role = str(episode["role"])
    episode_id = str(episode["episode_id"])
    seed = int(episode["seed"])
    sample_index = int(episode["sample_index"])
    source_root = (qualification / source_by_task[task_id]).resolve(strict=True)
    if not source_root.is_relative_to(qualification):
        raise ConfigurationError("bounded SFT source escaped qualification root")
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(task_id, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != entry.task_hash
        or task.source.content_hash != entry.source_hash
    ):
        raise ConfigurationError("bounded SFT qualified task source changed before execution")
    run_id = f"{campaign_id}-{episode_id}"
    config = RunConfig(
        task_id=task_id,
        suite_source=source,
        expected_suite_source_snapshot=snapshot,
        expected_task_hash=entry.task_hash,
        expected_source_hash=entry.source_hash,
        mode=InteractionMode.AGENT,
        agent="openhands-hwe-agent",
        agent_options={
            "model_id": _MODEL,
            "base_url_env": OPENHANDS_BOUNDED_SFT_BASE_URL_ENV,
            "api_key_env": OPENHANDS_BOUNDED_SFT_API_KEY_ENV,
            "max_iterations": _MAX_ITERATIONS,
            "max_process_time_s": 3_600,
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "max_context_tokens": _MAX_CONTEXT_TOKENS,
            "seed": seed,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "expected_sdk_version": _SDK_VERSION,
            "campaign_role": "training",
            "capture_training_transcript": True,
            "agent_version_id": OPENHANDS_BOUNDED_SFT_AGENT_VERSION_ID,
            "agent_version_hash": agent_version_hash,
            "agent_version_manifest_json": agent_version_manifest_json,
            "collection_profile_id": "hwe_production_native_shell_v2",
        },
        runtime="docker",
        docker_config=_docker_config(lock),
        seed=seed,
        sample_index=sample_index,
        output=runs,
        run_id=run_id,
        experiment_id=campaign_id,
        plan_item_id=episode_id,
        system_id="openhands-deepseek-v4-flash-hwe-bounded-sft-pilot-v1",
        base_seed=seed,
    )
    try:
        result = service.run(config)
    except Exception as exc:
        attempt = _infrastructure_attempt(
            episode,
            run_id,
            type(exc).__name__,
            source_commit=source_commit,
        )
        _stop(root, base_report, [*attempts, attempt], "run_boundary_exception")
        raise ConfigurationError(
            f"bounded SFT collection stopped on infrastructure-invalid {episode_id}"
        ) from exc
    scorecard = result.scorecard
    run_hash = content_hash({"run_id": run_id, "scorecard": scorecard.model_dump(mode="json")})
    if _infrastructure_invalid(scorecard):
        failure = scorecard.failure
        reason = (
            failure.protocol_error_subcategory or failure.category
            if failure is not None
            else "scorecard_infrastructure_invalid"
        )
        attempt = _infrastructure_attempt(
            episode,
            run_id,
            str(reason),
            source_commit=source_commit,
            run_hash=run_hash,
        )
        _stop(root, base_report, [*attempts, attempt], str(reason))
        raise ConfigurationError(
            f"bounded SFT collection stopped on infrastructure-invalid {episode_id}"
        )

    run_directory = Path(result.run_dir).resolve(strict=True)
    trajectory_path = run_directory / "artifacts" / "openhands_sdk" / "training-trajectory.json"
    trajectory: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    status, rejection_reason = _nonpositive_outcome(scorecard)
    if scorecard.resolved:
        if trajectory_path.is_symlink() or not trajectory_path.is_file():
            attempt = _infrastructure_attempt(
                episode,
                run_id,
                "resolved_run_lacks_openhands_training_trajectory",
                source_commit=source_commit,
                run_hash=run_hash,
            )
            _stop(root, base_report, [*attempts, attempt], "resolved_trajectory_missing")
            raise ConfigurationError(f"bounded SFT resolved trajectory missing for {episode_id}")
        trajectory = validate_openhands_training_trajectory(_json(trajectory_path))
        if trajectory.get("task_id") != task_id:
            raise ConfigurationError("bounded SFT trajectory task identity changed")
        reproducibility = scorecard.reproducibility
        try:
            records = materialize_openhands_decisions(
                trajectory,
                binding={
                    "sample_id": content_hash(
                        {
                            "contract_hash": base_report["contract_hash"],
                            "episode_id": episode_id,
                            "run_hash": run_hash,
                        }
                    ),
                    "task_hash": entry.task_hash,
                    "source_hash": entry.source_hash,
                    "candidate_hash": reproducibility.candidate_hash,
                    "verifier_hash": reproducibility.verifier_hash,
                },
                tokenizer=exact_tokenizer,
            )
            dry_runs = [
                dry_run_decision_record_v4(record, tokenizer=exact_tokenizer) for record in records
            ]
        except OpenHandsTrajectoryError as exc:
            attempt = {
                **_infrastructure_attempt(
                    episode,
                    run_id,
                    "exact_64k_materialization_failed",
                    source_commit=source_commit,
                    run_hash=run_hash,
                ),
                "status": "overlength_or_receipt_invalid",
                "infrastructure_valid": True,
                "ordinary_verifier_resolved": True,
                "transcript_hash": trajectory.get("transcript_hash"),
            }
            _stop(root, base_report, [*attempts, attempt], type(exc).__name__)
            raise ConfigurationError(
                f"bounded SFT exact 64K materialization failed for {episode_id}"
            ) from exc
        if any(bool(receipt["overlength"]) for receipt in dry_runs):
            raise ConfigurationError("bounded SFT exact dry run unexpectedly observed overlength")
        status = "eligible"
        rejection_reason = None
        _write_trajectory_records(
            records_root / f"{episode_id}.jsonl",
            records,
            episode_id=episode_id,
            role=role,
            task_id=task_id,
            transcript_hash=str(trajectory["transcript_hash"]),
            run_hash=run_hash,
        )
    elif trajectory_path.exists():
        attempt = _infrastructure_attempt(
            episode,
            run_id,
            "verifier_rejected_run_exported_positive_trajectory",
            source_commit=source_commit,
            run_hash=run_hash,
        )
        _stop(root, base_report, [*attempts, attempt], "positive_export_without_verifier_pass")
        raise ConfigurationError("bounded SFT ineligible trajectory was exported")

    accounting_path = run_directory / "artifacts" / "openhands_sdk" / "accounting.json"
    accounting_available = accounting_path.is_file() and not accounting_path.is_symlink()
    if accounting_available:
        accounting = _json(accounting_path)
    elif (
        scorecard.failure is not None
        and scorecard.failure.infrastructure is False
        and scorecard.failure.kind == "model"
    ):
        accounting = {}
    else:
        attempt = _infrastructure_attempt(
            episode,
            run_id,
            "openhands_accounting_missing",
            source_commit=source_commit,
            run_hash=run_hash,
        )
        _stop(root, base_report, [*attempts, attempt], "openhands_accounting_missing")
        raise ConfigurationError(f"bounded SFT accounting missing for {episode_id}")
    attempt = {
        "episode_id": episode_id,
        "role": role,
        "task_id": task_id,
        "sample_index": sample_index,
        "seed": seed,
        "run_id": run_id,
        "run_hash": run_hash,
        "status": status,
        "historical_predecessor": False,
        "source_commit": source_commit,
        "infrastructure_valid": True,
        "ordinary_verifier_resolved": scorecard.resolved,
        "exact_64k_eligible": bool(records),
        "truncation_applied": False,
        "transcript_hash": trajectory.get("transcript_hash") if trajectory else None,
        "decision_record_count": len(records),
        "max_decision_record_tokens": (
            max(int(record["token_count"]) for record in records) if records else None
        ),
        "model_call_count": accounting.get("model_call_count"),
        "process_wall_time_s": accounting.get("process_wall_time_s"),
        "accounting_available": accounting_available,
        "rejection_reason": rejection_reason,
        "whole_episode_retries": 0,
    }
    return attempt, records, dry_runs


def _require_runtime_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPENHANDS_BOUNDED_SFT_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_BOUNDED_SFT_OPT_IN_ENV}=1 is required")
    if not os.environ.get(OPENHANDS_BOUNDED_SFT_API_KEY_ENV) or not os.environ.get(
        OPENHANDS_BOUNDED_SFT_BASE_URL_ENV
    ):
        raise ConfigurationError("bounded SFT provider environment is incomplete")
    if (
        not campaign_id
        or len(campaign_id) > 80
        or not all(
            character.islower() or character.isdigit() or character == "-"
            for character in campaign_id
        )
    ):
        raise ConfigurationError("bounded SFT campaign ID is not canonical")
    for package, expected in (
        ("openhands-sdk", _SDK_VERSION),
        ("litellm", _LITELLM_VERSION),
        ("tiktoken", _TIKTOKEN_VERSION),
    ):
        if importlib.metadata.version(package) != expected:
            raise ConfigurationError(f"bounded SFT {package} version changed")


def _require_baseline_ancestor(source_commit: str) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "merge-base",
            "--is-ancestor",
            OPENHANDS_BOUNDED_SFT_PILOT_BASELINE_COMMIT,
            source_commit,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise ConfigurationError("bounded SFT execution commit does not descend from baseline")


def _qualified_sources(progress: dict[str, Any]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for key, count in (("training_pool", 11), ("development_validation", 2)):
        pool = progress.get(key)
        if not isinstance(pool, list) or len(pool) != count:
            raise ConfigurationError(f"bounded SFT qualification {key} changed")
        for item in pool:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("task_id"), str)
                or not isinstance(item.get("source"), str)
            ):
                raise ConfigurationError(f"bounded SFT qualification {key} is malformed")
            sources[str(item["task_id"])] = str(item["source"])
    return sources


def _predecessor_dataset_manifest(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    directory = root.resolve(strict=True)
    if not directory.is_dir() or root.is_symlink():
        raise ConfigurationError("bounded SFT predecessor dataset is unsafe")
    manifest = _json(directory / "dataset-manifest.json")
    expected_hash = manifest.get("dataset_hash")
    base = {key: value for key, value in manifest.items() if key != "dataset_hash"}
    expected = contract["collection"]["predecessor"]
    records_path = directory / "train.jsonl"
    if (
        content_hash(base) != expected_hash
        or expected_hash != expected["dataset_hash"]
        or manifest.get("format_id") != expected["dataset_format"]
        or manifest.get("trajectory_hashes") != [expected["trajectory_hash"]]
        or manifest.get("record_count") != expected["record_count"]
        or manifest.get("max_observed_token_count") != expected["max_observed_token_count"]
        or manifest.get("records_sha256") != hash_bytes(records_path.read_bytes())
        or manifest.get("overlength_records") != []
    ):
        raise ConfigurationError("bounded SFT predecessor dataset changed")
    return cast(dict[str, Any], manifest)


def _predecessor_dataset_records(
    root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    path = root / "train.jsonl"
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError("bounded SFT predecessor records file is unsafe")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"bounded SFT predecessor row {line_number} is invalid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise ConfigurationError(f"bounded SFT predecessor row {line_number} is not an object")
        records.append(value)
    if (
        len(records) != manifest["record_count"]
        or [record.get("record_hash") for record in records] != manifest["record_hashes"]
        or {record.get("transcript_hash") for record in records}
        != set(manifest["trajectory_hashes"])
        or any(record.get("eligible") is not True for record in records)
    ):
        raise ConfigurationError("bounded SFT predecessor record bindings changed")
    return records


def _zero_call_preflight(locks: dict[str, Any]) -> None:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    _configured_control_root()
    _configured_mcp_pythonpath()
    for task_id in (
        *OPENHANDS_BOUNDED_SFT_TRAINING_TASKS,
        *OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS,
    ):
        runtime = DockerRuntime(_docker_config(locks[task_id]))
        try:
            runtime.prepare(f"openhands-bounded-sft-preflight-{task_id.rsplit('-', 1)[-1]}")
        finally:
            runtime.close()


def _write_dataset(
    *,
    records: list[dict[str, Any]],
    dry_runs: list[dict[str, Any]],
    tokenizer: QwenDecisionExampleTokenizer,
    output: Path,
    role: str,
    qualification: Path,
    tokenizer_directory: Path,
) -> tuple[dict[str, Any], Any]:
    manifest = write_openhands_decision_dataset(records, tokenizer=tokenizer, output=output)
    dry_run_base = {
        "schema_version": "1.0",
        "format_id": _DRY_RUN_FORMAT,
        "role": role,
        "dataset_hash": manifest["dataset_hash"],
        "record_count": len(dry_runs),
        "record_hashes": [receipt["record_hash"] for receipt in dry_runs],
        "max_token_count": max(int(receipt["token_count"]) for receipt in dry_runs),
        "overlength_record_count": sum(bool(receipt["overlength"]) for receipt in dry_runs),
        "complete_assistant_decision_only": True,
        "truncation_applied": False,
        "tokenizer_hash": tokenizer.tokenizer_hash,
        "chat_template_hash": tokenizer.chat_template_hash,
        "records": dry_runs,
    }
    atomic_dump_json(
        output / "loader-dry-run.json",
        {**dry_run_base, "dry_run_hash": content_hash(dry_run_base)},
    )
    security = require_security_scan_pass(
        scan_artifact_roots(
            [output],
            report_id=f"openhands-hwe-bounded-sft-{role}-dataset",
            forbidden_host_roots=(
                str(qualification),
                str(tokenizer_directory),
                str(Path.cwd().resolve()),
            ),
        )
    )
    atomic_dump_json(output.parent / f"{role}-dataset-security-scan.json", security)
    return manifest, security


def _ordered_attempts(
    attempts: list[dict[str, Any]],
    training_schedule: list[dict[str, Any]],
    validation_schedule: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_episode = {str(item["episode_id"]): item for item in attempts}
    schedule = [*training_schedule, *validation_schedule]
    expected = [str(item["episode_id"]) for item in schedule]
    if len(by_episode) != len(attempts) or set(by_episode) != set(expected):
        raise ConfigurationError("bounded SFT attempt schedule is incomplete or duplicated")
    return [by_episode[episode_id] for episode_id in expected]


def _infrastructure_attempt(
    episode: dict[str, Any],
    run_id: str,
    reason: str,
    *,
    source_commit: str,
    run_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "episode_id": episode["episode_id"],
        "role": episode["role"],
        "task_id": episode["task_id"],
        "sample_index": episode["sample_index"],
        "seed": episode["seed"],
        "run_id": run_id,
        "run_hash": run_hash or content_hash({"run_id": run_id, "reason": reason}),
        "status": "infrastructure_invalid",
        "historical_predecessor": False,
        "source_commit": source_commit,
        "infrastructure_valid": False,
        "ordinary_verifier_resolved": False,
        "exact_64k_eligible": False,
        "truncation_applied": False,
        "transcript_hash": None,
        "decision_record_count": 0,
        "max_decision_record_tokens": None,
        "model_call_count": None,
        "rejection_reason": reason,
        "whole_episode_retries": 0,
    }


def _write_trajectory_records(
    path: Path,
    records: list[dict[str, Any]],
    *,
    episode_id: str,
    role: str,
    task_id: str,
    transcript_hash: str,
    run_hash: str,
) -> None:
    _atomic_jsonl(path, records)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_bounded_sft_trajectory_records_v1",
        "episode_id": episode_id,
        "role": role,
        "task_id": task_id,
        "transcript_hash": transcript_hash,
        "run_hash": run_hash,
        "record_count": len(records),
        "record_hashes": [record["record_hash"] for record in records],
        "max_token_count": max(int(record["token_count"]) for record in records),
        "records_file": path.name,
        "records_sha256": hash_bytes(path.read_bytes()),
        "truncation_applied": False,
        "production_training_ready": False,
    }
    atomic_dump_json(
        path.with_suffix(".manifest.json"), {**base, "manifest_hash": content_hash(base)}
    )


def _atomic_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _stop(
    root: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
    reason: str,
) -> None:
    stopped = {
        **base_report,
        "status": "stopped_infrastructure_or_data_invalid",
        "attempts": attempts,
        "stop_reason": reason,
        "data_gate_satisfied": False,
        "gpu_submission_allowed": False,
    }
    sealed = seal_campaign_report(stopped)
    atomic_dump_json(root / "campaign-progress.json", sealed)
    atomic_dump_json(root / "campaign-report.json", sealed)


def main() -> int:
    arguments = _parser().parse_args()
    report = collect(
        contract_path=arguments.contract,
        qualification_root=arguments.qualification_root,
        training_image_lock_dir=arguments.training_image_lock_dir,
        validation_image_lock_dir=arguments.validation_image_lock_dir,
        tokenizer_root=arguments.tokenizer_root,
        base_model_lock=arguments.base_model_lock,
        predecessor_root=arguments.predecessor_root,
        predecessor_dataset=arguments.predecessor_dataset,
        output=arguments.output,
        campaign_id=arguments.campaign_id,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
