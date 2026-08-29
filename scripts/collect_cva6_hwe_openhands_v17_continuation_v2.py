#!/usr/bin/env python3
"""Continue the frozen OpenHands v17 formal collection without replaying PR-2282."""

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
    OPENHANDS_V17_COLLECTION_LITELLM_VERSION,
    OPENHANDS_V17_COLLECTION_MODEL,
    OPENHANDS_V17_COLLECTION_MODEL_IDENTITY,
    OPENHANDS_V17_COLLECTION_SAMPLE_INDEX,
    OPENHANDS_V17_COLLECTION_SDK_VERSION,
    OPENHANDS_V17_COLLECTION_SEED,
    OPENHANDS_V17_COLLECTION_TIKTOKEN_VERSION,
    OPENHANDS_V17_COLLECTION_TOOL_CHOICE_POLICY,
    OPENHANDS_V17_FORMAL_TRAINING_ORDER,
    OPENHANDS_V17_FORMAL_VALIDATION_ORDER,
    OPENHANDS_V17_IMPORTED_TRAINING_TASKS,
    expected_v17_collection_contract,
    validate_canary_import_root,
)
from verigym_openhands.trajectory import (
    materialize_openhands_decisions,
    validate_openhands_training_trajectory,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.qwen_action_tokenizer import dry_run_decision_record_v4
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.external_agent import ExternalAgentAccounting

if __package__:
    from scripts.hwe_v17_collection_continuation_contract import (
        OPENHANDS_V17_CONTINUATION_CAMPAIGN_ID,
        OPENHANDS_V17_CONTINUATION_GATE_FORMAT,
        OPENHANDS_V17_CONTINUATION_OPT_IN_ENV,
        OPENHANDS_V17_CONTINUATION_REPORT_FORMAT,
        OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
        OPENHANDS_V17_RECOVERY_TASK,
        OPENHANDS_V17_REMAINING_FORMAL_TASKS,
        build_v17_continuation_agent_options,
        build_v17_continuation_agent_version,
        evaluate_v17_continuation_gate,
        load_v17_continuation_contract,
        validate_v17_continuation_image_locks,
        validate_v17_continuation_source,
        validate_v17_recovery_root,
    )
else:
    from hwe_v17_collection_continuation_contract import (
        OPENHANDS_V17_CONTINUATION_CAMPAIGN_ID,
        OPENHANDS_V17_CONTINUATION_GATE_FORMAT,
        OPENHANDS_V17_CONTINUATION_OPT_IN_ENV,
        OPENHANDS_V17_CONTINUATION_REPORT_FORMAT,
        OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
        OPENHANDS_V17_RECOVERY_TASK,
        OPENHANDS_V17_REMAINING_FORMAL_TASKS,
        build_v17_continuation_agent_options,
        build_v17_continuation_agent_version,
        evaluate_v17_continuation_gate,
        load_v17_continuation_contract,
        validate_v17_continuation_image_locks,
        validate_v17_continuation_source,
        validate_v17_recovery_root,
    )

_v1 = importlib.import_module(
    "scripts.collect_cva6_hwe_openhands_v17" if __package__ else "collect_cva6_hwe_openhands_v17"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--training-image-lock-dir", type=Path, required=True)
    parser.add_argument("--validation-image-lock-dir", type=Path, required=True)
    parser.add_argument("--canary-root", type=Path, required=True)
    parser.add_argument("--recovery-root", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=OPENHANDS_V17_CONTINUATION_CAMPAIGN_ID)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Import the exact v1 pass and continue from PR-2468 with no task retry."""

    _require_opt_in(arguments.campaign_id)
    collector_source_commit = _v1._clean_source_commit()
    contract = load_v17_continuation_contract(arguments.contract)
    qualification = arguments.qualification_root.resolve(strict=True)
    split = _v1.validate_task_split(
        TaskSplitManifest.model_validate(_v1._json(qualification / "task-split.json"))
    )
    try:
        derived_split = validate_v17_continuation_source(
            contract,
            split=split,
            task_split_path=qualification / "task-split.json",
            qualification_progress_path=qualification / "qualification-progress.json",
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    qualification_progress = _v1._json(qualification / "qualification-progress.json")
    if qualification_progress.get("status") != "completed":
        raise ConfigurationError("OpenHands v17 continuation qualification is incomplete")
    source_by_task = _v1._qualified_sources(qualification_progress)
    entries = {
        entry.task_id: entry for entry in (*derived_split.training, *derived_split.validation)
    }
    locks = _v1._load_locks(
        training_dir=arguments.training_image_lock_dir,
        validation_dir=arguments.validation_image_lock_dir,
    )
    try:
        validate_v17_continuation_image_locks(contract, locks)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    tokenizer_directory = arguments.tokenizer_root.resolve(strict=True)
    model_lock = _v1._base_model_lock(arguments.base_model_lock, tokenizer_directory)
    if (
        model_lock["snapshot_hash"] != contract["student"]["base_model_snapshot_hash"]
        or model_lock["tokenizer_hash"] != contract["student"]["tokenizer_hash"]
    ):
        raise ConfigurationError("OpenHands v17 continuation model/tokenizer lock changed")
    tokenizer, transformers_version = _v1._load_tokenizer(tokenizer_directory)
    exact_tokenizer = _v1.QwenDecisionExampleTokenizer(
        tokenizer,
        tokenizer_root=tokenizer_directory,
    )
    if exact_tokenizer.tokenizer_hash != model_lock["tokenizer_hash"]:
        raise ConfigurationError("OpenHands v17 continuation exact tokenizer identity changed")

    parent_contract = expected_v17_collection_contract()
    try:
        imported_paths = validate_canary_import_root(arguments.canary_root, parent_contract)
        recovery_path = validate_v17_recovery_root(arguments.recovery_root, contract)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    _v1._scan_provider_values(arguments.recovery_root.resolve(strict=True))

    agent_version = build_v17_continuation_agent_version(image_locks=locks)
    build_v17_continuation_agent_options(
        seed=OPENHANDS_V17_COLLECTION_SEED,
        agent_version=agent_version,
    )

    attempts: list[dict[str, Any]] = []
    records_by_role: dict[str, list[dict[str, Any]]] = {"training": [], "validation": []}
    dry_runs_by_role: dict[str, list[dict[str, Any]]] = {"training": [], "validation": []}
    imported_record_sets: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for task_id in OPENHANDS_V17_IMPORTED_TRAINING_TASKS:
        attempt, records, dry_runs = _v1._import_canary_trajectory(
            task_id=task_id,
            path=imported_paths[task_id],
            contract=parent_contract,
            tokenizer=exact_tokenizer,
        )
        attempts.append(attempt)
        records_by_role["training"].extend(records)
        dry_runs_by_role["training"].extend(dry_runs)
        imported_record_sets.append((attempt, records))
    recovery_attempt, recovery_records, recovery_dry_runs = _import_recovery_trajectory(
        path=recovery_path,
        recovery_root=arguments.recovery_root.resolve(strict=True),
        contract=contract,
        entry=entries[OPENHANDS_V17_RECOVERY_TASK],
        tokenizer=exact_tokenizer,
    )
    attempts.append(recovery_attempt)
    records_by_role["training"].extend(recovery_records)
    dry_runs_by_role["training"].extend(recovery_dry_runs)
    imported_record_sets.append((recovery_attempt, recovery_records))

    base_report = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CONTINUATION_REPORT_FORMAT,
        "campaign_id": arguments.campaign_id,
        "status": "formal_continuation_running",
        "contract_hash": contract["contract_hash"],
        "parent_formal_contract_hash": contract["parent_formal"]["contract_hash"],
        "collector_source_commit": collector_source_commit,
        "agent_source_commit": OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
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
        "recovery_task_reexecuted": False,
        "tool_schema_count": 6,
        "tool_choice_policy": OPENHANDS_V17_COLLECTION_TOOL_CHOICE_POLICY,
        "training_attempt_order": list(OPENHANDS_V17_FORMAL_TRAINING_ORDER),
        "validation_attempt_order": list(OPENHANDS_V17_FORMAL_VALIDATION_ORDER),
        "provider_attempt_order": list(OPENHANDS_V17_REMAINING_FORMAL_TASKS),
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

    root = _v1._new_output(arguments.output)
    runs = root / "runs"
    scans = root / "security-scans"
    records_root = root / "trajectory-records"
    failure_stage = "initial_directory_persistence"
    try:
        for directory in (runs, scans, records_root):
            directory.mkdir(mode=0o700)
        failure_stage = "initial_identity_persistence"
        atomic_dump_json(root / "agent-version.json", agent_version)
        atomic_dump_json(root / "image-lock-receipt.json", _v1._image_receipt(locks))
        atomic_dump_json(root / "preregistration.json", _seal(base_report))
        failure_stage = "imported_trajectory_record_persistence"
        for imported_attempt, imported_records in imported_record_sets:
            _v1._write_trajectory_records(
                records_root / f"{imported_attempt['episode_id']}.jsonl",
                imported_records,
                attempt=imported_attempt,
            )
        failure_stage = "initial_campaign_progress_persistence"
        _write_progress(root, base_report, attempts)
        failure_stage = "initial_collection_gate_persistence"
        _write_gate(root, attempts)
    except Exception as exc:
        reason = f"{failure_stage}:{type(exc).__name__}"
        _stop(root, base_report, attempts, reason)
        raise ConfigurationError("OpenHands v17 continuation initialization failed") from exc

    try:
        _zero_call_preflight(locks)
    except Exception as exc:
        reason = f"zero_call_preflight:{type(exc).__name__}"
        _stop(root, base_report, attempts, reason)
        raise ConfigurationError("OpenHands v17 continuation Docker preflight failed") from exc

    service = _v1._service()
    schedule = [
        *(_v1._episode("training", task_id) for task_id in OPENHANDS_V17_FORMAL_TRAINING_ORDER[1:]),
        *(_v1._episode("validation", task_id) for task_id in OPENHANDS_V17_FORMAL_VALIDATION_ORDER),
    ]
    for episode in schedule:
        gate = evaluate_v17_continuation_gate(attempts)
        if gate.satisfied:
            break
        if not gate.possible:
            _stop(root, base_report, attempts, gate.reason)
            raise ConfigurationError(f"OpenHands v17 continuation capacity failed: {gate.reason}")
        if gate.next_role != episode["role"]:
            continue
        failure_stage = "episode_execution"
        try:
            attempt = _v1._run_validated_episode(
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
                source_commit=OPENHANDS_V17_FROZEN_AGENT_SOURCE_COMMIT,
                agent_version=agent_version,
                agent_options_builder=build_v17_continuation_agent_options,
                runtime_evidence_validator=validate_v17_runtime_evidence,
                system_id=OPENHANDS_V17_COLLECTION_AGENT_VERSION_ID,
                security_report_prefix="openhands-hwe-v17-formal-continuation-v2",
            )
            attempt, records, dry_runs = _v1._materialize_fresh_attempt(
                attempt=attempt,
                episode=episode,
                runs=runs,
                entry=entries[str(episode["task_id"])],
                contract=contract,
                tokenizer=exact_tokenizer,
            )
            failure_stage = "trajectory_record_persistence"
            if records:
                _v1._write_trajectory_records(
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
            invalid = _v1._invalid_attempt(episode, reason)
            _stop(root, base_report, [*attempts, invalid], reason)
            if isinstance(exc, ConfigurationError):
                raise
            raise ConfigurationError(
                f"OpenHands v17 continuation stopped on {episode['episode_id']}"
            ) from exc
        attempts.append(attempt)
        role = str(episode["role"])
        records_by_role[role].extend(records)
        dry_runs_by_role[role].extend(dry_runs)

    gate = evaluate_v17_continuation_gate(attempts)
    _write_gate(root, attempts)
    if not gate.satisfied:
        _stop(root, base_report, attempts, gate.reason)
        raise ConfigurationError(f"OpenHands v17 continuation data gate failed: {gate.reason}")

    training_manifest, training_security = _v1._write_dataset(
        records=records_by_role["training"],
        dry_runs=dry_runs_by_role["training"],
        tokenizer=exact_tokenizer,
        output=root / "training-dataset",
        role="training",
        qualification=qualification,
        tokenizer_directory=tokenizer_directory,
    )
    validation_manifest, validation_security = _v1._write_dataset(
        records=records_by_role["validation"],
        dry_runs=dry_runs_by_role["validation"],
        tokenizer=exact_tokenizer,
        output=root / "validation-dataset",
        role="validation",
        qualification=qualification,
        tokenizer_directory=tokenizer_directory,
    )
    provider_scan = _v1._scan_provider_values(root)
    final = _seal(
        {
            **base_report,
            "status": "formal_continuation_completed_data_gate_passed",
            "attempts": attempts,
            "attempt_count": len(attempts),
            "new_provider_episode_count": sum(
                item.get("imported_canary") is not True
                and item.get("imported_recovery") is not True
                for item in attempts
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


def _import_recovery_trajectory(
    *,
    path: Path,
    recovery_root: Path,
    contract: dict[str, Any],
    entry: Any,
    tokenizer: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    receipt = contract["recovery_import"]
    trajectory = validate_openhands_training_trajectory(_v1._json(path))
    parent_contract = expected_v17_collection_contract()
    records = materialize_openhands_decisions(
        trajectory,
        binding={
            "sample_id": content_hash(
                {
                    "formal_contract_hash": parent_contract["contract_hash"],
                    "episode_id": receipt["episode_id"],
                    "run_hash": receipt["run_hash"],
                }
            ),
            "task_hash": entry.task_hash,
            "source_hash": entry.source_hash,
            "candidate_hash": receipt["candidate_hash"],
            "verifier_hash": receipt["verifier_hash"],
        },
        tokenizer=tokenizer,
    )
    partial_path = recovery_root / "trajectory-records/training-pr2282-s487.jsonl"
    partial_records = [json.loads(line) for line in partial_path.read_text().splitlines()]
    if records != partial_records:
        raise ConfigurationError("OpenHands v17 recovery materialized records changed")
    dry_runs = [dry_run_decision_record_v4(record, tokenizer=tokenizer) for record in records]
    if (
        len(records) != receipt["materialized_record_count"]
        or max(int(record["token_count"]) for record in records)
        != receipt["max_materialized_record_tokens"]
        or any(item["overlength"] for item in dry_runs)
    ):
        raise ConfigurationError("OpenHands v17 recovery exact 64K receipt changed")
    evidence = recovery_root / "runs/training-pr2282-s487/artifacts/openhands_sdk"
    accounting = ExternalAgentAccounting.model_validate(_v1._json(evidence / "accounting.json"))
    try:
        recovery_path = validate_v17_runtime_evidence(
            _v1._json(evidence / "broker.json"),
            _v1._json(evidence / "summary.json"),
            accounting,
            verifier_resolved=True,
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    return (
        {
            "episode_id": receipt["episode_id"],
            "role": "training",
            "task_id": receipt["task_id"],
            "seed": receipt["seed"],
            "sample_index": receipt["sample_index"],
            "run_id": receipt["episode_id"],
            "run_hash": receipt["run_hash"],
            "source_commit": receipt["source_commit"],
            "status": "eligible_imported_recovery",
            "imported_canary": False,
            "imported_recovery": True,
            "infrastructure_valid": True,
            "runtime_evidence_valid": True,
            "security_scan_passed": True,
            "recovery_accounting_valid": True,
            "recovery_path": recovery_path,
            "ordinary_verifier_resolved": True,
            "fresh_exact_trajectory": True,
            "exact_64k_eligible": True,
            "truncation_applied": False,
            "transcript_hash": trajectory["transcript_hash"],
            "decision_record_count": len(records),
            "max_decision_record_tokens": max(int(record["token_count"]) for record in records),
            "model_call_count": accounting.model_call_count,
            "tool_call_count": accounting.external_tool_call_count,
            "input_tokens": accounting.input_tokens,
            "output_tokens": accounting.output_tokens,
            "total_tokens": accounting.total_tokens,
            "whole_episode_retries": 0,
            "provider_request_retries": 0,
        },
        records,
        dry_runs,
    )


def _zero_call_preflight(locks: dict[str, Any]) -> None:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    _configured_control_root()
    _configured_mcp_pythonpath()
    for task_id in OPENHANDS_V17_REMAINING_FORMAL_TASKS:
        runtime = DockerRuntime(_v1._docker_config(locks[task_id]))
        try:
            runtime.prepare(f"openhands-v17-continuation-v2-preflight-{task_id.rsplit('-', 1)[-1]}")
        finally:
            runtime.close()


def _write_gate(root: Path, attempts: list[dict[str, Any]]) -> None:
    gate = evaluate_v17_continuation_gate(attempts)
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CONTINUATION_GATE_FORMAT,
        **asdict(gate),
        "attempt_count": len(attempts),
        "heldout_episodes_collected": 0,
        "recovery_task_reexecuted": False,
    }
    atomic_dump_json(root / "data-gate.json", {**base, "gate_hash": content_hash(base)})


def _write_progress(
    root: Path, base_report: dict[str, Any], attempts: list[dict[str, Any]]
) -> None:
    atomic_dump_json(
        root / "campaign-progress.json",
        _seal({**base_report, "attempts": attempts}),
    )


def _stop(
    root: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
    reason: str,
) -> None:
    stopped = _seal(
        {
            **base_report,
            "status": "formal_continuation_stopped_fail_closed",
            "attempts": attempts,
            "stop_reason": reason,
            "data_gate_satisfied": False,
            "gpu_submission_allowed": False,
            "recovery_task_reexecuted": False,
        }
    )
    atomic_dump_json(root / "campaign-progress.json", stopped)
    atomic_dump_json(root / "campaign-report.json", stopped)


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    base = dict(value)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPENHANDS_V17_CONTINUATION_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V17_CONTINUATION_OPT_IN_ENV}=1 is required")
    if campaign_id != OPENHANDS_V17_CONTINUATION_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands v17 continuation campaign identity changed")
    if not os.environ.get(OPENHANDS_V17_COLLECTION_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_V17_COLLECTION_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands v17 continuation provider environment is incomplete")
    expected = {
        "openhands-sdk": OPENHANDS_V17_COLLECTION_SDK_VERSION,
        "litellm": OPENHANDS_V17_COLLECTION_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V17_COLLECTION_TIKTOKEN_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"OpenHands v17 continuation {package} version changed")


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
