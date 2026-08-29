#!/usr/bin/env python3
"""Collect the frozen OpenHands v17 formal exact-64K development dataset."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_v17_canary_v4 import validate_v17_runtime_evidence
from verigym_openhands.hwe_v17_collection import (
    OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
    OPENHANDS_V17_COLLECTION_API_KEY_ENV,
    OPENHANDS_V17_COLLECTION_BASE_URL_ENV,
    OPENHANDS_V17_COLLECTION_CAMPAIGN_ID,
    OPENHANDS_V17_COLLECTION_GATE_FORMAT,
    OPENHANDS_V17_COLLECTION_LITELLM_VERSION,
    OPENHANDS_V17_COLLECTION_MODEL,
    OPENHANDS_V17_COLLECTION_MODEL_IDENTITY,
    OPENHANDS_V17_COLLECTION_OPT_IN_ENV,
    OPENHANDS_V17_COLLECTION_REPORT_FORMAT,
    OPENHANDS_V17_COLLECTION_SAMPLE_INDEX,
    OPENHANDS_V17_COLLECTION_SDK_VERSION,
    OPENHANDS_V17_COLLECTION_SEED,
    OPENHANDS_V17_COLLECTION_TIKTOKEN_VERSION,
    OPENHANDS_V17_COLLECTION_TOOL_CHOICE_POLICY,
    OPENHANDS_V17_FORMAL_TASKS,
    OPENHANDS_V17_FORMAL_TRAINING_ORDER,
    OPENHANDS_V17_FORMAL_VALIDATION_ORDER,
    OPENHANDS_V17_IDENTITY_TASKS,
    OPENHANDS_V17_IMPORTED_TRAINING_TASKS,
    build_v17_collection_agent_options,
    build_v17_collection_agent_version,
    evaluate_v17_collection_gate,
    load_v17_collection_contract,
    seal_v17_collection_report,
    validate_canary_import_root,
    validate_v17_collection_image_locks,
    validate_v17_collection_source,
)
from verigym_openhands.trajectory import (
    OpenHandsTrajectoryError,
    materialize_openhands_decisions,
    validate_openhands_training_trajectory,
    write_openhands_decision_dataset,
)

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
from verigym.schemas.evolution import TaskSplitManifest

_canary_runner = importlib.import_module(
    "scripts.collect_cva6_hwe_openhands_v17_canary_v3"
    if __package__
    else "collect_cva6_hwe_openhands_v17_canary_v3"
)
_legacy = importlib.import_module(
    "scripts.collect_cva6_hwe_openhands_pilot"
    if __package__
    else "collect_cva6_hwe_openhands_pilot"
)
_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)

_base_model_lock = _collection._base_model_lock
_docker_config = _collection._docker_config
_image_locks = _collection._image_locks
_json = _collection._json
_load_tokenizer = _collection._load_tokenizer
_clean_source_commit = _legacy._clean_source_commit
_new_output = _legacy._new_output
_run_validated_episode = _canary_runner._run_episode
_service = _canary_runner._service

_DRY_RUN_FORMAT = "verigym_openhands_hwe_v17_loader_dry_run_v1"
_SAMPLER_FORMAT = "verigym_openhands_hwe_v17_equal_trajectory_sampler_v1"
_RECORDS_FORMAT = "verigym_openhands_hwe_v17_trajectory_records_v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--training-image-lock-dir", type=Path, required=True)
    parser.add_argument("--validation-image-lock-dir", type=Path, required=True)
    parser.add_argument("--canary-root", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=OPENHANDS_V17_COLLECTION_CAMPAIGN_ID)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Import two sealed canary passes, then collect until the exact 8/2 gate."""

    _require_opt_in(arguments.campaign_id)
    source_commit = _clean_source_commit()
    contract = load_v17_collection_contract(arguments.contract.resolve(strict=True))
    qualification = arguments.qualification_root.resolve(strict=True)
    split = validate_task_split(
        TaskSplitManifest.model_validate(_json(qualification / "task-split.json"))
    )
    try:
        derived_split = validate_v17_collection_source(
            contract,
            split=split,
            task_split_path=qualification / "task-split.json",
            qualification_progress_path=qualification / "qualification-progress.json",
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    qualification_progress = _json(qualification / "qualification-progress.json")
    if qualification_progress.get("status") != "completed":
        raise ConfigurationError("OpenHands v17 formal qualification is incomplete")
    source_by_task = _qualified_sources(qualification_progress)
    entries = {
        entry.task_id: entry for entry in (*derived_split.training, *derived_split.validation)
    }
    locks = _load_locks(
        training_dir=arguments.training_image_lock_dir,
        validation_dir=arguments.validation_image_lock_dir,
    )
    try:
        validate_v17_collection_image_locks(contract, locks)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    tokenizer_directory = arguments.tokenizer_root.resolve(strict=True)
    model_lock = _base_model_lock(arguments.base_model_lock, tokenizer_directory)
    if (
        model_lock["snapshot_hash"] != contract["student"]["base_model_snapshot_hash"]
        or model_lock["tokenizer_hash"] != contract["student"]["tokenizer_hash"]
    ):
        raise ConfigurationError("OpenHands v17 formal model/tokenizer lock changed")
    tokenizer, transformers_version = _load_tokenizer(tokenizer_directory)
    exact_tokenizer = QwenDecisionExampleTokenizer(
        tokenizer,
        tokenizer_root=tokenizer_directory,
    )
    if exact_tokenizer.tokenizer_hash != model_lock["tokenizer_hash"]:
        raise ConfigurationError("OpenHands v17 formal exact tokenizer identity changed")
    try:
        imported_paths = validate_canary_import_root(arguments.canary_root, contract)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    agent_version = build_v17_collection_agent_version(
        source_commit=source_commit,
        image_locks=locks,
    )
    build_v17_collection_agent_options(
        seed=OPENHANDS_V17_COLLECTION_SEED,
        agent_version=agent_version,
    )
    root = _new_output(arguments.output)
    runs = root / "runs"
    scans = root / "security-scans"
    records_root = root / "trajectory-records"
    for directory in (runs, scans, records_root):
        directory.mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", agent_version)
    atomic_dump_json(root / "image-lock-receipt.json", _image_receipt(locks))

    attempts: list[dict[str, Any]] = []
    records_by_role: dict[str, list[dict[str, Any]]] = {"training": [], "validation": []}
    dry_runs_by_role: dict[str, list[dict[str, Any]]] = {"training": [], "validation": []}
    for task_id in OPENHANDS_V17_IMPORTED_TRAINING_TASKS:
        attempt, records, dry_runs = _import_canary_trajectory(
            task_id=task_id,
            path=imported_paths[task_id],
            contract=contract,
            tokenizer=exact_tokenizer,
        )
        attempts.append(attempt)
        records_by_role["training"].extend(records)
        dry_runs_by_role["training"].extend(dry_runs)
        _write_trajectory_records(
            records_root / f"{attempt['episode_id']}.jsonl",
            records,
            attempt=attempt,
        )

    base_report = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_COLLECTION_REPORT_FORMAT,
        "campaign_id": arguments.campaign_id,
        "status": "formal_collection_running",
        "contract_hash": contract["contract_hash"],
        "source_commit": source_commit,
        "source_task_split_hash": split.manifest_hash,
        "task_split_hash": derived_split.manifest_hash,
        "heldout_task_ids_loaded": [],
        "model_transport_id": OPENHANDS_V17_COLLECTION_MODEL,
        "model_identity": OPENHANDS_V17_COLLECTION_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "openhands_sdk_version": OPENHANDS_V17_COLLECTION_SDK_VERSION,
        "litellm_version": OPENHANDS_V17_COLLECTION_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_V17_COLLECTION_TIKTOKEN_VERSION,
        "transformers_version": transformers_version,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "chat_template_hash": exact_tokenizer.chat_template_hash,
        "seed": OPENHANDS_V17_COLLECTION_SEED,
        "sample_index": OPENHANDS_V17_COLLECTION_SAMPLE_INDEX,
        "temperature": 0,
        "top_p": 1,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "tool_schema_count": 6,
        "tool_choice_policy": OPENHANDS_V17_COLLECTION_TOOL_CHOICE_POLICY,
        "training_attempt_order": list(OPENHANDS_V17_FORMAL_TRAINING_ORDER),
        "validation_attempt_order": list(OPENHANDS_V17_FORMAL_VALIDATION_ORDER),
        "attempts": attempts,
        "benchmark_score_claimed": False,
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "hpc_jobs_submitted": False,
        "gpu_seconds": 0,
    }
    atomic_dump_json(root / "preregistration.json", seal_v17_collection_report(base_report))
    _write_progress(root, base_report, attempts)

    try:
        _zero_call_preflight(locks)
    except Exception as exc:
        _stop(root, base_report, attempts, f"zero_call_preflight:{type(exc).__name__}")
        raise ConfigurationError("OpenHands v17 formal Docker preflight failed") from exc

    service = _service()
    schedule = [
        *(_episode("training", task_id) for task_id in OPENHANDS_V17_FORMAL_TRAINING_ORDER),
        *(_episode("validation", task_id) for task_id in OPENHANDS_V17_FORMAL_VALIDATION_ORDER),
    ]
    for episode in schedule:
        gate = evaluate_v17_collection_gate(attempts)
        if gate.satisfied:
            break
        if not gate.possible:
            _stop(root, base_report, attempts, gate.reason)
            raise ConfigurationError(f"OpenHands v17 formal capacity failed: {gate.reason}")
        if gate.next_role != episode["role"]:
            continue
        failure_stage = "episode_execution"
        try:
            attempt = _run_validated_episode(
                service=service,
                episode=episode,
                qualification=qualification,
                source_relative=source_by_task[str(episode["task_id"])],
                entry=entries[str(episode["task_id"])],
                lock=locks[str(episode["task_id"])],
                runs=runs,
                scans=scans,
                root=root,
                campaign_id=arguments.campaign_id,
                source_commit=source_commit,
                agent_version=agent_version,
                agent_options_builder=build_v17_collection_agent_options,
                runtime_evidence_validator=validate_v17_runtime_evidence,
                system_id=OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
                security_report_prefix="openhands-hwe-v17-formal-v1",
            )
            attempt, records, dry_runs = _materialize_fresh_attempt(
                attempt=attempt,
                episode=episode,
                runs=runs,
                entry=entries[str(episode["task_id"])],
                contract=contract,
                tokenizer=exact_tokenizer,
            )
            failure_stage = "trajectory_record_persistence"
            if records:
                _write_trajectory_records(
                    records_root / f"{attempt['episode_id']}.jsonl",
                    records,
                    attempt=attempt,
                )
            prospective_attempts = [*attempts, attempt]
            failure_stage = "campaign_progress_persistence"
            _write_progress(root, base_report, prospective_attempts)
            failure_stage = "collection_gate_persistence"
            _write_gate(root, prospective_attempts)
        except Exception as exc:
            reason = f"{failure_stage}:{type(exc).__name__}"
            invalid = _invalid_attempt(episode, reason)
            _stop(root, base_report, [*attempts, invalid], reason)
            if isinstance(exc, ConfigurationError):
                raise
            raise ConfigurationError(
                f"OpenHands v17 formal stopped on {episode['episode_id']}"
            ) from exc
        attempts.append(attempt)
        role = str(episode["role"])
        records_by_role[role].extend(records)
        dry_runs_by_role[role].extend(dry_runs)

    gate = evaluate_v17_collection_gate(attempts)
    _write_gate(root, attempts)
    if not gate.satisfied:
        _stop(root, base_report, attempts, gate.reason)
        raise ConfigurationError(f"OpenHands v17 formal data gate not satisfied: {gate.reason}")

    training_manifest, training_security = _write_dataset(
        records=records_by_role["training"],
        dry_runs=dry_runs_by_role["training"],
        tokenizer=exact_tokenizer,
        output=root / "training-dataset",
        role="training",
        qualification=qualification,
        tokenizer_directory=tokenizer_directory,
    )
    validation_manifest, validation_security = _write_dataset(
        records=records_by_role["validation"],
        dry_runs=dry_runs_by_role["validation"],
        tokenizer=exact_tokenizer,
        output=root / "validation-dataset",
        role="validation",
        qualification=qualification,
        tokenizer_directory=tokenizer_directory,
    )
    provider_scan = _scan_provider_values(root)
    final: dict[str, Any] = seal_v17_collection_report(
        {
            **base_report,
            "status": "formal_collection_completed_data_gate_passed",
            "attempts": attempts,
            "attempt_count": len(attempts),
            "new_provider_episode_count": sum(
                item.get("imported_canary") is not True for item in attempts
            ),
            "training_distinct_task_count": gate.training_pass_count,
            "validation_distinct_task_count": gate.validation_pass_count,
            "training_dataset_hash": training_manifest["dataset_hash"],
            "validation_dataset_hash": validation_manifest["dataset_hash"],
            "training_decision_record_count": training_manifest["record_count"],
            "validation_decision_record_count": validation_manifest["record_count"],
            "training_max_decision_record_tokens": training_manifest["max_observed_token_count"],
            "validation_max_decision_record_tokens": validation_manifest[
                "max_observed_token_count"
            ],
            "training_dataset_security_scan": training_security.gate,
            "validation_dataset_security_scan": validation_security.gate,
            "provider_value_scan": provider_scan,
            "data_gate_satisfied": True,
            "gpu_submission_allowed": True,
        }
    )
    atomic_dump_json(root / "campaign-progress.json", final)
    atomic_dump_json(root / "campaign-report.json", final)
    return final


def _import_canary_trajectory(
    *,
    task_id: str,
    path: Path,
    contract: dict[str, Any],
    tokenizer: QwenDecisionExampleTokenizer,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    receipt = contract["canary_imports"][task_id]
    binding = contract["task_bindings"][task_id]
    trajectory = validate_openhands_training_trajectory(_json(path))
    if (
        trajectory["task_id"] != task_id
        or trajectory["transcript_hash"] != receipt["transcript_hash"]
        or trajectory["assistant_decision_count"] != receipt["assistant_decision_count"]
        or trajectory["verifier_resolved"] is not True
        or trajectory["sft_eligible"] is not True
    ):
        raise ConfigurationError("OpenHands v17 imported canary trajectory binding changed")
    records = materialize_openhands_decisions(
        trajectory,
        binding={
            "sample_id": content_hash(
                {
                    "formal_contract_hash": contract["contract_hash"],
                    "canary_run_hash": receipt["run_hash"],
                    "task_id": task_id,
                }
            ),
            "task_hash": binding["task_hash"],
            "source_hash": binding["source_hash"],
            "candidate_hash": receipt["candidate_hash"],
            "verifier_hash": receipt["verifier_hash"],
        },
        tokenizer=tokenizer,
    )
    dry_runs = [dry_run_decision_record_v4(record, tokenizer=tokenizer) for record in records]
    if not records or any(receipt["overlength"] for receipt in dry_runs):
        raise ConfigurationError("OpenHands v17 imported canary 64K receipt is invalid")
    return (
        {
            "episode_id": receipt["episode_id"],
            "role": "training",
            "task_id": task_id,
            "seed": 486,
            "sample_index": 2,
            "run_id": receipt["episode_id"],
            "run_hash": receipt["run_hash"],
            "status": "eligible_imported_canary",
            "imported_canary": True,
            "infrastructure_valid": True,
            "runtime_evidence_valid": True,
            "security_scan_passed": True,
            "ordinary_verifier_resolved": True,
            "fresh_exact_trajectory": True,
            "exact_64k_eligible": True,
            "truncation_applied": False,
            "transcript_hash": trajectory["transcript_hash"],
            "decision_record_count": len(records),
            "max_decision_record_tokens": max(int(record["token_count"]) for record in records),
            "whole_episode_retries": 0,
            "provider_request_retries": 0,
        },
        records,
        dry_runs,
    )


def _materialize_fresh_attempt(
    *,
    attempt: dict[str, Any],
    episode: dict[str, Any],
    runs: Path,
    entry: Any,
    contract: dict[str, Any],
    tokenizer: QwenDecisionExampleTokenizer,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if attempt["ordinary_verifier_resolved"] is not True:
        return (
            {
                **attempt,
                "imported_canary": False,
                "exact_64k_eligible": False,
                "decision_record_count": 0,
                "max_decision_record_tokens": None,
            },
            [],
            [],
        )
    episode_id = str(episode["episode_id"])
    evidence = runs / episode_id / "artifacts" / "openhands_sdk"
    trajectory = validate_openhands_training_trajectory(
        _json(evidence / "training-trajectory.json")
    )
    scorecard = _json(runs / episode_id / "scorecard.json")
    reproducibility = scorecard.get("reproducibility")
    if not isinstance(reproducibility, dict):
        raise ConfigurationError("OpenHands v17 formal scorecard binding is missing")
    try:
        records = materialize_openhands_decisions(
            trajectory,
            binding={
                "sample_id": content_hash(
                    {
                        "formal_contract_hash": contract["contract_hash"],
                        "episode_id": episode_id,
                        "run_hash": attempt["run_hash"],
                    }
                ),
                "task_hash": entry.task_hash,
                "source_hash": entry.source_hash,
                "candidate_hash": reproducibility["candidate_hash"],
                "verifier_hash": reproducibility["verifier_hash"],
            },
            tokenizer=tokenizer,
        )
    except (KeyError, OpenHandsTrajectoryError) as exc:
        raise ConfigurationError("OpenHands v17 formal exact 64K materialization failed") from exc
    dry_runs = [dry_run_decision_record_v4(record, tokenizer=tokenizer) for record in records]
    if not records or any(receipt["overlength"] for receipt in dry_runs):
        raise ConfigurationError("OpenHands v17 formal exact 64K dry run failed")
    return (
        {
            **attempt,
            "imported_canary": False,
            "exact_64k_eligible": True,
            "transcript_hash": trajectory["transcript_hash"],
            "decision_record_count": len(records),
            "max_decision_record_tokens": max(int(record["token_count"]) for record in records),
        },
        records,
        dry_runs,
    )


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
        "decision_only_loss_mask": True,
        "truncation_applied": False,
        "tokenizer_hash": tokenizer.tokenizer_hash,
        "chat_template_hash": tokenizer.chat_template_hash,
        "records": dry_runs,
    }
    atomic_dump_json(
        output / "loader-dry-run.json",
        {**dry_run_base, "dry_run_hash": content_hash(dry_run_base)},
    )
    _write_sampler_manifest(output, records, manifest)
    security = require_security_scan_pass(
        scan_artifact_roots(
            [output],
            report_id=f"openhands-hwe-v17-formal-{role}-dataset",
            forbidden_host_roots=(
                str(qualification),
                str(tokenizer_directory),
                str(Path.cwd().resolve()),
            ),
        )
    )
    atomic_dump_json(output.parent / f"{role}-dataset-security-scan.json", security)
    return manifest, security


def _write_sampler_manifest(
    output: Path, records: list[dict[str, Any]], dataset_manifest: dict[str, Any]
) -> None:
    try:
        module = importlib.import_module("verigym_training_reference.hwe_decision_sft_64k")
        schedule = module.trajectory_balanced_decision_indices(
            transcript_hashes=[str(record["transcript_hash"]) for record in records],
            decision_indices=[int(record["decision_index"]) for record in records],
            trajectory_decision_counts=[
                int(record["trajectory_assistant_decision_count"]) for record in records
            ],
        )
    except (ImportError, ValueError) as exc:
        raise ConfigurationError("OpenHands v17 equal-trajectory sampler failed") from exc
    transcript_counts: dict[str, int] = {}
    for index in schedule:
        transcript = str(records[index]["transcript_hash"])
        transcript_counts[transcript] = transcript_counts.get(transcript, 0) + 1
    if len(set(transcript_counts.values())) != 1:
        raise ConfigurationError("OpenHands v17 equal-trajectory weights drifted")
    base = {
        "schema_version": "1.0",
        "format_id": _SAMPLER_FORMAT,
        "dataset_hash": dataset_manifest["dataset_hash"],
        "objective_id": "trajectory_balanced_decision_target_token_mean_batch1_v1",
        "equal_trajectory_weight": True,
        "trajectory_count": len(transcript_counts),
        "samples_per_trajectory": next(iter(transcript_counts.values())),
        "source_record_count": len(records),
        "epoch_sample_count": len(schedule),
        "source_record_indices": list(schedule),
        "scheduled_record_hashes": [records[index]["record_hash"] for index in schedule],
    }
    atomic_dump_json(
        output / "sampler-manifest.json",
        {**base, "sampler_hash": content_hash(base)},
    )


def _write_trajectory_records(
    path: Path, records: list[dict[str, Any]], *, attempt: dict[str, Any]
) -> None:
    manifest_path = path.with_suffix(".manifest.json")
    try:
        _atomic_jsonl(path, records)
        base = {
            "schema_version": "1.0",
            "format_id": _RECORDS_FORMAT,
            "episode_id": attempt["episode_id"],
            "role": attempt["role"],
            "task_id": attempt["task_id"],
            "transcript_hash": attempt["transcript_hash"],
            "run_hash": attempt["run_hash"],
            "record_count": len(records),
            "record_hashes": [record["record_hash"] for record in records],
            "max_token_count": max(int(record["token_count"]) for record in records),
            "records_file": path.name,
            "records_sha256": hash_bytes(path.read_bytes()),
            "truncation_applied": False,
            "production_training_ready": False,
        }
        atomic_dump_json(
            manifest_path,
            {**base, "manifest_hash": content_hash(base)},
        )
    except BaseException:
        path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise


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


def _load_locks(*, training_dir: Path, validation_dir: Path) -> dict[str, Any]:
    training_tasks = set(OPENHANDS_V17_IDENTITY_TASKS) - {
        "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3191",
        "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204",
    }
    validation_tasks = set(OPENHANDS_V17_IDENTITY_TASKS) - training_tasks
    return {
        **_image_locks(training_dir, training_tasks),
        **_image_locks(validation_dir, validation_tasks),
    }


def _scan_provider_values(root: Path) -> dict[str, Any]:
    """Expose the frozen private-artifact scan to formal continuation entrypoints."""

    report: dict[str, Any] = _canary_runner._scan_provider_values(root)
    return report


def _zero_call_preflight(locks: dict[str, Any]) -> None:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    _configured_control_root()
    _configured_mcp_pythonpath()
    for task_id in OPENHANDS_V17_FORMAL_TASKS:
        runtime = DockerRuntime(_docker_config(locks[task_id]))
        try:
            runtime.prepare(f"openhands-v17-formal-preflight-{task_id.rsplit('-', 1)[-1]}")
        finally:
            runtime.close()


def _qualified_sources(progress: dict[str, Any]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for key in ("training_pool", "development_validation"):
        values = progress.get(key)
        if not isinstance(values, list):
            raise ConfigurationError("OpenHands v17 formal qualification pool is malformed")
        for item in values:
            if not isinstance(item, dict):
                raise ConfigurationError("OpenHands v17 formal qualification entry is malformed")
            task_id = item.get("task_id")
            source = item.get("source")
            if task_id in OPENHANDS_V17_IDENTITY_TASKS:
                if not isinstance(task_id, str) or not isinstance(source, str):
                    raise ConfigurationError("OpenHands v17 formal source mapping is malformed")
                sources[task_id] = source
    if set(sources) != set(OPENHANDS_V17_IDENTITY_TASKS):
        raise ConfigurationError("OpenHands v17 formal source mapping is incomplete")
    return sources


def _episode(role: str, task_id: str) -> dict[str, Any]:
    return {
        "episode_id": f"{role}-pr{task_id.rsplit('-', 1)[-1]}-s487",
        "role": role,
        "task_id": task_id,
        "seed": OPENHANDS_V17_COLLECTION_SEED,
        "sample_index": OPENHANDS_V17_COLLECTION_SAMPLE_INDEX,
    }


def _image_receipt(locks: dict[str, Any]) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v17_formal_image_locks_v1",
        "locks": {
            task_id: {
                "lock_hash": lock.lock_hash,
                "agent_image": lock.derived_agent_image_id,
                "verifier_image": lock.verifier_base_image_id,
            }
            for task_id, lock in sorted(locks.items())
        },
    }
    return {**base, "receipt_hash": content_hash(base)}


def _write_gate(root: Path, attempts: list[dict[str, Any]]) -> None:
    gate = evaluate_v17_collection_gate(attempts)
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_COLLECTION_GATE_FORMAT,
        **asdict(gate),
        "attempt_count": len(attempts),
        "heldout_episodes_collected": 0,
    }
    atomic_dump_json(root / "data-gate.json", {**base, "gate_hash": content_hash(base)})


def _write_progress(
    root: Path, base_report: dict[str, Any], attempts: list[dict[str, Any]]
) -> None:
    atomic_dump_json(
        root / "campaign-progress.json",
        seal_v17_collection_report({**base_report, "attempts": attempts}),
    )


def _invalid_attempt(episode: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **episode,
        "run_id": episode["episode_id"],
        "run_hash": content_hash({"episode": episode, "reason": reason}),
        "status": "infrastructure_or_security_invalid",
        "imported_canary": False,
        "infrastructure_valid": False,
        "runtime_evidence_valid": False,
        "security_scan_passed": False,
        "ordinary_verifier_resolved": False,
        "fresh_exact_trajectory": False,
        "exact_64k_eligible": False,
        "truncation_applied": False,
        "failure_boundary": reason,
    }


def _stop(
    root: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
    reason: str,
) -> None:
    stopped = seal_v17_collection_report(
        {
            **base_report,
            "status": "formal_collection_stopped_fail_closed",
            "attempts": attempts,
            "stop_reason": reason,
            "data_gate_satisfied": False,
            "gpu_submission_allowed": False,
        }
    )
    atomic_dump_json(root / "campaign-progress.json", stopped)
    atomic_dump_json(root / "campaign-report.json", stopped)


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPENHANDS_V17_COLLECTION_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V17_COLLECTION_OPT_IN_ENV}=1 is required")
    if campaign_id != OPENHANDS_V17_COLLECTION_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands v17 formal campaign identity changed")
    if not os.environ.get(OPENHANDS_V17_COLLECTION_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_V17_COLLECTION_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands v17 formal provider environment is incomplete")
    expected = {
        "openhands-sdk": OPENHANDS_V17_COLLECTION_SDK_VERSION,
        "litellm": OPENHANDS_V17_COLLECTION_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V17_COLLECTION_TIKTOKEN_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"OpenHands v17 formal {package} version changed")


def main() -> int:
    report = collect(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "data_gate_satisfied": report["data_gate_satisfied"],
                "training_distinct_task_count": report["training_distinct_task_count"],
                "validation_distinct_task_count": report["validation_distinct_task_count"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
