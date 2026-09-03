#!/usr/bin/env python3
"""Materialize a fresh five-task scaffold with lock-derived inner-image inventory."""

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
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v103_inspect_output_bound_scaffold as v103,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    load_v106_fresh_inventory_binding_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V106_FRESH_INVENTORY_BINDING_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold_v1.json"
)
V103_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v103_inspect_output_bound_scaffold_v1.json"
)
V103_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v103_inspect_output_bound_scaffold.py"
)
V103_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1"
)
V103_REPORT = V103_ROOT / "execution-scaffold-report.json"
V103_PROGRESS = V103_ROOT / "execution-scaffold-progress.json"
V103_TASK_MATERIALIZATION = V103_ROOT / "task-materialization-set.json"
V104_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v104-v103-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v106")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v106-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v106-runtime")
_REQUIRED_MERGED_PATHS = (
    *v103._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "configs/training/qwen35_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v104-v103-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v106-fresh-inventory-binding-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v106_fresh_inventory_binding_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold.py",
)

_V103_TRANSFER_IMAGES = v103._transfer_images  # noqa: SLF001
_V103_RUNTIME_PREPARE_PREFLIGHT = v103._runtime_prepare_preflight  # noqa: SLF001
_V103_HARNESS_INITIALIZE_PREFLIGHT = v103._harness_initialize_preflight  # noqa: SLF001
_V103_RUNTIME_RECEIPT = v103._runtime_receipt  # noqa: SLF001
_V103_CLEAN_SOCKET_VOLUME = v103._clean_socket_volume  # noqa: SLF001
_V103_VALIDATE_STATIC_BINDINGS = v103._validate_static_bindings  # noqa: SLF001
_V103_MATERIALIZE_TASKS = v103._materialize_tasks  # noqa: SLF001
_V103_SCAFFOLD_CONTRACT = v103._scaffold_contract  # noqa: SLF001
_V103_REQUIRE_CLEAN_MERGED_MAIN = v103._require_clean_merged_main  # noqa: SLF001
_LOAD_V103_INSPECT_OUTPUT_BOUND_SCAFFOLD_MANIFEST = (
    v103.load_v103_inspect_output_bound_scaffold_manifest
)
_V69_MATERIALIZE_TASK = v103._V69_MATERIALIZE_TASK  # noqa: SLF001

_ACTIVE_FRESH_COMMAND_IMAGES: dict[str, str] | None = None


def _parser() -> argparse.ArgumentParser:
    parser = v103._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the v103-tested workflow under fresh v106 inventory bindings."""

    with _v106_configuration():
        return v103.materialize(arguments)


@contextlib.contextmanager
def _v106_configuration() -> Iterator[None]:
    global _ACTIVE_FRESH_COMMAND_IMAGES

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
        "load_v103_inspect_output_bound_scaffold_manifest": (
            load_v106_fresh_inventory_binding_scaffold_manifest
        ),
        "_write_progress": _write_progress,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_v103_materialize_task": _v106_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v103, name) for name in replacements}
    previous_images = _ACTIVE_FRESH_COMMAND_IMAGES
    if previous_images is not None:
        raise ConfigurationError("v106 fresh inventory binding is already active")
    try:
        for name, value in replacements.items():
            setattr(v103, name, value)
        yield
    finally:
        _ACTIVE_FRESH_COMMAND_IMAGES = previous_images
        for name, value in previous.items():
            setattr(v103, name, value)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v106 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v106_scaffold_progress_v1",
            "v103_manifest_hash": (
                "931a3863559c848e53a6015fc023275f5fb4a12927e09fe70b47c38ac66c5fee"
            ),
            "v103_report_hash": (
                "0de771890a66ab9b70016b02892851135767c96d601d9927b3123deeb3a22e7c"
            ),
            "v104_audit_commit": "95b9a11dbb3833fd57fc5b0a43bcd8708bc25865",
            "v104_post_merge_main_run_id": 33795946043,
        }
    )
    if value.get("status") in {
        "completed_pending_independent_v95_audit",
        "completed_pending_independent_v98_audit",
        "completed_pending_independent_v101_audit",
        "completed_pending_independent_v104_audit",
    }:
        value["status"] = "completed_pending_independent_v107_audit"
    v103.v100.v97.v94._V94_WRITE_PROGRESS(root, value)  # noqa: SLF001


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


def _transfer_images(
    dind_name: str,
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V103_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v103.v100.v97.v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v106_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v106 image transfer receipt inventory is not exactly two")
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
        format_id="verigym_deepseek_harness_hwe_v106_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    return _reseal(
        _V103_RUNTIME_PREPARE_PREFLIGHT(manifest, locks=locks, dind_name=dind_name),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v106_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    return _reseal(
        _V103_HARNESS_INITIALIZE_PREFLIGHT(
            manifest,
            controller_receipt_hash=controller_receipt_hash,
            root=root,
        ),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v106_harness_initialize_preflight_v1",
    )


def _runtime_receipt(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V103_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value["v103_data_volume_reused"] = False
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v106_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    result = _reseal(
        _V103_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v106_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _validate_static_bindings(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    _V103_VALIDATE_STATIC_BINDINGS(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v92_manifest_path,
        v92_report_path=v92_report_path,
    )
    v103_manifest = _LOAD_V103_INSPECT_OUTPUT_BOUND_SCAFFOLD_MANIFEST(V103_MANIFEST)
    v103_report = v103.v100.v97.v94._load_json(V103_REPORT)  # noqa: SLF001
    v103_tasks = v103.v100.v97.v94._load_json(V103_TASK_MATERIALIZATION)  # noqa: SLF001
    if (
        v69._hash_file(V103_MANIFEST) != manifest.v103_manifest_sha256  # noqa: SLF001
        or v103_manifest.manifest_hash != manifest.v103_manifest_hash
        or v69._hash_file(V103_RUNNER) != manifest.v103_runner_sha256  # noqa: SLF001
        or v69._hash_file(V103_REPORT) != manifest.v103_report_sha256  # noqa: SLF001
        or v69._hash_file(V103_PROGRESS) != manifest.v103_report_sha256  # noqa: SLF001
        or v103.v100.v97.v94._canonical_hash(v103_report, "report_hash")  # noqa: SLF001
        != manifest.v103_report_hash
        or v69._hash_file(V103_TASK_MATERIALIZATION)  # noqa: SLF001
        != manifest.v103_task_materialization_sha256
        or v103.v100.v97.v94._canonical_hash(v103_tasks, "receipt_hash")  # noqa: SLF001
        != manifest.v103_task_materialization_hash
        or v69._hash_file(V104_AUDIT) != manifest.v104_audit_sha256  # noqa: SLF001
    ):
        raise ConfigurationError("v106 predecessor evidence binding changed")
    if (
        v103_report.get("identity") != "deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1"
        or v103_report.get("status") != "stopped_without_execution_scaffold"
        or v103_report.get("stop_reason") != "ConfigurationError"
        or v103_report.get("completed_stages")
        != ["controller_and_workspace_runtime_transferred", "five_task_offline_materialization"]
        or v103_report.get("provider_execution_scaffold_published") is not False
        or v103_report.get("provider_request_started") is not False
        or v103_report.get("provider_calls") != 0
        or v103_report.get("model_process_count") != 0
        or v103_report.get("dind_cleanup_confirmed") is not True
        or v103_report.get("raw_exception_persisted") is not False
        or (V103_ROOT / "execution-scaffold-contract.json").exists()
        or (V103_ROOT / "execution-inventory.json").exists()
        or any(
            v103_report.get(key) is not False
            for key in v103.v100.v97.v94._closed_training_flags()  # noqa: SLF001
        )
    ):
        raise ConfigurationError("v106 requires the exact audited v103 pre-provider stop")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    receipts = v103_tasks.get("task_receipts")
    if (
        v103_tasks.get("identity") != "deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1"
        or v103_tasks.get("task_count") != 5
        or v103_tasks.get("completed_task_ids") != expected_task_ids
        or not isinstance(receipts, list)
        or len(receipts) != 5
        or v103_tasks.get("all_base_failed_reference_passed") is not True
        or v103_tasks.get("all_command_images_v2_scanned") is not True
        or v103_tasks.get("all_historical_task_semantics_matched") is not True
        or v103_tasks.get("all_reference_patches_compatible") is not True
        or v103_tasks.get("partial_archive_used") is not False
        or v103_tasks.get("registry_accessed") is not False
        or v103_tasks.get("provider_calls") != 0
        or v103_tasks.get("toolchain_inventory_inspect_output_bound_bytes") != 1024 * 1024
    ):
        raise ConfigurationError("v106 requires the exact complete v103 task materialization")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v104_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v106 requires the merged v104 audit")
    if (
        manifest.v103_evidence_root != str(V103_ROOT)
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.final_inventory_command_image_source != "fresh-materialization-locks"
        or manifest.final_inventory_fresh_command_image_count != 5
        or manifest.required_inner_image_count != 12
        or manifest.v103_data_volume_reused is not False
        or manifest.v105_identity_retired is not True
        or manifest.provider_credentials_available is not False
        or manifest.registry_access_allowed is not False
    ):
        raise ConfigurationError("v106 fresh purpose-bound inventory identity changed")


def _v106_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v106 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v106"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _materialize_tasks(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
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
    global _ACTIVE_FRESH_COMMAND_IMAGES

    value, locks = _V103_MATERIALIZE_TASKS(
        manifest,
        v92_manifest,
        upstream=upstream,
        v79_manifest=v79_manifest,
        v79_contract=v79_contract,
        instances=instances,
        archive_root=archive_root,
        rg_binary=rg_binary,
        rg_archive=rg_archive,
        root=root,
    )
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if (
        _ACTIVE_FRESH_COMMAND_IMAGES is not None
        or set(locks) != set(expected_task_ids)
        or not isinstance(receipts, list)
        or len(receipts) != 5
    ):
        raise ConfigurationError("v106 refuses incomplete fresh command-image locks")
    receipts_by_task: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("task_id"), str):
            raise ConfigurationError("v106 task receipt is malformed")
        if receipt["task_id"] in receipts_by_task:
            raise ConfigurationError("v106 task receipt inventory contains a duplicate")
        receipts_by_task[receipt["task_id"]] = receipt
    if set(receipts_by_task) != set(expected_task_ids):
        raise ConfigurationError("v106 task receipt inventory changed")

    fresh_images: dict[str, str] = {}
    lock_hashes: dict[str, str] = {}
    schedule_by_task = {item.task_id: item for item in manifest.schedule}
    for task_id in expected_task_ids:
        lock = locks[task_id]
        receipt = receipts_by_task[task_id]
        schedule = schedule_by_task[task_id]
        if (
            lock.task_id != task_id
            or receipt.get("agent_command_image") != lock.derived_command_image_id
            or receipt.get("fresh_derived_command_image") != lock.derived_command_image_id
            or receipt.get("agent_command_image_lock_hash") != lock.lock_hash
            or receipt.get("official_verifier_image") != lock.verifier_base_image_id
            or lock.verifier_base_image_id != schedule.official_verifier_image
            or receipt.get("historical_derived_command_image") != schedule.command_image
            or receipt.get("historical_derived_image_identity_required") is not False
            or receipt.get("cross_build_derived_image_identity_equal") is not False
        ):
            raise ConfigurationError("v106 fresh command-image receipt binding changed")
        receipt.pop("task_receipt_hash", None)
        receipt["final_inventory_command_image_source"] = "fresh-materialization-lock"
        receipt["final_inventory_command_image"] = lock.derived_command_image_id
        receipt["task_receipt_hash"] = content_hash(receipt)
        fresh_images[task_id] = lock.derived_command_image_id
        lock_hashes[task_id] = lock.lock_hash
    if len(set(fresh_images.values())) != manifest.final_inventory_fresh_command_image_count:
        raise ConfigurationError("v106 fresh command-image inventory is not distinct")

    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v106_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [
                receipts_by_task[item]["task_receipt_hash"] for item in expected_task_ids
            ],
            "final_inventory_command_image_source": (manifest.final_inventory_command_image_source),
            "final_inventory_fresh_command_images": fresh_images,
            "final_inventory_fresh_command_image_lock_hashes": lock_hashes,
            "final_inventory_fresh_command_image_count": len(fresh_images),
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "task-materialization-set.json", result)
    _ACTIVE_FRESH_COMMAND_IMAGES = fresh_images
    return result, locks


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
) -> dict[str, Any]:
    fresh_images = _ACTIVE_FRESH_COMMAND_IMAGES
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if (
        fresh_images is None
        or list(fresh_images) != expected_task_ids
        or len(set(fresh_images.values())) != manifest.final_inventory_fresh_command_image_count
    ):
        raise ConfigurationError("v106 final inventory lacks fresh command-image bindings")
    result = v103.v100.v97.v94.dind._inner(  # noqa: SLF001
        ["image", "ls", "--all", "--no-trunc", "--format", "{{.ID}}"],
        container=dind_name,
        timeout_s=30,
    )
    if (
        result.returncode != 0
        or result.stderr
        or not result.stdout
        or len(result.stdout) > manifest.toolchain_inventory_inspect_output_bound_bytes
    ):
        raise ConfigurationError("v106 inner image inventory command failed")
    try:
        observed_lines = result.stdout.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise ConfigurationError("v106 inner image inventory is malformed") from exc
    if not observed_lines or any(
        v103.v100.v97.v94._DIGEST.fullmatch(item) is None  # noqa: SLF001
        for item in observed_lines
    ):
        raise ConfigurationError("v106 inner image inventory is malformed")
    observed = sorted(set(observed_lines))
    official_images = {item.official_verifier_image for item in manifest.schedule}
    required = sorted(
        {
            manifest.controller_image_id,
            manifest.workspace_runtime_image_id,
            *fresh_images.values(),
            *official_images,
        }
    )
    if (
        len(official_images) != 5
        or len(required) != manifest.required_inner_image_count
        or not set(required).issubset(observed)
    ):
        raise ConfigurationError("v106 inner image inventory is incomplete or inconsistent")
    historical = {item.task_id: item.command_image for item in manifest.schedule}
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v106_execution_inventory_v1",
        "identity": IDENTITY,
        "required_image_ids": required,
        "observed_image_ids": observed,
        "required_image_count": len(required),
        "observed_image_count": len(observed),
        "required_images_present": True,
        "workspace_runtime_image_present": manifest.workspace_runtime_image_id in observed,
        "final_inventory_command_image_source": manifest.final_inventory_command_image_source,
        "fresh_command_images_by_task": dict(fresh_images),
        "fresh_command_image_count": len(fresh_images),
        "historical_command_images_by_task": historical,
        "historical_command_images_required": False,
        "preflight_inner_network_removed": True,
        "inner_container_inventory_empty": True,
        "inner_volume_inventory_empty": True,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    return {**base, "inventory_hash": content_hash(base)}


def _scaffold_contract(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    **kwargs: Any,
) -> dict[str, Any]:
    task_materialization = kwargs.get("task_materialization")
    inventory = kwargs.get("inventory")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if not isinstance(task_materialization, Mapping) or not isinstance(inventory, Mapping):
        raise ConfigurationError("v106 contract requires fresh inventory evidence")
    fresh_images = task_materialization.get("final_inventory_fresh_command_images")
    lock_hashes = task_materialization.get("final_inventory_fresh_command_image_lock_hashes")
    task_receipts = task_materialization.get("task_receipts")
    required_image_ids = inventory.get("required_image_ids")
    if (
        not isinstance(fresh_images, dict)
        or list(fresh_images) != expected_task_ids
        or not isinstance(lock_hashes, dict)
        or list(lock_hashes) != expected_task_ids
        or not isinstance(task_receipts, list)
        or not isinstance(required_image_ids, list)
        or len(task_receipts) != manifest.final_inventory_fresh_command_image_count
        or len(set(fresh_images.values())) != manifest.final_inventory_fresh_command_image_count
        or task_materialization.get("final_inventory_command_image_source")
        != manifest.final_inventory_command_image_source
        or task_materialization.get("final_inventory_fresh_command_image_count")
        != manifest.final_inventory_fresh_command_image_count
        or inventory.get("final_inventory_command_image_source")
        != manifest.final_inventory_command_image_source
        or inventory.get("fresh_command_images_by_task") != fresh_images
        or inventory.get("fresh_command_image_count")
        != manifest.final_inventory_fresh_command_image_count
        or inventory.get("historical_command_images_required") is not False
        or not set(fresh_images.values()).issubset(required_image_ids)
    ):
        raise ConfigurationError("v106 contract refuses stale or incomplete fresh inventory")
    receipts_by_task = {
        receipt.get("task_id"): receipt for receipt in task_receipts if isinstance(receipt, dict)
    }
    if list(receipts_by_task) != expected_task_ids or any(
        receipts_by_task[task_id].get("final_inventory_command_image") != fresh_images[task_id]
        or receipts_by_task[task_id].get("final_inventory_command_image_source")
        != "fresh-materialization-lock"
        for task_id in expected_task_ids
    ):
        raise ConfigurationError("v106 contract refuses inconsistent task inventory bindings")
    value = _V103_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("v103_tasks_materialized_from_completed_local_archives", None)
    base.pop("requires_independent_v104_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v106_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v103_manifest_hash": manifest.v103_manifest_hash,
            "v103_report_hash": manifest.v103_report_hash,
            "v103_task_materialization_hash": manifest.v103_task_materialization_hash,
            "v104_audit_commit": manifest.v104_audit_commit,
            "v104_post_merge_main_run_id": manifest.v104_post_merge_main_run_id,
            "v106_tasks_materialized_from_completed_local_archives": True,
            "final_inventory_command_image_source": (manifest.final_inventory_command_image_source),
            "final_inventory_fresh_command_image_count": (
                manifest.final_inventory_fresh_command_image_count
            ),
            "v103_data_volume_reused": False,
            "v105_identity_retired": True,
            "requires_independent_v107_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
) -> str:
    head = _V103_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v104_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v106 requires clean merged origin/main after v104")
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
