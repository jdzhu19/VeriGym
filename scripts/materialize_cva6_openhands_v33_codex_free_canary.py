#!/usr/bin/env python3
"""Build six Codex-free command images and seal the v33 successor canary contract."""

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
from verigym.hwe.materialization_preflight import (
    MaterializationHeadroomError,
    discover_docker_root,
    require_materialization_headroom,
)

OPENHANDS_V33_OPT_IN_ENV = "VERIGYM_MATERIALIZE_OPENHANDS_HWE_V33_CODEX_FREE_CANARY"
OPENHANDS_V33_APPROVAL_FORMAT = (
    "verigym_openhands_hwe_v33_codex_free_canary_materialization_authorization_v1"
)
OPENHANDS_V33_PROGRESS_FORMAT = (
    "verigym_openhands_hwe_v33_codex_free_canary_materialization_progress_v1"
)
OPENHANDS_V33_CATALOG_FORMAT = "verigym_openhands_hwe_v33_command_image_catalog_v1"
OPENHANDS_V33_CONTRACT_FORMAT = "verigym_openhands_hwe_v33_codex_free_canary_contract_v1"
OPENHANDS_V33_IDENTITY = "openhands-hwe-v33-codex-free-canary-materialization-v1"
OPENHANDS_V33_CAMPAIGN_ID = "openhands-hwe-v33-codex-free-required-tool-canary-v1"
OPENHANDS_V33_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v33-codex-free-canary-v1"
OPENHANDS_V33_APPROVAL_HASH = "79cca2864460c0b6ca4d4d8902e4f7be1cb6ae8296743b6b1409b2e3725deb17"

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
_V32_AUDIT_MERGE = "d4b37fb1cfbcb8df0d51fcc995a40d73b79981f6"
_V32_PROGRESS_HASH = "4d713ed9faa05104a9fcee28a559158d1af03e19915986aedbeacb9672e1942b"
_V32_PROGRESS_SHA256 = "27c48e0ff1a2905ba4a3f6f7e2ed1defe17c1746c4a7d01de97fd2ff869d0583"
_V32_RECEIPT_SHA256 = "45fa97a18ed0c7b2e5e540f6d101e972ea928ec401a6ba8400effd0d7cdb5959"
_V32_FAILED_COMMAND_IMAGE = (
    "sha256:10ff15403de96b2db89e7c48167d0ea968ea8e83ed8be33cc06536ecd755869e"
)
_V32_FAILED_UNSANITIZED_IMAGE = (
    "sha256:2368312010a59bcd548219cf1f1a69a4eaffa94a152dc787b04763d428090064"
)
_MATERIALIZATION_FIX_MERGE = "066212da8adcc9293948bcbf350c4dfeccffa489"
_PREAUTH_HEADROOM_HASH = "ae63e24aca016abbabb8d988f66717bc53916cc01646a26b2d36b7e36b7f6960"
_PREAUTH_HEADROOM_SHA256 = "98f79f4e7ff324985d2fdcd53eb641ef6f4f0c28a320536fa8fe1a6e7c736fdf"
_RG_VERSION = "ripgrep 15.2.0 (rev e89fff89ac)"
_RG_SHA256 = "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
_RG_ARCHIVE_SHA256 = "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
_MAX_JSON_BYTES = 16 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v33_codex_free_canary_materialization_v1.json",
    "docker/cva6-hwe-command/Dockerfile",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_command_runtime.py",
    "scripts/build_cva6_hwe_command_image.sh",
    "scripts/materialize_cva6_openhands_v33_codex_free_canary.py",
    "scripts/scan_and_lock_cva6_hwe_command_image.py",
    "src/verigym/hwe/materialization_preflight.py",
    "src/verigym/runtimes/docker/episode_command.py",
)

_HEADROOM_POLICY = {
    "absolute_thresholds": True,
    "percentage_thresholds": False,
    "planned_command_image_count": 6,
    "maximum_bytes_per_command_image": 8 * 1024**3,
    "docker_headroom_multiplier": 2,
}
_HEADROOM_REQUIREMENTS: tuple[dict[str, str | int], ...] = (
    {"role": "control_root", "minimum_free_bytes": 4 * 1024**3, "minimum_free_inodes": 100_000},
    {
        "role": "docker_root",
        "minimum_free_bytes": 96 * 1024**3,
        "minimum_free_inodes": 250_000,
    },
    {"role": "scratch_root", "minimum_free_bytes": 8 * 1024**3, "minimum_free_inodes": 50_000},
    {"role": "output_parent", "minimum_free_bytes": 2 * 1024**3, "minimum_free_inodes": 10_000},
)
_DIAGNOSTIC_FAILURE_STAGES = {
    "container_cleanup",
    "container_control_inspection",
    "container_diagnostic_start",
    "container_state_inspection",
    "docker_create",
    "unknown",
    "workspace_cleanup",
    "workspace_proof_validation",
}
_DIAGNOSTIC_ERROR_CATEGORIES = {
    "container_assertion_failed",
    "container_cleanup_failed",
    "container_command_failed",
    "container_controls_invalid",
    "container_inspect_failed",
    "diagnostic_output_over_bound",
    "docker_create_failed",
    "docker_create_output_invalid",
    "docker_start_failed",
    "docker_start_timeout",
    "unexpected_command_output",
    "unknown",
    "workspace_cleanup_failed",
    "workspace_proof_missing",
}
_DIAGNOSTIC_ASSERTION_IDS = {
    "allowlisted_artifact_hash_exact",
    "codex_auth_absent",
    "codex_command_absent",
    "codex_executable_absent",
    "codex_library_absent",
    "container_parent_readable",
    "hidden_verifier_absent",
    "keepalive_available",
    "legacy_source_marker_absent",
    "make_available",
    "non_root_identity",
    "public_payload_absent",
    "reference_patch_absent",
    "repository_parent_visible",
    "ripgrep_hash_exact",
    "ripgrep_version_exact",
    "rootfs_write_rejected",
    "source_whiteout_directory_present",
    "source_whiteout_empty",
    "tmp_writable",
    "verifier_workspace_absent",
    "verilator_binary_available",
    "verilator_wrapper_available",
    "workspace_writable",
}


def _task(number: int) -> str:
    return f"hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-{number}"


_TRAINING_RESERVES = (_task(2330), _task(3226), _task(3231))
_VALIDATION_RESERVES = (_task(2989), _task(3059))
_RESERVES = (*_TRAINING_RESERVES, *_VALIDATION_RESERVES)
_CANARY_VALIDATION = OPENHANDS_V19_CANARY_VALIDATION_TASK
_IMAGE_TASKS = (*_RESERVES, _CANARY_VALIDATION)
_CANARY_TASKS = (_TRAINING_RESERVES[0], _CANARY_VALIDATION)
_TAG_NAMESPACE = "verigym/cva6-openhands-v33-command"

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
    parser.add_argument("--v32-root", type=Path, required=True)
    parser.add_argument("--validation-image-lock", type=Path, required=True)
    parser.add_argument("--rg-binary", type=Path, required=True)
    parser.add_argument("--rg-release-archive", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the authorized zero-provider command-image materialization."""

    if os.environ.get(OPENHANDS_V33_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V33_OPT_IN_ENV}=1 is required")
    authorization = _validated_authorization(_load_json(_safe_file(arguments.authorization)))
    source_commit = _merged_source_commit()
    v29 = _safe_directory(arguments.v29_root, "v29 materialization")
    v30 = _safe_directory(arguments.v30_root, "v30 stopped canary")
    v32 = _safe_directory(arguments.v32_root, "v32 stopped materialization")
    qualification, prior_contract = _validated_prior_evidence(v29, v30)
    _validate_v32_stop(v32)
    legacy_locks = _validated_legacy_locks(v29, _safe_file(arguments.validation_image_lock))
    scratch_root = _safe_directory(arguments.scratch_root, "command-image scratch")
    rg_binary = _safe_executable(arguments.rg_binary)
    rg_archive = _safe_file(arguments.rg_release_archive)
    if (
        hash_bytes(rg_binary.read_bytes()) != _RG_SHA256
        or hash_bytes(rg_archive.read_bytes()) != _RG_ARCHIVE_SHA256
    ):
        raise ConfigurationError("OpenHands v33 ripgrep release identity changed")

    root = _new_directory(arguments.output)
    for name in ("image-receipts", "security-scans", "image-locks"):
        (root / name).mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V33_PROGRESS_FORMAT,
        "identity": OPENHANDS_V33_IDENTITY,
        "status": "headroom_preflight_running",
        "authorization_hash": authorization["authorization_hash"],
        "source_commit": source_commit,
        "v29_qualification_receipt_hash": qualification["receipt_hash"],
        "v29_canary_contract_hash": prior_contract["contract_hash"],
        "v30_stopped_report_hash": _V30_REPORT_HASH,
        "v32_stopped_progress_hash": _V32_PROGRESS_HASH,
        "runtime_fix_merge_commit": _RUNTIME_FIX_MERGE,
        "materialization_fix_merge_commit": _MATERIALIZATION_FIX_MERGE,
        "headroom_preflight_hash": None,
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
    try:
        headroom = require_materialization_headroom(
            control_root=Path("/"),
            docker_root=discover_docker_root(),
            scratch_root=scratch_root,
            output_parent=root.parent,
        )
    except MaterializationHeadroomError as exc:
        atomic_dump_json(root / "headroom-preflight.json", exc.receipt)
        progress.update(
            {
                "status": "stopped_insufficient_headroom",
                "headroom_preflight_hash": exc.receipt["preflight_hash"],
                "failure_stage": "headroom_preflight",
                "failure_type": type(exc).__name__,
            }
        )
        _write_progress(root, progress)
        raise ConfigurationError("OpenHands v33 materialization headroom was rejected") from None
    except (Exception, KeyboardInterrupt) as exc:
        progress.update(
            {
                "status": "stopped_infrastructure_invalid",
                "failure_stage": "headroom_preflight",
                "failure_type": type(exc).__name__,
            }
        )
        _write_progress(root, progress)
        raise ConfigurationError("OpenHands v33 headroom preflight failed") from None
    atomic_dump_json(root / "headroom-preflight.json", headroom)
    try:
        headroom = _validated_headroom_receipt(headroom)
    except ConfigurationError:
        progress.update(
            {
                "status": "stopped_policy_invalid",
                "failure_stage": "headroom_preflight",
                "failure_type": "PolicyMismatch",
            }
        )
        _write_progress(root, progress)
        raise ConfigurationError("OpenHands v33 headroom policy changed") from None
    progress.update(
        {
            "status": "materialization_running",
            "headroom_preflight_hash": headroom["preflight_hash"],
        }
    )
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
            diagnostic = _failure_diagnostic(root, task_id)
            progress.update(
                {
                    "status": "stopped_security_or_infrastructure_invalid",
                    "active_task_id": None,
                    "failure_task_id": task_id,
                    "failure_type": type(exc).__name__,
                    "failure_diagnostic": diagnostic,
                }
            )
            _write_progress(root, progress)
            raise ConfigurationError(
                f"OpenHands v33 command-image materialization stopped on {task_id}"
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
        raise ConfigurationError("OpenHands v33 command images are not task-distinct")
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
    _validate_passed_security_scan(scan, lock)
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
        raise ConfigurationError("OpenHands v33 command-image lock binding changed")


def _validate_passed_security_scan(path: Path, lock: HweCommandImageLock) -> None:
    scan = _validated_content_hash(_load_json(path), "security_scan_id")
    diagnostic = _validated_content_hash(scan["diagnostic"], "diagnostic_hash")
    if (
        scan.get("format_id") != "verigym_hwe_command_image_security_scan_v2"
        or scan.get("scanner_profile_id") != "cva6-hwe-command-container-native-offline-v2"
        or scan.get("task_id") != lock.task_id
        or scan.get("derived_command_image_id") != lock.derived_command_image_id
        or scan.get("security_scan_id") != lock.security_scan_id
        or scan.get("scan_passed") is not True
        or scan.get("secrets_detected") is not False
        or diagnostic.get("format_id") != "verigym_hwe_command_image_diagnostic_v2"
        or diagnostic.get("status") != "passed"
        or diagnostic.get("failure_stage") is not None
        or diagnostic.get("error_category") is not None
        or diagnostic.get("assertion_id") is not None
        or diagnostic.get("exit_code") != 0
        or diagnostic.get("container_exit_code") != 0
        or diagnostic.get("temporary_container_removed") is not True
        or diagnostic.get("temporary_workspace_removed") is not True
        or diagnostic.get("raw_output_persisted") is not False
        or diagnostic.get("create_nonempty_output_hashed") is not False
        or diagnostic.get("nonempty_output_hashed") is not False
        or diagnostic.get("cleanup_nonempty_output_hashed") is not False
    ):
        raise ConfigurationError("OpenHands v33 command-image security receipt changed")


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
        "format_id": OPENHANDS_V33_CATALOG_FORMAT,
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
        "format_id": OPENHANDS_V33_CONTRACT_FORMAT,
        "campaign_id": OPENHANDS_V33_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V33_AGENT_VERSION_ID,
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
    return validate_v33_canary_contract({**base, "contract_hash": content_hash(base)})


def validate_v33_canary_contract(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop("contract_hash", None)
    if not isinstance(observed, str) or content_hash(result) != observed:
        raise ConfigurationError("OpenHands v33 canary contract identity changed")
    if (
        result.get("schema_version") != "1.0"
        or result.get("format_id") != OPENHANDS_V33_CONTRACT_FORMAT
        or result.get("campaign_id") != OPENHANDS_V33_CAMPAIGN_ID
        or result.get("agent_version_id") != OPENHANDS_V33_AGENT_VERSION_ID
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
        raise ConfigurationError("OpenHands v33 canary contract policy changed")
    bindings = result.get("task_bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(_CANARY_TASKS):
        raise ConfigurationError("OpenHands v33 canary command bindings changed")
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
            raise ConfigurationError("OpenHands v33 canary command binding is malformed")
    result["contract_hash"] = observed
    return result


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop("authorization_hash", None)
    if observed != OPENHANDS_V33_APPROVAL_HASH or content_hash(result) != observed:
        raise ConfigurationError("OpenHands v33 authorization identity changed")
    expected = _expected_authorization()
    if result != expected:
        raise ConfigurationError("OpenHands v33 authorization policy changed")
    return {**result, "authorization_hash": observed}


def _expected_authorization() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V33_APPROVAL_FORMAT,
        "status": "authorized_pending_materialization",
        "identity": OPENHANDS_V33_IDENTITY,
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
            "v32_audit_merge_commit": _V32_AUDIT_MERGE,
            "v32_progress_hash": _V32_PROGRESS_HASH,
            "v32_progress_file_sha256": _V32_PROGRESS_SHA256,
            "v32_build_receipt_file_sha256": _V32_RECEIPT_SHA256,
            "v32_status": "stopped_security_or_infrastructure_invalid",
            "v32_locked_command_image_count": 0,
            "materialization_fix_merge_commit": _MATERIALIZATION_FIX_MERGE,
        },
        "v32_predecessor_stop": {
            "identity": "openhands-hwe-v32-codex-free-canary-materialization-v1",
            "status": "stopped_security_or_infrastructure_invalid",
            "failure_task_id": _task(2330),
            "failed_command_image_id": _V32_FAILED_COMMAND_IMAGE,
            "failed_unsanitized_image_id": _V32_FAILED_UNSANITIZED_IMAGE,
            "provider_calls": 0,
            "model_process_count": 0,
            "canary_executed": False,
            "command_image_locks": 0,
            "reuse_allowed": False,
        },
        "preauthorization_headroom": {
            "status": "passed_snapshot_only",
            "preflight_hash": _PREAUTH_HEADROOM_HASH,
            "receipt_file_sha256": _PREAUTH_HEADROOM_SHA256,
            "policy": copy.deepcopy(_HEADROOM_POLICY),
            "requirements": copy.deepcopy(list(_HEADROOM_REQUIREMENTS)),
            "execution_gate_must_rerun": True,
            "authorization_granted_by_snapshot": False,
            "provider_calls": 0,
            "model_process_count": 0,
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
            "security_scan_format": "verigym_hwe_command_image_security_scan_v2",
            "scanner_profile_id": "cva6-hwe-command-container-native-offline-v2",
            "codex_present": False,
        },
        "canary_contract": {
            "campaign_id": OPENHANDS_V33_CAMPAIGN_ID,
            "agent_version_id": OPENHANDS_V33_AGENT_VERSION_ID,
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
            "headroom_preflight_before_image_build": True,
            "headroom_policy_exact": True,
            "failed_scan_diagnostic_content_free": True,
            "v32_images_reused": False,
            "public_qualification_rerun": False,
            "codex_binary_absent": True,
            "provider_credentials_absent": True,
            "atomic_progress": True,
            "heldout_tasks_loaded": False,
        },
        "authorized_actions": {
            "consume_sealed_v29_evidence": True,
            "record_sealed_v30_stop": True,
            "record_sealed_v32_stop": True,
            "run_zero_provider_headroom_preflight": True,
            "build_six_command_images": True,
            "scan_six_command_images": True,
            "materialize_successor_canary_contract": True,
            "reuse_v32_command_images": False,
            "rerun_public_qualification": False,
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
        raise ConfigurationError("OpenHands v33 predecessor evidence file changed")
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
        raise ConfigurationError("OpenHands v33 predecessor evidence state changed")
    return qualification, prior_contract


def _validated_headroom_receipt(value: dict[str, Any]) -> dict[str, Any]:
    receipt = _validated_content_hash(value, "preflight_hash")
    filesystems = receipt.get("filesystems")
    if (
        receipt.get("schema_version") != "1.0"
        or receipt.get("format_id") != "verigym_hwe_command_image_materialization_headroom_v1"
        or receipt.get("status") != "passed"
        or receipt.get("policy") != _HEADROOM_POLICY
        or not isinstance(filesystems, list)
        or len(filesystems) != len(_HEADROOM_REQUIREMENTS)
        or receipt.get("provider_calls") != 0
        or receipt.get("model_process_count") != 0
        or receipt.get("raw_command_output_persisted") is not False
    ):
        raise ConfigurationError("OpenHands v33 headroom receipt changed")
    for observed, required in zip(filesystems, _HEADROOM_REQUIREMENTS, strict=True):
        if not isinstance(observed, dict):
            raise ConfigurationError("OpenHands v33 headroom observation changed")
        minimum_free_bytes = required["minimum_free_bytes"]
        minimum_free_inodes = required["minimum_free_inodes"]
        if type(minimum_free_bytes) is not int or type(minimum_free_inodes) is not int:
            raise ConfigurationError("OpenHands v33 headroom requirement changed")
        free_bytes = observed.get("observed_free_bytes")
        free_inodes = observed.get("observed_free_inodes")
        if (
            observed.get("role") != required["role"]
            or observed.get("minimum_free_bytes") != minimum_free_bytes
            or observed.get("minimum_free_inodes") != minimum_free_inodes
            or type(free_bytes) is not int
            or type(free_inodes) is not int
            or free_bytes < minimum_free_bytes
            or free_inodes < minimum_free_inodes
            or observed.get("bytes_satisfied") is not True
            or observed.get("inodes_satisfied") is not True
        ):
            raise ConfigurationError("OpenHands v33 headroom observation changed")
    return receipt


def _validate_v32_stop(v32: Path) -> None:
    expected_files = {
        "image-receipts/pr-2330.json": _V32_RECEIPT_SHA256,
        "materialization-progress.json": _V32_PROGRESS_SHA256,
    }
    observed_files: dict[str, Path] = {}
    for path in v32.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("OpenHands v33 v32 evidence contains a symlink")
        if path.is_file():
            observed_files[path.relative_to(v32).as_posix()] = path
    if set(observed_files) != set(expected_files):
        raise ConfigurationError("OpenHands v33 v32 evidence inventory changed")
    if any(
        hash_bytes(observed_files[name].read_bytes()) != digest
        for name, digest in expected_files.items()
    ):
        raise ConfigurationError("OpenHands v33 v32 evidence file changed")
    progress = _validated_content_hash(
        _load_json(observed_files["materialization-progress.json"]), "progress_hash"
    )
    receipt = _load_json(observed_files["image-receipts/pr-2330.json"])
    if (
        progress.get("progress_hash") != _V32_PROGRESS_HASH
        or progress.get("identity") != "openhands-hwe-v32-codex-free-canary-materialization-v1"
        or progress.get("status") != "stopped_security_or_infrastructure_invalid"
        or progress.get("failure_task_id") != _task(2330)
        or progress.get("locks") != {}
        or progress.get("provider_calls") != 0
        or progress.get("model_process_count") != 0
        or progress.get("heldout_task_ids_loaded") != []
        or progress.get("canary_executed") is not False
        or progress.get("collection_started") is not False
        or progress.get("training_started") is not False
        or receipt.get("format_id") != "verigym_hwe_command_image_build_receipt_v1"
        or receipt.get("task_id") != _task(2330)
        or receipt.get("derived_command_image_id") != _V32_FAILED_COMMAND_IMAGE
        or receipt.get("unsanitized_command_image_id") != _V32_FAILED_UNSANITIZED_IMAGE
        or receipt.get("codex_present") is not False
        or receipt.get("build_network") != "none"
    ):
        raise ConfigurationError("OpenHands v33 v32 stopped state changed")


def _failure_diagnostic(root: Path, task_id: str) -> dict[str, Any] | None:
    suffix = task_id.rsplit("-", 1)[-1]
    path = root / "security-scans" / f"pr-{suffix}.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        scan = _validated_content_hash(_load_json(path), "security_scan_id")
        diagnostic = _validated_content_hash(scan["diagnostic"], "diagnostic_hash")
    except (Exception, KeyboardInterrupt):
        return {"status": "invalid_diagnostic_receipt"}
    failure_stage = diagnostic.get("failure_stage")
    error_category = diagnostic.get("error_category")
    assertion_id = diagnostic.get("assertion_id")
    exit_code = diagnostic.get("exit_code")
    container_exit_code = diagnostic.get("container_exit_code")
    if (
        scan.get("format_id") != "verigym_hwe_command_image_security_scan_v2"
        or scan.get("scanner_profile_id") != "cva6-hwe-command-container-native-offline-v2"
        or scan.get("task_id") != task_id
        or scan.get("scan_passed") is not False
        or scan.get("secrets_detected") is not False
        or diagnostic.get("format_id") != "verigym_hwe_command_image_diagnostic_v2"
        or diagnostic.get("status") != "failed"
        or failure_stage not in _DIAGNOSTIC_FAILURE_STAGES
        or error_category not in _DIAGNOSTIC_ERROR_CATEGORIES
        or (
            assertion_id is not None
            and (
                error_category != "container_assertion_failed"
                or assertion_id not in _DIAGNOSTIC_ASSERTION_IDS
            )
        )
        or (exit_code is not None and type(exit_code) is not int)
        or (container_exit_code is not None and type(container_exit_code) is not int)
        or type(diagnostic.get("temporary_container_removed")) is not bool
        or type(diagnostic.get("temporary_workspace_removed")) is not bool
        or diagnostic.get("raw_output_persisted") is not False
        or diagnostic.get("create_nonempty_output_hashed") is not False
        or diagnostic.get("nonempty_output_hashed") is not False
        or diagnostic.get("cleanup_nonempty_output_hashed") is not False
    ):
        return {"status": "invalid_diagnostic_receipt"}
    return {
        "status": "validated_content_free_failure",
        "security_scan_id": scan["security_scan_id"],
        "diagnostic_hash": diagnostic["diagnostic_hash"],
        "failure_stage": failure_stage,
        "error_category": error_category,
        "assertion_id": assertion_id,
        "exit_code": exit_code,
        "container_exit_code": container_exit_code,
        "temporary_container_removed": diagnostic.get("temporary_container_removed"),
        "temporary_workspace_removed": diagnostic.get("temporary_workspace_removed"),
        "raw_output_persisted": False,
    }


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
            raise ConfigurationError("OpenHands v33 legacy image-lock file changed")
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
            raise ConfigurationError("OpenHands v33 legacy image-lock binding changed")
        locks[task_id] = lock
    return locks


def _validated_content_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop(field, None)
    if not isinstance(observed, str) or content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v33 predecessor {field} changed")
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
            "OpenHands v33 requires tracked, unchanged runtime and authorization files"
        ) from exc
    if head != upstream or len(head) != 40:
        raise ConfigurationError("OpenHands v33 requires the clean merged main commit")
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
            raise ConfigurationError("OpenHands v33 required merged path identity changed")
    subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", "HEAD", "--", *_REQUIRED_MERGED_PATHS],
        cwd=repository,
        check=True,
    )


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError("OpenHands v33 JSON input is unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError("OpenHands v33 JSON input is not an object")
    return value


def _safe_file(path: Path) -> Path:
    if path.is_symlink():
        raise ConfigurationError("OpenHands v33 input file must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ConfigurationError("OpenHands v33 input file is unavailable")
    return resolved


def _safe_executable(path: Path) -> Path:
    resolved = _safe_file(path)
    if not os.access(resolved, os.X_OK):
        raise ConfigurationError("OpenHands v33 ripgrep binary is not executable")
    return resolved


def _safe_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"OpenHands v33 {label} root must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError(f"OpenHands v33 {label} root is unavailable")
    return resolved


def _safe_child(root: Path, relative: str) -> Path:
    candidate = root / relative
    if candidate.is_symlink():
        raise ConfigurationError("OpenHands v33 evidence path contains a symlink")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ConfigurationError("OpenHands v33 evidence path escaped its root")
    return resolved


def _new_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("OpenHands v33 output must be a new directory")
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
