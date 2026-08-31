#!/usr/bin/env python3
"""Build six Codex-free command images and seal the v32 successor canary contract."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_SAMPLE_INDEX,
    OPENHANDS_V19_CANARY_SEED,
    OPENHANDS_V19_CANARY_VALIDATION_TASK,
    validate_v19_canary_contract,
    validate_v19_qualification_receipt,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock, HweCommandImageLock

OPENHANDS_V32_OPT_IN_ENV = "VERIGYM_MATERIALIZE_OPENHANDS_HWE_V32_CODEX_FREE_CANARY"
OPENHANDS_V32_APPROVAL_FORMAT = (
    "verigym_openhands_hwe_v32_codex_free_canary_materialization_authorization_v1"
)
OPENHANDS_V32_PROGRESS_FORMAT = (
    "verigym_openhands_hwe_v32_codex_free_canary_materialization_progress_v1"
)
OPENHANDS_V32_CATALOG_FORMAT = "verigym_openhands_hwe_v32_command_image_catalog_v1"
OPENHANDS_V32_CONTRACT_FORMAT = "verigym_openhands_hwe_v32_codex_free_canary_contract_v1"
OPENHANDS_V32_IDENTITY = "openhands-hwe-v32-codex-free-canary-materialization-v1"
OPENHANDS_V32_CAMPAIGN_ID = "openhands-hwe-v32-codex-free-required-tool-canary-v1"
OPENHANDS_V32_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v32-codex-free-canary-v1"
OPENHANDS_V32_APPROVAL_HASH = "8e0f3a3057053679dd9781cd45bf663f0f7e0ad364e4e1e52f476ebb4f52c1e4"

_V29_PROGRESS_HASH = "42f85402c9e509a687ec32c953b24a026f978b5bf0684eb877f32876d0d302f0"
_V29_PROGRESS_SHA256 = "f2992d89c13de3ce4a55cb15f4c4985be8c7dd2c0402ea1b675bb793f55b00f2"
_V29_QUALIFICATION_HASH = "3eea3a1b0fc2bb3d2027c4c9c97549012ce32c484b3b7d07bdb15fc5260e59cb"
_V29_QUALIFICATION_SHA256 = "c56201069b55e1eb1bf5d7532dbfe891d54aa562c2ee980a83e3340f3b05d9e8"
_V29_CATALOG_HASH = "7d708bb0c7ac86e0562899e42abce671cde0c9c5b1d96fa21420cfed1fed400f"
_V29_CATALOG_SHA256 = "09abccc6d25f20abd9866d9bd8a7004727566a10bf3aa87af02077637931836a"
_V29_CONTRACT_HASH = "cf6ba5b011f35ec958eaef319ee79ee4f8cd2fcbab77f0dae62f6dbd2c202efc"
_V29_CONTRACT_SHA256 = "c65e4f10d243c0efb3e56fb2217c4c65f350cd58cd51aa0f69b13b3f12854a8a"
_V29_AUDIT_MERGE = "33b30172999ef5b7e99e0df26d709deaf6bcd117"
_V30_REPORT_HASH = "da246599e8f2a0553d54771fa0f8f6e15a7167f9290c07bac23533f81144bb76"
_V30_REPORT_SHA256 = "68df4079a1a12e278f596b481282c9d6128ac7f1a5b125acafcf5dbfd175e017"
_V30_AUDIT_MERGE = "ac6e604a15be1901c0d3ac7be4576ae14b292d1a"
_RUNTIME_FIX_MERGE = "54d25fe88da82ea1bbc57842ef8ed4a4250387f7"
_RG_VERSION = "ripgrep 15.2.0 (rev e89fff89ac)"
_RG_SHA256 = "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
_RG_ARCHIVE_SHA256 = "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
_MAX_JSON_BYTES = 16 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v32_codex_free_canary_materialization_v1.json",
    "docker/cva6-hwe-command/Dockerfile",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_command_runtime.py",
    "scripts/build_cva6_hwe_command_image.sh",
    "scripts/materialize_cva6_openhands_v32_codex_free_canary.py",
    "scripts/scan_and_lock_cva6_hwe_command_image.py",
    "src/verigym/runtimes/docker/episode_command.py",
)


def _task(number: int) -> str:
    return f"hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-{number}"


_TRAINING_RESERVES = (_task(2330), _task(3226), _task(3231))
_VALIDATION_RESERVES = (_task(2989), _task(3059))
_RESERVES = (*_TRAINING_RESERVES, *_VALIDATION_RESERVES)
_CANARY_VALIDATION = OPENHANDS_V19_CANARY_VALIDATION_TASK
_IMAGE_TASKS = (*_RESERVES, _CANARY_VALIDATION)
_CANARY_TASKS = (_TRAINING_RESERVES[0], _CANARY_VALIDATION)
_TAG_NAMESPACE = "verigym/cva6-openhands-v32-command"

_LEGACY_INPUTS: dict[str, dict[str, str]] = {
    _task(2330): {
        "file_sha256": "38776012996f20a2ac8d34a1bf5c80d77db9303d2132921d6dfcb064386a3f46",
        "lock_hash": "e26ca258478f3182d3ebf145ae17451fea22522f74ae5eb4b3c7af5dc4b26036",
        "task_hash": "c0ce40d1c733daf1f48ab7c4f357839b7738ac3174c318ba77697ffc70032fba",
        "source_hash": "b2682457ca342f6548850c2e83d1a7eea60bff7dec99f168eb6b9a75c9054c7b",
        "verifier_image": "sha256:bd04dfaa28bf30b408365e26b31bc829a2d3c729e3ea5321522289c583b1dcf9",
    },
    _task(3226): {
        "file_sha256": "b6c41c6618c0c057d6108109f18a67b976e5bbeba6bc1ce52ce8990f5926d34a",
        "lock_hash": "71f05955ded644c97d85ec53aafb89fc2675498103a4839a36009a40ec5f0926",
        "task_hash": "47cd8b6b6964b337751528bd7479dc9fb8e7f18cbdef1bf605bd70acd6e70fad",
        "source_hash": "b6a03041571bfbd70cbea308f358747efce9001685f1104ff411306e51bbafa9",
        "verifier_image": "sha256:ba05f4c8a52ffe566161af9fd1b654690019837509e6d0a5797a4b4b9e959ad8",
    },
    _task(3231): {
        "file_sha256": "39d0107eee9943c81b4152ed926edc224ee359ea24a06f001a164275813186bd",
        "lock_hash": "4318625b6d93f680fa4ae19285c28cde504d68965cca17f2b8b0b4a620df4576",
        "task_hash": "6597b3856b61cca5608ca1591a1df9ef911f930578a87fe1f57fbcba1745f913",
        "source_hash": "400347869b2873f624202d475d9fd677dda3789ba2751f7d77c226bce5057cb6",
        "verifier_image": "sha256:ab7533912960b0fe851b446c85569b5994e1c7c3321449dcc7dfc6ab7e2af34d",
    },
    _task(2989): {
        "file_sha256": "ebbab5bb45be755c3807b49b9389548a741f1b0f3a774ce432f84be65c52140d",
        "lock_hash": "cae38b4a1cf018929ad14edb8aaea06512c088585ec9560f1cffc315395d027b",
        "task_hash": "1c4dcc4c8ba5bed7b8b5342a1752350ae0447fe2101adb7e3f77c85151e368c0",
        "source_hash": "8c8c4c95bd12348a232e9d85c9da430ad3378bb3e9f65e87c4825154a91bbe24",
        "verifier_image": "sha256:80542137a7ac8379c7ee2fd7f851f3aad3bf3e857da85c6292503ccfdb47c260",
    },
    _task(3059): {
        "file_sha256": "7de070d9b073db665c64ca23127432770eb615b534e24583470b0ad9b57d1708",
        "lock_hash": "824c5df9a84b2f91bc545e79930d280fac8d24a2b8cc5d630d88a88f469c772f",
        "task_hash": "c1549938585e9152fa30898df196e312a45836062e03f2a35bb28d4896fba7e0",
        "source_hash": "e5c320e0beaaba4e4c473da9c695db5ffdabb537c29e89d8d48bb8be9e8422b5",
        "verifier_image": "sha256:c4c9b688bec8e6a8f730bc7b1e5aad6766cbd22c74b5d1cbdcfdd8ba59565479",
    },
    _task(3204): {
        "file_sha256": "55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b",
        "lock_hash": "b3fe6732fe4d9b52a6444cda90b25add311665af537acf6b389ad1fdafa1933b",
        "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
        "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
        "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
    },
}

_EXPECTED_TEACHER = {
    "model": "openai/deepseek-v4-flash",
    "model_identity": "deepseek-v4-flash",
    "openhands_sdk_version": "1.42.1",
    "litellm_version": "1.93.0",
    "tiktoken_version": "0.7.0",
    "temperature": 0,
    "tool_choice_policy": "required_tool_content_recovery_v19",
    "max_provider_calls": 64,
    "max_provider_tokens": 1_000_000,
    "max_context_tokens": 65_536,
    "max_output_tokens": 2_048,
    "provider_request_retries": 0,
    "whole_episode_retries": 0,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--v29-root", type=Path, required=True)
    parser.add_argument("--v30-root", type=Path, required=True)
    parser.add_argument("--validation-image-lock", type=Path, required=True)
    parser.add_argument("--rg-binary", type=Path, required=True)
    parser.add_argument("--rg-release-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the authorized zero-provider command-image materialization."""

    if os.environ.get(OPENHANDS_V32_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V32_OPT_IN_ENV}=1 is required")
    authorization = _validated_authorization(_load_json(_safe_file(arguments.authorization)))
    source_commit = _merged_source_commit()
    v29 = _safe_directory(arguments.v29_root, "v29 materialization")
    v30 = _safe_directory(arguments.v30_root, "v30 stopped canary")
    qualification, prior_contract = _validated_prior_evidence(v29, v30)
    legacy_locks = _validated_legacy_locks(v29, _safe_file(arguments.validation_image_lock))
    rg_binary = _safe_executable(arguments.rg_binary)
    rg_archive = _safe_file(arguments.rg_release_archive)
    if (
        hash_bytes(rg_binary.read_bytes()) != _RG_SHA256
        or hash_bytes(rg_archive.read_bytes()) != _RG_ARCHIVE_SHA256
    ):
        raise ConfigurationError("OpenHands v32 ripgrep release identity changed")

    root = _new_directory(arguments.output)
    for name in ("image-receipts", "security-scans", "image-locks"):
        (root / name).mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V32_PROGRESS_FORMAT,
        "identity": OPENHANDS_V32_IDENTITY,
        "status": "materialization_running",
        "authorization_hash": authorization["authorization_hash"],
        "source_commit": source_commit,
        "v29_qualification_receipt_hash": qualification["receipt_hash"],
        "v29_canary_contract_hash": prior_contract["contract_hash"],
        "v30_stopped_report_hash": _V30_REPORT_HASH,
        "runtime_fix_merge_commit": _RUNTIME_FIX_MERGE,
        "task_ids": list(_IMAGE_TASKS),
        "active_task_id": None,
        "locks": {},
        "build_network": "none",
        "runtime_network": "none",
        "command_execution_backend": "episode_container_exec_v1",
        "provider_calls": 0,
        "model_process_count": 0,
        "heldout_task_ids_loaded": [],
        "canary_executed": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    _write_progress(root, progress)
    repository = Path(__file__).resolve().parents[1]
    for task_id in _IMAGE_TASKS:
        progress["active_task_id"] = task_id
        _write_progress(root, progress)
        try:
            lock = _build_one(
                root=root,
                repository=repository,
                legacy=legacy_locks[task_id],
                rg_binary=rg_binary,
                rg_archive=rg_archive,
            )
        except (Exception, KeyboardInterrupt) as exc:
            progress.update(
                {
                    "status": "stopped_security_or_infrastructure_invalid",
                    "active_task_id": None,
                    "failure_task_id": task_id,
                    "failure_type": type(exc).__name__,
                }
            )
            _write_progress(root, progress)
            raise ConfigurationError(
                f"OpenHands v32 command-image materialization stopped on {task_id}"
            ) from exc
        suffix = task_id.rsplit("-", 1)[-1]
        lock_path = root / "image-locks" / f"pr-{suffix}.json"
        progress["locks"][task_id] = {
            "lock": f"image-locks/pr-{suffix}.json",
            "lock_file_sha256": hash_bytes(lock_path.read_bytes()),
            "lock_hash": lock.lock_hash,
            "command_image": lock.derived_command_image_id,
            "verifier_image": lock.verifier_base_image_id,
            "security_scan_id": lock.security_scan_id,
        }
        progress["active_task_id"] = None
        _write_progress(root, progress)

    image_ids = [item["command_image"] for item in progress["locks"].values()]
    if len(set(image_ids)) != len(_IMAGE_TASKS):
        progress["status"] = "stopped_security_invalid"
        _write_progress(root, progress)
        raise ConfigurationError("OpenHands v32 command images are not task-distinct")
    command_locks = {
        task_id: HweCommandImageLock.model_validate(
            _load_json(root / str(progress["locks"][task_id]["lock"]))
        )
        for task_id in _IMAGE_TASKS
    }
    catalog = _command_catalog(legacy_locks, command_locks, progress["locks"])
    contract = _canary_contract(qualification, prior_contract, command_locks)
    atomic_dump_json(root / "command-image-catalog.json", catalog)
    atomic_dump_json(root / "canary-contract.json", contract)
    progress.update(
        {
            "status": "completed_codex_free_canary_contract_materialized",
            "command_image_catalog_hash": catalog["catalog_hash"],
            "canary_contract_hash": contract["contract_hash"],
        }
    )
    _write_progress(root, progress)
    return _sealed(progress)


def _build_one(
    *,
    root: Path,
    repository: Path,
    legacy: HweAgentImageLock,
    rg_binary: Path,
    rg_archive: Path,
) -> HweCommandImageLock:
    task_id = legacy.task_id
    suffix = task_id.rsplit("-", 1)[-1]
    receipt = root / "image-receipts" / f"pr-{suffix}.json"
    scan = root / "security-scans" / f"pr-{suffix}.json"
    lock_path = root / "image-locks" / f"pr-{suffix}.json"
    legacy_path = root / f".legacy-pr-{suffix}.json"
    atomic_dump_json(legacy_path, legacy.model_dump(mode="json"))
    image_tag = f"{_TAG_NAMESPACE}-pr-{suffix}:rg-15.2.0-v1"
    try:
        subprocess.run(
            [
                str(repository / "scripts/build_cva6_hwe_command_image.sh"),
                str(rg_binary),
                str(rg_archive),
                legacy.verifier_base_image_id,
                task_id,
                image_tag,
                str(receipt),
            ],
            cwd=repository,
            check=True,
            timeout=1_800,
        )
        subprocess.run(
            [
                sys.executable,
                str(repository / "scripts/scan_and_lock_cva6_hwe_command_image.py"),
                "--receipt",
                str(receipt),
                "--identity-lock",
                str(legacy_path),
                "--security-scan-output",
                str(scan),
                "--lock-output",
                str(lock_path),
            ],
            cwd=repository,
            check=True,
            timeout=600,
        )
    finally:
        legacy_path.unlink(missing_ok=True)
    lock = HweCommandImageLock.model_validate(_load_json(lock_path))
    _validate_final_lock(lock, legacy=legacy)
    return lock


def _validate_final_lock(lock: HweCommandImageLock, *, legacy: HweAgentImageLock) -> None:
    if (
        lock.task_id != legacy.task_id
        or lock.task_hash != legacy.task_hash
        or lock.source_hash != legacy.source_hash
        or lock.verifier_base_image_id != legacy.verifier_base_image_id
        or lock.rg_sha256 != _RG_SHA256
        or lock.rg_release_archive_sha256 != _RG_ARCHIVE_SHA256
        or lock.supported_execution_backends
        != ("ephemeral_container_v1", "episode_container_exec_v1")
        or lock.codex_present is not False
        or lock.provider_credentials_present is not False
        or lock.hidden_assets_present is not False
        or lock.verifier_payload_present is not False
        or lock.reference_patch_present is not False
        or lock.security_scan_passed is not True
        or lock.build_network != "none"
        or lock.runtime_network != "none"
    ):
        raise ConfigurationError("OpenHands v32 command-image lock binding changed")


def _command_catalog(
    legacy: dict[str, HweAgentImageLock],
    commands: dict[str, HweCommandImageLock],
    progress_locks: dict[str, dict[str, str]],
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for task_id in _IMAGE_TASKS:
        role = (
            "training_reserve"
            if task_id in _TRAINING_RESERVES
            else "validation_reserve"
            if task_id in _VALIDATION_RESERVES
            else "canary_validation"
        )
        tasks.append(
            {
                "task_id": task_id,
                "role": role,
                "task_hash": commands[task_id].task_hash,
                "source_hash": commands[task_id].source_hash,
                "verifier_image": commands[task_id].verifier_base_image_id,
                "legacy_agent_lock_hash": legacy[task_id].lock_hash,
                "command_image_lock": progress_locks[task_id]["lock"],
                "command_image_lock_file_sha256": progress_locks[task_id]["lock_file_sha256"],
                "command_image_lock_hash": commands[task_id].lock_hash,
                "command_image": commands[task_id].derived_command_image_id,
                "security_scan_id": commands[task_id].security_scan_id,
            }
        )
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V32_CATALOG_FORMAT,
        "task_count": len(tasks),
        "tasks": tasks,
        "training_reserve_task_ids": list(_TRAINING_RESERVES),
        "validation_reserve_task_ids": list(_VALIDATION_RESERVES),
        "canary_validation_task_id": _CANARY_VALIDATION,
        "codex_present": False,
        "provider_credentials_present": False,
        "command_execution_backend": "episode_container_exec_v1",
        "build_network": "none",
        "runtime_network": "none",
    }
    return {**base, "catalog_hash": content_hash(base)}


def _canary_contract(
    qualification: dict[str, Any],
    prior_contract: dict[str, Any],
    commands: dict[str, HweCommandImageLock],
) -> dict[str, Any]:
    bindings: dict[str, dict[str, str]] = {}
    for task_id in _CANARY_TASKS:
        lock = commands[task_id]
        bindings[task_id] = {
            "task_hash": lock.task_hash,
            "source_hash": lock.source_hash,
            "verifier_image": lock.verifier_base_image_id,
            "command_image": lock.derived_command_image_id,
            "command_image_lock_hash": lock.lock_hash,
            "security_scan_id": lock.security_scan_id,
        }
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V32_CONTRACT_FORMAT,
        "campaign_id": OPENHANDS_V32_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V32_AGENT_VERSION_ID,
        "protocol_profile": "required_tool_content_recovery_v19",
        "predecessor_campaign_id": prior_contract["campaign_id"],
        "predecessor_stopped_without_provider_episode": True,
        "qualification_receipt_hash": qualification["receipt_hash"],
        "schedule": [
            {
                "task_id": _CANARY_TASKS[0],
                "role": "training",
                "seed": OPENHANDS_V19_CANARY_SEED,
                "sample_index": OPENHANDS_V19_CANARY_SAMPLE_INDEX,
            },
            {
                "task_id": _CANARY_TASKS[1],
                "role": "validation",
                "seed": OPENHANDS_V19_CANARY_SEED,
                "sample_index": OPENHANDS_V19_CANARY_SAMPLE_INDEX,
            },
        ],
        "task_bindings": bindings,
        "teacher": copy.deepcopy(_EXPECTED_TEACHER),
        "runtime": {
            "command_role": "credential_free_command_image",
            "command_execution_backend": "episode_container_exec_v1",
            "external_agent_process_available": False,
            "codex_cli_required": False,
            "codex_login_required": False,
            "provider_credentials_in_command_container": False,
            "network": "none",
        },
        "gate": copy.deepcopy(prior_contract["gate"]),
        "heldout_task_ids_loaded": [],
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    return validate_v32_canary_contract({**base, "contract_hash": content_hash(base)})


def validate_v32_canary_contract(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop("contract_hash", None)
    if not isinstance(observed, str) or content_hash(result) != observed:
        raise ConfigurationError("OpenHands v32 canary contract identity changed")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V32_CONTRACT_FORMAT
        or result.get("campaign_id") != OPENHANDS_V32_CAMPAIGN_ID
        or result.get("agent_version_id") != OPENHANDS_V32_AGENT_VERSION_ID
        or result.get("protocol_profile") != "required_tool_content_recovery_v19"
        or result.get("predecessor_campaign_id") != "openhands-hwe-v19-required-tool-canary-v1"
        or result.get("predecessor_stopped_without_provider_episode") is not True
        or not _hash(result.get("qualification_receipt_hash"))
        or result.get("schedule")
        != [
            {
                "task_id": _CANARY_TASKS[0],
                "role": "training",
                "seed": 489,
                "sample_index": 5,
            },
            {
                "task_id": _CANARY_TASKS[1],
                "role": "validation",
                "seed": 489,
                "sample_index": 5,
            },
        ]
        or result.get("teacher") != _EXPECTED_TEACHER
        or result.get("gate")
        != {
            "all_six_result_planes_required": True,
            "automatic_next_identity_allowed": False,
            "benchmark_or_trajectory_failure_policy": "canary_fail_closed",
            "decision_token_limit": 65536,
            "infrastructure_or_security_failure_policy": "stop_immediately",
            "truncation_allowed": False,
        }
        or result.get("runtime")
        != {
            "command_role": "credential_free_command_image",
            "command_execution_backend": "episode_container_exec_v1",
            "external_agent_process_available": False,
            "codex_cli_required": False,
            "codex_login_required": False,
            "provider_credentials_in_command_container": False,
            "network": "none",
        }
        or result.get("heldout_task_ids_loaded") != []
        or result.get("production_training_ready") is not False
        or result.get("benchmark_score_claimed") is not False
    ):
        raise ConfigurationError("OpenHands v32 canary contract policy changed")
    bindings = result.get("task_bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(_CANARY_TASKS):
        raise ConfigurationError("OpenHands v32 canary command bindings changed")
    for binding in bindings.values():
        if (
            not isinstance(binding, dict)
            or not _hash(binding.get("task_hash"))
            or not _hash(binding.get("source_hash"))
            or not _digest(binding.get("verifier_image"))
            or not _digest(binding.get("command_image"))
            or not _hash(binding.get("command_image_lock_hash"))
            or not _hash(binding.get("security_scan_id"))
            or binding["verifier_image"] == binding["command_image"]
        ):
            raise ConfigurationError("OpenHands v32 canary command binding is malformed")
    result["contract_hash"] = observed
    return result


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop("authorization_hash", None)
    if observed != OPENHANDS_V32_APPROVAL_HASH or content_hash(result) != observed:
        raise ConfigurationError("OpenHands v32 authorization identity changed")
    expected = _expected_authorization()
    if result != expected:
        raise ConfigurationError("OpenHands v32 authorization policy changed")
    return {**result, "authorization_hash": observed}


def _expected_authorization() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V32_APPROVAL_FORMAT,
        "status": "authorized_pending_materialization",
        "identity": OPENHANDS_V32_IDENTITY,
        "prior_evidence": {
            "v29_audit_merge_commit": _V29_AUDIT_MERGE,
            "v29_progress_hash": _V29_PROGRESS_HASH,
            "v29_progress_file_sha256": _V29_PROGRESS_SHA256,
            "v29_qualification_receipt_hash": _V29_QUALIFICATION_HASH,
            "v29_qualification_file_sha256": _V29_QUALIFICATION_SHA256,
            "v29_source_catalog_hash": _V29_CATALOG_HASH,
            "v29_source_catalog_file_sha256": _V29_CATALOG_SHA256,
            "v29_canary_contract_hash": _V29_CONTRACT_HASH,
            "v29_canary_contract_file_sha256": _V29_CONTRACT_SHA256,
            "v30_audit_merge_commit": _V30_AUDIT_MERGE,
            "v30_report_hash": _V30_REPORT_HASH,
            "v30_report_file_sha256": _V30_REPORT_SHA256,
            "v30_status": "stopped_infrastructure_invalid",
            "v30_provider_episode_count": 0,
            "runtime_fix_merge_commit": _RUNTIME_FIX_MERGE,
        },
        "preauthorization_diagnostic": {
            "identity": "openhands-hwe-v31-codex-free-canary-materialization-v1",
            "status": "stopped_local_premerge_gate_regression",
            "source_commit": _RUNTIME_FIX_MERGE,
            "failure_task_id": _task(2330),
            "failure_stage": "sanitize_unsanitized_command_image",
            "failure_type": "KeyboardInterrupt",
            "progress_hash": "5fe56ffedb704e528e12bc8741059c6c252e46c8c4db3fa2eb51f0d2e9915046",
            "progress_file_sha256": (
                "4d3c690d23a1b575cc902467586236b10776753e4e64c0b13d5a9c6a0272ccb9"
            ),
            "discarded_tag_namespace": "verigym/cva6-openhands-v31-command",
            "discarded_unsanitized_image_id": (
                "sha256:191a9603e4d37cfb4d822ead20b8181f43fbdfb9f578b5928e1eb80c0aaea4c8"
            ),
            "provider_calls": 0,
            "model_process_count": 0,
            "canary_executed": False,
            "reuse_allowed": False,
        },
        "legacy_image_locks": [
            {"task_id": task_id, **copy.deepcopy(_LEGACY_INPUTS[task_id])}
            for task_id in _IMAGE_TASKS
        ],
        "command_image_inputs": {
            "image_count": 6,
            "ripgrep_version": _RG_VERSION,
            "ripgrep_binary_sha256": _RG_SHA256,
            "ripgrep_release_archive_sha256": _RG_ARCHIVE_SHA256,
            "tag_namespace": _TAG_NAMESPACE,
            "build_network": "none",
            "runtime_network": "none",
            "execution_backend": "episode_container_exec_v1",
            "codex_present": False,
        },
        "canary_contract": {
            "campaign_id": OPENHANDS_V32_CAMPAIGN_ID,
            "agent_version_id": OPENHANDS_V32_AGENT_VERSION_ID,
            "protocol_profile": "required_tool_content_recovery_v19",
            "task_ids": list(_CANARY_TASKS),
            "roles": ["training", "validation"],
            "seed": 489,
            "sample_index": 5,
            "provider_calls_during_materialization": 0,
        },
        "required_controls": {
            "clean_merged_source_commit": True,
            "historical_tasks_retried": False,
            "historical_evidence_relabelled": False,
            "one_distinct_command_image_per_task": True,
            "task_source_verifier_binding_exact": True,
            "build_network_none": True,
            "runtime_network_none": True,
            "image_security_scan_required": True,
            "codex_binary_absent": True,
            "provider_credentials_absent": True,
            "atomic_progress": True,
            "heldout_tasks_loaded": False,
        },
        "authorized_actions": {
            "consume_sealed_v29_evidence": True,
            "record_sealed_v30_stop": True,
            "build_six_command_images": True,
            "scan_six_command_images": True,
            "materialize_successor_canary_contract": True,
            "invoke_provider": False,
            "execute_canary": False,
            "start_collection": False,
            "start_training": False,
            "load_heldout_tasks": False,
        },
        "failure_policy": "stop_immediately_no_retry",
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }


def _validated_prior_evidence(v29: Path, v30: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    progress_path = _safe_child(v29, "materialization-progress.json")
    qualification_path = _safe_child(v29, "qualification-receipt.json")
    catalog_path = _safe_child(v29, "source-catalog.json")
    contract_path = _safe_child(v29, "canary-contract.json")
    report_path = _safe_child(v30, "canary-report.json")
    expected_files = {
        progress_path: _V29_PROGRESS_SHA256,
        qualification_path: _V29_QUALIFICATION_SHA256,
        catalog_path: _V29_CATALOG_SHA256,
        contract_path: _V29_CONTRACT_SHA256,
        report_path: _V30_REPORT_SHA256,
    }
    if any(hash_bytes(path.read_bytes()) != digest for path, digest in expected_files.items()):
        raise ConfigurationError("OpenHands v32 predecessor evidence file changed")
    progress = _load_json(progress_path)
    qualification = validate_v19_qualification_receipt(_load_json(qualification_path))
    catalog = _validated_content_hash(_load_json(catalog_path), "catalog_hash")
    prior_contract = validate_v19_canary_contract(_load_json(contract_path))
    report = _validated_content_hash(_load_json(report_path), "report_hash")
    if (
        progress.get("progress_hash") != _V29_PROGRESS_HASH
        or progress.get("status") != "completed_canary_contract_materialized"
        or qualification.get("receipt_hash") != _V29_QUALIFICATION_HASH
        or catalog.get("catalog_hash") != _V29_CATALOG_HASH
        or prior_contract.get("contract_hash") != _V29_CONTRACT_HASH
        or report.get("report_hash") != _V30_REPORT_HASH
        or report.get("status") != "stopped_infrastructure_invalid"
        or report.get("attempts") != []
        or report.get("provider_call_count") != 0
        or report.get("provider_episode_count") != 0
        or report.get("heldout_task_ids_loaded") != []
        or report.get("collection_started") is not False
        or report.get("training_started") is not False
    ):
        raise ConfigurationError("OpenHands v32 predecessor evidence state changed")
    return qualification, prior_contract


def _validated_legacy_locks(v29: Path, validation_path: Path) -> dict[str, HweAgentImageLock]:
    locks: dict[str, HweAgentImageLock] = {}
    for task_id in _IMAGE_TASKS:
        suffix = task_id.rsplit("-", 1)[-1]
        path = (
            validation_path
            if task_id == _CANARY_VALIDATION
            else _safe_child(v29, f"image-locks/pr-{suffix}.json")
        )
        expected = _LEGACY_INPUTS[task_id]
        if hash_bytes(path.read_bytes()) != expected["file_sha256"]:
            raise ConfigurationError("OpenHands v32 legacy image-lock file changed")
        lock = HweAgentImageLock.model_validate(_load_json(path))
        if (
            lock.task_id != task_id
            or lock.lock_hash != expected["lock_hash"]
            or lock.task_hash != expected["task_hash"]
            or lock.source_hash != expected["source_hash"]
            or lock.verifier_base_image_id != expected["verifier_image"]
            or lock.security_scan_passed is not True
            or lock.runtime_network != "none"
        ):
            raise ConfigurationError("OpenHands v32 legacy image-lock binding changed")
        locks[task_id] = lock
    return locks


def _validated_content_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop(field, None)
    if not isinstance(observed, str) or content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v32 predecessor {field} changed")
    result[field] = observed
    return result


def _write_progress(root: Path, progress: dict[str, Any]) -> None:
    atomic_dump_json(root / "materialization-progress.json", _sealed(progress))


def _sealed(value: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(value)
    base.pop("progress_hash", None)
    return {**base, "progress_hash": content_hash(base)}


def _merged_source_commit() -> str:
    repository = Path(__file__).resolve().parents[1]
    try:
        _require_tracked_merged_paths(repository)
        subprocess.run(
            ["git", "diff", "--quiet", "--no-ext-diff", "--"], cwd=repository, check=True
        )
        subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--no-ext-diff", "--"],
            cwd=repository,
            check=True,
        )
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
    except subprocess.CalledProcessError as exc:
        raise ConfigurationError(
            "OpenHands v32 requires tracked, unchanged runtime and authorization files"
        ) from exc
    if head != upstream or len(head) != 40:
        raise ConfigurationError("OpenHands v32 requires the clean merged main commit")
    return head


def _require_tracked_merged_paths(repository: Path) -> None:
    for relative in _REQUIRED_MERGED_PATHS:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != relative:
            raise ConfigurationError("OpenHands v32 required merged path identity changed")
    subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", "HEAD", "--", *_REQUIRED_MERGED_PATHS],
        cwd=repository,
        check=True,
    )


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError("OpenHands v32 JSON input is unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError("OpenHands v32 JSON input is not an object")
    return value


def _safe_file(path: Path) -> Path:
    if path.is_symlink():
        raise ConfigurationError("OpenHands v32 input file must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ConfigurationError("OpenHands v32 input file is unavailable")
    return resolved


def _safe_executable(path: Path) -> Path:
    resolved = _safe_file(path)
    if not os.access(resolved, os.X_OK):
        raise ConfigurationError("OpenHands v32 ripgrep binary is not executable")
    return resolved


def _safe_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"OpenHands v32 {label} root must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError(f"OpenHands v32 {label} root is unavailable")
    return resolved


def _safe_child(root: Path, relative: str) -> Path:
    candidate = root / relative
    if candidate.is_symlink():
        raise ConfigurationError("OpenHands v32 evidence path contains a symlink")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ConfigurationError("OpenHands v32 evidence path escaped its root")
    return resolved


def _new_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("OpenHands v32 output must be a new directory")
    parent = path.parent.resolve(strict=True)
    root = parent / path.name
    root.mkdir(mode=0o700)
    return root


def _hash(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _digest(value: object) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and _hash(value[7:])


def main() -> int:
    result = materialize(_parser().parse_args())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
