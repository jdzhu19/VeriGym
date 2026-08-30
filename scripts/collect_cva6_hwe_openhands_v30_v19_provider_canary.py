#!/usr/bin/env python3
"""Run the authorized two-task v19 required-tool provider canary once."""

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

from verigym_openhands.hwe_v19 import (
    classify_v19_campaign_result,
    seal_v19_decision_receipt,
    seal_v19_trajectory_receipt,
)
from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V19_CANARY_CAMPAIGN_ID,
    OPENHANDS_V19_CANARY_SAMPLE_INDEX,
    OPENHANDS_V19_CANARY_SEED,
    OPENHANDS_V19_CANARY_VALIDATION_TASK,
    evaluate_v19_canary_gate,
    validate_v19_canary_contract,
    validate_v19_qualification_receipt,
)
from verigym_openhands.hwe_v19_canary_runtime import (
    OPENHANDS_V19_CANARY_API_KEY_ENV,
    OPENHANDS_V19_CANARY_BASE_URL_ENV,
    OPENHANDS_V19_CANARY_LITELLM_VERSION,
    OPENHANDS_V19_CANARY_MODEL,
    OPENHANDS_V19_CANARY_MODEL_IDENTITY,
    OPENHANDS_V19_CANARY_OPT_IN_ENV,
    OPENHANDS_V19_CANARY_SDK_VERSION,
    OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
    OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
    build_v19_canary_agent_options,
    build_v19_canary_agent_version,
    validate_v19_canary_runtime_evidence,
)
from verigym_openhands.trajectory import (
    OpenHandsTrajectoryError,
    materialize_openhands_decisions,
    validate_openhands_training_trajectory,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock
from verigym.hwe.qwen_action_tokenizer import QwenDecisionExampleTokenizer
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.run import RunConfig
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_docker_config = _collection._docker_config
_infrastructure_invalid = _collection._infrastructure_invalid
_load_tokenizer = _collection._load_tokenizer
_base_model_lock = _collection._base_model_lock

OPENHANDS_V30_APPROVAL_FORMAT = "verigym_openhands_hwe_v30_v19_provider_canary_authorization_v1"
OPENHANDS_V30_REPORT_FORMAT = "verigym_openhands_hwe_v30_v19_provider_canary_report_v1"
OPENHANDS_V30_IDENTITY = "openhands-hwe-v30-v19-provider-canary-v1"
OPENHANDS_V30_APPROVAL_HASH = "3619b56bbaf3dc5577c8511865e6f0a681f9d03a53b80b261d77e359f01994d8"
OPENHANDS_V30_MATERIALIZATION_AUDIT_MERGE = "33b30172999ef5b7e99e0df26d709deaf6bcd117"
OPENHANDS_V30_MATERIALIZATION_PROGRESS_HASH = (
    "42f85402c9e509a687ec32c953b24a026f978b5bf0684eb877f32876d0d302f0"
)
OPENHANDS_V30_MATERIALIZATION_PROGRESS_SHA256 = (
    "f2992d89c13de3ce4a55cb15f4c4985be8c7dd2c0402ea1b675bb793f55b00f2"
)
OPENHANDS_V30_CONTRACT_HASH = "cf6ba5b011f35ec958eaef319ee79ee4f8cd2fcbab77f0dae62f6dbd2c202efc"
OPENHANDS_V30_CONTRACT_SHA256 = "c65e4f10d243c0efb3e56fb2217c4c65f350cd58cd51aa0f69b13b3f12854a8a"
OPENHANDS_V30_QUALIFICATION_HASH = (
    "3eea3a1b0fc2bb3d2027c4c9c97549012ce32c484b3b7d07bdb15fc5260e59cb"
)
OPENHANDS_V30_QUALIFICATION_SHA256 = (
    "c56201069b55e1eb1bf5d7532dbfe891d54aa562c2ee980a83e3340f3b05d9e8"
)
OPENHANDS_V30_SOURCE_CATALOG_HASH = (
    "7d708bb0c7ac86e0562899e42abce671cde0c9c5b1d96fa21420cfed1fed400f"
)
OPENHANDS_V30_SOURCE_CATALOG_SHA256 = (
    "09abccc6d25f20abd9866d9bd8a7004727566a10bf3aa87af02077637931836a"
)
OPENHANDS_V30_TRAINING_LOCK_SHA256 = (
    "38776012996f20a2ac8d34a1bf5c80d77db9303d2132921d6dfcb064386a3f46"
)
OPENHANDS_V30_VALIDATION_LOCK_SHA256 = (
    "55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b"
)
OPENHANDS_V30_TRAINING_SOURCE_LOCK_SHA256 = (
    "69ddfef98824cb3cceeaa7bb6996f3dca4477a76a71fa15adbb4964ee699ff6f"
)
OPENHANDS_V30_VALIDATION_SOURCE_LOCK_SHA256 = (
    "ab23ac165898d66c54fc165de21e3eddfadc732542d5149ad15074c368447fa8"
)
OPENHANDS_V30_BASE_MODEL_LOCK_SHA256 = (
    "fb91ef923333c0bb251ca20d09801ee66aedf4a693b3adb85bbfb60858d8368b"
)
OPENHANDS_V30_MODEL_SNAPSHOT_HASH = (
    "fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156"
)
OPENHANDS_V30_TOKENIZER_HASH = "440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e"

_MAX_JSON_BYTES = 64 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--materialization-root", type=Path, required=True)
    parser.add_argument("--training-source", type=Path, required=True)
    parser.add_argument("--validation-source", type=Path, required=True)
    parser.add_argument("--validation-image-lock", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=OPENHANDS_V19_CANARY_CAMPAIGN_ID)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute at most two frozen episodes and stop after the first failed gate."""

    authorization = _validated_authorization(_load_json(arguments.authorization))
    _require_opt_in(arguments.campaign_id)
    source_commit = _merged_source_commit()
    materialization = _safe_directory(arguments.materialization_root, "materialization")
    contract, qualification, catalog, materialization_progress = _materialized_contract(
        materialization
    )
    task_ids = [str(item["task_id"]) for item in contract["schedule"]]
    training_task_id, validation_task_id = task_ids
    if authorization["schedule"]["task_ids"] != task_ids:
        raise ConfigurationError("OpenHands v30 authorization schedule changed")

    training_source = _validated_source(
        arguments.training_source,
        expected_lock_sha256=OPENHANDS_V30_TRAINING_SOURCE_LOCK_SHA256,
    )
    validation_source = _validated_source(
        arguments.validation_source,
        expected_lock_sha256=OPENHANDS_V30_VALIDATION_SOURCE_LOCK_SHA256,
    )
    sources = {
        training_task_id: training_source,
        validation_task_id: validation_source,
    }
    locks = {
        training_task_id: _validated_image_lock(
            materialization / "image-locks" / "pr-2330.json",
            expected_file_sha256=OPENHANDS_V30_TRAINING_LOCK_SHA256,
            task_id=training_task_id,
            contract=contract,
        ),
        validation_task_id: _validated_image_lock(
            arguments.validation_image_lock,
            expected_file_sha256=OPENHANDS_V30_VALIDATION_LOCK_SHA256,
            task_id=validation_task_id,
            contract=contract,
        ),
    }
    tokenizer_root = _safe_directory(arguments.tokenizer_root, "tokenizer")
    model_lock_path = _safe_file(arguments.base_model_lock)
    if hash_bytes(model_lock_path.read_bytes()) != OPENHANDS_V30_BASE_MODEL_LOCK_SHA256:
        raise ConfigurationError("OpenHands v30 base-model lock changed")
    model_lock = _base_model_lock(model_lock_path, tokenizer_root)
    if (
        model_lock["snapshot_hash"] != OPENHANDS_V30_MODEL_SNAPSHOT_HASH
        or model_lock["tokenizer_hash"] != OPENHANDS_V30_TOKENIZER_HASH
    ):
        raise ConfigurationError("OpenHands v30 Qwen tokenizer identity changed")
    tokenizer, transformers_version = _load_tokenizer(tokenizer_root)
    exact_tokenizer = QwenDecisionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_root)
    if exact_tokenizer.tokenizer_hash != OPENHANDS_V30_TOKENIZER_HASH:
        raise ConfigurationError("OpenHands v30 exact tokenizer hash changed")

    agent_version = build_v19_canary_agent_version(
        contract=contract,
        source_commit=source_commit,
        image_locks=locks,
    )
    build_v19_canary_agent_options(seed=OPENHANDS_V19_CANARY_SEED, agent_version=agent_version)
    root = _new_output(arguments.output)
    runs = root / "runs"
    scans = root / "security-scans"
    records = root / "trajectory-records"
    for directory in (runs, scans, records):
        directory.mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", agent_version)
    atomic_dump_json(root / "contract-receipt.json", _contract_receipt(contract, qualification))

    base_report = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V30_REPORT_FORMAT,
        "identity": OPENHANDS_V30_IDENTITY,
        "authorization_hash": authorization["authorization_hash"],
        "campaign_id": arguments.campaign_id,
        "status": "canary_running",
        "source_commit": source_commit,
        "materialization_audit_merge_commit": OPENHANDS_V30_MATERIALIZATION_AUDIT_MERGE,
        "materialization_progress_hash": materialization_progress["progress_hash"],
        "qualification_receipt_hash": qualification["receipt_hash"],
        "source_catalog_hash": catalog["catalog_hash"],
        "contract_hash": contract["contract_hash"],
        "schedule": copy.deepcopy(contract["schedule"]),
        "model_transport_id": OPENHANDS_V19_CANARY_MODEL,
        "model_identity": OPENHANDS_V19_CANARY_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers_version": transformers_version,
        "base_model_lock_file_sha256": OPENHANDS_V30_BASE_MODEL_LOCK_SHA256,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "seed": OPENHANDS_V19_CANARY_SEED,
        "sample_index": OPENHANDS_V19_CANARY_SAMPLE_INDEX,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "attempts": [],
        "heldout_task_ids_loaded": [],
        "fallback_identity_created": False,
        "remaining_reserve_consumed": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
        "formal_collection_allowed": False,
    }
    _write_report(root, base_report)
    try:
        _zero_call_preflight(locks)
    except Exception as exc:
        return _stop(
            root,
            base_report,
            [],
            status="stopped_infrastructure_invalid",
            reason=f"zero_call_preflight:{type(exc).__name__}",
        )

    service = _service()
    attempts: list[dict[str, Any]] = []
    for index, episode in enumerate(contract["schedule"]):
        task_id = str(episode["task_id"])
        role = str(episode["role"])
        episode_id = f"{role}-pr{task_id.rsplit('-', 1)[-1]}-s489-v19"
        try:
            attempt = _run_episode(
                service=service,
                contract=contract,
                episode=episode,
                episode_id=episode_id,
                source_root=sources[task_id],
                lock=locks[task_id],
                agent_version=agent_version,
                tokenizer=exact_tokenizer,
                runs=runs,
                scans=scans,
                records=records,
                root=root,
            )
        except Exception as exc:
            return _stop(
                root,
                base_report,
                attempts,
                status="stopped_infrastructure_or_security_invalid",
                reason=f"{episode_id}:{type(exc).__name__}",
            )
        attempts.append(attempt)
        running = {**base_report, "attempts": attempts}
        _write_report(root, running)
        stop_kind = _attempt_stop_kind(attempt)
        if stop_kind == "infrastructure_or_security_invalid":
            return _stop(
                root,
                base_report,
                attempts,
                status="stopped_infrastructure_or_security_invalid",
                reason=f"{episode_id}:invalid_result_plane",
            )
        if stop_kind == "six_plane_gate_failed":
            return _stop(
                root,
                base_report,
                attempts,
                status="canary_failed_closed",
                reason=f"{episode_id}:six_plane_gate_failed",
            )
        if index == 0 and task_id != training_task_id:
            raise ConfigurationError("OpenHands v30 training canary schedule drifted")

    passed = evaluate_v19_canary_gate(
        attempts,
        training_reserve_task_id=training_task_id,
    )
    final = _seal_report(
        {
            **base_report,
            "status": (
                "canary_passed_formal_collection_allowed" if passed else "canary_failed_closed"
            ),
            "attempts": attempts,
            "canary_passed": passed,
            "formal_collection_allowed": passed,
            **_observed_provider_accounting(root, attempts),
            "failure_reason": None if passed else "six_plane_gate_failed",
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def _run_episode(
    *,
    service: VeriGym,
    contract: dict[str, Any],
    episode: dict[str, Any],
    episode_id: str,
    source_root: Path,
    lock: HweAgentImageLock,
    agent_version: Any,
    tokenizer: QwenDecisionExampleTokenizer,
    runs: Path,
    scans: Path,
    records: Path,
    root: Path,
) -> dict[str, Any]:
    task_id = str(episode["task_id"])
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(task_id, source)
    snapshot = suite.source_snapshot()
    binding = contract["task_bindings"][task_id]
    if (
        snapshot is None
        or content_hash(task) != binding["task_hash"]
        or task.source.content_hash != binding["source_hash"]
    ):
        raise ConfigurationError("OpenHands v30 loaded task/source binding changed")
    started = time.monotonic()
    result = service.run(
        RunConfig(
            task_id=task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=binding["task_hash"],
            expected_source_hash=binding["source_hash"],
            mode=InteractionMode.AGENT,
            agent="openhands-hwe-agent",
            agent_options=build_v19_canary_agent_options(
                seed=int(episode["seed"]),
                agent_version=agent_version,
            ),
            runtime="docker",
            docker_config=_docker_config(lock),
            seed=int(episode["seed"]),
            sample_index=int(episode["sample_index"]),
            output=runs,
            run_id=episode_id,
            experiment_id=OPENHANDS_V19_CANARY_CAMPAIGN_ID,
            plan_item_id=episode_id,
            system_id=OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
            base_seed=int(episode["seed"]),
        )
    )
    scorecard = result.scorecard.model_dump(mode="json")
    infrastructure_valid = not _infrastructure_invalid(result.scorecard)
    run_directory = Path(result.run_dir).resolve(strict=True)
    if not run_directory.is_relative_to(runs) or run_directory.is_symlink():
        raise ConfigurationError("OpenHands v30 run directory escaped its output root")
    evidence = run_directory / "artifacts" / "openhands_sdk"
    if not infrastructure_valid:
        campaign_result = classify_v19_campaign_result(
            scorecard,
            agent_protocol_valid=False,
            trajectory_eligible=False,
            infrastructure_valid=False,
            security_valid=False,
            admit_to_sft=False,
        )
        return _attempt(
            episode=episode,
            episode_id=episode_id,
            run_id=episode_id,
            scorecard=scorecard,
            campaign_result=campaign_result,
            wall_seconds=time.monotonic() - started,
        )

    protocol: dict[str, Any] | None = None
    agent_protocol_valid = False
    try:
        broker = _load_json(evidence / "broker.json")
        summary = _load_json(evidence / "summary.json")
        accounting = ExternalAgentAccounting.model_validate(
            _load_json(evidence / "accounting.json")
        )
        protocol = validate_v19_canary_runtime_evidence(
            broker=broker,
            summary=summary,
            accounting=accounting,
            protocol_receipt=_load_json(evidence / "v19-protocol-receipt.json"),
        )
        agent_protocol_valid = True
    except (KeyError, OSError, ValueError, ConfigurationError):
        pass

    trajectory: dict[str, Any] | None = None
    decision_records: list[dict[str, Any]] = []
    trajectory_eligible = False
    if infrastructure_valid and agent_protocol_valid:
        try:
            trajectory = validate_openhands_training_trajectory(
                _load_json(evidence / "training-trajectory.json")
            )
            reproducibility = scorecard.get("reproducibility")
            if (
                trajectory["task_id"] != task_id
                or trajectory["verifier_resolved"] is not True
                or trajectory["sft_eligible"] is not True
                or not isinstance(reproducibility, dict)
            ):
                raise OpenHandsTrajectoryError("OpenHands v30 trajectory binding changed")
            decision_records = materialize_openhands_decisions(
                trajectory,
                binding={
                    "sample_id": content_hash(
                        {
                            "contract_hash": contract["contract_hash"],
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
            trajectory_eligible = bool(decision_records)
        except (KeyError, OSError, ValueError, ConfigurationError, OpenHandsTrajectoryError):
            trajectory = None
            decision_records = []

    record_path: Path | None = None
    if trajectory_eligible:
        record_path = records / f"{episode_id}.jsonl"
        _atomic_jsonl(record_path, decision_records)
    roots = [evidence]
    if record_path is not None:
        roots.append(record_path)
    security_report = scan_artifact_roots(
        roots,
        report_id=f"openhands-hwe-v30-v19-{episode_id}",
        proxy_values=_provider_values(),
        forbidden_host_roots=(
            str(source_root),
            str(Path.cwd().resolve()),
        ),
    )
    atomic_dump_json(scans / f"{episode_id}.json", security_report)
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

    campaign_result = classify_v19_campaign_result(
        scorecard,
        agent_protocol_valid=agent_protocol_valid,
        trajectory_eligible=trajectory_eligible,
        infrastructure_valid=infrastructure_valid,
        security_valid=security_valid,
        admit_to_sft=trajectory_eligible,
    )
    trajectory_receipt: dict[str, Any] | None = None
    decision_receipt: dict[str, Any] | None = None
    if campaign_result["sft_admitted"] is True:
        assert protocol is not None and trajectory is not None
        trajectory_receipt = seal_v19_trajectory_receipt(
            transcript_hash=trajectory["transcript_hash"],
            protocol_receipt=protocol,
            campaign_result=campaign_result,
        )
        decision_receipt = seal_v19_decision_receipt(
            records=decision_records,
            trajectory_receipt=trajectory_receipt,
        )
    elif record_path is not None:
        record_path.unlink(missing_ok=True)
        record_path = None

    attempt = {
        "episode_id": episode_id,
        "role": episode["role"],
        "task_id": task_id,
        "seed": episode["seed"],
        "sample_index": episode["sample_index"],
        "run_id": episode_id,
        "run_hash": content_hash({"run_id": episode_id, "scorecard": scorecard}),
        "wall_seconds": time.monotonic() - started,
        "result": campaign_result,
        "security_scan_hash": security_report.report_hash,
        "provider_value_scan": provider_value_scan,
        "protocol_receipt": protocol,
        "trajectory_receipt": trajectory_receipt,
        "decision_receipt": decision_receipt,
        "trajectory_file_sha256": (
            hash_bytes((evidence / "training-trajectory.json").read_bytes())
            if trajectory is not None
            else None
        ),
        "decision_records_file": record_path.name if record_path is not None else None,
        "decision_records_file_sha256": (
            hash_bytes(record_path.read_bytes())
            if record_path is not None and record_path.is_file()
            else None
        ),
        "decision_record_count": len(decision_records) if trajectory_receipt is not None else 0,
        "maximum_decision_tokens": (
            max(int(item["token_count"]) for item in decision_records)
            if trajectory_receipt is not None
            else None
        ),
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }
    return attempt


def _attempt(
    *,
    episode: dict[str, Any],
    episode_id: str,
    run_id: str,
    scorecard: dict[str, Any],
    campaign_result: dict[str, Any],
    wall_seconds: float,
) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "role": episode["role"],
        "task_id": episode["task_id"],
        "seed": episode["seed"],
        "sample_index": episode["sample_index"],
        "run_id": run_id,
        "run_hash": content_hash({"run_id": run_id, "scorecard": scorecard}),
        "wall_seconds": wall_seconds,
        "result": campaign_result,
        "security_scan_hash": None,
        "provider_value_scan": None,
        "protocol_receipt": None,
        "trajectory_receipt": None,
        "decision_receipt": None,
        "trajectory_file_sha256": None,
        "decision_records_file": None,
        "decision_records_file_sha256": None,
        "decision_record_count": 0,
        "maximum_decision_tokens": None,
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _attempt_stop_kind(attempt: dict[str, Any]) -> str | None:
    result = attempt.get("result")
    if not isinstance(result, dict):
        raise ConfigurationError("OpenHands v30 attempt lacks its six-plane result")
    if result.get("infrastructure_valid") is not True or result.get("security_valid") is not True:
        return "infrastructure_or_security_invalid"
    if result.get("sft_admitted") is not True:
        return "six_plane_gate_failed"
    return None


def _materialized_contract(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = {
        "progress": root / "materialization-progress.json",
        "contract": root / "canary-contract.json",
        "qualification": root / "qualification-receipt.json",
        "catalog": root / "source-catalog.json",
    }
    expected = {
        "progress": OPENHANDS_V30_MATERIALIZATION_PROGRESS_SHA256,
        "contract": OPENHANDS_V30_CONTRACT_SHA256,
        "qualification": OPENHANDS_V30_QUALIFICATION_SHA256,
        "catalog": OPENHANDS_V30_SOURCE_CATALOG_SHA256,
    }
    for key, path in paths.items():
        if hash_bytes(_safe_file(path).read_bytes()) != expected[key]:
            raise ConfigurationError(f"OpenHands v30 materialized {key} file changed")
    progress = _load_json(paths["progress"])
    contract = validate_v19_canary_contract(_load_json(paths["contract"]))
    qualification = validate_v19_qualification_receipt(_load_json(paths["qualification"]))
    catalog = _load_json(paths["catalog"])
    catalog_base = dict(catalog)
    catalog_hash = catalog_base.pop("catalog_hash", None)
    if (
        progress.get("status") != "completed_canary_contract_materialized"
        or progress.get("progress_hash") != OPENHANDS_V30_MATERIALIZATION_PROGRESS_HASH
        or progress.get("provider_calls") != 0
        or progress.get("canary_executed") is not False
        or progress.get("canary_contract_hash") != OPENHANDS_V30_CONTRACT_HASH
        or contract["contract_hash"] != OPENHANDS_V30_CONTRACT_HASH
        or qualification["receipt_hash"] != OPENHANDS_V30_QUALIFICATION_HASH
        or contract["qualification_receipt_hash"] != qualification["receipt_hash"]
        or catalog_hash != OPENHANDS_V30_SOURCE_CATALOG_HASH
        or content_hash(catalog_base) != catalog_hash
        or catalog.get("qualification_progress_hash") != progress.get("qualification_progress_hash")
    ):
        raise ConfigurationError("OpenHands v30 materialized evidence chain changed")
    return contract, qualification, catalog, progress


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    observed = value.pop("authorization_hash", None)
    if observed != OPENHANDS_V30_APPROVAL_HASH or content_hash(value) != observed:
        raise ConfigurationError("OpenHands v30 authorization identity changed")
    value["authorization_hash"] = observed
    expected = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V30_APPROVAL_FORMAT,
        "status": "authorized_pending_provider_canary",
        "identity": OPENHANDS_V30_IDENTITY,
        "failure_policy": "stop_after_first_failed_gate_no_retry",
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise ConfigurationError("OpenHands v30 authorization is malformed")
    evidence = value.get("materialization_evidence")
    schedule = value.get("schedule")
    controls = value.get("required_controls")
    actions = value.get("authorized_actions")
    if not all(isinstance(item, dict) for item in (evidence, schedule, controls, actions)):
        raise ConfigurationError("OpenHands v30 authorization sections are missing")
    assert isinstance(evidence, dict)
    assert isinstance(schedule, dict)
    assert isinstance(controls, dict)
    assert isinstance(actions, dict)
    if (
        evidence
        != {
            "audit_merge_commit": OPENHANDS_V30_MATERIALIZATION_AUDIT_MERGE,
            "progress_hash": OPENHANDS_V30_MATERIALIZATION_PROGRESS_HASH,
            "progress_file_sha256": OPENHANDS_V30_MATERIALIZATION_PROGRESS_SHA256,
            "contract_hash": OPENHANDS_V30_CONTRACT_HASH,
            "contract_file_sha256": OPENHANDS_V30_CONTRACT_SHA256,
            "qualification_receipt_hash": OPENHANDS_V30_QUALIFICATION_HASH,
            "qualification_receipt_file_sha256": OPENHANDS_V30_QUALIFICATION_SHA256,
            "source_catalog_hash": OPENHANDS_V30_SOURCE_CATALOG_HASH,
            "source_catalog_file_sha256": OPENHANDS_V30_SOURCE_CATALOG_SHA256,
        }
        or schedule
        != {
            "campaign_id": OPENHANDS_V19_CANARY_CAMPAIGN_ID,
            "agent_version_id": OPENHANDS_V19_CANARY_AGENT_VERSION_ID,
            "task_ids": [
                "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330",
                OPENHANDS_V19_CANARY_VALIDATION_TASK,
            ],
            "roles": ["training", "validation"],
            "seed": OPENHANDS_V19_CANARY_SEED,
            "sample_index": OPENHANDS_V19_CANARY_SAMPLE_INDEX,
            "maximum_provider_episodes": 2,
        }
        or controls
        != {
            "clean_merged_source_commit": True,
            "exact_materialization_chain": True,
            "exact_task_source_image_binding": True,
            "provider_request_retries": 0,
            "whole_episode_retries": 0,
            "stop_after_first_failed_gate": True,
            "runtime_network_none": True,
            "security_scan_before_admission": True,
            "exact_64k_no_truncation": True,
            "atomic_progress": True,
            "heldout_tasks_loaded": False,
        }
        or actions
        != {
            "invoke_provider": True,
            "execute_fixed_two_task_canary": True,
            "consume_additional_reserve": False,
            "create_fallback_identity": False,
            "start_collection": False,
            "start_training": False,
            "load_heldout_tasks": False,
        }
    ):
        raise ConfigurationError("OpenHands v30 authorization policy changed")
    inputs = value.get("input_locks")
    if inputs != {
        "training_image_lock_file_sha256": OPENHANDS_V30_TRAINING_LOCK_SHA256,
        "validation_image_lock_file_sha256": OPENHANDS_V30_VALIDATION_LOCK_SHA256,
        "training_source_image_lock_sha256": OPENHANDS_V30_TRAINING_SOURCE_LOCK_SHA256,
        "validation_source_image_lock_sha256": OPENHANDS_V30_VALIDATION_SOURCE_LOCK_SHA256,
        "base_model_lock_file_sha256": OPENHANDS_V30_BASE_MODEL_LOCK_SHA256,
        "base_model_snapshot_hash": OPENHANDS_V30_MODEL_SNAPSHOT_HASH,
        "tokenizer_hash": OPENHANDS_V30_TOKENIZER_HASH,
    }:
        raise ConfigurationError("OpenHands v30 input locks changed")
    return value


def _validated_image_lock(
    path: Path,
    *,
    expected_file_sha256: str,
    task_id: str,
    contract: dict[str, Any],
) -> HweAgentImageLock:
    resolved = _safe_file(path)
    if hash_bytes(resolved.read_bytes()) != expected_file_sha256:
        raise ConfigurationError("OpenHands v30 image-lock file changed")
    lock = HweAgentImageLock.model_validate(_load_json(resolved))
    binding = contract["task_bindings"][task_id]
    if (
        lock.task_id != task_id
        or lock.task_hash != binding["task_hash"]
        or lock.source_hash != binding["source_hash"]
        or lock.lock_hash != binding["image_lock_hash"]
        or lock.derived_agent_image_id != binding["agent_image"]
        or lock.verifier_base_image_id != binding["verifier_image"]
        or lock.runtime_network != "none"
        or lock.security_scan_passed is not True
    ):
        raise ConfigurationError("OpenHands v30 image-lock binding changed")
    return lock


def _validated_source(path: Path, *, expected_lock_sha256: str) -> Path:
    root = _safe_directory(path, "source")
    if hash_bytes(_safe_file(root / "image-lock.json").read_bytes()) != expected_lock_sha256:
        raise ConfigurationError("OpenHands v30 source image lock changed")
    return root


def _contract_receipt(contract: dict[str, Any], qualification: dict[str, Any]) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v30_contract_receipt_v1",
        "contract_hash": contract["contract_hash"],
        "qualification_receipt_hash": qualification["receipt_hash"],
        "task_bindings": copy.deepcopy(contract["task_bindings"]),
        "schedule": copy.deepcopy(contract["schedule"]),
        "heldout_task_ids_loaded": [],
    }
    return {**base, "receipt_hash": content_hash(base)}


def _zero_call_preflight(locks: dict[str, HweAgentImageLock]) -> None:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    _configured_control_root()
    _configured_mcp_pythonpath()
    for task_id, lock in locks.items():
        runtime = DockerRuntime(_docker_config(lock))
        try:
            runtime.prepare(f"openhands-v30-v19-preflight-{task_id.rsplit('-', 1)[-1]}")
        finally:
            runtime.close()


def _service() -> VeriGym:
    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "openhands-hwe-agent" not in registries.agents.names():
        from verigym_openhands.hwe_agent import OpenHandsHweAgentAdapter

        registries.agents.register(OpenHandsHweAgentAdapter())
    return VeriGym(registries)


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPENHANDS_V19_CANARY_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V19_CANARY_OPT_IN_ENV}=1 is required")
    if campaign_id != OPENHANDS_V19_CANARY_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands v30 campaign identity changed")
    if not os.environ.get(OPENHANDS_V19_CANARY_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_V19_CANARY_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands v30 provider environment is incomplete")
    expected = {
        "openhands-sdk": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers": OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"OpenHands v30 {package} version changed")


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
            raise ConfigurationError("OpenHands v30 artifact contains a symlink")
        if not path.is_file():
            continue
        data = path.read_bytes()
        files += 1
        byte_count += len(data)
        if any(value in data for value in values):
            raise ConfigurationError("provider value reached OpenHands v30 artifacts")
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
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise ConfigurationError("OpenHands v30 canary requires clean tracked files")
    head = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(head) != 40 or head != upstream:
        raise ConfigurationError("OpenHands v30 canary requires merged origin/main")
    return head


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_dir():
        raise ConfigurationError(f"OpenHands v30 {label} root is unsafe")
    return expanded.resolve(strict=True)


def _safe_file(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise ConfigurationError(f"unsafe OpenHands v30 input: {expanded.name}")
    resolved = expanded.resolve(strict=True)
    if not 0 < resolved.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError(f"oversized OpenHands v30 input: {resolved.name}")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    resolved = _safe_file(path)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v30 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v30 JSON input is not an object: {resolved.name}")
    return value


def _new_output(path: Path) -> Path:
    target = path.expanduser()
    if target.exists():
        raise ConfigurationError("OpenHands v30 output must not already exist")
    target.mkdir(parents=True, mode=0o700)
    return target.resolve(strict=True)


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


def _write_report(root: Path, value: dict[str, Any]) -> None:
    atomic_dump_json(root / "canary-progress.json", _seal_report(value))


def _stop(
    root: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
    *,
    status: str,
    reason: str,
) -> dict[str, Any]:
    final = _seal_report(
        {
            **base_report,
            "status": status,
            "attempts": attempts,
            "canary_passed": False,
            "formal_collection_allowed": False,
            **_observed_provider_accounting(root, attempts),
            "failure_reason": reason,
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def _observed_provider_accounting(root: Path, attempts: list[dict[str, Any]]) -> dict[str, int]:
    call_count = 0
    episode_count = 0
    runs = root / "runs"
    if runs.is_dir() and not runs.is_symlink():
        for path in sorted(runs.glob("*/artifacts/openhands_sdk/accounting.json")):
            if path.is_symlink() or not path.is_file():
                raise ConfigurationError("OpenHands v30 provider accounting path is unsafe")
            accounting = ExternalAgentAccounting.model_validate(_load_json(path))
            observed_calls = accounting.model_call_count
            if isinstance(observed_calls, bool) or not isinstance(observed_calls, int):
                raise ConfigurationError("OpenHands v30 provider call accounting is missing")
            call_count += observed_calls
            episode_count += 1
    if episode_count == 0:
        receipts: list[dict[str, Any]] = []
        for attempt in attempts:
            receipt = attempt.get("protocol_receipt")
            if isinstance(receipt, dict):
                receipts.append(receipt)
        call_count = sum(int(item["provider_call_count"]) for item in receipts)
        episode_count = len(receipts)
    return {
        "provider_episode_count": episode_count,
        "provider_call_count": call_count,
    }


def main() -> int:
    report = collect(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "canary_passed": report["canary_passed"],
                "formal_collection_allowed": report["formal_collection_allowed"],
                "provider_episode_count": report["provider_episode_count"],
                "provider_call_count": report["provider_call_count"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["formal_collection_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
