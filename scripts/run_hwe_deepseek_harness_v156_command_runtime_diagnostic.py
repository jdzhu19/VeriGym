#!/usr/bin/env python3
"""Diagnose the v154 nested-Docker command runtime without provider access."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
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

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v138_fresh_explicit_scaffold as v138,
)
from scripts import run_hwe_deepseek_harness_v136_command_runtime_diagnostic as v136  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV156CommandRuntimeDiagnosticManifest,
    load_v154_official_matrix_manifest,
    load_v156_command_runtime_diagnostic_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v156-command-runtime-diagnostic-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V156_COMMAND_RUNTIME_DIAGNOSTIC"
CHILD_BOUNDARY_ENV = "VERIGYM_DEEPSEEK_HARNESS_V156_ZERO_PROVIDER_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v156_command_runtime_diagnostic_v1.json"
)
V154_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v154_official_matrix_v1.json"
)
V154_RUNNER = _REPOSITORY / "scripts/collect_hwe_deepseek_harness_v154_official_matrix.py"
V154_LAUNCHER = _REPOSITORY / "scripts/launch_hwe_deepseek_harness_v154_official_matrix.py"
V154_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-05_deepseek-harness-v154-official-matrix-authorization.md"
)
V155_AUDIT = _REPOSITORY / "docs/audits/2026-09-05_deepseek-harness-v155-v154-result.md"
V154_ROOT = Path("/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v154-official-matrix-v1")
V154_REPORT = V154_ROOT / "matrix-report.json"
V154_ATTEMPT = V154_ROOT / "attempts/pr-465.json"
V154_CLEANUP = V154_ROOT / "dind-cleanup-receipt.json"
V148_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1"
)
V148_COMMAND_LOCK = V148_ROOT / "image-locks/pr-465.json"
V148_SECURITY_SCAN = V148_ROOT / "security-scans/pr-465.json"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v156-command-runtime-diagnostic-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v156")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
RUNTIME_SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v156-runtime")
_DAEMON_NAME = "verigym-dind-v156-command-runtime"
_CLEANUP_NAME = "verigym-dind-v156-cleanup"
_DOCKER_ENDPOINT_ENV_NAMES = ("DOCKER_CONTEXT", "DOCKER_HOST")
_CLOSED_FLAGS = (
    "formal_collection_allowed",
    "formal_collection_started",
    "collection_started",
    "training_started",
    "production_training_ready",
)
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v154_official_matrix_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v156_command_runtime_diagnostic_v1.json",
    "docs/audits/2026-09-05_deepseek-harness-v154-official-matrix-authorization.md",
    "docs/audits/2026-09-05_deepseek-harness-v155-v154-result.md",
    "integrations/verigym-deepseek-harness/tests/test_v156_command_runtime_diagnostic.py",
    "scripts/collect_hwe_deepseek_harness_v154_official_matrix.py",
    "scripts/launch_hwe_deepseek_harness_v154_official_matrix.py",
    "scripts/launch_hwe_deepseek_harness_v156_command_runtime_diagnostic.py",
    "scripts/run_hwe_deepseek_harness_v156_command_runtime_diagnostic.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)

_BASE_V136_VALIDATE = v136._validate_static_predecessors  # noqa: SLF001
_BASE_V136_TRANSFER = v136._transfer_workspace_runtime  # noqa: SLF001
_BASE_V136_DIAGNOSE_BINDING = v136._diagnose_runtime_binding  # noqa: SLF001
_BASE_V130_CLEANUP = v136.v130._cleanup  # noqa: SLF001
_V136_COMMAND_LOCK = v136.V132_COMMAND_LOCK
_V136_SECURITY_SCAN = v136.V132_SECURITY_SCAN


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ConfigurationError("v156 immutable JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v156 immutable JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v156 immutable JSON must be an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v156 immutable canonical hash changed")
    return observed


def _git_text(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_execution_boundary(arguments: argparse.Namespace) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(CHILD_BOUNDARY_ENV) != "1":
        raise ConfigurationError("v156 requires its one-use zero-provider child boundary")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v156 requires a non-root host identity")
    blocked = (*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, *_DOCKER_ENDPOINT_ENV_NAMES)
    if any(name in os.environ for name in blocked):
        raise ConfigurationError("v156 zero-provider child environment is contaminated")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v156 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v156 requires its positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV156CommandRuntimeDiagnosticManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git_text("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v156 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v155_audit_merge, head],
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    if (
        branch != "main"
        or head != upstream
        or len(head) != 40
        or ancestor.returncode != 0
        or ancestor.stdout
        or ancestor.stderr
    ):
        raise ConfigurationError("v156 requires clean merged origin/main after v155")
    return head


def _validate_static_predecessors(
    manifest: DeepSeekHarnessV156CommandRuntimeDiagnosticManifest,
) -> tuple[dict[str, Any], Any, Any]:
    current_lock = v136.V132_COMMAND_LOCK
    current_scan = v136.V132_SECURITY_SCAN
    try:
        v136.V132_COMMAND_LOCK = _V136_COMMAND_LOCK
        v136.V132_SECURITY_SCAN = _V136_SECURITY_SCAN
        predecessor, task, source_lock = _BASE_V136_VALIDATE(manifest)
    finally:
        v136.V132_COMMAND_LOCK = current_lock
        v136.V132_SECURITY_SCAN = current_scan

    v154_manifest = load_v154_official_matrix_manifest(V154_MANIFEST)
    v154_report = _load_json(V154_REPORT)
    v154_attempt = _load_json(V154_ATTEMPT)
    v154_cleanup = _load_json(V154_CLEANUP)
    v148_lock = HweCommandImageLock.model_validate_json(V148_COMMAND_LOCK.read_bytes())
    v148_scan = _load_json(V148_SECURITY_SCAN)
    state = v154_report.get("matrix_state")
    state_attempts = state.get("attempts") if isinstance(state, dict) else None
    state_attempt = (
        state_attempts[0]
        if isinstance(state_attempts, list)
        and len(state_attempts) == 1
        and isinstance(state_attempts[0], dict)
        else None
    )
    if (
        _hash_file(V154_MANIFEST) != manifest.v154_manifest_sha256
        or v154_manifest.manifest_hash != manifest.v154_manifest_hash
        or _hash_file(V154_RUNNER) != manifest.v154_runner_sha256
        or _hash_file(V154_LAUNCHER) != manifest.v154_launcher_sha256
        or _hash_file(V154_AUTHORIZATION) != manifest.v154_authorization_sha256
        or _hash_file(V154_REPORT) != manifest.v154_report_sha256
        or _canonical_hash(v154_report, "report_hash") != manifest.v154_report_hash
        or _hash_file(V154_ATTEMPT) != manifest.v154_attempt_sha256
        or _canonical_hash(v154_attempt, "attempt_hash") != manifest.v154_attempt_hash
        or _hash_file(V154_CLEANUP) != manifest.v154_cleanup_sha256
        or _canonical_hash(v154_cleanup, "receipt_hash") != manifest.v154_cleanup_hash
        or _hash_file(V155_AUDIT) != manifest.v155_audit_sha256
        or _hash_file(V148_COMMAND_LOCK) != manifest.v148_command_lock_sha256
        or v148_lock.lock_hash != manifest.v148_command_lock_hash
        or v148_lock.derived_command_image_id != manifest.v148_command_image_id
        or _hash_file(V148_SECURITY_SCAN) != manifest.v148_security_scan_sha256
        or v148_scan.get("security_scan_id") != manifest.v148_security_scan_id
        or v148_lock.security_scan_id != manifest.v148_security_scan_id
        or task.task_id != manifest.task_id
        or task.official_verifier_image != manifest.official_verifier_image
    ):
        raise ConfigurationError("v156 static predecessor or image binding changed")
    if (
        v154_report.get("status") != "stopped_pending_independent_v155_audit"
        or v154_report.get("stop_reason") != "pre_provider_infrastructure_failure"
        or v154_report.get("exception_type") != "DockerImageError"
        or v154_report.get("provider_episode_count") != 0
        or v154_report.get("provider_call_count") != 0
        or v154_report.get("provider_total_tokens") != 0
        or v154_report.get("v148_data_volume_reopen_count") != 1
        or v154_report.get("dind_cleanup_confirmed") is not True
        or any(v154_report.get(name) is not False for name in _CLOSED_FLAGS)
        or v154_attempt.get("provider_marker") != "not_started"
        or v154_attempt.get("provider_call_count") != 0
        or v154_attempt.get("provider_total_tokens") != 0
        or v154_attempt.get("first_effective_modification_action") is not None
        or not isinstance(state_attempt, dict)
        or state_attempt.get("provider_consumed") is not False
        or v154_cleanup.get("cleanup_confirmed") is not True
        or manifest.v148_volume_inspection_allowed is not False
        or manifest.v148_volume_mutation_allowed is not False
        or manifest.explicit_archive_import_required is not True
        or manifest.structured_subreason_required is not True
    ):
        raise ConfigurationError("v156 requires the exact audited v154 terminal state")
    base = copy.deepcopy(predecessor)
    base.pop("receipt_hash", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v156_predecessor_preflight_v1",
            "identity": IDENTITY,
            "v154_manifest_hash": v154_manifest.manifest_hash,
            "v154_report_hash": v154_report["report_hash"],
            "v154_attempt_hash": v154_attempt["attempt_hash"],
            "v154_cleanup_hash": v154_cleanup["receipt_hash"],
            "v155_audit_merge": manifest.v155_audit_merge,
            "v155_post_merge_main_run_id": manifest.v155_post_merge_main_run_id,
            "v148_command_lock_hash": v148_lock.lock_hash,
            "v148_security_scan_id": v148_scan["security_scan_id"],
            "v154_provider_consumed": False,
            "v148_reopen_budget_consumed": True,
            "v148_volume_inspected": False,
            "v148_volume_mutated": False,
        }
    )
    return {**base, "receipt_hash": content_hash(base)}, task, source_lock


def _reseal(value: Mapping[str, Any], *, field: str, format_id: str) -> dict[str, Any]:
    base = copy.deepcopy(dict(value))
    base.pop(field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, field: content_hash(base)}


def _transfer_workspace_runtime(
    manifest: DeepSeekHarnessV156CommandRuntimeDiagnosticManifest,
) -> dict[str, Any]:
    return _reseal(
        _BASE_V136_TRANSFER(manifest),
        field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v156_workspace_runtime_transfer_v1",
    )


def _diagnose_runtime_binding(
    manifest: DeepSeekHarnessV156CommandRuntimeDiagnosticManifest,
    lock: HweCommandImageLock,
) -> dict[str, Any]:
    value = _BASE_V136_DIAGNOSE_BINDING(manifest, lock)
    value.update(
        {
            "v154_failure_class": "DockerImageError",
            "v154_missing_subreason_recovered": value.get("status") == "confirmed",
            "ambient_docker_host_inheritance_used": False,
            "explicit_nested_docker_engine_used": True,
            "v148_volume_inspected": False,
            "v148_volume_mutated": False,
        }
    )
    return _reseal(
        value,
        field="diagnostic_hash",
        format_id="verigym_deepseek_harness_hwe_v156_command_runtime_diagnostic_v1",
    )


def _base_report(
    manifest: DeepSeekHarnessV156CommandRuntimeDiagnosticManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v156_command_runtime_report_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "stop_reason": None,
        "diagnosis_confirmed": False,
        "diagnosis": None,
        "docker_image_subreason": None,
        "explicit_nested_engine_probe_passed": False,
        "predecessor_preflight_hash": None,
        "archive_receipt_hash": None,
        "workspace_runtime_transfer_hash": None,
        "command_image_lock_hash": None,
        "security_scan_id": None,
        "diagnostic_hash": None,
        "cleanup_receipt_hash": None,
        "cleanup_confirmed": False,
        "startup_attempt_count": 0,
        "task_archive_read": False,
        "task_image_imported": False,
        "command_image_built": False,
        "task_execution_started": False,
        "base_reference_verification_started": False,
        "harness_controller_started": False,
        "registry_accessed": False,
        "partial_archive_used": False,
        "v148_volume_inspected": False,
        "v148_volume_mutated": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "raw_exception_persisted": False,
        "raw_exception_hashed": False,
        "requires_independent_v157_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }


def _write_report(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(report)
    base.pop("report_hash", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v156_command_runtime_report_v1",
            "identity": IDENTITY,
        }
    )
    value = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(root / "command-runtime-progress.json", value)
    atomic_dump_json(root / "command-runtime-report.json", value)
    return value


def _cleanup(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _reseal(
        _BASE_V130_CLEANUP(*args, **kwargs),
        field="receipt_hash",
        format_id="verigym_deepseek_harness_hwe_v156_cleanup_v1",
    )


def _load_completed_archive(task: Any, *, archive_root: Path) -> None:
    previous_identity = v138.IDENTITY
    previous_socket = v138.DIND_SOCKET_BACKING
    try:
        v138.IDENTITY = IDENTITY
        v138.DIND_SOCKET_BACKING = DIND_SOCKET_BACKING
        manifest = load_v156_command_runtime_diagnostic_manifest(MANIFEST)
        v138._explicit_archive_import(  # noqa: SLF001
            task,
            archive_root=archive_root,
            root=OUTPUT_ROOT,
            manifest=manifest,
        )
    finally:
        v138.IDENTITY = previous_identity
        v138.DIND_SOCKET_BACKING = previous_socket
    path = OUTPUT_ROOT / "archive-import-diagnostics/pr-465.json"
    atomic_dump_json(
        path,
        _reseal(
            _load_json(path),
            field="diagnostic_hash",
            format_id="verigym_deepseek_harness_hwe_v156_archive_import_diagnostic_v1",
        ),
    )


@contextlib.contextmanager
def _v156_bindings() -> Iterator[None]:
    replacements: dict[str, Any] = {
        "IDENTITY": IDENTITY,
        "OPT_IN_ENV": OPT_IN_ENV,
        "MANIFEST": MANIFEST,
        "V132_COMMAND_LOCK": V148_COMMAND_LOCK,
        "V132_SECURITY_SCAN": V148_SECURITY_SCAN,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "DIND_PARENT": DIND_PARENT,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
        "RUNTIME_SCRATCH": RUNTIME_SCRATCH,
        "_DAEMON_NAME": _DAEMON_NAME,
        "_CLEANUP_NAME": _CLEANUP_NAME,
        "_REQUIRED_MERGED_PATHS": _REQUIRED_MERGED_PATHS,
        "load_v136_command_runtime_diagnostic_manifest": (
            load_v156_command_runtime_diagnostic_manifest
        ),
        "_require_execution_boundary": _require_execution_boundary,
        "_require_clean_merged_main": _require_clean_merged_main,
        "_validate_static_predecessors": _validate_static_predecessors,
        "_transfer_workspace_runtime": _transfer_workspace_runtime,
        "_diagnose_runtime_binding": _diagnose_runtime_binding,
        "_base_report": _base_report,
        "_write_report": _write_report,
    }
    previous = {name: getattr(v136, name) for name in replacements}
    previous_load = v136.v130.v69._load_completed_archive  # noqa: SLF001
    previous_cleanup = v136.v130._cleanup  # noqa: SLF001
    try:
        for name, value in replacements.items():
            setattr(v136, name, value)
        v136.v130.v69._load_completed_archive = _load_completed_archive  # noqa: SLF001
        v136.v130._cleanup = _cleanup  # noqa: SLF001
        yield
    finally:
        v136.v130._cleanup = previous_cleanup  # noqa: SLF001
        v136.v130.v69._load_completed_archive = previous_load  # noqa: SLF001
        for name, value in previous.items():
            setattr(v136, name, value)


def diagnose(arguments: argparse.Namespace) -> dict[str, Any]:
    with _v156_bindings():
        report = v136.diagnose(arguments)
    report["requires_independent_v157_audit"] = True
    report.pop("requires_independent_v137_audit", None)
    if report.get("status") == "diagnosed_pending_independent_v137_audit":
        report["status"] = "diagnosed_pending_independent_v157_audit"
    return _write_report(OUTPUT_ROOT, report)


def main(argv: Sequence[str] | None = None) -> int:
    report = diagnose(_parser().parse_args(argv))
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnosis": report["diagnosis"],
                "docker_image_subreason": report["docker_image_subreason"],
                "explicit_nested_engine_probe_passed": report[
                    "explicit_nested_engine_probe_passed"
                ],
                "cleanup_confirmed": report["cleanup_confirmed"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return (
        0
        if report["status"] == "diagnosed_pending_independent_v157_audit"
        and report["diagnosis_confirmed"] is True
        and report["cleanup_confirmed"] is True
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
