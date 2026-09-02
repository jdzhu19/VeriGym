#!/usr/bin/env python3
"""Run the authorized single-task Ibex PR-974 DeepSeek Harness canary once."""

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
from typing import Any, Literal

from verigym_deepseek_harness import __version__ as VERIGYM_DEEPSEEK_HARNESS_VERSION
from verigym_deepseek_harness.config import (
    API_KEY_ENV,
    BASE_URL_ENV,
    DEEPSEEK_HARNESS_VERSION,
    MAX_PROVIDER_CALLS,
    MAX_PROVIDER_TOKENS,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID
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
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerCommandImageRuntimeConfig, DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_base_model_lock = _collection._base_model_lock
_infrastructure_invalid = _collection._infrastructure_invalid
_load_tokenizer = _collection._load_tokenizer
_zero_call_conformance = _collection._zero_call_conformance

CAMPAIGN_ID = "deepseek-harness-hwe-v62-ibex-pr974-provider-canary-v1"
TASK_ID = "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-974"
SEED = 499
SAMPLE_INDEX = 15
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V62_IBEX_PR974_CANARY"
AUTHORIZATION_FORMAT = (
    "verigym_deepseek_harness_hwe_v62_ibex_pr974_provider_canary_authorization_v1"
)
AUTHORIZATION_HASH = "6bf16888b107fdfe26da968a053e9dc371c9cf30c5cfb76b80db3caca07b0b74"
REPORT_FORMAT = "verigym_deepseek_harness_hwe_v62_ibex_pr974_provider_canary_result_v1"
DECISION_FORMAT = "verigym_deepseek_harness_hwe_v62_decision_sft_64k_v1"
DATASET_FORMAT = "verigym_deepseek_harness_hwe_v62_decision_dataset_64k_v1"
QUALIFICATION_MERGE_COMMIT = "e63b72b83568ba442148f139955daace518a62c6"
QUALIFICATION_MAIN_RUN_ID = 33_625_137_601

MATERIALIZATION_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v61-ibex-pr974-command-image-v1"
)
SOURCE_ROOT = Path("/data2/jiadongzhu/Agent/datasets/hwe-ibex-pr974-harness-v60-fresh-v1")
TOKENIZER_ROOT = Path("/data2/jiadongzhu/Agent/datasets/Qwen3.5-9B-tokenizer-v1")
BASE_MODEL_LOCK = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "openhands-hwe-v58-ibex-pr54-provider-canary-inputs-v1/base-model-lock.json"
)
COMMAND_LOCK_FILE_SHA256 = "e44f60ce7834b0c04fea07f91cf191845fc07eb69016d9da7db8e5bf3641492d"
SECURITY_SCAN_FILE_SHA256 = "642ce55852ab4048eebcf2c7fc78cf264815c2a98254503c2f67612006bf4a5a"
ZERO_PROVIDER_RESULT_SHA256 = "0cf950ac6f42f30c8fc658c553aeb955674dac9c8c23b94ba9ef117466cf27d8"
SOURCE_IMAGE_LOCK_SHA256 = "333372b2c47577493d9caea69eb44f7585512cce11233d8ba1a3fab9310e84ad"
BASE_MODEL_LOCK_SHA256 = "cf7c9873fda3df377d6c46096b57f8aa1b9b13c4ab6f7d2c19739c2082b0e111"
MODEL_SNAPSHOT_HASH = "fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156"
TOKENIZER_HASH = "440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e"
COMMAND_EXECUTION_BACKEND: Literal["episode_container_exec_v1"] = "episode_container_exec_v1"
MAX_JSON_BYTES = 64 * 1024 * 1024
REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_deepseek_harness_v62_ibex_pr974_provider_canary_v1.json",
    "docs/audits/2026-09-02_deepseek-harness-v61-ibex-pr974-zero-provider-materialization.md",
    "docs/audits/2026-09-02_deepseek-harness-v62-ibex-pr974-provider-canary-authorization.md",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/agent.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/broker.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/config.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/helper.py",
    "integrations/verigym-deepseek-harness/src/verigym_deepseek_harness/runtime/hwe-tools.mjs",
    "scripts/collect_ibex_hwe_deepseek_harness_v62_provider_canary.py",
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
        != "fe8cb6e6b8ea27a0a443322107ad0163fc315c66f899b9cb56ceb9c820000284"
        or binding.get("source_hash")
        != "0bb584274d5584dca886a00e377920e27f4c971f175487c9baa1b36fcb9b5221"
        or binding.get("command_image_lock_hash")
        != "ce72dd5277f44407a2c2b64bc2b3989e30625cd2727c2d87b7b8829dc9e4fd22"
        or binding.get("command_image")
        != "sha256:d888a3faa8fe5d6cf3717f8488a96e5a8ce5d3122d0da321dcb3fbafe8ae6bab"
        or binding.get("verifier_image")
        != "sha256:ac668cbaf8b16e2804adf222834a06965282841bc30927fe5f98e3a2239b431b"
        or binding.get("security_scan_id")
        != "7b0bccf29d490b1b22a104c0ba29a2df34486484644ce6d17e15635db86690dc"
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
            "invoke_provider_for_pr974_once": True,
            "retry_pr974": False,
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
        raise ConfigurationError("DeepSeek Harness v62 authorization identity changed")
    return {**validated, "authorization_hash": expected_hash}


def materialize_exact_64k_records(
    transcript: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    tokenizer: QwenDecisionExampleTokenizer,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep v3 decisions byte-for-byte while adding exact 64K token receipts."""

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
            raise ValueError("DeepSeek Harness v62 decision exceeds exact 64K")
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
        dry_run = dry_run_decision_record_v4(record, tokenizer=tokenizer)
        records.append(record)
        dry_runs.append(dry_run)
    if not records:
        raise ValueError("DeepSeek Harness v62 resolved trajectory has no supervised decisions")
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
        raise ConfigurationError("DeepSeek Harness v62 base-model lock changed")
    model_lock = _base_model_lock(base_model_lock_path, tokenizer_root)
    if (
        model_lock["snapshot_hash"] != MODEL_SNAPSHOT_HASH
        or model_lock["tokenizer_hash"] != TOKENIZER_HASH
    ):
        raise ConfigurationError("DeepSeek Harness v62 tokenizer binding changed")
    tokenizer, transformers_version = _load_tokenizer(tokenizer_root)
    exact_tokenizer = QwenDecisionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_root)
    if exact_tokenizer.tokenizer_hash != TOKENIZER_HASH:
        raise ConfigurationError("DeepSeek Harness v62 exact tokenizer identity changed")

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

    running = {**base_report, "status": "provider_canary_running", "provider_episode_started": True}
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
        return _stop(
            root,
            running,
            "stopped_post_provider_infrastructure_or_security_invalid",
            f"provider_episode:{type(exc).__name__}",
            provider_started=True,
        )
    atomic_dump_json(root / "attempt.json", attempt)
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
        raise ConfigurationError("DeepSeek Harness v62 task/source binding changed")
    episode_id = "training-ibex-pr974-s499-v62"
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
    infrastructure_valid = not _infrastructure_invalid(scorecard)
    run_dir = Path(result.run_dir).resolve(strict=True)
    if run_dir.is_symlink() or not run_dir.is_relative_to((root / "runs").resolve()):
        raise ConfigurationError("DeepSeek Harness v62 run directory escaped output")
    evidence_root = run_dir / "artifacts/deepseek_harness"
    evidence: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None
    protocol_valid = False
    if infrastructure_valid:
        try:
            evidence = _load_json(evidence_root / "collection_evidence.json")
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
        report_id=f"deepseek-harness-hwe-v62-{episode_id}",
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
        "format_id": "verigym_deepseek_harness_hwe_v62_qwen_loader_dry_run_v1",
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
    runtime_user = f"{os.getuid()}:{os.getgid()}"
    labels = {
        "org.verigym.runtime.role": "hwe-ibex-command",
        "org.verigym.collection.profile": lock.collection_profile_id,
        "org.verigym.tool.contract": lock.tool_contract_id,
        "org.verigym.command.protocol": lock.command_protocol,
        "org.verigym.command.rg.version": lock.rg_version,
        "org.verigym.command.rg.sha256": lock.rg_sha256,
        "org.verigym.command.rg.release_archive.sha256": lock.rg_release_archive_sha256,
        "org.verigym.hwe.task_id": lock.task_id,
        "org.verigym.ibex.verifier_base_image_id": lock.verifier_base_image_id,
        "org.verigym.ibex.toolchain.profile": "verilator",
        "org.verigym.codex.present": "absent",
        "org.verigym.provider_credentials": "absent",
        "org.verigym.hidden_assets": "absent",
        "org.verigym.reference_patch": "absent",
        "org.verigym.verifier_payload": "absent",
    }
    return DockerRuntimeConfig(
        image=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        expected_image_id=HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        pull_policy="never",
        network_mode="none",
        run_as_user=runtime_user,
        memory_bytes=16 * 1024**3,
        cpus=4,
        pids_limit=4096,
        max_command_time_s=900,
        command_image=DockerCommandImageRuntimeConfig(
            image=lock.derived_command_image_id,
            expected_image_id=lock.derived_command_image_id,
            expected_rg_version=lock.rg_version,
            expected_rg_sha256=lock.rg_sha256,
            protocol=lock.command_protocol,
            execution_backend=COMMAND_EXECUTION_BACKEND,
            required_image_labels=labels,
            run_as_user=runtime_user,
            memory_bytes=16 * 1024**3,
            cpus=4,
            pids_limit=4096,
            max_command_time_s=3600,
            max_output_bytes=32 * 1024 * 1024,
        ),
    )


def _zero_call_preflight(root: Path, lock: HweCommandImageLock) -> None:
    completed: list[str] = []
    stage = "runtime"
    try:
        runtime = DockerRuntime(_runtime_config(lock))
        try:
            runtime.prepare("deepseek-harness-v62-preflight-pr974")
        finally:
            runtime.close()
        completed.append(stage)
        stage = "harness_initialize"
        _zero_call_conformance()
        completed.append(stage)
    except Exception as exc:
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v62_zero_call_preflight_v1",
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
        "format_id": "verigym_deepseek_harness_hwe_v62_zero_call_preflight_v1",
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
    lock_path = root / "image-locks/pr-974.json"
    scan_path = root / "security-scans/pr-974.json"
    zero_path = root / "zero-provider-result.json"
    expected = (
        (lock_path, COMMAND_LOCK_FILE_SHA256),
        (scan_path, SECURITY_SCAN_FILE_SHA256),
        (zero_path, ZERO_PROVIDER_RESULT_SHA256),
    )
    if any(
        path.is_symlink() or hash_bytes(path.read_bytes()) != digest for path, digest in expected
    ):
        raise ConfigurationError("DeepSeek Harness v62 zero-provider evidence changed")
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
        or zero.get("result_hash")
        != "81a41375faa6a1fce41b9fd3b5f0e2d98ead2ff961b96a1d8b4330115437574a"
        or zero.get("base_failed") is not True
        or zero.get("base_infrastructure_error") is not False
        or zero.get("reference_passed") is not True
        or zero.get("model_process_count") != 0
        or zero.get("provider_calls") != 0
    ):
        raise ConfigurationError("DeepSeek Harness v62 materialization binding changed")
    observed = subprocess.run(
        ["docker", "image", "inspect", lock.derived_command_image_id, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if observed != lock.derived_command_image_id:
        raise ConfigurationError("DeepSeek Harness v62 command image is unavailable")
    return lock


def _validated_source(root: Path) -> None:
    lock = root / "image-lock.json"
    if lock.is_symlink() or hash_bytes(lock.read_bytes()) != SOURCE_IMAGE_LOCK_SHA256:
        raise ConfigurationError("DeepSeek Harness v62 source lock changed")


def _validate_collection_evidence(value: dict[str, Any]) -> None:
    broker = value.get("broker")
    progress = value.get("progress_receipt")
    if (
        value.get("model") != DEEPSEEK_HARNESS_MODEL
        or value.get("thinking") != "disabled"
        or value.get("temperature") != 0
        or value.get("max_output_tokens") != 2048
        or value.get("provider_request_retries") != 0
        or value.get("whole_episode_retries") != 0
        or value.get("max_provider_calls") != MAX_PROVIDER_CALLS
        or value.get("max_provider_tokens") != MAX_PROVIDER_TOKENS
        or value.get("provider_budget_valid") is not True
        or not isinstance(value.get("observed_provider_calls"), int)
        or value["observed_provider_calls"] > MAX_PROVIDER_CALLS
        or not isinstance(value.get("observed_provider_total_tokens"), int)
        or value["observed_provider_total_tokens"] > MAX_PROVIDER_TOKENS
        or not isinstance(broker, dict)
        or broker.get("infrastructure_failure") is not None
        or not isinstance(progress, dict)
        or progress.get("progress_checkpoint_sha256")
        != "7b51021e80041b03d4b4f37bf1fda9dae7b766573900889d5abaefd1e6d7ba34"
        or value.get("raw_provider_events_exported") is not False
        or value.get("raw_observations_exported") is not False
        or value.get("credential_values_exported") is not False
    ):
        raise ConfigurationError("DeepSeek Harness v62 collection evidence changed")


def _service() -> VeriGym:
    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "deepseek-harness-hwe-agent-v4" not in registries.agents.names():
        from verigym_deepseek_harness import DeepSeekHarnessHweAgentV4Adapter

        registries.agents.register(DeepSeekHarnessHweAgentV4Adapter())
    return VeriGym(registries)


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if campaign_id != CAMPAIGN_ID:
        raise ConfigurationError("DeepSeek Harness v62 campaign identity changed")
    if not os.environ.get(API_KEY_ENV) or not os.environ.get(BASE_URL_ENV):
        raise ConfigurationError("DeepSeek Harness v62 provider environment is incomplete")
    if VERIGYM_DEEPSEEK_HARNESS_VERSION != "0.3.0":
        raise ConfigurationError("DeepSeek Harness v62 integration version changed")


def _provider_values() -> tuple[str, str]:
    return os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV]


def _scan_provider_values(root: Path) -> dict[str, Any]:
    values = tuple(value.encode() for value in _provider_values())
    files = 0
    bytes_scanned = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("DeepSeek Harness v62 artifact contains a symlink")
        if not path.is_file():
            continue
        payload = path.read_bytes()
        files += 1
        bytes_scanned += len(payload)
        if any(value in payload for value in values):
            raise ConfigurationError("provider value reached DeepSeek Harness v62 artifacts")
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
            raise ConfigurationError("DeepSeek Harness v62 required merged path changed")
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
        raise ConfigurationError("DeepSeek Harness v62 requires clean merged origin/main")
    return head


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"DeepSeek Harness v62 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_dir():
        raise ConfigurationError(f"DeepSeek Harness v62 {label} identity changed")
    return resolved


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"DeepSeek Harness v62 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_file():
        raise ConfigurationError(f"DeepSeek Harness v62 {label} identity changed")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ConfigurationError(f"unsafe DeepSeek Harness v62 JSON input: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"DeepSeek Harness v62 JSON is not an object: {path.name}")
    return value


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("DeepSeek Harness v62 output must not already exist")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


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


def _seal_report(value: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(value)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_progress(root: Path, value: dict[str, Any]) -> None:
    atomic_dump_json(root / "canary-progress.json", _seal_report(value))


def _stop(
    root: Path,
    report: dict[str, Any],
    status: str,
    reason: str,
    *,
    provider_started: bool,
) -> dict[str, Any]:
    final = _seal_report(
        {
            **report,
            "status": status,
            "provider_episode_started": provider_started,
            "canary_passed": False,
            "trajectory_collected": False,
            "exact_64k_eligible": False,
            "task_consumed": provider_started,
            "failure_reason": reason,
            "raw_exception_persisted": False,
            "provider_episode_count": 1 if provider_started else 0,
            "provider_call_count": None if provider_started else 0,
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def main() -> int:
    report = collect(_parser().parse_args())
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("canary_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
