#!/usr/bin/env python3
"""Diagnose the v134 command-runtime Docker transport without a provider call."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
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

from scripts import collect_hwe_deepseek_harness_v134_official_matrix as v134  # noqa: E402
from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v130_bounded_command_scan_create_probe as v130,
)
from scripts import run_repository_rollout_dind_controller as dind  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
    inspect_offline_image_archive,
    load_v130_bounded_command_scan_probe_manifest,
    load_v134_official_matrix_manifest,
    load_v136_command_runtime_diagnostic_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock  # noqa: E402
from verigym.runtimes.docker.engine import DockerCliEngine  # noqa: E402
from verigym.runtimes.docker.errors import DockerImageError  # noqa: E402
from verigym.runtimes.docker.runtime import DockerRuntime  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v136-command-runtime-diagnostic-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V136_COMMAND_RUNTIME_DIAGNOSTIC"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v136_command_runtime_diagnostic_v1.json"
)
V130_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v130_bounded_command_scan_create_probe_v1.json"
)
V130_RUNNER = _REPOSITORY / (
    "scripts/run_hwe_deepseek_harness_v130_bounded_command_scan_create_probe.py"
)
V134_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v134_official_matrix_v1.json"
)
V134_RUNNER = _REPOSITORY / "scripts/collect_hwe_deepseek_harness_v134_official_matrix.py"
V135_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v135-v134-result.md"
V134_ROOT = Path("/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v134-official-matrix-v1")
V134_REPORT = V134_ROOT / "matrix-report.json"
V132_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"
)
V132_COMMAND_LOCK = V132_ROOT / "image-locks/pr-465.json"
V132_SECURITY_SCAN = V132_ROOT / "security-scans/pr-465.json"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v136-command-runtime-diagnostic-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v136")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
RUNTIME_SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v136-runtime")
ARCHIVE_ROOT = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
_DAEMON_NAME = "verigym-dind-v136-command-runtime"
_CLEANUP_NAME = "verigym-dind-v136-cleanup"
_CLOSED_FLAGS = (
    "formal_collection_allowed",
    "formal_collection_started",
    "collection_started",
    "training_started",
    "production_training_ready",
)
_ALLOWED_IMAGE_SUBREASONS = frozenset(
    {
        "agent_image_health_failed",
        "agent_image_identity_invalid",
        "agent_image_labels_invalid",
        "agent_user_mapping_invalid",
        "command_image_health_failed",
        "command_image_identity_invalid",
        "command_image_labels_invalid",
        "command_image_user_mapping_invalid",
        "image_environment_forbidden",
        "image_health_failed",
        "image_missing",
        "image_observation_cache_invalid",
        "image_probe_output_invalid",
        "invalid_image_id",
        "invalid_image_metadata",
        "invalid_runtime_user",
        "replay_image_mismatch",
        "role_image_identity_collision",
        "root_image_user",
        "root_runtime_user",
        "tool_version_unavailable",
    }
)
_MAX_TRANSFER_OUTPUT_BYTES = 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v130_bounded_command_scan_create_probe_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v134_official_matrix_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v136_command_runtime_diagnostic_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v135-v134-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v136-command-runtime-diagnostic-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v136_command_runtime_diagnostic.py",
    "scripts/collect_hwe_deepseek_harness_v134_official_matrix.py",
    "scripts/run_hwe_deepseek_harness_v130_bounded_command_scan_create_probe.py",
    "scripts/run_hwe_deepseek_harness_v136_command_runtime_diagnostic.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
)
_V130_PATCH_NAMES = (
    "IDENTITY",
    "OUTPUT_ROOT",
    "DIND_PARENT",
    "DIND_DATA_BACKING",
    "DIND_SOCKET_BACKING",
    "RUNTIME_SCRATCH",
    "_DAEMON_NAME",
    "_CLEANUP_NAME",
)


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
        raise ConfigurationError("v136 immutable JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v136 immutable JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v136 immutable JSON must be an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v136 immutable canonical hash changed")
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
    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v136 requires a non-root host identity")
    if any(name in os.environ for name in v130._PROVIDER_ENV_NAMES):  # noqa: SLF001
        raise ConfigurationError("v136 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v136 requires the default local Docker endpoint")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v136 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v136 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git_text("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v136 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v135_audit_merge, head],
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
        raise ConfigurationError("v136 requires clean merged origin/main after v135")
    return head


def _validate_static_predecessors(
    manifest: DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
) -> tuple[dict[str, Any], Any, Any]:
    v130_manifest = load_v130_bounded_command_scan_probe_manifest(V130_MANIFEST)
    v134_manifest = load_v134_official_matrix_manifest(V134_MANIFEST)
    v134_report = _load_json(V134_REPORT)
    v132_lock = HweCommandImageLock.model_validate_json(V132_COMMAND_LOCK.read_bytes())
    v132_scan = _load_json(V132_SECURITY_SCAN)
    v130_predecessor, source_lock = v130._validate_static_predecessor(  # noqa: SLF001
        v130_manifest
    )
    task = v130._task_lock(v130_manifest)  # noqa: SLF001
    attempts = v134_report.get("attempts")
    attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    matrix_state = v134_report.get("matrix_state")
    if (
        _hash_file(V130_MANIFEST) != manifest.v130_manifest_sha256
        or v130_manifest.manifest_hash != manifest.v130_manifest_hash
        or _hash_file(V130_RUNNER) != manifest.v130_runner_sha256
        or _hash_file(V134_MANIFEST) != manifest.v134_manifest_sha256
        or v134_manifest.manifest_hash != manifest.v134_manifest_hash
        or _hash_file(V134_RUNNER) != manifest.v134_runner_sha256
        or _hash_file(V134_REPORT) != manifest.v134_report_sha256
        or _canonical_hash(v134_report, "report_hash") != manifest.v134_report_hash
        or _hash_file(V135_AUDIT) != manifest.v135_audit_sha256
        or _hash_file(V132_COMMAND_LOCK) != manifest.v132_command_lock_sha256
        or v132_lock.lock_hash != manifest.v132_command_lock_hash
        or _hash_file(V132_SECURITY_SCAN) != manifest.v132_security_scan_sha256
        or v132_scan.get("security_scan_id") != manifest.v132_security_scan_id
        or v132_lock.derived_command_image_id != manifest.v132_command_image_id
        or task.task_id != manifest.task_id
        or task.archive_relpath != manifest.archive_relpath
        or task.archive_sha256_relpath != manifest.archive_sha256_relpath
        or task.archive_sha256 != manifest.archive_sha256
        or task.registry_digest_relpath != manifest.registry_digest_relpath
        or task.registry_manifest_digest != manifest.registry_manifest_digest
        or task.image_config_digest != manifest.image_config_digest
        or task.official_verifier_image != manifest.official_verifier_image
        or manifest.workspace_runtime_image_id != HWE_WORKSPACE_RUNTIME_IMAGE_ID
    ):
        raise ConfigurationError("v136 static predecessor or task binding changed")
    if (
        v134_report.get("status") != "stopped_pending_independent_v135_audit"
        or v134_report.get("stop_reason") != "pre_provider_infrastructure_failure"
        or v134_report.get("exception_type") != "DockerImageError"
        or v134_report.get("provider_episode_count") != 0
        or v134_report.get("provider_call_count") != 0
        or v134_report.get("provider_total_tokens") != 0
        or v134_report.get("v132_data_volume_reopen_count") != 1
        or any(v134_report.get(name) is not False for name in _CLOSED_FLAGS)
        or not isinstance(attempt, dict)
        or attempt.get("task_id") != manifest.task_id
        or attempt.get("provider_marker") != "not_started"
        or attempt.get("provider_call_count") != 0
        or attempt.get("provider_total_tokens") != 0
        or attempt.get("collection_started") is not False
        or not isinstance(matrix_state, dict)
        or any(
            item.get("provider_consumed") is not False
            for item in matrix_state.get("attempts", [])
            if isinstance(item, dict)
        )
    ):
        raise ConfigurationError("v136 requires the exact audited v134 terminal state")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v136_predecessor_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "v130_manifest_hash": v130_manifest.manifest_hash,
        "v130_predecessor_hash": v130_predecessor["receipt_hash"],
        "v134_manifest_hash": v134_manifest.manifest_hash,
        "v134_report_hash": v134_report["report_hash"],
        "v135_audit_commit": manifest.v135_audit_commit,
        "v135_audit_merge": manifest.v135_audit_merge,
        "v135_post_merge_main_run_id": manifest.v135_post_merge_main_run_id,
        "v132_command_lock_hash": v132_lock.lock_hash,
        "v132_security_scan_id": v132_scan["security_scan_id"],
        "all_five_tasks_provider_unconsumed": True,
        "v132_reopen_budget_consumed": True,
        "v132_volume_inspected": False,
        "v132_volume_mutated": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}, task, source_lock


@contextlib.contextmanager
def _v136_v130_configuration() -> Iterator[None]:
    replacements = {
        "IDENTITY": IDENTITY,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "DIND_PARENT": DIND_PARENT,
        "DIND_DATA_BACKING": DIND_DATA_BACKING,
        "DIND_SOCKET_BACKING": DIND_SOCKET_BACKING,
        "RUNTIME_SCRATCH": RUNTIME_SCRATCH,
        "_DAEMON_NAME": _DAEMON_NAME,
        "_CLEANUP_NAME": _CLEANUP_NAME,
    }
    previous = {name: getattr(v130, name) for name in _V130_PATCH_NAMES}
    try:
        for name, value in replacements.items():
            setattr(v130, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(v130, name, value)


@contextlib.contextmanager
def _nested_runtime_environment(
    manifest: DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
) -> Iterator[None]:
    socket_path = DIND_SOCKET_BACKING / "docker.sock"
    if manifest.nested_docker_host != f"unix://{socket_path}" or not socket_path.is_socket():
        raise ConfigurationError("v136 nested Docker socket is unavailable")
    previous = {
        "DOCKER_HOST": os.environ.get("DOCKER_HOST"),
        "DOCKER_CONTEXT": os.environ.get("DOCKER_CONTEXT"),
        "TMPDIR": os.environ.get("TMPDIR"),
    }
    previous_tempdir = tempfile.tempdir
    os.environ["DOCKER_HOST"] = manifest.nested_docker_host
    os.environ.pop("DOCKER_CONTEXT", None)
    os.environ["TMPDIR"] = str(RUNTIME_SCRATCH)
    tempfile.tempdir = str(RUNTIME_SCRATCH)
    try:
        yield
    finally:
        tempfile.tempdir = previous_tempdir
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _transfer_workspace_runtime(
    manifest: DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
) -> dict[str, Any]:
    host = v130._docker_json(  # noqa: SLF001
        ["image", "inspect", manifest.workspace_runtime_image_id], timeout=60
    )
    if (
        not isinstance(host, list)
        or len(host) != 1
        or not isinstance(host[0], dict)
        or host[0].get("Id") != manifest.workspace_runtime_image_id
    ):
        raise v130._ProbeFailure("workspace_runtime_host_identity_failed")  # noqa: SLF001
    before = dind._inner(  # noqa: SLF001
        ["image", "inspect", manifest.workspace_runtime_image_id],
        container=_DAEMON_NAME,
        timeout_s=30,
    )
    if before.returncode == 0:
        raise v130._ProbeFailure("workspace_runtime_not_fresh")  # noqa: SLF001
    try:
        stdout, stderr = dind._pipe_image(  # noqa: SLF001
            container=_DAEMON_NAME,
            image_id=manifest.workspace_runtime_image_id,
            timeout_s=1800,
        )
    except RuntimeError as exc:
        raise v130._ProbeFailure("workspace_runtime_transfer_failed") from exc  # noqa: SLF001
    after = dind._inner(  # noqa: SLF001
        ["image", "inspect", manifest.workspace_runtime_image_id, "--format", "{{.Id}}"],
        container=_DAEMON_NAME,
        timeout_s=30,
    )
    if (
        len(stdout) > _MAX_TRANSFER_OUTPUT_BYTES
        or len(stderr) > _MAX_TRANSFER_OUTPUT_BYTES
        or after.returncode != 0
        or after.stdout.decode().strip() != manifest.workspace_runtime_image_id
    ):
        raise v130._ProbeFailure("workspace_runtime_transfer_identity_failed")  # noqa: SLF001
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v136_workspace_runtime_transfer_v1",
        "identity": IDENTITY,
        "status": "passed",
        "workspace_runtime_image_id": manifest.workspace_runtime_image_id,
        "outer_source_read_only": True,
        "inner_image_id_verified": True,
        "transfer_archive_persisted": False,
        "transfer_stdout_bytes": len(stdout),
        "transfer_stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "transfer_stderr_bytes": len(stderr),
        "transfer_stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "raw_transfer_output_persisted": False,
        "registry_accessed": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _host_command_image_absent(image_id: str) -> bool:
    environment = dict(os.environ)
    environment.pop("DOCKER_HOST", None)
    environment.pop("DOCKER_CONTEXT", None)
    result = v130._run(  # noqa: SLF001
        ["docker", "image", "inspect", image_id],
        timeout=30,
        env=environment,
    )
    return result.returncode != 0


def _command_lock_semantics(lock: HweCommandImageLock) -> dict[str, Any]:
    value = lock.model_dump(mode="json")
    for field in ("derived_command_image_id", "lock_hash", "security_scan_id"):
        value.pop(field, None)
    return value


def _diagnose_runtime_binding(
    manifest: DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
    lock: HweCommandImageLock,
) -> dict[str, Any]:
    if not _host_command_image_absent(lock.derived_command_image_id):
        raise v130._ProbeFailure("host_command_image_unexpectedly_present")  # noqa: SLF001
    config = v134._runtime_config(lock)  # noqa: SLF001
    inherited_subreason: str | None = None
    inherited_runtime = DockerRuntime(config)
    try:
        inherited_runtime.prepare("v136-inherited-environment-probe")
    except DockerImageError as exc:
        inherited_subreason = (
            exc.subreason
            if exc.subreason in _ALLOWED_IMAGE_SUBREASONS
            else "unallowlisted_docker_image_error"
        )
    finally:
        inherited_runtime.close()
    explicit_engine = DockerCliEngine(docker_host=manifest.nested_docker_host)
    explicit_runtime = DockerRuntime(config, engine=explicit_engine)
    explicit_passed = False
    explicit_subreason: str | None = None
    try:
        explicit_runtime.prepare("v136-explicit-nested-engine-probe")
        explicit_passed = True
    except DockerImageError as exc:
        explicit_subreason = (
            exc.subreason
            if exc.subreason in _ALLOWED_IMAGE_SUBREASONS
            else "unallowlisted_docker_image_error"
        )
    finally:
        explicit_runtime.close()
    inventory = v130._inner_inventory()  # noqa: SLF001
    matched = (
        inherited_subreason == manifest.expected_inherited_environment_subreason
        and explicit_passed is manifest.explicit_nested_engine_expected_pass
        and explicit_subreason is None
        and inventory.get("status") == "passed"
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v136_command_runtime_diagnostic_v1",
        "identity": IDENTITY,
        "status": "confirmed" if matched else "not_confirmed",
        "diagnosis": (
            "docker_cli_missing_explicit_nested_endpoint_binding"
            if matched
            else "expected_transport_binding_diagnosis_not_confirmed"
        ),
        "inherited_environment_probe_count": 1,
        "inherited_environment_probe_passed": inherited_subreason is None,
        "inherited_environment_subreason": inherited_subreason,
        "explicit_nested_engine_probe_count": 1,
        "explicit_nested_engine_probe_passed": explicit_passed,
        "explicit_nested_engine_subreason": explicit_subreason,
        "same_runtime_configuration_fingerprint": True,
        "command_image_present_in_fresh_nested_daemon": True,
        "command_image_absent_from_host_daemon": True,
        "docker_cli_explicit_binding_required": matched,
        "inner_container_inventory_empty": inventory.get("all_container_count") == 0,
        "inner_volume_inventory_empty": inventory.get("all_volume_count") == 0,
        "task_execution_started": False,
        "base_reference_verification_started": False,
        "harness_controller_started": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "raw_exception_persisted": False,
        "raw_exception_hashed": False,
        "raw_docker_output_persisted": False,
    }
    return {**base, "diagnostic_hash": content_hash(base)}


def _base_report(
    manifest: DeepSeekHarnessV136CommandRuntimeDiagnosticManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v136_command_runtime_report_v1",
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
        "v132_volume_inspected": False,
        "v132_volume_mutated": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "raw_exception_persisted": False,
        "raw_exception_hashed": False,
        "requires_independent_v137_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }


def _write_report(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(report)
    base.pop("report_hash", None)
    value = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(root / "command-runtime-progress.json", value)
    atomic_dump_json(root / "command-runtime-report.json", value)
    return value


def diagnose(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_execution_boundary(arguments)
    manifest = load_v136_command_runtime_diagnostic_manifest(arguments.manifest)
    source_commit = _require_clean_merged_main(manifest)
    predecessor, task, source_lock = _validate_static_predecessors(manifest)
    archive = inspect_offline_image_archive(task, archive_root=ARCHIVE_ROOT)
    with _v136_v130_configuration():
        v130_manifest_view: Any = manifest
        root = v130._new_output(arguments.output)  # noqa: SLF001
        (root / "transfer-receipts").mkdir(mode=0o700)
        atomic_dump_json(root / "predecessor-preflight.json", predecessor)
        atomic_dump_json(root / "archive-receipts/pr-465.json", archive)
        report = _base_report(
            manifest,
            source_commit=source_commit,
            post_merge_main_run_id=arguments.post_merge_main_run_id,
        )
        report.update(
            predecessor_preflight_hash=predecessor["receipt_hash"],
            archive_receipt_hash=archive["receipt_hash"],
            task_archive_read=True,
        )
        _write_report(root, report)
        data_attempted = False
        socket_attempted = False
        daemon_attempted = False
        failure_category: str | None = None
        cleanup: dict[str, Any]
        try:
            v130._create_runtime_paths(v130_manifest_view)  # noqa: SLF001
            host_image = v130._host_image_receipt(v130_manifest_view)  # noqa: SLF001
            atomic_dump_json(root / "host-image-identity.json", host_image)
            v130._require_container_absent(_DAEMON_NAME)  # noqa: SLF001
            v130._require_container_absent(_CLEANUP_NAME)  # noqa: SLF001
            v130._require_volume_absent(manifest.dind_data_volume)  # noqa: SLF001
            v130._require_volume_absent(manifest.dind_socket_volume)  # noqa: SLF001
            data_attempted = True
            v130._create_volume(  # noqa: SLF001
                name=manifest.dind_data_volume,
                role="data",
                backing=DIND_DATA_BACKING,
            )
            socket_attempted = True
            v130._create_volume(  # noqa: SLF001
                name=manifest.dind_socket_volume,
                role="socket",
                backing=DIND_SOCKET_BACKING,
            )
            volumes = v130._volume_setup_receipt(v130_manifest_view)  # noqa: SLF001
            atomic_dump_json(root / "volume-setup-receipt.json", volumes)
            report.update(status="dind_start", startup_attempt_count=1)
            _write_report(root, report)
            daemon_attempted = True
            runtime = v130._start_dind(v130_manifest_view)  # noqa: SLF001
            atomic_dump_json(root / "dind-runtime-receipt.json", runtime)
            transfer = _transfer_workspace_runtime(manifest)
            atomic_dump_json(root / "transfer-receipts/workspace-runtime.json", transfer)
            report.update(
                status="bounded_command_image_materialization",
                workspace_runtime_transfer_hash=transfer["receipt_hash"],
            )
            _write_report(root, report)
            with v130._nested_docker(v130_manifest_view):  # noqa: SLF001
                scan, lock_raw, inventory = v130._build_and_scan(  # noqa: SLF001
                    v130_manifest_view,
                    task,
                    source_lock,
                    root=root,
                )
            lock = HweCommandImageLock.model_validate(lock_raw)
            historical_lock = HweCommandImageLock.model_validate_json(
                V132_COMMAND_LOCK.read_bytes()
            )
            if (
                _command_lock_semantics(lock) != _command_lock_semantics(historical_lock)
                or scan.get("security_scan_id") != lock.security_scan_id
            ):
                raise v130._ProbeFailure(  # noqa: SLF001
                    "rebuilt_command_image_semantics_changed"
                )
            atomic_dump_json(root / "inner-inventory-after-scan.json", inventory)
            report.update(
                status="command_runtime_binding_diagnostic",
                task_image_imported=True,
                command_image_built=True,
                command_image_lock_hash=lock.lock_hash,
                security_scan_id=scan["security_scan_id"],
            )
            _write_report(root, report)
            with _nested_runtime_environment(manifest):
                diagnostic = _diagnose_runtime_binding(manifest, lock)
            atomic_dump_json(root / "command-runtime-diagnostic.json", diagnostic)
            report.update(
                diagnosis_confirmed=diagnostic["status"] == "confirmed",
                diagnosis=diagnostic["diagnosis"],
                docker_image_subreason=diagnostic["inherited_environment_subreason"],
                explicit_nested_engine_probe_passed=diagnostic[
                    "explicit_nested_engine_probe_passed"
                ],
                diagnostic_hash=diagnostic["diagnostic_hash"],
            )
            if diagnostic["status"] != "confirmed":
                failure_category = "transport_binding_diagnosis_not_confirmed"
        except v130._ProbeFailure as exc:  # noqa: SLF001
            failure_category = exc.category
        except subprocess.TimeoutExpired:
            failure_category = "unexpected_control_timeout"
        except Exception:
            failure_category = "unexpected_controller_failure"
        finally:
            try:
                cleanup = v130._cleanup(  # noqa: SLF001
                    v130_manifest_view,
                    daemon_attempted=daemon_attempted,
                    data_attempted=data_attempted,
                    socket_attempted=socket_attempted,
                )
            except Exception:
                cleanup_base = {
                    "schema_version": "1.0",
                    "format_id": "verigym_deepseek_harness_hwe_v136_cleanup_v1",
                    "identity": IDENTITY,
                    "status": "cleanup_unconfirmed",
                    "raw_exception_persisted": False,
                    "provider_calls": 0,
                }
                cleanup = {**cleanup_base, "receipt_hash": content_hash(cleanup_base)}
            atomic_dump_json(root / "cleanup-receipt.json", cleanup)
        report["cleanup_receipt_hash"] = cleanup["receipt_hash"]
        report["cleanup_confirmed"] = cleanup["status"] == "passed"
        if failure_category is not None:
            report.update(
                status="stopped_after_zero_provider_diagnostic",
                stop_reason=failure_category,
            )
        elif cleanup["status"] != "passed":
            report.update(
                status="stopped_cleanup_unconfirmed",
                stop_reason="cleanup_unconfirmed",
            )
        else:
            report.update(
                status="diagnosed_pending_independent_v137_audit",
                stop_reason=None,
            )
        return _write_report(root, report)


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
        if report["status"] == "diagnosed_pending_independent_v137_audit"
        and report["diagnosis_confirmed"] is True
        and report["cleanup_confirmed"] is True
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
