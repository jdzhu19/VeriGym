#!/usr/bin/env python3
"""Run one provider-free, content-free probe of the inner DinD identity fields."""

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
    DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    load_v121_bounded_dind_start_diagnostic_manifest,
    load_v123_bounded_dind_identity_probe_manifest,
)
from verigym.hwe.materialization_preflight import (  # noqa: E402
    materialization_headroom_receipt,
)
from verigym.runtimes.docker.engine import DockerCliEngine, EngineResult  # noqa: E402

IDENTITY = "deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1"
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V123_BOUNDED_DIND_IDENTITY_PROBE"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v123_bounded_dind_identity_probe_v1.json"
)
V121_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v121_bounded_dind_start_diagnostic_v1.json"
)
V121_AUTHORIZATION = _REPOSITORY / (
    "docs/audits/2026-09-04_deepseek-harness-v121-bounded-dind-start-authorization.md"
)
V122_AUDIT = _REPOSITORY / "docs/audits/2026-09-04_deepseek-harness-v122-v121-result.md"
V121_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1"
)
V121_FILES = {
    "report": V121_ROOT / "diagnostic-report.json",
    "progress": V121_ROOT / "diagnostic-progress.json",
    "startup": V121_ROOT / "startup-diagnostic-receipt.json",
    "cleanup": V121_ROOT / "cleanup-receipt.json",
    "host_image": V121_ROOT / "host-image-identity.json",
    "headroom": V121_ROOT / "headroom-preflight.json",
    "volume_setup": V121_ROOT / "volume-setup-receipt.json",
    "predecessor": V121_ROOT / "predecessor-preflight.json",
}
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1"
)
DIND_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v123")
DIND_DATA_BACKING = DIND_PARENT / "data"
DIND_SOCKET_BACKING = DIND_PARENT / "socket"
CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v123-control")
DIAGNOSTIC_SCRATCH = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v123-scratch")

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
    "configs/training/qwen35_hwe_deepseek_harness_v123_bounded_dind_identity_probe_v1.json",
    "docs/audits/2026-09-04_deepseek-harness-v122-v121-result.md",
    "docs/audits/2026-09-04_deepseek-harness-v123-bounded-dind-identity-probe-authorization.md",
    "integrations/verigym-deepseek-harness/tests/test_v123_bounded_dind_identity_probe.py",
    "scripts/run_hwe_deepseek_harness_v123_bounded_dind_identity_probe.py",
    "src/verigym/hwe/deepseek_harness_campaign.py",
    "tests/unit/test_hwe_deepseek_harness_campaign.py",
)
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_NOT_FOUND = ("no such container", "no such object", "no such volume", "not found")
_CLOSED_FLAGS = (
    "formal_collection_allowed",
    "formal_collection_started",
    "collection_started",
    "training_started",
    "production_training_ready",
)


class _ProbeFailure(Exception):
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
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ConfigurationError("v123 predecessor JSON path is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v123 predecessor JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("v123 predecessor JSON must be an object")
    return value


def _canonical_hash(value: Mapping[str, Any], field: str) -> str:
    base = dict(value)
    claimed = base.pop(field, None)
    observed = content_hash(base)
    if claimed != observed:
        raise ConfigurationError("v123 predecessor canonical hash changed")
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
        raise ConfigurationError("v123 requires a non-root host identity")
    if any(name in os.environ for name in _PROVIDER_ENV_NAMES):
        raise ConfigurationError("v123 refuses a provider configuration environment")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v123 requires the default local Docker endpoint")
    if arguments.manifest != MANIFEST or arguments.output != OUTPUT_ROOT:
        raise ConfigurationError("v123 manifest and output identities are exact")
    if arguments.post_merge_main_run_id < 1:
        raise ConfigurationError("v123 requires a positive post-merge main run ID")


def _require_clean_merged_main(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
) -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        if _git_text("ls-files", "--error-unmatch", "--", relative) != relative:
            raise ConfigurationError("v123 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=True)
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    upstream = _git_text("rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest.v122_audit_commit, head],
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
        raise ConfigurationError("v123 requires clean merged origin/main after v122")
    return head


def _validate_static_predecessor(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
) -> dict[str, Any]:
    v121_manifest = load_v121_bounded_dind_start_diagnostic_manifest(V121_MANIFEST)
    values = {name: _load_json(path) for name, path in V121_FILES.items()}
    report = values["report"]
    if (
        _hash_file(V121_MANIFEST) != manifest.v121_manifest_sha256
        or v121_manifest.manifest_hash != manifest.v121_manifest_hash
        or _hash_file(V121_AUTHORIZATION) != manifest.v121_authorization_sha256
        or _hash_file(V122_AUDIT) != manifest.v122_audit_sha256
        or _hash_file(V121_FILES["report"]) != manifest.v121_report_sha256
        or _hash_file(V121_FILES["progress"]) != manifest.v121_report_sha256
        or _canonical_hash(report, "report_hash") != manifest.v121_report_hash
        or _canonical_hash(values["progress"], "report_hash") != manifest.v121_report_hash
        or _hash_file(V121_FILES["startup"]) != manifest.v121_startup_sha256
        or _canonical_hash(values["startup"], "receipt_hash") != manifest.v121_startup_hash
        or _hash_file(V121_FILES["cleanup"]) != manifest.v121_cleanup_sha256
        or _canonical_hash(values["cleanup"], "receipt_hash") != manifest.v121_cleanup_hash
        or _hash_file(V121_FILES["host_image"]) != manifest.v121_host_image_sha256
        or _canonical_hash(values["host_image"], "receipt_hash") != manifest.v121_host_image_hash
        or _hash_file(V121_FILES["headroom"]) != manifest.v121_headroom_sha256
        or _canonical_hash(values["headroom"], "preflight_hash") != manifest.v121_headroom_hash
        or _hash_file(V121_FILES["volume_setup"]) != manifest.v121_volume_setup_sha256
        or _canonical_hash(values["volume_setup"], "receipt_hash")
        != manifest.v121_volume_setup_hash
        or _hash_file(V121_FILES["predecessor"]) != manifest.v121_predecessor_sha256
        or _canonical_hash(values["predecessor"], "receipt_hash") != manifest.v121_predecessor_hash
    ):
        raise ConfigurationError("v123 audited predecessor binding changed")
    entries = list(V121_ROOT.rglob("*"))
    directories = 1 + sum(path.is_dir() and not path.is_symlink() for path in entries)
    files = sum(path.is_file() and not path.is_symlink() for path in entries)
    symlinks = sum(path.is_symlink() for path in entries)
    startup = values["startup"]
    cleanup = values["cleanup"]
    if (
        directories != manifest.v121_evidence_directory_count
        or files != manifest.v121_evidence_regular_file_count
        or symlinks != manifest.v121_evidence_symlink_count
        or report != values["progress"]
        or report.get("identity") != "deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1"
        or report.get("status") != "completed_pending_independent_v122_audit"
        or report.get("diagnostic_complete") is not True
        or report.get("dind_ready") is not False
        or report.get("cleanup_confirmed") is not True
        or report.get("startup_attempt_count") != 1
        or report.get("startup_attempt_limit") != 1
        or report.get("provider_request_started") is not False
        or report.get("provider_calls") != 0
        or report.get("model_process_count") != 0
        or any(report.get(name) is not False for name in _CLOSED_FLAGS)
        or startup.get("status") != "startup_failed"
        or startup.get("diagnostic_category") != "dind_runtime_identity_failed"
        or startup.get("daemon_ready") is not True
        or startup.get("server_version_valid") is not False
        or startup.get("storage_driver_valid") is not False
        or startup.get("default_runtime_valid") is not False
        or cleanup.get("status") != "passed"
        or any(
            values[name].get("status") != "passed"
            for name in values
            if name not in {"report", "progress", "startup"}
        )
        or manifest.predecessor_volume_inspection_allowed is not False
        or manifest.predecessor_volume_mutation_allowed is not False
    ):
        raise ConfigurationError("v123 requires the exact audited v121 terminal state")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v123_predecessor_preflight_v1",
        "identity": IDENTITY,
        "status": "passed",
        "v121_manifest_hash": manifest.v121_manifest_hash,
        "v121_report_hash": manifest.v121_report_hash,
        "v121_startup_hash": manifest.v121_startup_hash,
        "v121_cleanup_hash": manifest.v121_cleanup_hash,
        "v122_audit_commit": manifest.v122_audit_commit,
        "v122_post_merge_main_run_id": manifest.v122_post_merge_main_run_id,
        "v122_post_merge_main_all_eight_classes_passed": True,
        "v121_evidence_directory_count": directories,
        "v121_evidence_regular_file_count": files,
        "v121_evidence_symlink_count": symlinks,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "task_archives_read": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _new_output(path: Path) -> Path:
    if path != OUTPUT_ROOT or path.exists() or path.is_symlink():
        raise ConfigurationError("v123 output identity must be new and exact")
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise ConfigurationError("v123 output parent is unsafe")
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path.resolve(strict=True)


def _create_runtime_paths(manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest) -> None:
    expected = {
        DIND_DATA_BACKING: manifest.dind_data_backing,
        DIND_SOCKET_BACKING: manifest.dind_socket_backing,
        CONTROL_ROOT: manifest.control_headroom_root,
        DIAGNOSTIC_SCRATCH: manifest.diagnostic_scratch_root,
    }
    if manifest.output_root != str(OUTPUT_ROOT) or DIND_PARENT.exists() or DIND_PARENT.is_symlink():
        raise ConfigurationError("v123 writable identities must be fresh and exact")
    if CONTROL_ROOT.exists() or CONTROL_ROOT.is_symlink():
        raise ConfigurationError("v123 control root must be fresh")
    if DIAGNOSTIC_SCRATCH.exists() or DIAGNOSTIC_SCRATCH.is_symlink():
        raise ConfigurationError("v123 diagnostic scratch root must be fresh")
    DIND_DATA_BACKING.mkdir(parents=True, mode=0o700)
    DIND_SOCKET_BACKING.mkdir(mode=0o700)
    CONTROL_ROOT.mkdir(parents=True, mode=0o700)
    DIAGNOSTIC_SCRATCH.mkdir(parents=True, mode=0o700)
    for path, frozen in expected.items():
        if str(path) != frozen or path.is_symlink() or not path.is_dir():
            raise ConfigurationError("v123 runtime path differs from the manifest")
        path.chmod(0o700)
        if next(path.iterdir(), None) is not None:
            raise ConfigurationError("v123 runtime path must start empty")


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
            "format_id": "verigym_deepseek_harness_hwe_v123_headroom_preflight_v1",
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
        pattern in _combined_output(result) for pattern in _NOT_FOUND
    )


def _classify_failure(phase: str, result: EngineResult) -> str:
    if result.timed_out:
        return f"{phase}_timeout"
    if result.output_truncated:
        return "diagnostic_output_bound_exceeded"
    text = _combined_output(result)
    patterns = (
        ("permission_denied", ("permission denied", "access denied", "operation not permitted")),
        ("no_space_left", ("no space left on device", "disk quota exceeded")),
        ("daemon_unavailable", ("cannot connect to the docker daemon", "error during connect")),
        ("oci_runtime_create_failed", ("oci runtime create failed", "runc create failed")),
    )
    for category, needles in patterns:
        if any(needle in text for needle in needles):
            return category
    return f"unclassified_{phase}_failure"


def _summary(result: EngineResult, prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_exit_code": result.exit_code,
        f"{prefix}_timed_out": result.timed_out,
        f"{prefix}_output_truncated": result.output_truncated,
        f"{prefix}_stdout_bytes": len(result.stdout.encode()),
        f"{prefix}_stderr_bytes": len(result.stderr.encode()),
    }


def _host_image_receipt(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    engine: DockerCliEngine,
) -> dict[str, Any]:
    result = _docker_call(
        engine,
        ["image", "inspect", manifest.dind_image_id],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if result.exit_code != 0 or result.timed_out or result.output_truncated:
        raise _ProbeFailure(_classify_failure("host_image_inspect", result))
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _ProbeFailure("invalid_host_image_inspect_response") from exc
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
        raise _ProbeFailure("host_image_identity_failed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v123_host_image_identity_v1",
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


def _volume_matches(value: Any, *, name: str, role: str, backing: Path) -> bool:
    return (
        isinstance(value, dict)
        and value.get("Name") == name
        and value.get("Driver") == "local"
        and value.get("Labels") == {"verigym.owner": IDENTITY, "verigym.role": role}
        and value.get("Options")
        == {"device": str(backing.resolve(strict=True)), "o": "bind", "type": "none"}
    )


def _inspect_volume(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    engine: DockerCliEngine,
    *,
    name: str,
    role: str,
    backing: Path,
) -> bool:
    result = _docker_call(
        engine,
        ["volume", "inspect", name],
        timeout_s=30,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    if result.exit_code != 0 or result.timed_out or result.output_truncated:
        return False
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(values, list)
        and len(values) == 1
        and _volume_matches(values[0], name=name, role=role, backing=backing)
    )


def _create_volume(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
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
        raise _ProbeFailure("fresh_volume_precondition_failed")
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
        or not _inspect_volume(manifest, engine, name=name, role=role, backing=backing)
    ):
        raise _ProbeFailure(_classify_failure("volume_create", created))


def _volume_setup_receipt(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v123_volume_setup_v1",
        "identity": IDENTITY,
        "status": "passed",
        "data_volume": manifest.dind_data_volume,
        "socket_volume": manifest.dind_socket_volume,
        "bind_backed": True,
        "fresh": True,
        "backing_roots_under_data2": True,
        "host_paths_persisted": False,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_reused": False,
        "raw_docker_output_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _outer_controls_valid(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
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
    expected = {
        "/var/lib/docker": (manifest.dind_data_volume, True),
        "/var/run": (manifest.dind_socket_volume, True),
        "/verigym-host-sentinel": (str(CONTROL_ROOT.resolve(strict=True)), False),
    }
    observed: dict[str, tuple[str, bool]] = {}
    for mount in mounts:
        if not isinstance(mount, dict) or mount.get("Destination") not in expected:
            return False
        source = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
        if not isinstance(source, str) or not isinstance(mount.get("RW"), bool):
            return False
        observed[mount["Destination"]] = (source, mount["RW"])
    environment = config.get("Env")
    return (
        value.get("Image") == manifest.dind_image_id
        and host.get("Privileged") is True
        and host.get("NetworkMode") == "none"
        and host.get("PidsLimit") == 32768
        and observed == expected
        and isinstance(environment, list)
        and "DOCKER_TLS_CERTDIR=" in environment
    )


def _startup_command(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
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
        "verigym.role=identity-probe-daemon",
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


def _legacy_category(result: EngineResult) -> str:
    if result.timed_out:
        return "timeout"
    if result.output_truncated:
        return "output_bound_exceeded"
    if result.exit_code == 0:
        return "success"
    value = _combined_output(result)
    if any(pattern in value for pattern in ("template", "can't evaluate field", "executing")):
        return "formatter_failure"
    if any(pattern in value for pattern in ("cannot connect", "error during connect")):
        return "daemon_connect_failure"
    if any(pattern in value for pattern in ("client is newer", "api version", "version mismatch")):
        return "api_negotiation_failure"
    return "other_command_failure"


def _seal_probe_receipt(base: dict[str, Any]) -> dict[str, Any]:
    fixed = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v123_identity_probe_v1",
        "identity": IDENTITY,
        "startup_attempt_count": 1,
        "startup_attempt_limit": 1,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "raw_exception_persisted": False,
        "container_identity_persisted": False,
        "host_paths_persisted": False,
        "provider_request_started": False,
        "provider_calls": 0,
    }
    value = {**fixed, **base}
    return {**value, "receipt_hash": content_hash(value)}


def _run_identity_probe(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    engine: DockerCliEngine,
    name: str,
) -> dict[str, Any]:
    started = _docker_call(
        engine,
        _startup_command(manifest, name),
        timeout_s=manifest.startup_command_timeout_seconds,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    common: dict[str, Any] = {
        **_summary(started, "docker_run"),
        "docker_run_stdout_shape": "unavailable",
        "outer_controls_valid": False,
        "daemon_ready": False,
        "readiness_poll_count": 0,
        "json_info_server_version_present": False,
        "json_info_driver_present": False,
        "json_info_default_runtime_present": False,
        "json_info_server_version_equal": False,
        "json_info_driver_equal": False,
        "json_info_default_runtime_equal": False,
        "explicit_info_exit_code": None,
        "explicit_info_timed_out": False,
        "explicit_info_output_truncated": False,
        "explicit_info_stdout_bytes": 0,
        "explicit_info_stderr_bytes": 0,
        "explicit_info_value_count": 0,
        "explicit_info_server_version_equal": False,
        "explicit_info_driver_equal": False,
        "explicit_info_default_runtime_equal": False,
        "legacy_version_exit_code": None,
        "legacy_version_timed_out": False,
        "legacy_version_output_truncated": False,
        "legacy_version_stdout_bytes": 0,
        "legacy_version_stderr_bytes": 0,
        "legacy_version_category": "not_attempted",
        "identity_qualified": False,
    }
    if (
        started.exit_code != 0
        or started.timed_out
        or started.output_truncated
        or _CONTAINER_ID.fullmatch(started.stdout.strip()) is None
    ):
        common.update(
            status="probe_failed",
            diagnostic_category=_classify_failure("docker_run", started),
        )
        return _seal_probe_receipt(common)
    common["docker_run_stdout_shape"] = "immutable_id"
    if not _outer_controls_valid(manifest, engine, name):
        common.update(status="probe_failed", diagnostic_category="outer_container_controls_invalid")
        return _seal_probe_receipt(common)
    common["outer_controls_valid"] = True
    deadline = time.monotonic() + manifest.readiness_timeout_seconds
    metadata: dict[str, Any] | None = None
    readiness_failure = "dind_readiness_timeout"
    while time.monotonic() < deadline and common["readiness_poll_count"] < 24:
        common["readiness_poll_count"] += 1
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
        common.update(status="probe_failed", diagnostic_category=readiness_failure)
        return _seal_probe_receipt(common)
    common["daemon_ready"] = True
    field_bindings = (
        ("ServerVersion", "server_version", manifest.dind_server_version),
        ("Driver", "driver", manifest.dind_storage_driver),
        ("DefaultRuntime", "default_runtime", manifest.dind_default_runtime),
    )
    for key, receipt_name, expected in field_bindings:
        common[f"json_info_{receipt_name}_present"] = key in metadata
        common[f"json_info_{receipt_name}_equal"] = metadata.get(key) == expected
    explicit = _docker_call(
        engine,
        [
            "exec",
            name,
            "docker",
            "info",
            "--format",
            "{{.ServerVersion}}\t{{.Driver}}\t{{.DefaultRuntime}}",
        ],
        timeout_s=manifest.probe_command_timeout_seconds,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    common.update(_summary(explicit, "explicit_info"))
    explicit_values = explicit.stdout.strip().split("\t") if explicit.exit_code == 0 else []
    common["explicit_info_value_count"] = len(explicit_values)
    if (
        explicit.exit_code == 0
        and not explicit.timed_out
        and not explicit.output_truncated
        and len(explicit_values) == 3
    ):
        common["explicit_info_server_version_equal"] = (
            explicit_values[0] == manifest.dind_server_version
        )
        common["explicit_info_driver_equal"] = explicit_values[1] == manifest.dind_storage_driver
        common["explicit_info_default_runtime_equal"] = (
            explicit_values[2] == manifest.dind_default_runtime
        )
    legacy = _docker_call(
        engine,
        ["exec", name, "docker", "version", "--format", "{{.Server.Version}}"],
        timeout_s=manifest.probe_command_timeout_seconds,
        maximum_bytes=manifest.maximum_diagnostic_output_bytes,
    )
    common.update(_summary(legacy, "legacy_version"))
    common["legacy_version_category"] = _legacy_category(legacy)
    qualified = all(
        common[key]
        for key in (
            "explicit_info_server_version_equal",
            "explicit_info_driver_equal",
            "explicit_info_default_runtime_equal",
        )
    )
    common["identity_qualified"] = qualified
    common["status"] = "passed" if qualified else "probe_failed"
    common["diagnostic_category"] = (
        "dind_identity_qualified" if qualified else "explicit_info_identity_failed"
    )
    return _seal_probe_receipt(common)


def _remove_container(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    engine: DockerCliEngine,
    name: str,
    *,
    role: str,
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
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return False, "invalid_container_inspect_response"
    config = values[0].get("Config") if isinstance(values, list) and len(values) == 1 else None
    labels = config.get("Labels") if isinstance(config, dict) else None
    if (
        not isinstance(labels, dict)
        or labels.get("verigym.owner") != IDENTITY
        or labels.get("verigym.role") != role
    ):
        return False, "unowned_container_preserved"
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


def _remove_volume(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
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
    if not _inspect_volume(manifest, engine, name=name, role=role, backing=backing):
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
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    engine: DockerCliEngine,
    *,
    main_name: str,
    data_attempted: bool,
    socket_attempted: bool,
) -> dict[str, Any]:
    main_removed, main_category = _remove_container(
        manifest, engine, main_name, role="identity-probe-daemon"
    )
    owned = {
        "data": data_attempted
        and _inspect_volume(
            manifest, engine, name=manifest.dind_data_volume, role="data", backing=DIND_DATA_BACKING
        ),
        "socket": socket_attempted
        and _inspect_volume(
            manifest,
            engine,
            name=manifest.dind_socket_volume,
            role="socket",
            backing=DIND_SOCKET_BACKING,
        ),
    }
    helper_attempted = any(owned.values())
    helper_status = "not_required"
    helper_exit_code: int | None = None
    helper_removed = True
    if helper_attempted:
        helper_name = f"verigym-dind-v123-cleanup-{secrets.token_hex(10)}"
        mounts: list[str] = []
        scripts: list[str] = []
        for role, volume, target in (
            ("data", manifest.dind_data_volume, "/verigym-data"),
            ("socket", manifest.dind_socket_volume, "/verigym-socket"),
        ):
            if owned[role]:
                mounts.extend(["--mount", f"type=volume,src={volume},dst={target}"])
                scripts.extend(
                    [
                        f"rm -rf -- {target}/* {target}/.[!.]* {target}/..?*",
                        f"chown {os.getuid()}:{os.getgid()} {target}",
                        f"chmod 0700 {target}",
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
                "verigym.role=identity-probe-cleanup",
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
        helper_removed, helper_remove_category = _remove_container(
            manifest, engine, helper_name, role="identity-probe-cleanup"
        )
        if not helper_removed:
            helper_status = helper_remove_category
    data_removed, data_category = _remove_volume(
        manifest,
        engine,
        name=manifest.dind_data_volume,
        role="data",
        backing=DIND_DATA_BACKING,
        attempted=data_attempted,
    )
    socket_removed, socket_category = _remove_volume(
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
            data_removed,
            socket_removed,
            data_restored,
            socket_restored,
        )
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v123_cleanup_v1",
        "identity": IDENTITY,
        "status": "passed" if passed else "cleanup_unconfirmed",
        "main_container_removed": main_removed,
        "main_container_cleanup_category": main_category,
        "cleanup_helper_attempted": helper_attempted,
        "cleanup_helper_exit_code": helper_exit_code,
        "cleanup_helper_status": helper_status,
        "cleanup_helper_container_removed": helper_removed,
        "data_volume_removed": data_removed,
        "data_volume_cleanup_category": data_category,
        "socket_volume_removed": socket_removed,
        "socket_volume_cleanup_category": socket_category,
        "data_backing_empty_and_ownership_restored": data_restored,
        "socket_backing_empty_and_ownership_restored": socket_restored,
        "volume_removal_independent_of_cleanup_helper": True,
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "raw_stdout_persisted": False,
        "raw_stderr_persisted": False,
        "raw_output_hashed": False,
        "container_identity_persisted": False,
        "host_paths_persisted": False,
        "provider_calls": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _base_report(
    manifest: DeepSeekHarnessV123BoundedDindIdentityProbeManifest,
    *,
    source_commit: str,
    post_merge_main_run_id: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v123_identity_probe_report_v1",
        "identity": IDENTITY,
        "manifest_hash": manifest.manifest_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "static_preflight",
        "diagnostic_complete": False,
        "startup_attempt_limit": 1,
        "startup_attempt_count": 0,
        "diagnostic_category": None,
        "dind_identity_qualified": False,
        "cleanup_confirmed": False,
        "predecessor_preflight_hash": None,
        "headroom_preflight_hash": None,
        "host_image_identity_hash": None,
        "volume_setup_receipt_hash": None,
        "identity_probe_receipt_hash": None,
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
        "predecessor_volumes_inspected": False,
        "predecessor_volumes_mutated": False,
        "raw_docker_output_persisted": False,
        "raw_docker_output_hashed": False,
        "raw_exception_persisted": False,
        "container_identity_persisted": False,
        "host_paths_persisted_in_diagnostics": False,
        "requires_independent_v124_audit": True,
        **{name: False for name in _CLOSED_FLAGS},
    }


def _write_report(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(report)
    base.pop("report_hash", None)
    value = {**base, "report_hash": content_hash(base)}
    atomic_dump_json(root / "identity-probe-progress.json", value)
    atomic_dump_json(root / "identity-probe-report.json", value)
    return value


def diagnose(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_execution_boundary(arguments)
    manifest = load_v123_bounded_dind_identity_probe_manifest(arguments.manifest)
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
    main_name = f"verigym-dind-v123-{secrets.token_hex(10)}"
    failure_category: str | None = None
    probe: dict[str, Any] | None = None
    cleanup: dict[str, Any]
    try:
        _create_runtime_paths(manifest)
        headroom = _headroom_receipt()
        atomic_dump_json(root / "headroom-preflight.json", headroom)
        report["headroom_preflight_hash"] = headroom["preflight_hash"]
        if headroom["status"] != "passed":
            raise _ProbeFailure("insufficient_headroom")
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
        report["status"] = "bounded_identity_probe"
        _write_report(root, report)
        probe = _run_identity_probe(manifest, engine, main_name)
        atomic_dump_json(root / "identity-probe-receipt.json", probe)
        report.update(
            {
                "startup_attempt_count": 1,
                "diagnostic_category": probe["diagnostic_category"],
                "identity_probe_receipt_hash": probe["receipt_hash"],
                "dind_identity_qualified": probe["status"] == "passed",
            }
        )
    except _ProbeFailure as exc:
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
                "format_id": "verigym_deepseek_harness_hwe_v123_cleanup_v1",
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
            status="stopped_before_diagnostic_completion",
            stop_reason=failure_category,
            diagnostic_complete=False,
        )
    elif probe is None:
        report.update(
            status="stopped_before_diagnostic_completion",
            stop_reason="identity_probe_receipt_missing",
            diagnostic_complete=False,
        )
    elif cleanup["status"] != "passed":
        report.update(
            status="stopped_cleanup_unconfirmed",
            stop_reason="cleanup_unconfirmed",
            diagnostic_complete=True,
        )
    else:
        report.update(
            status="completed_pending_independent_v124_audit",
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
                "diagnostic_category": report["diagnostic_category"],
                "dind_identity_qualified": report["dind_identity_qualified"],
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
