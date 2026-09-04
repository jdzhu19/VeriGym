#!/usr/bin/env python3
"""Run one provider-free, bounded PR-465 command-image scan in a fresh VFS DinD."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
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
from scripts.scan_and_lock_cva6_hwe_command_image import (  # noqa: E402
    CommandImageScanRuntimePolicy,
    scan_and_lock,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV130BoundedCommandScanProbeManifest,
    HweOfflineTaskLock,
    inspect_offline_image_archive,
    load_v69_manifest,
    load_v127_readiness_gated_scaffold_manifest,
    load_v130_bounded_command_scan_probe_manifest,
)
from verigym.hwe.image_lock import HweCommandSourceLock  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V130_BOUNDED_COMMAND_SCAN_CREATE_PROBE"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v130_bounded_command_scan_create_probe_v1.json"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v130")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
RUNTIME_SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v130-runtime")
ARCHIVE_ROOT = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
RG_ROOT = Path(
    "/data2/jiadongzhu/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl"
)
RG_BINARY = RG_ROOT / "rg"
RG_ARCHIVE = RG_ROOT.parent / "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz"
RG_SHA256 = "e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849"
RG_ARCHIVE_SHA256 = "33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c"
V69_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
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
V127_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v127-readiness-gated-scaffold-v1"
)
V127_REPORT = V127_ROOT / "execution-scaffold-report.json"
V127_RUNTIME_RECEIPT = V127_ROOT / "dind-runtime-receipt.json"
V127_ARCHIVE_RECEIPT = V127_ROOT / "archive-receipts/pr-465.json"
V127_SOURCE_LOCK = V127_ROOT / "source-image-locks/pr-465.json"
V127_FAILED_SCAN = V127_ROOT / "security-scans/pr-465.json"
V127_CLEANUP = V127_ROOT / "dind-cleanup-receipt.json"
BUILD_SCRIPT = _REPOSITORY / "scripts/build_ibex_hwe_command_image.sh"

_PROVIDER_ENV_NAMES = v69._PROVIDER_ENV_NAMES  # noqa: SLF001
_CLOSED_FLAGS = (
    "formal_collection_allowed",
    "formal_collection_started",
    "collection_started",
    "training_started",
    "production_training_ready",
)
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONTROL_BYTES = 4096
_MAX_BUILD_OUTPUT_BYTES = 32 * 1024 * 1024
_DAEMON_NAME = "verigym-dind-v130-command-scan"
_CLEANUP_NAME = "verigym-dind-v130-cleanup"
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v130_bounded_command_scan_create_probe_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v128-v127-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v130-bounded-command-scan-create-probe-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v130_bounded_command_scan_create_probe.py",
    "scripts/run_hwe_deepseek_harness_v130_bounded_command_scan_create_probe.py",
    "scripts/scan_and_lock_cva6_hwe_command_image.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_command_image_scanner.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)


class _ProbeFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


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
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
        raise ConfigurationError("v130 immutable JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v130 immutable JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v130 immutable JSON must be an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v130 immutable canonical hash changed")
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
        raise ConfigurationError("v130 requires a non-root host identity")
    if any(name in os.environ for name in _PROVIDER_ENV_NAMES):
        raise ConfigurationError("v130 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v130 requires the default local Docker endpoint")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v130 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v130 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git_text("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v130 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v128_audit_merge, head],
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
        raise ConfigurationError("v130 requires clean merged origin/main after v128")
    return head


def _task_lock(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> HweOfflineTaskLock:
    campaign = load_v69_manifest(V69_MANIFEST)
    matches = [task for task in campaign.primary_tasks if task.task_id == manifest.task_id]
    if len(matches) != 1:
        raise ConfigurationError("v130 PR-465 task lock inventory changed")
    task = matches[0]
    bindings = {
        "archive_relpath": manifest.archive_relpath,
        "archive_sha256_relpath": manifest.archive_sha256_relpath,
        "archive_sha256": manifest.archive_sha256,
        "registry_digest_relpath": manifest.registry_digest_relpath,
        "registry_manifest_digest": manifest.registry_manifest_digest,
        "image_config_digest": manifest.image_config_digest,
        "official_verifier_image": manifest.official_verifier_image,
    }
    if any(getattr(task, name) != value for name, value in bindings.items()):
        raise ConfigurationError("v130 PR-465 task/archive/image binding changed")
    return task


def _validate_static_predecessor(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> tuple[dict[str, Any], HweCommandSourceLock]:
    predecessor_manifest = load_v127_readiness_gated_scaffold_manifest(V127_MANIFEST)
    report = _load_json(V127_REPORT)
    runtime = _load_json(V127_RUNTIME_RECEIPT)
    archive = _load_json(V127_ARCHIVE_RECEIPT)
    source_raw = _load_json(V127_SOURCE_LOCK)
    source_lock = HweCommandSourceLock.model_validate(source_raw)
    scan = _load_json(V127_FAILED_SCAN)
    cleanup = _load_json(V127_CLEANUP)
    entries = list(V127_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    diagnostic = scan.get("diagnostic")
    if (
        _hash_file(V127_MANIFEST) != manifest.v127_manifest_sha256
        or predecessor_manifest.manifest_hash != manifest.v127_manifest_hash
        or _hash_file(V127_RUNNER) != manifest.v127_runner_sha256
        or _hash_file(V127_AUTHORIZATION) != manifest.v127_authorization_sha256
        or _hash_file(V128_AUDIT) != manifest.v128_audit_sha256
        or _hash_file(V127_REPORT) != manifest.v127_report_sha256
        or _canonical_hash(report, "report_hash") != manifest.v127_report_hash
        or _hash_file(V127_RUNTIME_RECEIPT) != manifest.v127_runtime_receipt_sha256
        or _canonical_hash(runtime, "receipt_hash") != manifest.v127_runtime_receipt_hash
        or _hash_file(V127_ARCHIVE_RECEIPT) != manifest.v127_archive_receipt_sha256
        or _canonical_hash(archive, "receipt_hash") != manifest.v127_archive_receipt_hash
        or _hash_file(V127_SOURCE_LOCK) != manifest.v127_source_lock_sha256
        or source_lock.lock_hash != manifest.v127_source_lock_hash
        or _hash_file(V127_FAILED_SCAN) != manifest.v127_failed_scan_sha256
        or scan.get("security_scan_id") != manifest.v127_failed_scan_id
        or not isinstance(diagnostic, dict)
        or _canonical_hash(diagnostic, "diagnostic_hash") != manifest.v127_failed_diagnostic_hash
        or scan.get("derived_command_image_id") != manifest.v127_derived_command_image_id
        or _hash_file(V127_CLEANUP) != manifest.v127_cleanup_sha256
        or _canonical_hash(cleanup, "receipt_hash") != manifest.v127_cleanup_hash
        or directories != manifest.v127_evidence_directory_count
        or files != manifest.v127_evidence_regular_file_count
        or symlinks != manifest.v127_evidence_symlink_count
    ):
        raise ConfigurationError("v130 audited v127 binding changed")
    if (
        report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "RuntimeError"
        or report.get("source_commit") != manifest.v127_source_commit
        or report.get("post_merge_main_run_id") != manifest.v127_post_merge_main_run_id
        or report.get("provider_execution_scaffold_published") is not False
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or any(report.get(name) is not False for name in _CLOSED_FLAGS)
        or runtime.get("server_version") != manifest.dind_server_version
        or runtime.get("storage_driver") != manifest.dind_storage_driver
        or runtime.get("default_runtime") != manifest.dind_default_runtime
        or runtime.get("predecessor_volumes_inspected") is not False
        or runtime.get("predecessor_volumes_mutated") is not False
        or archive.get("task_id") != manifest.task_id
        or archive.get("registry_accessed") is not False
        or archive.get("partial_archive_used") is not False
        or source_lock.task_id != manifest.task_id
        or source_lock.verifier_base_image_id != manifest.official_verifier_image
        or scan.get("scan_passed") is not False
        or diagnostic.get("status") != "failed"
        or diagnostic.get("failure_stage") != "docker_create"
        or diagnostic.get("error_category") != "docker_create_failed"
        or diagnostic.get("temporary_container_created") is not False
        or diagnostic.get("temporary_workspace_removed") is not True
        or cleanup.get("socket_volume_removed") is not True
        or cleanup.get("predecessor_volumes_inspected") is not False
        or cleanup.get("predecessor_volumes_mutated") is not False
    ):
        raise ConfigurationError("v130 requires the exact audited v127 terminal state")
    if (
        manifest.archive_root != str(ARCHIVE_ROOT)
        or manifest.output_root != str(OUTPUT_ROOT)
        or manifest.dind_data_backing != str(DIND_DATA_BACKING)
        or manifest.dind_socket_backing != str(DIND_SOCKET_BACKING)
        or manifest.runtime_scratch_root != str(RUNTIME_SCRATCH)
        or manifest.nested_docker_host != f"unix://{DIND_SOCKET_BACKING / 'docker.sock'}"
        or manifest.startup_attempt_limit != 1
        or manifest.registry_access_allowed is not False
        or manifest.partial_archive_allowed is not False
        or manifest.predecessor_volume_inspection_allowed is not False
        or manifest.predecessor_volume_mutation_allowed is not False
        or manifest.provider_credentials_available is not False
        or manifest.provider_request_started is not False
        or manifest.provider_calls != 0
        or any(getattr(manifest, name) is not False for name in _CLOSED_FLAGS)
    ):
        raise ConfigurationError("v130 purpose or isolation policy changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_predecessor_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "v127_manifest_hash": manifest.v127_manifest_hash,
        "v127_report_hash": manifest.v127_report_hash,
        "v127_runtime_receipt_hash": manifest.v127_runtime_receipt_hash,
        "v127_failed_scan_id": manifest.v127_failed_scan_id,
        "v127_failed_diagnostic_hash": manifest.v127_failed_diagnostic_hash,
        "v127_source_lock_hash": source_lock.lock_hash,
        "v128_audit_merge": manifest.v128_audit_merge,
        "v128_post_merge_main_run_id": manifest.v128_post_merge_main_run_id,
        "v128_post_merge_main_all_eight_classes_passed": True,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}, source_lock


def _validated_tool(path: Path, expected_hash: str, *, executable: bool) -> Path:
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.is_file()
        or _hash_file(path) != expected_hash
        or (executable and not os.access(path, os.X_OK))
    ):
        raise ConfigurationError("v130 frozen ripgrep tool input changed")
    return path.resolve(strict=True)


def _new_output(path: Path) -> Path:
    if path != OUTPUT_ROOT or path.exists() or path.is_symlink():
        raise ConfigurationError("v130 output identity must be new and exact")
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise ConfigurationError("v130 output parent is unsafe")
    path.mkdir(mode=0o700)
    for relative in ("archive-receipts", "image-receipts", "security-scans", "image-locks"):
        (path / relative).mkdir(mode=0o700)
    return path.resolve(strict=True)


def _create_runtime_paths(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> None:
    expected = {
        DIND_DATA_BACKING: manifest.dind_data_backing,
        DIND_SOCKET_BACKING: manifest.dind_socket_backing,
        RUNTIME_SCRATCH: manifest.runtime_scratch_root,
    }
    if DIND_PARENT.exists() or DIND_PARENT.is_symlink():
        raise ConfigurationError("v130 DinD root must be fresh")
    if RUNTIME_SCRATCH.exists() or RUNTIME_SCRATCH.is_symlink():
        raise ConfigurationError("v130 runtime scratch must be fresh")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    RUNTIME_SCRATCH.mkdir(parents=True, mode=0o700)
    for path, frozen in expected.items():
        if (
            str(path) != frozen
            or path.is_symlink()
            or not path.is_dir()
            or next(path.iterdir(), None) is not None
        ):
            raise ConfigurationError("v130 runtime path differs from the frozen fresh identity")
        path.chmod(0o700)


def _run(
    arguments: list[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        cwd=_REPOSITORY,
        check=False,
        capture_output=True,
        timeout=timeout,
        env=None if env is None else dict(env),
    )


def _safe_result(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    stdout = result.stdout or b""
    stderr = result.stderr or b""
    return {
        "exit_code": result.returncode,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "output_within_bound": len(stdout) <= _MAX_CONTROL_BYTES
        and len(stderr) <= _MAX_CONTROL_BYTES,
        "raw_output_persisted": False,
        "raw_output_hashed": False,
    }


def _docker_json(arguments: list[str], *, timeout: float = 60) -> Any:
    result = _run(["docker", *arguments], timeout=timeout)
    if result.returncode != 0 or len(result.stdout) > 16 * 1024 * 1024 or result.stderr:
        raise _ProbeFailure("docker_control_command_failed")
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise _ProbeFailure("docker_control_response_invalid") from exc


def _host_image_receipt(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> dict[str, Any]:
    values = _docker_json(["image", "inspect", manifest.dind_image_id], timeout=60)
    image = values[0] if isinstance(values, list) and len(values) == 1 else None
    config = image.get("Config") if isinstance(image, dict) else None
    repo_digests = image.get("RepoDigests") if isinstance(image, dict) else None
    if (
        not isinstance(image, dict)
        or image.get("Id") != manifest.dind_image_id
        or not isinstance(config, dict)
        or not isinstance(config.get("Entrypoint"), list)
        or not config["Entrypoint"]
        or Path(str(config["Entrypoint"][0])).name != "dockerd-entrypoint.sh"
        or not isinstance(repo_digests, list)
        or not any(
            isinstance(value, str) and value.endswith(f"@{manifest.dind_repository_digest}")
            for value in repo_digests
        )
    ):
        raise _ProbeFailure("host_dind_image_identity_failed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_host_image_identity_v1",
        "identity": IDENTITY,
        "status": "passed",
        "dind_image_id": manifest.dind_image_id,
        "dind_repository_digest": manifest.dind_repository_digest,
        "image_id_matched": True,
        "repository_digest_matched": True,
        "official_entrypoint_matched": True,
        "registry_accessed": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _volume_matches(value: Any, *, name: str, role: str, backing: Path) -> bool:
    return (
        isinstance(value, dict)
        and value.get("Name") == name
        and value.get("Driver") == "local"
        and value.get("Labels") == {"verigym.owner": IDENTITY, "verigym.role": role}
        and value.get("Options")
        == {"device": str(backing.resolve(strict=True)), "o": "bind", "type": "none"}
    )


def _require_volume_absent(name: str) -> None:
    result = _run(["docker", "volume", "inspect", name], timeout=30)
    message = ((result.stdout or b"") + b"\n" + (result.stderr or b"")).lower()
    if result.returncode == 0 or b"no such volume" not in message:
        raise _ProbeFailure("fresh_volume_precondition_failed")


def _require_container_absent(name: str) -> None:
    result = _run(["docker", "container", "inspect", name], timeout=30)
    message = ((result.stdout or b"") + b"\n" + (result.stderr or b"")).lower()
    if result.returncode == 0 or not any(
        marker in message for marker in (b"no such container", b"no such object")
    ):
        raise _ProbeFailure("fresh_container_precondition_failed")


def _create_volume(*, name: str, role: str, backing: Path) -> None:
    absent = _run(["docker", "volume", "inspect", name], timeout=30)
    if absent.returncode == 0:
        raise _ProbeFailure("fresh_volume_precondition_failed")
    created = _run(
        [
            "docker",
            "volume",
            "create",
            "--driver",
            "local",
            "--opt",
            "type=none",
            "--opt",
            "o=bind",
            "--opt",
            f"device={backing.resolve(strict=True)}",
            "--label",
            f"verigym.owner={IDENTITY}",
            "--label",
            f"verigym.role={role}",
            name,
        ],
        timeout=30,
    )
    values = _docker_json(["volume", "inspect", name], timeout=30)
    if (
        created.returncode != 0
        or created.stdout.decode(errors="replace").strip() != name
        or not isinstance(values, list)
        or len(values) != 1
        or not _volume_matches(values[0], name=name, role=role, backing=backing)
    ):
        raise _ProbeFailure("volume_create_failed")


def _volume_setup_receipt(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_volume_setup_v1",
        "identity": IDENTITY,
        "status": "passed",
        "data_volume": manifest.dind_data_volume,
        "socket_volume": manifest.dind_socket_volume,
        "bind_backed": True,
        "fresh": True,
        "backing_roots_under_data2": True,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_reused": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _outer_controls_valid(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> bool:
    try:
        values = _docker_json(["container", "inspect", _DAEMON_NAME], timeout=60)
    except _ProbeFailure:
        return False
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return False
    value = values[0]
    host = value.get("HostConfig")
    config = value.get("Config")
    mounts = value.get("Mounts")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        return False
    expected = {
        "/var/lib/docker": (manifest.dind_data_volume, True),
        "/var/run": (manifest.dind_socket_volume, True),
        str(RUNTIME_SCRATCH.resolve(strict=True)): (
            str(RUNTIME_SCRATCH.resolve(strict=True)),
            True,
        ),
    }
    observed: dict[str, tuple[str, bool]] = {}
    for mount in mounts:
        if not isinstance(mount, dict) or mount.get("Destination") not in expected:
            return False
        source = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
        if not isinstance(source, str) or not isinstance(mount.get("RW"), bool):
            return False
        observed[str(mount["Destination"])] = (source, mount["RW"])
    labels = config.get("Labels")
    environment = config.get("Env")
    return (
        value.get("Image") == manifest.dind_image_id
        and host.get("Privileged") is True
        and host.get("NetworkMode") == "none"
        and host.get("PidsLimit") == 32768
        and observed == expected
        and isinstance(labels, dict)
        and labels.get("verigym.owner") == IDENTITY
        and labels.get("verigym.role") == "command-scan-probe-daemon"
        and isinstance(environment, list)
        and "DOCKER_TLS_CERTDIR=" in environment
    )


def _start_dind(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
) -> dict[str, Any]:
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        _DAEMON_NAME,
        "--label",
        f"verigym.owner={IDENTITY}",
        "--label",
        "verigym.role=command-scan-probe-daemon",
        "--privileged",
        "--network",
        "none",
        "--pids-limit",
        "32768",
        "--env",
        "DOCKER_TLS_CERTDIR=",
        "--mount",
        f"type=volume,src={manifest.dind_socket_volume},dst=/var/run",
        "--mount",
        f"type=volume,src={manifest.dind_data_volume},dst=/var/lib/docker",
        "--mount",
        f"type=bind,src={RUNTIME_SCRATCH.resolve(strict=True)},"
        f"dst={RUNTIME_SCRATCH.resolve(strict=True)}",
        manifest.dind_image_id,
        "--storage-driver=vfs",
        "--iptables=false",
        "--ip6tables=false",
        "--bridge=none",
        f"--group={os.getgid()}",
    ]
    try:
        started = _run(command, timeout=manifest.startup_command_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise _ProbeFailure("dind_start_timeout") from exc
    if started.returncode != 0 or _CONTAINER_ID.fullmatch(started.stdout.decode().strip()) is None:
        raise _ProbeFailure("dind_start_failed")
    if not _outer_controls_valid(manifest):
        raise _ProbeFailure("outer_container_controls_invalid")
    deadline = time.monotonic() + manifest.readiness_timeout_seconds
    poll_count = 0
    while time.monotonic() < deadline:
        poll_count += 1
        try:
            ready = _run(
                [
                    "docker",
                    "exec",
                    _DAEMON_NAME,
                    "docker",
                    "info",
                    "--format",
                    "{{.ServerVersion}}\t{{.Driver}}\t{{.DefaultRuntime}}",
                ],
                timeout=manifest.readiness_command_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            ready = None
        if ready is not None and ready.returncode == 0 and not ready.stderr:
            values = ready.stdout.decode(errors="replace").rstrip("\r\n").split("\t")
            if len(values) == 3:
                expected = (
                    manifest.dind_server_version,
                    manifest.dind_storage_driver,
                    manifest.dind_default_runtime,
                )
                if tuple(values) != expected:
                    raise _ProbeFailure("dind_identity_mismatch")
                base = {
                    "schema_version": "1.0",
                    "format_id": "verigym_deepseek_harness_hwe_v130_dind_runtime_v1",
                    "identity": IDENTITY,
                    "status": "passed",
                    "server_version": values[0],
                    "storage_driver": values[1],
                    "default_runtime": values[2],
                    "readiness_poll_count": poll_count,
                    "readiness_timeout_seconds": manifest.readiness_timeout_seconds,
                    "readiness_command_timeout_seconds": manifest.readiness_command_timeout_seconds,
                    "outer_network": "none",
                    "outer_controls_valid": True,
                    "docker_root_dir": "/var/lib/docker",
                    "nested_docker_host": manifest.nested_docker_host,
                    "predecessor_volumes_inspected": False,
                    "predecessor_volumes_mutated": False,
                    "provider_calls": 0,
                }
                return {**base, "receipt_hash": content_hash(base)}
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(float(manifest.readiness_poll_interval_seconds), remaining))
    raise _ProbeFailure("dind_readiness_timeout")


@contextmanager
def _nested_docker(manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest) -> Iterator[None]:
    previous_host = os.environ.get("DOCKER_HOST")
    previous_context = os.environ.pop("DOCKER_CONTEXT", None)
    os.environ["DOCKER_HOST"] = manifest.nested_docker_host
    try:
        yield
    finally:
        if previous_host is None:
            os.environ.pop("DOCKER_HOST", None)
        else:
            os.environ["DOCKER_HOST"] = previous_host
        if previous_context is not None:
            os.environ["DOCKER_CONTEXT"] = previous_context


def _bounded_build(command: list[str], *, timeout: int) -> dict[str, Any]:
    try:
        result = _run(command, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v130_build_diagnostic_v1",
            "identity": IDENTITY,
            "status": "failed",
            "category": "command_image_build_timeout",
            "timeout_seconds": timeout,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "raw_output_persisted": False,
            "raw_output_hashed": False,
            "provider_calls": 0,
        }
        return {**base, "diagnostic_hash": content_hash(base)}
    summary = _safe_result(result)
    output_within_bound = (
        len(result.stdout or b"") <= _MAX_BUILD_OUTPUT_BYTES
        and len(result.stderr or b"") <= _MAX_BUILD_OUTPUT_BYTES
    )
    passed = result.returncode == 0 and output_within_bound
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_build_diagnostic_v1",
        "identity": IDENTITY,
        "status": "passed" if passed else "failed",
        "category": "command_image_build_complete" if passed else "command_image_build_failed",
        "timeout_seconds": timeout,
        **summary,
        "maximum_output_bytes": _MAX_BUILD_OUTPUT_BYTES,
        "output_within_bound": output_within_bound,
        "provider_calls": 0,
    }
    return {**base, "diagnostic_hash": content_hash(base)}


def _inner_inventory() -> dict[str, Any]:
    containers = _run(["docker", "container", "ls", "--all", "--quiet"], timeout=60)
    volumes = _run(["docker", "volume", "ls", "--quiet"], timeout=60)
    if containers.returncode != 0 or volumes.returncode != 0:
        raise _ProbeFailure("inner_inventory_failed")
    container_count = len(containers.stdout.splitlines())
    volume_count = len(volumes.stdout.splitlines())
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_inner_inventory_v1",
        "identity": IDENTITY,
        "status": "passed" if container_count == 0 and volume_count == 0 else "failed",
        "all_container_count": container_count,
        "all_volume_count": volume_count,
        "temporary_scan_container_absent": container_count == 0,
        "inner_volume_inventory_empty": volume_count == 0,
        "explicit_nested_docker_binding": True,
        "raw_identifiers_persisted": False,
        "provider_calls": 0,
    }
    value = {**base, "inventory_hash": content_hash(base)}
    return value


def _build_and_scan(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
    task: HweOfflineTaskLock,
    source_lock: HweCommandSourceLock,
    *,
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    v69._load_completed_archive(task, archive_root=ARCHIVE_ROOT)  # noqa: SLF001
    import_base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_task_image_import_v1",
        "identity": IDENTITY,
        "status": "passed",
        "task_id": task.task_id,
        "official_verifier_image": task.official_verifier_image,
        "registry_manifest_digest": task.registry_manifest_digest,
        "source_lock_hash": source_lock.lock_hash,
        "archive_receipt_hash": manifest.v127_archive_receipt_hash,
        "registry_accessed": False,
        "partial_archive_used": False,
        "task_execution_started": False,
        "provider_calls": 0,
    }
    import_receipt = {**import_base, "receipt_hash": content_hash(import_base)}
    atomic_dump_json(root / "task-image-import-receipt.json", import_receipt)
    receipt = root / "image-receipts/pr-465.json"
    scan_path = root / "security-scans/pr-465.json"
    lock_path = root / "image-locks/pr-465.json"
    tag = "verigym/ibex-hwe-command:harness-v130-pr465"
    diagnostic = _bounded_build(
        [
            str(BUILD_SCRIPT),
            str(RG_BINARY),
            str(RG_ARCHIVE),
            manifest.official_verifier_image,
            manifest.task_id,
            tag,
            str(receipt),
            "verilator",
        ],
        timeout=1800,
    )
    atomic_dump_json(root / "build-command-diagnostic.json", diagnostic)
    if diagnostic["status"] != "passed" or not receipt.is_file():
        raise _ProbeFailure(str(diagnostic["category"]))
    policy = CommandImageScanRuntimePolicy(
        policy_id=manifest.scanner_policy_id,
        create_timeout_seconds=manifest.create_timeout_seconds,
        inspect_timeout_seconds=manifest.inspect_timeout_seconds,
        start_timeout_seconds=manifest.start_timeout_seconds,
        remove_timeout_seconds=manifest.remove_timeout_seconds,
        overall_timeout_seconds=manifest.overall_timeout_seconds,
        container_name=manifest.scanner_container_name,
        owner_label=IDENTITY,
    )
    try:
        scan, lock = scan_and_lock(
            receipt_path=receipt,
            identity_lock_path=V127_SOURCE_LOCK,
            security_output=scan_path,
            lock_output=lock_path,
            repository_profile="ibex-verilator",
            runtime_scratch_parent=RUNTIME_SCRATCH,
            runtime_policy=policy,
        )
    except RuntimeError as exc:
        inventory = _inner_inventory()
        atomic_dump_json(root / "inner-inventory.json", inventory)
        if inventory["status"] != "passed":
            raise _ProbeFailure("inner_inventory_not_empty") from exc
        if scan_path.is_file():
            failed = _load_json(scan_path)
            category = (failed.get("diagnostic") or {}).get("error_category")
            if isinstance(category, str):
                raise _ProbeFailure(category) from exc
        raise _ProbeFailure("command_image_scan_failed_without_receipt") from exc
    inventory = _inner_inventory()
    if inventory["status"] != "passed":
        raise _ProbeFailure("inner_inventory_not_empty")
    if (
        scan.get("scan_passed") is not True
        or lock.security_scan_passed is not True
        or lock.task_id != manifest.task_id
        or lock.verifier_base_image_id != manifest.official_verifier_image
    ):
        raise _ProbeFailure("command_image_scan_identity_failed")
    return scan, lock.model_dump(mode="json"), inventory


def _remove_owned_container(name: str, *, role: str) -> tuple[bool, str]:
    inspected = _run(["docker", "container", "inspect", name], timeout=30)
    if inspected.returncode != 0:
        return True, "already_absent"
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return False, "invalid_container_inspect_response"
    config = values[0].get("Config") if isinstance(values, list) and len(values) == 1 else None
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict) or labels.get("verigym.owner") != IDENTITY:
        return False, "unowned_container_preserved"
    if labels.get("verigym.role") != role:
        return False, "container_role_mismatch_preserved"
    removed = _run(["docker", "rm", "--force", name], timeout=120)
    verified = _run(["docker", "container", "inspect", name], timeout=30)
    return (
        (True, "removed")
        if removed.returncode == 0 and verified.returncode != 0
        else (False, "container_remove_failed")
    )


def _remove_owned_volume(*, name: str, role: str, backing: Path) -> tuple[bool, str]:
    inspected = _run(["docker", "volume", "inspect", name], timeout=30)
    if inspected.returncode != 0:
        return True, "already_absent"
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return False, "invalid_volume_inspect_response"
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not _volume_matches(values[0], name=name, role=role, backing=backing)
    ):
        return False, "unowned_volume_preserved"
    removed = _run(["docker", "volume", "rm", name], timeout=120)
    verified = _run(["docker", "volume", "inspect", name], timeout=30)
    return (
        (True, "removed")
        if removed.returncode == 0 and verified.returncode != 0
        else (False, "volume_remove_failed")
    )


def _backing_restored(path: Path) -> bool:
    try:
        metadata = path.stat()
        return (
            not path.is_symlink()
            and path.is_dir()
            and next(path.iterdir(), None) is None
            and metadata.st_uid == os.getuid()
            and metadata.st_gid == os.getgid()
            and (metadata.st_mode & 0o777) == 0o700
        )
    except OSError:
        return False


def _cleanup(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
    *,
    daemon_attempted: bool,
    data_attempted: bool,
    socket_attempted: bool,
) -> dict[str, Any]:
    if daemon_attempted:
        daemon_removed, daemon_category = _remove_owned_container(
            _DAEMON_NAME, role="command-scan-probe-daemon"
        )
    else:
        daemon_removed, daemon_category = True, "not_attempted"
    owned: list[tuple[str, str]] = []
    for attempted, name, role, backing, target in (
        (
            data_attempted,
            manifest.dind_data_volume,
            "data",
            DIND_DATA_BACKING,
            "/verigym-data",
        ),
        (
            socket_attempted,
            manifest.dind_socket_volume,
            "socket",
            DIND_SOCKET_BACKING,
            "/verigym-socket",
        ),
    ):
        if not daemon_removed or not attempted:
            continue
        inspected = _run(["docker", "volume", "inspect", name], timeout=30)
        try:
            values = json.loads(inspected.stdout) if inspected.returncode == 0 else None
        except json.JSONDecodeError:
            values = None
        if (
            isinstance(values, list)
            and len(values) == 1
            and _volume_matches(values[0], name=name, role=role, backing=backing)
        ):
            owned.append((name, target))
    helper_attempted = bool(owned)
    helper_status = "not_required" if daemon_removed else "blocked_by_daemon_cleanup"
    helper_removed = True
    if helper_attempted:
        mounts: list[str] = []
        targets: list[str] = []
        for name, target in owned:
            mounts.extend(("--mount", f"type=volume,src={name},dst={target}"))
            targets.append(target)
        target_text = " ".join(targets)
        helper = _run(
            [
                "docker",
                "run",
                "--name",
                _CLEANUP_NAME,
                "--label",
                f"verigym.owner={IDENTITY}",
                "--label",
                "verigym.role=command-scan-probe-cleanup",
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
                *mounts,
                "--entrypoint",
                "/bin/sh",
                manifest.dind_image_id,
                "-euc",
                f"find {target_text} -mindepth 1 -delete; "
                f"chown {os.getuid()}:{os.getgid()} {target_text}; "
                f"chmod 0700 {target_text}",
            ],
            timeout=300,
        )
        helper_status = "passed" if helper.returncode == 0 else "cleanup_helper_failed"
        helper_removed, _ = _remove_owned_container(
            _CLEANUP_NAME, role="command-scan-probe-cleanup"
        )
    data_removed, data_category = _remove_owned_volume(
        name=manifest.dind_data_volume,
        role="data",
        backing=DIND_DATA_BACKING,
    )
    socket_removed, socket_category = _remove_owned_volume(
        name=manifest.dind_socket_volume,
        role="socket",
        backing=DIND_SOCKET_BACKING,
    )
    data_restored = _backing_restored(DIND_DATA_BACKING)
    socket_restored = _backing_restored(DIND_SOCKET_BACKING)
    scratch_empty = (
        RUNTIME_SCRATCH.is_dir()
        and not RUNTIME_SCRATCH.is_symlink()
        and next(RUNTIME_SCRATCH.iterdir(), None) is None
    )
    passed = all(
        (
            daemon_removed,
            helper_removed,
            helper_status in {"passed", "not_required"},
            data_removed,
            socket_removed,
            data_restored,
            socket_restored,
            scratch_empty,
        )
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_cleanup_v1",
        "identity": IDENTITY,
        "status": "passed" if passed else "cleanup_unconfirmed",
        "daemon_removed": daemon_removed,
        "daemon_cleanup_category": daemon_category,
        "cleanup_helper_attempted": helper_attempted,
        "cleanup_helper_status": helper_status,
        "cleanup_helper_removed": helper_removed,
        "data_volume_removed": data_removed,
        "data_volume_cleanup_category": data_category,
        "socket_volume_removed": socket_removed,
        "socket_volume_cleanup_category": socket_category,
        "data_backing_empty_and_ownership_restored": data_restored,
        "socket_backing_empty_and_ownership_restored": socket_restored,
        "runtime_scratch_empty": scratch_empty,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "raw_output_persisted": False,
        "raw_output_hashed": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _base_report(
    manifest: DeepSeekHarnessV130BoundedCommandScanProbeManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v130_command_scan_probe_report_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "stop_reason": None,
        "diagnostic_complete": False,
        "command_image_scan_passed": False,
        "cleanup_confirmed": False,
        "startup_attempt_limit": 1,
        "startup_attempt_count": 0,
        "scanner_policy": {
            "policy_id": manifest.scanner_policy_id,
            "create_timeout_seconds": manifest.create_timeout_seconds,
            "inspect_timeout_seconds": manifest.inspect_timeout_seconds,
            "start_timeout_seconds": manifest.start_timeout_seconds,
            "remove_timeout_seconds": manifest.remove_timeout_seconds,
            "overall_timeout_seconds": manifest.overall_timeout_seconds,
            "container_name": manifest.scanner_container_name,
        },
        "predecessor_preflight_hash": None,
        "archive_receipt_hash": None,
        "task_image_import_receipt_hash": None,
        "host_image_identity_hash": None,
        "volume_setup_receipt_hash": None,
        "dind_runtime_receipt_hash": None,
        "build_diagnostic_hash": None,
        "security_scan_id": None,
        "command_image_lock_hash": None,
        "inner_inventory_hash": None,
        "cleanup_receipt_hash": None,
        "task_archive_read": False,
        "task_image_imported": False,
        "command_image_built": False,
        "task_execution_started": False,
        "base_reference_verification_started": False,
        "harness_controller_started": False,
        "docker_networks_created": False,
        "registry_accessed": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "raw_docker_output_persisted": False,
        "raw_docker_output_hashed": False,
        "raw_exception_persisted": False,
        "requires_independent_v131_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }


def _write_report(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(report)
    base.pop("report_hash", None)
    value = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(root / "command-scan-probe-progress.json", value)
    atomic_dump_json(root / "command-scan-probe-report.json", value)
    return value


def diagnose(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_execution_boundary(arguments)
    manifest = load_v130_bounded_command_scan_probe_manifest(arguments.manifest)
    source_commit = _require_clean_merged_main(manifest)
    predecessor, source_lock = _validate_static_predecessor(manifest)
    task = _task_lock(manifest)
    rg_binary = _validated_tool(RG_BINARY, RG_SHA256, executable=True)
    rg_archive = _validated_tool(RG_ARCHIVE, RG_ARCHIVE_SHA256, executable=False)
    if rg_binary != RG_BINARY or rg_archive != RG_ARCHIVE:
        raise ConfigurationError("v130 ripgrep paths changed")
    archive = inspect_offline_image_archive(task, archive_root=ARCHIVE_ROOT)
    root = _new_output(arguments.output)
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
        _create_runtime_paths(manifest)
        host_image = _host_image_receipt(manifest)
        atomic_dump_json(root / "host-image-identity.json", host_image)
        report["host_image_identity_hash"] = host_image["receipt_hash"]
        _require_container_absent(_DAEMON_NAME)
        _require_container_absent(_CLEANUP_NAME)
        _require_volume_absent(manifest.dind_data_volume)
        _require_volume_absent(manifest.dind_socket_volume)
        data_attempted = True
        _create_volume(name=manifest.dind_data_volume, role="data", backing=DIND_DATA_BACKING)
        socket_attempted = True
        _create_volume(
            name=manifest.dind_socket_volume,
            role="socket",
            backing=DIND_SOCKET_BACKING,
        )
        volumes = _volume_setup_receipt(manifest)
        atomic_dump_json(root / "volume-setup-receipt.json", volumes)
        report["volume_setup_receipt_hash"] = volumes["receipt_hash"]
        report["status"] = "dind_start"
        _write_report(root, report)
        report["startup_attempt_count"] = 1
        daemon_attempted = True
        runtime = _start_dind(manifest)
        atomic_dump_json(root / "dind-runtime-receipt.json", runtime)
        report["dind_runtime_receipt_hash"] = runtime["receipt_hash"]
        report["status"] = "bounded_command_image_scan"
        _write_report(root, report)
        with _nested_docker(manifest):
            scan, lock, inventory = _build_and_scan(
                manifest,
                task,
                source_lock,
                root=root,
            )
        diagnostic = _load_json(root / "build-command-diagnostic.json")
        atomic_dump_json(root / "inner-inventory.json", inventory)
        report.update(
            task_image_imported=True,
            command_image_built=True,
            command_image_scan_passed=True,
            diagnostic_complete=True,
            build_diagnostic_hash=diagnostic["diagnostic_hash"],
            security_scan_id=scan["security_scan_id"],
            command_image_lock_hash=lock["lock_hash"],
            inner_inventory_hash=inventory["inventory_hash"],
        )
    except _ProbeFailure as exc:
        failure_category = exc.category
    except subprocess.TimeoutExpired:
        failure_category = "unexpected_control_timeout"
    except Exception:
        failure_category = "unexpected_controller_failure"
    finally:
        try:
            cleanup = _cleanup(
                manifest,
                daemon_attempted=daemon_attempted,
                data_attempted=data_attempted,
                socket_attempted=socket_attempted,
            )
        except Exception:
            cleanup_base = {
                "schema_version": "1.0",
                "format_id": "verigym_deepseek_harness_hwe_v130_cleanup_v1",
                "identity": IDENTITY,
                "status": "cleanup_unconfirmed",
                "raw_exception_persisted": False,
                "provider_calls": 0,
            }
            cleanup = {**cleanup_base, "receipt_hash": content_hash(cleanup_base)}
        atomic_dump_json(root / "cleanup-receipt.json", cleanup)
    report["cleanup_receipt_hash"] = cleanup["receipt_hash"]
    report["cleanup_confirmed"] = cleanup["status"] == "passed"
    evidence_bindings = (
        ("task-image-import-receipt.json", "receipt_hash", "task_image_import_receipt_hash"),
        ("build-command-diagnostic.json", "diagnostic_hash", "build_diagnostic_hash"),
        ("security-scans/pr-465.json", "security_scan_id", "security_scan_id"),
        ("image-locks/pr-465.json", "lock_hash", "command_image_lock_hash"),
        ("inner-inventory.json", "inventory_hash", "inner_inventory_hash"),
    )
    for relative, source_field, report_field in evidence_bindings:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            value = _load_json(path)
            observed = value.get(source_field)
            if isinstance(observed, str) and _HASH.fullmatch(observed):
                report[report_field] = observed
    report["task_image_imported"] = report["task_image_import_receipt_hash"] is not None
    report["command_image_built"] = (
        report["build_diagnostic_hash"] is not None
        and (root / "image-receipts/pr-465.json").is_file()
    )
    if failure_category is not None:
        report.update(
            status="stopped_after_bounded_probe",
            stop_reason=failure_category,
            diagnostic_complete=(root / "security-scans/pr-465.json").is_file(),
        )
    elif cleanup["status"] != "passed":
        report.update(status="stopped_cleanup_unconfirmed", stop_reason="cleanup_unconfirmed")
    else:
        report.update(
            status="completed_pending_independent_v131_audit",
            stop_reason=None,
            diagnostic_complete=True,
        )
    return _write_report(root, report)


def main(argv: Sequence[str] | None = None) -> int:
    report = diagnose(_parser().parse_args(argv))
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_complete": report["diagnostic_complete"],
                "command_image_scan_passed": report["command_image_scan_passed"],
                "cleanup_confirmed": report["cleanup_confirmed"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return (
        0
        if report["status"] == "completed_pending_independent_v131_audit"
        and report["command_image_scan_passed"] is True
        and report["cleanup_confirmed"] is True
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
