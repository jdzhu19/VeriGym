#!/usr/bin/env python3
"""Run the bounded five-task OpenHands HWE collection pilot without retries."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from verigym_openhands.hwe_pilot import (
    OPENHANDS_HWE_AGENT_VERSION_ID,
    OPENHANDS_HWE_API_KEY_ENV,
    OPENHANDS_HWE_BASE_URL_ENV,
    OPENHANDS_HWE_MODEL,
    OPENHANDS_HWE_MODEL_IDENTITY,
    OPENHANDS_HWE_NEW_TASKS,
    OPENHANDS_HWE_OPT_IN_ENV,
    OPENHANDS_HWE_PILOT_FORMAT,
    OPENHANDS_HWE_PILOT_REPORT_FORMAT,
    OPENHANDS_HWE_PILOT_TASKS,
    OPENHANDS_HWE_PREDECESSOR_TASK,
    OPENHANDS_HWE_SDK_VERSION,
    build_pilot_agent_version,
    load_predecessor_qualification,
    seal_campaign_report,
    validate_pilot_split,
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
    dry_run_decision_record,
)
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import TaskSplitManifest
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_base_model_lock = _collection._base_model_lock
_docker_config = _collection._docker_config
_image_locks = _collection._image_locks
_infrastructure_invalid = _collection._infrastructure_invalid
_json = _collection._json
_load_tokenizer = _collection._load_tokenizer
_qualified_sources = _collection._qualified_sources

_SEED = 484
_MAX_CONTEXT_TOKENS = 65_536
_MAX_OUTPUT_TOKENS = 2_048
_MAX_ITERATIONS = 200
_DEEPSEEK_V3_FORMAT = "verigym_hwe_deepseek_harness_three_task_pilot_v3"
_DEEPSEEK_PAIRED_TASKS = OPENHANDS_HWE_PILOT_TASKS[:3]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--image-lock-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--predecessor-root", type=Path, required=True)
    parser.add_argument("--deepseek-v3-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    return parser


def collect(
    *,
    qualification_root: Path,
    image_lock_dir: Path,
    tokenizer_root: Path,
    base_model_lock: Path,
    predecessor_root: Path,
    deepseek_v3_report: Path,
    output: Path,
    campaign_id: str,
) -> dict[str, Any]:
    """Collect four new episodes and reuse one immutable positive predecessor."""

    if os.environ.get(OPENHANDS_HWE_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_HWE_OPT_IN_ENV}=1 is required")
    if not os.environ.get(OPENHANDS_HWE_API_KEY_ENV) or not os.environ.get(
        OPENHANDS_HWE_BASE_URL_ENV
    ):
        raise ConfigurationError("OpenHands DeepSeek provider environment is incomplete")
    if (
        not campaign_id
        or len(campaign_id) > 80
        or not all(
            character.islower() or character.isdigit() or character == "-"
            for character in campaign_id
        )
    ):
        raise ConfigurationError("OpenHands pilot campaign ID is not canonical")
    source_commit = _clean_source_commit()
    qualification = qualification_root.resolve(strict=True)
    tokenizer_directory = tokenizer_root.resolve(strict=True)
    split = validate_task_split(
        TaskSplitManifest.model_validate(_json(qualification / "task-split.json"))
    )
    try:
        validate_pilot_split(split)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    qualification_progress = _json(qualification / "qualification-progress.json")
    if (
        qualification_progress.get("status") != "completed"
        or qualification_progress.get("task_split_hash") != split.manifest_hash
    ):
        raise ConfigurationError("CVA6 qualification is incomplete or changed")
    source_by_task = _qualified_sources(qualification_progress)
    training = {entry.task_id: entry for entry in split.training}
    locks = _image_locks(image_lock_dir, set(OPENHANDS_HWE_NEW_TASKS))
    for task_id in OPENHANDS_HWE_NEW_TASKS:
        entry = training[task_id]
        lock = locks[task_id]
        if lock.task_hash != entry.task_hash or lock.source_hash != entry.source_hash:
            raise ConfigurationError("OpenHands pilot task/source/image identity changed")
    model_lock = _base_model_lock(base_model_lock, tokenizer_directory)
    tokenizer, transformers_version = _load_tokenizer(tokenizer_directory)
    exact_tokenizer = QwenDecisionExampleTokenizer(
        tokenizer,
        tokenizer_root=tokenizer_directory,
    )
    if exact_tokenizer.tokenizer_hash != model_lock["tokenizer_hash"]:
        raise ConfigurationError("OpenHands pilot tokenizer differs from the base-model lock")
    predecessor = load_predecessor_qualification(predecessor_root)
    predecessor_entry = training[OPENHANDS_HWE_PREDECESSOR_TASK]
    if (
        predecessor.report.get("task_hash") != predecessor_entry.task_hash
        or predecessor.report.get("source_hash") != predecessor_entry.source_hash
    ):
        raise ConfigurationError("OpenHands predecessor differs from the frozen training split")
    deepseek_report = _deepseek_v3_report(deepseek_v3_report)
    agent_version = build_pilot_agent_version(
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
    predecessor_records = materialize_openhands_decisions(
        predecessor.trajectory,
        binding={
            "sample_id": content_hash(
                {
                    "predecessor_report_hash": predecessor.report_hash,
                    "task_id": OPENHANDS_HWE_PREDECESSOR_TASK,
                }
            ),
            "task_hash": predecessor_entry.task_hash,
            "source_hash": predecessor_entry.source_hash,
            "candidate_hash": str(predecessor.report["candidate_hash"]),
            "verifier_hash": str(predecessor.report["verifier_hash"]),
        },
        tokenizer=exact_tokenizer,
    )
    predecessor_attempt = {
        "task_id": OPENHANDS_HWE_PREDECESSOR_TASK,
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
        "verifier_pass": True,
        "normalized": True,
        "transcript_hash": predecessor.trajectory["transcript_hash"],
        "decision_record_count": len(predecessor_records),
        "max_decision_record_tokens": max(
            int(record["token_count"]) for record in predecessor_records
        ),
        "model_call_count": predecessor.report["agent_model_calls"],
        "whole_episode_retries": 0,
    }
    attempts: list[dict[str, Any]] = [predecessor_attempt]
    all_records = list(predecessor_records)
    dry_runs = [
        dry_run_decision_record(record, tokenizer=exact_tokenizer) for record in predecessor_records
    ]
    base_report = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_HWE_PILOT_REPORT_FORMAT,
        "pilot_format": OPENHANDS_HWE_PILOT_FORMAT,
        "campaign_id": campaign_id,
        "status": "pilot_running",
        "source_commit": source_commit,
        "task_split_hash": split.manifest_hash,
        "pilot_task_ids": list(OPENHANDS_HWE_PILOT_TASKS),
        "new_task_ids": list(OPENHANDS_HWE_NEW_TASKS),
        "predecessor_task_id": OPENHANDS_HWE_PREDECESSOR_TASK,
        "predecessor_report_hash": predecessor.report_hash,
        "predecessor_trajectory_hash": predecessor.trajectory["transcript_hash"],
        "predecessor_reused": True,
        "predecessor_resampled": False,
        "deepseek_v3_report_hash": deepseek_report["report_hash"],
        "samples_per_new_task": 1,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "best_of_k": False,
        "model_substitution": False,
        "model_transport_id": OPENHANDS_HWE_MODEL,
        "model_identity": OPENHANDS_HWE_MODEL_IDENTITY,
        "openhands_sdk_version": OPENHANDS_HWE_SDK_VERSION,
        "agent_version_id": OPENHANDS_HWE_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "seed": _SEED,
        "temperature": 0,
        "top_p": 1,
        "thinking": "disabled",
        "max_context_tokens": _MAX_CONTEXT_TOKENS,
        "max_output_tokens": _MAX_OUTPUT_TOKENS,
        "max_iterations": _MAX_ITERATIONS,
        "tool_contract": "hwe_native_shell_v2",
        "tool_schema_count": 6,
        "campaign_role": "training",
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

    for task_id in OPENHANDS_HWE_NEW_TASKS:
        entry = training[task_id]
        lock = locks[task_id]
        source_root = (qualification / source_by_task[task_id]).resolve(strict=True)
        if not source_root.is_relative_to(qualification):
            raise ConfigurationError("OpenHands pilot source escaped qualification root")
        source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
        suite, task, _assets = service.load_task(task_id, source)
        snapshot = suite.source_snapshot()
        if (
            snapshot is None
            or content_hash(task) != entry.task_hash
            or task.source.content_hash != entry.source_hash
        ):
            raise ConfigurationError("OpenHands pilot qualified source changed before execution")
        suffix = task_id.rsplit("-", 1)[-1]
        run_id = f"{campaign_id}-{suffix}"
        config = RunConfig(
            task_id=task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=entry.task_hash,
            expected_source_hash=entry.source_hash,
            mode=InteractionMode.AGENT,
            agent="openhands-hwe-agent",
            agent_options={
                "model_id": OPENHANDS_HWE_MODEL,
                "base_url_env": OPENHANDS_HWE_BASE_URL_ENV,
                "api_key_env": OPENHANDS_HWE_API_KEY_ENV,
                "max_iterations": _MAX_ITERATIONS,
                "max_process_time_s": 3_600,
                "max_output_tokens": _MAX_OUTPUT_TOKENS,
                "max_context_tokens": _MAX_CONTEXT_TOKENS,
                "seed": _SEED,
                "temperature": 0,
                "top_p": 1,
                "whole_episode_retries": 0,
                "expected_sdk_version": OPENHANDS_HWE_SDK_VERSION,
                "campaign_role": "training",
                "capture_training_transcript": True,
                "agent_version_id": agent_version.agent_version_id,
                "agent_version_hash": agent_version.version_hash,
                "agent_version_manifest_json": manifest_json,
                "collection_profile_id": "hwe_production_native_shell_v2",
            },
            runtime="docker",
            docker_config=_docker_config(lock),
            seed=_SEED,
            sample_index=0,
            output=runs,
            run_id=run_id,
            experiment_id=campaign_id,
            plan_item_id=run_id,
            system_id="openhands-deepseek-v4-flash-hwe-training-pilot-v1",
            base_seed=_SEED,
        )
        try:
            result = service.run(config)
        except Exception as exc:
            attempt = _infrastructure_attempt(task_id, run_id, type(exc).__name__)
            attempts.append(attempt)
            stopped = {
                **base_report,
                "status": "stopped_infrastructure_invalid",
                "attempts": attempts,
                "stop_reason": "run_boundary_exception",
            }
            _write_stopped_report(root, stopped)
            raise ConfigurationError(
                f"OpenHands pilot stopped on infrastructure-invalid {task_id}"
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
            attempt = _infrastructure_attempt(task_id, run_id, reason, run_hash=run_hash)
            attempts.append(attempt)
            stopped = {
                **base_report,
                "status": "stopped_infrastructure_invalid",
                "attempts": attempts,
                "stop_reason": reason,
            }
            _write_stopped_report(root, stopped)
            raise ConfigurationError(f"OpenHands pilot stopped on infrastructure-invalid {task_id}")

        run_directory = Path(result.run_dir).resolve(strict=True)
        trajectory_path = run_directory / "artifacts" / "openhands_sdk" / "training-trajectory.json"
        trajectory: dict[str, Any] | None = None
        records: list[dict[str, Any]] = []
        status = "verifier_rejected"
        rejection_reason: str | None = "ordinary_verifier_rejected"
        if scorecard.resolved:
            if trajectory_path.is_symlink() or not trajectory_path.is_file():
                attempt = _infrastructure_attempt(
                    task_id,
                    run_id,
                    "resolved_run_lacks_openhands_training_trajectory",
                    run_hash=run_hash,
                )
                attempts.append(attempt)
                stopped = {
                    **base_report,
                    "status": "stopped_infrastructure_invalid",
                    "attempts": attempts,
                    "stop_reason": "resolved_trajectory_missing",
                }
                _write_stopped_report(root, stopped)
                raise ConfigurationError(
                    f"OpenHands pilot stopped on missing trajectory for {task_id}"
                )
            trajectory = validate_openhands_training_trajectory(_json(trajectory_path))
            reproducibility = scorecard.reproducibility
            try:
                records = materialize_openhands_decisions(
                    trajectory,
                    binding={
                        "sample_id": content_hash(
                            {
                                "campaign_id": campaign_id,
                                "task_id": task_id,
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
            except OpenHandsTrajectoryError as exc:
                attempt = {
                    **_infrastructure_attempt(
                        task_id,
                        run_id,
                        "exact_64k_materialization_failed",
                        run_hash=run_hash,
                    ),
                    "status": "overlength_or_receipt_invalid",
                    "infrastructure_valid": True,
                    "verifier_pass": True,
                    "normalized": True,
                    "transcript_hash": trajectory.get("transcript_hash"),
                }
                attempts.append(attempt)
                stopped = {
                    **base_report,
                    "status": "stopped_overlength_or_receipt_invalid",
                    "attempts": attempts,
                    "stop_reason": type(exc).__name__,
                    "loader_ready": False,
                }
                _write_stopped_report(root, stopped)
                raise ConfigurationError(
                    f"OpenHands pilot exact 64K materialization failed for {task_id}"
                ) from exc
            status = "eligible"
            rejection_reason = None
            all_records.extend(records)
            dry_runs.extend(
                dry_run_decision_record(record, tokenizer=exact_tokenizer) for record in records
            )
            _write_trajectory_records(
                records_root / f"pr-{suffix}.jsonl",
                records,
                task_id=task_id,
                transcript_hash=str(trajectory["transcript_hash"]),
                run_hash=run_hash,
            )
        elif trajectory_path.exists():
            attempt = _infrastructure_attempt(
                task_id,
                run_id,
                "verifier_rejected_run_exported_positive_trajectory",
                run_hash=run_hash,
            )
            attempts.append(attempt)
            stopped = {
                **base_report,
                "status": "stopped_infrastructure_invalid",
                "attempts": attempts,
                "stop_reason": "positive_export_without_verifier_pass",
            }
            _write_stopped_report(root, stopped)
            raise ConfigurationError("OpenHands pilot exported an ineligible positive trajectory")

        accounting_path = run_directory / "artifacts" / "openhands_sdk" / "accounting.json"
        accounting = _json(accounting_path)
        attempt = {
            "task_id": task_id,
            "run_id": run_id,
            "run_hash": run_hash,
            "status": status,
            "historical_predecessor": False,
            "source_commit": source_commit,
            "infrastructure_valid": True,
            "verifier_pass": scorecard.resolved,
            "normalized": trajectory is not None,
            "transcript_hash": trajectory.get("transcript_hash") if trajectory else None,
            "decision_record_count": len(records),
            "max_decision_record_tokens": (
                max(int(record["token_count"]) for record in records) if records else None
            ),
            "model_call_count": accounting.get("model_call_count"),
            "process_wall_time_s": accounting.get("process_wall_time_s"),
            "rejection_reason": rejection_reason,
            "whole_episode_retries": 0,
        }
        attempts.append(attempt)
        progress = {**base_report, "attempts": attempts, "status": "pilot_running"}
        atomic_dump_json(root / "campaign-progress.json", seal_campaign_report(progress))

    dataset_root = root / "dataset"
    manifest = write_openhands_decision_dataset(
        all_records,
        tokenizer=exact_tokenizer,
        output=dataset_root,
    )
    dry_run_base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_five_task_qwen_loader_dry_run_v1",
        "dataset_hash": manifest["dataset_hash"],
        "record_count": len(dry_runs),
        "record_hashes": [receipt["record_hash"] for receipt in dry_runs],
        "max_token_count": max(int(receipt["token_count"]) for receipt in dry_runs),
        "overlength_record_count": sum(bool(receipt["overlength"]) for receipt in dry_runs),
        "complete_assistant_decision_only": True,
        "truncation_applied": False,
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "chat_template_hash": exact_tokenizer.chat_template_hash,
        "records": dry_runs,
    }
    atomic_dump_json(
        dataset_root / "loader-dry-run.json",
        {**dry_run_base, "dry_run_hash": content_hash(dry_run_base)},
    )
    _assert_provider_secret_absent(root)
    security = require_security_scan_pass(
        scan_artifact_roots(
            [dataset_root],
            report_id="openhands-hwe-five-task-pilot-public-dataset",
            forbidden_host_roots=(
                str(qualification),
                str(tokenizer_directory),
                str(Path.cwd().resolve()),
            ),
        )
    )
    atomic_dump_json(root / "dataset-security-scan.json", security)
    ordered_attempts = _ordered_attempts(attempts)
    comparison = _comparison_receipt(ordered_attempts, deepseek_report)
    atomic_dump_json(root / "three-task-harness-comparison.json", comparison)
    new_attempts = [item for item in attempts if item["historical_predecessor"] is False]
    new_passes = sum(bool(item["verifier_pass"]) for item in new_attempts)
    final = {
        **base_report,
        "status": "pilot_completed",
        "attempts": ordered_attempts,
        "attempt_count": len(ordered_attempts),
        "new_attempt_count": len(new_attempts),
        "infrastructure_valid_attempt_count": sum(
            bool(item["infrastructure_valid"]) for item in ordered_attempts
        ),
        "verifier_pass_count": sum(bool(item["verifier_pass"]) for item in ordered_attempts),
        "new_verifier_pass_count": new_passes,
        "eligible_trajectory_count": manifest["trajectory_count"],
        "decision_record_count": manifest["record_count"],
        "max_decision_record_tokens": manifest["max_observed_token_count"],
        "dataset_hash": manifest["dataset_hash"],
        "loader_ready": True,
        "collector_ready": True,
        "pilot_yield_sufficient": new_passes >= 1,
        "fifty_trajectory_data_gate_satisfied": False,
        "dataset_security_scan": security.gate,
        "comparison_receipt_hash": comparison["comparison_hash"],
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "hpc_jobs_submitted": False,
        "gpu_seconds": 0,
    }
    sealed = seal_campaign_report(final)
    atomic_dump_json(root / "campaign-progress.json", sealed)
    atomic_dump_json(root / "campaign-report.json", sealed)
    return sealed


def _zero_call_preflight(locks: dict[str, Any]) -> None:
    if importlib.metadata.version("openhands-sdk") != OPENHANDS_HWE_SDK_VERSION:
        raise ConfigurationError("OpenHands SDK differs from frozen version 1.42.1")
    if importlib.metadata.version("litellm") != "1.93.0":
        raise ConfigurationError("LiteLLM differs from frozen version 1.93.0")
    from verigym_openhands.hwe_agent import (
        _configured_control_root,
        _configured_mcp_pythonpath,
    )

    _configured_control_root()
    _configured_mcp_pythonpath()
    for task_id in OPENHANDS_HWE_NEW_TASKS:
        runtime = DockerRuntime(_docker_config(locks[task_id]))
        try:
            runtime.prepare(f"openhands-pilot-preflight-{task_id.rsplit('-', 1)[-1]}")
        finally:
            runtime.close()


def _deepseek_v3_report(path: Path) -> dict[str, Any]:
    report = _json(path.resolve(strict=True))
    report_hash = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    attempts = report.get("attempts")
    if (
        not isinstance(report_hash, str)
        or content_hash(base) != report_hash
        or report.get("format_id") != _DEEPSEEK_V3_FORMAT
        or report.get("status") != "pilot_completed"
        or report.get("pilot_task_ids") != list(_DEEPSEEK_PAIRED_TASKS)
        or not isinstance(attempts, list)
        or len(attempts) != 3
    ):
        raise ConfigurationError("DeepSeek v3 comparison report changed")
    return cast(dict[str, Any], report)


def _comparison_receipt(
    openhands_attempts: list[dict[str, Any]],
    deepseek_report: dict[str, Any],
) -> dict[str, Any]:
    openhands = {item["task_id"]: item for item in openhands_attempts}
    deepseek = {item["task_id"]: item for item in deepseek_report["attempts"]}
    rows = []
    for task_id in _DEEPSEEK_PAIRED_TASKS:
        left = deepseek[task_id]
        right = openhands[task_id]
        rows.append(
            {
                "task_id": task_id,
                "deepseek_harness": {
                    "status": left.get("status"),
                    "verifier_pass": left.get("verifier_pass"),
                    "decision_record_count": left.get("decision_record_count"),
                    "max_decision_record_tokens": left.get("max_decision_record_tokens"),
                },
                "openhands": {
                    "status": right.get("status"),
                    "verifier_pass": right.get("verifier_pass"),
                    "decision_record_count": right.get("decision_record_count"),
                    "max_decision_record_tokens": right.get("max_decision_record_tokens"),
                },
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_deepseek_three_task_descriptive_comparison_v1",
        "task_ids": list(_DEEPSEEK_PAIRED_TASKS),
        "rows": rows,
        "same_model_identity": True,
        "same_task_source_bindings": True,
        "benchmark_score_claimed": False,
        "statistical_superiority_claimed": False,
    }
    return {**base, "comparison_hash": content_hash(base)}


def _ordered_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_task = {str(item["task_id"]): item for item in attempts}
    if set(by_task) != set(OPENHANDS_HWE_PILOT_TASKS) or len(by_task) != len(attempts):
        raise ConfigurationError("OpenHands pilot attempt set is incomplete or duplicated")
    return [by_task[task_id] for task_id in OPENHANDS_HWE_PILOT_TASKS]


def _infrastructure_attempt(
    task_id: str,
    run_id: str,
    reason: str,
    *,
    run_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "run_id": run_id,
        "run_hash": run_hash or content_hash({"run_id": run_id, "reason": reason}),
        "status": "infrastructure_invalid",
        "historical_predecessor": False,
        "source_commit": None,
        "infrastructure_valid": False,
        "verifier_pass": False,
        "normalized": False,
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
    task_id: str,
    transcript_hash: str,
    run_hash: str,
) -> None:
    _atomic_jsonl(path, records)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_pilot_trajectory_records_v1",
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
        path.with_suffix(".manifest.json"),
        {**base, "manifest_hash": content_hash(base)},
    )


def _write_stopped_report(root: Path, report: dict[str, Any]) -> None:
    sealed = seal_campaign_report(report)
    atomic_dump_json(root / "campaign-progress.json", sealed)
    atomic_dump_json(root / "campaign-report.json", sealed)


def _assert_provider_secret_absent(root: Path) -> None:
    credential = os.environ[OPENHANDS_HWE_API_KEY_ENV].encode("utf-8")
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink() and credential in path.read_bytes():
            raise ConfigurationError("provider credential value reached OpenHands pilot artifacts")


def _new_output(path: Path) -> Path:
    target = path.expanduser()
    if target.exists() or target.is_symlink():
        raise ConfigurationError("OpenHands pilot output must not already exist")
    target.mkdir(parents=True, mode=0o700)
    return target.resolve(strict=True)


def _clean_source_commit() -> str:
    root = Path(__file__).resolve().parents[1]
    for args in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        diff_result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if diff_result.returncode != 0:
            raise ConfigurationError("OpenHands pilot requires no tracked source changes")
    commit_result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = commit_result.stdout.strip()
    if len(commit) != 40:
        raise ConfigurationError("OpenHands pilot could not resolve a full source commit")
    return commit


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


def main() -> int:
    arguments = _parser().parse_args()
    report = collect(
        qualification_root=arguments.qualification_root,
        image_lock_dir=arguments.image_lock_dir,
        tokenizer_root=arguments.tokenizer_root,
        base_model_lock=arguments.base_model_lock,
        predecessor_root=arguments.predecessor_root,
        deepseek_v3_report=arguments.deepseek_v3_report,
        output=arguments.output,
        campaign_id=arguments.campaign_id,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
