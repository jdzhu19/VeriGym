#!/usr/bin/env python3
"""Materialize five tasks with a widened, separately recorded Docker control bound."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
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
    materialize_hwe_deepseek_harness_v138_fresh_explicit_scaffold as v138,
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
    load_v138_fresh_explicit_scaffold_manifest,
    load_v140_verifier_control_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

v132 = v138.v132
v127 = v138.v127
v94 = v138.v94
v69 = v138.v69

IDENTITY = "deepseek-harness-hwe-v140-verifier-control-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V140_VERIFIER_CONTROL_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v140_verifier_control_scaffold_v1.json"
)
V138_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v138_fresh_explicit_scaffold_v1.json"
)
V138_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v138_fresh_explicit_scaffold.py"
)
V138_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v138-fresh-explicit-scaffold-authorization.md"
)
V139_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v139-v138-result.md"
V138_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v138-fresh-explicit-scaffold-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v140-verifier-control-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v140")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v140-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v140-runtime")
_TASK_PR_NUMBERS = frozenset({465, 1135, 1780, 2017, 2711})
_DOCKER_CONTROL_TIMEOUT_SECONDS = 300
_OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS = 900

_REQUIRED_MERGED_PATHS = (
    *v138._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-04_deepseek-harness-v139-v138-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v140_verifier_control_scaffold_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v140-verifier-control-scaffold-authorization.md",
    "scripts/materialize_hwe_deepseek_harness_v140_verifier_control_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v140_verifier_control_scaffold.py",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/adapter.py",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/cva6_qualification.py",
    "integrations/verigym-hwe-bench/src/verigym_hwe_bench/docker_verifier.py",
    "integrations/verigym-hwe-bench/tests/test_docker_verifier.py",
    "scripts/materialize_hwe_deepseek_harness_v69.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
    "SECURITY.md",
)

_V138_NAMES = (
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
    "_write_import_diagnostic",
    "_v138_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V138_BASELINE = {name: getattr(v138, name) for name in _V138_NAMES}


def _parser() -> argparse.ArgumentParser:
    parser = v138._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the fresh five-task provider-free verifier-control workflow."""

    with _v140_configuration():
        return v138.materialize(arguments)


@contextlib.contextmanager
def _v140_configuration() -> Iterator[None]:
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
        "_write_import_diagnostic": _write_import_diagnostic,
        "_v138_materialize_task": _v140_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v138, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v138, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v138, name, value)


@contextlib.contextmanager
def _v138_baseline() -> Iterator[None]:
    current = {name: getattr(v138, name) for name in _V138_BASELINE}
    try:
        for name, value in _V138_BASELINE.items():
            setattr(v138, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v138, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v140_verifier_control_scaffold_manifest(path)
    with _v138_baseline():
        predecessor = _V138_BASELINE["_load_composed_manifest"](V138_MANIFEST)
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
        raise ConfigurationError("v140 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v140_scaffold_progress_v1",
            "identity": IDENTITY,
            "v138_manifest_hash": (
                "82a041fc1a8ee234a08f48178c11699a9b8ef45e50fb110b2d7da234f00a1992"
            ),
            "v138_report_hash": (
                "0532764a23d9c50666f4708142135d2c54740b9950239e687905d536a43dde8b"
            ),
            "v139_audit_merge": "6837518e4014cd3431e3b6b40a42282c2fbbddc8",
            "archive_import_policy": "explicit-endpoint-stage-diagnostic-v1",
            "verifier_control_policy": "separate-cold-vfs-control-bound-v1",
            "verifier_docker_control_timeout_seconds": _DOCKER_CONTROL_TIMEOUT_SECONDS,
            "official_verifier_test_timeout_seconds": _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS,
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
        }
    )
    if value.get("status") in v127._SUCCESS_STATUS_NAMES:  # noqa: SLF001
        value["status"] = "completed_pending_independent_v141_audit"
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
    value = _V138_BASELINE["_transfer_images"](
        dind_name, manifest, host_images=host_images, root=root
    )
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v140_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v140 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
            "v138_failure_audited": True,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v140_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V138_BASELINE["_runtime_prepare_preflight"](*args, **kwargs)
    value.update(
        {
            "verifier_docker_control_timeout_seconds": _DOCKER_CONTROL_TIMEOUT_SECONDS,
            "official_verifier_test_timeout_seconds": _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS,
            "v138_volume_inspected": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v140_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V138_BASELINE["_harness_initialize_preflight"](*args, **kwargs)
    value.update({"v139_audit_merge": "6837518e4014cd3431e3b6b40a42282c2fbbddc8"})
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v140_harness_initialize_preflight_v1",
    )


def _inventory(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V138_BASELINE["_inventory"](*args, **kwargs),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v140_execution_inventory_v1",
    )


def _runtime_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V138_BASELINE["_runtime_receipt"](*args, **kwargs)
    value.update(
        {
            "scanner_policy_id": "deepseek-harness-v140-bounded-command-scan-v1",
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v140_dind_runtime_receipt_v1",
    )


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    value = _V138_BASELINE["_clean_socket_volume"](manifest, root=root)
    value.update(
        {
            "failed_data_volume_policy": "freeze-exact-owned-volume",
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v140_socket_cleanup_receipt_v1",
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
        raise ConfigurationError("v140 predecessor canonical hash changed")
    return observed


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError("v140 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v140 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v140 predecessor JSON must be an object")
    return value


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    purpose = load_v140_verifier_control_scaffold_manifest(MANIFEST)
    with _v138_baseline():
        predecessor = _V138_BASELINE["_load_composed_manifest"](V138_MANIFEST)
        _V138_BASELINE["_validate_static_bindings"](
            predecessor,
            v92_manifest,
            v92_report,
            v92_manifest_path=v92_manifest_path,
            v92_report_path=v92_report_path,
        )
    v138_purpose = load_v138_fresh_explicit_scaffold_manifest(V138_MANIFEST)
    report_path = V138_ROOT / "execution-scaffold-report.json"
    import_path = V138_ROOT / "archive-import-diagnostics/pr-465.json"
    base_path = V138_ROOT / ("qualification/pr-465/base-verifier/run_hidden_regression/result.json")
    reference_path = V138_ROOT / (
        "qualification/pr-465/reference-verifier/run_hidden_regression/result.json"
    )
    smoke_path = V138_ROOT / "qualification/pr-465/smoke-report.json"
    cleanup_path = V138_ROOT / "dind-cleanup-receipt.json"
    report = _load_json(report_path)
    import_diagnostic = _load_json(import_path)
    base_result = _load_json(base_path)
    reference_result = _load_json(reference_path)
    smoke = _load_json(smoke_path)
    cleanup = _load_json(cleanup_path)
    if (
        _hash_file(V138_MANIFEST) != purpose.v138_manifest_sha256
        or v138_purpose.manifest_hash != purpose.v138_manifest_hash
        or _hash_file(V138_RUNNER) != purpose.v138_runner_sha256
        or _hash_file(V138_AUTHORIZATION) != purpose.v138_authorization_sha256
        or _hash_file(report_path) != purpose.v138_report_sha256
        or _canonical_hash(report, "report_hash") != purpose.v138_report_hash
        or _hash_file(import_path) != purpose.v138_import_diagnostic_sha256
        or _canonical_hash(import_diagnostic, "diagnostic_hash")
        != purpose.v138_import_diagnostic_hash
        or _hash_file(base_path) != purpose.v138_base_result_sha256
        or _hash_file(reference_path) != purpose.v138_reference_result_sha256
        or _hash_file(smoke_path) != purpose.v138_smoke_report_sha256
        or _hash_file(cleanup_path) != purpose.v138_cleanup_sha256
        or _canonical_hash(cleanup, "receipt_hash") != purpose.v138_cleanup_hash
        or _hash_file(V139_AUDIT) != purpose.v139_audit_sha256
        or manifest.schedule != v92_manifest.schedule
        or [item.task_id for item in manifest.schedule] != purpose.schedule_task_ids
        or manifest.seed != purpose.seed
        or manifest.sample_index != purpose.sample_index
        or manifest.manifest_hash != purpose.manifest_hash
    ):
        raise ConfigurationError("v140 predecessor evidence or immutable schedule changed")
    if (
        report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "ConfigurationError"
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("provider_execution_scaffold_published") is not False
        or import_diagnostic.get("status") != "passed"
        or import_diagnostic.get("category") != "archive_import_complete"
        or base_result.get("status") != "failed"
        or base_result.get("error_category") != "test_failed"
        or reference_result.get("status") != "error"
        or reference_result.get("error_category") != "timeout"
        or reference_result.get("metadata") != {}
        or smoke.get("base_failed") is not True
        or smoke.get("base_infrastructure_error") is not False
        or smoke.get("reference_passed") is not False
        or cleanup.get("socket_volume_removed") is not True
        or purpose.dind_data_backing != str(DIND_DATA_BACKING)
        or purpose.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or purpose.control_headroom_root != str(CONTROL_ROOT)
        or purpose.runtime_scratch_root != str(RUNTIME_TMP)
        or purpose.output_root != str(OUTPUT_ROOT)
        or purpose.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.dind_owner != IDENTITY
        or purpose.verifier_docker_control_timeout_seconds != _DOCKER_CONTROL_TIMEOUT_SECONDS
        or purpose.official_verifier_test_timeout_seconds != _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS
        or purpose.verifier_control_stage_metadata_required is not True
        or purpose.verifier_control_raw_output_allowed is not False
        or purpose.v138_volume_inspection_allowed is not False
        or purpose.v138_volume_mutation_allowed is not False
        or purpose.provider_successor_identity != "deepseek-harness-hwe-v142-official-matrix-v1"
        or purpose.requires_independent_v141_audit is not True
        or any(getattr(purpose, name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v140 purpose or audited v138 terminal state changed")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", purpose.v139_audit_merge, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v140 requires the independent v139 audit merged")


def _bounded_scan_and_lock(**kwargs: Any) -> Any:
    if "runtime_policy" in kwargs:
        raise ConfigurationError("v140 refuses an externally supplied scanner policy")
    lock_path = kwargs.get("identity_lock_path")
    if not isinstance(lock_path, Path) or not lock_path.stem.startswith("pr-"):
        raise ConfigurationError("v140 scanner task identity is invalid")
    try:
        pr_number = int(lock_path.stem.removeprefix("pr-"))
    except ValueError as exc:
        raise ConfigurationError("v140 scanner task identity is invalid") from exc
    if pr_number not in _TASK_PR_NUMBERS:
        raise ConfigurationError("v140 scanner task is outside the frozen schedule")
    policy = CommandImageScanRuntimePolicy(
        policy_id="deepseek-harness-v140-bounded-command-scan-v1",
        create_timeout_seconds=300,
        inspect_timeout_seconds=60,
        start_timeout_seconds=180,
        remove_timeout_seconds=120,
        overall_timeout_seconds=720,
        container_name=f"verigym-hwe-v140-command-scan-pr-{pr_number}",
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
        raise ConfigurationError("v140 bounded command-image scan did not pass")
    return scan, lock


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
        "format_id": "verigym_deepseek_harness_hwe_v140_archive_import_diagnostic_v1",
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


def _verifier_control_row(path: Path, *, role: str, expected_status: str) -> dict[str, Any]:
    result = _load_json(path)
    metadata = result.get("metadata")
    if (
        result.get("status") != expected_status
        or result.get("raw_output_persisted") is not False
        or not isinstance(metadata, dict)
        or metadata.get("docker_control_stage") != "complete"
        or metadata.get("docker_control_timeout_s") != _DOCKER_CONTROL_TIMEOUT_SECONDS
        or metadata.get("verifier_timeout_s") != _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS
        or metadata.get("network_mode") != "none"
        or metadata.get("container_removed") is not True
        or metadata.get("output_persisted") is not False
    ):
        raise ConfigurationError("v140 verifier control result is incomplete or changed")
    return {
        "role": role,
        "status": result["status"],
        "error_category": result.get("error_category"),
        "docker_control_stage": metadata["docker_control_stage"],
        "docker_control_timeout_seconds": metadata["docker_control_timeout_s"],
        "official_verifier_test_timeout_seconds": metadata["verifier_timeout_s"],
        "network_mode": metadata["network_mode"],
        "container_removed": metadata["container_removed"],
        "raw_output_persisted": False,
    }


def _verifier_control_diagnostic(root: Path, task: HweOfflineTaskLock) -> dict[str, Any]:
    qualification = root / "qualification" / f"pr-{task.pr_number}"
    rows = [
        _verifier_control_row(
            qualification / "base-verifier/run_hidden_regression/result.json",
            role="base",
            expected_status="failed",
        ),
        _verifier_control_row(
            qualification / "reference-verifier/run_hidden_regression/result.json",
            role="reference",
            expected_status="passed",
        ),
    ]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v140_verifier_control_diagnostic_v1",
        "identity": IDENTITY,
        "task_id": task.task_id,
        "status": "passed",
        "verifier_runs": rows,
        "control_bound_widened_only": True,
        "official_verifier_semantics_unchanged": True,
        "raw_output_persisted": False,
        "nonempty_output_hashed": False,
        "provider_calls": 0,
    }
    result = {**base, "diagnostic_hash": content_hash(base)}
    directory = root / "verifier-control-diagnostics"
    directory.mkdir(mode=0o700, exist_ok=True)
    atomic_dump_json(directory / f"pr-{task.pr_number}.json", result)
    return result


def _v140_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97" or not args:
        raise ConfigurationError("v140 refuses an unexpected task materialization call")
    task = args[0]
    root = kwargs.get("root")
    if not isinstance(task, HweOfflineTaskLock) or not isinstance(root, Path):
        raise ConfigurationError("v140 task materialization binding is invalid")
    manifest = _load_composed_manifest(MANIFEST)

    def load_completed_archive(bound: HweOfflineTaskLock, *, archive_root: Path) -> None:
        if bound != task:
            raise ConfigurationError("v140 archive import task binding changed")
        v138._explicit_archive_import(  # noqa: SLF001
            bound,
            archive_root=archive_root,
            root=root,
            manifest=manifest,
        )

    previous = v69._load_completed_archive  # noqa: SLF001
    try:
        v69._load_completed_archive = load_completed_archive  # noqa: SLF001
        kwargs["command_tag_version"] = "v140"
        value = v132._V127_BASE_MATERIALIZE_TASK(*args, **kwargs)  # noqa: SLF001
    finally:
        v69._load_completed_archive = previous  # noqa: SLF001
    diagnostic = _verifier_control_diagnostic(root, task)
    base = copy.deepcopy(value)
    base.pop("task_receipt_hash", None)
    base.update(
        {
            "scanner_policy_id": "deepseek-harness-v140-bounded-command-scan-v1",
            "scanner_create_timeout_seconds": 300,
            "scanner_overall_timeout_seconds": 720,
            "archive_import_explicit_endpoint": True,
            "archive_import_stage_diagnostic": True,
            "verifier_docker_control_timeout_seconds": _DOCKER_CONTROL_TIMEOUT_SECONDS,
            "official_verifier_test_timeout_seconds": _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS,
            "verifier_control_diagnostic_hash": diagnostic["diagnostic_hash"],
            "v138_failure_audited": True,
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
        raise ConfigurationError("v140 refuses partial task materialization")
    for task_id, receipt in zip(expected, receipts, strict=True):
        if (
            not isinstance(receipt, dict)
            or receipt.get("task_id") != task_id
            or receipt.get("scanner_policy_id") != "deepseek-harness-v140-bounded-command-scan-v1"
            or receipt.get("archive_import_explicit_endpoint") is not True
            or receipt.get("verifier_docker_control_timeout_seconds")
            != _DOCKER_CONTROL_TIMEOUT_SECONDS
            or receipt.get("official_verifier_test_timeout_seconds")
            != _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS
        ):
            raise ConfigurationError("v140 task receipt is incomplete")
        receipt.pop("task_receipt_hash", None)
        receipt.pop("requires_independent_v133_audit", None)
        receipt.pop("requires_independent_v139_audit", None)
        receipt.update(
            {
                "format_id": "verigym_deepseek_harness_hwe_v140_task_materialization_receipt_v1",
                "identity": IDENTITY,
                "requires_independent_v141_audit": True,
                "predecessor_volumes_inspected": False,
                "predecessor_volumes_mutated": False,
                "v132_volume_inspected": False,
                "v132_volume_mutated": False,
                "v138_volume_inspected": False,
                "v138_volume_mutated": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v140_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "scanner_policy_id": "deepseek-harness-v140-bounded-command-scan-v1",
            "scanner_all_five_tasks_required": True,
            "archive_import_all_five_explicit": True,
            "verifier_control_diagnostics_all_five_passed": True,
            "requires_independent_v141_audit": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v140 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V138_BASELINE["_scaffold_contract"](manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("requires_independent_v139_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v140_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v138_manifest_hash": manifest.v138_manifest_hash,
            "v138_report_hash": manifest.v138_report_hash,
            "v139_audit_merge": manifest.v139_audit_merge,
            "v139_post_merge_main_run_id": manifest.v139_post_merge_main_run_id,
            "scanner_policy_id": manifest.scanner_policy_id,
            "verifier_control_policy": "separate-cold-vfs-control-bound-v1",
            "verifier_docker_control_timeout_seconds": (
                manifest.verifier_docker_control_timeout_seconds
            ),
            "official_verifier_test_timeout_seconds": (
                manifest.official_verifier_test_timeout_seconds
            ),
            "verifier_control_diagnostics_all_five_passed": True,
            "docker_cli_explicit_binding": True,
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
            "requires_independent_v141_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = _V138_BASELINE["_require_clean_merged_main"](manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v139_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v140 requires clean merged origin/main after v139")
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
