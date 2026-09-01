#!/usr/bin/env python3
"""Run the authorized two-task v37 public-thought provider canary once."""

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
from typing import Any, Literal, cast

from verigym_openhands.hwe_agent import _validated_hwe_runtime_bridge
from verigym_openhands.hwe_command_runtime import build_hwe_command_runtime_config
from verigym_openhands.hwe_v19_canary_runtime import (
    OPENHANDS_V19_CANARY_API_KEY_ENV,
    OPENHANDS_V19_CANARY_BASE_URL_ENV,
    OPENHANDS_V19_CANARY_LITELLM_VERSION,
    OPENHANDS_V19_CANARY_MODEL,
    OPENHANDS_V19_CANARY_MODEL_IDENTITY,
    OPENHANDS_V19_CANARY_SDK_VERSION,
    OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
    OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
)
from verigym_openhands.hwe_v20 import (
    classify_v20_campaign_result,
    seal_v20_decision_receipt,
    seal_v20_trajectory_receipt,
)
from verigym_openhands.hwe_v20_protocol import OPENHANDS_V20_TOOL_CHOICE_POLICY
from verigym_openhands.hwe_v37_canary_runtime import (
    OPENHANDS_V37_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V37_CANARY_CAMPAIGN_ID,
    OPENHANDS_V37_CANARY_CONTRACT_FORMAT,
    OPENHANDS_V37_CANARY_OPT_IN_ENV,
    OPENHANDS_V37_CANARY_SAMPLE_INDEX,
    OPENHANDS_V37_CANARY_SEED,
    OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
    build_v37_canary_agent_options,
    build_v37_canary_agent_version,
    validate_v37_canary_contract,
    validate_v37_canary_runtime_evidence,
)
from verigym_openhands.trajectory import (
    OpenHandsTrajectoryError,
    materialize_openhands_decisions,
    validate_openhands_training_trajectory,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.evolution.memory import validate_agent_version
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.hwe.qwen_action_tokenizer import QwenDecisionExampleTokenizer
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_infrastructure_invalid = _collection._infrastructure_invalid
_load_tokenizer = _collection._load_tokenizer
_base_model_lock = _collection._base_model_lock

OPENHANDS_V37_APPROVAL_FORMAT = "verigym_openhands_hwe_v37_provider_canary_authorization_v1"
OPENHANDS_V37_REPORT_FORMAT = "verigym_openhands_hwe_v37_provider_canary_report_v1"
OPENHANDS_V37_IDENTITY = "openhands-hwe-v37-provider-canary-v1"
OPENHANDS_V37_APPROVAL_HASH = "5b898808a9e1796e6dbff0f510545776b6b21ef961c20eea63e08878a7907b19"

_V33_AUDIT_MERGE = "648fe717e88b36876245df09e73222f906f83918"
_V33_AUDIT_FILE_SHA256 = "63f814ebeee613e479db3c99f362211e6304778d11ab4cc35873c50f7750af5a"
_V33_TREE_HASH = "62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6"
_V33_PROGRESS_HASH = "463aa8016d62e947421379cd925009c131a589d754e0c17e7c7f83c72fef26df"
_V33_PROGRESS_SHA256 = "267c8340e98b81a092216afccc5dadd0834960613920499c392f34522dd78839"
_V33_CATALOG_HASH = "05be424d40014e7ef69106f85e5ea161db2bb8e70103c8d1279e4a7c118f8e05"
_V33_CATALOG_SHA256 = "08c31fb7ad13d96fda850f114b34688ec22c0d96a865eb21e5d19fe03df5a423"

_V36_AUDIT_MERGE = "e650953f5d508c1b53dc35c325944108d4b90420"
_V36_AUDIT_FILE_SHA256 = "58cb19ce494248ff8714a9786563b6b70b818c8d49eed5e880f169467a436ddd"
_V36_ROOT_CAUSE_MERGE = "24705dff206845cb8741a7cadeeaeaa6913cc178"
_V36_ROOT_CAUSE_FILE_SHA256 = "8725ef62106101b741ba371db1c60e484814ed5d4867fd9a53841806e125b352"
_V36_TREE_HASH = "ccf9094dfe373587454346f5b52b4a8f7d3ade828b4f15b524c63d14a6d26f4d"
_V36_REPORT_HASH = "debf637e7697c921c24898a027a907d045514c0f7f65d131ad7e3471998124d0"
_V36_REPORT_SHA256 = "9abe705efe3ddfd24c51f9261febe5349a8649037771036063b803c8523e55e8"
_V36_AGENT_VERSION_HASH = "0f346efa5627469a7d71c595459e97b061225385d005d124816b91c8bc37ed77"
_V36_AGENT_VERSION_SHA256 = "43d212129f9c99c234ffe81b267a000274e299e9bba241ef77fe684cf8e8ed03"
_V36_CONTRACT_RECEIPT_HASH = "07d88c51512cc57f55d857627700d3fd8fbe0e87668eb355a4bbb45068365bd7"
_V36_CONTRACT_RECEIPT_SHA256 = "70bd0f9929a3cae3acd52cd12c9cb5602232773e46ea746e13f9eab9c71a2644"
_V36_PREFLIGHT_RECEIPT_HASH = "fb784dbcd80a369833634edc4ccf8b875d5393984c40eedc1260e2cc689c5e68"
_V36_PREFLIGHT_RECEIPT_SHA256 = "f5fae39b09cc20ca58f2b67a3e59e190738a1eb7a8ac7be6ad6390502a6b887b"
_V36_ATTEMPT_SHA256 = "fa0bc526bae7d7734bec3adca53ff57d8b1f67b3fc6a7072a25e85ca9575634f"

_BROKER_ROOT_ENV = "VERIGYM_OPENHANDS_BROKER_ROOT"
_MCP_PYTHONPATH_ENV = "VERIGYM_OPENHANDS_MCP_PYTHONPATH"
_BROKER_ROOT = "/data/jzhu484/Agent/.verigym-tmp/oh-v37"
_MCP_PYTHONPATH_ENTRIES = (
    "/data/jzhu484/Agent/VeriGym/src",
    "/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src",
    "/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src",
    "/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src",
)

_TRAINING_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3226"
_VALIDATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
_TASKS = (_TRAINING_TASK, _VALIDATION_TASK)
_LOCK_INPUTS = {
    _TRAINING_TASK: {
        "task_hash": "47cd8b6b6964b337751528bd7479dc9fb8e7f18cbdef1bf605bd70acd6e70fad",
        "source_hash": "b6a03041571bfbd70cbea308f358747efce9001685f1104ff411306e51bbafa9",
        "file_sha256": "a8772638c4a34dca8d522ea0a6ba65389293f1f7c8ac4a93036c39e006fd2c59",
        "lock_hash": "ee9ea16b67e910adb591c473d53fc6dfd73fe3935126e8a372d00be9d6159a3e",
        "security_scan_file_sha256": (
            "127412a7924e36d79efbabadadf912f948fd0424385fd7e71941a234e97d4c8e"
        ),
        "security_scan_id": "e3b1ce79576cba909f0eb42d22db4a95a057754f49aabe63ee16a8008f97d9c0",
        "command_image": "sha256:8b693c06696f4afa6c731e2c4cd98b48de8c67b50431c1fd33d5a700b555f6bb",
        "verifier_image": "sha256:ba05f4c8a52ffe566161af9fd1b654690019837509e6d0a5797a4b4b9e959ad8",
    },
    _VALIDATION_TASK: {
        "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
        "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
        "file_sha256": "a3a29f4ad2515c9502b3716e8644806154c7f9a74d388f9cd9c741d81458dc22",
        "lock_hash": "4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7",
        "security_scan_file_sha256": (
            "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1"
        ),
        "security_scan_id": "55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf",
        "command_image": "sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784",
        "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
    },
}
_TRAINING_SOURCE_LOCK_SHA256 = "a60a4ae70d6dedcead4bf33fba431e4f07d366dc8fe5eef3cd78afd57e1a5e6a"
_VALIDATION_SOURCE_LOCK_SHA256 = "ab23ac165898d66c54fc165de21e3eddfadc732542d5149ad15074c368447fa8"
_BASE_MODEL_LOCK_SHA256 = "fb91ef923333c0bb251ca20d09801ee66aedf4a693b3adb85bbfb60858d8368b"
_MODEL_SNAPSHOT_HASH = "fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156"
_TOKENIZER_HASH = "440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e"
_MAX_JSON_BYTES = 64 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v37_provider_canary_v1.json",
    "docs/audits/2026-09-01_openhands-v33-codex-free-materialization-passed.md",
    "docs/audits/2026-09-01_openhands-v36-provider-canary-failed-closed.md",
    "docs/audits/2026-09-01_openhands-v36-provider-response-root-cause.md",
    "docs/audits/2026-09-01_openhands-v37-provider-canary-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_agent.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v20.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v20_protocol.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v37_canary_runtime.py",
    "scripts/collect_cva6_hwe_openhands_v37_provider_canary.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--materialization-root", type=Path, required=True)
    parser.add_argument("--failed-v36-canary-root", type=Path, required=True)
    parser.add_argument("--training-source", type=Path, required=True)
    parser.add_argument("--validation-source", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=OPENHANDS_V37_CANARY_CAMPAIGN_ID)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute at most two fresh episodes and stop after the first failed plane."""

    authorization = _validated_authorization(_load_json(arguments.authorization))
    _require_opt_in(arguments.campaign_id)
    source_commit = _merged_source_commit()
    materialization = _safe_directory(arguments.materialization_root, "v33 materialization")
    contract, catalog, progress, locks = _materialized_contract(materialization)
    failed_v36 = _failed_v36_evidence(
        _safe_directory(arguments.failed_v36_canary_root, "v36 failed canary")
    )
    control_plane = _control_plane_contract()
    if authorization["schedule"]["task_ids"] != list(_TASKS):
        raise ConfigurationError("OpenHands v37 authorization schedule changed")
    sources = {
        _TRAINING_TASK: _validated_source(
            arguments.training_source, expected_lock_sha256=_TRAINING_SOURCE_LOCK_SHA256
        ),
        _VALIDATION_TASK: _validated_source(
            arguments.validation_source, expected_lock_sha256=_VALIDATION_SOURCE_LOCK_SHA256
        ),
    }
    tokenizer_root = _safe_directory(arguments.tokenizer_root, "tokenizer")
    model_lock_path = _safe_file(arguments.base_model_lock)
    if hash_bytes(model_lock_path.read_bytes()) != _BASE_MODEL_LOCK_SHA256:
        raise ConfigurationError("OpenHands v37 base-model lock changed")
    model_lock = _base_model_lock(model_lock_path, tokenizer_root)
    if (
        model_lock["snapshot_hash"] != _MODEL_SNAPSHOT_HASH
        or model_lock["tokenizer_hash"] != _TOKENIZER_HASH
    ):
        raise ConfigurationError("OpenHands v37 Qwen tokenizer identity changed")
    tokenizer, transformers_version = _load_tokenizer(tokenizer_root)
    exact_tokenizer = QwenDecisionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_root)
    if exact_tokenizer.tokenizer_hash != _TOKENIZER_HASH:
        raise ConfigurationError("OpenHands v37 exact tokenizer hash changed")

    agent_version = build_v37_canary_agent_version(
        contract=contract,
        source_commit=source_commit,
        command_image_locks=locks,
        predecessor_report_hash=failed_v36["report_hash"],
        v33_catalog_hash=catalog["catalog_hash"],
        control_plane_contract_hash=control_plane["contract_hash"],
    )
    for role in ("training", "validation"):
        build_v37_canary_agent_options(
            seed=OPENHANDS_V37_CANARY_SEED, role=role, agent_version=agent_version
        )
    root = _new_output(arguments.output)
    runs = root / "runs"
    scans = root / "security-scans"
    records = root / "trajectory-records"
    attempts_root = root / "attempts"
    for directory in (runs, scans, records, attempts_root):
        directory.mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", agent_version)
    atomic_dump_json(root / "contract-receipt.json", _contract_receipt(contract, locks))

    base_report: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V37_REPORT_FORMAT,
        "identity": OPENHANDS_V37_IDENTITY,
        "authorization_hash": authorization["authorization_hash"],
        "campaign_id": arguments.campaign_id,
        "status": "canary_running",
        "source_commit": source_commit,
        "v33_materialization_audit_merge_commit": _V33_AUDIT_MERGE,
        "v33_materialization_tree_hash": _V33_TREE_HASH,
        "v33_materialization_progress_hash": progress["progress_hash"],
        "v33_command_image_catalog_hash": catalog["catalog_hash"],
        "failed_v36_audit_merge_commit": _V36_AUDIT_MERGE,
        "failed_v36_evidence_tree_hash": _V36_TREE_HASH,
        "failed_v36_report_hash": failed_v36["report_hash"],
        "v36_root_cause_merge_commit": _V36_ROOT_CAUSE_MERGE,
        "control_plane_contract_hash": control_plane["contract_hash"],
        "canary_contract_hash": contract["contract_hash"],
        "schedule": copy.deepcopy(authorization["schedule"]),
        "runtime": copy.deepcopy(authorization["runtime"]),
        "model_transport_id": OPENHANDS_V19_CANARY_MODEL,
        "model_identity": OPENHANDS_V19_CANARY_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_V37_CANARY_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers_version": transformers_version,
        "base_model_lock_file_sha256": _BASE_MODEL_LOCK_SHA256,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "seed": OPENHANDS_V37_CANARY_SEED,
        "sample_index": OPENHANDS_V37_CANARY_SAMPLE_INDEX,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "attempts": [],
        "heldout_task_ids_loaded": [],
        "fallback_identity_created": False,
        "training_reserve_consumed_by_canary": True,
        "formal_training_schedule_requires_replacement": True,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
        "formal_collection_allowed": False,
    }
    _write_report(root, base_report)
    try:
        _zero_call_preflight(root, locks, sources)
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
        episode_id = f"{role}-pr{task_id.rsplit('-', 1)[-1]}-s490-v37"
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
        atomic_dump_json(attempts_root / f"{episode_id}.json", attempt)
        _write_report(root, {**base_report, "attempts": attempts})
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
        if index == 0 and task_id != _TRAINING_TASK:
            raise ConfigurationError("OpenHands v37 training canary schedule drifted")

    passed = len(attempts) == 2 and all(_attempt_stop_kind(item) is None for item in attempts)
    final = _seal_report(
        {
            **base_report,
            "status": (
                "canary_passed_formal_collection_allowed" if passed else "canary_failed_closed"
            ),
            "attempts": attempts,
            "canary_passed": passed,
            "canary_trajectory_count": sum(
                int(item.get("trajectory_receipt") is not None) for item in attempts
            ),
            "exact_64k_trajectory_count": sum(
                int(item.get("token_receipt") is not None) for item in attempts
            ),
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
    lock: HweCommandImageLock,
    agent_version: AgentVersionManifest,
    tokenizer: QwenDecisionExampleTokenizer,
    runs: Path,
    scans: Path,
    records: Path,
    root: Path,
) -> dict[str, Any]:
    task_id = str(episode["task_id"])
    role_value = episode["role"]
    if role_value not in {"training", "validation"}:
        raise ConfigurationError("OpenHands v37 episode role changed")
    role = cast(Literal["training", "validation"], role_value)
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(task_id, source)
    snapshot = suite.source_snapshot()
    binding = contract["task_bindings"][task_id]
    if (
        snapshot is None
        or content_hash(task) != binding["task_hash"]
        or task.source.content_hash != binding["source_hash"]
    ):
        raise ConfigurationError("OpenHands v37 loaded task/source binding changed")
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
            agent_options=build_v37_canary_agent_options(
                seed=int(episode["seed"]), role=role, agent_version=agent_version
            ),
            runtime="docker",
            docker_config=_runtime_config(lock),
            seed=int(episode["seed"]),
            sample_index=int(episode["sample_index"]),
            output=runs,
            run_id=episode_id,
            experiment_id=OPENHANDS_V37_CANARY_CAMPAIGN_ID,
            plan_item_id=episode_id,
            system_id=OPENHANDS_V37_CANARY_AGENT_VERSION_ID,
            base_seed=int(episode["seed"]),
        )
    )
    scorecard = result.scorecard.model_dump(mode="json")
    infrastructure_valid = not _infrastructure_invalid(result.scorecard)
    run_directory = Path(result.run_dir).resolve(strict=True)
    if not run_directory.is_relative_to(runs) or run_directory.is_symlink():
        raise ConfigurationError("OpenHands v37 run directory escaped its output root")
    evidence = run_directory / "artifacts" / "openhands_sdk"
    if not infrastructure_valid:
        campaign_result = classify_v20_campaign_result(
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
            scorecard=scorecard,
            campaign_result=campaign_result,
            wall_seconds=time.monotonic() - started,
        )
    _validate_runtime_manifest(result.manifest.environment_summary, lock)

    protocol: dict[str, Any] | None = None
    agent_protocol_valid = False
    try:
        accounting = ExternalAgentAccounting.model_validate(
            _load_json(evidence / "accounting.json")
        )
        protocol = validate_v37_canary_runtime_evidence(
            broker=_load_json(evidence / "broker.json"),
            summary=_load_json(evidence / "summary.json"),
            accounting=accounting,
            protocol_receipt=_load_json(evidence / "v20-protocol-receipt.json"),
        )
        agent_protocol_valid = True
    except (KeyError, OSError, ValueError, ConfigurationError):
        pass

    trajectory: dict[str, Any] | None = None
    decision_records: list[dict[str, Any]] = []
    trajectory_eligible = False
    if agent_protocol_valid:
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
                raise OpenHandsTrajectoryError("OpenHands v37 trajectory binding changed")
            decision_records = materialize_openhands_decisions(
                trajectory,
                binding={
                    "sample_id": content_hash(
                        {
                            "contract_hash": contract["contract_hash"],
                            "campaign_id": OPENHANDS_V37_CANARY_CAMPAIGN_ID,
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

    record_dir: Path | None = None
    record_path: Path | None = None
    if trajectory_eligible:
        record_dir = records / episode_id
        record_dir.mkdir(mode=0o700)
        record_path = record_dir / "decisions.jsonl"
        _atomic_jsonl(record_path, decision_records)
    scan_roots = [evidence]
    private_audit = run_directory / "private-audit"
    if private_audit.is_dir() and not private_audit.is_symlink():
        scan_roots.append(private_audit)
    if record_dir is not None:
        scan_roots.append(record_dir)
    security_report = scan_artifact_roots(
        scan_roots,
        report_id=f"openhands-hwe-v37-{episode_id}",
        proxy_values=_provider_values(),
        forbidden_host_roots=(str(source_root), str(Path.cwd().resolve())),
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

    campaign_result = classify_v20_campaign_result(
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
    if campaign_result["sft_admitted"] is True:
        assert protocol is not None and trajectory is not None and record_dir is not None
        trajectory_receipt = seal_v20_trajectory_receipt(
            transcript_hash=trajectory["transcript_hash"],
            protocol_receipt=protocol,
            campaign_result=campaign_result,
        )
        decision_receipt = seal_v20_decision_receipt(
            records=decision_records,
            trajectory_receipt=trajectory_receipt,
        )
        token_base = {
            "schema_version": "1.0",
            "format_id": "verigym_openhands_hwe_v37_exact_64k_token_receipt_v1",
            "episode_id": episode_id,
            "transcript_hash": trajectory["transcript_hash"],
            "decision_receipt_hash": decision_receipt["receipt_hash"],
            "decision_record_count": len(decision_records),
            "maximum_token_count": max(int(item["token_count"]) for item in decision_records),
            "max_length": 65_536,
            "truncation": "error",
            "truncation_applied": False,
            "decision_only_loss_mask": True,
            "public_tool_thought_supervised": True,
        }
        token_receipt = {**token_base, "receipt_hash": content_hash(token_base)}
        atomic_dump_json(record_dir / "trajectory-receipt.json", trajectory_receipt)
        atomic_dump_json(record_dir / "decision-receipt.json", decision_receipt)
        atomic_dump_json(record_dir / "token-receipt.json", token_receipt)
        provider_value_scan = _scan_provider_values(root)

    return {
        "episode_id": episode_id,
        "role": role,
        "task_id": task_id,
        "seed": episode["seed"],
        "sample_index": episode["sample_index"],
        "run_id": episode_id,
        "run_hash": content_hash({"run_id": episode_id, "scorecard": scorecard}),
        "wall_seconds": time.monotonic() - started,
        "result": campaign_result,
        "runtime_command_image": lock.derived_command_image_id,
        "command_execution_backend": OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
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
        "decision_record_count": len(decision_records) if trajectory_receipt is not None else 0,
        "maximum_decision_tokens": (
            max(int(item["token_count"]) for item in decision_records)
            if trajectory_receipt is not None
            else None
        ),
        "exact_64k_eligible": token_receipt is not None,
        "decision_only_loss_mask": token_receipt is not None,
        "public_tool_thought_supervised": token_receipt is not None,
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _attempt(
    *,
    episode: dict[str, Any],
    episode_id: str,
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
        "run_id": episode_id,
        "run_hash": content_hash({"run_id": episode_id, "scorecard": scorecard}),
        "wall_seconds": wall_seconds,
        "result": campaign_result,
        "runtime_command_image": None,
        "command_execution_backend": OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
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
        "public_tool_thought_supervised": False,
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _attempt_stop_kind(attempt: dict[str, Any]) -> str | None:
    result = attempt.get("result")
    if not isinstance(result, dict):
        raise ConfigurationError("OpenHands v37 attempt lacks its six-plane result")
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
        or attempt.get("public_tool_thought_supervised") is not True
        or attempt.get("truncation_applied") is not False
        or not isinstance(attempt.get("trajectory_receipt"), dict)
        or not isinstance(attempt.get("decision_receipt"), dict)
        or not isinstance(attempt.get("token_receipt"), dict)
    ):
        return "six_plane_gate_failed"
    return None


def _materialized_contract(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, HweCommandImageLock]]:
    if hash_directory(root) != _V33_TREE_HASH:
        raise ConfigurationError("OpenHands v37 v33 evidence inventory changed")
    progress_path = root / "materialization-progress.json"
    catalog_path = root / "command-image-catalog.json"
    for path, expected in (
        (progress_path, _V33_PROGRESS_SHA256),
        (catalog_path, _V33_CATALOG_SHA256),
    ):
        if hash_bytes(_safe_file(path).read_bytes()) != expected:
            raise ConfigurationError("OpenHands v37 v33 evidence file changed")
    progress = _validated_content_hash(_load_json(progress_path), "progress_hash")
    catalog = _validated_content_hash(_load_json(catalog_path), "catalog_hash")
    tasks = catalog.get("tasks")
    if (
        progress.get("status") != "completed_codex_free_canary_contract_materialized"
        or progress.get("progress_hash") != _V33_PROGRESS_HASH
        or progress.get("provider_calls") != 0
        or progress.get("model_process_count") != 0
        or progress.get("canary_executed") is not False
        or progress.get("collection_started") is not False
        or progress.get("training_started") is not False
        or progress.get("production_training_ready") is not False
        or progress.get("heldout_task_ids_loaded") != []
        or progress.get("runtime_network") != "none"
        or progress.get("command_execution_backend") != OPENHANDS_V37_COMMAND_EXECUTION_BACKEND
        or catalog.get("catalog_hash") != _V33_CATALOG_HASH
        or catalog.get("task_count") != 6
        or catalog.get("provider_credentials_present") is not False
        or catalog.get("codex_present") is not False
        or catalog.get("runtime_network") != "none"
        or catalog.get("command_execution_backend") != OPENHANDS_V37_COMMAND_EXECUTION_BACKEND
        or not isinstance(tasks, list)
        or len(tasks) != 6
    ):
        raise ConfigurationError("OpenHands v37 v33 evidence state changed")
    catalog_tasks = {str(item.get("task_id")): item for item in tasks if isinstance(item, dict)}
    if len(catalog_tasks) != 6:
        raise ConfigurationError("OpenHands v37 v33 catalog inventory changed")

    locks: dict[str, HweCommandImageLock] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for task_id in _TASKS:
        suffix = task_id.rsplit("-", 1)[-1]
        expected_input = _LOCK_INPUTS[task_id]
        lock_path = root / "image-locks" / f"pr-{suffix}.json"
        scan_path = root / "security-scans" / f"pr-{suffix}.json"
        if (
            hash_bytes(_safe_file(lock_path).read_bytes()) != expected_input["file_sha256"]
            or hash_bytes(_safe_file(scan_path).read_bytes())
            != expected_input["security_scan_file_sha256"]
        ):
            raise ConfigurationError("OpenHands v37 command-image evidence file changed")
        lock = HweCommandImageLock.model_validate(_load_json(lock_path))
        scan = _validated_content_hash(_load_json(scan_path), "security_scan_id")
        catalog_entry = catalog_tasks.get(task_id)
        binding = {
            "task_hash": expected_input["task_hash"],
            "source_hash": expected_input["source_hash"],
            "command_image_lock_hash": expected_input["lock_hash"],
            "command_image": expected_input["command_image"],
            "verifier_image": expected_input["verifier_image"],
            "security_scan_id": expected_input["security_scan_id"],
        }
        if (
            not isinstance(catalog_entry, dict)
            or any(catalog_entry.get(key) != value for key, value in binding.items())
            or catalog_entry.get("command_image_lock_file_sha256") != expected_input["file_sha256"]
            or lock.task_id != task_id
            or lock.task_hash != expected_input["task_hash"]
            or lock.source_hash != expected_input["source_hash"]
            or lock.lock_hash != expected_input["lock_hash"]
            or lock.derived_command_image_id != expected_input["command_image"]
            or lock.verifier_base_image_id != expected_input["verifier_image"]
            or lock.security_scan_id != expected_input["security_scan_id"]
            or scan.get("security_scan_id") != lock.security_scan_id
            or scan.get("scan_passed") is not True
            or scan.get("secrets_detected") is not False
            or lock.security_scan_passed is not True
            or lock.codex_present is not False
            or lock.provider_credentials_present is not False
            or lock.hidden_assets_present is not False
            or lock.reference_patch_present is not False
            or lock.verifier_payload_present is not False
            or lock.runtime_network != "none"
            or OPENHANDS_V37_COMMAND_EXECUTION_BACKEND not in lock.supported_execution_backends
        ):
            raise ConfigurationError("OpenHands v37 command-image binding changed")
        locks[task_id] = lock
        bindings[task_id] = binding

    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V37_CANARY_CONTRACT_FORMAT,
        "protocol_profile": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        "predecessor_catalog_hash": catalog["catalog_hash"],
        "schedule": [
            {
                "task_id": _TRAINING_TASK,
                "role": "training",
                "seed": OPENHANDS_V37_CANARY_SEED,
                "sample_index": OPENHANDS_V37_CANARY_SAMPLE_INDEX,
            },
            {
                "task_id": _VALIDATION_TASK,
                "role": "validation",
                "seed": OPENHANDS_V37_CANARY_SEED,
                "sample_index": OPENHANDS_V37_CANARY_SAMPLE_INDEX,
            },
        ],
        "task_bindings": bindings,
        "runtime": {
            "command_execution_backend": OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
            "command_role": "credential_free_command_image",
            "network": "none",
            "codex_present": False,
            "provider_credentials_in_command_container": False,
        },
        "heldout_task_ids_loaded": [],
    }
    contract = validate_v37_canary_contract({**base, "contract_hash": content_hash(base)})
    return contract, catalog, progress, locks


def _failed_v36_evidence(root: Path) -> dict[str, Any]:
    if hash_directory(root) != _V36_TREE_HASH:
        raise ConfigurationError("OpenHands v37 v36 evidence inventory changed")
    paths = {
        "report": root / "canary-report.json",
        "progress": root / "canary-progress.json",
        "agent": root / "agent-version.json",
        "contract": root / "contract-receipt.json",
        "preflight": root / "zero-call-preflight.json",
        "attempt": root / "attempts" / "training-pr2330-s489-v36.json",
    }
    expected_file_hashes = {
        "report": _V36_REPORT_SHA256,
        "progress": _V36_REPORT_SHA256,
        "agent": _V36_AGENT_VERSION_SHA256,
        "contract": _V36_CONTRACT_RECEIPT_SHA256,
        "preflight": _V36_PREFLIGHT_RECEIPT_SHA256,
        "attempt": _V36_ATTEMPT_SHA256,
    }
    for name, path in paths.items():
        if hash_bytes(_safe_file(path).read_bytes()) != expected_file_hashes[name]:
            raise ConfigurationError("OpenHands v37 v36 evidence file changed")
    report = _validated_content_hash(_load_json(paths["report"]), "report_hash")
    progress = _validated_content_hash(_load_json(paths["progress"]), "report_hash")
    agent = validate_agent_version(
        AgentVersionManifest.model_validate(_load_json(paths["agent"]))
    ).model_dump(mode="json")
    receipt = _validated_content_hash(_load_json(paths["contract"]), "receipt_hash")
    preflight = _validated_content_hash(_load_json(paths["preflight"]), "receipt_hash")
    attempt = _load_json(paths["attempt"])
    result = attempt.get("result")
    expected_planes = {
        "benchmark_verifier_pass": False,
        "agent_protocol_valid": False,
        "trajectory_eligible": False,
        "infrastructure_valid": True,
        "security_valid": True,
        "sft_admitted": False,
    }
    if (
        report != progress
        or report.get("identity") != "openhands-hwe-v36-provider-canary-v1"
        or report.get("status") != "canary_failed_closed"
        or report.get("failure_reason") != "training-pr2330-s489-v36:six_plane_gate_failed"
        or report.get("report_hash") != _V36_REPORT_HASH
        or report.get("provider_episode_count") != 1
        or report.get("provider_call_count") != 1
        or report.get("attempts") != [attempt]
        or report.get("canary_passed") is not False
        or report.get("formal_collection_allowed") is not False
        or report.get("formal_collection_started") is not False
        or report.get("collection_started") is not False
        or report.get("training_started") is not False
        or report.get("production_training_ready") is not False
        or report.get("benchmark_score_claimed") is not False
        or report.get("heldout_task_ids_loaded") != []
        or agent.get("version_hash") != _V36_AGENT_VERSION_HASH
        or receipt.get("receipt_hash") != _V36_CONTRACT_RECEIPT_HASH
        or preflight.get("receipt_hash") != _V36_PREFLIGHT_RECEIPT_HASH
        or preflight.get("status") != "passed"
        or preflight.get("provider_episode_count") != 0
        or preflight.get("provider_call_count") != 0
        or attempt.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330"
        or attempt.get("seed") != 489
        or attempt.get("sample_index") != 5
        or not isinstance(result, dict)
        or any(result.get(key) is not value for key, value in expected_planes.items())
        or attempt.get("protocol_receipt") is not None
        or attempt.get("trajectory_receipt") is not None
        or attempt.get("decision_receipt") is not None
        or attempt.get("token_receipt") is not None
        or attempt.get("exact_64k_eligible") is not False
        or attempt.get("whole_episode_retries") != 0
        or attempt.get("provider_request_retries") != 0
    ):
        raise ConfigurationError("OpenHands v37 v36 failed evidence state changed")
    return report


def _control_plane_contract() -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v37_control_plane_contract_v1",
        "broker_root": _BROKER_ROOT,
        "maximum_encoded_broker_root_bytes": 72,
        "mcp_pythonpath_entries": list(_MCP_PYTHONPATH_ENTRIES),
        "maximum_mcp_pythonpath_entries": 16,
        "maximum_encoded_mcp_pythonpath_bytes": 4096,
        "paths_must_exist": True,
        "paths_must_be_non_symlink": True,
        "preflight_receipt_format": "verigym_openhands_hwe_v37_zero_call_preflight_v1",
        "raw_exception_persisted": False,
    }
    return {**base, "contract_hash": content_hash(base)}


def _expected_authorization() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V37_APPROVAL_FORMAT,
        "status": "authorized_pending_provider_canary",
        "identity": OPENHANDS_V37_IDENTITY,
        "v33_materialization_evidence": {
            "audit_merge_commit": _V33_AUDIT_MERGE,
            "audit_file_sha256": _V33_AUDIT_FILE_SHA256,
            "evidence_tree_hash": _V33_TREE_HASH,
            "progress_hash": _V33_PROGRESS_HASH,
            "progress_file_sha256": _V33_PROGRESS_SHA256,
            "catalog_hash": _V33_CATALOG_HASH,
            "catalog_file_sha256": _V33_CATALOG_SHA256,
        },
        "failed_v36_evidence": {
            "audit_merge_commit": _V36_AUDIT_MERGE,
            "audit_file_sha256": _V36_AUDIT_FILE_SHA256,
            "evidence_tree_hash": _V36_TREE_HASH,
            "report_hash": _V36_REPORT_HASH,
            "report_file_sha256": _V36_REPORT_SHA256,
            "agent_version_hash": _V36_AGENT_VERSION_HASH,
            "agent_version_file_sha256": _V36_AGENT_VERSION_SHA256,
            "contract_receipt_hash": _V36_CONTRACT_RECEIPT_HASH,
            "contract_receipt_file_sha256": _V36_CONTRACT_RECEIPT_SHA256,
            "preflight_receipt_hash": _V36_PREFLIGHT_RECEIPT_HASH,
            "preflight_receipt_file_sha256": _V36_PREFLIGHT_RECEIPT_SHA256,
            "attempt_file_sha256": _V36_ATTEMPT_SHA256,
            "provider_episode_count": 1,
            "provider_call_count": 1,
            "task_attempt_count": 1,
            "failed_task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330",
            "failed_task_retry_authorized": False,
        },
        "v36_root_cause_evidence": {
            "merge_commit": _V36_ROOT_CAUSE_MERGE,
            "audit_file_sha256": _V36_ROOT_CAUSE_FILE_SHA256,
            "diagnosis": "v19_rejected_single_tool_call_with_public_visible_text",
            "successor_protocol": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        },
        "control_plane": _control_plane_contract(),
        "command_image_locks": [
            {"task_id": task_id, **copy.deepcopy(_LOCK_INPUTS[task_id])} for task_id in _TASKS
        ],
        "input_locks": {
            "training_source_image_lock_sha256": _TRAINING_SOURCE_LOCK_SHA256,
            "validation_source_image_lock_sha256": _VALIDATION_SOURCE_LOCK_SHA256,
            "base_model_lock_file_sha256": _BASE_MODEL_LOCK_SHA256,
            "base_model_snapshot_hash": _MODEL_SNAPSHOT_HASH,
            "tokenizer_hash": _TOKENIZER_HASH,
        },
        "software": {
            "model": OPENHANDS_V19_CANARY_MODEL,
            "model_identity": OPENHANDS_V19_CANARY_MODEL_IDENTITY,
            "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
            "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
            "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
            "transformers_version": OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
        },
        "schedule": {
            "campaign_id": OPENHANDS_V37_CANARY_CAMPAIGN_ID,
            "agent_version_id": OPENHANDS_V37_CANARY_AGENT_VERSION_ID,
            "task_ids": list(_TASKS),
            "roles": ["training", "validation"],
            "seed": OPENHANDS_V37_CANARY_SEED,
            "sample_index": OPENHANDS_V37_CANARY_SAMPLE_INDEX,
            "maximum_provider_episodes": 2,
            "pr2330_retry_authorized": False,
            "pr3226_consumed_as_canary": True,
            "formal_training_schedule_requires_replacement": True,
        },
        "runtime": {
            "command_role": "credential_free_command_image",
            "command_execution_backend": OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
            "external_agent_process_available": False,
            "codex_present": False,
            "provider_credentials_in_command_container": False,
            "network": "none",
        },
        "provider_budget": {
            "temperature": 0,
            "max_provider_calls_per_episode": 64,
            "max_provider_tokens_per_episode": 1_000_000,
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "provider_request_retries": 0,
            "whole_episode_retries": 0,
        },
        "protocol": {
            "profile": OPENHANDS_V20_TOOL_CHOICE_POLICY,
            "ordinary_tool_choice": "required",
            "maximum_tool_calls_per_response": 1,
            "public_visible_tool_thought_allowed": True,
            "public_visible_tool_thought_supervised": True,
            "private_reasoning_rejected": True,
            "malformed_or_duplicate_json_rejected": True,
            "safe_shape_only": True,
            "raw_model_content_persisted": False,
            "raw_tool_arguments_persisted": False,
            "content_only_recovery_budget": 1,
        },
        "required_controls": {
            "clean_merged_source_commit": True,
            "exact_v33_result_chain": True,
            "exact_failed_v36_result_chain": True,
            "exact_v36_root_cause_chain": True,
            "fresh_tasks_only": True,
            "explicit_command_backend_capability": True,
            "exact_task_source_command_image_binding": True,
            "control_plane_validated_before_output": True,
            "redacted_zero_call_preflight_receipt": True,
            "stop_after_first_failed_gate": True,
            "all_six_result_planes_required": True,
            "runtime_network_none": True,
            "security_scan_before_admission": True,
            "exact_64k_no_truncation": True,
            "decision_only_loss_mask": True,
            "atomic_per_task_progress": True,
            "provider_values_never_persisted_or_hashed": True,
            "heldout_tasks_loaded": False,
        },
        "authorized_actions": {
            "invoke_provider": True,
            "execute_fixed_two_task_canary": True,
            "retry_pr2330": False,
            "consume_pr3226_as_canary": True,
            "consume_any_other_reserve": False,
            "create_fallback_identity": False,
            "start_formal_collection": False,
            "start_training": False,
            "load_heldout_tasks": False,
        },
        "failure_policy": "stop_after_first_failed_gate_no_retry_freeze_identity",
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop("authorization_hash", None)
    if observed != OPENHANDS_V37_APPROVAL_HASH or content_hash(result) != observed:
        raise ConfigurationError("OpenHands v37 authorization identity changed")
    if result != _expected_authorization():
        raise ConfigurationError("OpenHands v37 authorization policy changed")
    return {**result, "authorization_hash": observed}


def _validated_source(path: Path, *, expected_lock_sha256: str) -> Path:
    root = _safe_directory(path, "source")
    if hash_bytes(_safe_file(root / "image-lock.json").read_bytes()) != expected_lock_sha256:
        raise ConfigurationError("OpenHands v37 source image lock changed")
    return root


def _contract_receipt(
    contract: dict[str, Any], locks: dict[str, HweCommandImageLock]
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v37_contract_receipt_v1",
        "v33_catalog_hash": _V33_CATALOG_HASH,
        "failed_v36_report_hash": _V36_REPORT_HASH,
        "v36_root_cause_merge_commit": _V36_ROOT_CAUSE_MERGE,
        "v37_contract_hash": contract["contract_hash"],
        "control_plane_contract_hash": _control_plane_contract()["contract_hash"],
        "campaign_id": OPENHANDS_V37_CANARY_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V37_CANARY_AGENT_VERSION_ID,
        "task_bindings": copy.deepcopy(contract["task_bindings"]),
        "command_image_lock_hashes": {task_id: locks[task_id].lock_hash for task_id in _TASKS},
        "schedule": copy.deepcopy(contract["schedule"]),
        "protocol_profile": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        "command_execution_backend": OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
        "pr2330_retry_authorized": False,
        "training_reserve_consumed_by_canary": True,
        "formal_training_schedule_requires_replacement": True,
        "heldout_task_ids_loaded": [],
    }
    return {**base, "receipt_hash": content_hash(base)}


def _runtime_config(lock: HweCommandImageLock) -> DockerRuntimeConfig:
    return build_hwe_command_runtime_config(
        lock,
        runtime_user=f"{os.getuid()}:{os.getgid()}",
        execution_backend=OPENHANDS_V37_COMMAND_EXECUTION_BACKEND,
    )


def _validated_control_plane_environment() -> dict[str, Any]:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    expected_pythonpath = os.pathsep.join(_MCP_PYTHONPATH_ENTRIES)
    if os.environ.get(_BROKER_ROOT_ENV) != _BROKER_ROOT:
        raise ConfigurationError("OpenHands v37 broker root contract changed")
    if os.environ.get(_MCP_PYTHONPATH_ENV) != expected_pythonpath:
        raise ConfigurationError("OpenHands v37 MCP Python path contract changed")
    if str(_configured_control_root()) != _BROKER_ROOT:
        raise ConfigurationError("OpenHands v37 resolved broker root changed")
    if _configured_mcp_pythonpath() != expected_pythonpath:
        raise ConfigurationError("OpenHands v37 resolved MCP Python path changed")
    return _control_plane_contract()


def _zero_call_preflight(
    root: Path,
    locks: dict[str, HweCommandImageLock],
    sources: dict[str, Path],
) -> None:
    completed: list[str] = []
    stage = "control_plane"
    try:
        control_plane = _validated_control_plane_environment()
        completed.append(stage)
        for task_id in _TASKS:
            suffix = task_id.rsplit("-", 1)[-1]
            stage = f"command_image_pr_{suffix}"
            runtime = DockerRuntime(_runtime_config(locks[task_id]))
            try:
                runtime.prepare(f"openhands-v37-preflight-{suffix}")
                _validate_runtime_manifest(runtime.environment_summary(), locks[task_id])
                completed.append(stage)
                stage = f"adapter_start_pr_{suffix}"
                session = runtime.create_session(
                    SessionSpec(source_dir=str(sources[task_id]), label="agent")
                )
                try:
                    bridge = RuntimeExternalAgentBridge(
                        session=session,
                        artifact_root=root / "preflight-adapter-artifacts" / f"pr-{suffix}",
                        isolation_level="docker_standard",
                        policy=WorkspacePolicy(editable_globs=("**/*",)),
                        trace=TraceWriter(
                            root / "preflight-traces" / f"pr-{suffix}.jsonl",
                            f"openhands-v37-preflight-{suffix}",
                        ),
                    )
                    if _validated_hwe_runtime_bridge(bridge) is not bridge:
                        raise ConfigurationError("OpenHands v37 adapter-start bridge changed")
                finally:
                    session.close()
            finally:
                runtime.close()
            completed.append(stage)
    except Exception as exc:
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_openhands_hwe_v37_zero_call_preflight_v1",
            "status": "failed",
            "control_plane_contract_hash": _control_plane_contract()["contract_hash"],
            "completed_stages": completed,
            "failed_stage": stage,
            "exception_type": type(exc).__name__,
            "provider_episode_count": 0,
            "provider_call_count": 0,
            "raw_exception_persisted": False,
        }
        atomic_dump_json(
            root / "zero-call-preflight.json",
            {**base, "receipt_hash": content_hash(base)},
        )
        raise
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v37_zero_call_preflight_v1",
        "status": "passed",
        "control_plane_contract_hash": control_plane["contract_hash"],
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
    if not isinstance(roles, dict):
        raise ConfigurationError("OpenHands v37 runtime role evidence is missing")
    command = roles.get("command")
    if (
        roles.get("external_agent") is not None
        or not isinstance(command, dict)
        or command.get("resolved_image_id") != lock.derived_command_image_id
        or value.get("external_agent_execution_backend") != "runtime_external_process_unavailable"
        or value.get("external_agent_command_execution_backend")
        != OPENHANDS_V37_COMMAND_EXECUTION_BACKEND
    ):
        raise ConfigurationError("OpenHands v37 command runtime evidence changed")


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
    if os.environ.get(OPENHANDS_V37_CANARY_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V37_CANARY_OPT_IN_ENV}=1 is required")
    if campaign_id != OPENHANDS_V37_CANARY_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands v37 campaign identity changed")
    _validated_control_plane_environment()
    if not os.environ.get(OPENHANDS_V19_CANARY_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_V19_CANARY_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands v37 provider environment is incomplete")
    expected = {
        "openhands-sdk": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers": OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"OpenHands v37 {package} version changed")


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
            raise ConfigurationError("OpenHands v37 artifact contains a symlink")
        if not path.is_file():
            continue
        data = path.read_bytes()
        files += 1
        byte_count += len(data)
        if any(value in data for value in values):
            raise ConfigurationError("provider value reached OpenHands v37 artifacts")
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
            raise ConfigurationError("OpenHands v37 required merged path changed")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=repository, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for predecessor in (_V33_AUDIT_MERGE, _V36_AUDIT_MERGE, _V36_ROOT_CAUSE_MERGE):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", predecessor, head],
            cwd=repository,
            check=True,
        )
    v33_audit = (
        repository / "docs/audits/2026-09-01_openhands-v33-codex-free-materialization-passed.md"
    )
    v36_audit = repository / "docs/audits/2026-09-01_openhands-v36-provider-canary-failed-closed.md"
    root_cause = repository / "docs/audits/2026-09-01_openhands-v36-provider-response-root-cause.md"
    if (
        head != upstream
        or len(head) != 40
        or hash_bytes(v33_audit.read_bytes()) != _V33_AUDIT_FILE_SHA256
        or hash_bytes(v36_audit.read_bytes()) != _V36_AUDIT_FILE_SHA256
        or hash_bytes(root_cause.read_bytes()) != _V36_ROOT_CAUSE_FILE_SHA256
    ):
        raise ConfigurationError("OpenHands v37 canary requires clean merged origin/main")
    return head


def _safe_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"OpenHands v37 {label} root is unsafe")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError(f"OpenHands v37 {label} root is unavailable")
    return resolved


def _safe_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"unsafe OpenHands v37 input: {path.name}")
    resolved = path.resolve(strict=True)
    if not 0 < resolved.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError(f"oversized OpenHands v37 input: {resolved.name}")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    resolved = _safe_file(path)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v37 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v37 JSON input is not an object: {resolved.name}")
    return value


def _validated_content_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop(field, None)
    if not isinstance(observed, str) or content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v37 {field} identity changed")
    return {**result, field: observed}


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("OpenHands v37 output must not already exist")
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
            "canary_trajectory_count": sum(
                int(item.get("trajectory_receipt") is not None) for item in attempts
            ),
            "exact_64k_trajectory_count": sum(
                int(item.get("token_receipt") is not None) for item in attempts
            ),
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
            accounting = ExternalAgentAccounting.model_validate(_load_json(path))
            observed_calls = accounting.model_call_count
            if isinstance(observed_calls, bool) or not isinstance(observed_calls, int):
                raise ConfigurationError("OpenHands v37 provider call accounting is missing")
            call_count += observed_calls
            episode_count += 1
    if episode_count == 0:
        receipts = [
            item["protocol_receipt"]
            for item in attempts
            if isinstance(item.get("protocol_receipt"), dict)
        ]
        call_count = sum(int(item["provider_call_count"]) for item in receipts)
        episode_count = len(receipts)
    return {"provider_episode_count": episode_count, "provider_call_count": call_count}


def main() -> int:
    report = collect(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "canary_passed": report["canary_passed"],
                "formal_collection_allowed": report["formal_collection_allowed"],
                "formal_collection_started": report["formal_collection_started"],
                "training_started": report["training_started"],
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
