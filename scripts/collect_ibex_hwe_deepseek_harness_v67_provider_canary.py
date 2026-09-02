#!/usr/bin/env python3
"""Run the authorized single-task Ibex PR-166 DeepSeek Harness canary once."""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from verigym_deepseek_harness import __version__ as VERIGYM_DEEPSEEK_HARNESS_VERSION
from verigym_deepseek_harness.config import (
    API_KEY_ENV,
    BASE_URL_ENV,
    DEEPSEEK_HARNESS_VERSION,
    MAX_PROVIDER_CALLS,
    MAX_PROVIDER_TOKENS,
)

from verigym.api import VeriGym
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.core.trace import read_trace
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness import (
    DEEPSEEK_HARNESS_MODEL,
    materialize_deepseek_harness_decision_examples_v3,
    validate_deepseek_harness_transcript_v3,
)
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID
from verigym.hwe.qwen_action_tokenizer import (
    QwenDecisionExampleTokenizer,
    dry_run_decision_record_v4,
    exact_decision_token_receipt,
)
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_base = importlib.import_module(
    "scripts.collect_ibex_hwe_deepseek_harness_v65_provider_canary"
    if __package__
    else "collect_ibex_hwe_deepseek_harness_v65_provider_canary"
)

CAMPAIGN_ID = "deepseek-harness-hwe-v67-ibex-pr166-provider-canary-v1"
TASK_ID = "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-166"
SEED = 501
SAMPLE_INDEX = 17
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V67_IBEX_PR166_CANARY"
AUTHORIZATION_FORMAT = (
    "verigym_deepseek_harness_hwe_v67_ibex_pr166_provider_canary_authorization_v1"
)
AUTHORIZATION_HASH = "51914255de5d7ad8994b0e58cbc8f2a8b6c20703dab48369a6bf36e7ad3bb246"
REPORT_FORMAT = "verigym_deepseek_harness_hwe_v67_ibex_pr166_provider_canary_result_v1"
DECISION_FORMAT = "verigym_deepseek_harness_hwe_v67_decision_sft_64k_v1"
DATASET_FORMAT = "verigym_deepseek_harness_hwe_v67_decision_dataset_64k_v1"
QUALIFICATION_MERGE_COMMIT = "64c3883eab594eab23a9ccc6452705ae4381c52f"
QUALIFICATION_MAIN_RUN_ID = 33_641_643_247

MATERIALIZATION_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v66-ibex-pr166-command-image-v1"
)
SOURCE_ROOT = Path("/data2/jiadongzhu/Agent/datasets/hwe-ibex-pr166-harness-v66-fresh-v1")
TOKENIZER_ROOT = Path("/data2/jiadongzhu/Agent/datasets/Qwen3.5-9B-tokenizer-v1")
BASE_MODEL_LOCK = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "openhands-hwe-v58-ibex-pr54-provider-canary-inputs-v1/base-model-lock.json"
)
COMMAND_LOCK_FILE_SHA256 = "43c0a0c44da6acdb0b762df9751a5586dec547cb06b00322fd6ef9f9fed04d2b"
SECURITY_SCAN_FILE_SHA256 = "d1c60102ffc0ad902e5b2749c29c7b9831bdeb8e4c2de16204a0461a19de0b1d"
ZERO_PROVIDER_RESULT_SHA256 = "62454c972923bcd2f1e3575415fe0770f6d0049983d4731c379c18f05f9b1354"
SOURCE_IMAGE_LOCK_SHA256 = "aabe5a6bb353f4836e4a69e4a6bf6e922ae0a4a49f8eef40a950b79409b1971b"
BASE_MODEL_LOCK_SHA256 = "cf7c9873fda3df377d6c46096b57f8aa1b9b13c4ab6f7d2c19739c2082b0e111"
MODEL_SNAPSHOT_HASH = "fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156"
TOKENIZER_HASH = "440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e"
ZERO_PROVIDER_RESULT_HASH = "5ef5464693bc957eb548232c7a4dfacaf2f80f6e07dc53d48c183f5fc2cfe678"
COMMAND_EXECUTION_BACKEND: Literal["episode_container_exec_v1"] = "episode_container_exec_v1"
MAX_JSON_BYTES = 64 * 1024 * 1024
REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_deepseek_harness_v67_ibex_pr166_provider_canary_v1.json",
    "docs/audits/2026-09-02_deepseek-harness-v66-pr222-scaffold-stop-pr166-zero-provider.md",
    "docs/audits/2026-09-02_deepseek-harness-v67-ibex-pr166-provider-canary-authorization.md",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/agent.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/broker.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/config.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/helper.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/process.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/runtime/hwe-tools.mjs",
    "scripts/collect_ibex_hwe_deepseek_harness_v67_provider_canary.py",
    "src/verigym/schemas/external_agent.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--materialization-root", type=Path, default=MATERIALIZATION_ROOT)
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--tokenizer-root", type=Path, default=TOKENIZER_ROOT)
    parser.add_argument("--base-model-lock", type=Path, default=BASE_MODEL_LOCK)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=CAMPAIGN_ID)
    return parser


def validate_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    validated = copy.deepcopy(dict(value))
    expected_hash = validated.pop("authorization_hash", None)
    schedule = validated.get("schedule")
    binding = validated.get("task_binding")
    protocol = validated.get("protocol")
    budget = validated.get("provider_budget")
    actions = validated.get("authorized_actions")
    if (
        expected_hash != AUTHORIZATION_HASH
        or content_hash(validated) != expected_hash
        or validated.get("format_id") != AUTHORIZATION_FORMAT
        or validated.get("identity") != CAMPAIGN_ID
        or validated.get("qualification_merge_commit") != QUALIFICATION_MERGE_COMMIT
        or validated.get("qualification_post_merge_main_run_id") != QUALIFICATION_MAIN_RUN_ID
        or validated.get("qualification_post_merge_main_all_eight_classes_passed") is not True
        or schedule
        != [{"task_id": TASK_ID, "role": "training", "seed": SEED, "sample_index": SAMPLE_INDEX}]
        or not isinstance(binding, dict)
        or binding.get("task_id") != TASK_ID
        or binding.get("task_hash")
        != "d3c05fdf9be2c8c9dae301f702de207c0986dc222625a0c573e1745b14b45d24"
        or binding.get("source_hash")
        != "205b4e61416e4bca5bd7ef8a52167637845b1817e09e960e746b572c7814f18a"
        or binding.get("command_image_lock_hash")
        != "d174aa1ce310c672cafa5820197351250b2b9b7b9fecdc61b1b0f01845a4864f"
        or binding.get("command_image")
        != "sha256:1b5c838add1f3f969ce7e6887fe68c5c84078b2b2920535856751c7bff632809"
        or binding.get("verifier_image")
        != "sha256:b7894597216546304802a6470aab76b0db297854704854b21fa32de3fd80a240"
        or binding.get("security_scan_id")
        != "60277eaa6168466c9b4789374c3a5fab56e049c516360b4efa992dd2a377563e"
        or not isinstance(protocol, dict)
        or protocol.get("ordinary_tool_choice") != "auto"
        or protocol.get("provider_hidden_thinking") != "disabled"
        or protocol.get("content_only_recovery_budget") != 1
        or protocol.get("pre_edit_checkpoint_action") != 16
        or protocol.get("pre_edit_no_progress_action") != 32
        or not isinstance(budget, dict)
        or budget.get("max_provider_calls") != MAX_PROVIDER_CALLS
        or budget.get("max_provider_tokens") != MAX_PROVIDER_TOKENS
        or budget.get("max_context_tokens") != 65_536
        or budget.get("max_output_tokens") != 2048
        or budget.get("temperature") != 0
        or budget.get("provider_request_retries") != 0
        or budget.get("whole_episode_retries") != 0
        or actions
        != {
            "invoke_provider_for_pr166_once": True,
            "retry_pr166": False,
            "run_formal_collection": False,
            "start_training": False,
        }
        or validated.get("provider_calls_before_canary") != 0
        or validated.get("benchmark_task_consumed_before_canary") is not False
        or any(
            validated.get(key) is not False
            for key in (
                "formal_collection_allowed",
                "formal_collection_started",
                "collection_started",
                "training_started",
                "production_training_ready",
            )
        )
    ):
        raise ConfigurationError("DeepSeek Harness v67 authorization identity changed")
    return {**validated, "authorization_hash": expected_hash}


def materialize_exact_64k_records(
    transcript: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    tokenizer: QwenDecisionExampleTokenizer,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_rows = materialize_deepseek_harness_decision_examples_v3(
        transcript,
        binding=binding,
        tokenizer=tokenizer,
    )
    records: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    for source_row in source_rows:
        tools = copy.deepcopy(source_row["tools"])
        input_messages = copy.deepcopy(source_row["input_messages"])
        target_message = copy.deepcopy(source_row["target_message"])
        receipt = exact_decision_token_receipt(
            tokenizer=tokenizer,
            tools=tools,
            input_messages=input_messages,
            target_message=target_message,
        )
        if receipt["token_count"] > 65_536:
            raise ValueError("DeepSeek Harness v67 decision exceeds exact 64K")
        base = {
            key: copy.deepcopy(item)
            for key, item in source_row.items()
            if key
            not in {
                "format_id",
                "record_hash",
                "tokenizer_id",
                "tokenizer_hash",
                "chat_template_hash",
                "input_tokens",
                "target_tokens",
                "token_count",
                "max_length",
                "eligible",
            }
        }
        base.update(
            {
                "format_id": DECISION_FORMAT,
                "source_v3_record_hash": source_row["record_hash"],
                "tools": tools,
                "tool_schema_hash": content_hash(tools),
                "input_messages": input_messages,
                "target_message": target_message,
                **receipt,
                "max_length": 65_536,
                "eligible": True,
            }
        )
        record = {**base, "record_hash": content_hash(base)}
        records.append(record)
        dry_runs.append(dry_run_decision_record_v4(record, tokenizer=tokenizer))
    if not records:
        raise ValueError("DeepSeek Harness v67 resolved trajectory has no supervised decisions")
    return records, dry_runs


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    authorization = validate_authorization(_load_json(arguments.authorization))
    _require_opt_in(arguments.campaign_id)
    source_commit = _merged_source_commit()
    materialization = _exact_directory(
        arguments.materialization_root, MATERIALIZATION_ROOT, "materialization"
    )
    source_root = _exact_directory(arguments.source, SOURCE_ROOT, "source")
    tokenizer_root = _exact_directory(arguments.tokenizer_root, TOKENIZER_ROOT, "tokenizer")
    base_model_lock_path = _exact_file(
        arguments.base_model_lock, BASE_MODEL_LOCK, "base-model lock"
    )
    lock = _materialized_lock(materialization, authorization)
    _validated_source(source_root)
    if hash_bytes(base_model_lock_path.read_bytes()) != BASE_MODEL_LOCK_SHA256:
        raise ConfigurationError("DeepSeek Harness v67 base-model lock changed")
    model_lock = _base._base_model_lock(base_model_lock_path, tokenizer_root)
    if (
        model_lock["snapshot_hash"] != MODEL_SNAPSHOT_HASH
        or model_lock["tokenizer_hash"] != TOKENIZER_HASH
    ):
        raise ConfigurationError("DeepSeek Harness v67 tokenizer binding changed")
    tokenizer, transformers_version = _base._load_tokenizer(tokenizer_root)
    exact_tokenizer = QwenDecisionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_root)
    if exact_tokenizer.tokenizer_hash != TOKENIZER_HASH:
        raise ConfigurationError("DeepSeek Harness v67 exact tokenizer identity changed")

    root = _new_output(arguments.output)
    for directory in ("runs", "dataset", "trajectory-records", "security-scans"):
        (root / directory).mkdir(mode=0o700)
    base_report: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": REPORT_FORMAT,
        "campaign_id": CAMPAIGN_ID,
        "authorization_hash": authorization["authorization_hash"],
        "source_commit": source_commit,
        "qualification_merge_commit": QUALIFICATION_MERGE_COMMIT,
        "qualification_post_merge_main_run_id": QUALIFICATION_MAIN_RUN_ID,
        "task_id": TASK_ID,
        "seed": SEED,
        "sample_index": SAMPLE_INDEX,
        "provider": "deepseek-official",
        "model": DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "max_provider_calls": MAX_PROVIDER_CALLS,
        "max_provider_tokens": MAX_PROVIDER_TOKENS,
        "provider_request_retries": 0,
        "whole_episode_retries": 0,
        "harness_version": DEEPSEEK_HARNESS_VERSION,
        "verigym_deepseek_harness_version": VERIGYM_DEEPSEEK_HARNESS_VERSION,
        "transformers_version": transformers_version,
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "command_image_lock_hash": lock.lock_hash,
        "provider_episode_started": False,
        "attempt": None,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
        "status": "preflight",
    }
    _write_progress(root, base_report)
    try:
        _zero_call_preflight(root, lock)
    except Exception as exc:
        return _stop(
            root,
            base_report,
            "stopped_pre_provider_infrastructure_invalid",
            f"zero_call_preflight:{type(exc).__name__}",
            provider_started=False,
        )

    running = {
        **base_report,
        "status": "provider_canary_running_pending_request_marker",
        "provider_episode_started": False,
    }
    _write_progress(root, running)
    try:
        attempt = _run_episode(
            service=_service(),
            authorization=authorization,
            source_root=source_root,
            lock=lock,
            tokenizer=exact_tokenizer,
            root=root,
        )
    except Exception as exc:
        return _stop_after_episode_exception(root, running, exc)
    atomic_dump_json(root / "attempt.json", attempt)
    provider_started = attempt["provider_request_started"] is True
    if not provider_started:
        return _stop(
            root,
            running,
            "stopped_pre_provider_infrastructure_invalid",
            "provider_episode:request_marker_missing",
            provider_started=False,
        )
    planes = attempt["planes"]
    passed = all(
        planes.get(key) is True
        for key in (
            "benchmark_verifier_pass",
            "agent_protocol_valid",
            "trajectory_eligible",
            "infrastructure_valid",
            "security_valid",
            "sft_admitted",
        )
    )
    final = _seal_report(
        {
            **running,
            "provider_episode_started": True,
            "status": (
                "canary_passed_pending_formal_materialization" if passed else "canary_failed_closed"
            ),
            "attempt": attempt,
            "canary_passed": passed,
            "trajectory_collected": attempt["decision_record_count"] > 0,
            "exact_64k_eligible": attempt["exact_64k_eligible"],
            "task_consumed": True,
            "task_disposition": (
                "import_canary_without_reexecution" if passed else "frozen_after_failed_canary"
            ),
            "failure_reason": None if passed else "six_plane_gate_failed",
            "provider_episode_count": 1,
            "provider_call_count": attempt["provider_call_count"],
            "provider_input_tokens": attempt["provider_input_tokens"],
            "provider_output_tokens": attempt["provider_output_tokens"],
            "provider_total_tokens": attempt["provider_total_tokens"],
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def _run_episode(
    *,
    service: VeriGym,
    authorization: dict[str, Any],
    source_root: Path,
    lock: HweCommandImageLock,
    tokenizer: QwenDecisionExampleTokenizer,
    root: Path,
) -> dict[str, Any]:
    binding = authorization["task_binding"]
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(TASK_ID, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != binding["task_hash"]
        or task.source.content_hash != binding["source_hash"]
    ):
        raise ConfigurationError("DeepSeek Harness v67 task/source binding changed")
    episode_id = "training-ibex-pr166-s501-v67"
    started = time.monotonic()
    result = service.run(
        RunConfig(
            task_id=TASK_ID,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=binding["task_hash"],
            expected_source_hash=binding["source_hash"],
            mode=InteractionMode.AGENT,
            agent="deepseek-harness-hwe-agent-v4",
            agent_options={
                "model_id": DEEPSEEK_HARNESS_MODEL,
                "max_process_time_s": 3600,
                "max_output_bytes": 32 * 1024 * 1024,
                "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "command_image_lock_hash": lock.lock_hash,
                "whole_episode_retries": 0,
            },
            runtime="docker",
            docker_config=_runtime_config(lock),
            seed=SEED,
            sample_index=SAMPLE_INDEX,
            output=root / "runs",
            run_id=episode_id,
            experiment_id=CAMPAIGN_ID,
            plan_item_id=episode_id,
            system_id="deepseek-harness-hwe-native-shell-v4",
            base_seed=SEED,
        )
    )
    scorecard = result.scorecard
    infrastructure_valid = not _base._infrastructure_invalid(scorecard)
    run_dir = Path(result.run_dir).resolve(strict=True)
    if run_dir.is_symlink() or not run_dir.is_relative_to((root / "runs").resolve()):
        raise ConfigurationError("DeepSeek Harness v67 run directory escaped output")
    evidence_root = run_dir / "artifacts/deepseek_harness"
    evidence: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None
    protocol_valid = False
    try:
        evidence = _load_json(evidence_root / "collection_evidence.json")
    except (OSError, TypeError, ValueError, ConfigurationError):
        evidence = None
    marker_started = _provider_request_started_in_runs(root)
    provider_started = (
        evidence is not None
        and evidence.get("provider_request_started") is True
        and evidence.get("provider_request_count_lower_bound") == 1
    ) or marker_started
    if infrastructure_valid and evidence is not None:
        try:
            transcript = validate_deepseek_harness_transcript_v3(
                _load_json(evidence_root / "deepseek_harness_teacher_transcript_v3.json")
            )
            _validate_collection_evidence(evidence)
            protocol_valid = True
        except (OSError, KeyError, TypeError, ValueError, ConfigurationError):
            evidence = None
            transcript = None

    records: list[dict[str, Any]] = []
    dry_runs: list[dict[str, Any]] = []
    if scorecard.resolved and protocol_valid and transcript is not None:
        reproducibility = scorecard.reproducibility
        try:
            records, dry_runs = materialize_exact_64k_records(
                transcript,
                binding={
                    "sample_id": content_hash(
                        {
                            "authorization_hash": authorization["authorization_hash"],
                            "episode_id": episode_id,
                            "scorecard": scorecard.model_dump(mode="json"),
                        }
                    ),
                    "task_hash": binding["task_hash"],
                    "source_hash": binding["source_hash"],
                    "candidate_hash": reproducibility.candidate_hash,
                    "verifier_hash": reproducibility.verifier_hash,
                },
                tokenizer=tokenizer,
            )
        except (KeyError, TypeError, ValueError):
            records = []
            dry_runs = []

    record_root: Path | None = None
    if records:
        record_root = root / "trajectory-records" / episode_id
        record_root.mkdir(mode=0o700)
        _atomic_jsonl(record_root / "decisions.jsonl", records)
        _write_dataset(root / "dataset", records, dry_runs, transcript)

    scan_roots = [evidence_root]
    if record_root is not None:
        scan_roots.extend((record_root, root / "dataset"))
    security_report = scan_artifact_roots(
        scan_roots,
        report_id=f"deepseek-harness-hwe-v67-{episode_id}",
        proxy_values=_provider_values(),
        forbidden_host_roots=(str(source_root), str(Path.cwd().resolve())),
    )
    atomic_dump_json(root / "security-scans" / f"{episode_id}.json", security_report)
    security_valid = security_report.gate == "pass"
    if security_valid:
        require_security_scan_pass(security_report)
    provider_value_scan = _scan_provider_values(root)
    security_valid = security_valid and provider_value_scan["passed"] is True

    trajectory_eligible = bool(records)
    sft_admitted = (
        scorecard.resolved
        and protocol_valid
        and trajectory_eligible
        and infrastructure_valid
        and security_valid
    )
    efficiency = scorecard.efficiency
    planes = {
        "benchmark_verifier_pass": scorecard.resolved,
        "agent_protocol_valid": protocol_valid,
        "trajectory_eligible": trajectory_eligible,
        "infrastructure_valid": infrastructure_valid,
        "security_valid": security_valid,
        "sft_admitted": sft_admitted,
    }
    return {
        "episode_id": episode_id,
        "task_id": TASK_ID,
        "seed": SEED,
        "sample_index": SAMPLE_INDEX,
        "provider_request_started": provider_started,
        "provider_request_count_lower_bound": 1 if provider_started else 0,
        "wall_seconds": time.monotonic() - started,
        "run_hash": content_hash(
            {"episode_id": episode_id, "scorecard": scorecard.model_dump(mode="json")}
        ),
        "planes": planes,
        "provider_call_count": efficiency.external_model_call_count,
        "provider_input_tokens": efficiency.external_input_tokens,
        "provider_output_tokens": efficiency.external_output_tokens,
        "provider_total_tokens": efficiency.external_total_tokens,
        "provider_budget_valid": (
            efficiency.external_model_call_count is not None
            and efficiency.external_model_call_count <= MAX_PROVIDER_CALLS
            and efficiency.external_total_tokens is not None
            and efficiency.external_total_tokens <= MAX_PROVIDER_TOKENS
        ),
        "transcript_hash": transcript.get("transcript_hash") if transcript else None,
        "assistant_decision_count": (
            transcript.get("assistant_decision_count") if transcript else None
        ),
        "supervised_decision_count": (
            transcript.get("supervised_decision_count") if transcript else None
        ),
        "accepted_tool_action_count": (
            transcript.get("accepted_tool_action_count") if transcript else None
        ),
        "masked_policy_error_decision_count": (
            transcript.get("masked_policy_error_decision_count") if transcript else None
        ),
        "masked_format_error_decision_count": (
            transcript.get("masked_format_error_decision_count") if transcript else None
        ),
        "format_repair_count": transcript.get("format_repair_count") if transcript else None,
        "decision_record_count": len(records),
        "maximum_decision_tokens": (
            max(int(item["token_count"]) for item in records) if records else None
        ),
        "exact_64k_eligible": bool(records),
        "truncation_applied": False,
        "decision_only_loss_mask": bool(records),
        "public_rationale_supervised": bool(records),
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
        "sibling_targets_split": False,
        "security_scan_hash": security_report.report_hash,
        "provider_value_scan": provider_value_scan,
        "runtime_command_image": lock.derived_command_image_id,
        "command_execution_backend": COMMAND_EXECUTION_BACKEND,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _write_dataset(
    root: Path,
    records: list[dict[str, Any]],
    dry_runs: list[dict[str, Any]],
    transcript: dict[str, Any] | None,
) -> None:
    _atomic_jsonl(root / "train.jsonl", records)
    manifest_base = {
        "schema_version": "1.0",
        "format_id": DATASET_FORMAT,
        "task_ids": [TASK_ID],
        "record_count": len(records),
        "record_hashes": [item["record_hash"] for item in records],
        "transcript_hash": transcript["transcript_hash"] if transcript else None,
        "supervised_decision_count": len(records),
        "supervised_tool_action_count": sum(int(item["tool_action_count"]) for item in records),
        "max_observed_token_count": max(int(item["token_count"]) for item in records),
        "max_length": 65_536,
        "truncation": "error",
        "truncation_applied": False,
        "exact_token_receipts": True,
        "decision_only_loss_mask": True,
        "failed_decisions_supervised": False,
        "content_only_recovery_supervised": False,
        "sibling_targets_split": False,
        "loader_ready": True,
        "formal_collection_allowed": False,
        "production_training_ready": False,
        "training_started": False,
    }
    atomic_dump_json(
        root / "dataset-manifest.json",
        {**manifest_base, "dataset_hash": content_hash(manifest_base)},
    )
    dry_base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v67_qwen_loader_dry_run_v1",
        "record_count": len(dry_runs),
        "record_hashes": [item["record_hash"] for item in dry_runs],
        "maximum_token_count": max(int(item["token_count"]) for item in dry_runs),
        "overlength_record_count": 0,
        "truncation_applied": False,
        "records": dry_runs,
    }
    atomic_dump_json(
        root / "loader-dry-run.json",
        {**dry_base, "dry_run_hash": content_hash(dry_base)},
    )


def _runtime_config(lock: HweCommandImageLock) -> DockerRuntimeConfig:
    return cast(DockerRuntimeConfig, _base._runtime_config(lock))


def _zero_call_preflight(root: Path, lock: HweCommandImageLock) -> None:
    completed: list[str] = []
    stage = "runtime"
    try:
        runtime = _base.DockerRuntime(_runtime_config(lock))
        try:
            runtime.prepare("deepseek-harness-v67-preflight-pr166")
        finally:
            runtime.close()
        completed.append(stage)
        stage = "harness_initialize"
        _base._zero_call_conformance()
        completed.append(stage)
    except Exception as exc:
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v67_zero_call_preflight_v1",
            "status": "failed",
            "completed_stages": completed,
            "failed_stage": stage,
            "exception_type": type(exc).__name__,
            "provider_episode_count": 0,
            "provider_call_count": 0,
            "raw_exception_persisted": False,
        }
        atomic_dump_json(
            root / "zero-call-preflight.json", {**base, "receipt_hash": content_hash(base)}
        )
        raise
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v67_zero_call_preflight_v1",
        "status": "passed",
        "completed_stages": completed,
        "failed_stage": None,
        "exception_type": None,
        "provider_episode_count": 0,
        "provider_call_count": 0,
        "raw_exception_persisted": False,
    }
    atomic_dump_json(
        root / "zero-call-preflight.json", {**base, "receipt_hash": content_hash(base)}
    )


def _materialized_lock(root: Path, authorization: dict[str, Any]) -> HweCommandImageLock:
    lock_path = root / "image-locks/pr-166.json"
    scan_path = root / "security-scans/pr-166.json"
    zero_path = root / "zero-provider-result.json"
    expected = (
        (lock_path, COMMAND_LOCK_FILE_SHA256),
        (scan_path, SECURITY_SCAN_FILE_SHA256),
        (zero_path, ZERO_PROVIDER_RESULT_SHA256),
    )
    if any(
        path.is_symlink() or hash_bytes(path.read_bytes()) != digest for path, digest in expected
    ):
        raise ConfigurationError("DeepSeek Harness v67 zero-provider evidence changed")
    lock = HweCommandImageLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
    scan = _load_json(scan_path)
    zero = _load_json(zero_path)
    binding = authorization["task_binding"]
    if (
        lock.task_id != TASK_ID
        or lock.lock_hash != binding["command_image_lock_hash"]
        or lock.derived_command_image_id != binding["command_image"]
        or lock.verifier_base_image_id != binding["verifier_image"]
        or lock.security_scan_id != binding["security_scan_id"]
        or lock.source_whiteout_path != "/home/ibex"
        or lock.toolchain_profile_id != binding["toolchain_profile_id"]
        or scan.get("scan_passed") is not True
        or scan.get("secrets_detected") is not False
        or scan.get("security_scan_id") != lock.security_scan_id
        or zero.get("result_hash") != ZERO_PROVIDER_RESULT_HASH
        or zero.get("base_failed") is not True
        or zero.get("base_infrastructure_error") is not False
        or zero.get("reference_passed") is not True
        or zero.get("model_process_count") != 0
        or zero.get("provider_calls") != 0
    ):
        raise ConfigurationError("DeepSeek Harness v67 materialization binding changed")
    observed = subprocess.run(
        ["docker", "image", "inspect", lock.derived_command_image_id, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if observed != lock.derived_command_image_id:
        raise ConfigurationError("DeepSeek Harness v67 command image is unavailable")
    return lock


def _validated_source(root: Path) -> None:
    lock = root / "image-lock.json"
    if lock.is_symlink() or hash_bytes(lock.read_bytes()) != SOURCE_IMAGE_LOCK_SHA256:
        raise ConfigurationError("DeepSeek Harness v67 source lock changed")


def _validate_collection_evidence(value: dict[str, Any]) -> None:
    _base._validate_collection_evidence(value)


def _provider_boundary_state(root: Path) -> tuple[bool, bool]:
    """Return conservative consumption and exact public-marker validity."""

    runs_root = (root / "runs").resolve(strict=True)
    observed = False
    valid = True
    expected = {
        "provider_request_started": True,
        "provider_request_count_lower_bound": 1,
        "credential_values_persisted": False,
        "content_truncated": False,
    }
    for trace_path in sorted(runs_root.rglob("trace.jsonl")):
        resolved = trace_path.resolve(strict=True)
        if trace_path.is_symlink() or not resolved.is_relative_to(runs_root):
            raise ConfigurationError("DeepSeek Harness v67 provider marker trace escaped output")
        for event in read_trace(resolved):
            if event.event_type != "deepseek_harness_provider_request_started":
                continue
            observed = True
            valid = valid and event.payload == expected
    return observed, valid


def _provider_request_started_in_runs(root: Path) -> bool:
    observed, valid = _provider_boundary_state(root)
    if observed and not valid:
        raise ConfigurationError("DeepSeek Harness v67 provider marker payload changed")
    return observed


def _stop_after_episode_exception(
    root: Path,
    report: dict[str, Any],
    exception: Exception,
) -> dict[str, Any]:
    """Always seal a bounded result, including when public marker parsing fails."""

    try:
        provider_started, marker_valid = _provider_boundary_state(root)
        reason = f"provider_episode:{type(exception).__name__}"
        if provider_started and not marker_valid:
            reason = "provider_episode:provider_marker_payload_invalid"
    except (OSError, TypeError, ValueError, ConfigurationError):
        provider_started = True
        reason = "provider_episode:provider_marker_unreadable"
    return _stop(
        root,
        report,
        (
            "stopped_post_provider_infrastructure_or_security_invalid"
            if provider_started
            else "stopped_pre_provider_infrastructure_invalid"
        ),
        reason,
        provider_started=provider_started,
    )


def _service() -> VeriGym:
    return cast(VeriGym, _base._service())


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if campaign_id != CAMPAIGN_ID:
        raise ConfigurationError("DeepSeek Harness v67 campaign identity changed")
    if not os.environ.get(API_KEY_ENV) or not os.environ.get(BASE_URL_ENV):
        raise ConfigurationError("DeepSeek Harness v67 provider environment is incomplete")
    if VERIGYM_DEEPSEEK_HARNESS_VERSION != "0.5.0":
        raise ConfigurationError("DeepSeek Harness v67 integration version changed")


def _provider_values() -> tuple[str, str]:
    return os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV]


def _scan_provider_values(root: Path) -> dict[str, Any]:
    values = tuple(value.encode() for value in _provider_values())
    files = 0
    bytes_scanned = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("DeepSeek Harness v67 artifact contains a symlink")
        if not path.is_file():
            continue
        payload = path.read_bytes()
        files += 1
        bytes_scanned += len(payload)
        if any(value in payload for value in values):
            raise ConfigurationError("provider value reached DeepSeek Harness v67 artifacts")
    return {
        "passed": True,
        "provider_value_count_scanned": len(values),
        "file_count_scanned": files,
        "byte_count_scanned": bytes_scanned,
        "provider_value_hit_count": 0,
        "provider_values_persisted_or_hashed": False,
    }


def _merged_source_commit() -> str:
    repository = Path(__file__).resolve().parents[1]
    for relative in REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("DeepSeek Harness v67 required merged path changed")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=repository, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    upstream = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", QUALIFICATION_MERGE_COMMIT, head],
        cwd=repository,
        check=True,
    )
    if head != upstream or len(head) != 40:
        raise ConfigurationError("DeepSeek Harness v67 requires clean merged origin/main")
    return head


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"DeepSeek Harness v67 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_dir():
        raise ConfigurationError(f"DeepSeek Harness v67 {label} identity changed")
    return resolved


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"DeepSeek Harness v67 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_file():
        raise ConfigurationError(f"DeepSeek Harness v67 {label} identity changed")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ConfigurationError(f"unsafe DeepSeek Harness v67 JSON input: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"DeepSeek Harness v67 JSON is not an object: {path.name}")
    return value


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("DeepSeek Harness v67 output must not already exist")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _atomic_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    _base._atomic_jsonl(path, values)


def _seal_report(value: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _base._seal_report(value))


def _write_progress(root: Path, value: dict[str, Any]) -> None:
    _base._write_progress(root, value)


def _stop(
    root: Path,
    report: dict[str, Any],
    status: str,
    reason: str,
    *,
    provider_started: bool,
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _base._stop(
            root,
            report,
            status,
            reason,
            provider_started=provider_started,
        ),
    )


def main() -> int:
    report = collect(_parser().parse_args())
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("canary_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
