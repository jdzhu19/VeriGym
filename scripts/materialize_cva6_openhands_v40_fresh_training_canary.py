#!/usr/bin/env python3
"""Build one Codex-free training image and seal the v22 successor canary contract."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweAgentImageLock, HweCommandImageLock
from verigym.hwe.materialization_preflight import (
    MaterializationHeadroomError,
    discover_docker_root,
    require_materialization_headroom,
)

OPENHANDS_V40_OPT_IN_ENV = "VERIGYM_MATERIALIZE_OPENHANDS_HWE_V40_TRAINING_CANARY"
OPENHANDS_V40_APPROVAL_FORMAT = (
    "verigym_openhands_hwe_v40_fresh_training_canary_materialization_authorization_v1"
)
OPENHANDS_V40_PROGRESS_FORMAT = (
    "verigym_openhands_hwe_v40_fresh_training_canary_materialization_progress_v1"
)
OPENHANDS_V40_CATALOG_FORMAT = "verigym_openhands_hwe_v40_canary_command_image_catalog_v1"
OPENHANDS_V40_CONTRACT_FORMAT = "verigym_openhands_hwe_v40_v22_canary_contract_v1"
OPENHANDS_V40_IDENTITY = "openhands-hwe-v40-fresh-training-canary-materialization-v1"
OPENHANDS_V40_CAMPAIGN_ID = "openhands-hwe-v41-v22-required-tool-canary-v1"
OPENHANDS_V40_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v41-v22-canary-v1"
OPENHANDS_V40_APPROVAL_HASH = "606e38351b12d8a266121094b51569b3b24ac7ead8711459329a58006eee2725"

_TRAINING_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549"
_VALIDATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
_CANARY_TASKS = (_TRAINING_TASK, _VALIDATION_TASK)
_TAG_NAMESPACE = "verigym/cva6-openhands-v40-command"
_RG_VERSION = "ripgrep 15.2.0 (rev e89fff89ac)"
_RG_SHA256 = "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
_RG_ARCHIVE_SHA256 = "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
_MAX_JSON_BYTES = 16 * 1024 * 1024

_V33_ROOT_FILES = {
    "materialization-progress.json": (
        "267c8340e98b81a092216afccc5dadd0834960613920499c392f34522dd78839"
    ),
    "command-image-catalog.json": (
        "08c31fb7ad13d96fda850f114b34688ec22c0d96a865eb21e5d19fe03df5a423"
    ),
    "image-locks/pr-3204.json": (
        "a3a29f4ad2515c9502b3716e8644806154c7f9a74d388f9cd9c741d81458dc22"
    ),
    "security-scans/pr-3204.json": (
        "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1"
    ),
}
_V33_PROGRESS_HASH = "463aa8016d62e947421379cd925009c131a589d754e0c17e7c7f83c72fef26df"
_V33_CATALOG_HASH = "05be424d40014e7ef69106f85e5ea161db2bb8e70103c8d1279e4a7c118f8e05"
_V33_TREE_HASH = "62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6"
_V33_AUDIT_MERGE = "648fe717e88b36876245df09e73222f906f83918"
_V33_AUDIT_SHA256 = "63f814ebeee613e479db3c99f362211e6304778d11ab4cc35873c50f7750af5a"

_V39_ROOT_FILES = {
    "canary-report.json": "3f9f65de1f5e585c58630d30e49d8576aefbefc6cbc33001396400d85b08acca",
    "attempts/training-pr3231-s492-v39.json": (
        "f4709f0cb1901fba17adfcdd05eb931ebd8f8d7685dd495efef8882ef384b7ff"
    ),
    "security-scans/training-pr3231-s492-v39.json": (
        "83079b8de700a2c54e19b72ba186e70370253ef76de838794f34afa869f460a5"
    ),
}
_V39_REPORT_HASH = "072f237207f22f7f04a640819bded258d05e880ffc634340739e956064b03077"
_V39_TREE_HASH = "1fee66ee5a9f3902ce726a4459da875ba2dccb13c576763c2a4b5d6b44bac6be"
_V39_AUDIT_MERGE = "5a3c4cdb547cd3ca8bc7d3c45d21267e5d47648b"
_V39_AUDIT_SHA256 = "681d56d87627ededab88ac38ef51641e856016a62548132b35541d4ec434b263"

_V22_REPAIR_MERGE = "299cc6212be24f12c7cb695f596e4328258e294d"
_V22_AUDIT_SHA256 = "1328c6ddcdad557311832531844a3a827ed5fbb2d8412938c8a611862be21a62"
_V22_MAIN_RUN_ID = 33471695480
_LEGACY_QUALIFICATION_COMMIT = "732018de738d9886b11f7d633e693847beebf0ef"
_LEGACY_QUALIFICATION_AUDIT_SHA256 = (
    "9ee086e625ad33bed50ea7ff29bbb963d53197602dfe11f0f5eb3a09ff360ef7"
)

_TRAINING_LEGACY = {
    "task_id": _TRAINING_TASK,
    "file_sha256": "89c949025b604b0d078ac708bbdb59dc55109b4aace5c4ef7cb5b1962d75fae4",
    "lock_hash": "dfbca8971466d121a1df3274fb4dc46daad0459872edaaf6f57826c28632358c",
    "task_hash": "d594eaa3d87441dd5ad034682486f0c410c923f75372ef4d2caa654e2ab212f9",
    "source_hash": "50a08b2358ddb7b939fa77ac7d726e1baf0735fa863d891c4325a3d204c5eaa0",
    "agent_image": "sha256:2c713d28aa075180bf95ba61bcc18237f1cf82896da5cee2d76bf69900eb224f",
    "verifier_image": "sha256:a43f709fa63c987f4b8c894c19dcd3fc9c34269a45cfb3def0fbd5432fde4b40",
}
_VALIDATION_COMMAND = {
    "task_id": _VALIDATION_TASK,
    "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
    "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
    "lock_hash": "4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7",
    "security_scan_id": "55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf",
    "command_image": "sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784",
    "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
}

_HEADROOM_POLICY = {
    "absolute_thresholds": True,
    "percentage_thresholds": False,
    "planned_command_image_count": 6,
    "maximum_bytes_per_command_image": 8 * 1024**3,
    "docker_headroom_multiplier": 2,
}
_HEADROOM_REQUIREMENTS: tuple[dict[str, str | int], ...] = (
    {"role": "control_root", "minimum_free_bytes": 4 * 1024**3, "minimum_free_inodes": 100_000},
    {"role": "docker_root", "minimum_free_bytes": 96 * 1024**3, "minimum_free_inodes": 250_000},
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
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v40_fresh_training_canary_materialization_v1.json",
    "docker/cva6-hwe-command/Dockerfile",
    "docs/audits/2026-09-01_openhands-v40-fresh-training-canary-materialization-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v22.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v22_protocol.py",
    "scripts/build_cva6_hwe_command_image.sh",
    "scripts/materialize_cva6_openhands_v40_fresh_training_canary.py",
    "scripts/scan_and_lock_cva6_hwe_command_image.py",
    "SECURITY.md",
    "src/verigym/hwe/materialization_preflight.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--legacy-image-lock", type=Path, required=True)
    parser.add_argument("--v33-root", type=Path, required=True)
    parser.add_argument("--v39-root", type=Path, required=True)
    parser.add_argument("--rg-binary", type=Path, required=True)
    parser.add_argument("--rg-release-archive", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the authorized single-image, zero-provider materialization."""

    if os.environ.get(OPENHANDS_V40_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V40_OPT_IN_ENV}=1 is required")
    authorization = _validated_authorization(_load_json(_safe_file(arguments.authorization)))
    source_commit = _merged_source_commit()
    v33_root = _safe_directory(arguments.v33_root, "v33 materialization")
    v39_root = _safe_directory(arguments.v39_root, "v39 failed canary")
    validation_lock = _validated_v33_evidence(v33_root)
    _validate_v39_failure(v39_root)
    legacy = _validated_training_legacy(_safe_file(arguments.legacy_image_lock))
    rg_binary = _safe_executable(arguments.rg_binary)
    rg_archive = _safe_file(arguments.rg_release_archive)
    scratch_root = _safe_directory(arguments.scratch_root, "command-image scratch")
    if (
        hash_bytes(rg_binary.read_bytes()) != _RG_SHA256
        or hash_bytes(rg_archive.read_bytes()) != _RG_ARCHIVE_SHA256
    ):
        raise ConfigurationError("OpenHands v40 ripgrep release identity changed")

    root = _new_directory(arguments.output)
    for name in ("image-receipts", "security-scans", "image-locks"):
        (root / name).mkdir(mode=0o700)
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V40_PROGRESS_FORMAT,
        "identity": OPENHANDS_V40_IDENTITY,
        "status": "headroom_preflight_running",
        "authorization_hash": authorization["authorization_hash"],
        "source_commit": source_commit,
        "v33_progress_hash": _V33_PROGRESS_HASH,
        "v33_catalog_hash": _V33_CATALOG_HASH,
        "v39_report_hash": _V39_REPORT_HASH,
        "v22_repair_merge_commit": _V22_REPAIR_MERGE,
        "headroom_preflight_hash": None,
        "task_ids": [_TRAINING_TASK],
        "active_task_id": None,
        "locks": {},
        "provider_calls": 0,
        "provider_episodes": 0,
        "model_process_count": 0,
        "canary_executed": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "heldout_task_ids_loaded": [],
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
        raise ConfigurationError("OpenHands v40 materialization headroom was rejected") from None
    except (Exception, KeyboardInterrupt) as exc:
        progress.update(
            {
                "status": "stopped_infrastructure_invalid",
                "failure_stage": "headroom_preflight",
                "failure_type": type(exc).__name__,
            }
        )
        _write_progress(root, progress)
        raise ConfigurationError("OpenHands v40 headroom preflight failed") from None
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
        raise ConfigurationError("OpenHands v40 headroom policy changed") from None
    progress.update(
        {"status": "materialization_running", "headroom_preflight_hash": headroom["preflight_hash"]}
    )
    progress["active_task_id"] = _TRAINING_TASK
    _write_progress(root, progress)
    try:
        training_lock = _build_one(
            root=root,
            repository=Path(__file__).resolve().parents[1],
            legacy=legacy,
            rg_binary=rg_binary,
            rg_archive=rg_archive,
        )
    except (Exception, KeyboardInterrupt) as exc:
        progress.update(
            {
                "status": "stopped_security_or_infrastructure_invalid",
                "active_task_id": None,
                "failure_task_id": _TRAINING_TASK,
                "failure_type": type(exc).__name__,
                "failure_diagnostic": _failure_diagnostic(root),
            }
        )
        _write_progress(root, progress)
        raise ConfigurationError("OpenHands v40 command-image materialization stopped") from exc

    lock_path = root / "image-locks/pr-2549.json"
    progress["locks"][_TRAINING_TASK] = {
        "lock": "image-locks/pr-2549.json",
        "lock_file_sha256": hash_bytes(lock_path.read_bytes()),
        "lock_hash": training_lock.lock_hash,
        "command_image": training_lock.derived_command_image_id,
        "verifier_image": training_lock.verifier_base_image_id,
        "security_scan_id": training_lock.security_scan_id,
    }
    progress["active_task_id"] = None
    _write_progress(root, progress)
    catalog = _command_catalog(training_lock, validation_lock, progress["locks"][_TRAINING_TASK])
    contract = _canary_contract(training_lock, validation_lock)
    atomic_dump_json(root / "canary-command-image-catalog.json", catalog)
    atomic_dump_json(root / "canary-contract.json", contract)
    progress.update(
        {
            "status": "completed_v22_canary_contract_materialized",
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
    receipt = root / "image-receipts/pr-2549.json"
    scan = root / "security-scans/pr-2549.json"
    lock_path = root / "image-locks/pr-2549.json"
    legacy_path = root / ".legacy-pr-2549.json"
    atomic_dump_json(legacy_path, legacy.model_dump(mode="json"))
    image_tag = f"{_TAG_NAMESPACE}-pr-2549:rg-15.2.0-v1"
    try:
        subprocess.run(
            [
                str(repository / "scripts/build_cva6_hwe_command_image.sh"),
                str(rg_binary),
                str(rg_archive),
                legacy.verifier_base_image_id,
                legacy.task_id,
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
    _validate_final_lock(lock, legacy)
    _validate_passed_security_scan(scan, lock)
    return lock


def _validate_final_lock(lock: HweCommandImageLock, legacy: HweAgentImageLock) -> None:
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
        raise ConfigurationError("OpenHands v40 command-image lock binding changed")


def _validate_passed_security_scan(path: Path, lock: HweCommandImageLock) -> None:
    scan = _validated_content_hash(_load_json(path), "security_scan_id", "security scan")
    diagnostic = _validated_content_hash(scan["diagnostic"], "diagnostic_hash", "diagnostic")
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
        raise ConfigurationError("OpenHands v40 command-image security receipt changed")


def _command_catalog(
    training: HweCommandImageLock,
    validation: HweCommandImageLock,
    progress_lock: dict[str, str],
) -> dict[str, Any]:
    if training.derived_command_image_id == validation.derived_command_image_id:
        raise ConfigurationError("OpenHands v40 canary command images are not task-distinct")
    tasks = [
        {
            "task_id": training.task_id,
            "role": "training_canary_replacement",
            "task_hash": training.task_hash,
            "source_hash": training.source_hash,
            "verifier_image": training.verifier_base_image_id,
            "legacy_agent_lock_hash": _TRAINING_LEGACY["lock_hash"],
            "command_image_lock": progress_lock["lock"],
            "command_image_lock_file_sha256": progress_lock["lock_file_sha256"],
            "command_image_lock_hash": training.lock_hash,
            "command_image": training.derived_command_image_id,
            "security_scan_id": training.security_scan_id,
            "source": "v40_materialized",
        },
        {
            "task_id": validation.task_id,
            "role": "canary_validation",
            "task_hash": validation.task_hash,
            "source_hash": validation.source_hash,
            "verifier_image": validation.verifier_base_image_id,
            "command_image_lock": "v33:image-locks/pr-3204.json",
            "command_image_lock_file_sha256": _V33_ROOT_FILES["image-locks/pr-3204.json"],
            "command_image_lock_hash": validation.lock_hash,
            "command_image": validation.derived_command_image_id,
            "security_scan_id": validation.security_scan_id,
            "source": "sealed_v33_reuse",
        },
    ]
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V40_CATALOG_FORMAT,
        "task_count": 2,
        "tasks": tasks,
        "codex_present": False,
        "provider_credentials_present": False,
        "command_execution_backend": "episode_container_exec_v1",
        "build_network": "none",
        "runtime_network": "none",
        "provider_calls": 0,
    }
    return {**base, "catalog_hash": content_hash(base)}


def _canary_contract(
    training: HweCommandImageLock, validation: HweCommandImageLock
) -> dict[str, Any]:
    if training.derived_command_image_id == validation.derived_command_image_id:
        raise ConfigurationError("OpenHands v40 canary command images are not task-distinct")
    bindings = {
        training.task_id: _binding(training),
        validation.task_id: _binding(validation),
    }
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V40_CONTRACT_FORMAT,
        "campaign_id": OPENHANDS_V40_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V40_AGENT_VERSION_ID,
        "protocol_profile": "required_tool_atomic_shape_recovery_v22",
        "schedule": [
            {"task_id": _TRAINING_TASK, "role": "training", "seed": 493, "sample_index": 9},
            {"task_id": _VALIDATION_TASK, "role": "validation", "seed": 493, "sample_index": 9},
        ],
        "task_bindings": bindings,
        "teacher": {
            "model": "openai/deepseek-v4-flash",
            "model_identity": "deepseek-v4-flash",
            "openhands_sdk_version": "1.42.1",
            "litellm_version": "1.93.0",
            "tiktoken_version": "0.7.0",
            "transformers_version": "4.57.6",
            "numpy_version": "2.2.6",
            "pillow_version": "12.1.1",
            "temperature": 0,
            "max_provider_calls": 64,
            "max_provider_tokens": 1_000_000,
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "provider_request_retries": 0,
            "whole_episode_retries": 0,
        },
        "runtime": {
            "command_role": "credential_free_command_image",
            "command_execution_backend": "episode_container_exec_v1",
            "external_agent_process_available": False,
            "codex_present": False,
            "provider_credentials_in_command_container": False,
            "network": "none",
        },
        "gate": {
            "all_six_result_planes_required": True,
            "stop_after_first_failed_gate": True,
            "decision_token_limit": 65_536,
            "truncation_allowed": False,
            "formal_collection_allowed_only_after_audit_merge": True,
        },
        "training_task_disposition_after_success": "import_canary_without_formal_reexecution",
        "provider_calls_during_materialization": 0,
        "heldout_task_ids_loaded": [],
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }
    return validate_v40_canary_contract({**base, "contract_hash": content_hash(base)})


def validate_v40_canary_contract(value: dict[str, Any]) -> dict[str, Any]:
    result = _validated_content_hash(value, "contract_hash", "canary contract")
    if result != {
        **_canary_contract_base_from_bindings(result.get("task_bindings")),
        "contract_hash": result["contract_hash"],
    }:
        raise ConfigurationError("OpenHands v40 canary contract policy changed")
    return result


def _canary_contract_base_from_bindings(bindings: object) -> dict[str, Any]:
    if not isinstance(bindings, dict) or set(bindings) != set(_CANARY_TASKS):
        raise ConfigurationError("OpenHands v40 canary task bindings changed")
    for task_id, expected in (
        (_TRAINING_TASK, _TRAINING_LEGACY),
        (_VALIDATION_TASK, _VALIDATION_COMMAND),
    ):
        binding = bindings.get(task_id)
        if (
            not isinstance(binding, dict)
            or binding.get("task_hash") != expected["task_hash"]
            or binding.get("source_hash") != expected["source_hash"]
            or binding.get("verifier_image") != expected["verifier_image"]
            or not _digest(binding.get("command_image"))
            or not _hash(binding.get("command_image_lock_hash"))
            or not _hash(binding.get("security_scan_id"))
        ):
            raise ConfigurationError("OpenHands v40 canary command binding changed")
        if task_id == _VALIDATION_TASK and (
            binding.get("command_image") != _VALIDATION_COMMAND["command_image"]
            or binding.get("command_image_lock_hash") != _VALIDATION_COMMAND["lock_hash"]
            or binding.get("security_scan_id") != _VALIDATION_COMMAND["security_scan_id"]
        ):
            raise ConfigurationError("OpenHands v40 v33 validation command binding changed")
    training_binding = bindings[_TRAINING_TASK]
    validation_binding = bindings[_VALIDATION_TASK]
    if training_binding.get("command_image") == validation_binding.get("command_image"):
        raise ConfigurationError("OpenHands v40 canary command images are not task-distinct")
    return {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V40_CONTRACT_FORMAT,
        "campaign_id": OPENHANDS_V40_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V40_AGENT_VERSION_ID,
        "protocol_profile": "required_tool_atomic_shape_recovery_v22",
        "schedule": [
            {"task_id": _TRAINING_TASK, "role": "training", "seed": 493, "sample_index": 9},
            {"task_id": _VALIDATION_TASK, "role": "validation", "seed": 493, "sample_index": 9},
        ],
        "task_bindings": copy.deepcopy(bindings),
        "teacher": {
            "model": "openai/deepseek-v4-flash",
            "model_identity": "deepseek-v4-flash",
            "openhands_sdk_version": "1.42.1",
            "litellm_version": "1.93.0",
            "tiktoken_version": "0.7.0",
            "transformers_version": "4.57.6",
            "numpy_version": "2.2.6",
            "pillow_version": "12.1.1",
            "temperature": 0,
            "max_provider_calls": 64,
            "max_provider_tokens": 1_000_000,
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "provider_request_retries": 0,
            "whole_episode_retries": 0,
        },
        "runtime": {
            "command_role": "credential_free_command_image",
            "command_execution_backend": "episode_container_exec_v1",
            "external_agent_process_available": False,
            "codex_present": False,
            "provider_credentials_in_command_container": False,
            "network": "none",
        },
        "gate": {
            "all_six_result_planes_required": True,
            "stop_after_first_failed_gate": True,
            "decision_token_limit": 65_536,
            "truncation_allowed": False,
            "formal_collection_allowed_only_after_audit_merge": True,
        },
        "training_task_disposition_after_success": "import_canary_without_formal_reexecution",
        "provider_calls_during_materialization": 0,
        "heldout_task_ids_loaded": [],
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }


def _binding(lock: HweCommandImageLock) -> dict[str, str]:
    return {
        "task_hash": lock.task_hash,
        "source_hash": lock.source_hash,
        "verifier_image": lock.verifier_base_image_id,
        "command_image": lock.derived_command_image_id,
        "command_image_lock_hash": lock.lock_hash,
        "security_scan_id": lock.security_scan_id,
    }


def _expected_authorization() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V40_APPROVAL_FORMAT,
        "status": "authorized_pending_materialization",
        "identity": OPENHANDS_V40_IDENTITY,
        "v33_materialization_evidence": {
            "audit_merge_commit": _V33_AUDIT_MERGE,
            "audit_file_sha256": _V33_AUDIT_SHA256,
            "evidence_tree_hash": _V33_TREE_HASH,
            "progress_hash": _V33_PROGRESS_HASH,
            "progress_file_sha256": _V33_ROOT_FILES["materialization-progress.json"],
            "catalog_hash": _V33_CATALOG_HASH,
            "catalog_file_sha256": _V33_ROOT_FILES["command-image-catalog.json"],
            "validation_lock_file_sha256": _V33_ROOT_FILES["image-locks/pr-3204.json"],
            "validation_scan_file_sha256": _V33_ROOT_FILES["security-scans/pr-3204.json"],
        },
        "failed_v39_evidence": {
            "audit_merge_commit": _V39_AUDIT_MERGE,
            "audit_file_sha256": _V39_AUDIT_SHA256,
            "evidence_tree_hash": _V39_TREE_HASH,
            "report_hash": _V39_REPORT_HASH,
            "report_file_sha256": _V39_ROOT_FILES["canary-report.json"],
            "attempt_file_sha256": _V39_ROOT_FILES["attempts/training-pr3231-s492-v39.json"],
            "security_scan_file_sha256": _V39_ROOT_FILES[
                "security-scans/training-pr3231-s492-v39.json"
            ],
            "provider_episode_count": 1,
            "provider_call_count": 1,
            "failed_task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231",
            "validation_task_started": False,
        },
        "v22_protocol_repair_evidence": {
            "merge_commit": _V22_REPAIR_MERGE,
            "audit_file_sha256": _V22_AUDIT_SHA256,
            "post_merge_main_run_id": _V22_MAIN_RUN_ID,
            "post_merge_main_all_eight_classes_passed": True,
            "predecessor_protocol": "required_tool_atomic_shape_recovery_v21",
            "successor_protocol": "required_tool_atomic_shape_recovery_v22",
            "provider_invocation_authorized_by_repair": False,
        },
        "training_legacy_image_lock": copy.deepcopy(_TRAINING_LEGACY),
        "legacy_qualification_evidence": {
            "audit_commit": _LEGACY_QUALIFICATION_COMMIT,
            "audit_file_sha256": _LEGACY_QUALIFICATION_AUDIT_SHA256,
            "security_scan_passed": True,
            "runtime_network": "none",
            "historical_trajectory_relabelled": False,
        },
        "reserve_ledger": [
            {
                "task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330",
                "role": "training_reserve",
                "state": "consumed_v36",
            },
            {
                "task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3226",
                "role": "training_reserve",
                "state": "consumed_v38",
            },
            {
                "task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231",
                "role": "training_reserve",
                "state": "consumed_v39",
            },
            {
                "task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2989",
                "role": "validation_reserve",
                "state": "unconsumed_role_frozen",
            },
            {
                "task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3059",
                "role": "validation_reserve",
                "state": "unconsumed_role_frozen",
            },
            {"task_id": _VALIDATION_TASK, "role": "canary_validation", "state": "unstarted"},
        ],
        "headroom_policy": {
            "policy": copy.deepcopy(_HEADROOM_POLICY),
            "requirements": copy.deepcopy(list(_HEADROOM_REQUIREMENTS)),
            "single_image_build_uses_conservative_six_image_threshold": True,
            "execution_gate_must_rerun": True,
        },
        "command_image_inputs": {
            "image_count": 1,
            "task_id": _TRAINING_TASK,
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
        "future_canary_contract": {
            "campaign_id": OPENHANDS_V40_CAMPAIGN_ID,
            "agent_version_id": OPENHANDS_V40_AGENT_VERSION_ID,
            "protocol_profile": "required_tool_atomic_shape_recovery_v22",
            "task_ids": list(_CANARY_TASKS),
            "roles": ["training", "validation"],
            "seed": 493,
            "sample_index": 9,
            "provider_calls_during_materialization": 0,
            "training_task_disposition_after_success": ("import_canary_without_formal_reexecution"),
        },
        "required_controls": {
            "clean_merged_source_commit": True,
            "exact_v33_result_chain": True,
            "exact_failed_v39_result_chain": True,
            "exact_v22_protocol_repair_chain": True,
            "historical_tasks_retried": False,
            "historical_evidence_relabelled": False,
            "task_source_verifier_binding_exact": True,
            "build_network_none": True,
            "runtime_network_none": True,
            "image_security_scan_required": True,
            "headroom_preflight_before_image_build": True,
            "failed_scan_diagnostic_content_free": True,
            "validation_reserve_roles_changed": False,
            "codex_binary_absent": True,
            "provider_credentials_absent": True,
            "atomic_progress": True,
            "heldout_tasks_loaded": False,
        },
        "authorized_actions": {
            "consume_sealed_v33_validation_binding": True,
            "consume_sealed_v39_failure_evidence": True,
            "consume_legacy_pr2549_qualification": True,
            "run_zero_provider_headroom_preflight": True,
            "build_pr2549_command_image": True,
            "scan_pr2549_command_image": True,
            "materialize_v22_canary_contract": True,
            "invoke_provider": False,
            "execute_canary": False,
            "start_formal_collection": False,
            "start_training": False,
            "load_heldout_tasks": False,
        },
        "failure_policy": "stop_immediately_no_retry_freeze_identity",
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    result = _validated_content_hash(value, "authorization_hash", "authorization")
    if result["authorization_hash"] != OPENHANDS_V40_APPROVAL_HASH:
        raise ConfigurationError("OpenHands v40 authorization hash changed")
    expected = _expected_authorization()
    if result != {**expected, "authorization_hash": OPENHANDS_V40_APPROVAL_HASH}:
        raise ConfigurationError("OpenHands v40 authorization policy changed")
    return result


def _validated_v33_evidence(root: Path) -> HweCommandImageLock:
    for relative, digest in _V33_ROOT_FILES.items():
        if hash_bytes(_safe_child(root, relative).read_bytes()) != digest:
            raise ConfigurationError("OpenHands v40 v33 evidence file changed")
    progress = _validated_content_hash(
        _load_json(_safe_child(root, "materialization-progress.json")),
        "progress_hash",
        "v33 progress",
    )
    catalog = _validated_content_hash(
        _load_json(_safe_child(root, "command-image-catalog.json")),
        "catalog_hash",
        "v33 catalog",
    )
    lock = HweCommandImageLock.model_validate(
        _load_json(_safe_child(root, "image-locks/pr-3204.json"))
    )
    _validate_passed_security_scan(_safe_child(root, "security-scans/pr-3204.json"), lock)
    tasks = catalog.get("tasks")
    matching = (
        [
            item
            for item in tasks
            if isinstance(item, dict) and item.get("task_id") == _VALIDATION_TASK
        ]
        if isinstance(tasks, list)
        else []
    )
    if (
        progress.get("progress_hash") != _V33_PROGRESS_HASH
        or progress.get("status") != "completed_codex_free_canary_contract_materialized"
        or progress.get("provider_calls") != 0
        or progress.get("canary_executed") is not False
        or catalog.get("catalog_hash") != _V33_CATALOG_HASH
        or catalog.get("task_count") != 6
        or len(matching) != 1
        or matching[0].get("role") != "canary_validation"
        or lock.task_id != _VALIDATION_TASK
        or lock.task_hash != _VALIDATION_COMMAND["task_hash"]
        or lock.source_hash != _VALIDATION_COMMAND["source_hash"]
        or lock.lock_hash != _VALIDATION_COMMAND["lock_hash"]
        or lock.security_scan_id != _VALIDATION_COMMAND["security_scan_id"]
        or lock.derived_command_image_id != _VALIDATION_COMMAND["command_image"]
        or lock.verifier_base_image_id != _VALIDATION_COMMAND["verifier_image"]
    ):
        raise ConfigurationError("OpenHands v40 v33 validation binding changed")
    return lock


def _validate_v39_failure(root: Path) -> None:
    for relative, digest in _V39_ROOT_FILES.items():
        if hash_bytes(_safe_child(root, relative).read_bytes()) != digest:
            raise ConfigurationError("OpenHands v40 v39 evidence file changed")
    report = _validated_content_hash(
        _load_json(_safe_child(root, "canary-report.json")), "report_hash", "v39 report"
    )
    attempt = _load_json(_safe_child(root, "attempts/training-pr3231-s492-v39.json"))
    if (
        report.get("report_hash") != _V39_REPORT_HASH
        or report.get("status") != "canary_failed_closed"
        or report.get("provider_episode_count") != 1
        or report.get("provider_call_count") != 1
        or report.get("formal_collection_allowed") is not False
        or report.get("formal_collection_started") is not False
        or report.get("training_started") is not False
        or report.get("attempts") != [attempt]
        or attempt.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231"
        or attempt.get("result", {}).get("agent_protocol_valid") is not False
        or attempt.get("result", {}).get("infrastructure_valid") is not True
        or attempt.get("result", {}).get("security_valid") is not True
    ):
        raise ConfigurationError("OpenHands v40 v39 stopped state changed")


def _validated_training_legacy(path: Path) -> HweAgentImageLock:
    if hash_bytes(path.read_bytes()) != _TRAINING_LEGACY["file_sha256"]:
        raise ConfigurationError("OpenHands v40 PR-2549 image-lock file changed")
    lock = HweAgentImageLock.model_validate(_load_json(path))
    if (
        lock.task_id != _TRAINING_TASK
        or lock.task_hash != _TRAINING_LEGACY["task_hash"]
        or lock.source_hash != _TRAINING_LEGACY["source_hash"]
        or lock.lock_hash != _TRAINING_LEGACY["lock_hash"]
        or lock.derived_agent_image_id != _TRAINING_LEGACY["agent_image"]
        or lock.verifier_base_image_id != _TRAINING_LEGACY["verifier_image"]
        or lock.security_scan_passed is not True
        or lock.provider_credentials_present is not False
        or lock.hidden_assets_present is not False
        or lock.verifier_payload_present is not False
        or lock.reference_patch_present is not False
        or lock.build_network != "none"
        or lock.runtime_network != "none"
    ):
        raise ConfigurationError("OpenHands v40 PR-2549 image-lock binding changed")
    return lock


def _validated_headroom_receipt(value: dict[str, Any]) -> dict[str, Any]:
    receipt = _validated_content_hash(value, "preflight_hash", "headroom receipt")
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
        raise ConfigurationError("OpenHands v40 headroom receipt changed")
    for observed, required in zip(filesystems, _HEADROOM_REQUIREMENTS, strict=True):
        if not isinstance(observed, dict):
            raise ConfigurationError("OpenHands v40 headroom observation changed")
        free_bytes = observed.get("observed_free_bytes")
        free_inodes = observed.get("observed_free_inodes")
        if (
            observed.get("role") != required["role"]
            or observed.get("minimum_free_bytes") != required["minimum_free_bytes"]
            or observed.get("minimum_free_inodes") != required["minimum_free_inodes"]
            or type(free_bytes) is not int
            or type(free_inodes) is not int
            or free_bytes < int(required["minimum_free_bytes"])
            or free_inodes < int(required["minimum_free_inodes"])
            or observed.get("bytes_satisfied") is not True
            or observed.get("inodes_satisfied") is not True
        ):
            raise ConfigurationError("OpenHands v40 headroom observation changed")
    return receipt


def _failure_diagnostic(root: Path) -> dict[str, Any] | None:
    path = root / "security-scans/pr-2549.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        scan = _validated_content_hash(_load_json(path), "security_scan_id", "failed scan")
        diagnostic = _validated_content_hash(scan["diagnostic"], "diagnostic_hash", "diagnostic")
    except (Exception, KeyboardInterrupt):
        return {"status": "invalid_diagnostic_receipt"}
    failure_stage = diagnostic.get("failure_stage")
    error_category = diagnostic.get("error_category")
    assertion_id = diagnostic.get("assertion_id")
    exit_code = diagnostic.get("exit_code")
    container_exit_code = diagnostic.get("container_exit_code")
    if (
        scan.get("format_id") != "verigym_hwe_command_image_security_scan_v2"
        or scan.get("task_id") != _TRAINING_TASK
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


def _validated_content_hash(value: object, field: str, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v40 {label} is not an object")
    result = copy.deepcopy(value)
    observed = result.pop(field, None)
    if not isinstance(observed, str) or content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v40 {label} identity changed")
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
        for commit in (
            _V33_AUDIT_MERGE,
            _V39_AUDIT_MERGE,
            _V22_REPAIR_MERGE,
            _LEGACY_QUALIFICATION_COMMIT,
        ):
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=repository, check=True
            )
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
    except subprocess.CalledProcessError as exc:
        raise ConfigurationError(
            "OpenHands v40 requires tracked, unchanged, merged authorization inputs"
        ) from exc
    if head != upstream or len(head) != 40:
        raise ConfigurationError("OpenHands v40 requires the clean merged main commit")
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
            raise ConfigurationError("OpenHands v40 required merged path identity changed")
    subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", "HEAD", "--", *_REQUIRED_MERGED_PATHS],
        cwd=repository,
        check=True,
    )


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError("OpenHands v40 JSON input is unsafe")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError("OpenHands v40 JSON input is not an object")
    return value


def _safe_file(path: Path) -> Path:
    if path.is_symlink():
        raise ConfigurationError("OpenHands v40 input file must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ConfigurationError("OpenHands v40 input file is unavailable")
    return resolved


def _safe_executable(path: Path) -> Path:
    resolved = _safe_file(path)
    if not os.access(resolved, os.X_OK):
        raise ConfigurationError("OpenHands v40 ripgrep binary is not executable")
    return resolved


def _safe_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"OpenHands v40 {label} root must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError(f"OpenHands v40 {label} root is unavailable")
    return resolved


def _safe_child(root: Path, relative: str) -> Path:
    candidate = root / relative
    if candidate.is_symlink():
        raise ConfigurationError("OpenHands v40 evidence path contains a symlink")
    resolved = candidate.resolve(strict=True)
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
        or resolved.stat().st_size > _MAX_JSON_BYTES
    ):
        raise ConfigurationError("OpenHands v40 evidence path escaped its root")
    return resolved


def _new_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("OpenHands v40 output must be a new directory")
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
