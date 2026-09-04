#!/usr/bin/env python3
"""Materialize five tasks with a bounded, content-free socket-cleanup controller."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import secrets
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
    materialize_hwe_deepseek_harness_v140_verifier_control_scaffold as v140,
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
    load_v140_verifier_control_scaffold_manifest,
    load_v142_cleanup_control_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

v138 = v140.v138
v132 = v140.v132
v127 = v140.v127
v94 = v140.v94
v69 = v140.v69
dind = v94.dind

IDENTITY = "deepseek-harness-hwe-v142-cleanup-control-scaffold-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V142_CLEANUP_CONTROL_SCAFFOLD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v142_cleanup_control_scaffold_v1.json"
)
V140_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v140_verifier_control_scaffold_v1.json"
)
V140_RUNNER = _REPOSITORY / (
    "scripts/materialize_hwe_deepseek_harness_v140_verifier_control_scaffold.py"
)
V140_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v140-verifier-control-scaffold-authorization.md"
)
V141_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v141-v140-result.md"
V140_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v140-verifier-control-scaffold-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v142-cleanup-control-scaffold-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v142")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v142-control")
RUNTIME_TMP = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v142-runtime")
_TASK_PR_NUMBERS = frozenset({465, 1135, 1780, 2017, 2711})
_DOCKER_CONTROL_TIMEOUT_SECONDS = 300
_OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS = 900
_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS = 300

_REQUIRED_MERGED_PATHS = (
    *v140._REQUIRED_MERGED_PATHS,  # noqa: SLF001
    "docs/audits/2026-09-05_deepseek-harness-v141-v140-result.md",
    "configs/training/qwen35_hwe_deepseek_harness_v142_cleanup_control_scaffold_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v142-cleanup-control-scaffold-authorization.md",
    "scripts/materialize_hwe_deepseek_harness_v142_cleanup_control_scaffold.py",
    "integrations/verigym-deepseek-harness/tests/test_v142_cleanup_control_scaffold.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
    "SECURITY.md",
)

_V140_NAMES = (
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
    "_v140_materialize_task",
    "_materialize_tasks",
    "_scaffold_contract",
    "_require_clean_merged_main",
)
_V140_BASELINE = {name: getattr(v140, name) for name in _V140_NAMES}


def _parser() -> argparse.ArgumentParser:
    parser = v140._parser()  # noqa: SLF001
    parser.description = __doc__
    parser.set_defaults(manifest=MANIFEST, output=OUTPUT_ROOT)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the fresh five-task provider-free cleanup-control workflow."""

    with _v142_configuration():
        return v140.materialize(arguments)


@contextlib.contextmanager
def _v142_configuration() -> Iterator[None]:
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
        "_v140_materialize_task": _v142_materialize_task,
        "_materialize_tasks": _materialize_tasks,
        "_scaffold_contract": _scaffold_contract,
        "_require_clean_merged_main": _require_clean_merged_main,
    }
    previous = {name: getattr(v140, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(v140, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v140, name, value)


@contextlib.contextmanager
def _v140_baseline() -> Iterator[None]:
    current = {name: getattr(v140, name) for name in _V140_BASELINE}
    try:
        for name, value in _V140_BASELINE.items():
            setattr(v140, name, value)
        yield
    finally:
        for name, value in current.items():
            setattr(v140, name, value)


def _load_composed_manifest(path: Path) -> Any:
    purpose = load_v142_cleanup_control_scaffold_manifest(path)
    with _v140_baseline():
        predecessor = _V140_BASELINE["_load_composed_manifest"](V140_MANIFEST)
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
        raise ConfigurationError("v142 progress must remain a mutable object")
    value.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v142_scaffold_progress_v1",
            "identity": IDENTITY,
            "v140_manifest_hash": (
                "ccd0e7927fde7d72ca0638bf5081b994d30a505e5e28c2ad869791f6ae1e236c"
            ),
            "v140_report_hash": (
                "30064d0bbd8332dc30c4908c2f42cc8addd6e204243f12686283d1e8bca192f9"
            ),
            "v141_audit_merge": "9a9713cfab4247f783fd8fc841ee46c5d0347bf6",
            "archive_import_policy": "explicit-endpoint-stage-diagnostic-v1",
            "verifier_control_policy": "separate-cold-vfs-control-bound-v1",
            "socket_cleanup_control_policy": "bounded-content-free-stage-diagnostic-v1",
            "verifier_docker_control_timeout_seconds": _DOCKER_CONTROL_TIMEOUT_SECONDS,
            "official_verifier_test_timeout_seconds": _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS,
            "socket_cleanup_control_timeout_seconds": (_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS),
            "nested_docker_host": f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}",
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
            "v140_volume_inspected": False,
            "v140_volume_mutated": False,
        }
    )
    if value.get("status") in v127._SUCCESS_STATUS_NAMES:  # noqa: SLF001
        value["status"] = "completed_pending_independent_v143_audit"
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
    value = _V140_BASELINE["_transfer_images"](
        dind_name, manifest, host_images=host_images, root=root
    )
    receipts: list[dict[str, Any]] = []
    for path in sorted((root / "transfer-receipts").glob("*.json")):
        receipt = _reseal(
            v94._load_json(path),  # noqa: SLF001
            hash_field="receipt_hash",
            format_id="verigym_deepseek_harness_hwe_v142_image_transfer_receipt_v1",
        )
        atomic_dump_json(path, receipt)
        receipts.append(receipt)
    if len(receipts) != 2:
        raise ConfigurationError("v142 image transfer receipt inventory is not exactly two")
    value.update(
        {
            "ordered_receipt_hashes": [item["receipt_hash"] for item in receipts],
            "controller_receipt_hash": receipts[0]["receipt_hash"],
            "workspace_runtime_receipt_hash": receipts[1]["receipt_hash"],
            "v140_failure_audited": True,
        }
    )
    result = _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v142_image_transfer_set_v1",
    )
    atomic_dump_json(root / "image-transfer-set.json", result)
    return result


def _runtime_prepare_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V140_BASELINE["_runtime_prepare_preflight"](*args, **kwargs)
    value.update(
        {
            "socket_cleanup_control_timeout_seconds": (_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS),
            "v140_volume_inspected": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v142_runtime_prepare_preflight_v1",
    )


def _harness_initialize_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V140_BASELINE["_harness_initialize_preflight"](*args, **kwargs)
    value.update({"v141_audit_merge": "9a9713cfab4247f783fd8fc841ee46c5d0347bf6"})
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v142_harness_initialize_preflight_v1",
    )


def _inventory(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _V140_BASELINE["_inventory"](*args, **kwargs),
        hash_field="inventory_hash",
        format_id="verigym_deepseek_harness_hwe_v142_execution_inventory_v1",
    )


def _runtime_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V140_BASELINE["_runtime_receipt"](*args, **kwargs)
    value.update(
        {
            "scanner_policy_id": "deepseek-harness-v142-bounded-command-scan-v1",
            "v140_volume_inspected": False,
            "v140_volume_mutated": False,
        }
    )
    return _reseal(
        value,
        hash_field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v142_dind_runtime_receipt_v1",
    )


def _cleanup_metric(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
    }


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
        "format_id": "verigym_deepseek_harness_hwe_v142_socket_cleanup_diagnostic_v1",
        "identity": IDENTITY,
        "attempt": attempt,
        "status": status,
        "category": category,
        "socket_cleanup_control_timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        "stages": dict(stages),
        "raw_output_persisted": False,
        "nonempty_output_hashed": False,
        "raw_exception_persisted": False,
        "v140_volume_inspected": False,
        "v140_volume_mutated": False,
        "provider_calls": 0,
    }
    result = {**base, "diagnostic_hash": content_hash(base)}
    atomic_dump_json(directory / f"attempt-{attempt}.json", result)
    return result


def _remove_cleanup_helper(name: str, stages: dict[str, Any]) -> None:
    try:
        result = dind._run(  # noqa: SLF001
            ["docker", "rm", "--force", name],
            timeout_s=_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        stages["helper_remove"] = {
            "status": "timeout",
            "timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        }
        return
    stages["helper_remove"] = _cleanup_metric(result)


def _clean_socket_volume(manifest: Any, *, root: Path) -> dict[str, Any]:
    if (
        manifest.socket_cleanup_control_timeout_seconds != _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS
        or manifest.socket_cleanup_stage_metadata_required is not True
        or manifest.socket_cleanup_raw_output_allowed is not False
        or manifest.dind_socket_volume != "verigym-deepseek-harness-v142-dind-socket"
        or Path(manifest.dind_socket_backing) != DIND_SOCKET_BACKING
    ):
        raise ConfigurationError("v142 socket cleanup policy changed")
    dind._bind_backed_volume(  # noqa: SLF001
        manifest.dind_socket_volume,
        owner=IDENTITY,
        role="socket",
        backing=DIND_SOCKET_BACKING,
    )
    name = f"verigym-dind-v142-socket-cleanup-{secrets.token_hex(10)}"
    script = (
        "rm -rf -- "
        + " ".join(v94._CLEANUP_PATHS)  # noqa: SLF001
        + f"; chown {os.getuid()}:{os.getgid()} /verigym-socket"
        + "; chmod 0700 /verigym-socket"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        f"verigym.owner={IDENTITY}",
        "--label",
        "verigym.role=socket_cleanup",
        "--network",
        "none",
        "--read-only",
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "FOWNER",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.25",
        "--volume",
        f"{manifest.dind_socket_volume}:/verigym-socket:rw",
        "--entrypoint",
        "/bin/sh",
        manifest.dind_image_id,
        "-euc",
        script,
    ]
    stages: dict[str, Any] = {
        "volume_binding": {
            "status": "passed",
            "timeout_seconds": 30,
            "exact_owned_bind_backed_volume": True,
        }
    }
    try:
        completed = dind._run(  # noqa: SLF001
            command,
            timeout_s=_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stages["cleanup_helper"] = {
            "status": "timeout",
            "timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        }
        _remove_cleanup_helper(name, stages)
        _write_cleanup_diagnostic(
            root, status="failed", category="cleanup_helper_timeout", stages=stages
        )
        raise ConfigurationError("v142 socket cleanup helper timed out") from exc
    stages["cleanup_helper"] = _cleanup_metric(completed)
    if (
        completed.returncode != 0
        or len(completed.stdout) > v94.MAX_TRANSFER_OUTPUT_BYTES
        or len(completed.stderr) > v94.MAX_TRANSFER_OUTPUT_BYTES
    ):
        _remove_cleanup_helper(name, stages)
        _write_cleanup_diagnostic(
            root, status="failed", category="cleanup_helper_failed", stages=stages
        )
        raise ConfigurationError("v142 socket cleanup helper failed")
    try:
        removed = dind._run(  # noqa: SLF001
            ["docker", "volume", "rm", manifest.dind_socket_volume],
            timeout_s=_SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stages["volume_remove"] = {
            "status": "timeout",
            "timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        }
        _write_cleanup_diagnostic(
            root, status="failed", category="socket_volume_remove_timeout", stages=stages
        )
        raise ConfigurationError("v142 socket volume removal timed out") from exc
    stages["volume_remove"] = _cleanup_metric(removed)
    if removed.returncode != 0:
        _write_cleanup_diagnostic(
            root, status="failed", category="socket_volume_remove_failed", stages=stages
        )
        raise ConfigurationError("v142 socket volume removal failed")
    metadata = DIND_SOCKET_BACKING.stat()
    if (
        next(DIND_SOCKET_BACKING.iterdir(), None) is not None
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_gid != os.getgid()
    ):
        stages["backing_confirmation"] = {"status": "failed"}
        _write_cleanup_diagnostic(
            root, status="failed", category="socket_backing_not_restored", stages=stages
        )
        raise ConfigurationError("v142 socket backing cleanup was not confirmed")
    stages["backing_confirmation"] = {
        "status": "passed",
        "empty": True,
        "mode": "0700",
        "owner_restored": True,
    }
    diagnostic = _write_cleanup_diagnostic(
        root, status="passed", category="socket_cleanup_complete", stages=stages
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v142_socket_cleanup_receipt_v1",
        "identity": IDENTITY,
        "socket_volume_removed": True,
        "socket_backing_empty": True,
        "socket_backing_mode": "0700",
        "socket_backing_owner_restored": True,
        "socket_cleanup_control_timeout_seconds": _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS,
        "cleanup_stdout_bytes": len(completed.stdout),
        "cleanup_stderr_bytes": len(completed.stderr),
        "raw_cleanup_output_persisted": False,
        "nonempty_output_hashed": False,
        "cleanup_diagnostic_hash": diagnostic["diagnostic_hash"],
        "failed_data_volume_policy": "freeze-exact-owned-volume",
        "v140_volume_inspected": False,
        "v140_volume_mutated": False,
    }
    result = {**base, "receipt_hash": content_hash(base)}
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
        raise ConfigurationError("v142 predecessor canonical hash changed")
    return observed


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError("v142 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v142 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v142 predecessor JSON must be an object")
    return value


def _validate_static_bindings(
    manifest: Any,
    v92_manifest: DeepSeekHarnessV92OfficialMatrixManifest,
    v92_report: Mapping[str, Any],
    *,
    v92_manifest_path: Path,
    v92_report_path: Path,
) -> None:
    purpose = load_v142_cleanup_control_scaffold_manifest(MANIFEST)
    with _v140_baseline():
        predecessor = _V140_BASELINE["_load_composed_manifest"](V140_MANIFEST)
        _V140_BASELINE["_validate_static_bindings"](
            predecessor,
            v92_manifest,
            v92_report,
            v92_manifest_path=v92_manifest_path,
            v92_report_path=v92_report_path,
        )
    v140_purpose = load_v140_verifier_control_scaffold_manifest(V140_MANIFEST)
    report_path = V140_ROOT / "execution-scaffold-report.json"
    task_path = V140_ROOT / "task-materialization-set.json"
    runtime_path = V140_ROOT / "preflight/runtime-prepare.json"
    harness_path = V140_ROOT / "preflight/harness-initialize.json"
    late_cleanup_path = V140_ROOT / "late-cleanup-receipt.json"
    report = _load_json(report_path)
    task = _load_json(task_path)
    runtime = _load_json(runtime_path)
    harness = _load_json(harness_path)
    late_cleanup = _load_json(late_cleanup_path)
    if (
        _hash_file(V140_MANIFEST) != purpose.v140_manifest_sha256
        or v140_purpose.manifest_hash != purpose.v140_manifest_hash
        or _hash_file(V140_RUNNER) != purpose.v140_runner_sha256
        or _hash_file(V140_AUTHORIZATION) != purpose.v140_authorization_sha256
        or _hash_file(report_path) != purpose.v140_report_sha256
        or _canonical_hash(report, "report_hash") != purpose.v140_report_hash
        or _hash_file(task_path) != purpose.v140_task_materialization_sha256
        or _canonical_hash(task, "receipt_hash") != purpose.v140_task_materialization_hash
        or _hash_file(runtime_path) != purpose.v140_runtime_prepare_sha256
        or _canonical_hash(runtime, "receipt_hash") != purpose.v140_runtime_prepare_hash
        or _hash_file(harness_path) != purpose.v140_harness_initialize_sha256
        or _canonical_hash(harness, "receipt_hash") != purpose.v140_harness_initialize_hash
        or _hash_file(late_cleanup_path) != purpose.v140_late_cleanup_sha256
        or _canonical_hash(late_cleanup, "receipt_hash") != purpose.v140_late_cleanup_hash
        or _hash_file(V141_AUDIT) != purpose.v141_audit_sha256
        or manifest.schedule != v92_manifest.schedule
        or [item.task_id for item in manifest.schedule] != purpose.schedule_task_ids
        or manifest.seed != purpose.seed
        or manifest.sample_index != purpose.sample_index
        or manifest.manifest_hash != purpose.manifest_hash
    ):
        raise ConfigurationError("v142 predecessor evidence or immutable schedule changed")
    if (
        report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "TimeoutExpired"
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("provider_execution_scaffold_published") is not False
        or task.get("verifier_control_diagnostics_all_five_passed") is not True
        or len(task.get("task_receipts", [])) != 5
        or runtime.get("status") != "passed"
        or runtime.get("task_count") != 5
        or harness.get("status") != "passed"
        or late_cleanup.get("socket_volume_removed") is not True
        or purpose.dind_data_backing != str(DIND_DATA_BACKING)
        or purpose.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or purpose.control_headroom_root != str(CONTROL_ROOT)
        or purpose.runtime_scratch_root != str(RUNTIME_TMP)
        or purpose.output_root != str(OUTPUT_ROOT)
        or purpose.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or purpose.dind_owner != IDENTITY
        or purpose.verifier_docker_control_timeout_seconds != _DOCKER_CONTROL_TIMEOUT_SECONDS
        or purpose.official_verifier_test_timeout_seconds != _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS
        or purpose.socket_cleanup_control_timeout_seconds != _SOCKET_CLEANUP_CONTROL_TIMEOUT_SECONDS
        or purpose.socket_cleanup_stage_metadata_required is not True
        or purpose.socket_cleanup_raw_output_allowed is not False
        or purpose.v140_volume_inspection_allowed is not False
        or purpose.v140_volume_mutation_allowed is not False
        or purpose.provider_successor_identity != "deepseek-harness-hwe-v144-official-matrix-v1"
        or purpose.requires_independent_v143_audit is not True
        or any(getattr(purpose, name) is not False for name in v94._closed_training_flags())  # noqa: SLF001
    ):
        raise ConfigurationError("v142 purpose or audited v140 terminal state changed")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", purpose.v141_audit_merge, "HEAD"],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v142 requires the independent v141 audit merged")


def _bounded_scan_and_lock(**kwargs: Any) -> Any:
    if "runtime_policy" in kwargs:
        raise ConfigurationError("v142 refuses an externally supplied scanner policy")
    lock_path = kwargs.get("identity_lock_path")
    if not isinstance(lock_path, Path) or not lock_path.stem.startswith("pr-"):
        raise ConfigurationError("v142 scanner task identity is invalid")
    try:
        pr_number = int(lock_path.stem.removeprefix("pr-"))
    except ValueError as exc:
        raise ConfigurationError("v142 scanner task identity is invalid") from exc
    if pr_number not in _TASK_PR_NUMBERS:
        raise ConfigurationError("v142 scanner task is outside the frozen schedule")
    policy = CommandImageScanRuntimePolicy(
        policy_id="deepseek-harness-v142-bounded-command-scan-v1",
        create_timeout_seconds=300,
        inspect_timeout_seconds=60,
        start_timeout_seconds=180,
        remove_timeout_seconds=120,
        overall_timeout_seconds=720,
        container_name=f"verigym-hwe-v142-command-scan-pr-{pr_number}",
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
        raise ConfigurationError("v142 bounded command-image scan did not pass")
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
        "format_id": "verigym_deepseek_harness_hwe_v142_archive_import_diagnostic_v1",
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


def _v142_materialize_task(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("command_tag_version") != "v97" or not args:
        raise ConfigurationError("v142 refuses an unexpected task materialization call")
    task = args[0]
    root = kwargs.get("root")
    if not isinstance(task, HweOfflineTaskLock) or not isinstance(root, Path):
        raise ConfigurationError("v142 task materialization binding is invalid")
    manifest = _load_composed_manifest(MANIFEST)

    def load_completed_archive(bound: HweOfflineTaskLock, *, archive_root: Path) -> None:
        if bound != task:
            raise ConfigurationError("v142 archive import task binding changed")
        v138._explicit_archive_import(  # noqa: SLF001
            bound,
            archive_root=archive_root,
            root=root,
            manifest=manifest,
        )

    previous = v69._load_completed_archive  # noqa: SLF001
    try:
        v69._load_completed_archive = load_completed_archive  # noqa: SLF001
        kwargs["command_tag_version"] = "v142"
        value = v132._V127_BASE_MATERIALIZE_TASK(*args, **kwargs)  # noqa: SLF001
    finally:
        v69._load_completed_archive = previous  # noqa: SLF001
    diagnostic = v140._verifier_control_diagnostic(root, task)  # noqa: SLF001
    diagnostic = _reseal(
        diagnostic,
        hash_field="diagnostic_hash",
        format_id="verigym_deepseek_harness_hwe_v142_verifier_control_diagnostic_v1",
    )
    atomic_dump_json(
        root / "verifier-control-diagnostics" / f"pr-{task.pr_number}.json", diagnostic
    )
    base = copy.deepcopy(value)
    base.pop("task_receipt_hash", None)
    base.update(
        {
            "scanner_policy_id": "deepseek-harness-v142-bounded-command-scan-v1",
            "scanner_create_timeout_seconds": 300,
            "scanner_overall_timeout_seconds": 720,
            "archive_import_explicit_endpoint": True,
            "archive_import_stage_diagnostic": True,
            "verifier_docker_control_timeout_seconds": _DOCKER_CONTROL_TIMEOUT_SECONDS,
            "official_verifier_test_timeout_seconds": _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS,
            "verifier_control_diagnostic_hash": diagnostic["diagnostic_hash"],
            "v140_failure_audited": True,
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
        raise ConfigurationError("v142 refuses partial task materialization")
    for task_id, receipt in zip(expected, receipts, strict=True):
        if (
            not isinstance(receipt, dict)
            or receipt.get("task_id") != task_id
            or receipt.get("scanner_policy_id") != "deepseek-harness-v142-bounded-command-scan-v1"
            or receipt.get("archive_import_explicit_endpoint") is not True
            or receipt.get("verifier_docker_control_timeout_seconds")
            != _DOCKER_CONTROL_TIMEOUT_SECONDS
            or receipt.get("official_verifier_test_timeout_seconds")
            != _OFFICIAL_VERIFIER_TEST_TIMEOUT_SECONDS
        ):
            raise ConfigurationError("v142 task receipt is incomplete")
        receipt.pop("task_receipt_hash", None)
        receipt.pop("requires_independent_v133_audit", None)
        receipt.pop("requires_independent_v139_audit", None)
        receipt.pop("requires_independent_v141_audit", None)
        receipt.update(
            {
                "format_id": ("verigym_deepseek_harness_hwe_v142_task_materialization_receipt_v1"),
                "identity": IDENTITY,
                "requires_independent_v143_audit": True,
                "predecessor_volumes_inspected": False,
                "predecessor_volumes_mutated": False,
                "v132_volume_inspected": False,
                "v132_volume_mutated": False,
                "v138_volume_inspected": False,
                "v138_volume_mutated": False,
                "v140_volume_inspected": False,
                "v140_volume_mutated": False,
            }
        )
        receipt["task_receipt_hash"] = content_hash(receipt)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v142_task_materialization_set_v1",
            "identity": IDENTITY,
            "task_receipt_hashes": [item["task_receipt_hash"] for item in receipts],
            "scanner_policy_id": "deepseek-harness-v142-bounded-command-scan-v1",
            "scanner_all_five_tasks_required": True,
            "archive_import_all_five_explicit": True,
            "verifier_control_diagnostics_all_five_passed": True,
            "requires_independent_v143_audit": True,
            "predecessor_volumes_inspected": False,
            "predecessor_volumes_mutated": False,
            "v132_volume_inspected": False,
            "v132_volume_mutated": False,
            "v138_volume_inspected": False,
            "v138_volume_mutated": False,
            "v140_volume_inspected": False,
            "v140_volume_mutated": False,
        }
    )
    result = {**base, "receipt_hash": content_hash(base)}
    root = kwargs.get("root")
    if not isinstance(root, Path):
        raise ConfigurationError("v142 task materialization output root is missing")
    atomic_dump_json(root / "task-materialization-set.json", result)
    return result, locks


def _scaffold_contract(manifest: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V140_BASELINE["_scaffold_contract"](manifest, **kwargs)
    base = copy.deepcopy(value)
    base.pop("contract_hash", None)
    base.pop("requires_independent_v141_audit", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v142_execution_scaffold_contract_v1",
            "identity": IDENTITY,
            "v140_manifest_hash": manifest.v140_manifest_hash,
            "v140_report_hash": manifest.v140_report_hash,
            "v141_audit_merge": manifest.v141_audit_merge,
            "v141_post_merge_main_run_id": manifest.v141_post_merge_main_run_id,
            "scanner_policy_id": manifest.scanner_policy_id,
            "verifier_control_policy": "separate-cold-vfs-control-bound-v1",
            "socket_cleanup_control_policy": "bounded-content-free-stage-diagnostic-v1",
            "socket_cleanup_control_timeout_seconds": (
                manifest.socket_cleanup_control_timeout_seconds
            ),
            "socket_cleanup_stage_metadata_required": True,
            "socket_cleanup_raw_output_allowed": False,
            "docker_cli_explicit_binding": True,
            "v140_volume_inspected": False,
            "v140_volume_mutated": False,
            "requires_independent_v143_audit": True,
        }
    )
    return {**base, "contract_hash": content_hash(base)}


def _require_clean_merged_main(manifest: Any) -> str:
    head = _V140_BASELINE["_require_clean_merged_main"](manifest)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v141_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0 or ancestor.stdout or ancestor.stderr:
        raise ConfigurationError("v142 requires clean merged origin/main after v141")
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
