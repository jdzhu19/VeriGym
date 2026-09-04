#!/usr/bin/env python3
"""Run one provider-free, content-free diagnostic of the outer DinD startup boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
for _source_root in reversed((_REPOSITORY, _REPOSITORY / "src")):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    load_v118_explicit_inner_inventory_scaffold_manifest,
    load_v121_bounded_dind_start_diagnostic_manifest,
)
from verigym.hwe.materialization_preflight import (  # noqa: E402
    materialization_headroom_receipt,
)
from verigym.runtimes.docker.engine import DockerCliEngine, EngineResult  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V121_BOUNDED_DIND_START_DIAGNOSTIC"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v121_bounded_dind_start_diagnostic_v1.json"
)
AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v121-bounded-dind-start-authorization.md"
)
V118_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v118_explicit_inner_inventory_scaffold_v1.json"
)
V118_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v118-explicit-inner-inventory-authorization.md"
)
V119_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v119-v118-result.md"
V118_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1"
)
V118_REPORT = V118_ROOT / "execution-scaffold-report.json"
V118_PROGRESS = V118_ROOT / "execution-scaffold-progress.json"
V118_HEADROOM = V118_ROOT / "headroom-preflight.json"
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v121")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v121-control")
DIAGNOSTIC_SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v121-scratch")

_PROVIDER_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "VERIGYM_DEEPSEEK_API_BASE_URL",
        "VERIGYM_DEEPSEEK_API_KEY",
    }
)
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v121_bounded_dind_start_diagnostic_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v119-v118-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v121-bounded-dind-start-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v121_bounded_dind_start_diagnostic.py",
    "scripts/run_hwe_deepseek_harness_v121_bounded_dind_start_diagnostic.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_NOT_FOUND_PATTERNS = ("no such container", "no such object", "no such volume", "not found")
_CLASSIFICATION_PATTERNS = (
    ("permission_denied", ("permission denied", "access denied", "operation not permitted")),
    ("no_space_left", ("no space left on device", "disk quota exceeded")),
    (
        "mount_source_unavailable",
        (
            "bind source path does not exist",
            "error while creating mount source path",
            "invalid mount config",
            "mount source path does not exist",
        ),
    ),
    (
        "oci_runtime_create_failed",
        (
            "oci runtime create failed",
            "failed to create shim task",
            "runc create failed",
            "container init caused",
        ),
    ),
    (
        "daemon_unavailable",
        (
            "cannot connect to the docker daemon",
            "is the docker daemon running",
            "error during connect",
        ),
    ),
    ("container_name_conflict", ("container name", "already in use")),
)
_CLOSED_FLAGS = (
    "formal_collection_allowed",
    "formal_collection_started",
    "collection_started",
    "training_started",
    "production_training_ready",
)


class _DiagnosticFailure(Exception):
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


def _load_json(path: Path, *, maximum_bytes: int = 1024 * 1024) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum_bytes:
        raise ConfigurationError("v121 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v121 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v121 predecessor JSON must be an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v121 predecessor canonical hash changed")
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
        raise ConfigurationError("v121 requires a non-root host identity")
    if any(name in os.environ for name in _PROVIDER_ENV_NAMES):
        raise ConfigurationError("v121 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v121 requires the default local Docker endpoint")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v121 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v121 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = _git_text("ls-files", "--error-unmatch", "--", relative)
        if tracked != relative:
            raise ConfigurationError("v121 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v119_audit_commit, head],
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
        raise ConfigurationError("v121 requires clean merged origin/main after v119")
    return head


def _validate_static_predecessor(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
) -> dict[str, Any]:
    v118_manifest = load_v118_explicit_inner_inventory_scaffold_manifest(V118_MANIFEST)
    report = _load_json(V118_REPORT)
    progress = _load_json(V118_PROGRESS)
    headroom = _load_json(V118_HEADROOM)
    if (
        _hash_file(V118_MANIFEST) != manifest.v118_manifest_sha256
        or v118_manifest.manifest_hash != manifest.v118_manifest_hash
        or _hash_file(V118_AUTHORIZATION) != manifest.v118_authorization_sha256
        or _hash_file(V118_REPORT) != manifest.v118_report_sha256
        or _hash_file(V118_PROGRESS) != manifest.v118_report_sha256
        or _canonical_hash(report, "report_hash") != manifest.v118_report_hash
        or _canonical_hash(progress, "report_hash") != manifest.v118_report_hash
        or _hash_file(V118_HEADROOM) != manifest.v118_headroom_sha256
        or _canonical_hash(headroom, "preflight_hash") != manifest.v118_headroom_hash
        or _hash_file(V119_AUDIT) != manifest.v119_audit_sha256
    ):
        raise ConfigurationError("v121 audited predecessor binding changed")
    entries = list(V118_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    if (
        directories != manifest.v118_evidence_directory_count
        or files != manifest.v118_evidence_regular_file_count
        or symlinks != manifest.v118_evidence_symlink_count
        or report != progress
        or report.get("identity")
        != "deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1"
        or report.get("status") != "stopped_without_execution_scaffold"
        or report.get("stop_reason") != "RuntimeError"
        or report.get("completed_stages") != []
        or report.get("provider_execution_scaffold_published") is not False
        or report.get("provider_execution_authorized") is not False
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or report.get("dind_cleanup_confirmed") is not False
        or report.get("raw_exception_persisted") is not False
        or any(report.get(name) is not False for name in _CLOSED_FLAGS)
        or headroom.get("status") != "passed"
    ):
        raise ConfigurationError("v121 requires the exact audited v118 terminal state")
    if (
        manifest.frozen_v118_data_volume != "verigym-deepseek-harness-v118-dind-data"
        or manifest.frozen_v118_socket_volume != "verigym-deepseek-harness-v118-dind-socket"
        or manifest.v118_volume_inspection_allowed is not False
        or manifest.v118_volume_mutation_allowed is not False
    ):
        raise ConfigurationError("v121 frozen v118 resource policy changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v121_predecessor_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "v118_manifest_hash": manifest.v118_manifest_hash,
        "v118_report_hash": manifest.v118_report_hash,
        "v118_headroom_hash": manifest.v118_headroom_hash,
        "v119_audit_commit": manifest.v119_audit_commit,
        "v119_post_merge_main_run_id": manifest.v119_post_merge_main_run_id,
        "v119_post_merge_main_all_eight_classes_passed": True,
        "v118_evidence_directory_count": directories,
        "v118_evidence_regular_file_count": files,
        "v118_evidence_symlink_count": symlinks,
        "v118_volumes_inspected": False,
        "v118_volumes_mutated": False,
        "task_archives_read": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _new_output(path: Path) -> Path:
    if path != OUTPUT_ROOT or path.exists() or path.is_symlink():
        raise ConfigurationError("v121 output identity must be new and exact")
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise ConfigurationError("v121 output parent is unsafe")
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path.resolve(strict=True)


def _create_runtime_paths(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
) -> None:
    expected = {
        DIND_DATA_BACKING: manifest.dind_data_backing,
        DIND_SOCKET_BACKING: manifest.dind_socket_backing,
        CONTROL_ROOT: manifest.control_headroom_root,
        DIAGNOSTIC_SCRATCH: manifest.diagnostic_scratch_root,
    }
    if manifest.output_root != str(OUTPUT_ROOT) or DIND_PARENT.exists() or DIND_PARENT.is_symlink():
        raise ConfigurationError("v121 writable identities must be fresh and exact")
    if CONTROL_ROOT.exists() or CONTROL_ROOT.is_symlink():
        raise ConfigurationError("v121 control root must be fresh")
    if DIAGNOSTIC_SCRATCH.exists() or DIAGNOSTIC_SCRATCH.is_symlink():
        raise ConfigurationError("v121 diagnostic scratch root must be fresh")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    CONTROL_ROOT.mkdir(parents=True, mode=0o700)
    DIAGNOSTIC_SCRATCH.mkdir(parents=True, mode=0o700)
    for path, frozen in expected.items():
        if str(path) != frozen or path.is_symlink() or not path.is_dir():
            raise ConfigurationError("v121 runtime path differs from the manifest")
        path.chmod(0o700)
        if next(path.iterdir(), None) is not None:
            raise ConfigurationError("v121 runtime path must start empty")


def _headroom_receipt() -> dict[str, Any]:
    value = materialization_headroom_receipt(
        control_root=CONTROL_ROOT,
        docker_root=DIND_DATA_BACKING,
        scratch_root=DIAGNOSTIC_SCRATCH,
        output_parent=OUTPUT_ROOT.parent,
    )
    base = dict(value)
    base.pop("preflight_hash", None)
    base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v121_headroom_preflight_v1",
            "identity": IDENTITY,
            "all_writable_roots_under_data2": True,
            "host_paths_persisted": False,
        }
    )
    return {**base, "preflight_hash": content_hash(base)}


def _docker_call(
    engine: DockerCliEngine,
    arguments: list[str],
    *,
    timeout_s: int,
    maximum_bytes: int,
) -> EngineResult:
    return engine._invoke(  # noqa: SLF001
        arguments,
        timeout_s=timeout_s,
        max_output_bytes=maximum_bytes,
    )


def _combined_output(result: EngineResult) -> str:
    return f"{result.stderr}\n{result.stdout}".lower()


def _is_not_found(result: EngineResult) -> bool:
    return result.exit_code != 0 and any(
        pattern in _combined_output(result) for pattern in _NOT_FOUND_PATTERNS
    )


def _classify_failure(phase: str, result: EngineResult) -> str:
    if result.timed_out:
        return f"{phase}_timeout"
    if result.output_truncated:
        return "diagnostic_output_bound_exceeded"
    text = _combined_output(result)
    for category, patterns in _CLASSIFICATION_PATTERNS:
        matched = (
            all(pattern in text for pattern in patterns)
            if category == "container_name_conflict"
            else any(pattern in text for pattern in patterns)
        )
        if matched:
            return category
    return f"unclassified_{phase}_failure"


def _result_summary(result: EngineResult, *, prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_exit_code": result.exit_code,
        f"{prefix}_timed_out": result.timed_out,
        f"{prefix}_output_truncated": result.output_truncated,
        f"{prefix}_stdout_bytes": len(result.stdout.encode("utf-8")),
        f"{prefix}_stderr_bytes": len(result.stderr.encode("utf-8")),
    }


def _host_image_receipt(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
) -> dict[str, Any]:
    result = _docker_call(
        engine,
        ["image", "inspect", manifest.dind_image_id],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if result.exit_code != 0 or result.timed_out or result.output_truncated:
        raise _DiagnosticFailure(_classify_failure("host_image_inspect", result))
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _DiagnosticFailure("invalid_host_image_inspect_response") from exc
    image = values[0] if isinstance(values, list) and len(values) == 1 else None
    config = image.get("Config") if isinstance(image, dict) else None
    entrypoint = config.get("Entrypoint") if isinstance(config, dict) else None
    repo_digests = image.get("RepoDigests") if isinstance(image, dict) else None
    digest_bound = isinstance(repo_digests, list) and any(
        isinstance(value, str) and value.endswith(f"@{manifest.dind_repository_digest}")
        for value in repo_digests
    )
    if (
        not isinstance(image, dict)
        or image.get("Id") != manifest.dind_image_id
        or not digest_bound
        or not isinstance(entrypoint, list)
        or len(entrypoint) != 1
        or not isinstance(entrypoint[0], str)
        or Path(entrypoint[0]).name != "dockerd-entrypoint.sh"
    ):
        raise _DiagnosticFailure("host_image_identity_failed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v121_host_image_identity_v1",
        "identity": IDENTITY,
        "status": "passed",
        "dind_image_id": manifest.dind_image_id,
        "dind_repository_digest": manifest.dind_repository_digest,
        "image_id_matched": True,
        "repository_digest_matched": True,
        "official_entrypoint_matched": True,
        "registry_accessed": False,
        "raw_docker_output_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _inspect_volume(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    *,
    name: str,
    role: str,
    backing: Path,
) -> None:
    result = _docker_call(
        engine,
        ["volume", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if result.exit_code != 0 or result.timed_out or result.output_truncated:
        raise _DiagnosticFailure(_classify_failure("volume_inspect", result))
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _DiagnosticFailure("invalid_volume_inspect_response") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise _DiagnosticFailure("invalid_volume_inspect_response")
    value = values[0]
    if (
        value.get("Driver") != "local"
        or value.get("Labels") != {"verigym.owner": IDENTITY, "verigym.role": role}
        or value.get("Options")
        != {"device": str(backing.resolve(strict=True)), "o": "bind", "type": "none"}
    ):
        raise _DiagnosticFailure("bind_backed_volume_identity_failed")


def _create_volume(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    *,
    name: str,
    role: str,
    backing: Path,
) -> None:
    absent = _docker_call(
        engine,
        ["volume", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if absent.exit_code == 0 or not _is_not_found(absent):
        raise _DiagnosticFailure("fresh_volume_precondition_failed")
    created = _docker_call(
        engine,
        [
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
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if (
        created.exit_code != 0
        or created.timed_out
        or created.output_truncated
        or created.stdout.strip() != name
    ):
        raise _DiagnosticFailure(_classify_failure("volume_create", created))
    _inspect_volume(manifest, engine, name=name, role=role, backing=backing)


def _volume_setup_receipt(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v121_volume_setup_v1",
        "identity": IDENTITY,
        "status": "passed",
        "data_volume": manifest.dind_data_volume,
        "socket_volume": manifest.dind_socket_volume,
        "bind_backed": True,
        "fresh": True,
        "backing_roots_under_data2": True,
        "host_paths_persisted": False,
        "v118_volumes_inspected": False,
        "v118_volumes_reused": False,
        "raw_docker_output_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _outer_controls_valid(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    name: str,
) -> bool:
    result = _docker_call(
        engine,
        ["container", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if result.exit_code != 0 or result.timed_out or result.output_truncated:
        return False
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return False
    value = values[0]
    host = value.get("HostConfig")
    config = value.get("Config")
    mounts = value.get("Mounts")
    if not isinstance(host, dict) or not isinstance(config, dict) or not isinstance(mounts, list):
        return False
    expected_mounts = {
        "/var/lib/docker": (manifest.dind_data_volume, True),
        "/var/run": (manifest.dind_socket_volume, True),
        "/verigym-host-sentinel": (str(CONTROL_ROOT.resolve(strict=True)), False),
    }
    observed: dict[str, tuple[str, bool]] = {}
    for mount in mounts:
        if not isinstance(mount, dict):
            return False
        destination = mount.get("Destination")
        if destination not in expected_mounts:
            return False
        source = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
        if not isinstance(source, str) or not isinstance(mount.get("RW"), bool):
            return False
        observed[destination] = (source, mount["RW"])
    environment = config.get("Env")
    return (
        value.get("Image") == manifest.dind_image_id
        and host.get("Privileged") is True
        and host.get("NetworkMode") == "none"
        and host.get("PidsLimit") == 32768
        and observed == expected_mounts
        and isinstance(environment, list)
        and "DOCKER_TLS_CERTDIR=" in environment
    )


def _startup_command(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    name: str,
) -> list[str]:
    return [
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"verigym.owner={IDENTITY}",
        "--label",
        "verigym.role=diagnostic-daemon",
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
        f"type=bind,src={CONTROL_ROOT.resolve(strict=True)},dst=/verigym-host-sentinel,readonly",
        manifest.dind_image_id,
        "--storage-driver=vfs",
        "--iptables=false",
        "--ip6tables=false",
        "--bridge=none",
        f"--group={os.getgid()}",
    ]


def _run_startup_diagnostic(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    name: str,
) -> dict[str, Any]:
    started = _docker_call(
        engine,
        _startup_command(manifest, name),
        timeout_s=manifest.startup_command_timeout_seconds,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    summary = _result_summary(started, prefix="docker_run")
    container_shape = "unavailable"
    if (
        started.exit_code != 0
        or started.timed_out
        or started.output_truncated
        or _CONTAINER_ID.fullmatch(started.stdout.strip()) is None
    ):
        category = _classify_failure("docker_run", started)
        if started.exit_code == 0 and not started.timed_out and not started.output_truncated:
            category = "invalid_docker_run_response"
        return _seal_startup_receipt(
            manifest,
            status="startup_failed",
            category=category,
            readiness_poll_count=0,
            outer_controls_valid=False,
            daemon_ready=False,
            server_version_valid=False,
            storage_driver_valid=False,
            default_runtime_valid=False,
            container_shape=container_shape,
            result_summary=summary,
        )
    container_shape = "immutable_id"
    controls_valid = _outer_controls_valid(manifest, engine, name)
    if not controls_valid:
        return _seal_startup_receipt(
            manifest,
            status="startup_failed",
            category="outer_container_controls_invalid",
            readiness_poll_count=0,
            outer_controls_valid=False,
            daemon_ready=False,
            server_version_valid=False,
            storage_driver_valid=False,
            default_runtime_valid=False,
            container_shape=container_shape,
            result_summary=summary,
        )
    deadline = time.monotonic() + manifest.readiness_timeout_seconds
    polls = 0
    metadata: dict[str, Any] | None = None
    readiness_failure = "dind_readiness_timeout"
    while time.monotonic() < deadline and polls < 24:
        polls += 1
        ready = _docker_call(
            engine,
            ["exec", name, "docker", "info", "--format", "{{json .}}"],
            timeout_s=5,
            maximum_bytes=manifest.maximum_diagnostic_output_bytes,
        )
        if ready.output_truncated:
            readiness_failure = "diagnostic_output_bound_exceeded"
            break
        if ready.exit_code == 0 and not ready.timed_out:
            try:
                candidate = json.loads(ready.stdout)
            except json.JSONDecodeError:
                readiness_failure = "invalid_dind_info_response"
                break
            if not isinstance(candidate, dict):
                readiness_failure = "invalid_dind_info_response"
                break
            metadata = candidate
            break
        time.sleep(0.25)
    if metadata is None:
        return _seal_startup_receipt(
            manifest,
            status="startup_failed",
            category=readiness_failure,
            readiness_poll_count=polls,
            outer_controls_valid=True,
            daemon_ready=False,
            server_version_valid=False,
            storage_driver_valid=False,
            default_runtime_valid=False,
            container_shape=container_shape,
            result_summary=summary,
        )
    version = _docker_call(
        engine,
        ["exec", name, "docker", "version", "--format", "{{.Server.Version}}"],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    version_valid = (
        version.exit_code == 0
        and not version.timed_out
        and not version.output_truncated
        and version.stdout.strip() == manifest.dind_server_version
    )
    driver_valid = metadata.get("Driver") == manifest.dind_storage_driver
    runtime_valid = metadata.get("DefaultRuntime") == manifest.dind_default_runtime
    daemon_identity_valid = version_valid and driver_valid and runtime_valid
    return _seal_startup_receipt(
        manifest,
        status="passed" if daemon_identity_valid else "startup_failed",
        category=("dind_ready" if daemon_identity_valid else "dind_runtime_identity_failed"),
        readiness_poll_count=polls,
        outer_controls_valid=True,
        daemon_ready=True,
        server_version_valid=version_valid,
        storage_driver_valid=driver_valid,
        default_runtime_valid=runtime_valid,
        container_shape=container_shape,
        result_summary=summary,
    )


def _seal_startup_receipt(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    *,
    status: str,
    category: str,
    readiness_poll_count: int,
    outer_controls_valid: bool,
    daemon_ready: bool,
    server_version_valid: bool,
    storage_driver_valid: bool,
    default_runtime_valid: bool,
    container_shape: str,
    result_summary: Mapping[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v121_startup_diagnostic_v1",
        "identity": IDENTITY,
        "status": status,
        "diagnostic_category": category,
        "startup_attempt_limit": manifest.startup_attempt_limit,
        "startup_attempt_count": 1,
        "startup_command_timeout_seconds": manifest.startup_command_timeout_seconds,
        "readiness_timeout_seconds": manifest.readiness_timeout_seconds,
        "maximum_diagnostic_output_bytes": manifest.maximum_diagnostic_output_bytes,
        "readiness_poll_count": readiness_poll_count,
        "docker_run_stdout_shape": container_shape,
        "outer_controls_valid": outer_controls_valid,
        "daemon_ready": daemon_ready,
        "server_version_valid": server_version_valid,
        "storage_driver_valid": storage_driver_valid,
        "default_runtime_valid": default_runtime_valid,
        **dict(result_summary),
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "container_identity_persisted": False,
        "host_paths_persisted": False,
        "provider_request_started": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _remove_named_container(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    name: str,
) -> tuple[bool, str]:
    inspected = _docker_call(
        engine,
        ["container", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if _is_not_found(inspected):
        return True, "already_absent"
    if inspected.exit_code != 0 or inspected.timed_out or inspected.output_truncated:
        return False, _classify_failure("container_inspect", inspected)
    removed = _docker_call(
        engine,
        ["rm", "--force", name],
        timeout_s=manifest.cleanup_command_timeout_seconds,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    verified = _docker_call(
        engine,
        ["container", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if removed.exit_code == 0 and not removed.timed_out and _is_not_found(verified):
        return True, "removed"
    return False, _classify_failure("container_remove", removed)


def _owned_volume_for_cleanup(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    *,
    name: str,
    role: str,
    backing: Path,
    attempted: bool,
) -> tuple[bool, str]:
    if not attempted:
        return False, "not_attempted"
    inspected = _docker_call(
        engine,
        ["volume", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if _is_not_found(inspected):
        return False, "already_absent"
    if inspected.exit_code != 0 or inspected.timed_out or inspected.output_truncated:
        return False, _classify_failure("volume_inspect", inspected)
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return False, "invalid_volume_inspect_response"
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return False, "invalid_volume_inspect_response"
    value = values[0]
    if (
        value.get("Driver") != "local"
        or value.get("Labels") != {"verigym.owner": IDENTITY, "verigym.role": role}
        or value.get("Options")
        != {"device": str(backing.resolve(strict=True)), "o": "bind", "type": "none"}
    ):
        return False, "unowned_volume_preserved"
    return True, "owned"


def _remove_volume(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    *,
    name: str,
    role: str,
    backing: Path,
    attempted: bool,
) -> tuple[bool, str]:
    if not attempted:
        return True, "not_attempted"
    inspected = _docker_call(
        engine,
        ["volume", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if _is_not_found(inspected):
        return True, "already_absent"
    if inspected.exit_code != 0 or inspected.timed_out or inspected.output_truncated:
        return False, _classify_failure("volume_inspect", inspected)
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return False, "invalid_volume_inspect_response"
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return False, "invalid_volume_inspect_response"
    value = values[0]
    if (
        value.get("Driver") != "local"
        or value.get("Labels") != {"verigym.owner": IDENTITY, "verigym.role": role}
        or value.get("Options")
        != {"device": str(backing.resolve(strict=True)), "o": "bind", "type": "none"}
    ):
        return False, "unowned_volume_preserved"
    removed = _docker_call(
        engine,
        ["volume", "rm", name],
        timeout_s=manifest.cleanup_command_timeout_seconds,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    verified = _docker_call(
        engine,
        ["volume", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if removed.exit_code == 0 and not removed.timed_out and _is_not_found(verified):
        return True, "removed"
    return False, _classify_failure("volume_remove", removed)


def _backing_restored(path: Path) -> bool:
    try:
        metadata = path.stat()
        return (
            not path.is_symlink()
            and path.is_dir()
            and next(path.iterdir(), None) is None
            and stat.S_IMODE(metadata.st_mode) == 0o700
            and metadata.st_uid == os.getuid()
            and metadata.st_gid == os.getgid()
        )
    except OSError:
        return False


def _cleanup(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    engine: DockerCliEngine,
    *,
    main_name: str,
    data_attempted: bool,
    socket_attempted: bool,
) -> dict[str, Any]:
    main_removed, main_category = _remove_named_container(manifest, engine, main_name)
    data_owned, _data_precleanup_category = _owned_volume_for_cleanup(
        manifest,
        engine,
        name=manifest.dind_data_volume,
        role="data",
        backing=DIND_DATA_BACKING,
        attempted=data_attempted,
    )
    socket_owned, _socket_precleanup_category = _owned_volume_for_cleanup(
        manifest,
        engine,
        name=manifest.dind_socket_volume,
        role="socket",
        backing=DIND_SOCKET_BACKING,
        attempted=socket_attempted,
    )
    helper_attempted = data_owned or socket_owned
    helper_status = "not_required"
    helper_exit_code: int | None = None
    helper_removed = True
    if helper_attempted:
        helper_name = f"verigym-dind-v121-cleanup-{secrets.token_hex(10)}"
        mounts: list[str] = []
        scripts: list[str] = []
        if data_owned:
            mounts.extend(
                [
                    "--mount",
                    f"type=volume,src={manifest.dind_data_volume},dst=/verigym-data",
                ]
            )
            scripts.extend(
                [
                    "rm -rf -- /verigym-data/* /verigym-data/.[!.]* /verigym-data/..?*",
                    f"chown {os.getuid()}:{os.getgid()} /verigym-data",
                    "chmod 0700 /verigym-data",
                ]
            )
        if socket_owned:
            mounts.extend(
                [
                    "--mount",
                    f"type=volume,src={manifest.dind_socket_volume},dst=/verigym-socket",
                ]
            )
            scripts.extend(
                [
                    "rm -rf -- /verigym-socket/* /verigym-socket/.[!.]* /verigym-socket/..?*",
                    f"chown {os.getuid()}:{os.getgid()} /verigym-socket",
                    "chmod 0700 /verigym-socket",
                ]
            )
        helper = _docker_call(
            engine,
            [
                "run",
                "--rm",
                "--name",
                helper_name,
                "--label",
                f"verigym.owner={IDENTITY}",
                "--label",
                "verigym.role=diagnostic-cleanup",
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
                "; ".join(scripts),
            ],
            timeout_s=manifest.cleanup_command_timeout_seconds,
            maximum_bytes=manifest.maximum_diagnostic_output_bytes,
        )
        helper_exit_code = helper.exit_code
        helper_status = (
            "passed"
            if helper.exit_code == 0 and not helper.timed_out and not helper.output_truncated
            else _classify_failure("cleanup_helper", helper)
        )
        helper_removed, helper_remove_category = _remove_named_container(
            manifest, engine, helper_name
        )
        if not helper_removed:
            helper_status = helper_remove_category
    data_volume_removed, data_volume_category = _remove_volume(
        manifest,
        engine,
        name=manifest.dind_data_volume,
        role="data",
        backing=DIND_DATA_BACKING,
        attempted=data_attempted,
    )
    socket_volume_removed, socket_volume_category = _remove_volume(
        manifest,
        engine,
        name=manifest.dind_socket_volume,
        role="socket",
        backing=DIND_SOCKET_BACKING,
        attempted=socket_attempted,
    )
    data_restored = _backing_restored(DIND_DATA_BACKING)
    socket_restored = _backing_restored(DIND_SOCKET_BACKING)
    passed = all(
        (
            main_removed,
            helper_removed,
            helper_status in {"passed", "not_required"},
            data_volume_removed,
            socket_volume_removed,
            data_restored,
            socket_restored,
        )
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v121_cleanup_v1",
        "identity": IDENTITY,
        "status": "passed" if passed else "cleanup_unconfirmed",
        "main_container_removed": main_removed,
        "main_container_cleanup_category": main_category,
        "cleanup_helper_attempted": helper_attempted,
        "cleanup_helper_exit_code": helper_exit_code,
        "cleanup_helper_status": helper_status,
        "cleanup_helper_container_removed": helper_removed,
        "data_volume_removed": data_volume_removed,
        "data_volume_cleanup_category": data_volume_category,
        "socket_volume_removed": socket_volume_removed,
        "socket_volume_cleanup_category": socket_volume_category,
        "data_backing_empty_and_ownership_restored": data_restored,
        "socket_backing_empty_and_ownership_restored": socket_restored,
        "volume_removal_independent_of_cleanup_helper": True,
        "v118_volumes_inspected": False,
        "v118_volumes_mutated": False,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "container_identity_persisted": False,
        "host_paths_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _base_report(
    manifest: DeepSeekHarnessV121BoundedDindStartDiagnosticManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v121_diagnostic_report_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "diagnostic_complete": False,
        "startup_attempt_limit": 1,
        "startup_attempt_count": 0,
        "startup_diagnostic_category": None,
        "dind_ready": False,
        "cleanup_confirmed": False,
        "predecessor_preflight_hash": None,
        "headroom_preflight_hash": None,
        "host_image_identity_hash": None,
        "volume_setup_receipt_hash": None,
        "startup_diagnostic_receipt_hash": None,
        "cleanup_receipt_hash": None,
        "task_archives_read": False,
        "tasks_materialized": False,
        "base_reference_verification_started": False,
        "harness_controller_started": False,
        "docker_networks_created": False,
        "registry_accessed": False,
        "provider_credentials_available": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "v118_volumes_inspected": False,
        "v118_volumes_mutated": False,
        "raw_docker_output_persisted": False,
        "raw_docker_output_hashed": False,
        "raw_exception_persisted": False,
        "container_identity_persisted": False,
        "host_paths_persisted_in_diagnostics": False,
        "requires_independent_v122_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }


def _write_report(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(report)
    base.pop("report_hash", None)
    value = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(root / "diagnostic-progress.json", value)
    atomic_dump_json(root / "diagnostic-report.json", value)
    return value


def diagnose(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_execution_boundary(arguments)
    manifest = load_v121_bounded_dind_start_diagnostic_manifest(arguments.manifest)
    source_commit = _require_clean_merged_main(manifest)
    predecessor = _validate_static_predecessor(manifest)
    root = _new_output(arguments.output)
    report = _base_report(
        manifest,
        source_commit=source_commit,
        post_merge_main_run_id=arguments.post_merge_main_run_id,
    )
    atomic_dump_json(root / "predecessor-preflight.json", predecessor)
    report["predecessor_preflight_hash"] = predecessor["receipt_hash"]
    _write_report(root, report)

    engine = DockerCliEngine()
    data_attempted = False
    socket_attempted = False
    main_name = f"verigym-dind-v121-{secrets.token_hex(10)}"
    failure_category: str | None = None
    startup: dict[str, Any] | None = None
    cleanup: dict[str, Any] | None = None
    try:
        _create_runtime_paths(manifest)
        headroom = _headroom_receipt()
        atomic_dump_json(root / "headroom-preflight.json", headroom)
        report["headroom_preflight_hash"] = headroom["preflight_hash"]
        if headroom["status"] != "passed":
            raise _DiagnosticFailure("insufficient_headroom")
        image = _host_image_receipt(manifest, engine)
        atomic_dump_json(root / "host-image-identity.json", image)
        report["host_image_identity_hash"] = image["receipt_hash"]
        data_attempted = True
        _create_volume(
            manifest,
            engine,
            name=manifest.dind_data_volume,
            role="data",
            backing=DIND_DATA_BACKING,
        )
        socket_attempted = True
        _create_volume(
            manifest,
            engine,
            name=manifest.dind_socket_volume,
            role="socket",
            backing=DIND_SOCKET_BACKING,
        )
        volume_setup = _volume_setup_receipt(manifest)
        atomic_dump_json(root / "volume-setup-receipt.json", volume_setup)
        report["volume_setup_receipt_hash"] = volume_setup["receipt_hash"]
        report["status"] = "bounded_startup_attempt"
        _write_report(root, report)
        startup = _run_startup_diagnostic(manifest, engine, main_name)
        atomic_dump_json(root / "startup-diagnostic-receipt.json", startup)
        report.update(
            {
                "startup_attempt_count": 1,
                "startup_diagnostic_category": startup["diagnostic_category"],
                "startup_diagnostic_receipt_hash": startup["receipt_hash"],
                "dind_ready": startup["status"] == "passed",
            }
        )
    except _DiagnosticFailure as exc:
        failure_category = exc.category
    except Exception:
        failure_category = "unexpected_controller_failure"
    finally:
        try:
            cleanup = _cleanup(
                manifest,
                engine,
                main_name=main_name,
                data_attempted=data_attempted,
                socket_attempted=socket_attempted,
            )
        except Exception:
            cleanup = {
                "schema_version": "1.0",
                "format_id": "verigym_deepseek_harness_hwe_v121_cleanup_v1",
                "identity": IDENTITY,
                "status": "cleanup_unconfirmed",
                "cleanup_controller_failure": True,
                "raw_exception_persisted": False,
                "provider_calls": 0,
            }
            cleanup["receipt_hash"] = content_hash(cleanup)
        atomic_dump_json(root / "cleanup-receipt.json", cleanup)
        engine.close()

    report["cleanup_receipt_hash"] = cleanup["receipt_hash"]
    report["cleanup_confirmed"] = cleanup["status"] == "passed"
    if failure_category is not None:
        report.update(
            {
                "status": "stopped_before_diagnostic_completion",
                "stop_reason": failure_category,
                "diagnostic_complete": False,
            }
        )
    elif startup is None:
        report.update(
            {
                "status": "stopped_before_diagnostic_completion",
                "stop_reason": "startup_receipt_missing",
                "diagnostic_complete": False,
            }
        )
    elif cleanup["status"] != "passed":
        report.update(
            {
                "status": "stopped_cleanup_unconfirmed",
                "stop_reason": "cleanup_unconfirmed",
                "diagnostic_complete": True,
            }
        )
    else:
        report.update(
            {
                "status": "completed_pending_independent_v122_audit",
                "stop_reason": None,
                "diagnostic_complete": True,
            }
        )
    return _write_report(root, report)


def main(argv: Sequence[str] | None = None) -> int:
    report = diagnose(_parser().parse_args(argv))
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_complete": report["diagnostic_complete"],
                "startup_diagnostic_category": report["startup_diagnostic_category"],
                "dind_ready": report["dind_ready"],
                "cleanup_confirmed": report["cleanup_confirmed"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["diagnostic_complete"] and report["cleanup_confirmed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
