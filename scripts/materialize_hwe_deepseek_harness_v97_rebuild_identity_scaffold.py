#!/usr/bin/env python3
"""Materialize a fresh five-task scaffold without requiring historical rebuild IDs."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
_SOURCE_ROOTS = (
    _REPOSITORY,
    _REPOSITORY / "src",
    _REPOSITORY / "integrations/verigym-hwe-bench/src",
    _REPOSITORY / "integrations/verigym-deepseek-harness/src",
)
for _source_root in reversed(_SOURCE_ROOTS):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v79_dind as v79  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v81_execution_scaffold as v81,
)
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v94_runtime_complete_scaffold as v94,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    HweOfflineTaskLock,
    load_v94_runtime_complete_scaffold_manifest,
    load_v97_rebuild_identity_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V97_REBUILD_IDENTITY_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v97_rebuild_identity_scaffold_v1.json"
)
V92_MANIFEST = v94.V92_MANIFEST
V92_REPORT = v94.V92_REPORT
V90_ROOT = v94.V90_ROOT
V94_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v94_runtime_complete_scaffold_v1.json"
)
V94_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v94-runtime-complete-scaffold-v1"
)
V94_REPORT = V94_ROOT / "execution-scaffold-report.json"
V95_AUDIT = _REPOSITORY / "docs/audits/2026-09-03_deepseek-harness-v95-v94-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v97")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v97-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v97-runtime")
_REQUIRED_MERGED_PATHS = (
    *v94._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "configs/training/qwen35_hwe_deepseek_harness_v97_rebuild_identity_scaffold_v1.json",
    "docs/audits/2026-09-03_deepseek-harness-v95-v94-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v97-rebuild-identity-scaffold-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v97_rebuild_identity_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v97_rebuild_identity_scaffold.py",
)
_V94_WRITE_PROGRESS = v94._write_progress  # noqa: SLF001
_V94_TRANSFER_IMAGES = v94._transfer_images  # noqa: SLF001
_V94_RUNTIME_PREPARE_PREFLIGHT = v94._runtime_prepare_preflight  # noqa: SLF001
_V94_HARNESS_INITIALIZE_PREFLIGHT = v94._harness_initialize_preflight  # noqa: SLF001
_V94_INVENTORY = v94._inventory  # noqa: SLF001
_V94_RUNTIME_RECEIPT = v94._runtime_receipt  # noqa: SLF001
_V94_CLEAN_SOCKET_VOLUME = v94._clean_socket_volume  # noqa: SLF001


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--v92-manifest", type=Path, default=V92_MANIFEST)
    parser.add_argument("--v90-root", type=Path, default=V90_ROOT)
    parser.add_argument("--v92-report", type=Path, default=V92_REPORT)
    parser.add_argument("--upstream-manifest", type=Path, default=v94.UPSTREAM_MANIFEST)
    parser.add_argument("--v79-manifest", type=Path, default=v94.V79_MANIFEST)
    parser.add_argument("--v79-provider-contract", type=Path, default=v94.V79_PROVIDER_CONTRACT)
    parser.add_argument("--archive-root", type=Path, default=v94.ARCHIVE_ROOT)
    parser.add_argument("--rg-binary", type=Path, default=v69.RG_BINARY)
    parser.add_argument("--rg-release-archive", type=Path, default=v69.RG_ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the v94-tested workflow under the fresh v97 bindings."""

    with _v97_base_configuration():
        return v94.materialize(arguments)


@contextlib.contextmanager
def _v97_base_configuration() -> Iterator[None]:
    replacements: dict[str, Any] = {
        "IDENTITY": IDENTITY,
        "OPT_IN_ENV": OPT_IN_ENV,
        "MANIFEST": MANIFEST,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "DIND_PARENT": DIND_PARENT,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
        "CONTROL_ROOT": CONTROL_ROOT,
        "RUNTIME_TMP": RUNTIME_TMP,
        "_REQUIRED_MERGED_PATHS": _REQUIRED_MERGED_PATHS,
        "load_v94_runtime_complete_scaffold_manifest": (
            load_v97_rebuild_identity_scaffold_manifest
        ),
        "_validate_static_bindings": _validate_static_bindings,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
        "_write_progress": _write_progress,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
    }
    previous = {name: getattr(v94, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v94, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v94, name, value)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v97 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v97_scaffold_progress_v1",
            "v94_manifest_hash": (
                "45a3e0132f6a31e70cb17ebd665e556c84ffa4300de429c8f4c4e9d54dbca27c"
            ),
            "v94_report_hash": ("29202688ef99ebed3381b7dcb448cab6bb6db923f5034352e677b7e63515ad12"),
            "v95_audit_commit": "57cf77be8d9992e5fcc2e5833ec64ff458365d00",
            "v95_post_merge_main_run_id": 33776059453,
        }
    )
    if value.get("status") == "completed_pending_independent_v95_audit":
        value["status"] = "completed_pending_independent_v98_audit"
    _V94_WRITE_PROGRESS(root, value)


def _transfer_images(
    dind_name: str,
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V94_TRANSFER_IMAGES(
        dind_name,
        manifest,
        host_images=host_images,
        root=root,
    )
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v97_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v97 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v97_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    return _reseal(
        _V94_RUNTIME_PREPARE_PREFLIGHT(manifest, locks=locks, dind_name=dind_name),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v97_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    return _reseal(
        _V94_HARNESS_INITIALIZE_PREFLIGHT(
            manifest,
            controller_receipt_hash=controller_receipt_hash,
            root=root,
        ),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v97_harness_initialize_preflight_v1",
    )


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
) -> dict[str, Any]:
    return _reseal(
        _V94_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v97_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V94_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value["v94_data_volume_reused"] = False
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v97_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    result = _reseal(
        _V94_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v97_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _reseal(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    format_id: str,
) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _validate_static_bindings(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    v94_manifest = load_v94_runtime_complete_scaffold_manifest(V94_MANIFEST)
    v94_report = v94._load_json(V94_REPORT)  # noqa: SLF001
    if (
        v69._hash_file(v92_manifest_path) != manifest.v92_manifest_sha256  # noqa: SLF001
        or v92_manifest.manifest_hash != manifest.v92_manifest_hash
        or v69._hash_file(v92_report_path) != manifest.v92_report_sha256  # noqa: SLF001
        or v94._canonical_hash(v92_report, "report_hash") != manifest.v92_report_hash  # noqa: SLF001
        or v69._hash_file(v94.V93_AUDIT) != manifest.v93_audit_sha256  # noqa: SLF001
        or v69._hash_file(V94_MANIFEST) != manifest.v94_manifest_sha256  # noqa: SLF001
        or v94_manifest.manifest_hash != manifest.v94_manifest_hash
        or v69._hash_file(V94_REPORT) != manifest.v94_report_sha256  # noqa: SLF001
        or v94._canonical_hash(v94_report, "report_hash") != manifest.v94_report_hash  # noqa: SLF001
        or v69._hash_file(V95_AUDIT) != manifest.v95_audit_sha256  # noqa: SLF001
        or manifest.schedule != v92_manifest.schedule
        or manifest.schedule != v94_manifest.schedule
        or manifest.workspace_runtime_image_id != v94_manifest.workspace_runtime_image_id
        or manifest.controller_image_id != v94_manifest.controller_image_id
        or manifest.controller_image_repository_digest
        != v94_manifest.controller_image_repository_digest
        or manifest.dind_image_id != v94_manifest.dind_image_id
        or manifest.dind_repository_digest != v94_manifest.dind_repository_digest
    ):
        raise ConfigurationError("v97 predecessor or fixed-image binding changed")
    if (
        v94_report.get("identity") != "deepseek-harness-hwe-v94-runtime-complete-scaffold-v1"
        or v94_report.get("status") != "stopped_without_execution_scaffold"
        or v94_report.get("stop_reason") != "ConfigurationError"
        or v94_report.get("provider_execution_scaffold_published") is not False
        or v94_report.get("provider_request_started") is not False
        or v94_report.get("provider_calls") != 0
        or v94_report.get("model_process_count") != 0
        or v94_report.get("dind_cleanup_confirmed") is not True
        or v94_report.get("raw_exception_persisted") is not False
        or (V94_ROOT / "execution-scaffold-contract.json").exists()
        or any(v94_report.get(key) is not False for key in v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v97 requires the exact audited v94 pre-provider stop")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v95_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v97 requires the merged v95 audit")
    if (
        manifest.v90_evidence_root != str(V90_ROOT)
        or manifest.v92_evidence_root != str(v94.V92_ROOT)
        or manifest.v94_evidence_root != str(V94_ROOT)
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.v90_data_volume_reused is not False
        or manifest.v92_data_volume_reused is not False
        or manifest.v94_data_volume_reused is not False
        or manifest.v96_identity_retired is not True
        or manifest.historical_derived_image_identity_required is not False
        or manifest.provider_credentials_available is not False
        or manifest.registry_access_allowed is not False
    ):
        raise ConfigurationError("v97 fresh purpose-bound DinD identity changed")


def _materialize_tasks(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    *,
    upstream: Any,
    v79_manifest: Any,
    v79_contract: Mapping[str, Any],
    instances: Mapping[str, Any],
    archive_root: Path,
    rg_binary: Path,
    rg_archive: Path,
    root: Path,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    receipts: list[dict[str, Any]] = []
    locks: dict[str, HweCommandImageLock] = {}
    if [task.task_id for task in upstream.primary_tasks] != [
        item.task_id for item in manifest.schedule
    ]:
        raise ConfigurationError("v97 upstream task order differs from the frozen schedule")
    for task, binding in zip(upstream.primary_tasks, v92_manifest.schedule, strict=True):
        expected = v81._contract_binding(v79_contract, task.task_id)  # noqa: SLF001
        diagnostic = root / "command-diagnostics" / f"pr-{task.pr_number}.json"

        def build_command_runner(
            command: list[str],
            timeout: int,
            *,
            output: Path = diagnostic,
        ) -> dict[str, Any]:
            return v94._content_free_bounded_command(  # noqa: SLF001
                command, timeout=timeout, receipt_path=output
            )

        def source_binding_runner(
            source: Path,
            task_lock: HweOfflineTaskLock,
        ) -> dict[str, str]:
            return v81._source_binding(  # noqa: SLF001
                source,
                task_lock,
                v79_manifest=v79_manifest,
                expected_binding=v81._contract_binding(  # noqa: SLF001
                    v79_contract, task_lock.task_id
                ),
            )

        receipt = v69._materialize_task(  # noqa: SLF001
            task,
            instance=instances[task.task_id],
            archive_root=archive_root,
            rg_binary=rg_binary,
            rg_archive=rg_archive,
            root=root,
            campaign_identity=IDENTITY,
            command_tag_version="v97",
            build_command_runner=build_command_runner,
            source_binding_runner=source_binding_runner,
            scan_scratch_parent=root / "scan-workspaces",
            docker_control_timeout_s=300,
        )
        receipt = v79._runtime_bound_task_receipt(  # noqa: SLF001
            receipt, task, successor=v79_manifest
        )
        v81._validate_execution_receipt(receipt, expected, task, v79_manifest)  # noqa: SLF001
        lock_path = root / "image-locks" / f"pr-{task.pr_number}.json"
        scan_path = root / "security-scans" / f"pr-{task.pr_number}.json"
        lock = HweCommandImageLock.model_validate_json(lock_path.read_bytes())
        new_lock = v94._load_json(lock_path)  # noqa: SLF001
        new_scan = v94._load_json(scan_path)  # noqa: SLF001
        old_lock = v94._load_json(V90_ROOT / "image-locks" / lock_path.name)  # noqa: SLF001
        old_scan = v94._load_json(V90_ROOT / "security-scans" / scan_path.name)  # noqa: SLF001
        if (
            receipt.get("task_hash") != binding.task_hash
            or receipt.get("source_hash") != binding.source_hash
            or receipt.get("prepared_source_image_lock_sha256")
            != binding.prepared_source_image_lock_sha256
            or receipt.get("official_verifier_image") != binding.official_verifier_image
            or receipt.get("agent_toolchain_id") != binding.agent_toolchain_id
            or receipt.get("toolchain_profile_id") != binding.toolchain_profile_id
            or receipt.get("agent_command_image") != lock.derived_command_image_id
            or receipt.get("agent_command_image_lock_hash") != lock.lock_hash
            or receipt.get("security_scan_id") != lock.security_scan_id
            or _without(old_lock, "derived_command_image_id", "lock_hash", "security_scan_id")
            != _without(new_lock, "derived_command_image_id", "lock_hash", "security_scan_id")
            or _without(
                old_scan,
                "derived_command_image_id",
                "diagnostic",
                "security_scan_id",
                "unsanitized_command_image_id",
            )
            != _without(
                new_scan,
                "derived_command_image_id",
                "diagnostic",
                "security_scan_id",
                "unsanitized_command_image_id",
            )
        ):
            raise ConfigurationError("v97 rebuilt task semantics differ from the audited binding")
        receipt_base = dict(receipt)
        receipt_base.pop("task_receipt_hash", None)
        receipt_base.update(
            {
                "cross_build_command_image_identity_policy": "fresh-materialization-lock-v1",
                "historical_derived_image_identity_required": False,
                "historical_derived_command_image": binding.command_image,
                "fresh_derived_command_image": lock.derived_command_image_id,
                "cross_build_derived_image_identity_equal": (
                    binding.command_image == lock.derived_command_image_id
                ),
                "command_image_lock_semantics_match": True,
                "security_scan_semantics_match": True,
            }
        )
        sealed_receipt = {
            **receipt_base,
            "task_receipt_hash": content_hash(receipt_base),
        }
        receipts.append(sealed_receipt)
        locks[task.task_id] = lock
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v97_task_materialization_set_v1",
        "identity": IDENTITY,
        "completed_task_ids": [item["task_id"] for item in receipts],
        "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
        "task_count": len(receipts),
        "all_reference_patches_compatible": True,
        "all_base_failed_reference_passed": True,
        "all_command_images_v2_scanned": True,
        "all_historical_task_semantics_matched": True,
        "historical_derived_image_identity_required": False,
        "source_preparation_docker_control_timeout_seconds": 300,
        "registry_accessed": False,
        "partial_archive_used": False,
        "provider_calls": 0,
        "task_receipts": receipts,
    }
    if len(receipts) != 5:
        raise ConfigurationError("v97 refuses partial task materialization")
    value = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "task-materialization-set.json", value)
    return value, locks


def _without(value: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    for key in keys:
        result.pop(key, None)
    return result


def _scaffold_contract(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
    runtime_receipt: Mapping[str, Any],
    transfer: Mapping[str, Any],
    task_materialization: Mapping[str, Any],
    inventory: Mapping[str, Any],
    runtime_preflight: Mapping[str, Any],
    harness_preflight: Mapping[str, Any],
    cleanup: Mapping[str, Any],
) -> dict[str, Any]:
    schedule = [item.task_id for item in manifest.schedule]
    task_receipts = task_materialization.get("task_receipts")
    if (
        inventory.get("required_image_count") != 12
        or inventory.get("workspace_runtime_image_present") is not True
        or task_materialization.get("completed_task_ids") != schedule
        or task_materialization.get("task_count") != 5
        or task_materialization.get("all_base_failed_reference_passed") is not True
        or task_materialization.get("all_command_images_v2_scanned") is not True
        or task_materialization.get("all_historical_task_semantics_matched") is not True
        or task_materialization.get("historical_derived_image_identity_required") is not False
        or not isinstance(task_receipts, list)
        or [item.get("task_id") for item in task_receipts if isinstance(item, dict)] != schedule
        or any(
            not isinstance(item, dict)
            or item.get("command_image_lock_semantics_match") is not True
            or item.get("security_scan_semantics_match") is not True
            or item.get("historical_derived_image_identity_required") is not False
            for item in task_receipts
        )
        or runtime_preflight.get("completed_task_ids") != schedule
        or runtime_preflight.get("task_count") != 5
        or harness_preflight.get("provider_request_started") is not False
        or harness_preflight.get("provider_call_count") != 0
        or harness_preflight.get("provider_values_persisted_or_hashed") is not False
    ):
        raise ConfigurationError("v97 refuses a partial or provider-crossing scaffold contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v97_execution_scaffold_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "v92_manifest_hash": manifest.v92_manifest_hash,
        "v92_report_hash": manifest.v92_report_hash,
        "v94_manifest_hash": manifest.v94_manifest_hash,
        "v94_report_hash": manifest.v94_report_hash,
        "v95_audit_commit": manifest.v95_audit_commit,
        "v95_post_merge_main_run_id": manifest.v95_post_merge_main_run_id,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "schedule": schedule,
        "task_bindings": task_receipts,
        "task_count": len(schedule),
        "cross_build_command_image_identity_policy": (
            manifest.cross_build_command_image_identity_policy
        ),
        "historical_derived_image_identity_required": False,
        "historical_task_semantics_required": True,
        "all_historical_task_semantics_matched": True,
        "v90_task_qualification_reused_as_expected_binding": True,
        "v97_tasks_materialized_from_completed_local_archives": True,
        "all_base_failed_reference_passed": True,
        "all_command_images_v2_scanned": True,
        "controller_and_workspace_runtime_transferred": True,
        "required_inner_image_count": manifest.required_inner_image_count,
        "workspace_runtime_image_id": manifest.workspace_runtime_image_id,
        "workspace_runtime_transfer_receipt_hash": transfer["workspace_runtime_receipt_hash"],
        "controller_transfer_receipt_hash": transfer["controller_receipt_hash"],
        "image_transfer_set_hash": transfer["receipt_hash"],
        "task_materialization_receipt_hash": task_materialization["receipt_hash"],
        "execution_inventory_hash": inventory["inventory_hash"],
        "runtime_prepare_receipt_hash": runtime_preflight["receipt_hash"],
        "harness_initialize_receipt_hash": harness_preflight["receipt_hash"],
        "dind_runtime_receipt_hash": runtime_receipt["receipt_hash"],
        "dind_cleanup_receipt_hash": cleanup["receipt_hash"],
        "dind_cleanup_confirmed": True,
        "dind_data_volume": manifest.dind_data_volume,
        "dind_data_backing": manifest.dind_data_backing,
        "scaffold_outer_network": manifest.scaffold_outer_network,
        "preflight_inner_network_was_internal": True,
        "preflight_inner_network_removed": True,
        "task_network": manifest.task_network,
        "verifier_network": manifest.verifier_network,
        "host_docker_root_used_for_task_layers": False,
        "v90_data_volume_reused": False,
        "v92_data_volume_reused": False,
        "v94_data_volume_reused": False,
        "v96_identity_retired": True,
        "provider_successor_identity": manifest.provider_successor_identity,
        "provider_successor_reopen_budget": manifest.provider_successor_reopen_budget,
        "provider_successor_reopen_count": 0,
        "provider_execution_scaffold_published": True,
        "provider_execution_authorized": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "requires_independent_v98_audit": True,
        **v94._closed_training_flags(),  # noqa: SLF001
    }
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("v97 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = v94._git_text("branch", "--show-current")  # noqa: SLF001
    head = v94._git_text("rev-parse", "HEAD")  # noqa: SLF001
    upstream = v94._git_text("rev-parse", "origin/main")  # noqa: SLF001
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v95_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if (
        branch != "main"
        or head != upstream
        or len(head) != 40
        or ancestor.returncode != 0
        or ancestor.stdout
        or ancestor.stderr
    ):
        raise ConfigurationError("v97 requires clean merged origin/main after v95")
    return head


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "provider_execution_scaffold_published": report[
                    "provider_execution_scaffold_published"
                ],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["provider_execution_scaffold_published"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
