#!/usr/bin/env python3
"""Materialize a fresh five-task scaffold with explicit observable image imports."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
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
    materialize_hwe_deepseek_harness_v132_bounded_scan_scaffold as v132,
)
from scripts.scan_and_lock_cva6_hwe_command_image import (  # noqa: E402
    CommandImageScanRuntimePolicy,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV92OfficialMatrixManifest,
    HweOfflineTaskLock,
    load_v132_bounded_scan_scaffold_manifest,
    load_v136_command_runtime_diagnostic_manifest,
    load_v138_fresh_explicit_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

v127 = v132.v127
v94 = v132.v94
v69 = v132.v69

IDENTITY = "deepseek-harness-hwe-v138-fresh-explicit-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V138_FRESH_EXPLICIT_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v138_fresh_explicit_scaffold_v1.json"
)
V132_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v132_bounded_scan_scaffold_v1.json"
)
V132_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v132_bounded_scan_scaffold.py"
)
V133_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v133-v132-result.md"
V136_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v136_command_runtime_diagnostic_v1.json"
)
V136_RUNNER = _REPOSITORY / ("scripts/run_hwe_deepseek_harness_v136_command_runtime_diagnostic.py")
V136_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v136-command-runtime-diagnostic-authorization.md"
)
V137_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v137-v136-result.md"
V132_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"
)
V136_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v136-command-runtime-diagnostic-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v138-fresh-explicit-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v138")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v138-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v138-runtime")
_MAX_IMPORT_OUTPUT = 1024 * 1024
_TASK_PR_NUMBERS = frozenset({465, 1135, 1780, 2017, 2711})

_REQUIRED_MERGED_PATHS = (
    *v132._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v133-v132-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v136_command_runtime_diagnostic_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v136-command-runtime-diagnostic-authorization.md",
    "scripts/run_hwe_deepseek_harness_v136_command_runtime_diagnostic.py",
    "integrations/verigym-deepseek-harness/tests/test_v136_command_runtime_diagnostic.py",
    "docs/audits/2026-09-04_deepseek-harness-v137-v136-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v138_fresh_explicit_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v138-fresh-explicit-scaffold-authorization.md",
    "scripts/materialize_hwe_deepseek_harness_v138_fresh_explicit_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v138_fresh_explicit_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)

_V132_NAMES = (
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
    "_transfer_images",
    "_runtime_prepare_preflight",
    "_harness_initialize_preflight",
    "_inventory",
    "_runtime_receipt",
    "_clean_socket_volume",
    "_validate_static_bindings",
    "_bounded_scan_and_lock",
    "_v132_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V132_BASELINE = {name: getattr(v132, name) for name in _V132_NAMES}


def _parser() -> argparse.ArgumentParser:
    parser = v132._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the fresh five-task provider-free workflow."""

    with _v138_configuration():
        return v132.materialize(arguments)


@contextlib.contextmanager
def _v138_configuration() -> Iterator[None]:
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
        "_transfer_images": _transfer_images,
        "_runtime_prepare_preflight": _runtime_prepare_preflight,
        "_harness_initialize_preflight": _harness_initialize_preflight,
        "_inventory": _inventory,
        "_runtime_receipt": _runtime_receipt,
        "_clean_socket_volume": _clean_socket_volume,
        "_validate_static_bindings": _validate_static_bindings,
        "_bounded_scan_and_lock": _bounded_scan_and_lock,
        "_v132_materialize_task": _v138_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v132, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v132, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v132, name, value)


@contextlib.contextmanager
def _v132_baseline() -> Iterator[None]:
    current = {name: getattr(v132, name) for name in _V132_BASELINE}
    try:
        for name, value in _V132_BASELINE.items():
            setattr(v132, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v132, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v138_fresh_explicit_scaffold_manifest(path)
    with _v132_baseline():
        predecessor = _V132_BASELINE["_load_composed_manifest"](V132_MANIFEST)
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
        raise ConfigurationError("v138 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v138_scaffold_progress_v1",
            "identity": IDENTITY,
            "v132_manifest_hash": (
                "4cb189e20714729dd61af77b7c860a320eefa1027fa3597ae1dc45a799ae7317"
            ),
            "v136_report_hash": (
                "e358b0e2023e81fb7f56ed5b4df0116a3fdf42ac8b0573df7e7b6d455ecad673"
            ),
            "v137_audit_merge": "98c083b7dfc6cb378d0ee7239148370308f7c06f",
            "archive_import_policy": "explicit-endpoint-stage-diagnostic-v1",
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
        }
    )
    if value.get("status") in v127._SUCCESS_STATUS_NAMES:  # noqa: SLF001
        value["status"] = "completed_pending_independent_v139_audit"
    v132._V127_WRITE_PROGRESS(root, value)  # noqa: SLF001


def _reseal(value: Mapping[str, Any], *, hash_field: str, format_id: str) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _transfer_images(
    dind_name: str,
    manifest: Any,
    *,
    host_images: list[Mapping[str, str]],
    root: Path,
) -> dict[str, Any]:
    value = _V132_BASELINE["_transfer_images"](
        dind_name, manifest, host_images=host_images, root=root
    )
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v138_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v138 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
            "v132_scaffold_qualified": True,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v138_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V132_BASELINE["_runtime_prepare_preflight"](*args, **kwargs)
    value.update(
        {
            "archive_import_explicit_endpoint": True,
            "docker_cli_explicit_binding": True,
            "v132_volume_inspected": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v138_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V132_BASELINE["_harness_initialize_preflight"](*args, **kwargs)
    value.update({"v137_audit_merge": "98c083b7dfc6cb378d0ee7239148370308f7c06f"})
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v138_harness_initialize_preflight_v1",
    )


def _inventory(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V132_BASELINE["_inventory"](*args, **kwargs),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v138_execution_inventory_v1",
    )


def _runtime_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V132_BASELINE["_runtime_receipt"](*args, **kwargs)
    value.update(
        {
            "scanner_policy_id": "deepseek-harness-v138-bounded-command-scan-v1",
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v138_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    value = _V132_BASELINE["_clean_socket_volume"](manifest, root=root)
    value.update(
        {
            "failed_data_volume_policy": "freeze-exact-owned-volume",
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v138_socket_cleanup_receipt_v1",
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
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v138 predecessor canonical hash changed")
    return observed


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError("v138 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v138 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v138 predecessor JSON must be an object")
    return value


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    purpose = load_v138_fresh_explicit_scaffold_manifest(MANIFEST)
    with _v132_baseline():
        predecessor = _V132_BASELINE["_load_composed_manifest"](V132_MANIFEST)
        _V132_BASELINE["_validate_static_bindings"](
            predecessor,
            v92_manifest,
            v92_report,
            v92_manifest_path=v92_manifest_path,
            v92_report_path=v92_report_path,
        )
    v132_purpose = load_v132_bounded_scan_scaffold_manifest(V132_MANIFEST)
    v136_purpose = load_v136_command_runtime_diagnostic_manifest(V136_MANIFEST)
    v132_report_path = V132_ROOT / "execution-scaffold-report.json"
    v132_contract_path = V132_ROOT / "execution-scaffold-contract.json"
    v136_report_path = V136_ROOT / "command-runtime-report.json"
    v136_cleanup_path = V136_ROOT / "cleanup-receipt.json"
    v132_report = _load_json(v132_report_path)
    v132_contract = _load_json(v132_contract_path)
    v136_report = _load_json(v136_report_path)
    v136_cleanup = _load_json(v136_cleanup_path)
    if (
        _hash_file(V132_MANIFEST) != purpose.v132_manifest_sha256
        or v132_purpose.manifest_hash != purpose.v132_manifest_hash
        or _hash_file(V132_RUNNER) != purpose.v132_runner_sha256
        or _hash_file(v132_report_path) != purpose.v132_report_sha256
        or _canonical_hash(v132_report, "report_hash") != purpose.v132_report_hash
        or _hash_file(v132_contract_path) != purpose.v132_contract_sha256
        or _canonical_hash(v132_contract, "contract_hash") != purpose.v132_contract_hash
        or _hash_file(V133_AUDIT) != purpose.v133_audit_sha256
        or _hash_file(V136_MANIFEST) != purpose.v136_manifest_sha256
        or v136_purpose.manifest_hash != purpose.v136_manifest_hash
        or _hash_file(V136_RUNNER) != purpose.v136_runner_sha256
        or _hash_file(V136_AUTHORIZATION) != purpose.v136_authorization_sha256
        or _hash_file(v136_report_path) != purpose.v136_report_sha256
        or _canonical_hash(v136_report, "report_hash") != purpose.v136_report_hash
        or _hash_file(v136_cleanup_path) != purpose.v136_cleanup_sha256
        or _canonical_hash(v136_cleanup, "receipt_hash") != purpose.v136_cleanup_hash
        or _hash_file(V137_AUDIT) != purpose.v137_audit_sha256
        or manifest.schedule != v92_manifest.schedule
        or [item.task_id for item in manifest.schedule] != purpose.schedule_task_ids
        or manifest.seed != purpose.seed
        or manifest.sample_index != purpose.sample_index
        or manifest.manifest_hash != purpose.manifest_hash
    ):
        raise ConfigurationError("v138 predecessor or immutable schedule binding changed")
    if (
        v132_report.get("status") != "completed_pending_independent_v133_audit"
        or v132_report.get("provider_execution_scaffold_published") is not True
        or v132_report.get("provider_calls") != 0
        or v132_contract.get("contract_hash") != purpose.v132_contract_hash
        or v136_report.get("status") != "stopped_after_zero_provider_diagnostic"
        or v136_report.get("stop_reason") != "unexpected_controller_failure"
        or v136_report.get("provider_request_started") is not False
        or v136_report.get("provider_calls") != 0
        or v136_report.get("task_execution_started") is not False
        or v136_cleanup.get("status") != "cleanup_unconfirmed"
        or purpose.archive_import_explicit_endpoint_required is not True
        or purpose.archive_import_stage_diagnostic_required is not True
        or purpose.archive_import_raw_output_allowed is not False
        or purpose.archive_import_nonempty_output_hashing_allowed is not False
        or purpose.v132_volume_inspection_allowed is not False
        or purpose.v132_volume_mutation_allowed is not False
        or purpose.provider_successor_identity != "deepseek-harness-hwe-v140-official-matrix-v1"
        or purpose.requires_independent_v139_audit is not True
        or any(getattr(purpose, name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v138 purpose or zero-provider predecessor state changed")
    for commit in (purpose.v133_audit_merge, purpose.v137_audit_merge):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=_REPOSITORY,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout or result.stderr:
            raise ConfigurationError("v138 requires its independent audits merged")


def _bounded_scan_and_lock(**kwargs: Any) -> Any:
    if "runtime_policy" in kwargs:
        raise ConfigurationError("v138 refuses an externally supplied scanner policy")
    lock_path = kwargs.get("identity_lock_path")
    if not isinstance(lock_path, Path) or not lock_path.stem.startswith("pr-"):
        raise ConfigurationError("v138 scanner task identity is invalid")
    try:
        pr_number = int(lock_path.stem.removeprefix("pr-"))
    except ValueError as exc:
        raise ConfigurationError("v138 scanner task identity is invalid") from exc
    if pr_number not in _TASK_PR_NUMBERS:
        raise ConfigurationError("v138 scanner task is outside the frozen schedule")
    policy = CommandImageScanRuntimePolicy(
        policy_id="deepseek-harness-v138-bounded-command-scan-v1",
        create_timeout_seconds=300,
        inspect_timeout_seconds=60,
        start_timeout_seconds=180,
        remove_timeout_seconds=120,
        overall_timeout_seconds=720,
        container_name=f"verigym-hwe-v138-command-scan-pr-{pr_number}",
        owner_label=IDENTITY,
    )
    scan, lock = v132._V69_SCAN_AND_LOCK(**kwargs, runtime_policy=policy)  # noqa: SLF001
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
        raise ConfigurationError("v138 bounded command-image scan did not pass")
    return scan, lock


def _import_metric(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    return {
        "exit_code": result.returncode,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
    }


def _write_import_diagnostic(
    root: Path,
    task: HweOfflineTaskLock,
    *,
    status: str,
    category: str,
    stages: Mapping[str, Any],
) -> None:
    directory = root / "archive-import-diagnostics"
    directory.mkdir(mode=0o700, exist_ok=True)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v138_archive_import_diagnostic_v1",
        "identity": IDENTITY,
        "task_id": task.task_id,
        "status": status,
        "category": category,
        "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
        "explicit_endpoint_binding": True,
        "stages": dict(stages),
        "raw_output_persisted": False,
        "nonempty_output_hashed": False,
        "raw_exception_persisted": False,
        "registry_accessed": False,
        "partial_archive_used": False,
        "provider_calls": 0,
    }
    atomic_dump_json(
        directory / f"pr-{task.pr_number}.json",
        {**base, "diagnostic_hash": content_hash(base)},
    )


def _explicit_docker_environment(manifest: Any) -> dict[str, str]:
    socket = DIND_SOCKET_BACKING / "docker.sock"
    expected = f"unix://{socket}"
    if manifest.nested_docker_host != expected or not socket.is_socket():
        raise ConfigurationError("v138 explicit nested Docker socket is unavailable")
    environment = dict(os.environ)
    environment["DOCKER_HOST"] = expected
    environment.pop("DOCKER_CONTEXT", None)
    return environment


def _docker_command(
    arguments: list[str],
    *,
    environment: Mapping[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", *arguments],
        cwd=_REPOSITORY,
        env=environment,
        check=False,
        capture_output=True,
        timeout=timeout,
    )


def _explicit_archive_import(
    task: HweOfflineTaskLock,
    *,
    archive_root: Path,
    root: Path,
    manifest: Any,
) -> None:
    archive = v69._contained_file(  # noqa: SLF001
        archive_root, task.archive_relpath, 16 * 1024 * 1024 * 1024
    )
    environment = _explicit_docker_environment(manifest)
    stages: dict[str, Any] = {}
    try:
        loaded = _docker_command(
            ["load", "--input", str(archive)],
            environment=environment,
            timeout=manifest.archive_import_timeout_seconds,
        )
        stages["load"] = _import_metric(loaded)
        if loaded.returncode != 0:
            category = "archive_load_exit_nonzero"
        elif max(len(loaded.stdout), len(loaded.stderr)) > _MAX_IMPORT_OUTPUT:
            category = "archive_load_output_oversized"
        else:
            category = "archive_load_complete"
        if category != "archive_load_complete":
            _write_import_diagnostic(root, task, status="failed", category=category, stages=stages)
            raise ConfigurationError("v138 explicit archive import failed")
        image = _docker_command(
            ["image", "inspect", task.official_verifier_image, "--format", "{{.Id}}"],
            environment=environment,
            timeout=30,
        )
        stages["image_identity"] = _import_metric(image)
        image_id = image.stdout.decode("ascii", errors="strict").strip()
        if image.returncode != 0 or image_id != task.official_verifier_image:
            _write_import_diagnostic(
                root,
                task,
                status="failed",
                category="archive_image_identity_mismatch",
                stages=stages,
            )
            raise ConfigurationError("v138 imported image identity changed")
        tagged = _docker_command(
            ["image", "inspect", task.registry_reference, "--format", "{{.Id}}"],
            environment=environment,
            timeout=30,
        )
        stages["tag_before"] = _import_metric(tagged)
        tagged_id = tagged.stdout.decode("ascii", errors="strict").strip()
        if tagged.returncode == 0 and tagged_id != task.official_verifier_image:
            _write_import_diagnostic(
                root,
                task,
                status="failed",
                category="archive_tag_collision",
                stages=stages,
            )
            raise ConfigurationError("v138 official task tag collision")
        if tagged.returncode != 0:
            tag = _docker_command(
                ["image", "tag", task.official_verifier_image, task.registry_reference],
                environment=environment,
                timeout=30,
            )
            stages["tag_create"] = _import_metric(tag)
            if tag.returncode != 0:
                _write_import_diagnostic(
                    root,
                    task,
                    status="failed",
                    category="archive_tag_create_failed",
                    stages=stages,
                )
                raise ConfigurationError("v138 official task tag creation failed")
        verified = _docker_command(
            ["image", "inspect", task.registry_reference, "--format", "{{.Id}}"],
            environment=environment,
            timeout=30,
        )
        stages["tag_verify"] = _import_metric(verified)
        verified_id = verified.stdout.decode("ascii", errors="strict").strip()
        if verified.returncode != 0 or verified_id != task.official_verifier_image:
            _write_import_diagnostic(
                root,
                task,
                status="failed",
                category="archive_tag_verify_failed",
                stages=stages,
            )
            raise ConfigurationError("v138 official task tag verification failed")
    except subprocess.TimeoutExpired as exc:
        stages["timeout"] = {
            "stdout_bytes": len(exc.stdout or b""),
            "stderr_bytes": len(exc.stderr or b""),
            "timeout_seconds": exc.timeout,
        }
        _write_import_diagnostic(
            root,
            task,
            status="failed",
            category="archive_import_timeout",
            stages=stages,
        )
        raise ConfigurationError("v138 explicit archive import timed out") from exc
    except (OSError, UnicodeError) as exc:
        _write_import_diagnostic(
            root,
            task,
            status="failed",
            category="archive_import_controller_error",
            stages=stages,
        )
        raise ConfigurationError("v138 explicit archive import controller failed") from exc
    _write_import_diagnostic(
        root,
        task,
        status="passed",
        category="archive_import_complete",
        stages=stages,
    )


def _v138_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97" or not args:
        raise ConfigurationError("v138 refuses an unexpected task materialization call")
    task = args[0]
    root = kwargs.get("root")
    if not isinstance(task, HweOfflineTaskLock) or not isinstance(root, Path):
        raise ConfigurationError("v138 task materialization binding is invalid")
    manifest = _load_composed_manifest(MANIFEST)

    def load_completed_archive(bound: HweOfflineTaskLock, *, archive_root: Path) -> None:
        if bound != task:
            raise ConfigurationError("v138 archive import task binding changed")
        _explicit_archive_import(bound, archive_root=archive_root, root=root, manifest=manifest)

    previous = v69._load_completed_archive  # noqa: SLF001
    try:
        v69._load_completed_archive = load_completed_archive  # noqa: SLF001
        kwargs["command_tag_version"] = "v138"
        value = v132._V127_BASE_MATERIALIZE_TASK(*args, **kwargs)  # noqa: SLF001
    finally:
        v69._load_completed_archive = previous  # noqa: SLF001
    base = copy.deepcopy(value)
    base.pop("task_receipt_hash", None)
    base.update(
        {
            "scanner_policy_id": "deepseek-harness-v138-bounded-command-scan-v1",
            "scanner_create_timeout_seconds": 300,
            "scanner_overall_timeout_seconds": 720,
            "archive_import_explicit_endpoint": True,
            "archive_import_stage_diagnostic": True,
            "v132_scaffold_qualified": True,
        }
    )
    return {**base, "task_receipt_hash": content_hash(base)}


def _materialize_tasks(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, HweCommandImageLock]]:
    value, locks = v132._V127_MATERIALIZE_TASKS(  # noqa: SLF001
        manifest, v92_manifest, **kwargs
    )
    base = copy.deepcopy(value)
    base.pop("receipt_hash", None)
    receipts = base.get("task_receipts")
    expected = [item.task_id for item in manifest.schedule]
    if not isinstance(receipts, list) or len(receipts) != len(expected):
        raise ConfigurationError("v138 refuses partial task materialization")
    for task_id, receipt in zip(expected, receipts, strict=True):
        if (
            not isinstance(receipt, dict)
            or receipt.get("task_id") != task_id
            or receipt.get("scanner_policy_id") != "deepseek-harness-v138-bounded-command-scan-v1"
            or receipt.get("archive_import_explicit_endpoint") is not True
        ):
            raise ConfigurationError("v138 task receipt is incomplete")
        receipt.pop("task_receipt_hash", None)
        receipt.pop("requires_independent_v133_audit", None)
        receipt.update(
            {
                "format_id": ("verigym_deepseek_harness_hwe_v138_task_materialization_receipt_v1"),
                "identity": IDENTITY,
                "requires_independent_v139_audit": True,
                "predecessor_volumes_inspected": False,
                "predecessor_volumes_mutated": False,
                "v132_volume_inspected": False,
                "v132_volume_mutated": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v138_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "scanner_policy_id": "deepseek-harness-v138-bounded-command-scan-v1",
            "scanner_all_five_tasks_required": True,
            "archive_import_all_five_explicit": True,
            "requires_independent_v139_audit": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v138 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = v132._V127_SCAFFOLD_CONTRACT(manifest, **kwargs)  # noqa: SLF001
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("requires_independent_v128_audit", None)
    base.pop("requires_independent_v133_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v138_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v132_manifest_hash": manifest.v132_manifest_hash,
            "v136_report_hash": manifest.v136_report_hash,
            "v137_audit_merge": manifest.v137_audit_merge,
            "v137_post_merge_main_run_id": manifest.v137_post_merge_main_run_id,
            "scanner_policy_id": manifest.scanner_policy_id,
            "archive_import_policy": "explicit-endpoint-stage-diagnostic-v1",
            "archive_import_all_five_passed": True,
            "scanner_all_five_tasks_passed": True,
            "docker_cli_explicit_binding": True,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
            "requires_independent_v139_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = v132._V127_REQUIRE_CLEAN_MERGED_MAIN(manifest)  # noqa: SLF001
    for commit in (manifest.v133_audit_merge, manifest.v137_audit_merge):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, head],
            cwd=_REPOSITORY,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout or result.stderr:
            raise ConfigurationError("v138 requires clean merged origin/main after its audits")
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
