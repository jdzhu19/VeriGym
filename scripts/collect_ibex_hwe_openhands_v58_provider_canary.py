#!/usr/bin/env python3
"""Run the authorized single-task Ibex PR-54 OpenHands v23 provider canary once."""

from __future__ import annotations

import argparse
import copy
import importlib
import importlib.metadata
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_agent import _validated_hwe_runtime_bridge
from verigym_openhands.hwe_command_runtime import build_hwe_command_runtime_config
from verigym_openhands.hwe_v19_canary_runtime import (
    OPENHANDS_V19_CANARY_API_KEY_ENV,
    OPENHANDS_V19_CANARY_BASE_URL_ENV,
    OPENHANDS_V19_CANARY_LITELLM_VERSION,
    OPENHANDS_V19_CANARY_MODEL,
    OPENHANDS_V19_CANARY_SDK_VERSION,
    OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
    OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
)
from verigym_openhands.hwe_v23 import (
    classify_v23_campaign_result,
    seal_v23_decision_receipt,
    seal_v23_trajectory_receipt,
)
from verigym_openhands.hwe_v58_ibex_canary_runtime import (
    OPENHANDS_V58_AGENT_VERSION_ID,
    OPENHANDS_V58_AUTHORIZATION_FORMAT,
    OPENHANDS_V58_CAMPAIGN_ID,
    OPENHANDS_V58_COMMAND_EXECUTION_BACKEND,
    OPENHANDS_V58_NUMPY_VERSION,
    OPENHANDS_V58_OPT_IN_ENV,
    OPENHANDS_V58_PILLOW_VERSION,
    OPENHANDS_V58_REPORT_FORMAT,
    OPENHANDS_V58_SAMPLE_INDEX,
    OPENHANDS_V58_SEED,
    OPENHANDS_V58_TASK_ID,
    build_v58_agent_options,
    build_v58_agent_version,
    validate_v58_authorization,
    validate_v58_runtime_evidence,
)
from verigym_openhands.trajectory import (
    OpenHandsTrajectoryError,
    materialize_openhands_decisions,
    validate_openhands_training_trajectory,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.hwe.qwen_action_tokenizer import QwenDecisionExampleTokenizer
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_base_model_lock = _collection._base_model_lock
_infrastructure_invalid = _collection._infrastructure_invalid
_load_tokenizer = _collection._load_tokenizer

_QUALIFICATION_MERGE_COMMIT = "0a71773a3acb52414739bebbb6e4e73a7d2ab37c"
_QUALIFICATION_MAIN_RUN_ID = 33_618_065_213
_AUTHORIZATION_HASH = "5e9ef47d1ff1f145d0eefb4c3587dd28d9f58e5f916b84ce7f0965a8ec547841"
_MATERIALIZATION_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/openhands-hwe-ibex-pr54-command-image-v1"
)
_SOURCE_ROOT = Path("/data2/jiadongzhu/Agent/datasets/hwe-ibex-pr54-fresh-v1")
_TOKENIZER_ROOT = Path("/data2/jiadongzhu/Agent/datasets/Qwen3.5-9B-tokenizer-v1")
_BASE_MODEL_LOCK = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "openhands-hwe-v58-ibex-pr54-provider-canary-inputs-v1/base-model-lock.json"
)
_COMMAND_LOCK_FILE_SHA256 = "272d81368a14d2eecd208a3aa26140f194e935441ad1d2f51265a4da4a7016f2"
_SECURITY_SCAN_FILE_SHA256 = "16d72b471efbd71aa901b485956ef90d1f0c039b2b9d4e34998f3142976aa445"
_ZERO_PROVIDER_RESULT_SHA256 = "834611cf73128c05cf87c1df372806845c9b0c74cb88d8ebedd3d45d6c871500"
_SOURCE_LOCK_SHA256 = "7cf1a6fc213fd49d39f729da39b8cff0282adb71bdad393a2c7b048f8f5d2a8e"
_BASE_MODEL_LOCK_SHA256 = "cf7c9873fda3df377d6c46096b57f8aa1b9b13c4ab6f7d2c19739c2082b0e111"
_MODEL_SNAPSHOT_HASH = "fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156"
_TOKENIZER_HASH = "440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e"
_BROKER_ROOT_ENV = "VERIGYM_OPENHANDS_BROKER_ROOT"
_MCP_PYTHONPATH_ENV = "VERIGYM_OPENHANDS_MCP_PYTHONPATH"
_BROKER_ROOT = "/data2/jiadongzhu/Agent/.verigym-tmp/oh-v58"
_MCP_PYTHONPATH_ENTRIES = (
    "/data2/jiadongzhu/Agent/VeriGym/src",
    "/data2/jiadongzhu/Agent/VeriGym/integrations/verigym-hwe-bench/src",
    "/data2/jiadongzhu/Agent/VeriGym/integrations/verigym-openhands/src",
    "/data2/jiadongzhu/Agent/VeriGym/integrations/verigym-deepseek-harness/src",
)
_MAX_JSON_BYTES = 64 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v58_ibex_pr54_provider_canary_v1.json",
    "docs/audits/2026-09-02_openhands-ibex-pr54-zero-provider-materialization.md",
    "docs/audits/2026-09-02_openhands-v58-ibex-pr54-provider-canary-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_agent.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_command_runtime.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v23.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v23_protocol.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v58_ibex_canary_runtime.py",
    "integrations/verigym-openhands/src/verigym_openhands/trajectory.py",
    "scripts/collect_ibex_hwe_openhands_v58_provider_canary.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--materialization-root", type=Path, default=_MATERIALIZATION_ROOT)
    parser.add_argument("--source", type=Path, default=_SOURCE_ROOT)
    parser.add_argument("--tokenizer-root", type=Path, default=_TOKENIZER_ROOT)
    parser.add_argument("--base-model-lock", type=Path, default=_BASE_MODEL_LOCK)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=OPENHANDS_V58_CAMPAIGN_ID)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute exactly one fresh PR-54 provider episode after a zero-call preflight."""

    authorization = _validated_authorization(_load_json(arguments.authorization))
    _require_opt_in(arguments.campaign_id)
    source_commit = _merged_source_commit()
    materialization = _exact_directory(
        arguments.materialization_root, _MATERIALIZATION_ROOT, "materialization"
    )
    source_root = _exact_directory(arguments.source, _SOURCE_ROOT, "source")
    tokenizer_root = _exact_directory(arguments.tokenizer_root, _TOKENIZER_ROOT, "tokenizer")
    base_model_lock_path = _exact_file(
        arguments.base_model_lock, _BASE_MODEL_LOCK, "base-model lock"
    )
    lock = _materialized_lock(materialization, authorization)
    _validated_source(source_root)
    if hash_bytes(base_model_lock_path.read_bytes()) != _BASE_MODEL_LOCK_SHA256:
        raise ConfigurationError("OpenHands v58 base-model lock changed")
    model_lock = _base_model_lock(base_model_lock_path, tokenizer_root)
    if (
        model_lock["snapshot_hash"] != _MODEL_SNAPSHOT_HASH
        or model_lock["tokenizer_hash"] != _TOKENIZER_HASH
    ):
        raise ConfigurationError("OpenHands v58 Qwen tokenizer identity changed")
    tokenizer, transformers_version = _load_tokenizer(tokenizer_root)
    exact_tokenizer = QwenDecisionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_root)
    if exact_tokenizer.tokenizer_hash != _TOKENIZER_HASH:
        raise ConfigurationError("OpenHands v58 exact tokenizer hash changed")

    agent_version = build_v58_agent_version(
        authorization=authorization,
        source_commit=source_commit,
        command_image_lock=lock,
    )
    build_v58_agent_options(agent_version=agent_version)
    root = _new_output(arguments.output)
    for directory in ("runs", "security-scans", "trajectory-records"):
        (root / directory).mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", agent_version)
    atomic_dump_json(root / "authorization-receipt.json", _authorization_receipt(authorization))
    base_report: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V58_REPORT_FORMAT,
        "identity": OPENHANDS_V58_CAMPAIGN_ID,
        "authorization_hash": authorization["authorization_hash"],
        "campaign_id": arguments.campaign_id,
        "status": "canary_running",
        "source_commit": source_commit,
        "qualification_merge_commit": _QUALIFICATION_MERGE_COMMIT,
        "qualification_post_merge_main_run_id": _QUALIFICATION_MAIN_RUN_ID,
        "task_id": OPENHANDS_V58_TASK_ID,
        "task_hash": authorization["task_binding"]["task_hash"],
        "source_hash": authorization["task_binding"]["source_hash"],
        "command_image_lock_hash": lock.lock_hash,
        "security_scan_id": lock.security_scan_id,
        "model_transport_id": OPENHANDS_V19_CANARY_MODEL,
        "agent_version_id": OPENHANDS_V58_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers_version": transformers_version,
        "numpy_version": OPENHANDS_V58_NUMPY_VERSION,
        "pillow_version": OPENHANDS_V58_PILLOW_VERSION,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "seed": OPENHANDS_V58_SEED,
        "sample_index": OPENHANDS_V58_SAMPLE_INDEX,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "provider_episode_started": False,
        "attempt": None,
        "heldout_task_ids_loaded": [],
        "retry_authorized": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    _write_progress(root, base_report)
    try:
        _zero_call_preflight(root, lock, source_root)
    except Exception as exc:
        return _stop(
            root,
            base_report,
            status="stopped_pre_provider_infrastructure_invalid",
            reason=f"zero_call_preflight:{type(exc).__name__}",
            provider_episode_started=False,
        )

    running = {**base_report, "provider_episode_started": True}
    _write_progress(root, running)
    try:
        attempt = _run_episode(
            service=_service(),
            authorization=authorization,
            source_root=source_root,
            lock=lock,
            agent_version=agent_version,
            tokenizer=exact_tokenizer,
            root=root,
        )
    except Exception as exc:
        return _stop(
            root,
            running,
            status="stopped_post_provider_infrastructure_or_security_invalid",
            reason=f"provider_episode:{type(exc).__name__}",
            provider_episode_started=True,
        )
    atomic_dump_json(root / "attempt.json", attempt)
    stop_kind = _attempt_stop_kind(attempt)
    passed = stop_kind is None
    final = _seal_report(
        {
            **running,
            "status": (
                "canary_passed_pending_formal_materialization" if passed else "canary_failed_closed"
            ),
            "attempt": attempt,
            "canary_passed": passed,
            "trajectory_collected": attempt.get("trajectory_receipt") is not None,
            "exact_64k_eligible": attempt.get("token_receipt") is not None,
            "task_consumed": True,
            "task_disposition": (
                "import_canary_without_reexecution" if passed else "frozen_after_failed_canary"
            ),
            "failure_reason": stop_kind,
            **_observed_provider_accounting(root, attempt),
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
    agent_version: Any,
    tokenizer: QwenDecisionExampleTokenizer,
    root: Path,
) -> dict[str, Any]:
    binding = authorization["task_binding"]
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(OPENHANDS_V58_TASK_ID, source)
    snapshot = suite.source_snapshot()
    if (
        snapshot is None
        or content_hash(task) != binding["task_hash"]
        or task.source.content_hash != binding["source_hash"]
    ):
        raise ConfigurationError("OpenHands v58 loaded task/source binding changed")
    episode_id = "training-ibex-pr54-s498-v58"
    started = time.monotonic()
    result = service.run(
        RunConfig(
            task_id=OPENHANDS_V58_TASK_ID,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=binding["task_hash"],
            expected_source_hash=binding["source_hash"],
            mode=InteractionMode.AGENT,
            agent="openhands-hwe-agent",
            agent_options=build_v58_agent_options(agent_version=agent_version),
            runtime="docker",
            docker_config=_runtime_config(lock),
            seed=OPENHANDS_V58_SEED,
            sample_index=OPENHANDS_V58_SAMPLE_INDEX,
            output=root / "runs",
            run_id=episode_id,
            experiment_id=OPENHANDS_V58_CAMPAIGN_ID,
            plan_item_id=episode_id,
            system_id=OPENHANDS_V58_AGENT_VERSION_ID,
            base_seed=OPENHANDS_V58_SEED,
        )
    )
    scorecard = result.scorecard.model_dump(mode="json")
    infrastructure_valid = not _infrastructure_invalid(result.scorecard)
    run_directory = Path(result.run_dir).resolve(strict=True)
    if not run_directory.is_relative_to((root / "runs").resolve()) or run_directory.is_symlink():
        raise ConfigurationError("OpenHands v58 run directory escaped its output root")
    evidence = run_directory / "artifacts" / "openhands_sdk"
    if not infrastructure_valid:
        campaign = classify_v23_campaign_result(
            scorecard,
            agent_protocol_valid=False,
            trajectory_eligible=False,
            infrastructure_valid=False,
            security_valid=False,
            admit_to_sft=False,
        )
        return _empty_attempt(scorecard, campaign, time.monotonic() - started)
    _validate_runtime_manifest(result.manifest.environment_summary, lock)

    protocol: dict[str, Any] | None = None
    agent_protocol_valid = False
    try:
        accounting = ExternalAgentAccounting.model_validate(
            _load_json(evidence / "accounting.json")
        )
        protocol = validate_v58_runtime_evidence(
            broker=_load_json(evidence / "broker.json"),
            summary=_load_json(evidence / "summary.json"),
            accounting=accounting,
            protocol_receipt=_load_json(evidence / "v23-protocol-receipt.json"),
        )
        agent_protocol_valid = True
    except (KeyError, OSError, ValueError, ConfigurationError):
        pass

    trajectory: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []
    trajectory_eligible = False
    if agent_protocol_valid:
        try:
            trajectory = validate_openhands_training_trajectory(
                _load_json(evidence / "training-trajectory.json")
            )
            reproducibility = scorecard.get("reproducibility")
            if (
                trajectory["task_id"] != OPENHANDS_V58_TASK_ID
                or trajectory["verifier_resolved"] is not True
                or trajectory["sft_eligible"] is not True
                or not isinstance(reproducibility, dict)
            ):
                raise OpenHandsTrajectoryError("OpenHands v58 trajectory binding changed")
            records = materialize_openhands_decisions(
                trajectory,
                binding={
                    "sample_id": content_hash(
                        {
                            "authorization_hash": authorization["authorization_hash"],
                            "campaign_id": OPENHANDS_V58_CAMPAIGN_ID,
                            "episode_id": episode_id,
                            "scorecard_hash": content_hash(scorecard),
                        }
                    ),
                    "task_hash": binding["task_hash"],
                    "source_hash": binding["source_hash"],
                    "candidate_hash": reproducibility["candidate_hash"],
                    "verifier_hash": reproducibility["verifier_hash"],
                },
                tokenizer=tokenizer,
            )
            trajectory_eligible = bool(records)
        except (KeyError, OSError, ValueError, ConfigurationError, OpenHandsTrajectoryError):
            trajectory = None
            records = []

    record_dir: Path | None = None
    record_path: Path | None = None
    if trajectory_eligible:
        record_dir = root / "trajectory-records" / episode_id
        record_dir.mkdir(mode=0o700)
        record_path = record_dir / "decisions.jsonl"
        _atomic_jsonl(record_path, records)
    scan_roots = [evidence]
    private_audit = run_directory / "private-audit"
    if private_audit.is_dir() and not private_audit.is_symlink():
        scan_roots.append(private_audit)
    if record_dir is not None:
        scan_roots.append(record_dir)
    security_report = scan_artifact_roots(
        scan_roots,
        report_id=f"openhands-hwe-v58-{episode_id}",
        proxy_values=_provider_values(),
        forbidden_host_roots=(str(source_root), str(Path.cwd().resolve())),
    )
    atomic_dump_json(root / "security-scans" / f"{episode_id}.json", security_report)
    security_valid = security_report.gate == "pass"
    if security_valid:
        require_security_scan_pass(security_report)
    try:
        provider_value_scan = _scan_provider_values(root)
    except ConfigurationError:
        security_valid = False
        provider_value_scan = {
            "passed": False,
            "provider_value_count_scanned": 2,
            "provider_value_hit_count": None,
            "provider_values_persisted_or_hashed": None,
        }
    campaign = classify_v23_campaign_result(
        scorecard,
        agent_protocol_valid=agent_protocol_valid,
        trajectory_eligible=trajectory_eligible,
        infrastructure_valid=infrastructure_valid,
        security_valid=security_valid,
        admit_to_sft=trajectory_eligible,
    )
    trajectory_receipt: dict[str, Any] | None = None
    decision_receipt: dict[str, Any] | None = None
    token_receipt: dict[str, Any] | None = None
    if campaign["sft_admitted"] is True:
        assert protocol is not None and trajectory is not None and record_dir is not None
        trajectory_receipt = seal_v23_trajectory_receipt(
            trajectory=trajectory,
            protocol_receipt=protocol,
            campaign_result=campaign,
        )
        decision_receipt = seal_v23_decision_receipt(
            records=records,
            trajectory_receipt=trajectory_receipt,
        )
        token_base = {
            "schema_version": "1.0",
            "format_id": "verigym_openhands_hwe_v58_exact_64k_token_receipt_v1",
            "episode_id": episode_id,
            "transcript_hash": trajectory["transcript_hash"],
            "decision_receipt_hash": decision_receipt["receipt_hash"],
            "decision_record_count": len(records),
            "maximum_token_count": max(int(item["token_count"]) for item in records),
            "max_length": 65_536,
            "truncation": "error",
            "truncation_applied": False,
            "decision_only_loss_mask": True,
            "public_rationale_supervised": True,
            "content_only_recovery_supervised": False,
            "failed_tool_decisions_supervised": False,
            "sibling_targets_split": False,
        }
        token_receipt = {**token_base, "receipt_hash": content_hash(token_base)}
        atomic_dump_json(record_dir / "trajectory-receipt.json", trajectory_receipt)
        atomic_dump_json(record_dir / "decision-receipt.json", decision_receipt)
        atomic_dump_json(record_dir / "token-receipt.json", token_receipt)
        provider_value_scan = _scan_provider_values(root)
    return {
        "episode_id": episode_id,
        "role": "training",
        "task_id": OPENHANDS_V58_TASK_ID,
        "seed": OPENHANDS_V58_SEED,
        "sample_index": OPENHANDS_V58_SAMPLE_INDEX,
        "run_hash": content_hash({"run_id": episode_id, "scorecard": scorecard}),
        "wall_seconds": time.monotonic() - started,
        "result": campaign,
        "runtime_command_image": lock.derived_command_image_id,
        "command_execution_backend": OPENHANDS_V58_COMMAND_EXECUTION_BACKEND,
        "security_scan_hash": security_report.report_hash,
        "provider_value_scan": provider_value_scan,
        "protocol_receipt": protocol,
        "trajectory_receipt": trajectory_receipt,
        "decision_receipt": decision_receipt,
        "token_receipt": token_receipt,
        "trajectory_file_sha256": (
            hash_bytes((evidence / "training-trajectory.json").read_bytes())
            if trajectory is not None
            else None
        ),
        "decision_records_file": (
            record_path.relative_to(root).as_posix() if record_path is not None else None
        ),
        "decision_records_file_sha256": (
            hash_bytes(record_path.read_bytes()) if record_path is not None else None
        ),
        "decision_record_count": len(records) if trajectory_receipt is not None else 0,
        "maximum_decision_tokens": (
            max(int(item["token_count"]) for item in records)
            if trajectory_receipt is not None
            else None
        ),
        "exact_64k_eligible": token_receipt is not None,
        "decision_only_loss_mask": token_receipt is not None,
        "public_rationale_supervised": token_receipt is not None,
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
        "sibling_targets_split": False,
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _empty_attempt(
    scorecard: dict[str, Any], campaign: dict[str, Any], wall_seconds: float
) -> dict[str, Any]:
    return {
        "episode_id": "training-ibex-pr54-s498-v58",
        "role": "training",
        "task_id": OPENHANDS_V58_TASK_ID,
        "seed": OPENHANDS_V58_SEED,
        "sample_index": OPENHANDS_V58_SAMPLE_INDEX,
        "run_hash": content_hash({"run_id": "training-ibex-pr54-s498-v58", "scorecard": scorecard}),
        "wall_seconds": wall_seconds,
        "result": campaign,
        "runtime_command_image": None,
        "command_execution_backend": OPENHANDS_V58_COMMAND_EXECUTION_BACKEND,
        "security_scan_hash": None,
        "provider_value_scan": None,
        "protocol_receipt": None,
        "trajectory_receipt": None,
        "decision_receipt": None,
        "token_receipt": None,
        "trajectory_file_sha256": None,
        "decision_records_file": None,
        "decision_records_file_sha256": None,
        "decision_record_count": 0,
        "maximum_decision_tokens": None,
        "exact_64k_eligible": False,
        "decision_only_loss_mask": False,
        "public_rationale_supervised": False,
        "content_only_recovery_supervised": False,
        "failed_tool_decisions_supervised": False,
        "sibling_targets_split": False,
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _attempt_stop_kind(attempt: dict[str, Any]) -> str | None:
    result = attempt.get("result")
    if not isinstance(result, dict):
        raise ConfigurationError("OpenHands v58 attempt lacks its six-plane result")
    if result.get("infrastructure_valid") is not True or result.get("security_valid") is not True:
        return "infrastructure_or_security_invalid"
    if any(
        result.get(plane) is not True
        for plane in (
            "benchmark_verifier_pass",
            "agent_protocol_valid",
            "trajectory_eligible",
            "infrastructure_valid",
            "security_valid",
            "sft_admitted",
        )
    ):
        return "six_plane_gate_failed"
    if (
        attempt.get("exact_64k_eligible") is not True
        or attempt.get("decision_only_loss_mask") is not True
        or attempt.get("public_rationale_supervised") is not True
        or attempt.get("content_only_recovery_supervised") is not False
        or attempt.get("failed_tool_decisions_supervised") is not False
        or attempt.get("sibling_targets_split") is not False
        or attempt.get("truncation_applied") is not False
        or not isinstance(attempt.get("trajectory_receipt"), dict)
        or not isinstance(attempt.get("decision_receipt"), dict)
        or not isinstance(attempt.get("token_receipt"), dict)
    ):
        return "six_plane_gate_failed"
    return None


def _materialized_lock(root: Path, authorization: dict[str, Any]) -> HweCommandImageLock:
    lock_path = root / "image-locks/pr-54.json"
    scan_path = root / "security-scans/pr-54.json"
    zero_path = root / "zero-provider-result.json"
    expected = (
        (lock_path, _COMMAND_LOCK_FILE_SHA256),
        (scan_path, _SECURITY_SCAN_FILE_SHA256),
        (zero_path, _ZERO_PROVIDER_RESULT_SHA256),
    )
    if any(
        path.is_symlink() or hash_bytes(path.read_bytes()) != digest for path, digest in expected
    ):
        raise ConfigurationError("OpenHands v58 zero-provider evidence changed")
    lock = HweCommandImageLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
    scan = _load_json(scan_path)
    binding = authorization["task_binding"]
    if (
        lock.task_id != OPENHANDS_V58_TASK_ID
        or lock.lock_hash != binding["command_image_lock_hash"]
        or lock.derived_command_image_id != binding["command_image"]
        or lock.verifier_base_image_id != binding["verifier_image"]
        or lock.security_scan_id != binding["security_scan_id"]
        or lock.source_whiteout_path != "/home/ibex"
        or scan.get("scan_passed") is not True
        or scan.get("secrets_detected") is not False
        or scan.get("security_scan_id") != lock.security_scan_id
        or not isinstance(scan.get("checks"), dict)
        or not all(value is True for value in scan["checks"].values())
    ):
        raise ConfigurationError("OpenHands v58 materialized image binding changed")
    observed = subprocess.run(
        ["docker", "image", "inspect", lock.derived_command_image_id, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if observed != lock.derived_command_image_id:
        raise ConfigurationError("OpenHands v58 command image is unavailable")
    return lock


def _validated_source(root: Path) -> None:
    lock = root / "image-lock.json"
    if lock.is_symlink() or hash_bytes(lock.read_bytes()) != _SOURCE_LOCK_SHA256:
        raise ConfigurationError("OpenHands v58 source image lock changed")


def _runtime_config(lock: HweCommandImageLock) -> DockerRuntimeConfig:
    return build_hwe_command_runtime_config(
        lock,
        runtime_user=f"{os.getuid()}:{os.getgid()}",
        execution_backend=OPENHANDS_V58_COMMAND_EXECUTION_BACKEND,
    )


def _zero_call_preflight(root: Path, lock: HweCommandImageLock, source_root: Path) -> None:
    completed: list[str] = []
    stage = "control_plane"
    try:
        _validated_control_plane_environment()
        completed.append(stage)
        stage = "command_image"
        runtime = DockerRuntime(_runtime_config(lock))
        try:
            runtime.prepare("openhands-v58-preflight-pr54")
            _validate_runtime_manifest(runtime.environment_summary(), lock)
            completed.append(stage)
            stage = "adapter_start"
            session = runtime.create_session(
                SessionSpec(source_dir=str(source_root), label="agent")
            )
            try:
                bridge = RuntimeExternalAgentBridge(
                    session=session,
                    artifact_root=root / "preflight-adapter-artifacts/pr-54",
                    isolation_level="docker_standard",
                    policy=WorkspacePolicy(editable_globs=("**/*",)),
                    trace=TraceWriter(
                        root / "preflight-traces/pr-54.jsonl", "openhands-v58-preflight-pr54"
                    ),
                )
                if _validated_hwe_runtime_bridge(bridge) is not bridge:
                    raise ConfigurationError("OpenHands v58 adapter-start bridge changed")
            finally:
                session.close()
        finally:
            runtime.close()
        completed.append(stage)
    except Exception as exc:
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_openhands_hwe_v58_zero_call_preflight_v1",
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
        "format_id": "verigym_openhands_hwe_v58_zero_call_preflight_v1",
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


def _validate_runtime_manifest(value: dict[str, Any], lock: HweCommandImageLock) -> None:
    roles = value.get("docker_role_images")
    command = roles.get("command") if isinstance(roles, dict) else None
    if (
        not isinstance(roles, dict)
        or roles.get("external_agent") is not None
        or not isinstance(command, dict)
        or command.get("resolved_image_id") != lock.derived_command_image_id
        or value.get("external_agent_execution_backend") != "runtime_external_process_unavailable"
        or value.get("external_agent_command_execution_backend")
        != OPENHANDS_V58_COMMAND_EXECUTION_BACKEND
    ):
        raise ConfigurationError("OpenHands v58 command runtime evidence changed")


def _service() -> VeriGym:
    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "openhands-hwe-agent" not in registries.agents.names():
        from verigym_openhands.hwe_agent import OpenHandsHweAgentAdapter

        registries.agents.register(OpenHandsHweAgentAdapter())
    return VeriGym(registries)


def _validated_control_plane_environment() -> None:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    expected_pythonpath = os.pathsep.join(_MCP_PYTHONPATH_ENTRIES)
    control_root = Path(_BROKER_ROOT)
    if control_root.is_symlink():
        raise ConfigurationError("OpenHands v58 control root is a symlink")
    control_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not control_root.resolve(strict=True).is_dir():
        raise ConfigurationError("OpenHands v58 control root is unavailable")
    if (
        os.environ.get(_BROKER_ROOT_ENV) != _BROKER_ROOT
        or os.environ.get(_MCP_PYTHONPATH_ENV) != expected_pythonpath
        or str(_configured_control_root()) != _BROKER_ROOT
        or _configured_mcp_pythonpath() != expected_pythonpath
    ):
        raise ConfigurationError("OpenHands v58 control-plane environment changed")


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPENHANDS_V58_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V58_OPT_IN_ENV}=1 is required")
    if campaign_id != OPENHANDS_V58_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands v58 campaign identity changed")
    _validated_control_plane_environment()
    if not os.environ.get(OPENHANDS_V19_CANARY_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_V19_CANARY_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands v58 provider environment is incomplete")
    expected = {
        "openhands-sdk": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers": OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
        "numpy": OPENHANDS_V58_NUMPY_VERSION,
        "pillow": OPENHANDS_V58_PILLOW_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"OpenHands v58 {package} version changed")


def _provider_values() -> tuple[str, str]:
    return (
        os.environ[OPENHANDS_V19_CANARY_BASE_URL_ENV],
        os.environ[OPENHANDS_V19_CANARY_API_KEY_ENV],
    )


def _scan_provider_values(root: Path) -> dict[str, Any]:
    values = tuple(value.encode() for value in _provider_values())
    files = 0
    byte_count = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("OpenHands v58 artifact contains a symlink")
        if not path.is_file():
            continue
        data = path.read_bytes()
        files += 1
        byte_count += len(data)
        if any(value in data for value in values):
            raise ConfigurationError("provider value reached OpenHands v58 artifacts")
    return {
        "passed": True,
        "provider_value_count_scanned": len(values),
        "file_count_scanned": files,
        "byte_count_scanned": byte_count,
        "provider_value_hit_count": 0,
        "provider_values_persisted_or_hashed": False,
    }


def _merged_source_commit() -> str:
    repository = Path(__file__).resolve().parents[1]
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("OpenHands v58 required merged path changed")
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
        ["git", "merge-base", "--is-ancestor", _QUALIFICATION_MERGE_COMMIT, head],
        cwd=repository,
        check=True,
    )
    if head != upstream or len(head) != 40:
        raise ConfigurationError("OpenHands v58 canary requires clean merged origin/main")
    return head


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    try:
        result = validate_v58_authorization(value)
    except ValueError as exc:
        raise ConfigurationError("OpenHands v58 authorization identity changed") from exc
    if result["authorization_hash"] != _AUTHORIZATION_HASH:
        raise ConfigurationError("OpenHands v58 authorization hash changed")
    return result


def _authorization_receipt(value: dict[str, Any]) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v58_authorization_receipt_v1",
        "authorization_format": OPENHANDS_V58_AUTHORIZATION_FORMAT,
        "authorization_hash": value["authorization_hash"],
        "task_id": OPENHANDS_V58_TASK_ID,
        "seed": OPENHANDS_V58_SEED,
        "sample_index": OPENHANDS_V58_SAMPLE_INDEX,
        "provider_calls_before_receipt": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"OpenHands v58 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_dir():
        raise ConfigurationError(f"OpenHands v58 {label} identity changed")
    return resolved


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink():
        raise ConfigurationError(f"OpenHands v58 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True) or not resolved.is_file():
        raise ConfigurationError(f"OpenHands v58 {label} identity changed")
    return resolved


def _safe_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"unsafe OpenHands v58 input: {path.name}")
    resolved = path.resolve(strict=True)
    if not 0 < resolved.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError(f"oversized OpenHands v58 input: {resolved.name}")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    resolved = _safe_file(path)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v58 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v58 JSON input is not an object: {resolved.name}")
    return value


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("OpenHands v58 output must not already exist")
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
    base_report: dict[str, Any],
    *,
    status: str,
    reason: str,
    provider_episode_started: bool,
) -> dict[str, Any]:
    accounting = _observed_provider_accounting(root, None)
    if provider_episode_started and accounting["provider_episode_count"] == 0:
        accounting = {
            "provider_episode_count": 1,
            "provider_call_count": None,
            "provider_input_tokens": None,
            "provider_output_tokens": None,
            "provider_total_tokens": None,
            "provider_accounting_complete": False,
        }
    final = _seal_report(
        {
            **base_report,
            "status": status,
            "provider_episode_started": provider_episode_started,
            "canary_passed": False,
            "trajectory_collected": False,
            "exact_64k_eligible": False,
            "task_consumed": provider_episode_started,
            "task_disposition": (
                "frozen_after_started_canary"
                if provider_episode_started
                else "not_consumed_pre_provider_stop"
            ),
            "failure_reason": reason,
            **accounting,
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def _observed_provider_accounting(root: Path, attempt: dict[str, Any] | None) -> dict[str, Any]:
    if attempt is not None and isinstance(attempt.get("protocol_receipt"), dict):
        protocol = attempt["protocol_receipt"]
        return {
            "provider_episode_count": 1,
            "provider_call_count": int(protocol["provider_call_count"]),
            "provider_input_tokens": int(protocol["provider_input_tokens"]),
            "provider_output_tokens": int(protocol["provider_output_tokens"]),
            "provider_total_tokens": int(protocol["provider_total_tokens"]),
            "provider_accounting_complete": True,
        }
    accounting_files = list((root / "runs").glob("*/artifacts/openhands_sdk/accounting.json"))
    if len(accounting_files) == 1:
        accounting = ExternalAgentAccounting.model_validate(_load_json(accounting_files[0]))
        calls = int(accounting.model_call_count or 0)
        input_tokens = int(accounting.input_tokens or 0)
        output_tokens = int(accounting.output_tokens or 0)
        return {
            "provider_episode_count": 1,
            "provider_call_count": calls,
            "provider_input_tokens": input_tokens,
            "provider_output_tokens": output_tokens,
            "provider_total_tokens": input_tokens + output_tokens,
            "provider_accounting_complete": True,
        }
    return {
        "provider_episode_count": 0,
        "provider_call_count": 0,
        "provider_input_tokens": 0,
        "provider_output_tokens": 0,
        "provider_total_tokens": 0,
        "provider_accounting_complete": True,
    }


def main() -> int:
    report = collect(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "canary_passed": report.get("canary_passed"),
                "provider_call_count": report.get("provider_call_count"),
                "trajectory_collected": report.get("trajectory_collected"),
                "exact_64k_eligible": report.get("exact_64k_eligible"),
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("canary_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
