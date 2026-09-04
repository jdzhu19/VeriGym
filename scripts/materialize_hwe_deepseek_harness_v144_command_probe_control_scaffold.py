#!/usr/bin/env python3
"""Materialize five tasks with a bounded, content-free command-image probe controller."""

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
    materialize_hwe_deepseek_harness_v142_cleanup_control_scaffold as v142,
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
    load_v142_cleanup_control_scaffold_manifest,
    load_v144_command_probe_control_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.runtimes.docker.errors import DockerImageError  # noqa: E402

v140 = v142.v140
v138 = v142.v138
v132 = v142.v132
v127 = v142.v127
v94 = v142.v94
v69 = v142.v69
dind = v142.dind

IDENTITY = "deepseek-harness-hwe-v144-command-probe-control-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V144_COMMAND_PROBE_CONTROL_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v144_command_probe_control_scaffold_v1.json"
)
V142_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v142_cleanup_control_scaffold_v1.json"
)
V142_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v142_cleanup_control_scaffold.py"
)
V142_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v142-cleanup-control-scaffold-authorization.md"
)
V143_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v143-v142-result.md"
V142_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v142-cleanup-control-scaffold-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v144-command-probe-control-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v144")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v144-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v144-runtime")
_TASK_PR_NUMBERS = frozenset({465, 1135, 1780, 2017, 2711})
_DOCKER_CONTROL_TIMEOUT_SECONDS = 300
_OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS = 900
_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS = 300
_COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS = 300

_REQUIRED_MERGED_PATHS = (
    *v142._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-05_deepseek-harness-v143-v142-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v144_command_probe_control_scaffold_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v144-command-probe-control-scaffold-authorization.md",
    "scripts/materialize_hwe_deepseek_harness_v144_command_probe_control_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v144_command_probe_control_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "src/verigym/runtimes/docker/runtime.py",
    "src/verigym/schemas/runtime.py",
    "tests/unit/test_docker_config_image.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
    "SECURITY.md",
)

_V142_NAMES = (
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
    "_write_cleanup_diagnostic",
    "_validate_static_bindings",
    "_bounded_scan_and_lock",
    "_write_import_diagnostic",
    "_v142_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V142_BASELINE = {name: getattr(v142, name) for name in _V142_NAMES}

_ALLOWED_IMAGE_SUBREASONS = frozenset(
    {
        "command_image_health_failed",
        "command_image_identity_invalid",
        "command_image_labels_invalid",
        "command_image_user_mapping_invalid",
        "image_environment_invalid",
        "image_health_failed",
        "image_id_mismatch",
        "image_missing",
        "image_probe_output_invalid",
        "role_image_identity_collision",
    }
)
_ALLOWED_FAILURE_REASONS = frozenset(
    {
        "container_cleanup_failed",
        "container_create_failed",
        "container_inspect_failed",
        "container_remove_failed",
        "container_start_failed",
        "out_of_memory",
        "timeout",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = v142._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the fresh five-task provider-free command-probe control workflow."""

    with _v144_configuration():
        return v142.materialize(arguments)


@contextlib.contextmanager
def _v144_configuration() -> Iterator[None]:
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
        "_write_cleanup_diagnostic": _write_cleanup_diagnostic,
        "_validate_static_bindings": _validate_static_bindings,
        "_bounded_scan_and_lock": _bounded_scan_and_lock,
        "_write_import_diagnostic": _write_import_diagnostic,
        "_v142_materialize_task": _v144_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v142, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v142, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v142, name, value)


@contextlib.contextmanager
def _v142_baseline() -> Iterator[None]:
    current = {name: getattr(v142, name) for name in _V142_BASELINE}
    try:
        for name, value in _V142_BASELINE.items():
            setattr(v142, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v142, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v144_command_probe_control_scaffold_manifest(path)
    with _v142_baseline():
        predecessor = _V142_BASELINE["_load_composed_manifest"](V142_MANIFEST)
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
        raise ConfigurationError("v144 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v144_scaffold_progress_v1",
            "identity": IDENTITY,
            "v142_manifest_hash": (
                "e092e4f943b51acffbd900c967d5732c616051491afed459aa11769813cc30ae"
            ),
            "v142_report_hash": (
                "933394340f0965bb102191e2958aa228292d57417d4096b60f47a1e6901cb87c"
            ),
            "v143_audit_merge": "0f2735e1720291a60debdadd18392626589775b0",
            "command_image_probe_control_policy": "explicit-bounded-content-free-v1",
            "command_image_probe_control_timeout_seconds": (
                _COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS
            ),
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
            "v140_volume_inspected": False,
            "v140_volume_mutated": False,
            "v142_volume_inspected": False,
            "v142_volume_mutated": False,
        }
    )
    if value.get("status") in v127._SUCCESS_STATUS_NAMES:  # noqa: SLF001
        value["status"] = "completed_pending_independent_v145_audit"
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
    value = _V142_BASELINE["_transfer_images"](
        dind_name, manifest, host_images=host_images, root=root
    )
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v144_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v144 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
            "v142_failure_audited": True,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v144_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _safe_probe_details(error: DockerImageError) -> dict[str, Any]:
    details = error.details
    failure_reason = details.get("failure_reason")
    failure_origin = details.get("failure_origin")
    exit_code = details.get("exit_code")
    return {
        "probe_protocol": (
            "combined_image_identity_v1"
            if details.get("probe_protocol") == "combined_image_identity_v1"
            else None
        ),
        "failure_reason": (failure_reason if failure_reason in _ALLOWED_FAILURE_REASONS else None),
        "failure_origin": (
            failure_origin if failure_origin in {"candidate_process", "control_plane"} else None
        ),
        "timed_out": details.get("timed_out") is True,
        "oom_killed": details.get("oom_killed") is True,
        "output_truncated": details.get("output_truncated") is True,
        "exit_code": (
            exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None
        ),
    }


def _write_command_probe_diagnostic(
    *,
    status: str,
    completed_task_ids: list[str],
    current_task_id: str | None,
    error: DockerImageError | None,
) -> dict[str, Any]:
    directory = OUTPUT_ROOT / "command-image-probe-diagnostics"
    directory.mkdir(mode=0o700, exist_ok=True)
    subreason = None
    if error is not None:
        subreason = (
            error.subreason
            if error.subreason in _ALLOWED_IMAGE_SUBREASONS
            else "unallowlisted_docker_image_error"
        )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v144_command_image_probe_diagnostic_v1",
        "identity": IDENTITY,
        "status": status,
        "category": "all_command_image_probes_passed" if error is None else subreason,
        "completed_task_ids": completed_task_ids,
        "current_task_id": current_task_id,
        "command_image_probe_control_timeout_seconds": (
            _COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS
        ),
        "probe_details": None if error is None else _safe_probe_details(error),
        "raw_output_persisted": False,
        "nonempty_output_hashed": False,
        "raw_exception_persisted": False,
        "raw_exception_hashed": False,
        "provider_calls": 0,
        "v142_volume_inspected": False,
        "v142_volume_mutated": False,
    }
    result = {**base, "diagnostic_hash": content_hash(base)}
    atomic_dump_json(directory / "attempt-1.json", result)
    return result


def _runtime_prepare_preflight(
    manifest: Any,
    *,
    locks: Mapping[str, HweCommandImageLock],
    dind_name: str,
) -> dict[str, Any]:
    if (
        manifest.command_image_probe_control_timeout_seconds
        != _COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS
        or manifest.command_image_probe_stage_metadata_required is not True
        or manifest.command_image_probe_raw_output_allowed is not False
        or manifest.command_image_probe_nonempty_output_hashing_allowed is not False
    ):
        raise ConfigurationError("v144 command-image probe control policy changed")
    runtime_module = v94.v92
    original_runtime_config = runtime_module._runtime_config  # noqa: SLF001
    current_task_id: str | None = None
    configured_task_ids: list[str] = []

    def runtime_config(lock: HweCommandImageLock) -> Any:
        nonlocal current_task_id
        current_task_id = lock.task_id
        config = original_runtime_config(lock)
        command = config.command_image
        if command is None:
            raise ConfigurationError("v144 command-image runtime binding is missing")
        configured_task_ids.append(lock.task_id)
        return config.model_copy(
            update={
                "command_image": command.model_copy(
                    update={
                        "identity_probe_timeout_s": (_COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS)
                    }
                )
            }
        )

    runtime_module._runtime_config = runtime_config  # type: ignore[assignment]  # noqa: SLF001
    try:
        value = _V142_BASELINE["_runtime_prepare_preflight"](
            manifest,
            locks=locks,
            dind_name=dind_name,
        )
    except DockerImageError as exc:
        completed = configured_task_ids[:-1] if configured_task_ids else []
        _write_command_probe_diagnostic(
            status="failed",
            completed_task_ids=completed,
            current_task_id=current_task_id,
            error=exc,
        )
        raise
    finally:
        runtime_module._runtime_config = original_runtime_config  # type: ignore[assignment]  # noqa: SLF001
    completed = list(value.get("completed_task_ids", []))
    diagnostic = _write_command_probe_diagnostic(
        status="passed",
        completed_task_ids=completed,
        current_task_id=None,
        error=None,
    )
    value.update(
        {
            "command_image_probe_control_policy": "explicit-bounded-content-free-v1",
            "command_image_probe_control_timeout_seconds": (
                _COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS
            ),
            "command_image_probe_diagnostic_hash": diagnostic["diagnostic_hash"],
            "v142_volume_inspected": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v144_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V142_BASELINE["_harness_initialize_preflight"](*args, **kwargs)
    value.update(
        {
            "v143_audit_merge": "0f2735e1720291a60debdadd18392626589775b0",
            "v142_volume_inspected": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v144_harness_initialize_preflight_v1",
    )


def _inventory(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V142_BASELINE["_inventory"](*args, **kwargs),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v144_execution_inventory_v1",
    )


def _runtime_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V142_BASELINE["_runtime_receipt"](*args, **kwargs)
    value.update(
        {
            "scanner_policy_id": "deepseek-harness-v144-bounded-command-scan-v1",
            "command_image_probe_control_timeout_seconds": (
                _COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS
            ),
            "v142_volume_inspected": False,
            "v142_volume_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v144_dind_runtime_receipt_v1",
    )


def _write_cleanup_diagnostic(
    root: Path,
    *,
    status: str,
    category: str,
    stages: Mapping[str, Any],
) -> dict[str, Any]:
    directory = root / "socket-cleanup-diagnostics"
    directory.mkdir(mode=0o700, exist_ok=True)
    attempt = len(tuple(directory.glob("attempt-*.json"))) + 1
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v144_socket_cleanup_diagnostic_v1",
        "identity": IDENTITY,
        "attempt": attempt,
        "status": status,
        "category": category,
        "socket_cleanup_control_timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        "stages": dict(stages),
        "raw_output_persisted": False,
        "nonempty_output_hashed": False,
        "raw_exception_persisted": False,
        "v142_volume_inspected": False,
        "v142_volume_mutated": False,
        "provider_calls": 0,
    }
    result = {**base, "diagnostic_hash": content_hash(base)}
    atomic_dump_json(directory / f"attempt-{attempt}.json", result)
    return result


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    value = _V142_BASELINE["_clean_socket_volume"](manifest, root=root)
    value.update(
        {
            "failed_data_volume_policy": "freeze-exact-owned-volume",
            "v142_volume_inspected": False,
            "v142_volume_mutated": False,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v144_socket_cleanup_receipt_v1",
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
        raise ConfigurationError("v144 predecessor canonical hash changed")
    return observed


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError("v144 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v144 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v144 predecessor JSON must be an object")
    return value


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    purpose = load_v144_command_probe_control_scaffold_manifest(MANIFEST)
    with _v142_baseline():
        predecessor = _V142_BASELINE["_load_composed_manifest"](V142_MANIFEST)
        _V142_BASELINE["_validate_static_bindings"](
            predecessor,
            v92_manifest,
            v92_report,
            v92_manifest_path=v92_manifest_path,
            v92_report_path=v92_report_path,
        )
    v142_purpose = load_v142_cleanup_control_scaffold_manifest(V142_MANIFEST)
    report_path = V142_ROOT / "execution-scaffold-report.json"
    task_path = V142_ROOT / "task-materialization-set.json"
    inventory_path = V142_ROOT / "execution-inventory.json"
    cleanup_path = V142_ROOT / "dind-cleanup-receipt.json"
    report = _load_json(report_path)
    task = _load_json(task_path)
    inventory = _load_json(inventory_path)
    cleanup = _load_json(cleanup_path)
    if (
        _hash_file(V142_MANIFEST) != purpose.v142_manifest_sha256
        or v142_purpose.manifest_hash != purpose.v142_manifest_hash
        or _hash_file(V142_RUNNER) != purpose.v142_runner_sha256
        or _hash_file(V142_AUTHORIZATION) != purpose.v142_authorization_sha256
        or _hash_file(report_path) != purpose.v142_report_sha256
        or _canonical_hash(report, "report_hash") != purpose.v142_report_hash
        or _hash_file(task_path) != purpose.v142_task_materialization_sha256
        or _canonical_hash(task, "receipt_hash") != purpose.v142_task_materialization_hash
        or _hash_file(inventory_path) != purpose.v142_execution_inventory_sha256
        or _canonical_hash(inventory, "inventory_hash") != purpose.v142_execution_inventory_hash
        or _hash_file(cleanup_path) != purpose.v142_cleanup_sha256
        or _canonical_hash(cleanup, "receipt_hash") != purpose.v142_cleanup_hash
        or _hash_file(V143_AUDIT) != purpose.v143_audit_sha256
        or manifest.schedule != v92_manifest.schedule
        or [item.task_id for item in manifest.schedule] != purpose.schedule_task_ids
        or manifest.seed != purpose.seed
        or manifest.sample_index != purpose.sample_index
        or manifest.manifest_hash != purpose.manifest_hash
    ):
        raise ConfigurationError("v144 predecessor evidence or immutable schedule changed")
    if (
        report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "DockerImageError"
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or report.get("provider_execution_scaffold_published") is not False
        or report.get("raw_exception_persisted") is not False
        or task.get("verifier_control_diagnostics_all_five_passed") is not True
        or task.get("all_base_failed_reference_passed") is not True
        or task.get("all_command_images_v2_scanned") is not True
        or len(task.get("task_receipts", [])) != 5
        or inventory.get("required_images_present") is not True
        or inventory.get("inner_container_inventory_empty") is not True
        or inventory.get("inner_volume_inventory_empty") is not True
        or cleanup.get("socket_volume_removed") is not True
        or cleanup.get("socket_backing_empty") is not True
        or purpose.dind_data_backing != str(DIND_DATA_BACKING)
        or purpose.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or purpose.control_headroom_root != str(CONTROL_ROOT)
        or purpose.runtime_scratch_root != str(RUNTIME_TMP)
        or purpose.output_root != str(OUTPUT_ROOT)
        or purpose.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.dind_owner != IDENTITY
        or purpose.command_image_probe_control_timeout_seconds
        != _COMMAND_IMAGE_PROBE_CONTROL_TIMEOUT_SECONDS
        or purpose.command_image_probe_stage_metadata_required is not True
        or purpose.command_image_probe_raw_output_allowed is not False
        or purpose.command_image_probe_nonempty_output_hashing_allowed is not False
        or purpose.v142_volume_inspection_allowed is not False
        or purpose.v142_volume_mutation_allowed is not False
        or purpose.provider_successor_identity != "deepseek-harness-hwe-v146-official-matrix-v1"
        or purpose.requires_independent_v145_audit is not True
        or any(getattr(purpose, name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v144 purpose or audited v142 terminal state changed")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", purpose.v143_audit_merge, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v144 requires the independent v143 audit merged")


def _bounded_scan_and_lock(**kwargs: Any) -> Any:
    if "runtime_policy" in kwargs:
        raise ConfigurationError("v144 refuses an externally supplied scanner policy")
    lock_path = kwargs.get("identity_lock_path")
    if not isinstance(lock_path, Path) or not lock_path.stem.startswith("pr-"):
        raise ConfigurationError("v144 scanner task identity is invalid")
    try:
        pr_number = int(lock_path.stem.removeprefix("pr-"))
    except ValueError as exc:
        raise ConfigurationError("v144 scanner task identity is invalid") from exc
    if pr_number not in _TASK_PR_NUMBERS:
        raise ConfigurationError("v144 scanner task is outside the frozen schedule")
    policy = CommandImageScanRuntimePolicy(
        policy_id="deepseek-harness-v144-bounded-command-scan-v1",
        create_timeout_seconds=300,
        inspect_timeout_seconds=60,
        start_timeout_seconds=180,
        remove_timeout_seconds=120,
        overall_timeout_seconds=720,
        container_name=f"verigym-hwe-v144-command-scan-pr-{pr_number}",
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
        raise ConfigurationError("v144 bounded command-image scan did not pass")
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
        "format_id": "verigym_deepseek_harness_hwe_v144_archive_import_diagnostic_v1",
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


def _v144_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97" or not args:
        raise ConfigurationError("v144 refuses an unexpected task materialization call")
    task = args[0]
    root = kwargs.get("root")
    if not isinstance(task, HweOfflineTaskLock) or not isinstance(root, Path):
        raise ConfigurationError("v144 task materialization binding is invalid")
    manifest = _load_composed_manifest(MANIFEST)

    def load_completed_archive(bound: HweOfflineTaskLock, *, archive_root: Path) -> None:
        if bound != task:
            raise ConfigurationError("v144 archive import task binding changed")
        v138._explicit_archive_import(  # noqa: SLF001
            bound,
            archive_root=archive_root,
            root=root,
            manifest=manifest,
        )

    previous = v69._load_completed_archive  # noqa: SLF001
    try:
        v69._load_completed_archive = load_completed_archive  # noqa: SLF001
        kwargs["command_tag_version"] = "v144"
        value = v132._V127_BASE_MATERIALIZE_TASK(*args, **kwargs)  # noqa: SLF001
    finally:
        v69._load_completed_archive = previous  # noqa: SLF001
    diagnostic = v140._verifier_control_diagnostic(root, task)  # noqa: SLF001
    diagnostic = _reseal(
        diagnostic,
        hash_field="diagnostic_hash",
        format_id="verigym_deepseek_harness_hwe_v144_verifier_control_diagnostic_v1",
    )
    atomic_dump_json(
        root / "verifier-control-diagnostics" / f"pr-{task.pr_number}.json", diagnostic
    )
    base = copy.deepcopy(value)
    base.pop("task_receipt_hash", None)
    base.update(
        {
            "scanner_policy_id": "deepseek-harness-v144-bounded-command-scan-v1",
            "scanner_create_timeout_seconds": 300,
            "scanner_overall_timeout_seconds": 720,
            "archive_import_explicit_endpoint": True,
            "archive_import_stage_diagnostic": True,
            "verifier_docker_control_timeout_seconds": _DOCKER_CONTROL_TIMEOUT_SECONDS,
            "official_verifier_test_timeout_seconds": _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS,
            "verifier_control_diagnostic_hash": diagnostic["diagnostic_hash"],
            "v142_failure_audited": True,
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
        raise ConfigurationError("v144 refuses partial task materialization")
    for task_id, receipt in zip(expected, receipts, strict=True):
        if (
            not isinstance(receipt, dict)
            or receipt.get("task_id") != task_id
            or receipt.get("scanner_policy_id") != "deepseek-harness-v144-bounded-command-scan-v1"
            or receipt.get("archive_import_explicit_endpoint") is not True
            or receipt.get("verifier_docker_control_timeout_seconds")
            != _DOCKER_CONTROL_TIMEOUT_SECONDS
            or receipt.get("official_verifier_test_timeout_seconds")
            != _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS
        ):
            raise ConfigurationError("v144 task receipt is incomplete")
        receipt.pop("task_receipt_hash", None)
        for field in (
            "requires_independent_v133_audit",
            "requires_independent_v139_audit",
            "requires_independent_v141_audit",
            "requires_independent_v143_audit",
        ):
            receipt.pop(field, None)
        receipt.update(
            {
                "format_id": ("verigym_deepseek_harness_hwe_v144_task_materialization_receipt_v1"),
                "identity": IDENTITY,
                "requires_independent_v145_audit": True,
                "predecessor_volumes_inspected": False,
                "predecessor_volumes_mutated": False,
                "v132_volume_inspected": False,
                "v132_volume_mutated": False,
                "v138_volume_inspected": False,
                "v138_volume_mutated": False,
                "v140_volume_inspected": False,
                "v140_volume_mutated": False,
                "v142_volume_inspected": False,
                "v142_volume_mutated": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v144_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "scanner_policy_id": "deepseek-harness-v144-bounded-command-scan-v1",
            "scanner_all_five_tasks_required": True,
            "archive_import_all_five_explicit": True,
            "verifier_control_diagnostics_all_five_passed": True,
            "requires_independent_v145_audit": True,
            "v142_volume_inspected": False,
            "v142_volume_mutated": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v144 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V142_BASELINE["_scaffold_contract"](manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("requires_independent_v143_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v144_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v142_manifest_hash": manifest.v142_manifest_hash,
            "v142_report_hash": manifest.v142_report_hash,
            "v143_audit_merge": manifest.v143_audit_merge,
            "v143_post_merge_main_run_id": manifest.v143_post_merge_main_run_id,
            "scanner_policy_id": manifest.scanner_policy_id,
            "command_image_probe_control_policy": "explicit-bounded-content-free-v1",
            "command_image_probe_control_timeout_seconds": (
                manifest.command_image_probe_control_timeout_seconds
            ),
            "command_image_probe_stage_metadata_required": True,
            "command_image_probe_raw_output_allowed": False,
            "command_image_probe_nonempty_output_hashing_allowed": False,
            "docker_cli_explicit_binding": True,
            "v142_volume_inspected": False,
            "v142_volume_mutated": False,
            "requires_independent_v145_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = _V142_BASELINE["_require_clean_merged_main"](manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v143_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v144 requires clean merged origin/main after v143")
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
