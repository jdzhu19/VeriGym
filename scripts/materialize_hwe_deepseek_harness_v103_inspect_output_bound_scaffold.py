#!/usr/bin/env python3
"""Materialize a fresh five-task scaffold with the dedicated Docker inspect bound."""

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
    materialize_hwe_deepseek_harness_v100_inventory_timeout_scaffold as v100,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    load_v103_inspect_output_bound_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V103_INSPECT_OUTPUT_BOUND_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v103_inspect_output_bound_scaffold_v1.json"
)
V100_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v100_inventory_timeout_scaffold_v1.json"
)
V100_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v100_inventory_timeout_scaffold.py"
)
V100_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1"
)
V100_REPORT = V100_ROOT / "execution-scaffold-report.json"
V100_PROGRESS = V100_ROOT / "execution-scaffold-progress.json"
V101_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v101-v100-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v103")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v103-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v103-runtime")
_REQUIRED_MERGED_PATHS = (
    *v100._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "configs/training/qwen35_hwe_deepseek_harness_v103_inspect_output_bound_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v101-v100-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v103-inspect-output-bound-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v103_inspect_output_bound_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v103_inspect_output_bound_scaffold.py",
)

_V100_TRANSFER_IMAGES = v100._transfer_images  # noqa: SLF001
_V100_RUNTIME_PREPARE_PREFLIGHT = v100._runtime_prepare_preflight  # noqa: SLF001
_V100_HARNESS_INITIALIZE_PREFLIGHT = v100._harness_initialize_preflight  # noqa: SLF001
_V100_INVENTORY = v100._inventory  # noqa: SLF001
_V100_RUNTIME_RECEIPT = v100._runtime_receipt  # noqa: SLF001
_V100_CLEAN_SOCKET_VOLUME = v100._clean_socket_volume  # noqa: SLF001
_V100_VALIDATE_STATIC_BINDINGS = v100._validate_static_bindings  # noqa: SLF001
_V100_MATERIALIZE_TASKS = v100._materialize_tasks  # noqa: SLF001
_V100_SCAFFOLD_CONTRACT = v100._scaffold_contract  # noqa: SLF001
_V100_REQUIRE_CLEAN_MERGED_MAIN = v100._require_clean_merged_main  # noqa: SLF001
_LOAD_V100_INVENTORY_TIMEOUT_SCAFFOLD_MANIFEST = v100.load_v100_inventory_timeout_scaffold_manifest
_V69_MATERIALIZE_TASK = v100._V69_MATERIALIZE_TASK  # noqa: SLF001


def _parser() -> argparse.ArgumentParser:
    parser = v100._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the v100-tested workflow under fresh v103 bindings and inspect bounds."""

    with _v103_configuration():
        return v100.materialize(arguments)


@contextlib.contextmanager
def _v103_configuration() -> Iterator[None]:
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
        "load_v100_inventory_timeout_scaffold_manifest": (
            load_v103_inspect_output_bound_scaffold_manifest
        ),
        "_write_progress": _write_progress,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_inventory_docker_inspect": _inventory_docker_inspect,
        "_v100_materialize_task": _v103_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v100, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v100, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v100, name, value)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v103 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v103_scaffold_progress_v1",
            "v97_manifest_hash": (
                "7bb335f8f6418b6cd4d5e315db67060672b8fc4d3d47b1cc68f3b8a7d5e94cc7"
            ),
            "v97_report_hash": ("6000435cb3f439cb206666dc06c55332e02d8a85cd688eb5e055537274f67f18"),
            "v98_audit_commit": "a766cc9d564f89c96170b1e451852e29e107388e",
            "v98_post_merge_main_run_id": 33782913003,
            "v100_manifest_hash": (
                "617aa02631333d7347ddfb54fde9f34f8554098ec003a229158d65cb2d33dfbe"
            ),
            "v100_report_hash": (
                "9aa3c4716f528429040ff95aa6e12d1da780543c26ad3fab6dce9f2672724b22"
            ),
            "v101_audit_commit": "3546e64c00b80f570334781a228ed521d5a601e8",
            "v101_post_merge_main_run_id": 33789571225,
        }
    )
    if value.get("status") in {
        "completed_pending_independent_v95_audit",
        "completed_pending_independent_v98_audit",
        "completed_pending_independent_v101_audit",
    }:
        value["status"] = "completed_pending_independent_v104_audit"
    v100.v97._V94_WRITE_PROGRESS(root, value)  # noqa: SLF001


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
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V100_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v100.v97.v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v103_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v103 image transfer receipt inventory is not exactly two")
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
        format_id="verigym_deepseek_harness_hwe_v103_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    return _reseal(
        _V100_RUNTIME_PREPARE_PREFLIGHT(manifest, locks=locks, dind_name=dind_name),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v103_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    return _reseal(
        _V100_HARNESS_INITIALIZE_PREFLIGHT(
            manifest,
            controller_receipt_hash=controller_receipt_hash,
            root=root,
        ),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v103_harness_initialize_preflight_v1",
    )


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
) -> dict[str, Any]:
    return _reseal(
        _V100_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v103_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V100_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value["v100_data_volume_reused"] = False
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v103_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    result = _reseal(
        _V100_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v103_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _validate_static_bindings(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    _V100_VALIDATE_STATIC_BINDINGS(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v92_manifest_path,
        v92_report_path=v92_report_path,
    )
    v100_manifest = _LOAD_V100_INVENTORY_TIMEOUT_SCAFFOLD_MANIFEST(V100_MANIFEST)
    v100_report = v100.v97.v94._load_json(V100_REPORT)  # noqa: SLF001
    if (
        v69._hash_file(V100_MANIFEST) != manifest.v100_manifest_sha256  # noqa: SLF001
        or v100_manifest.manifest_hash != manifest.v100_manifest_hash
        or v69._hash_file(V100_RUNNER) != manifest.v100_runner_sha256  # noqa: SLF001
        or v69._hash_file(V100_REPORT) != manifest.v100_report_sha256  # noqa: SLF001
        or v69._hash_file(V100_PROGRESS) != manifest.v100_report_sha256  # noqa: SLF001
        or v100.v97.v94._canonical_hash(v100_report, "report_hash")  # noqa: SLF001
        != manifest.v100_report_hash
        or v69._hash_file(V101_AUDIT) != manifest.v101_audit_sha256  # noqa: SLF001
    ):
        raise ConfigurationError("v103 predecessor evidence binding changed")
    if (
        v100_report.get("identity") != "deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1"
        or v100_report.get("status") != "stopped_without_execution_scaffold"
        or v100_report.get("stop_reason") != "ConfigurationError"
        or v100_report.get("completed_stages") != ["controller_and_workspace_runtime_transferred"]
        or v100_report.get("provider_execution_scaffold_published") is not False
        or v100_report.get("provider_request_started") is not False
        or v100_report.get("provider_calls") != 0
        or v100_report.get("model_process_count") != 0
        or v100_report.get("dind_cleanup_confirmed") is not True
        or v100_report.get("raw_exception_persisted") is not False
        or (V100_ROOT / "execution-scaffold-contract.json").exists()
        or any(
            v100_report.get(key) is not False
            for key in v100.v97.v94._closed_training_flags()  # noqa: SLF001
        )
    ):
        raise ConfigurationError("v103 requires the exact audited v100 pre-provider stop")
    smoke = v100.v97.v94._load_json(  # noqa: SLF001
        V100_ROOT / "qualification/pr-465/smoke-report.json"
    )
    if (
        v69._hash_file(V100_ROOT / "qualification/pr-465/smoke-report.json")  # noqa: SLF001
        != "f31aef682ef74774205da019fefa70327f13af028e00b4a88038432c49b70f0e"
        or smoke.get("base_failed") is not True
        or smoke.get("base_infrastructure_error") is not False
        or smoke.get("reference_passed") is not True
        or smoke.get("model_process_count") != 0
    ):
        raise ConfigurationError("v103 requires the audited v100 PR-465 qualification")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v101_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v103 requires the merged v101 audit")
    if (
        manifest.v100_evidence_root != str(V100_ROOT)
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.v100_failed_inspect_output_bound_bytes != v69._MAX_CONTROL_OUTPUT  # noqa: SLF001
        or manifest.toolchain_inventory_inspect_output_bound_bytes != 1024 * 1024
        or manifest.v100_data_volume_reused is not False
        or manifest.v102_identity_retired is not True
        or manifest.provider_credentials_available is not False
        or manifest.registry_access_allowed is not False
    ):
        raise ConfigurationError("v103 fresh purpose-bound inspect identity changed")


def _inventory_docker_inspect(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    container_id: str,
) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "container", "inspect", container_id],
        check=False,
        capture_output=True,
        timeout=manifest.toolchain_inventory_inspect_timeout_seconds,
    )
    if result.returncode != 0 or result.stderr:
        raise ConfigurationError("v103 container inspection failed")
    if (
        not result.stdout
        or len(result.stdout) > manifest.toolchain_inventory_inspect_output_bound_bytes
    ):
        raise ConfigurationError("v103 container inspection output is out of bounds")
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ConfigurationError("v103 container inspection output is malformed") from exc
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ConfigurationError("v103 container inspection output is malformed")
    return value[0]


def _v103_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v103 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v103"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _materialize_tasks(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
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
    value, locks = _V100_MATERIALIZE_TASKS(
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
        raise ConfigurationError("v103 refuses partial task materialization")
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ConfigurationError("v103 task receipt is malformed")
        receipt.pop("task_receipt_hash", None)
        receipt["toolchain_inventory_inspect_output_bound_bytes"] = (
            manifest.toolchain_inventory_inspect_output_bound_bytes
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v103_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "toolchain_inventory_inspect_output_bound_bytes": (
                manifest.toolchain_inventory_inspect_output_bound_bytes
            ),
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
    **kwargs: Any,
) -> dict[str, Any]:
    value = _V100_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("v100_tasks_materialized_from_completed_local_archives", None)
    base.pop("requires_independent_v101_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v103_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v100_manifest_hash": manifest.v100_manifest_hash,
            "v100_report_hash": manifest.v100_report_hash,
            "v101_audit_commit": manifest.v101_audit_commit,
            "v101_post_merge_main_run_id": manifest.v101_post_merge_main_run_id,
            "v103_tasks_materialized_from_completed_local_archives": True,
            "v100_failed_inspect_output_bound_bytes": (
                manifest.v100_failed_inspect_output_bound_bytes
            ),
            "toolchain_inventory_inspect_output_bound_bytes": (
                manifest.toolchain_inventory_inspect_output_bound_bytes
            ),
            "v100_data_volume_reused": False,
            "v102_identity_retired": True,
            "requires_independent_v104_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV103InspectOutputBoundScaffoldManifest,
) -> str:
    head = _V100_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v101_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v103 requires clean merged origin/main after v101")
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
