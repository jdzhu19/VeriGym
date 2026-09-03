#!/usr/bin/env python3
"""Materialize the fresh five-task scaffold using its real data2 control root."""

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
    materialize_hwe_deepseek_harness_v109_progress_writer_scaffold as v109,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    load_v109_progress_writer_scaffold_manifest,
    load_v112_data2_control_headroom_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.hwe.materialization_preflight import (  # noqa: E402
    MaterializationHeadroomError,
)

IDENTITY = "deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V112_DATA2_CONTROL_HEADROOM_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v112_data2_control_headroom_scaffold_v1.json"
)
V109_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v109_progress_writer_scaffold_v1.json"
)
V109_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v109_progress_writer_scaffold.py"
)
V109_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v109-progress-writer-authorization.md"
)
V109_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v109-progress-writer-scaffold-v1"
)
V109_REPORT = V109_ROOT / "execution-scaffold-report.json"
V109_PROGRESS = V109_ROOT / "execution-scaffold-progress.json"
V109_HEADROOM = V109_ROOT / "headroom-preflight.json"
V110_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v110-v109-result.md"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v112")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-runtime")
_DATA2_ROOT = Path("/data2")
_REQUIRED_MERGED_PATHS = (
    *v109._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v110-v109-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v112_data2_control_headroom_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v112-data2-control-headroom-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v112_data2_control_headroom_scaffold.py",
    "scripts/materialize_hwe_deepseek_harness_v112_data2_control_headroom_scaffold.py",
)
_V109_EXPECTED_FILES = {
    "execution-scaffold-progress.json": (
        "a2a1ee54a69d7542ce1ed078074e22265040e01e0ef7a96402fa40c3c94dd3e2"
    ),
    "execution-scaffold-report.json": (
        "a2a1ee54a69d7542ce1ed078074e22265040e01e0ef7a96402fa40c3c94dd3e2"
    ),
    "headroom-preflight.json": ("dfe8359c637f5eb21e9ebde66ea8d2258ea1743681eb2caa0acc1a76d2988824"),
    "patch-compatibility/pr-465.json": (
        "52f718976b97271e77c44cf12b9d5cfa5451b524b58f2e6c4cf59e8983542edc"
    ),
    "patch-compatibility/pr-1135.json": (
        "535d3f05b861d9bd0d0032a3388ef039bad1652ad046b0f3f830e7e197eee439"
    ),
    "patch-compatibility/pr-1780.json": (
        "e0d9e1d425431a59875b940242f1f59a5f44eaf2b4752c9ab339df5be9b98db1"
    ),
    "patch-compatibility/pr-2017.json": (
        "d5aa618bed2b175995a66568cd4c580766cd542f5f2ca28bfe24bd7bdf531dcb"
    ),
    "patch-compatibility/pr-2711.json": (
        "bcb8397740c6c27f1af1c517e0d0aab432dacd8ef70fa251216840e1f3fd21c8"
    ),
}
_V109_EXPECTED_DIRECTORIES = {
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
_V109_EMPTY_RUNTIME_PATHS = (
    Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v109/data"),
    Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v109/socket"),
    Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v109-control"),
    Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v109-runtime"),
)
_HEADROOM_REQUIREMENTS = {
    "control_root": (4 * 1024**3, 100_000),
    "docker_root": (6 * 8 * 1024**3 * 2, 250_000),
    "scratch_root": (8 * 1024**3, 50_000),
    "output_parent": (2 * 1024**3, 10_000),
}

_V94_WRITE_PROGRESS = v109._V94_WRITE_PROGRESS  # noqa: SLF001
_V109_TRANSFER_IMAGES = v109._transfer_images  # noqa: SLF001
_V109_RUNTIME_PREPARE_PREFLIGHT = v109._runtime_prepare_preflight  # noqa: SLF001
_V109_HARNESS_INITIALIZE_PREFLIGHT = v109._harness_initialize_preflight  # noqa: SLF001
_V109_INVENTORY = v109._inventory  # noqa: SLF001
_V109_RUNTIME_RECEIPT = v109._runtime_receipt  # noqa: SLF001
_V109_CLEAN_SOCKET_VOLUME = v109._clean_socket_volume  # noqa: SLF001
_V109_VALIDATE_STATIC_BINDINGS = v109._validate_static_bindings  # noqa: SLF001
_V109_MATERIALIZE_TASKS = v109._materialize_tasks  # noqa: SLF001
_V109_SCAFFOLD_CONTRACT = v109._scaffold_contract  # noqa: SLF001
_V109_REQUIRE_CLEAN_MERGED_MAIN = v109._require_clean_merged_main  # noqa: SLF001
_LOAD_V109_PROGRESS_WRITER_SCAFFOLD_MANIFEST = load_v109_progress_writer_scaffold_manifest
_V69_MATERIALIZE_TASK = v109._V69_MATERIALIZE_TASK  # noqa: SLF001
_V94_REQUIRE_MATERIALIZATION_HEADROOM = v109.v106.v103.v100.v97.v94.require_materialization_headroom


def _parser() -> argparse.ArgumentParser:
    parser = v109._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the v109-tested workflow under fresh v112 data2 bindings."""

    with _v112_configuration():
        return v109.materialize(arguments)


@contextlib.contextmanager
def _v112_configuration() -> Iterator[None]:
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
        "load_v109_progress_writer_scaffold_manifest": (
            load_v112_data2_control_headroom_scaffold_manifest
        ),
        "_write_progress": _write_progress,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_v109_materialize_task": _v112_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v109, name) for name in replacements}
    v94 = v109.v106.v103.v100.v97.v94
    previous_headroom = v94.require_materialization_headroom
    try:
        for name, value in replacements.items():
            setattr(v109, name, value)
        v94.require_materialization_headroom = _data2_control_headroom
        yield
    finally:
        v94.require_materialization_headroom = previous_headroom
        for name, value in previous.items():
            setattr(v109, name, value)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v112 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v112_scaffold_progress_v1",
            "v109_manifest_hash": (
                "363d2be159244606259325cc62a3421d3caf8b07dca0253f78e5fce56b80385e"
            ),
            "v109_report_hash": (
                "d70eba8db5a28eb24e8582f1bafddeb9bcbf71e5778e7374e305e60791f2f4f9"
            ),
            "v110_audit_commit": "557e11ffbca95175352e5221e2ee9d8c994588bf",
            "v110_post_merge_main_run_id": 33804279053,
            "progress_writer_source": "v97-captured-v94-base-writer",
            "control_headroom_root": str(CONTROL_ROOT),
            "system_root_headroom_required": False,
        }
    )
    if value.get("status") in {
        "completed_pending_independent_v95_audit",
        "completed_pending_independent_v98_audit",
        "completed_pending_independent_v101_audit",
        "completed_pending_independent_v104_audit",
        "completed_pending_independent_v107_audit",
        "completed_pending_independent_v110_audit",
    }:
        value["status"] = "completed_pending_independent_v113_audit"
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


def _require_data2_directory(path: Path, label: str, *, empty: bool = False) -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"v112 {label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        data2 = _DATA2_ROOT.resolve(strict=True)
    except OSError:
        raise ConfigurationError(f"v112 {label} is unavailable") from None
    if not resolved.is_dir() or not resolved.is_relative_to(data2):
        raise ConfigurationError(f"v112 {label} must be a directory under data2")
    if empty and next(resolved.iterdir(), None) is not None:
        raise ConfigurationError(f"v112 {label} must start empty")
    return resolved


def _reseal_headroom(value: Mapping[str, Any]) -> dict[str, Any]:
    observations = value.get("filesystems")
    if not isinstance(observations, list) or len(observations) != 4:
        raise ConfigurationError("v112 headroom receipt has an unexpected filesystem inventory")
    observed_requirements: dict[str, tuple[int, int]] = {}
    for item in observations:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ConfigurationError("v112 headroom receipt has a malformed filesystem row")
        observed_requirements[item["role"]] = (
            item.get("minimum_free_bytes"),
            item.get("minimum_free_inodes"),
        )
    if observed_requirements != _HEADROOM_REQUIREMENTS or value.get("policy") != {
        "absolute_thresholds": True,
        "percentage_thresholds": False,
        "planned_command_image_count": 6,
        "maximum_bytes_per_command_image": 8 * 1024**3,
        "docker_headroom_multiplier": 2,
    }:
        raise ConfigurationError("v112 refuses changed materialization headroom thresholds")
    base = copy.deepcopy(dict(value))
    base.pop("preflight_hash", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v112_data2_control_headroom_v1",
            "identity": IDENTITY,
            "inherited_control_headroom_root": "/",
            "control_headroom_root": str(CONTROL_ROOT),
            "system_root_headroom_required": False,
            "all_campaign_writable_roots_under_data2": True,
            "thresholds_changed": False,
        }
    )
    return {**base, "preflight_hash": content_hash(base)}


def _data2_control_headroom(
    *,
    control_root: Path,
    docker_root: Path,
    scratch_root: Path,
    output_parent: Path,
) -> dict[str, Any]:
    expected_scratch = v109.v106.v103.v100.v97.v94.SCRATCH_ROOT
    if (
        control_root != Path("/")
        or docker_root != DIND_DATA_BACKING
        or scratch_root != expected_scratch
        or output_parent != OUTPUT_ROOT.parent
    ):
        raise ConfigurationError("v112 inherited headroom call arguments changed")
    _require_data2_directory(CONTROL_ROOT, "control headroom root", empty=True)
    _require_data2_directory(DIND_DATA_BACKING, "Docker data backing", empty=True)
    _require_data2_directory(DIND_SOCKET_BACKING, "Docker socket backing", empty=True)
    _require_data2_directory(RUNTIME_TMP, "runtime scratch", empty=True)
    _require_data2_directory(scratch_root, "shared scratch root")
    _require_data2_directory(output_parent, "output parent")
    try:
        value = _V94_REQUIRE_MATERIALIZATION_HEADROOM(
            control_root=CONTROL_ROOT,
            docker_root=docker_root,
            scratch_root=scratch_root,
            output_parent=output_parent,
        )
    except MaterializationHeadroomError as exc:
        raise MaterializationHeadroomError(_reseal_headroom(exc.receipt)) from None
    return _reseal_headroom(value)


def _transfer_images(
    dind_name: str,
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V109_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v109.v106.v103.v100.v97.v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v112_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v112 image transfer receipt inventory is not exactly two")
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
        format_id="verigym_deepseek_harness_hwe_v112_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    return _reseal(
        _V109_RUNTIME_PREPARE_PREFLIGHT(manifest, locks=locks, dind_name=dind_name),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v112_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    *,
    controller_receipt_hash: str,
    root: Path,
) -> dict[str, Any]:
    return _reseal(
        _V109_HARNESS_INITIALIZE_PREFLIGHT(
            manifest,
            controller_receipt_hash=controller_receipt_hash,
            root=root,
        ),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v112_harness_initialize_preflight_v1",
    )


def _inventory(
    dind_name: str,
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
) -> dict[str, Any]:
    return _reseal(
        _V109_INVENTORY(dind_name, manifest),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v112_execution_inventory_v1",
    )


def _runtime_receipt(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    *,
    dind_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    value = _V109_RUNTIME_RECEIPT(manifest, dind_name=dind_name, metadata=metadata)
    value.update(
        {
            "v109_data_volume_reused": False,
            "control_headroom_root": str(CONTROL_ROOT),
            "system_root_headroom_required": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v112_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    *,
    root: Path,
) -> dict[str, Any]:
    result = _reseal(
        _V109_CLEAN_SOCKET_VOLUME(manifest, root=root),
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v112_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _validate_static_bindings(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    _V109_VALIDATE_STATIC_BINDINGS(
        manifest,
        v92_manifest,
        v92_report,
        v92_manifest_path=v92_manifest_path,
        v92_report_path=v92_report_path,
    )
    v109_manifest = _LOAD_V109_PROGRESS_WRITER_SCAFFOLD_MANIFEST(V109_MANIFEST)
    report = v109.v106.v103.v100.v97.v94._load_json(V109_REPORT)  # noqa: SLF001
    headroom = v109.v106.v103.v100.v97.v94._load_json(V109_HEADROOM)  # noqa: SLF001
    entries = list(V109_ROOT.rglob("*"))
    files = {str(path.relative_to(V109_ROOT)): path for path in entries if path.is_file()}
    directories = {str(path.relative_to(V109_ROOT)) for path in entries if path.is_dir()}
    if (
        v69._hash_file(V109_MANIFEST) != manifest.v109_manifest_sha256  # noqa: SLF001
        or v109_manifest.manifest_hash != manifest.v109_manifest_hash
        or v69._hash_file(V109_RUNNER) != manifest.v109_runner_sha256  # noqa: SLF001
        or v69._hash_file(V109_AUTHORIZATION)  # noqa: SLF001
        != manifest.v109_authorization_sha256
        or v69._hash_file(V109_REPORT) != manifest.v109_report_sha256  # noqa: SLF001
        or v69._hash_file(V109_PROGRESS) != manifest.v109_report_sha256  # noqa: SLF001
        or v109.v106.v103.v100.v97.v94._canonical_hash(report, "report_hash")  # noqa: SLF001
        != manifest.v109_report_hash
        or v69._hash_file(V109_HEADROOM) != manifest.v109_headroom_sha256  # noqa: SLF001
        or v109.v106.v103.v100.v97.v94._canonical_hash(  # noqa: SLF001
            headroom, "preflight_hash"
        )
        != manifest.v109_headroom_hash
        or v69._hash_file(V110_AUDIT) != manifest.v110_audit_sha256  # noqa: SLF001
        or set(files) != set(_V109_EXPECTED_FILES)
        or any(v69._hash_file(path) != _V109_EXPECTED_FILES[name] for name, path in files.items())  # noqa: SLF001
        or directories != _V109_EXPECTED_DIRECTORIES
        or len(directories) + 1 != 14
        or any(path.is_symlink() for path in entries)
    ):
        raise ConfigurationError("v112 predecessor evidence binding changed")
    if (
        report.get("identity") != "deepseek-harness-hwe-v109-progress-writer-scaffold-v1"
        or report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "MaterializationHeadroomError"
        or report.get("completed_stages") != []
        or report.get("provider_execution_scaffold_published") is not False
        or report.get("provider_execution_authorized") is not False
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or report.get("dind_cleanup_confirmed") is not True
        or report.get("raw_exception_persisted") is not False
        or any(
            report.get(key) is not False
            for key in v109.v106.v103.v100.v97.v94._closed_training_flags()  # noqa: SLF001
        )
    ):
        raise ConfigurationError("v112 requires the exact audited v109 pre-Docker stop")
    headroom_rows = {
        item.get("role"): item for item in headroom.get("filesystems", []) if isinstance(item, dict)
    }
    control_row = headroom_rows.get("control_root", {})
    if (
        headroom.get("status") != "rejected_insufficient_headroom"
        or set(headroom_rows) != set(_HEADROOM_REQUIREMENTS)
        or control_row.get("minimum_free_bytes") != 4 * 1024**3
        or control_row.get("bytes_satisfied") is not False
        or any(
            row.get("bytes_satisfied") is not True or row.get("inodes_satisfied") is not True
            for role, row in headroom_rows.items()
            if role != "control_root"
        )
    ):
        raise ConfigurationError("v112 requires the exact audited v109 root-headroom rejection")
    for path in _V109_EMPTY_RUNTIME_PATHS:
        if path.is_symlink() or not path.is_dir() or next(path.iterdir(), None) is not None:
            raise ConfigurationError("v112 requires frozen empty v109 runtime paths")
    for name in _V109_EXPECTED_FILES:
        if not name.startswith("patch-compatibility/"):
            continue
        receipt = v109.v106.v103.v100.v97.v94._load_json(V109_ROOT / name)  # noqa: SLF001
        if (
            receipt.get("compatible") is not True
            or receipt.get("docker_accessed") is not False
            or receipt.get("network_accessed") is not False
            or receipt.get("completed_before_archive_or_docker_access") is not True
        ):
            raise ConfigurationError("v112 requires audited v109 patch compatibility receipts")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v110_audit_commit, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v112 requires the merged v110 audit")
    if (
        manifest.v109_evidence_root != str(V109_ROOT)
        or manifest.inherited_control_headroom_root != "/"
        or manifest.control_headroom_root != str(CONTROL_ROOT)
        or manifest.system_root_headroom_required is not False
        or manifest.all_campaign_writable_roots_under_data2 is not True
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.v109_data_volume_reused is not False
        or manifest.v111_identity_retired is not True
        or manifest.final_inventory_command_image_source != "fresh-materialization-locks"
        or manifest.final_inventory_fresh_command_image_count != 5
        or manifest.required_inner_image_count != 12
        or manifest.provider_credentials_available is not False
        or manifest.registry_access_allowed is not False
    ):
        raise ConfigurationError("v112 fresh purpose-bound identity changed")


def _v112_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v112 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v112"
    return _V69_MATERIALIZE_TASK(*args, **kwargs)


def _materialize_tasks(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = _V109_MATERIALIZE_TASKS(manifest, v92_manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected_task_ids = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected_task_ids):
        raise ConfigurationError("v112 task receipt inventory is incomplete")
    for task_id, receipt in zip(expected_task_ids, receipts, strict=True):
        if not isinstance(receipt, dict) or receipt.get("task_id") != task_id:
            raise ConfigurationError("v112 task receipt ordering changed")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "format_id": "verigym_deepseek_harness_hwe_v112_task_materialization_receipt_v1",
                "identity": IDENTITY,
                "progress_writer_source": manifest.progress_writer_source,
                "control_headroom_root": str(CONTROL_ROOT),
                "system_root_headroom_required": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v112_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [receipt["task_receipt_hash"] for receipt in receipts],
            "progress_writer_source": manifest.progress_writer_source,
            "control_headroom_root": str(CONTROL_ROOT),
            "system_root_headroom_required": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v112 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    **kwargs: Any,
) -> dict[str, Any]:
    value = _V109_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("v109_tasks_materialized_from_completed_local_archives", None)
    base.pop("requires_independent_v110_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v112_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v109_manifest_hash": manifest.v109_manifest_hash,
            "v110_audit_commit": manifest.v110_audit_commit,
            "v110_post_merge_main_run_id": manifest.v110_post_merge_main_run_id,
            "v110_audit_completed": True,
            "v112_tasks_materialized_from_completed_local_archives": True,
            "progress_writer_source": manifest.progress_writer_source,
            "inherited_control_headroom_root": "/",
            "control_headroom_root": str(CONTROL_ROOT),
            "system_root_headroom_required": False,
            "all_campaign_writable_roots_under_data2": True,
            "headroom_thresholds_changed": False,
            "v109_data_volume_reused": False,
            "v111_identity_retired": True,
            "requires_independent_v113_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
) -> str:
    head = _V109_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v110_audit_commit, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v112 requires clean merged origin/main after v110")
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
