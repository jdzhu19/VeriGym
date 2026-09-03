#!/usr/bin/env python3
"""Materialize a fresh five-task scaffold with bounded inventory Docker controls."""

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
    materialize_hwe_deepseek_harness_v97_rebuild_identity_scaffold as v97,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    load_v100_inventory_timeout_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V100_INVENTORY_TIMEOUT_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v100_inventory_timeout_scaffold_v1.json"
)
V97_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v97_rebuild_identity_scaffold_v1.json"
)
V97_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1"
)
V97_REPORT = V97_ROOT / "execution-scaffold-report.json"
V98_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v98-v97-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v100")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v100-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v100-runtime")
_REQUIRED_MERGED_PATHS = (
    *v97._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "configs/training/qwen35_hwe_deepseek_harness_v100_inventory_timeout_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v98-v97-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v100-inventory-timeout-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v100_inventory_timeout_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v100_inventory_timeout_scaffold.py",
)

_V97_TRANSFER_IMAGES = v97._transfer_images  # noqa: SLF001
_V97_RUNTIME_PREPARE_PREFLIGHT = v97._runtime_prepare_preflight  # noqa: SLF001
_V97_HARNESS_INITIALIZE_PREFLIGHT = v97._harness_initialize_preflight  # noqa: SLF001
_V97_INVENTORY = v97._inventory  # noqa: SLF001
_V97_RUNTIME_RECEIPT = v97._runtime_receipt  # noqa: SLF001
_V97_CLEAN_SOCKET_VOLUME = v97._clean_socket_volume  # noqa: SLF001
_V97_VALIDATE_STATIC_BINDINGS = v97._validate_static_bindings  # noqa: SLF001
_V97_MATERIALIZE_TASKS = v97._materialize_tasks  # noqa: SLF001
_V97_SCAFFOLD_CONTRACT = v97._scaffold_contract  # noqa: SLF001
_V97_REQUIRE_CLEAN_MERGED_MAIN = v97._require_clean_merged_main  # noqa: SLF001
_LOAD_V97_REBUILD_IDENTITY_SCAFFOLD_MANIFEST = v97.load_v97_rebuild_identity_scaffold_manifest
_V69_BOUNDED_COMMAND = v69._bounded_command  # noqa: SLF001
_V69_MATERIALIZE_TASK = v69._materialize_task  # noqa: SLF001


def _parser() -> argparse.ArgumentParser:
    parser = v97._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the v97-tested workflow under fresh v100 bindings and timeouts."""

    with _v100_base_configuration():
        return v97.materialize(arguments)


@contextlib.contextmanager
def _v100_base_configuration() -> Iterator[None]:
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
        "load_v97_rebuild_identity_scaffold_manifest": (
            load_v100_inventory_timeout_scaffold_manifest
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
    previous = {name: getattr(v97, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v97, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v97, name, value)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v100 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v100_scaffold_progress_v1",
            "v97_manifest_hash": (
                "7bb335f8f6418b6cd4d5e315db67060672b8fc4d3d47b1cc68f3b8a7d5e94cc7"
            ),
            "v97_report_hash": ("6000435cb3f439cb206666dc06c55332e02d8a85cd688eb5e055537274f67f18"),
            "v98_audit_commit": "a766cc9d564f89c96170b1e451852e29e107388e",
            "v98_post_merge_main_run_id": 33782913003,
        }
    )
    if value.get("status") in {
        "completed_pending_independent_v95_audit",
        "completed_pending_independent_v98_audit",
    }:
        value["status"] = "completed_pending_independent_v101_audit"
    v97._V94_WRITE_PROGRESS(root, value)  # noqa: SLF001


def _transfer_images(
    dind_name: str,
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V97_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v97.v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v100_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v100 image transfer receipt inventory is not exactly two")
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
        format_id="verigym_deepseek_harness_hwe_v100_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    return _reseal(
        _V97_RUNTIME_PREPARE_PREFLIGHT(manifest, locks=locks, dind_name=dind_name),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v100_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    return _reseal(
        _V97_HARNESS_INITIALIZE_PREFLIGHT(
            manifest,
            controller_receipt_hash=controller_receipt_hash,
            root=root,
        ),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v100_harness_initialize_preflight_v1",
    )


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
) -> dict[str, Any]:
    return _reseal(
        _V97_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v100_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V97_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value["v97_data_volume_reused"] = False
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v100_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    result = _reseal(
        _V97_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v100_socket_cleanup_receipt_v1",
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
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    _V97_VALIDATE_STATIC_BINDINGS(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v92_manifest_path,
        v92_report_path=v92_report_path,
    )
    v97_manifest = _LOAD_V97_REBUILD_IDENTITY_SCAFFOLD_MANIFEST(V97_MANIFEST)
    v97_report = v97.v94._load_json(V97_REPORT)  # noqa: SLF001
    if (
        v69._hash_file(V97_MANIFEST) != manifest.v97_manifest_sha256  # noqa: SLF001
        or v97_manifest.manifest_hash != manifest.v97_manifest_hash
        or v69._hash_file(V97_REPORT) != manifest.v97_report_sha256  # noqa: SLF001
        or v97.v94._canonical_hash(v97_report, "report_hash")  # noqa: SLF001
        != manifest.v97_report_hash
        or v69._hash_file(V98_AUDIT) != manifest.v98_audit_sha256  # noqa: SLF001
    ):
        raise ConfigurationError("v100 predecessor evidence binding changed")
    if (
        v97_report.get("identity") != "deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1"
        or v97_report.get("status") != "stopped_without_execution_scaffold"
        or v97_report.get("stop_reason") != "TimeoutExpired"
        or v97_report.get("provider_execution_scaffold_published") is not False
        or v97_report.get("provider_request_started") is not False
        or v97_report.get("provider_calls") != 0
        or v97_report.get("model_process_count") != 0
        or v97_report.get("dind_cleanup_confirmed") is not True
        or v97_report.get("raw_exception_persisted") is not False
        or (V97_ROOT / "execution-scaffold-contract.json").exists()
        or any(
            v97_report.get(key) is not False
            for key in v97.v94._closed_training_flags()  # noqa: SLF001
        )
    ):
        raise ConfigurationError("v100 requires the exact audited v97 pre-provider stop")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v98_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v100 requires the merged v98 audit")
    if (
        manifest.v97_evidence_root != str(V97_ROOT)
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.toolchain_inventory_create_timeout_seconds != 300
        or manifest.toolchain_inventory_inspect_timeout_seconds != 300
        or manifest.toolchain_inventory_execute_timeout_seconds != 120
        or manifest.toolchain_inventory_remove_timeout_seconds != 300
        or manifest.v97_data_volume_reused is not False
        or manifest.v99_identity_retired is not True
        or manifest.provider_credentials_available is not False
        or manifest.registry_access_allowed is not False
    ):
        raise ConfigurationError("v100 fresh purpose-bound timeout identity changed")


@contextlib.contextmanager
def _v100_inventory_controls(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
) -> Iterator[None]:
    def bounded(
        command: list[str],
        *,
        timeout: int,
        return_stdout: bool = False,
        require_empty: bool = False,
    ) -> bytes:
        return _inventory_bounded_command(
            manifest,
            command,
            timeout=timeout,
            return_stdout=return_stdout,
            require_empty=require_empty,
        )

    def inspect(container_id: str) -> dict[str, Any]:
        return _inventory_docker_inspect(manifest, container_id)

    previous_bounded = v69._bounded_command  # noqa: SLF001
    previous_inspect = v69._docker_inspect  # noqa: SLF001
    previous_materialize = v69._materialize_task  # noqa: SLF001
    try:
        v69._bounded_command = bounded  # type: ignore[assignment]  # noqa: SLF001
        v69._docker_inspect = inspect  # type: ignore[assignment]  # noqa: SLF001
        v69._materialize_task = _v100_materialize_task  # type: ignore[assignment]  # noqa: SLF001
        yield
    finally:
        v69._bounded_command = previous_bounded  # type: ignore[assignment]  # noqa: SLF001
        v69._docker_inspect = previous_inspect  # type: ignore[assignment]  # noqa: SLF001
        v69._materialize_task = previous_materialize  # type: ignore[assignment]  # noqa: SLF001


def _v100_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v100 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v100"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _inventory_bounded_command(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    command: list[str],
    *,
    timeout: int,
    return_stdout: bool = False,
    require_empty: bool = False,
) -> bytes:
    selected_timeout = timeout
    is_create = (
        command[:2] == ["docker", "create"]
        and f"org.verigym.owner={IDENTITY}" in command
        and "org.verigym.role=toolchain_inventory" in command
    )
    is_remove = command[:4] == ["docker", "container", "rm", "--force"]
    is_execute = command[:3] == ["docker", "start", "--attach"]
    if is_create:
        if timeout != 30:
            raise ConfigurationError("v100 inventory create inherited an unexpected bound")
        selected_timeout = manifest.toolchain_inventory_create_timeout_seconds
    elif is_remove:
        if timeout != 30:
            raise ConfigurationError("v100 inventory remove inherited an unexpected bound")
        selected_timeout = manifest.toolchain_inventory_remove_timeout_seconds
    elif is_execute and timeout != manifest.toolchain_inventory_execute_timeout_seconds:
        raise ConfigurationError("v100 inventory execution inherited an unexpected bound")
    return _V69_BOUNDED_COMMAND(
        command,
        timeout=selected_timeout,
        return_stdout=return_stdout,
        require_empty=require_empty,
    )


def _inventory_docker_inspect(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    container_id: str,
) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "container", "inspect", container_id],
        check=False,
        capture_output=True,
        timeout=manifest.toolchain_inventory_inspect_timeout_seconds,
    )
    if result.returncode != 0 or result.stderr or len(result.stdout) > v69._MAX_CONTROL_OUTPUT:  # noqa: SLF001
        raise ConfigurationError("v100 container inspection failed")
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ConfigurationError("v100 container inspection output is malformed") from exc
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ConfigurationError("v100 container inspection output is malformed")
    return value[0]


def _materialize_tasks(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
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
    with _v100_inventory_controls(manifest):
        value, locks = _V97_MATERIALIZE_TASKS(
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
    if not isinstance(receipts, list) or len(receipts) != 5:
        raise ConfigurationError("v100 refuses partial task materialization")
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ConfigurationError("v100 task receipt is malformed")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "toolchain_inventory_create_timeout_seconds": (
                    manifest.toolchain_inventory_create_timeout_seconds
                ),
                "toolchain_inventory_inspect_timeout_seconds": (
                    manifest.toolchain_inventory_inspect_timeout_seconds
                ),
                "toolchain_inventory_execute_timeout_seconds": (
                    manifest.toolchain_inventory_execute_timeout_seconds
                ),
                "toolchain_inventory_remove_timeout_seconds": (
                    manifest.toolchain_inventory_remove_timeout_seconds
                ),
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v100_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "toolchain_inventory_create_timeout_seconds": (
                manifest.toolchain_inventory_create_timeout_seconds
            ),
            "toolchain_inventory_inspect_timeout_seconds": (
                manifest.toolchain_inventory_inspect_timeout_seconds
            ),
            "toolchain_inventory_execute_timeout_seconds": (
                manifest.toolchain_inventory_execute_timeout_seconds
            ),
            "toolchain_inventory_remove_timeout_seconds": (
                manifest.toolchain_inventory_remove_timeout_seconds
            ),
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    **kwargs: Any,
) -> dict[str, Any]:
    value = _V97_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("v97_tasks_materialized_from_completed_local_archives", None)
    base.pop("requires_independent_v98_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v100_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v97_manifest_hash": manifest.v97_manifest_hash,
            "v97_report_hash": manifest.v97_report_hash,
            "v98_audit_commit": manifest.v98_audit_commit,
            "v98_post_merge_main_run_id": manifest.v98_post_merge_main_run_id,
            "v100_tasks_materialized_from_completed_local_archives": True,
            "toolchain_inventory_create_timeout_seconds": (
                manifest.toolchain_inventory_create_timeout_seconds
            ),
            "toolchain_inventory_inspect_timeout_seconds": (
                manifest.toolchain_inventory_inspect_timeout_seconds
            ),
            "toolchain_inventory_execute_timeout_seconds": (
                manifest.toolchain_inventory_execute_timeout_seconds
            ),
            "toolchain_inventory_remove_timeout_seconds": (
                manifest.toolchain_inventory_remove_timeout_seconds
            ),
            "v97_data_volume_reused": False,
            "v99_identity_retired": True,
            "requires_independent_v101_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
) -> str:
    head = _V97_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v98_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v100 requires clean merged origin/main after v98")
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
