#!/usr/bin/env python3
"""Materialize the fresh five-task scaffold with a directly bound progress writer."""

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
    materialize_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold as v106,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    load_v109_progress_writer_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v109-progress-writer-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V109_PROGRESS_WRITER_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v109_progress_writer_scaffold_v1.json"
)
V106_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold_v1.json"
)
V106_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold.py"
)
V106_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v106-fresh-inventory-binding-authorization.md"
)
V106_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1"
)
V107_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v107-v106-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v109-progress-writer-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v109")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v109-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v109-runtime")
_REQUIRED_MERGED_PATHS = (
    *v106._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v107-v106-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v109_progress_writer_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v109-progress-writer-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v109_progress_writer_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v109_progress_writer_scaffold.py",
)
_V106_EMPTY_DIRECTORIES = {
    "archive-receipts",
    "command-diagnostics",
    "dind-empty-home",
    "image-locks",
    "image-receipts",
    "patch-compatibility",
    "preflight",
    "qualification",
    "scan-workspaces",
    "security-scans",
    "source-image-locks",
    "sources",
    "transfer-receipts",
}

_V94_WRITE_PROGRESS = v106.v103.v100.v97._V94_WRITE_PROGRESS  # noqa: SLF001
_V106_TRANSFER_IMAGES = v106._transfer_images  # noqa: SLF001
_V106_RUNTIME_PREPARE_PREFLIGHT = v106._runtime_prepare_preflight  # noqa: SLF001
_V106_HARNESS_INITIALIZE_PREFLIGHT = v106._harness_initialize_preflight  # noqa: SLF001
_V106_INVENTORY = v106._inventory  # noqa: SLF001
_V106_RUNTIME_RECEIPT = v106._runtime_receipt  # noqa: SLF001
_V106_CLEAN_SOCKET_VOLUME = v106._clean_socket_volume  # noqa: SLF001
_V106_VALIDATE_STATIC_BINDINGS = v106._validate_static_bindings  # noqa: SLF001
_V106_MATERIALIZE_TASKS = v106._materialize_tasks  # noqa: SLF001
_V106_SCAFFOLD_CONTRACT = v106._scaffold_contract  # noqa: SLF001
_V106_REQUIRE_CLEAN_MERGED_MAIN = v106._require_clean_merged_main  # noqa: SLF001
_LOAD_V106_FRESH_INVENTORY_BINDING_SCAFFOLD_MANIFEST = (
    v106.load_v106_fresh_inventory_binding_scaffold_manifest
)
_V69_MATERIALIZE_TASK = v106._V69_MATERIALIZE_TASK  # noqa: SLF001


def _parser() -> argparse.ArgumentParser:
    parser = v106._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the v106-tested workflow under fresh v109 bindings."""

    with _v109_configuration():
        return v106.materialize(arguments)


@contextlib.contextmanager
def _v109_configuration() -> Iterator[None]:
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
        "load_v106_fresh_inventory_binding_scaffold_manifest": (
            load_v109_progress_writer_scaffold_manifest
        ),
        "_write_progress": _write_progress,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_v106_materialize_task": _v109_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v106, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v106, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v106, name, value)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v109 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v109_scaffold_progress_v1",
            "v103_manifest_hash": (
                "931a3863559c848e53a6015fc023275f5fb4a12927e09fe70b47c38ac66c5fee"
            ),
            "v103_report_hash": (
                "0de771890a66ab9b70016b02892851135767c96d601d9927b3123deeb3a22e7c"
            ),
            "v104_audit_commit": "95b9a11dbb3833fd57fc5b0a43bcd8708bc25865",
            "v104_post_merge_main_run_id": 33795946043,
            "v106_manifest_hash": (
                "1ec4b4b9724519e593dc1b7621f8b1584595abebde1417fbed932a328aa4a98b"
            ),
            "v107_audit_commit": "96111d6073e4fe0944035a1a9a4b480e3f08d811",
            "v107_post_merge_main_run_id": 33800282289,
            "progress_writer_source": "v97-captured-v94-base-writer",
        }
    )
    if value.get("status") in {
        "completed_pending_independent_v95_audit",
        "completed_pending_independent_v98_audit",
        "completed_pending_independent_v101_audit",
        "completed_pending_independent_v104_audit",
        "completed_pending_independent_v107_audit",
    }:
        value["status"] = "completed_pending_independent_v110_audit"
    _V94_WRITE_PROGRESS(root, value)


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
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V106_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v106.v103.v100.v97.v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v109_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v109 image transfer receipt inventory is not exactly two")
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
        format_id="verigym_deepseek_harness_hwe_v109_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    return _reseal(
        _V106_RUNTIME_PREPARE_PREFLIGHT(manifest, locks=locks, dind_name=dind_name),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v109_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    return _reseal(
        _V106_HARNESS_INITIALIZE_PREFLIGHT(
            manifest,
            controller_receipt_hash=controller_receipt_hash,
            root=root,
        ),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v109_harness_initialize_preflight_v1",
    )


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
) -> dict[str, Any]:
    return _reseal(
        _V106_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v109_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V106_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value["v106_data_volume_reused"] = False
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v109_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    result = _reseal(
        _V106_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v109_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _validate_static_bindings(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    _V106_VALIDATE_STATIC_BINDINGS(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v92_manifest_path,
        v92_report_path=v92_report_path,
    )
    v106_manifest = _LOAD_V106_FRESH_INVENTORY_BINDING_SCAFFOLD_MANIFEST(V106_MANIFEST)
    if (
        v69._hash_file(V106_MANIFEST) != manifest.v106_manifest_sha256  # noqa: SLF001
        or v106_manifest.manifest_hash != manifest.v106_manifest_hash
        or v69._hash_file(V106_RUNNER) != manifest.v106_runner_sha256  # noqa: SLF001
        or v69._hash_file(V106_AUTHORIZATION)  # noqa: SLF001
        != manifest.v106_authorization_sha256
        or v69._hash_file(V107_AUDIT) != manifest.v107_audit_sha256  # noqa: SLF001
    ):
        raise ConfigurationError("v109 predecessor evidence binding changed")
    if V106_ROOT.is_symlink() or not V106_ROOT.is_dir():
        raise ConfigurationError("v109 requires the frozen v106 empty evidence root")
    entries = list(V106_ROOT.rglob("*"))
    directories = {str(path.relative_to(V106_ROOT)) for path in entries if path.is_dir()}
    if (
        directories != _V106_EMPTY_DIRECTORIES
        or len(directories) + 1 != manifest.v106_evidence_directory_count
        or any(path.is_file() for path in entries)
        or any(path.is_symlink() for path in entries)
        or manifest.v106_evidence_regular_file_count != 0
        or manifest.v106_evidence_symlink_count != 0
        or any(
            (V106_ROOT / name).exists()
            for name in (
                "execution-scaffold-progress.json",
                "execution-scaffold-report.json",
                "execution-scaffold-contract.json",
                "execution-inventory.json",
                "final-execution-inventory.json",
                "task-materialization-set.json",
            )
        )
    ):
        raise ConfigurationError("v109 requires the exact audited v106 pre-Docker stop")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v107_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v109 requires the merged v107 audit")
    if (
        manifest.v106_evidence_root != str(V106_ROOT)
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.progress_writer_source != "v97-captured-v94-base-writer"
        or manifest.final_inventory_command_image_source != "fresh-materialization-locks"
        or manifest.final_inventory_fresh_command_image_count != 5
        or manifest.required_inner_image_count != 12
        or manifest.v106_data_volume_reused is not False
        or manifest.v108_identity_retired is not True
        or manifest.provider_credentials_available is not False
        or manifest.registry_access_allowed is not False
    ):
        raise ConfigurationError("v109 fresh purpose-bound identity changed")


def _v109_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v109 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v109"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _materialize_tasks(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = _V106_MATERIALIZE_TASKS(manifest, v92_manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected_task_ids):
        raise ConfigurationError("v109 task receipt inventory is incomplete")
    for task_id, receipt in zip(expected_task_ids, receipts, strict=True):
        if not isinstance(receipt, dict) or receipt.get("task_id") != task_id:
            raise ConfigurationError("v109 task receipt ordering changed")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "format_id": "verigym_deepseek_harness_hwe_v109_task_materialization_receipt_v1",
                "identity": IDENTITY,
                "progress_writer_source": manifest.progress_writer_source,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v109_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [receipt["task_receipt_hash"] for receipt in receipts],
            "progress_writer_source": manifest.progress_writer_source,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v109 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    **kwargs: Any,
) -> dict[str, Any]:
    value = _V106_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("v106_tasks_materialized_from_completed_local_archives", None)
    base.pop("requires_independent_v107_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v109_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v106_manifest_hash": manifest.v106_manifest_hash,
            "v107_audit_commit": manifest.v107_audit_commit,
            "v107_post_merge_main_run_id": manifest.v107_post_merge_main_run_id,
            "v107_audit_completed": True,
            "v109_tasks_materialized_from_completed_local_archives": True,
            "progress_writer_source": manifest.progress_writer_source,
            "v106_data_volume_reused": False,
            "v108_identity_retired": True,
            "requires_independent_v110_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
) -> str:
    head = _V106_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v107_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v109 requires clean merged origin/main after v107")
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
