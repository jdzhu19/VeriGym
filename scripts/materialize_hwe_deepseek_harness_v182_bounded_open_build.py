#!/usr/bin/env python3
"""Run the one-use task-free v182 bounded open-toolchain build diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
for _source_root in reversed(
    (
        _REPOSITORY,
        _REPOSITORY / "src",
        _REPOSITORY / "integrations/verigym-hwe-bench/src",
    )
):
    _source_text = str(_source_root.resolve(strict=True))
    sys.path[:] = [_source_text, *(entry for entry in sys.path if entry != _source_text)]

from scripts import materialize_hwe_deepseek_harness_v172_open_toolchain as v172  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v176_open_toolchain_repair as v176,
)
from scripts import materialize_hwe_deepseek_harness_v178_local_builder as v178  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
)
from verigym.hwe.open_toolchain_build_diagnostic import (  # noqa: E402
    V182_IDENTITY,
    OpenToolchainV182BuildDiagnosticManifest,
    load_v182_build_diagnostic_manifest,
)
from verigym.hwe.open_toolchain_dind_mount_repair import (  # noqa: E402
    load_v180_dind_mount_repair_manifest,
)
from verigym.hwe.open_toolchain_local_builder import (  # noqa: E402
    OpenToolchainV178LocalBuilderManifest,
    load_v178_local_builder_manifest,
)
from verigym.hwe.open_toolchain_successor import exact_repository_digest  # noqa: E402

IDENTITY = V182_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V182_BOUNDED_OPEN_BUILD"
SANITIZED_CHILD_ENV = "VERIGYM_V182_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json"
)
V180_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v180_dind_mount_repair_v1.json"
)
V180_RESULT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1"
)
SCRATCH_ROOT = Path(
    "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v182-bounded-open-build-diagnostic"
)
BACKING_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v182")
DATA_BACKING = BACKING_PARENT / "data"
SOCKET_BACKING = BACKING_PARENT / "socket"
OWNER = "deepseek-harness-hwe-v182-bounded-open-build"
_DIND_TAG = "docker:23.0.6-dind"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_ALLOWED_UNTRACKED_PATHS = v178._ALLOWED_UNTRACKED_PATHS  # noqa: SLF001
_SENSITIVE_NAME = re.compile(
    r"(?:api.?key|token|secret|password|credential|authorization|cookie|proxy)", re.I
)
_SENSITIVE_MARKER = re.compile(
    rb"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    rb"(?:api.?key|token|secret|password|authorization)\s*[:=]\s*\S{4,})"
)
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json",
    "docs/audits/2026-09-06_deepseek-harness-v181-v180-build-cleanup-stop.md",
    "docs/audits/2026-09-06_deepseek-harness-v182-bounded-build-authorization.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v182_bounded_open_build.py",
    "scripts/launch_hwe_deepseek_harness_v182_bounded_open_build.py",
    "scripts/materialize_hwe_deepseek_harness_v176_open_toolchain_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v178_local_builder.py",
    "scripts/materialize_hwe_deepseek_harness_v180_dind_mount_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v182_bounded_open_build.py",
    "src/verigym/hwe/open_toolchain_build_diagnostic.py",
    "tests/unit/test_hwe_open_toolchain_build_diagnostic.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the sole authorized task-free diagnostic and always seal a terminal report."""

    successor = load_v182_build_diagnostic_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    _require_execution_boundary(arguments, successor)
    source_commit = _require_clean_merged_main()
    active_sensitive_values = _active_sensitive_values()
    with _sanitized_process_environment():
        builder, archive_receipt = _preflight_inputs(successor)
        root = _new_output(arguments.output, successor)
        scratch = _new_scratch(successor)
        return _execute(
            arguments,
            successor=successor,
            builder=builder,
            root=root,
            scratch=scratch,
            source_commit=source_commit,
            active_sensitive_values=active_sensitive_values,
            archive_receipt=archive_receipt,
        )


def _execute(
    arguments: argparse.Namespace,
    *,
    successor: OpenToolchainV182BuildDiagnosticManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    root: Path,
    scratch: Path,
    source_commit: str,
    active_sensitive_values: tuple[bytes, ...],
    archive_receipt: dict[str, Any],
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v182_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": successor.manifest_hash,
        "predecessor_result_tree_hash": successor.predecessor_result_tree_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "offline_preflight",
        "provider_calls": 0,
        "model_process_count": 0,
        "hwe_image_import_count": 0,
        "task_source_prepare_count": 0,
        "verifier_run_count": 0,
        "qualification_contract_published": False,
        "canary_authorized": False,
        **_closed_flags(),
    }
    _write_progress(root, progress)
    diagnostic: dict[str, Any] | None = None
    stop_reason: str | None = None
    try:
        atomic_dump_json(root / "headroom.json", _headroom_receipt())
        atomic_dump_json(root / "local-builder-archive.json", archive_receipt)
        progress["status"] = "local_transfer_prepare"
        _write_progress(root, progress)
        transfers = _save_transfer_inputs(successor, builder=builder, scratch=scratch)
        _prepare_dind_backings(successor)
        _create_bind_volume(successor.dind_data_volume, DATA_BACKING)
        _create_bind_volume(successor.dind_socket_volume, SOCKET_BACKING)
        dind_name = f"verigym-dind-v182-{secrets.token_hex(8)}"
        dind_receipt = _start_dind(dind_name, successor, root=root, scratch=scratch)
        atomic_dump_json(root / "dind-runtime.json", dind_receipt)
        docker_host = f"unix://{SOCKET_BACKING / 'docker.sock'}"

        progress["status"] = "local_builder_binding"
        _write_progress(root, progress)
        _load_transfer_inputs(
            successor,
            builder=builder,
            transfers=transfers,
            docker_host=docker_host,
        )
        builder_receipt = _bind_and_probe_builder(builder, successor, docker_host=docker_host)
        atomic_dump_json(root / "local-builder-binding.json", builder_receipt)

        progress["status"] = "bounded_final_image_build"
        _write_progress(root, progress)
        diagnostic = _run_build_diagnostic(
            successor,
            builder=builder,
            scratch=scratch,
            docker_host=docker_host,
            active_sensitive_values=active_sensitive_values,
        )
        atomic_dump_json(root / "build-diagnostic.json", diagnostic)
        progress["status"] = "build_diagnostic_captured"
        _write_progress(root, progress)
    except Exception as exc:
        stop_reason = type(exc).__name__
        if diagnostic is None:
            diagnostic = _diagnostic_receipt(
                successor,
                result=None,
                category="controller_error",
                sensitive=False,
            )
            atomic_dump_json(root / "build-diagnostic.json", diagnostic)

    cleanup = _cleanup(
        successor,
        scratch=scratch,
        active_sensitive_values=active_sensitive_values,
    )
    atomic_dump_json(root / "cleanup.json", cleanup)
    category = diagnostic["category"]
    if cleanup["cleanup_complete"] is not True:
        status_value = "stopped_cleanup_incomplete"
    elif category == "sensitive_output":
        status_value = "stopped_sensitive_output"
    elif category == "controller_error":
        status_value = "stopped_controller_error"
    else:
        status_value = "completed_build_diagnostic"
    terminal = {
        **progress,
        "status": status_value,
        "diagnostic_category": category,
        "diagnostic_hash": diagnostic["diagnostic_hash"],
        "build_succeeded": category == "success",
        "diagnostic_complete": category != "controller_error",
        "cleanup_complete": cleanup["cleanup_complete"],
        "cleanup_category": cleanup["category"],
        "cleanup_hash": cleanup["cleanup_hash"],
        "stop_reason": stop_reason,
        "raw_exception_persisted": False,
        "raw_output_persisted": False,
        "command_argv_persisted": False,
        "environment_names_persisted": False,
        "environment_values_persisted": False,
        "requires_independent_v183_audit": True,
    }
    sealed = _seal(terminal)
    _write_progress(root, terminal)
    atomic_dump_json(root / "zero-provider-report.json", sealed)
    _normalize_result_modes(root)
    return sealed


def _preflight_inputs(
    successor: OpenToolchainV182BuildDiagnosticManifest,
) -> tuple[OpenToolchainV178LocalBuilderManifest, dict[str, Any]]:
    _validate_predecessor_evidence(successor)
    predecessor_path = _REPOSITORY / successor.predecessor_manifest_path
    if (
        predecessor_path != V180_MANIFEST
        or _hash_file(predecessor_path) != successor.predecessor_manifest_sha256
    ):
        raise ConfigurationError("v182 predecessor manifest file changed")
    predecessor = load_v180_dind_mount_repair_manifest(predecessor_path)
    if predecessor.manifest_hash != successor.predecessor_manifest_hash:
        raise ConfigurationError("v182 predecessor manifest identity changed")
    builder_path = _REPOSITORY / predecessor.predecessor_manifest_path
    builder = load_v178_local_builder_manifest(builder_path)
    if (
        _hash_file(builder_path) != predecessor.predecessor_manifest_sha256
        or builder.manifest_hash != predecessor.predecessor_manifest_hash
    ):
        raise ConfigurationError("v182 local builder manifest binding changed")
    builder = builder.model_copy(
        update={
            "builder_tag": successor.builder_tag,
            "final_dockerfile": successor.final_dockerfile,
            "final_dockerfile_sha256": successor.final_dockerfile_sha256,
        }
    )
    bindings = {
        "local_builder_archive_path": builder.local_builder_archive_path,
        "local_builder_archive_sha256": builder.local_builder_archive_sha256,
        "local_builder_image_id": builder.local_builder_image_id,
    }
    if any(getattr(successor, name) != value for name, value in bindings.items()):
        raise ConfigurationError("v182 local builder input changed")
    expected = {
        _REPOSITORY / successor.inherited_runner_path: successor.inherited_runner_sha256,
        _REPOSITORY / successor.bounded_process_runner_path: (
            successor.bounded_process_runner_sha256
        ),
        _REPOSITORY / successor.local_builder_runner_path: successor.local_builder_runner_sha256,
        _REPOSITORY / successor.final_dockerfile: successor.final_dockerfile_sha256,
        Path(successor.verilator_archive_path): successor.verilator_archive_sha256,
        Path(successor.ripgrep_archive_path): successor.ripgrep_archive_sha256,
        _REPOSITORY / successor.predecessor_audit_path: successor.predecessor_audit_sha256,
    }
    for path, digest in expected.items():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name.endswith(".partial")
            or _hash_file(path) != digest
        ):
            raise ConfigurationError("v182 frozen input identity changed")
    dockerfile = (_REPOSITORY / successor.final_dockerfile).read_text(encoding="utf-8")
    if (
        f"FROM {successor.builder_tag} AS verilator-builder" not in dockerfile
        or dockerfile
        != (_REPOSITORY / "docker/open-rtl-tools-hwe/Dockerfile.v178")
        .read_text(encoding="utf-8")
        .replace("v178-builder", "v180-builder")
        or "RUN curl" in dockerfile
        or "RUN wget" in dockerfile
        or "ghcr.io/pku-liang" in dockerfile
    ):
        raise ConfigurationError("v182 exact v180 Dockerfile boundary changed")
    rg_binary = Path(successor.ripgrep_archive_path).parent / (
        "ripgrep-15.2.0-x86_64-unknown-linux-musl/rg"
    )
    if (
        rg_binary.is_symlink()
        or not rg_binary.is_file()
        or _hash_file(rg_binary) != successor.ripgrep_binary_sha256
    ):
        raise ConfigurationError("v182 ripgrep binary identity changed")
    if v172._docker_image_id(successor.accepted_open_tools_tag) != (  # noqa: SLF001
        successor.accepted_open_tools_image_id
    ):
        raise ConfigurationError("v182 accepted open-tools host image changed")
    if v172._docker_image_id(_DIND_TAG) != successor.dind_image_id:  # noqa: SLF001
        raise ConfigurationError("v182 DinD host image changed")
    dind = v172._inspect_image(_DIND_TAG)  # noqa: SLF001
    if dind is None:
        raise ConfigurationError("v182 DinD image inspection is missing")
    exact_repository_digest(
        dind.get("RepoDigests"),
        expected_repository="docker",
        expected_digest=successor.dind_repository_digest,
    )
    if (dind.get("Os"), dind.get("Architecture")) != ("linux", "amd64"):
        raise ConfigurationError("v182 DinD platform changed")
    archive = v178._builder_archive_receipt(builder)  # noqa: SLF001
    archive_base = dict(archive)
    archive_base.pop("receipt_hash")
    archive_base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v182_local_builder_archive_v1",
            "identity": IDENTITY,
        }
    )
    archive_receipt = {**archive_base, "receipt_hash": content_hash(archive_base)}
    for path in (OUTPUT_ROOT, SCRATCH_ROOT, BACKING_PARENT, DATA_BACKING, SOCKET_BACKING):
        if path.exists() or path.is_symlink():
            raise ConfigurationError("v182 resource path must be fresh")
    inventory_ok, owned = _owned_containers()
    if (
        _volume_exists(successor.dind_data_volume)
        or _volume_exists(successor.dind_socket_volume)
        or v172._docker_image_id(successor.final_image_tag, required=False) is not None  # noqa: SLF001
        or not inventory_ok
        or owned
    ):
        raise ConfigurationError("v182 campaign resource identity is not fresh")
    return builder, archive_receipt


def _validate_predecessor_evidence(
    successor: OpenToolchainV182BuildDiagnosticManifest,
) -> None:
    if Path(successor.predecessor_result_root) != V180_RESULT_ROOT:
        raise ConfigurationError("v182 predecessor result root changed")
    entries = (
        sorted(V180_RESULT_ROOT.iterdir(), key=lambda item: item.name)
        if V180_RESULT_ROOT.is_dir() and not V180_RESULT_ROOT.is_symlink()
        else []
    )
    root_stat = V180_RESULT_ROOT.stat() if entries else None
    if (
        [entry.name for entry in entries] != sorted(successor.predecessor_result_file_sha256)
        or root_stat is None
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.getuid()
        or root_stat.st_gid != os.getgid()
        or hash_directory(V180_RESULT_ROOT) != successor.predecessor_result_tree_hash
    ):
        raise ConfigurationError("v182 predecessor result tree changed")
    for entry in entries:
        metadata = entry.stat() if entry.is_file() and not entry.is_symlink() else None
        if (
            metadata is None
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
            or _hash_file(entry) != successor.predecessor_result_file_sha256[entry.name]
        ):
            raise ConfigurationError("v182 predecessor result file changed")
    try:
        progress = json.loads((V180_RESULT_ROOT / "materialization-progress.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v182 predecessor progress is malformed") from exc
    required = {
        "format_id": "verigym_deepseek_harness_hwe_v180_progress_v1",
        "identity": successor.predecessor_identity,
        "status": "open_toolchain_build",
        "manifest_hash": successor.predecessor_manifest_hash,
        "source_commit": successor.predecessor_implementation_merge_commit,
        "post_merge_main_run_id": successor.predecessor_qualification_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "provider_calls": 0,
        "model_process_count": 0,
        "qualification_contract_published": False,
        **_closed_flags(),
    }
    if (
        any(progress.get(name) != value for name, value in required.items())
        or (V180_RESULT_ROOT / "zero-provider-report.json").exists()
        or (V180_RESULT_ROOT / "qualification-contract.json").exists()
    ):
        raise ConfigurationError("v182 predecessor stop boundary changed")
    audit = _REPOSITORY / successor.predecessor_audit_path
    audit_text = audit.read_text(encoding="utf-8")
    if (
        _hash_file(audit) != successor.predecessor_audit_sha256
        or successor.predecessor_stop_category not in audit_text
        or "task-free final-image build diagnostic" not in audit_text
        or "provider calls" not in audit_text.lower()
    ):
        raise ConfigurationError("v182 predecessor audit authorization changed")


def _save_transfer_inputs(
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    builder: OpenToolchainV178LocalBuilderManifest,
    scratch: Path,
) -> dict[str, Path]:
    accepted = scratch / "accepted-open-tools.tar"
    _run_control(
        [
            "docker",
            "image",
            "save",
            "--output",
            str(accepted),
            successor.accepted_open_tools_image_id,
        ],
        timeout=1800,
    )
    builder_archive = Path(successor.local_builder_archive_path)
    if (
        accepted.is_symlink()
        or not accepted.is_file()
        or not 0 < accepted.stat().st_size <= 8 * 1024**3
        or builder_archive.is_symlink()
        or not builder_archive.is_file()
        or builder_archive.stat().st_size != builder.local_builder_archive_bytes
        or _hash_file(builder_archive) != successor.local_builder_archive_sha256
    ):
        raise ConfigurationError("v182 transfer archive is unsafe")
    return {"accepted": accepted, "builder": builder_archive}


def _prepare_dind_backings(successor: OpenToolchainV182BuildDiagnosticManifest) -> None:
    for path, expected in (
        (DATA_BACKING, Path(successor.dind_data_backing)),
        (SOCKET_BACKING, Path(successor.dind_socket_backing)),
    ):
        if path != expected or path.exists() or path.is_symlink():
            raise ConfigurationError("v182 DinD backing is not fresh")
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
        metadata = path.stat()
        if (
            next(path.iterdir(), None) is not None
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
        ):
            raise ConfigurationError("v182 DinD backing ownership changed")


def _create_bind_volume(name: str, backing: Path) -> None:
    if _volume_exists(name):
        raise ConfigurationError("v182 DinD volume is not fresh")
    result = _run_control(
        [
            "docker",
            "volume",
            "create",
            "--driver",
            "local",
            "--label",
            f"verigym.owner={OWNER}",
            "--opt",
            "type=none",
            "--opt",
            "o=bind",
            "--opt",
            f"device={backing}",
            name,
        ],
        timeout=30,
    )
    if result.stdout.decode().strip() != name:
        raise ConfigurationError("v182 DinD volume creation output changed")


def _dind_command(
    name: str,
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    root: Path,
    scratch: Path,
    empty_home: Path,
) -> list[str]:
    return [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        f"verigym.owner={OWNER}",
        "--label",
        "verigym.role=offline-daemon",
        "--privileged",
        "--network",
        "none",
        "--pids-limit",
        "32768",
        "--env",
        "DOCKER_TLS_CERTDIR=",
        "--volume",
        f"{successor.dind_socket_volume}:/var/run:rw",
        "--volume",
        f"{successor.dind_data_volume}:/var/lib/docker:rw",
        "--mount",
        f"type=bind,src={root},dst={root}",
        "--mount",
        f"type=bind,src={scratch},dst={scratch}",
        "--mount",
        f"type=bind,src={empty_home},dst=/verigym-host-sentinel,readonly",
        successor.dind_image_id,
        "--storage-driver=vfs",
        f"--group={os.getgid()}",
    ]


def _start_dind(
    name: str,
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    root: Path,
    scratch: Path,
) -> dict[str, Any]:
    empty_home = scratch / "empty-home"
    empty_home.mkdir(mode=0o700)
    _run_control(
        _dind_command(name, successor, root=root, scratch=scratch, empty_home=empty_home),
        timeout=60,
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = _run_control(
            ["docker", "exec", name, "docker", "info"],
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise ConfigurationError("v182 DinD daemon did not become ready")
    outer = v172._inspect_container(name)  # noqa: SLF001
    host = outer.get("HostConfig") or {}
    config = outer.get("Config") or {}
    mounts = outer.get("Mounts") or []
    by_destination = {item.get("Destination"): item for item in mounts if isinstance(item, dict)}
    expected = {
        "/var/run": ("volume", successor.dind_socket_volume, True),
        "/var/lib/docker": ("volume", successor.dind_data_volume, True),
        str(root): ("bind", str(root), True),
        str(scratch): ("bind", str(scratch), True),
        "/verigym-host-sentinel": ("bind", str(empty_home), False),
    }
    mount_checks = {
        destination: (
            isinstance(item := by_destination.get(destination), dict)
            and item.get("Type") == kind
            and item.get("RW") is writable
            and (item.get("Name") == source if kind == "volume" else item.get("Source") == source)
        )
        for destination, (kind, source, writable) in expected.items()
    }
    environment_names = {
        item.partition("=")[0] for item in config.get("Env") or [] if isinstance(item, str)
    }
    if (
        len(by_destination) != len(mounts)
        or host.get("Privileged") is not True
        or host.get("NetworkMode") != "none"
        or config.get("Labels", {}).get("verigym.owner") != OWNER
        or config.get("Labels", {}).get("verigym.role") != "offline-daemon"
        or set(by_destination) != set(expected)
        or not all(mount_checks.values())
        or "/var/run/docker.sock" in by_destination
        or any(_SENSITIVE_NAME.search(name) for name in environment_names)
    ):
        raise ConfigurationError("v182 outer DinD isolation differs from policy")
    info_result = _run_control(
        ["docker", "exec", name, "docker", "info", "--format", "{{json .}}"], timeout=30
    )
    info = json.loads(info_result.stdout)
    version = (
        _run_control(
            ["docker", "exec", name, "docker", "version", "--format", "{{.Server.Version}}"],
            timeout=30,
        )
        .stdout.decode()
        .strip()
    )
    if (
        version != successor.dind_server_version
        or info.get("Driver") != successor.dind_storage_driver
        or info.get("DefaultRuntime") != successor.dind_default_runtime
    ):
        raise ConfigurationError("v182 inner Docker identity changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v182_dind_runtime_v1",
        "identity": IDENTITY,
        "image_id": successor.dind_image_id,
        "repository_digest": successor.dind_repository_digest,
        "server_version": version,
        "storage_driver": info["Driver"],
        "default_runtime": info["DefaultRuntime"],
        "outer_network": "none",
        "host_socket_mounted": False,
        "writable_bind_mount_count": 2,
        "readonly_bind_mount_count": 1,
        "provider_or_proxy_environment_present": False,
        "mount_inspection_passed": True,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _load_transfer_inputs(
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    builder: OpenToolchainV178LocalBuilderManifest,
    transfers: dict[str, Path],
    docker_host: str,
) -> None:
    for path in transfers.values():
        _run_control(["docker", "--host", docker_host, "load", "--input", str(path)], timeout=1800)
    for image_id, tag in (
        (successor.accepted_open_tools_image_id, successor.accepted_open_tools_tag),
        (builder.local_builder_image_id, successor.builder_tag),
    ):
        _run_control(["docker", "--host", docker_host, "image", "tag", image_id, tag], timeout=30)
    if (
        v172._docker_image_id(successor.accepted_open_tools_tag, host=docker_host)  # noqa: SLF001
        != successor.accepted_open_tools_image_id
        or v172._docker_image_id(successor.builder_tag, host=docker_host)  # noqa: SLF001
        != builder.local_builder_image_id
    ):
        raise ConfigurationError("v182 transferred image identity changed")


def _bind_and_probe_builder(
    builder: OpenToolchainV178LocalBuilderManifest,
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    docker_host: str,
) -> dict[str, Any]:
    image = v172._inspect_image(  # noqa: SLF001
        builder.local_builder_image_id, host=docker_host, required=False
    )
    if image is None:
        raise ConfigurationError("v182 local builder image is missing")
    config = image.get("Config") or {}
    rootfs = image.get("RootFS") or {}
    checks = {
        "image_id": image.get("Id") == builder.local_builder_image_id,
        "created": image.get("Created") == builder.local_builder_created,
        "platform": (image.get("Os"), image.get("Architecture")) == ("linux", "amd64"),
        "layers": tuple(rootfs.get("Layers") or ()) == builder.local_builder_rootfs_layers,
        "parent": config.get("Image") == builder.local_builder_parent_image_id,
        "user": config.get("User") == "",
        "environment": config.get("Env")
        == ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
        "command": config.get("Cmd") == ["bash"],
        "entrypoint": config.get("Entrypoint") in (None, []),
        "working_directory": config.get("WorkingDir") == "",
        "labels": config.get("Labels") in (None, {}),
        "volumes": config.get("Volumes") in (None, {}),
    }
    if not all(checks.values()):
        raise ConfigurationError("v182 local builder metadata changed")
    history = v178._local_builder_history(builder, docker_host=docker_host)  # noqa: SLF001
    v178._validate_builder_history(builder, history)  # noqa: SLF001
    probe = v178._probe_local_builder(builder, docker_host=docker_host)  # noqa: SLF001
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v182_local_builder_binding_v1",
        "identity": IDENTITY,
        "image_id": builder.local_builder_image_id,
        "archive_sha256": builder.local_builder_archive_sha256,
        "rootfs_layers_hash": content_hash(list(builder.local_builder_rootfs_layers)),
        "history_sha256": builder.local_builder_history_sha256,
        "package_inventory_sha256": builder.local_builder_package_inventory_sha256,
        "required_binary_sha256": builder.local_builder_required_binary_sha256,
        "required_versions": builder.local_builder_required_versions,
        "probe_output_sha256": probe["output_sha256"],
        "probe_output_bytes": probe["output_bytes"],
        "network": "none",
        "read_only_root": True,
        "non_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "mount_count": 0,
        "hwe_image_present": False,
        "raw_history_persisted": False,
        "raw_probe_output_persisted": False,
        "registry_accessed": False,
        "download_performed": False,
        "binding_passed": True,
        "builder_tag": successor.builder_tag,
    }
    return {**base, "binding_hash": content_hash(base)}


def _build_command(
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    context: Path,
    docker_host: str,
) -> list[str]:
    return [
        "docker",
        "--host",
        docker_host,
        "build",
        "--progress=plain",
        "--network",
        "none",
        "--pull=false",
        "--tag",
        successor.final_image_tag,
        "--build-arg",
        f"VERILATOR_ARCHIVE_SHA256={successor.verilator_archive_sha256}",
        "--build-arg",
        f"VERILATOR_COMMIT={successor.verilator_commit}",
        "--build-arg",
        f"RIPGREP_ARCHIVE_SHA256={successor.ripgrep_archive_sha256}",
        "--build-arg",
        f"RIPGREP_BINARY_SHA256={successor.ripgrep_binary_sha256}",
        "--build-arg",
        f"HOST_UID={os.getuid()}",
        "--build-arg",
        f"HOST_GID={os.getgid()}",
        "--file",
        str(_REPOSITORY / successor.final_dockerfile),
        str(context),
    ]


def _run_build_diagnostic(
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    builder: OpenToolchainV178LocalBuilderManifest,
    scratch: Path,
    docker_host: str,
    active_sensitive_values: tuple[bytes, ...],
) -> dict[str, Any]:
    context = scratch / "build-context"
    context.mkdir(mode=0o700)
    shutil.copy2(successor.verilator_archive_path, context / "verilator-v5.008.tar.gz")
    shutil.copy2(
        successor.ripgrep_archive_path,
        context / "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz",
    )
    result = v176._run_bounded_process(  # noqa: SLF001
        _build_command(successor, context=context, docker_host=docker_host),
        timeout=successor.build_timeout_seconds,
        maximum=successor.build_output_max_bytes,
    )
    sensitive = _contains_sensitive_output(
        result.stdout, result.stderr, active_sensitive_values=active_sensitive_values
    )
    category = _classify_build_result(result, sensitive=sensitive)
    if category == "success":
        image_id = v172._docker_image_id(  # noqa: SLF001
            successor.final_image_tag, host=docker_host
        )
        if image_id in {
            successor.accepted_open_tools_image_id,
            successor.dind_image_id,
            builder.local_builder_image_id,
        }:
            category = "controller_error"
    return _diagnostic_receipt(
        successor,
        result=result,
        category=category,
        sensitive=sensitive,
    )


def _contains_sensitive_output(
    stdout: bytes,
    stderr: bytes,
    *,
    active_sensitive_values: tuple[bytes, ...],
) -> bool:
    output = stdout + b"\0" + stderr
    return _SENSITIVE_MARKER.search(output) is not None or any(
        value in output for value in active_sensitive_values
    )


def _classify_build_result(result: Any, *, sensitive: bool) -> str:
    if sensitive:
        return "sensitive_output"
    if not result.output_within_bound:
        return "output_overflow"
    if result.timed_out:
        return "timeout"
    if result.returncode == 0:
        return "success"
    output = (result.stdout + b"\0" + result.stderr).lower()
    if b"no space left on device" in output or b"disk quota exceeded" in output:
        return "storage_exhausted"
    if any(
        marker in output
        for marker in (
            b"killed signal terminated program cc1plus",
            b"fatal error: killed",
            b"out of memory",
        )
    ):
        return "compiler_killed"
    if b"no rule to make target" in output:
        return "missing_make_target"
    if b"command not found" in output or b": not found" in output:
        return "missing_executable"
    if (
        b"collect2: error" in output
        or b"ld returned" in output
        or b"linker command failed" in output
    ):
        return "linker_error"
    if b"error:" in output or b"make:" in output and b" error " in output:
        return "compiler_error"
    if b"cannot connect to the docker daemon" in output or b"docker daemon" in output:
        return "docker_daemon_error"
    return "unknown_nonzero"


def _diagnostic_receipt(
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    result: Any | None,
    category: str,
    sensitive: bool,
) -> dict[str, Any]:
    if category not in successor.diagnostic_categories:
        raise ConfigurationError("v182 refuses an unknown diagnostic category")
    stdout = b"" if result is None else result.stdout
    stderr = b"" if result is None else result.stderr
    safe_to_hash = not sensitive
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v182_build_diagnostic_v1",
        "identity": IDENTITY,
        "final_dockerfile_sha256": successor.final_dockerfile_sha256,
        "local_builder_image_id": successor.local_builder_image_id,
        "accepted_open_tools_image_id": successor.accepted_open_tools_image_id,
        "build_network": "none",
        "pull": False,
        "progress_mode": "plain",
        "timeout_seconds": successor.build_timeout_seconds,
        "output_max_bytes": successor.build_output_max_bytes,
        "category": category,
        "returncode": None if result is None else result.returncode,
        "timed_out": False if result is None else result.timed_out,
        "output_within_bound": True if result is None else result.output_within_bound,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest() if safe_to_hash else _EMPTY_SHA256,
        "stderr_sha256": hashlib.sha256(stderr).hexdigest() if safe_to_hash else _EMPTY_SHA256,
        "output_hashes_persisted": safe_to_hash,
        "sensitive_output_detected": sensitive,
        "raw_output_persisted": False,
        "command_argv_persisted": False,
        "environment_names_persisted": False,
        "environment_values_persisted": False,
        "hwe_image_imported": False,
        "task_source_prepared": False,
        "verifier_run": False,
        "model_process_count": 0,
        "provider_calls": 0,
    }
    return {**base, "diagnostic_hash": content_hash(base)}


def _cleanup(
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    scratch: Path,
    active_sensitive_values: tuple[bytes, ...],
) -> dict[str, Any]:
    try:
        return _cleanup_impl(
            successor,
            scratch=scratch,
            active_sensitive_values=active_sensitive_values,
        )
    except Exception:
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v182_cleanup_v1",
            "identity": IDENTITY,
            "category": "cleanup_controller_error",
            "cleanup_complete": False,
            "outer_and_helper_containers_removed": False,
            "named_volumes_removed": False,
            "backing_removed": not BACKING_PARENT.exists(),
            "scratch_removed": not scratch.exists(),
            "helper_required": BACKING_PARENT.exists(),
            "helper_network": "none",
            "helper_read_only_root": True,
            "helper_non_root": False,
            "helper_cap_drop_all": True,
            "helper_cap_add": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
            "helper_no_new_privileges": True,
            "helper_single_bind_mount": True,
            "helper_security_inspection_passed": False,
            "helper_sensitive_output_detected": False,
            "raw_cleanup_output_persisted": False,
            "cleanup_command_argv_persisted": False,
            "environment_values_persisted": False,
            "raw_exception_persisted": False,
        }
        return {**base, "cleanup_hash": content_hash(base)}


def _cleanup_impl(
    successor: OpenToolchainV182BuildDiagnosticManifest,
    *,
    scratch: Path,
    active_sensitive_values: tuple[bytes, ...],
) -> dict[str, Any]:
    container_inventory_ok, containers = _owned_containers()
    container_cleanup = container_inventory_ok
    for container in containers:
        result = _run_control(
            ["docker", "container", "rm", "--force", "--volumes", container],
            timeout=60,
            check=False,
        )
        container_cleanup = container_cleanup and result.returncode == 0

    helper_required = BACKING_PARENT.exists() and not BACKING_PARENT.is_symlink()
    helper_passed = not helper_required
    helper_security_passed = not helper_required
    helper_sensitive = False
    helper_name: str | None = None
    if helper_required:
        helper_name = f"verigym-v182-cleanup-{secrets.token_hex(8)}"
        try:
            create = _run_control(
                _cleanup_helper_command(helper_name, successor), timeout=60, check=False
            )
            if create.returncode == 0:
                helper_security_passed = _inspect_cleanup_helper(helper_name, successor)
                if helper_security_passed:
                    run = v176._run_bounded_process(  # noqa: SLF001
                        ["docker", "container", "start", "--attach", helper_name],
                        timeout=successor.cleanup_timeout_seconds,
                        maximum=successor.cleanup_output_max_bytes,
                    )
                    helper_sensitive = _contains_sensitive_output(
                        run.stdout,
                        run.stderr,
                        active_sensitive_values=active_sensitive_values,
                    )
                    helper_passed = (
                        run.returncode == 0
                        and not run.timed_out
                        and run.output_within_bound
                        and not helper_sensitive
                    )
        except Exception:
            helper_passed = False
        finally:
            if helper_name is not None:
                _run_control(
                    ["docker", "container", "rm", "--force", "--volumes", helper_name],
                    timeout=60,
                    check=False,
                )

    volume_cleanup = True
    for name in (successor.dind_socket_volume, successor.dind_data_volume):
        if _volume_exists(name):
            result = _run_control(["docker", "volume", "rm", name], timeout=60, check=False)
            volume_cleanup = volume_cleanup and result.returncode == 0
    backing_cleanup = _remove_empty_backing()
    scratch_cleanup = _remove_scratch(scratch)
    final_inventory_ok, remaining = _owned_containers()
    volumes_absent = not _volume_exists(successor.dind_socket_volume) and not _volume_exists(
        successor.dind_data_volume
    )
    cleanup_complete = (
        container_cleanup
        and helper_passed
        and helper_security_passed
        and not helper_sensitive
        and volume_cleanup
        and backing_cleanup
        and scratch_cleanup
        and final_inventory_ok
        and not remaining
        and volumes_absent
        and not BACKING_PARENT.exists()
        and not scratch.exists()
    )
    if not container_cleanup or not final_inventory_ok or remaining:
        category = "container_cleanup_failed"
    elif not helper_security_passed or not helper_passed or helper_sensitive:
        category = "cleanup_helper_failed"
    elif not volume_cleanup or not volumes_absent:
        category = "volume_cleanup_failed"
    elif not backing_cleanup or BACKING_PARENT.exists():
        category = "backing_cleanup_failed"
    elif not scratch_cleanup or scratch.exists():
        category = "scratch_cleanup_failed"
    else:
        category = "completed"
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v182_cleanup_v1",
        "identity": IDENTITY,
        "category": category,
        "cleanup_complete": cleanup_complete,
        "outer_and_helper_containers_removed": final_inventory_ok and not remaining,
        "named_volumes_removed": volumes_absent,
        "backing_removed": not BACKING_PARENT.exists(),
        "scratch_removed": not scratch.exists(),
        "helper_required": helper_required,
        "helper_network": "none",
        "helper_read_only_root": True,
        "helper_non_root": False,
        "helper_cap_drop_all": True,
        "helper_cap_add": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
        "helper_no_new_privileges": True,
        "helper_single_bind_mount": True,
        "helper_security_inspection_passed": helper_security_passed,
        "helper_sensitive_output_detected": helper_sensitive,
        "raw_cleanup_output_persisted": False,
        "cleanup_command_argv_persisted": False,
        "environment_values_persisted": False,
    }
    return {**base, "cleanup_hash": content_hash(base)}


def _cleanup_helper_command(
    name: str, successor: OpenToolchainV182BuildDiagnosticManifest
) -> list[str]:
    script = (
        "find /campaign -depth -mindepth 1 -delete; "
        f"chown {os.getuid()}:{os.getgid()} /campaign; chmod 0700 /campaign"
    )
    return [
        "docker",
        "container",
        "create",
        "--name",
        name,
        "--label",
        f"verigym.owner={OWNER}",
        "--label",
        "verigym.role=cleanup-helper",
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
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "1",
        "--ipc",
        "none",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=8m",
        "--mount",
        f"type=bind,src={BACKING_PARENT},dst=/campaign",
        "--entrypoint",
        "/bin/sh",
        successor.accepted_open_tools_image_id,
        "-ceu",
        script,
    ]


def _inspect_cleanup_helper(name: str, successor: OpenToolchainV182BuildDiagnosticManifest) -> bool:
    inspection = v172._inspect_container(name)  # noqa: SLF001
    host = inspection.get("HostConfig") or {}
    config = inspection.get("Config") or {}
    mounts = inspection.get("Mounts") or []
    environment_names = {
        item.partition("=")[0] for item in config.get("Env") or [] if isinstance(item, str)
    }
    return bool(
        config.get("Image") == successor.accepted_open_tools_image_id
        and config.get("User") == "0:0"
        and config.get("Entrypoint") == ["/bin/sh"]
        and config.get("Labels", {}).get("verigym.owner") == OWNER
        and config.get("Labels", {}).get("verigym.role") == "cleanup-helper"
        and host.get("NetworkMode") == "none"
        and host.get("ReadonlyRootfs") is True
        and set(host.get("CapDrop") or []) == {"ALL"}
        and set(host.get("CapAdd") or []) == {"CHOWN", "DAC_OVERRIDE", "FOWNER"}
        and any(str(item).startswith("no-new-privileges") for item in host.get("SecurityOpt") or [])
        and host.get("PidsLimit") == 64
        and host.get("Memory") == 256 * 1024**2
        and host.get("MemorySwap") == 256 * 1024**2
        and host.get("NanoCpus") == 1_000_000_000
        and host.get("IpcMode") == "none"
        and set(host.get("Tmpfs") or {}) == {"/tmp"}
        and len(mounts) == 1
        and mounts[0].get("Type") == "bind"
        and mounts[0].get("Source") == str(BACKING_PARENT)
        and mounts[0].get("Destination") == "/campaign"
        and mounts[0].get("RW") is True
        and not any(_SENSITIVE_NAME.search(name) for name in environment_names)
    )


def _remove_empty_backing() -> bool:
    if not BACKING_PARENT.exists():
        return True
    if BACKING_PARENT.is_symlink() or not BACKING_PARENT.is_dir():
        return False
    try:
        for path in (DATA_BACKING, SOCKET_BACKING):
            if path.exists():
                path.rmdir()
        BACKING_PARENT.rmdir()
    except OSError:
        return False
    return not BACKING_PARENT.exists()


def _remove_scratch(scratch: Path) -> bool:
    if not scratch.exists():
        return True
    if scratch != SCRATCH_ROOT or scratch.is_symlink() or not scratch.is_dir():
        return False
    try:
        shutil.rmtree(scratch)
    except OSError:
        return False
    return not scratch.exists()


def _run_control(
    command: list[str],
    *,
    timeout: int,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            command,
            cwd=_REPOSITORY,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConfigurationError("v182 control command timed out") from exc
    if len(result.stdout) > 1024 * 1024 or len(result.stderr) > 1024 * 1024:
        raise ConfigurationError("v182 control command output exceeded its bound")
    if check and result.returncode != 0:
        raise ConfigurationError("v182 control command failed")
    return result


def _volume_exists(name: str) -> bool:
    return (
        _run_control(["docker", "volume", "inspect", name], timeout=30, check=False).returncode == 0
    )


def _owned_containers() -> tuple[bool, list[str]]:
    result = _run_control(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--filter",
            f"label=verigym.owner={OWNER}",
            "--format",
            "{{.ID}}",
        ],
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return False, []
    return True, [line for line in result.stdout.decode().splitlines() if line]


def _headroom_receipt() -> dict[str, Any]:
    root = shutil.disk_usage("/")
    data2 = shutil.disk_usage("/data2")
    root_stat = os.statvfs("/")
    data2_stat = os.statvfs("/data2")
    passed = root.free >= 10 * 1024**3 and data2.free >= 50 * 1024**3
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v182_headroom_v1",
        "identity": IDENTITY,
        "control_root_available_bytes": root.free,
        "data2_available_bytes": data2.free,
        "control_root_available_inodes": root_stat.f_bavail,
        "data2_available_inodes": data2_stat.f_bavail,
        "capacity_satisfied": passed,
    }
    if not passed:
        raise ConfigurationError("v182 absolute headroom gate failed")
    return {**base, "receipt_hash": content_hash(base)}


def _active_sensitive_values() -> tuple[bytes, ...]:
    return tuple(
        value.encode(errors="surrogateescape")
        for name, value in os.environ.items()
        if _SENSITIVE_NAME.search(name) is not None and len(value) >= 4
    )


@contextmanager
def _sanitized_process_environment() -> Iterator[None]:
    removed: dict[str, str] = {}
    names = {
        name
        for name in os.environ
        if _SENSITIVE_NAME.search(name) is not None
        or name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
        or name in {"DOCKER_HOST", "DOCKER_CONTEXT"}
    }
    for name in names:
        value = os.environ.pop(name, None)
        if value is not None:
            removed[name] = value
    try:
        yield
    finally:
        os.environ.update(removed)


def _require_execution_boundary(
    arguments: argparse.Namespace,
    successor: OpenToolchainV182BuildDiagnosticManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v182 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v182 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v182 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v182 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= successor.predecessor_audit_post_merge_main_run_id:
        raise ConfigurationError("v182 requires a new post-merge main run identity")


def _require_clean_merged_main() -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != relative:
            raise ConfigurationError("v182 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        if subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=False).returncode != 0:
            raise ConfigurationError("v182 tracked repository state is dirty")
    if set(_git("ls-files", "--others", "--exclude-standard").splitlines()) != set(
        _ALLOWED_UNTRACKED_PATHS
    ):
        raise ConfigurationError("v182 untracked repository inventory changed")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "origin/main")
    if branch != "main" or head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("v182 requires clean merged origin/main")
    return head


def _new_output(path: Path, successor: OpenToolchainV182BuildDiagnosticManifest) -> Path:
    if (
        path != OUTPUT_ROOT
        or path.as_posix() != successor.output_root
        or path.exists()
        or path.is_symlink()
    ):
        raise ConfigurationError("v182 output identity must be fresh and exact")
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path.resolve(strict=True)


def _new_scratch(successor: OpenToolchainV182BuildDiagnosticManifest) -> Path:
    if (
        SCRATCH_ROOT.as_posix() != successor.scratch_root
        or SCRATCH_ROOT.exists()
        or SCRATCH_ROOT.is_symlink()
    ):
        raise ConfigurationError("v182 scratch identity must be fresh and exact")
    SCRATCH_ROOT.mkdir(parents=True, mode=0o700)
    SCRATCH_ROOT.chmod(0o700)
    return SCRATCH_ROOT.resolve(strict=True)


def _normalize_result_modes(root: Path) -> None:
    root.chmod(0o700)
    for path in root.iterdir():
        if path.is_file() and not path.is_symlink():
            path.chmod(0o600)


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=_REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hash_file(path: Path) -> str:
    return v172._hash_file(path)  # noqa: SLF001


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_file():
        raise ConfigurationError(f"v182 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v182 {label} identity changed")
    return resolved


def _closed_flags() -> dict[str, bool]:
    return {
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    base = dict(value)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_progress(root: Path, value: dict[str, Any]) -> None:
    atomic_dump_json(root / "materialization-progress.json", _seal(value))
    (root / "materialization-progress.json").chmod(0o600)


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_category": report["diagnostic_category"],
                "cleanup_complete": report["cleanup_complete"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
