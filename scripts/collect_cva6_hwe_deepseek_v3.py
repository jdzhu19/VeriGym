#!/usr/bin/env python3
"""Run the bounded three-task native DeepSeek Harness HWE v3 pilot exactly once."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
from typing import Any

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.evolution.splits import validate_task_split
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness import (
    DEEPSEEK_HARNESS_CAMPAIGN_FORMAT_V3,
    DEEPSEEK_HARNESS_MODEL,
    DEEPSEEK_HARNESS_PILOT_TASKS,
    build_deepseek_harness_dataset_manifest_v3,
    materialize_deepseek_harness_decision_examples_v3,
    validate_deepseek_harness_transcript_v3,
)
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID
from verigym.hwe.qwen_action_tokenizer import (
    QwenDecisionExampleTokenizer,
    dry_run_decision_record,
)
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_PILOT_FORMAT = "verigym_hwe_deepseek_harness_three_task_pilot_v3"
_collection_v2 = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_API_KEY_ENV: str = _collection_v2._API_KEY_ENV
_BASE_MODEL_ID: str = _collection_v2._BASE_MODEL_ID
_BASE_URL_ENV: str = _collection_v2._BASE_URL_ENV
_OPT_IN: str = _collection_v2._OPT_IN
_assert_provider_secret_absent = _collection_v2._assert_provider_secret_absent
_atomic_jsonl = _collection_v2._atomic_jsonl
_base_model_lock = _collection_v2._base_model_lock
_docker_config = _collection_v2._docker_config
_image_locks = _collection_v2._image_locks
_infrastructure_attempt = _collection_v2._infrastructure_attempt
_infrastructure_invalid = _collection_v2._infrastructure_invalid
_json = _collection_v2._json
_load_tokenizer = _collection_v2._load_tokenizer
_new_output = _collection_v2._new_output
_qualified_sources = _collection_v2._qualified_sources
_runtime_image_preflight = _collection_v2._runtime_image_preflight
_seal_report = _collection_v2._seal_report
_zero_call_conformance = _collection_v2._zero_call_conformance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--predecessor-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    return parser


def collect(
    *,
    qualification_root: Path,
    image_lock_dir: Path,
    tokenizer_root: Path,
    base_model_lock: Path,
    predecessor_report: Path,
    output: Path,
    campaign_id: str,
) -> dict[str, Any]:
    """Collect K=1 with a new contract; never retry, train, or submit HPC work."""

    if os.environ.get(_OPT_IN) != "1":
        raise ConfigurationError(f"{_OPT_IN}=1 is required")
    if not os.environ.get(_API_KEY_ENV) or not os.environ.get(_BASE_URL_ENV):
        raise ConfigurationError("DeepSeek provider environment is incomplete")
    predecessor_hash = _predecessor_receipt(predecessor_report)
    qualification = qualification_root.resolve(strict=True)
    tokenizer_directory = tokenizer_root.resolve(strict=True)
    split = validate_task_split(
        TaskSplitManifest.model_validate(_json(qualification / "task-split.json"))
    )
    progress = _json(qualification / "qualification-progress.json")
    if progress.get("status") != "completed":
        raise ConfigurationError("CVA6 qualification is incomplete")
    source_by_task = _qualified_sources(progress)
    training = {entry.task_id: entry for entry in split.training}
    if any(
        task_id not in source_by_task or task_id not in training
        for task_id in DEEPSEEK_HARNESS_PILOT_TASKS
    ):
        raise ConfigurationError("qualification or split omits a frozen DeepSeek pilot task")
    locks = _image_locks(image_lock_dir, set(DEEPSEEK_HARNESS_PILOT_TASKS))
    model_lock = _base_model_lock(base_model_lock, tokenizer_directory)
    tokenizer, transformers_version = _load_tokenizer(tokenizer_directory)
    exact_tokenizer = QwenDecisionExampleTokenizer(
        tokenizer,
        tokenizer_root=tokenizer_directory,
    )
    if exact_tokenizer.tokenizer_hash != model_lock["tokenizer_hash"]:
        raise ConfigurationError("Qwen tokenizer differs from the frozen base-model lock")
    _runtime_image_preflight(locks)

    root = _new_output(output)
    runs = root / "runs"
    records_root = root / "trajectory-records"
    dataset_root = root / "dataset"
    runs.mkdir(mode=0o700)
    records_root.mkdir(mode=0o700)
    dataset_root.mkdir(mode=0o700)
    base_report = {
        "schema_version": "1.0",
        "format_id": _PILOT_FORMAT,
        "campaign_contract_format": DEEPSEEK_HARNESS_CAMPAIGN_FORMAT_V3,
        "campaign_id": campaign_id,
        "predecessor_v2_report_hash": predecessor_hash,
        "predecessor_trajectories_reused": False,
        "task_split_hash": split.manifest_hash,
        "pilot_task_ids": list(DEEPSEEK_HARNESS_PILOT_TASKS),
        "samples_per_task": 1,
        "best_of_k": False,
        "whole_episode_retries": 0,
        "same_episode_format_repair_budget": 1,
        "provider_request_retries": 0,
        "model_substitution": False,
        "provider": "deepseek-official",
        "model": DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "max_parallel_tool_calls": 1,
        "tool_execution": "serial_in_emitted_order",
        "tool_choice": "auto_pinned_harness_generate_options_has_no_tool_choice_field",
        "assistant_output_contract": "public_text_plus_one_or_more_typed_tool_calls",
        "recoverable_broker_errors": ["invalid_arguments"],
        "failed_decisions_retained_as_context": True,
        "failed_decisions_supervised": False,
        "seed": 484,
        "harness_revision": "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e",
        "harness_version": "0.1.1-rc.2",
        "base_model_id": _BASE_MODEL_ID,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "chat_template_hash": exact_tokenizer.chat_template_hash,
        "transformers_version": transformers_version,
        "pilot_is_benchmark_score": False,
        "production_training_ready": False,
        "training_started": False,
        "heldout_evaluation_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
        "attempts": [],
        "status": "preflight",
    }
    atomic_dump_json(root / "campaign-progress.json", _seal_report(base_report))

    _zero_call_conformance()
    report = {**base_report, "status": "pilot_running", "zero_call_conformance": "passed"}
    atomic_dump_json(root / "campaign-progress.json", _seal_report(report))

    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "deepseek-harness-hwe-agent-v3" not in registries.agents.names():
        from verigym_deepseek_harness import DeepSeekHarnessHweAgentV3Adapter

        registries.agents.register(DeepSeekHarnessHweAgentV3Adapter())
    service = VeriGym(registries)
    all_examples: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    for task_id in DEEPSEEK_HARNESS_PILOT_TASKS:
        entry = training[task_id]
        lock = locks[task_id]
        source_root = (qualification / source_by_task[task_id]).resolve(strict=True)
        if not source_root.is_relative_to(qualification):
            raise ConfigurationError("CVA6 DeepSeek source escapes qualification root")
        source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
        suite, task, _assets = service.load_task(task_id, source)
        snapshot = suite.source_snapshot()
        if (
            snapshot is None
            or content_hash(task) != entry.task_hash
            or task.source.content_hash != entry.source_hash
            or lock.task_hash != entry.task_hash
            or lock.source_hash != entry.source_hash
        ):
            raise ConfigurationError("DeepSeek v3 pilot task/source/image identity changed")
        suffix = task_id.rsplit("-", 1)[-1]
        run_id = f"{campaign_id}-{suffix}"
        config = RunConfig(
            task_id=task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=entry.task_hash,
            expected_source_hash=entry.source_hash,
            mode=InteractionMode.AGENT,
            agent="deepseek-harness-hwe-agent-v3",
            agent_options={
                "model_id": DEEPSEEK_HARNESS_MODEL,
                "max_process_time_s": 3600,
                "max_output_bytes": 32 * 1024 * 1024,
                "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "agent_image_lock_hash": lock.lock_hash,
                "whole_episode_retries": 0,
            },
            runtime="docker",
            docker_config=_docker_config(lock),
            seed=484,
            sample_index=0,
            output=runs,
            run_id=run_id,
            experiment_id=campaign_id,
            plan_item_id=run_id,
            system_id="deepseek-harness-hwe-native-shell-v3",
            base_seed=484,
        )
        try:
            result = service.run(config)
        except Exception as exc:
            reason = str(getattr(exc, "subreason", type(exc).__name__))
            attempt = _infrastructure_attempt(task_id, run_id, reason)
            attempts.append(attempt)
            report = {**report, "attempts": attempts, "status": "stopped_infrastructure_invalid"}
            atomic_dump_json(root / "campaign-progress.json", _seal_report(report))
            atomic_dump_json(root / "campaign-report.json", _seal_report(report))
            raise ConfigurationError(
                f"DeepSeek HWE v3 pilot stopped on infrastructure-invalid {task_id}"
            ) from exc

        scorecard = result.scorecard
        failure = scorecard.failure
        run_hash = content_hash({"run_id": run_id, "scorecard": scorecard.model_dump(mode="json")})
        if _infrastructure_invalid(scorecard):
            reason = (
                failure.protocol_error_subcategory or failure.category
                if failure is not None
                else "scorecard_infrastructure_invalid"
            )
            attempt = _infrastructure_attempt(task_id, run_id, reason, run_hash=run_hash)
            attempts.append(attempt)
            report = {**report, "attempts": attempts, "status": "stopped_infrastructure_invalid"}
            atomic_dump_json(root / "campaign-progress.json", _seal_report(report))
            atomic_dump_json(root / "campaign-report.json", _seal_report(report))
            raise ConfigurationError(
                f"DeepSeek HWE v3 pilot stopped on infrastructure-invalid {task_id}"
            )

        transcript_path = (
            Path(result.run_dir)
            / "artifacts/deepseek_harness/deepseek_harness_teacher_transcript_v3.json"
        )
        transcript: dict[str, Any] | None = None
        task_examples: list[dict[str, Any]] = []
        task_dry_runs: list[dict[str, Any]] = []
        status = "verifier_rejected"
        rejection_reason: str | None = "ordinary_verifier_rejected"
        if not transcript_path.is_symlink() and transcript_path.is_file():
            transcript = validate_deepseek_harness_transcript_v3(_json(transcript_path))
        collection_evidence = _json(
            Path(result.run_dir) / "artifacts/deepseek_harness/collection_evidence.json"
        )
        broker_evidence = collection_evidence.get("broker")
        if not isinstance(broker_evidence, dict):
            raise ConfigurationError("DeepSeek v3 collection evidence lacks broker statistics")
        if scorecard.resolved:
            if transcript is None:
                status = "normalization_failed"
                rejection_reason = "resolved_run_lacks_deepseek_harness_v3_transcript"
            else:
                reproducibility = scorecard.reproducibility
                binding = {
                    "sample_id": content_hash(
                        {"campaign_id": campaign_id, "task_id": task_id, "run_hash": run_hash}
                    ),
                    "task_hash": entry.task_hash,
                    "source_hash": entry.source_hash,
                    "candidate_hash": reproducibility.candidate_hash,
                    "verifier_hash": reproducibility.verifier_hash,
                }
                task_examples = materialize_deepseek_harness_decision_examples_v3(
                    transcript,
                    binding=binding,
                    tokenizer=exact_tokenizer,
                )
                task_dry_runs = [
                    dry_run_decision_record(item, tokenizer=exact_tokenizer)
                    for item in task_examples
                ]
                overlength = [item for item in task_examples if item["eligible"] is not True]
                status = "eligible" if not overlength else "overlength"
                rejection_reason = None if not overlength else "one_or_more_rows_exceed_32768"
                _write_trajectory_records_v3(
                    records_root / f"{suffix}.jsonl",
                    task_examples,
                    task_id=task_id,
                    transcript_hash=str(transcript["transcript_hash"]),
                    run_hash=run_hash,
                )
                all_examples.extend(task_examples)
                dry_runs.extend(task_dry_runs)
        elif failure is not None and failure.kind in {"model", "policy"}:
            status = "policy_rejected"
            rejection_reason = failure.protocol_error_subcategory or failure.category

        attempt = {
            "task_id": task_id,
            "run_id": run_id,
            "run_hash": run_hash,
            "status": status,
            "infrastructure_valid": True,
            "verifier_pass": scorecard.resolved,
            "normalized": transcript is not None,
            "transcript_hash": transcript.get("transcript_hash") if transcript else None,
            "assistant_decision_count": (
                transcript.get("assistant_decision_count") if transcript else None
            ),
            "accepted_tool_action_count": (
                transcript.get("accepted_tool_action_count")
                if transcript
                else broker_evidence.get("tool_calls")
            ),
            "supervised_decision_count": (
                transcript.get("supervised_decision_count") if transcript else None
            ),
            "masked_policy_error_decision_count": (
                transcript.get("masked_policy_error_decision_count") if transcript else None
            ),
            "masked_format_error_decision_count": (
                transcript.get("masked_format_error_decision_count") if transcript else None
            ),
            "format_repair_count": collection_evidence.get("same_episode_format_repair_count"),
            "run_interval_count": collection_evidence.get("run_interval_count"),
            "finish_reason": collection_evidence.get("finish_reason"),
            "broker_rejected_call_count": broker_evidence.get("rejected_calls"),
            "broker_rejection_codes": broker_evidence.get("rejection_codes"),
            "decision_record_count": len(task_examples),
            "max_decision_record_tokens": (
                max(int(item["token_count"]) for item in task_examples) if task_examples else None
            ),
            "overlength_record_count": sum(item["eligible"] is not True for item in task_examples),
            "model_call_count": scorecard.efficiency.external_model_call_count,
            "input_tokens": scorecard.efficiency.external_input_tokens,
            "output_tokens": scorecard.efficiency.external_output_tokens,
            "total_tokens": scorecard.efficiency.external_total_tokens,
            "rejection_reason": rejection_reason,
            "whole_episode_retries": 0,
        }
        attempts.append(attempt)
        report = {**report, "attempts": attempts}
        atomic_dump_json(root / "campaign-progress.json", _seal_report(report))

    _atomic_jsonl(dataset_root / "train.jsonl", all_examples)
    manifest = build_deepseek_harness_dataset_manifest_v3(
        all_examples,
        pilot_task_ids=DEEPSEEK_HARNESS_PILOT_TASKS,
    )
    atomic_dump_json(dataset_root / "dataset-manifest.json", manifest)
    dry_run_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_qwen_loader_dry_run_v3",
        "record_count": len(dry_runs),
        "record_hashes": [item["record_hash"] for item in dry_runs],
        "max_token_count": max((int(item["token_count"]) for item in dry_runs), default=0),
        "overlength_record_count": sum(bool(item["overlength"]) for item in dry_runs),
        "complete_assistant_decision_only": True,
        "input_messages_including_failed_decisions_loss_masked": True,
        "truncation_applied": False,
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "chat_template_hash": exact_tokenizer.chat_template_hash,
        "records": dry_runs,
    }
    atomic_dump_json(
        dataset_root / "loader-dry-run.json",
        {**dry_run_base, "dry_run_hash": content_hash(dry_run_base)},
    )
    _assert_provider_secret_absent(dataset_root)
    security = require_security_scan_pass(
        scan_artifact_roots(
            [dataset_root],
            report_id="deepseek-harness-hwe-v3-pilot-public-dataset",
            forbidden_host_roots=(
                str(qualification),
                str(tokenizer_directory),
                str(Path.cwd().resolve()),
            ),
        )
    )
    atomic_dump_json(root / "dataset-security-scan.json", security)
    final = {
        **report,
        "attempts": attempts,
        "status": "pilot_completed",
        "attempt_count": len(attempts),
        "verifier_pass_count": sum(bool(item["verifier_pass"]) for item in attempts),
        "normalized_trajectory_count": sum(bool(item["normalized"]) for item in attempts),
        "eligible_trajectory_count": sum(item["status"] == "eligible" for item in attempts),
        "overlength_trajectory_count": sum(item["status"] == "overlength" for item in attempts),
        "decision_record_count": len(all_examples),
        "supervised_tool_action_count": manifest["supervised_tool_action_count"],
        "max_decision_record_tokens": max(
            (int(item["token_count"]) for item in all_examples), default=0
        ),
        "overlength_record_count": len(manifest["overlength_records"]),
        "observed_format_repair_count": sum(
            int(item["format_repair_count"] or 0) for item in attempts
        ),
        "observed_masked_policy_error_decision_count": sum(
            int(item["masked_policy_error_decision_count"] or 0) for item in attempts
        ),
        "observed_masked_format_error_decision_count": sum(
            int(item["masked_format_error_decision_count"] or 0) for item in attempts
        ),
        "total_model_call_count": sum(int(item["model_call_count"] or 0) for item in attempts),
        "total_accepted_tool_action_count": sum(
            int(item["accepted_tool_action_count"] or 0) for item in attempts
        ),
        "total_input_tokens": sum(int(item["input_tokens"] or 0) for item in attempts),
        "total_output_tokens": sum(int(item["output_tokens"] or 0) for item in attempts),
        "total_tokens": sum(int(item["total_tokens"] or 0) for item in attempts),
        "dataset_hash": manifest["dataset_hash"],
        "loader_ready": manifest["loader_ready"],
        "dataset_security_scan": security.gate,
        "production_training_ready": False,
        "training_started": False,
        "heldout_evaluation_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
    }
    sealed: dict[str, Any] = _seal_report(final)
    atomic_dump_json(root / "campaign-progress.json", sealed)
    atomic_dump_json(root / "campaign-report.json", sealed)
    return sealed


def _predecessor_receipt(path: Path) -> str:
    report = _json(path.resolve(strict=True))
    expected_hash = report.pop("report_hash", None)
    if (
        not isinstance(expected_hash, str)
        or content_hash(report) != expected_hash
        or report.get("status") != "pilot_completed"
        or report.get("campaign_id") != "cva6-hwe-deepseek-harness-pilot-3task-v2"
        or report.get("pilot_task_ids") != list(DEEPSEEK_HARNESS_PILOT_TASKS)
        or report.get("samples_per_task") != 1
        or report.get("whole_episode_retries") != 0
    ):
        raise ConfigurationError("DeepSeek v3 predecessor is not the sealed frozen v2 pilot")
    return expected_hash


def refresh_completed_report_evidence(root: Path) -> dict[str, Any]:
    """Refresh only aggregate evidence fields after a completed run; never call a model."""

    directory = root.resolve(strict=True)
    report = _json(directory / "campaign-report.json")
    expected_hash = report.pop("report_hash", None)
    attempts = report.get("attempts")
    if (
        not isinstance(expected_hash, str)
        or content_hash(report) != expected_hash
        or report.get("format_id") != _PILOT_FORMAT
        or report.get("status") != "pilot_completed"
        or not isinstance(attempts, list)
        or len(attempts) != 3
    ):
        raise ConfigurationError("DeepSeek v3 completed report cannot be safely refreshed")
    for attempt in attempts:
        if not isinstance(attempt, dict) or not isinstance(attempt.get("run_id"), str):
            raise ConfigurationError("DeepSeek v3 completed attempt receipt is malformed")
        evidence = _json(
            directory
            / "runs"
            / attempt["run_id"]
            / "artifacts/deepseek_harness/collection_evidence.json"
        )
        broker = evidence.get("broker")
        if not isinstance(broker, dict):
            raise ConfigurationError("DeepSeek v3 completed broker receipt is malformed")
        accepted = broker.get("tool_calls")
        if attempt.get("accepted_tool_action_count") not in {None, accepted}:
            raise ConfigurationError("DeepSeek v3 accepted-action receipt changed")
        attempt["accepted_tool_action_count"] = accepted
        attempt["format_repair_count"] = evidence.get("same_episode_format_repair_count")
        attempt["run_interval_count"] = evidence.get("run_interval_count")
        attempt["finish_reason"] = evidence.get("finish_reason")
        attempt["broker_rejected_call_count"] = broker.get("rejected_calls")
        attempt["broker_rejection_codes"] = broker.get("rejection_codes")
    report["observed_format_repair_count"] = sum(
        int(item.get("format_repair_count") or 0) for item in attempts
    )
    report["total_model_call_count"] = sum(
        int(item.get("model_call_count") or 0) for item in attempts
    )
    report["total_accepted_tool_action_count"] = sum(
        int(item.get("accepted_tool_action_count") or 0) for item in attempts
    )
    report["total_input_tokens"] = sum(int(item.get("input_tokens") or 0) for item in attempts)
    report["total_output_tokens"] = sum(int(item.get("output_tokens") or 0) for item in attempts)
    report["total_tokens"] = sum(int(item.get("total_tokens") or 0) for item in attempts)
    sealed: dict[str, Any] = _seal_report(report)
    atomic_dump_json(directory / "campaign-progress.json", sealed)
    atomic_dump_json(directory / "campaign-report.json", sealed)
    return sealed


def _write_trajectory_records_v3(
    path: Path,
    examples: list[dict[str, Any]],
    *,
    task_id: str,
    transcript_hash: str,
    run_hash: str,
) -> None:
    _atomic_jsonl(path, examples)
    raw = path.read_bytes()
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_trajectory_records_v3",
        "task_id": task_id,
        "transcript_hash": transcript_hash,
        "run_hash": run_hash,
        "record_count": len(examples),
        "record_hashes": [item["record_hash"] for item in examples],
        "supervised_tool_action_count": sum(int(item["tool_action_count"]) for item in examples),
        "max_token_count": max(int(item["token_count"]) for item in examples),
        "overlength_record_count": sum(item["eligible"] is not True for item in examples),
        "records_file": path.name,
        "records_sha256": hashlib.sha256(raw).hexdigest(),
        "production_training_ready": False,
        "hpc_jobs_submitted": False,
    }
    atomic_dump_json(
        path.with_suffix(".manifest.json"),
        {**base, "manifest_hash": content_hash(base)},
    )


def main() -> int:
    arguments = _parser().parse_args()
    report = collect(
        qualification_root=arguments.qualification_root,
        image_lock_dir=arguments.image_lock_dir,
        tokenizer_root=arguments.tokenizer_root,
        base_model_lock=arguments.base_model_lock,
        predecessor_report=arguments.predecessor_report,
        output=arguments.output,
        campaign_id=arguments.campaign_id,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
