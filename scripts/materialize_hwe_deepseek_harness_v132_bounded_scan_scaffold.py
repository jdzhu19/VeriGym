#!/usr/bin/env python3
"""Materialize the five-task scaffold with the audited bounded image scanner."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import re
import stat
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
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

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v127_readiness_gated_scaffold as v127,
)
from scripts.scan_and_lock_cva6_hwe_command_image import (  # noqa: E402
    CommandImageScanRuntimePolicy,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    DeepSeekHarnessV132BoundedScanScaffoldManifest,
    load_v127_readiness_gated_scaffold_manifest,
    load_v130_bounded_command_scan_probe_manifest,
    load_v132_bounded_scan_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

v118 = v127.v118
v94 = v127.v94
v69 = v127.v69
dind = v127.dind

IDENTITY = "deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V132_BOUNDED_SCAN_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v132_bounded_scan_scaffold_v1.json"
)
V127_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v127_readiness_gated_scaffold_v1.json"
)
V127_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v127_readiness_gated_scaffold.py"
)
V127_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v127-readiness-gated-scaffold-authorization.md"
)
V128_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v128-v127-result.md"
V130_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v130_bounded_command_scan_create_probe_v1.json"
)
V130_RUNNER = _REPOSITORY / (
    "scripts/run_hwe_deepseek_harness_v130_bounded_command_scan_create_probe.py"
)
V130_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v130-bounded-command-scan-create-probe-authorization.md"
)
V131_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v131-v130-result.md"
V130_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v132")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v132-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v132-runtime")

_REQUIRED_MERGED_PATHS = (
    *v127._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v128-v127-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v130_bounded_command_scan_create_probe_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v130-bounded-command-scan-create-probe-authorization.md",
    "scripts/run_hwe_deepseek_harness_v130_bounded_command_scan_create_probe.py",
    "integrations/verigym-deepseek-harness/tests/test_v130_bounded_command_scan_create_probe.py",
    "docs/audits/2026-09-04_deepseek-harness-v131-v130-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v132_bounded_scan_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v132-bounded-scan-scaffold-authorization.md",
    "scripts/materialize_hwe_deepseek_harness_v132_bounded_scan_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v132_bounded_scan_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)
_V130_FILES = {
    "archive": V130_ROOT / "archive-receipts/pr-465.json",
    "build": V130_ROOT / "build-command-diagnostic.json",
    "cleanup": V130_ROOT / "cleanup-receipt.json",
    "progress": V130_ROOT / "command-scan-probe-progress.json",
    "report": V130_ROOT / "command-scan-probe-report.json",
    "runtime": V130_ROOT / "dind-runtime-receipt.json",
    "host_image": V130_ROOT / "host-image-identity.json",
    "command_lock": V130_ROOT / "image-locks/pr-465.json",
    "image_receipt": V130_ROOT / "image-receipts/pr-465.json",
    "inventory": V130_ROOT / "inner-inventory.json",
    "late_cleanup": V130_ROOT / "late-cleanup-receipt.json",
    "predecessor": V130_ROOT / "predecessor-preflight.json",
    "security_scan": V130_ROOT / "security-scans/pr-465.json",
    "task_import": V130_ROOT / "task-image-import-receipt.json",
    "volume_setup": V130_ROOT / "volume-setup-receipt.json",
}
_V130_FILE_BINDINGS = {
    "archive": (
        "21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516",
        "receipt_hash",
        "fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63",
    ),
    "build": (
        "514082eab57bc4f8e9f83febd286b4baf8cd821c6c79d2dad4836c42acecf238",
        "diagnostic_hash",
        "c56e24a54e6b691ecc3a7ddaa978661797a79e8bac1af33a671b8a5a10c34f20",
    ),
    "cleanup": (
        "f7e1696663483a42bd9208a37e66b34b36d8126f44ae92267e3b4c375b12ccd5",
        "receipt_hash",
        "30fdd276b1f0a79b856b9d50ec31ecce3029b6b68a09cbd865099853d73047e5",
    ),
    "progress": (
        "1dc9ab7ddab4cbd24508e88912e7d84314230eca1c7214895baa7bef7e332afe",
        "report_hash",
        "3855fe26ffdf94da985d72ad62fcc260c9a2fb56b438f4026be5da20ed69dd31",
    ),
    "report": (
        "1dc9ab7ddab4cbd24508e88912e7d84314230eca1c7214895baa7bef7e332afe",
        "report_hash",
        "3855fe26ffdf94da985d72ad62fcc260c9a2fb56b438f4026be5da20ed69dd31",
    ),
    "runtime": (
        "70fa898323beec7b5ca5b5a8bd71b4f2d4f569b645d4f3c902a0c86f1266f477",
        "receipt_hash",
        "46adee492f5dbee7d9e4c899b2bb7d95998aac4d26c7c3c62f1fa8bd2c7f705a",
    ),
    "host_image": (
        "6cce8107e09161813c9bc29a99628faf4392d5c29752e903e627f71e92049d18",
        "receipt_hash",
        "34bc43a2588600566158421d7880e8b10a8137bc2598a10e662f670340524d93",
    ),
    "command_lock": (
        "19415af2bf4ae6490bb322efb63140ea0da7c049dc9ec11b6b973aa9214d6f03",
        "lock_hash",
        "8fff0f84401d52a137e3bca04c2458f66a8341af8a45246e4a8c4408205600a5",
    ),
    "image_receipt": (
        "621a9466d9f003f9c95300a42228c7a6ab2f2d99a278493fec7e932fec8e30ea",
        None,
        None,
    ),
    "inventory": (
        "f182f6bab177b22f7b0d517ce34c3fe96dd03cea110c8bfdad1ed4047c744c62",
        "inventory_hash",
        "6d967688ad43cefcb123f3f45ff7b449f452e068b317f73462e99c3d2a62e60c",
    ),
    "late_cleanup": (
        "5499cf67d855c04352fbea0d86840dabed8f7f1097119cfbd78b9bcf753fe571",
        "receipt_hash",
        "000f95a051fb25230403a6b522c0ac5a2675cad24f67d6c29af38951c248d598",
    ),
    "predecessor": (
        "f048c4ccb2aaf0fccbdab773ff97015b5194b53e3003de322afb843ecfa6cbe4",
        "receipt_hash",
        "08186411492e3815afb17190f50ed0ff10636e441889a8213be3e128fca4a8cc",
    ),
    "security_scan": (
        "c850fc774c18ac18a7b4c27b2536f7e5a262f3b379d967adc03edb860c9af0fb",
        "security_scan_id",
        "7e68ef3987f081e8e28af0b5d55f7e1aaeb6aa0336cff4547b62f8304e58d517",
    ),
    "task_import": (
        "9d9e252ff6f135f311cfb1339bd2602c3124d5933d6fe436ae49097d197dc2e6",
        "receipt_hash",
        "f679d6abc45c162072ca37b3de893f5ef547252a376e91e7c2d1aa879d651d56",
    ),
    "volume_setup": (
        "96a73146fe2e361455c16fc089524d8d2a5f37ff5fa19226385a0ad50efdbbb5",
        "receipt_hash",
        "f28e3afd7024acb3eb98652d8b12b0e9097eeb737267c8a781df5c25f22ddfbb",
    ),
}
_TASK_PR_NUMBERS = frozenset({465, 1135, 1780, 2017, 2711})
_PR_STEM = re.compile(r"^pr-(465|1135|1780|2017|2711)$")

_V127_CONFIGURATION_NAMES = (
    "IDENTITY",
    "OPT_IN_ENV",
    "MANIFEST",
    "OUTPUT_ROOT",
    "DIND_PARENT",
    "DIND_DATA_BACKING",
    "DIND_SOCKET_BACKING",
    "CONTROL_ROOT",
    "RUNTIME_TMP",
    "_REQUIRED_MERGED_PATHS",
    "_load_composed_manifest",
    "_write_progress",
    "_data2_control_headroom",
    "_transfer_images",
    "_runtime_prepare_preflight",
    "_harness_initialize_preflight",
    "_inventory",
    "_runtime_receipt",
    "_clean_socket_volume",
    "_validate_static_bindings",
    "_v127_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V127_PREDECESSOR_BINDINGS = {name: getattr(v127, name) for name in _V127_CONFIGURATION_NAMES}
_V127_LOAD_COMPOSED_MANIFEST = v127._load_composed_manifest  # noqa: SLF001
_V127_WRITE_PROGRESS = v127._V118_WRITE_PROGRESS  # noqa: SLF001
_V127_DATA2_CONTROL_HEADROOM = v127._data2_control_headroom  # noqa: SLF001
_V127_TRANSFER_IMAGES = v127._transfer_images  # noqa: SLF001
_V127_RUNTIME_PREPARE_PREFLIGHT = v127._runtime_prepare_preflight  # noqa: SLF001
_V127_HARNESS_INITIALIZE_PREFLIGHT = v127._harness_initialize_preflight  # noqa: SLF001
_V127_INVENTORY = v127._inventory  # noqa: SLF001
_V127_RUNTIME_RECEIPT = v127._runtime_receipt  # noqa: SLF001
_V127_CLEAN_SOCKET_VOLUME = v127._clean_socket_volume  # noqa: SLF001
_V127_VALIDATE_STATIC_BINDINGS = v127._validate_static_bindings  # noqa: SLF001
_V127_BASE_MATERIALIZE_TASK = v127._V69_MATERIALIZE_TASK  # noqa: SLF001
_V127_MATERIALIZE_TASKS = v127._materialize_tasks  # noqa: SLF001
_V127_SCAFFOLD_CONTRACT = v127._scaffold_contract  # noqa: SLF001
_V127_REQUIRE_CLEAN_MERGED_MAIN = v127._require_clean_merged_main  # noqa: SLF001
_V69_SCAN_AND_LOCK = v69.scan_and_lock


def _parser() -> argparse.ArgumentParser:
    parser = v127._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the five-task workflow with a bounded scanner and zero provider access."""

    with _v132_configuration():
        return v127.materialize(arguments)


@contextlib.contextmanager
def _v132_configuration() -> Iterator[None]:
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
        "_load_composed_manifest": _load_composed_manifest,
        "_write_progress": _write_progress,
        "_data2_control_headroom": _data2_control_headroom,
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_v127_materialize_task": _v132_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v127, name) for name in replacements}
    previous_scan = v69.scan_and_lock
    try:
        for name, value in replacements.items():
            setattr(v127, name, value)
        v69.scan_and_lock = _bounded_scan_and_lock
        yield
    finally:
        v69.scan_and_lock = previous_scan
        for name, value in previous.items():
            setattr(v127, name, value)


@contextlib.contextmanager
def _v127_predecessor_configuration() -> Iterator[None]:
    current = {name: getattr(v127, name) for name in _V127_PREDECESSOR_BINDINGS}
    try:
        for name, value in _V127_PREDECESSOR_BINDINGS.items():
            setattr(v127, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v127, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v132_bounded_scan_scaffold_manifest(path)
    with _v127_predecessor_configuration():
        predecessor = _V127_LOAD_COMPOSED_MANIFEST(V127_MANIFEST)
    values = vars(predecessor).copy()
    values.update(purpose.model_dump(mode="python"))
    values.update(
        {
            "schedule": predecessor.schedule,
            "dind_data_backing": purpose.dind_data_backing,
            "dind_socket_backing": purpose.dind_socket_backing,
            "control_headroom_root": purpose.control_headroom_root,
            "runtime_scratch_root": purpose.runtime_scratch_root,
            "nested_docker_host": purpose.nested_docker_host,
            "provider_successor_identity": purpose.provider_successor_identity,
            "manifest_hash": purpose.manifest_hash,
        }
    )
    return SimpleNamespace(**values)


def _write_progress(root: Path, value: Mapping[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ConfigurationError("v132 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v132_scaffold_progress_v1",
            "identity": IDENTITY,
            "v127_manifest_hash": (
                "cfa04d557d68e3d03efdfc15fdd579eb439b38e31876f186ab7270ed90e5bfcb"
            ),
            "v128_audit_merge": "dafe5a4fd3a5b64690a9b352ffc93556abba7425",
            "v130_manifest_hash": (
                "c25bd9762befe8a282d9b73be54c4349398f6777dc3a5e5875d8117a09226df2"
            ),
            "v130_security_scan_id": (
                "7e68ef3987f081e8e28af0b5d55f7e1aaeb6aa0336cff4547b62f8304e58d517"
            ),
            "v130_late_cleanup_hash": (
                "000f95a051fb25230403a6b522c0ac5a2675cad24f67d6c29af38951c248d598"
            ),
            "v131_audit_merge": "5c0022521ffd513c726a4d0f8d0a6f02e94eaecf",
            "scanner_policy_id": "deepseek-harness-v132-bounded-command-scan-v1",
            "scanner_create_timeout_seconds": 300,
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    if value.get("status") in v127._SUCCESS_STATUS_NAMES:  # noqa: SLF001
        value["status"] = "completed_pending_independent_v133_audit"
    _V127_WRITE_PROGRESS(root, value)


def _reseal(value: Mapping[str, Any], *, hash_field: str, format_id: str) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _data2_control_headroom(**kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V127_DATA2_CONTROL_HEADROOM(**kwargs),
        hash_field="preflight_hash",
        format_id="verigym_deepseek_harness_hwe_v132_data2_control_headroom_v1",
    )


def _transfer_images(
    dind_name: str,
    manifest: Any,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V127_TRANSFER_IMAGES(dind_name, manifest, host_images=host_images, root=root)
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v132_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v132 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
            "v130_scan_qualified": True,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v132_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V127_RUNTIME_PREPARE_PREFLIGHT(*args, **kwargs)
    value.update({"v130_scan_qualified": True})
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v132_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V127_HARNESS_INITIALIZE_PREFLIGHT(*args, **kwargs)
    value.update({"v131_audit_merge": "5c0022521ffd513c726a4d0f8d0a6f02e94eaecf"})
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v132_harness_initialize_preflight_v1",
    )


def _inventory(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V127_INVENTORY(*args, **kwargs),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v132_execution_inventory_v1",
    )


def _runtime_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V127_RUNTIME_RECEIPT(*args, **kwargs)
    value.update(
        {
            "scanner_policy_id": "deepseek-harness-v132-bounded-command-scan-v1",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v132_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    value = _V127_CLEAN_SOCKET_VOLUME(manifest, root=root)
    value.update(
        {
            "failed_data_volume_policy": "freeze-exact-owned-volume",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v132_socket_cleanup_receipt_v1",
    )
    atomic_dump_json(root / "dind-cleanup-receipt.json", result)
    return result


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = copy.deepcopy(dict(value))
    observed = base.pop(field, None)
    if not isinstance(observed, str) or content_hash(base) != observed:
        raise ConfigurationError("v132 predecessor canonical hash changed")
    return observed


def _load_v130_evidence(
    purpose: DeepSeekHarnessV132BoundedScanScaffoldManifest,
) -> dict[str, dict[str, Any]]:
    if V130_ROOT.is_symlink() or not V130_ROOT.is_dir():
        raise ConfigurationError("v132 audited v130 evidence root is unsafe")
    entries = list(V130_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    if (
        directories != purpose.v130_evidence_directory_count
        or files != purpose.v130_evidence_regular_file_count
        or symlinks != purpose.v130_evidence_symlink_count
        or stat.S_IMODE(V130_ROOT.stat().st_mode) != 0o700
    ):
        raise ConfigurationError("v132 audited v130 evidence inventory changed")
    values: dict[str, dict[str, Any]] = {}
    for name, path in _V130_FILES.items():
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ConfigurationError("v132 audited v130 evidence permissions changed")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError("v132 audited v130 evidence is invalid") from exc
        if not isinstance(value, dict):
            raise ConfigurationError("v132 audited v130 evidence is invalid")
        expected_sha, hash_field, expected_hash = _V130_FILE_BINDINGS[name]
        if _hash_file(path) != expected_sha:
            raise ConfigurationError("v132 audited v130 evidence file changed")
        if hash_field is not None and (_canonical_hash(value, hash_field) != expected_hash):
            raise ConfigurationError("v132 audited v130 evidence hash changed")
        values[name] = value
    return values


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    purpose = load_v132_bounded_scan_scaffold_manifest(MANIFEST)
    predecessor = load_v127_readiness_gated_scaffold_manifest(V127_MANIFEST)
    with _v127_predecessor_configuration():
        predecessor_view = _V127_LOAD_COMPOSED_MANIFEST(V127_MANIFEST)
        _V127_VALIDATE_STATIC_BINDINGS(
            predecessor_view,
            v92_manifest,
            v92_report,
            v92_manifest_path=v92_manifest_path,
            v92_report_path=v92_report_path,
        )
    probe_manifest = load_v130_bounded_command_scan_probe_manifest(V130_MANIFEST)
    values = _load_v130_evidence(purpose)
    report = values["report"]
    scan = values["security_scan"]
    diagnostic = scan.get("diagnostic")
    command_lock = values["command_lock"]
    cleanup = values["cleanup"]
    late_cleanup = values["late_cleanup"]
    if (
        _hash_file(V127_MANIFEST) != purpose.v127_manifest_sha256
        or predecessor.manifest_hash != purpose.v127_manifest_hash
        or _hash_file(V127_RUNNER) != purpose.v127_runner_sha256
        or _hash_file(V127_AUTHORIZATION) != purpose.v127_authorization_sha256
        or _hash_file(V128_AUDIT) != purpose.v128_audit_sha256
        or _hash_file(V130_MANIFEST) != purpose.v130_manifest_sha256
        or probe_manifest.manifest_hash != purpose.v130_manifest_hash
        or _hash_file(V130_RUNNER) != purpose.v130_runner_sha256
        or _hash_file(V130_AUTHORIZATION) != purpose.v130_authorization_sha256
        or _hash_file(V131_AUDIT) != purpose.v131_audit_sha256
        or manifest.schedule != v92_manifest.schedule
        or [item.task_id for item in manifest.schedule] != purpose.schedule_task_ids
        or manifest.seed != purpose.seed
        or manifest.sample_index != purpose.sample_index
        or manifest.manifest_hash != purpose.manifest_hash
    ):
        raise ConfigurationError("v132 predecessor or immutable schedule binding changed")
    checks = scan.get("checks")
    runtime_policy = diagnostic.get("runtime_policy") if isinstance(diagnostic, dict) else None
    if (
        report != values["progress"]
        or report.get("identity")
        != "deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1"
        or report.get("source_commit") != purpose.v130_source_commit
        or report.get("post_merge_main_run_id") != purpose.v130_post_merge_main_run_id
        or report.get("manifest_hash") != purpose.v130_manifest_hash
        or report.get("status") != "stopped_cleanup_unconfirmed"
        or report.get("stop_reason") != "cleanup_unconfirmed"
        or report.get("diagnostic_complete") is not True
        or report.get("command_image_scan_passed") is not True
        or report.get("cleanup_confirmed") is not False
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or report.get("requires_independent_v131_audit") is not True
        or any(report.get(name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
        or not isinstance(checks, dict)
        or len(checks) != 29
        or not all(value is True for value in checks.values())
        or scan.get("scan_passed") is not True
        or scan.get("security_scan_id") != purpose.v130_security_scan_id
        or not isinstance(diagnostic, dict)
        or diagnostic.get("status") != "passed"
        or diagnostic.get("diagnostic_hash") != purpose.v130_scan_diagnostic_hash
        or diagnostic.get("create_timed_out") is not False
        or diagnostic.get("create_exit_code") != 0
        or diagnostic.get("container_exit_code") != 0
        or diagnostic.get("cleanup_exit_code") != 0
        or diagnostic.get("temporary_container_removed") is not True
        or diagnostic.get("temporary_workspace_removed") is not True
        or diagnostic.get("raw_output_persisted") is not False
        or diagnostic.get("nonempty_output_hashed") is not False
        or not isinstance(runtime_policy, dict)
        or runtime_policy.get("create_timeout_seconds") != 300
        or runtime_policy.get("overall_timeout_seconds") != 720
        or command_lock.get("lock_hash") != purpose.v130_command_lock_hash
        or command_lock.get("security_scan_passed") is not True
        or cleanup.get("status") != "cleanup_unconfirmed"
        or late_cleanup.get("status") != "passed"
        or late_cleanup.get("receipt_hash") != purpose.v130_late_cleanup_hash
        or late_cleanup.get("original_report_hash") != purpose.v130_report_hash
        or late_cleanup.get("cleanup_helper_exit_code") != 0
        or late_cleanup.get("data_volume_removed") is not True
        or late_cleanup.get("socket_volume_removed") is not True
        or late_cleanup.get("predecessor_volumes_inspected") is not False
        or late_cleanup.get("predecessor_volumes_mutated") is not False
    ):
        raise ConfigurationError("v132 requires the exact audited v130 terminal state")
    if (
        purpose.dind_data_backing != str(DIND_DATA_BACKING)
        or purpose.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or purpose.control_headroom_root != str(CONTROL_ROOT)
        or purpose.runtime_scratch_root != str(RUNTIME_TMP)
        or purpose.output_root != str(OUTPUT_ROOT)
        or purpose.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.dind_owner != IDENTITY
        or purpose.scanner_policy_source != "exact-audited-v130-policy"
        or purpose.scanner_create_timeout_seconds != 300
        or purpose.scanner_inspect_timeout_seconds != 60
        or purpose.scanner_start_timeout_seconds != 180
        or purpose.scanner_remove_timeout_seconds != 120
        or purpose.scanner_overall_timeout_seconds != 720
        or purpose.scanner_all_five_tasks_required is not True
        or purpose.scanner_deterministic_owner_cleanup_required is not True
        or purpose.scanner_nonempty_output_hashing_allowed is not False
        or purpose.predecessor_volume_inspection_allowed is not False
        or purpose.predecessor_volume_mutation_allowed is not False
        or purpose.failed_data_volume_policy != "freeze-exact-owned-volume"
        or purpose.provider_successor_identity != "deepseek-harness-hwe-v134-official-matrix-v1"
        or purpose.provider_successor_reopen_budget != 1
        or purpose.registry_access_allowed is not False
        or purpose.partial_archive_allowed is not False
        or purpose.provider_credentials_available is not False
        or purpose.requires_independent_v133_audit is not True
        or purpose.v131_post_merge_main_all_eight_classes_passed is not True
        or any(getattr(purpose, name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v132 purpose-bound scanner or isolation policy changed")
    for commit in (purpose.v128_audit_merge, purpose.v131_audit_merge):
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=_REPOSITORY,
            check=False,
            capture_output=True,
            text=True,
        )
        if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
            raise ConfigurationError("v132 requires both independent audits merged")


def _bounded_scan_and_lock(**kwargs: Any) -> Any:
    if "runtime_policy" in kwargs:
        raise ConfigurationError("v132 refuses an externally supplied scanner policy")
    lock_path = kwargs.get("identity_lock_path")
    if not isinstance(lock_path, Path) or _PR_STEM.fullmatch(lock_path.stem) is None:
        raise ConfigurationError("v132 scanner task identity is invalid")
    pr_number = int(lock_path.stem.removeprefix("pr-"))
    if pr_number not in _TASK_PR_NUMBERS:
        raise ConfigurationError("v132 scanner task is outside the frozen schedule")
    policy = CommandImageScanRuntimePolicy(
        policy_id="deepseek-harness-v132-bounded-command-scan-v1",
        create_timeout_seconds=300,
        inspect_timeout_seconds=60,
        start_timeout_seconds=180,
        remove_timeout_seconds=120,
        overall_timeout_seconds=720,
        container_name=f"verigym-hwe-v132-command-scan-pr-{pr_number}",
        owner_label=IDENTITY,
    )
    scan, lock = _V69_SCAN_AND_LOCK(**kwargs, runtime_policy=policy)
    diagnostic = scan.get("diagnostic")
    if (
        scan.get("scan_passed") is not True
        or not isinstance(diagnostic, dict)
        or diagnostic.get("status") != "passed"
        or diagnostic.get("runtime_policy") != policy.as_dict()
        or diagnostic.get("temporary_container_removed") is not True
        or diagnostic.get("temporary_workspace_removed") is not True
        or diagnostic.get("nonempty_output_hashed") is not False
        or lock.security_scan_passed is not True
    ):
        raise ConfigurationError("v132 bounded command-image scan did not pass")
    return scan, lock


def _v132_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97":
        raise ConfigurationError("v132 refuses an unexpected command-image tag version")
    kwargs["command_tag_version"] = "v132"
    value = _V127_BASE_MATERIALIZE_TASK(*args, **kwargs)
    base = copy.deepcopy(value)
    base.pop("task_receipt_hash", None)
    base.update(
        {
            "scanner_policy_id": "deepseek-harness-v132-bounded-command-scan-v1",
            "scanner_create_timeout_seconds": 300,
            "scanner_overall_timeout_seconds": 720,
            "v130_scan_qualified": True,
        }
    )
    return {**base, "task_receipt_hash": content_hash(base)}


def _materialize_tasks(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = _V127_MATERIALIZE_TASKS(manifest, v92_manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected):
        raise ConfigurationError("v132 refuses partial task materialization")
    for task_id, receipt in zip(expected, receipts, strict=True):
        if (
            not isinstance(receipt, dict)
            or receipt.get("task_id") != task_id
            or receipt.get("scanner_policy_id") != "deepseek-harness-v132-bounded-command-scan-v1"
            or receipt.get("scanner_create_timeout_seconds") != 300
            or receipt.get("scanner_overall_timeout_seconds") != 720
        ):
            raise ConfigurationError("v132 task scanner receipt is incomplete")
        receipt.pop("task_receipt_hash", None)
        receipt.update(
            {
                "format_id": "verigym_deepseek_harness_hwe_v132_task_materialization_receipt_v1",
                "identity": IDENTITY,
                "requires_independent_v133_audit": True,
                "predecessor_volumes_inspected": False,
                "predecessor_volumes_mutated": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v132_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "scanner_policy_id": "deepseek-harness-v132-bounded-command-scan-v1",
            "scanner_all_five_tasks_required": True,
            "v130_scan_qualified": True,
            "requires_independent_v133_audit": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v132 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V127_SCAFFOLD_CONTRACT(manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    for key in ("requires_independent_v128_audit",):
        base.pop(key, None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v132_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v127_manifest_hash": manifest.v127_manifest_hash,
            "v128_audit_merge": manifest.v128_audit_merge,
            "v130_manifest_hash": manifest.v130_manifest_hash,
            "v130_security_scan_id": manifest.v130_security_scan_id,
            "v130_late_cleanup_hash": manifest.v130_late_cleanup_hash,
            "v131_audit_merge": manifest.v131_audit_merge,
            "v131_post_merge_main_run_id": manifest.v131_post_merge_main_run_id,
            "scanner_policy_id": manifest.scanner_policy_id,
            "scanner_create_timeout_seconds": manifest.scanner_create_timeout_seconds,
            "scanner_inspect_timeout_seconds": manifest.scanner_inspect_timeout_seconds,
            "scanner_start_timeout_seconds": manifest.scanner_start_timeout_seconds,
            "scanner_remove_timeout_seconds": manifest.scanner_remove_timeout_seconds,
            "scanner_overall_timeout_seconds": manifest.scanner_overall_timeout_seconds,
            "scanner_all_five_tasks_passed": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "requires_independent_v133_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = _V127_REQUIRE_CLEAN_MERGED_MAIN(manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v131_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v132 requires clean merged origin/main after v131")
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
