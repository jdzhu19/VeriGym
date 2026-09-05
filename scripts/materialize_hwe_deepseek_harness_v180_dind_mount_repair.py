#!/usr/bin/env python3
"""Retry PR-1816 qualification with the reviewed outer-DinD mount syntax repair."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
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

from scripts import materialize_hwe_deepseek_harness_v69 as v69  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v172_open_toolchain as v172  # noqa: E402
from scripts import materialize_hwe_deepseek_harness_v178_local_builder as v178  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    inspect_offline_image_archive,
)
from verigym.hwe.open_toolchain import (  # noqa: E402
    OpenToolchainImageLock,
    OpenToolchainQualificationManifest,
)
from verigym.hwe.open_toolchain_dind_mount_repair import (  # noqa: E402
    V180_IDENTITY,
    OpenToolchainV180DindMountRepairManifest,
    load_v180_dind_mount_repair_manifest,
)
from verigym.hwe.open_toolchain_local_builder import (  # noqa: E402
    OpenToolchainV178LocalBuilderManifest,
    load_v178_local_builder_manifest,
)
from verigym.hwe.open_toolchain_successor import exact_repository_digest  # noqa: E402

IDENTITY = V180_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V180_DIND_MOUNT_REPAIR"
SANITIZED_CHILD_ENV = "VERIGYM_V180_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v180_dind_mount_repair_v1.json"
)
PREDECESSOR_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json"
)
PREDECESSOR_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v178-local-builder-qualification-v1"
)
ARCHIVE_ROOT = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1"
)
SCRATCH_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v180-dind-mount-repair")
DATA_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v180/data")
SOCKET_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v180/socket")
FINAL_IMAGE_TAG = "verigym/open-rtl-tools:hwe-v180-pr1816"
OWNER = "deepseek-harness-hwe-v180-dind-mount-repair"
_DIND_TAG = "docker:23.0.6-dind"
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v180_dind_mount_repair_v1.json",
    "docker/open-rtl-tools-hwe/Dockerfile.v180",
    "docs/audits/2026-09-06_deepseek-harness-v179-v178-dind-start-stop.md",
    "docs/audits/2026-09-06_deepseek-harness-v180-dind-mount-repair-authorization.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v180_dind_mount_repair.py",
    "scripts/launch_hwe_deepseek_harness_v180_dind_mount_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v172_open_toolchain.py",
    "scripts/materialize_hwe_deepseek_harness_v178_local_builder.py",
    "scripts/materialize_hwe_deepseek_harness_v180_dind_mount_repair.py",
    "src/verigym/hwe/open_toolchain_dind_mount_repair.py",
    "tests/unit/test_hwe_open_toolchain_dind_mount_repair.py",
)
_ALLOWED_UNTRACKED_PATHS = v178._ALLOWED_UNTRACKED_PATHS  # noqa: SLF001
_PROXY_ENV_NAMES = frozenset(
    {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the sole authorized v180 zero-provider qualification."""

    successor = load_v180_dind_mount_repair_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    predecessor = _load_predecessor(successor)
    upstream = v178._load_and_bind_upstream(predecessor)  # noqa: SLF001
    projected = _project_predecessor(successor, predecessor)
    runtime = v178._runtime_manifest(projected, upstream)  # noqa: SLF001
    _require_execution_boundary(arguments, successor)
    source_commit = _require_clean_merged_main()
    archive_root = _exact_directory(arguments.archive_root, ARCHIVE_ROOT, "archive root")
    with _patched_inherited_runtime():
        builder_archive_receipt = _preflight_inputs(
            successor,
            projected,
            runtime,
            archive_root=archive_root,
        )
        root = v172._new_output(arguments.output, runtime)  # noqa: SLF001
        scratch = v172._new_scratch(runtime)  # noqa: SLF001
        return _execute(
            arguments,
            successor=successor,
            builder=projected,
            manifest=runtime,
            archive_root=archive_root,
            root=root,
            scratch=scratch,
            source_commit=source_commit,
            builder_archive_receipt=builder_archive_receipt,
        )


def _execute(
    arguments: argparse.Namespace,
    *,
    successor: OpenToolchainV180DindMountRepairManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    manifest: OpenToolchainQualificationManifest,
    archive_root: Path,
    root: Path,
    scratch: Path,
    source_commit: str,
    builder_archive_receipt: dict[str, Any],
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v180_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": manifest.manifest_hash,
        "predecessor_report_hash": successor.predecessor_report_hash,
        "source_commit": source_commit,
        "post_merge_main_run_id": arguments.post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "status": "offline_preflight",
        "provider_calls": 0,
        "model_process_count": 0,
        "qualification_contract_published": False,
        **_closed_flags(),
    }
    _write_progress(root, progress)
    dind_name: str | None = None
    data_retained = False
    try:
        headroom = v172._headroom_receipt()  # noqa: SLF001
        atomic_dump_json(root / "headroom.json", headroom)
        archive_receipt = inspect_offline_image_archive(manifest.task, archive_root=archive_root)
        atomic_dump_json(root / "archive-receipt.json", archive_receipt)
        patch_receipt, instance = v172._patch_receipt(  # noqa: SLF001
            manifest, archive_root=archive_root
        )
        atomic_dump_json(root / "reference-patch-compatibility.json", patch_receipt)
        atomic_dump_json(root / "local-builder-archive.json", builder_archive_receipt)

        transfers = v178._save_transfer_images(  # noqa: SLF001
            builder, manifest=manifest, scratch=scratch
        )
        progress["status"] = "isolated_dind_start"
        _write_progress(root, progress)
        v172._prepare_dind_backings(manifest)  # noqa: SLF001
        v172._create_bind_volume(manifest.dind_data_volume, DATA_BACKING)  # noqa: SLF001
        v172._create_bind_volume(manifest.dind_socket_volume, SOCKET_BACKING)  # noqa: SLF001
        dind_name = f"verigym-dind-v180-{secrets.token_hex(8)}"
        dind_receipt = _start_dind(dind_name, manifest, root=root, scratch=scratch)
        atomic_dump_json(root / "dind-runtime.json", dind_receipt)
        docker_host = f"unix://{SOCKET_BACKING / 'docker.sock'}"

        progress["status"] = "open_toolchain_build"
        _write_progress(root, progress)
        with v172._docker_host(docker_host):  # noqa: SLF001
            v172._load_transfer_images(  # noqa: SLF001
                manifest,
                builder_id=builder.local_builder_image_id,
                transfers=transfers,
                docker_host=docker_host,
            )
            progress["status"] = "local_complete_builder_binding"
            _write_progress(root, progress)
            builder_id, builder_receipt = v178._bind_and_probe_local_builder(  # noqa: SLF001
                builder, manifest, docker_host=docker_host
            )
            atomic_dump_json(root / "local-builder-binding.json", builder_receipt)
            progress["status"] = "open_toolchain_build"
            _write_progress(root, progress)
            image_id = v172._build_open_image(  # noqa: SLF001
                manifest,
                builder_id=builder_id,
                scratch=scratch,
                docker_host=docker_host,
            )
            v172._load_official_image(manifest, archive_root=archive_root)  # noqa: SLF001
            scan, image_lock = _scan_and_lock_open_image(
                manifest,
                image_id=image_id,
                builder_id=builder_id,
                docker_host=docker_host,
            )
            atomic_dump_json(root / "open-toolchain-security-scan.json", scan)
            atomic_dump_json(
                root / "open-toolchain-image-lock.json", image_lock.model_dump(mode="json")
            )

            source = root / "source"
            dataset = archive_root / manifest.task.dataset_relpath
            v172.prepare_source(
                dataset=dataset,
                output=source,
                selected_tasks=[manifest.task.instance_id],
                pull=False,
                imported_image_bindings={
                    manifest.task.registry_reference: {
                        "image_id": manifest.official_verifier_image,
                        "manifest_digest": manifest.task.registry_manifest_digest,
                    }
                },
                docker_control_timeout_s=120,
            )
            source_binding = v69._source_binding(source, manifest.task)  # noqa: SLF001
            atomic_dump_json(root / "source-binding.json", source_binding)

            progress["status"] = "dual_route_qualification"
            _write_progress(root, progress)
            official = v172.run_zero_model_smoke(
                source=source,
                output=root / "official-qualification",
                docker_control_timeout_s=120,
            )
            if not v172.zero_model_infrastructure_valid(
                official
            ) or not v172.zero_model_fail_to_pass_eligible(official):
                raise ConfigurationError("v180 official route is not base-FAIL/reference-PASS")
            open_comparison = v172._run_open_comparison(  # noqa: SLF001
                source=source,
                instance=instance,
                image_id=image_id,
                docker_host=docker_host,
                root=root,
            )
            atomic_dump_json(root / "open-comparison.json", open_comparison)
            binding = v172._binding_receipt(  # noqa: SLF001
                manifest, open_comparison=open_comparison, official=official
            )
            atomic_dump_json(root / "toolchain-verifier-binding.json", binding)
            inner_cleanup = v172._validate_inner_cleanup(docker_host)  # noqa: SLF001
            atomic_dump_json(root / "inner-cleanup.json", inner_cleanup)

        v172._stop_dind(dind_name)  # noqa: SLF001
        dind_name = None
        cleanup = _success_cleanup(builder, manifest=manifest, scratch=scratch)
        data_retained = True
        atomic_dump_json(root / "cleanup.json", cleanup)
        contract = _qualification_contract(
            successor,
            builder=builder,
            manifest=manifest,
            source_commit=source_commit,
            post_merge_main_run_id=arguments.post_merge_main_run_id,
            archive_receipt=archive_receipt,
            patch_receipt=patch_receipt,
            source_binding=source_binding,
            builder_receipt=builder_receipt,
            builder_archive_receipt=builder_archive_receipt,
            image_lock=image_lock,
            open_comparison=open_comparison,
            official=official,
            binding=binding,
            cleanup=cleanup,
        )
        atomic_dump_json(root / "qualification-contract.json", contract)
        progress.update(
            {
                "status": "completed_pending_independent_v181_audit",
                "qualification_contract_published": True,
                "qualification_contract_hash": contract["contract_hash"],
                "retained_dind_reopen_budget": 1,
                "v182_canary_authorized": False,
            }
        )
        report = _seal(progress)
        _write_progress(root, report)
        atomic_dump_json(root / "zero-provider-report.json", report)
        return report
    except (Exception, KeyboardInterrupt) as exc:
        if dind_name is not None:
            v172._stop_dind(dind_name, strict=False)  # noqa: SLF001
        failure_cleanup_complete = v172._failure_cleanup(  # noqa: SLF001
            manifest, scratch=scratch, preserve_output=root
        )
        stopped = _seal(
            {
                **progress,
                "status": "stopped_without_qualification_contract",
                "stop_reason": type(exc).__name__,
                "raw_exception_persisted": False,
                "qualification_contract_published": False,
                "provider_calls": 0,
                "cleanup_complete": failure_cleanup_complete,
            }
        )
        _write_progress(root, stopped)
        atomic_dump_json(root / "zero-provider-report.json", stopped)
        raise
    finally:
        if not data_retained:
            v172._remove_host_builder_tag(manifest)  # noqa: SLF001


def _load_predecessor(
    successor: OpenToolchainV180DindMountRepairManifest,
) -> OpenToolchainV178LocalBuilderManifest:
    path = _REPOSITORY / successor.predecessor_manifest_path
    if path != PREDECESSOR_MANIFEST or _hash_file(path) != successor.predecessor_manifest_sha256:
        raise ConfigurationError("v180 frozen predecessor manifest file changed")
    predecessor = load_v178_local_builder_manifest(path)
    if predecessor.manifest_hash != successor.predecessor_manifest_hash:
        raise ConfigurationError("v180 frozen predecessor manifest identity changed")
    return predecessor


def _project_predecessor(
    successor: OpenToolchainV180DindMountRepairManifest,
    predecessor: OpenToolchainV178LocalBuilderManifest,
) -> OpenToolchainV178LocalBuilderManifest:
    """Project only fresh v180 runtime resources onto the immutable v178 builder lock."""

    return predecessor.model_copy(
        update={
            "builder_tag": successor.builder_tag,
            "final_dockerfile": successor.final_dockerfile,
            "final_dockerfile_sha256": successor.final_dockerfile_sha256,
            "final_image_tag": successor.final_image_tag,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )


def _preflight_inputs(
    successor: OpenToolchainV180DindMountRepairManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    manifest: OpenToolchainQualificationManifest,
    *,
    archive_root: Path,
) -> dict[str, Any]:
    _validate_predecessor_evidence(successor)
    inherited = {
        successor.inherited_runner_path: successor.inherited_runner_sha256,
        successor.inherited_dind_runner_path: successor.inherited_dind_runner_sha256,
    }
    expected = {
        _REPOSITORY / manifest.builder_source_dockerfile: manifest.builder_source_dockerfile_sha256,
        _REPOSITORY / manifest.final_dockerfile: manifest.final_dockerfile_sha256,
        Path(manifest.verilator_archive_path): manifest.verilator_archive_sha256,
        Path(manifest.ripgrep_archive_path): manifest.ripgrep_archive_sha256,
        _REPOSITORY / manifest.predecessor_audit_path: manifest.predecessor_audit_sha256,
        **{_REPOSITORY / path: digest for path, digest in inherited.items()},
    }
    for path, digest in expected.items():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name.endswith(".partial")
            or _hash_file(path) != digest
        ):
            raise ConfigurationError("v180 frozen input identity changed")
    final_text = (_REPOSITORY / manifest.final_dockerfile).read_text(encoding="utf-8")
    if (
        "verigym/open-rtl-tools:v180-builder" not in final_text
        or "v178-builder" in final_text
        or "ghcr.io/pku-liang" in final_text
        or "RUN curl" in final_text
        or "RUN wget" in final_text
    ):
        raise ConfigurationError("v180 final Dockerfile boundary changed")
    v178_text = (_REPOSITORY / "docker/open-rtl-tools-hwe/Dockerfile.v178").read_text(
        encoding="utf-8"
    )
    if final_text != v178_text.replace("v178-builder", "v180-builder"):
        raise ConfigurationError("v180 final Dockerfile has changes beyond its fresh builder tag")
    rg_binary = Path(manifest.ripgrep_archive_path).parent / (
        "ripgrep-15.2.0-x86_64-unknown-linux-musl/rg"
    )
    if (
        rg_binary.is_symlink()
        or not rg_binary.is_file()
        or _hash_file(rg_binary) != manifest.ripgrep_binary_sha256
    ):
        raise ConfigurationError("v180 ripgrep executable identity changed")
    if v172._docker_image_id(manifest.accepted_open_tools_tag) != (  # noqa: SLF001
        manifest.accepted_open_tools_image_id
    ):
        raise ConfigurationError("v180 accepted open-tools image identity changed")
    if v172._docker_image_id(_DIND_TAG) != manifest.dind_image_id:  # noqa: SLF001
        raise ConfigurationError("v180 DinD tag identity changed")
    dind = v172._inspect_image(_DIND_TAG)  # noqa: SLF001
    if dind is None:
        raise ConfigurationError("v180 DinD image inspection is missing")
    exact_repository_digest(
        dind.get("RepoDigests"),
        expected_repository=builder.dind_repository_name,
        expected_digest=builder.dind_repository_digest,
    )
    if dind.get("Id") != manifest.dind_image_id or (dind.get("Os"), dind.get("Architecture")) != (
        "linux",
        "amd64",
    ):
        raise ConfigurationError("v180 DinD immutable identity or platform changed")
    builder_archive_receipt = v178._builder_archive_receipt(builder)  # noqa: SLF001
    for path in (OUTPUT_ROOT, SCRATCH_ROOT, DATA_BACKING, SOCKET_BACKING):
        if path.exists() or path.is_symlink():
            raise ConfigurationError("v180 resource path must be fresh")
    if (
        v172._volume_exists(manifest.dind_data_volume)  # noqa: SLF001
        or v172._volume_exists(manifest.dind_socket_volume)  # noqa: SLF001
        or v172._docker_image_id(manifest.builder_tag, required=False) is not None  # noqa: SLF001
        or v172._docker_image_id(FINAL_IMAGE_TAG, required=False) is not None  # noqa: SLF001
        or v172._owned_containers()  # noqa: SLF001
    ):
        raise ConfigurationError("v180 campaign resource identity is not fresh")
    inspect_offline_image_archive(manifest.task, archive_root=archive_root)
    return builder_archive_receipt


def _dind_command(
    name: str,
    manifest: OpenToolchainQualificationManifest,
    *,
    root: Path,
    scratch: Path,
    empty_home: Path,
) -> list[str]:
    """Render the v172 command with only the two rejected writable flags omitted."""

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
        f"{manifest.dind_socket_volume}:/var/run:rw",
        "--volume",
        f"{manifest.dind_data_volume}:/var/lib/docker:rw",
        "--mount",
        f"type=bind,src={root},dst={root}",
        "--mount",
        f"type=bind,src={scratch},dst={scratch}",
        "--mount",
        f"type=bind,src={empty_home},dst=/verigym-host-sentinel,readonly",
        manifest.dind_image_id,
        "--storage-driver=vfs",
        f"--group={os.getgid()}",
    ]


def _start_dind(
    name: str,
    manifest: OpenToolchainQualificationManifest,
    *,
    root: Path,
    scratch: Path,
) -> dict[str, Any]:
    empty_home = scratch / "empty-home"
    empty_home.mkdir(mode=0o700)
    command = _dind_command(
        name,
        manifest,
        root=root,
        scratch=scratch,
        empty_home=empty_home,
    )
    v172._run(command, timeout=60)  # noqa: SLF001
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = v172._run_result(  # noqa: SLF001
            ["docker", "exec", name, "docker", "info"], timeout=10
        )
        if result.returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise ConfigurationError("v180 DinD daemon did not become ready")
    outer = v172._inspect_container(name)  # noqa: SLF001
    host = outer.get("HostConfig") or {}
    config = outer.get("Config") or {}
    mounts = outer.get("Mounts") or []
    by_destination = {item.get("Destination"): item for item in mounts if isinstance(item, dict)}
    if len(by_destination) != len(mounts):
        raise ConfigurationError("v180 outer DinD mount inventory is ambiguous")
    expected = {
        "/var/run": ("volume", manifest.dind_socket_volume, True),
        "/var/lib/docker": ("volume", manifest.dind_data_volume, True),
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
        value.partition("=")[0] for value in config.get("Env") or [] if isinstance(value, str)
    }
    if (
        host.get("Privileged") is not True
        or host.get("NetworkMode") != "none"
        or config.get("Labels", {}).get("verigym.owner") != OWNER
        or config.get("Labels", {}).get("verigym.role") != "offline-daemon"
        or set(by_destination) != set(expected)
        or not all(mount_checks.values())
        or "/var/run/docker.sock" in by_destination
        or environment_names.intersection(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES)
        or environment_names.intersection(_PROXY_ENV_NAMES)
    ):
        raise ConfigurationError("v180 outer DinD isolation differs from policy")
    info = json.loads(
        v172._run(  # noqa: SLF001
            ["docker", "exec", name, "docker", "info", "--format", "{{json .}}"],
            timeout=30,
        )
    )
    version = (
        v172._run(  # noqa: SLF001
            ["docker", "exec", name, "docker", "version", "--format", "{{.Server.Version}}"],
            timeout=30,
        )
        .decode()
        .strip()
    )
    if (
        version != manifest.dind_server_version
        or info.get("Driver") != manifest.dind_storage_driver
        or info.get("DefaultRuntime") != manifest.dind_default_runtime
    ):
        raise ConfigurationError("v180 inner Docker identity changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v180_dind_runtime_v1",
        "identity": IDENTITY,
        "image_id": manifest.dind_image_id,
        "repository_digest": manifest.dind_repository_digest,
        "server_version": version,
        "storage_driver": info["Driver"],
        "default_runtime": info["DefaultRuntime"],
        "outer_network": "none",
        "host_socket_mounted": False,
        "data_backing_role": "data2_campaign_owned",
        "writable_bind_mount_count": 2,
        "writable_bind_mount_syntax": "default-without-rw-field",
        "readonly_bind_mount_count": 1,
        "readonly_bind_mount_syntax_unchanged": True,
        "provider_or_proxy_environment_present": False,
        "mount_inspection_passed": True,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _scan_and_lock_open_image(
    manifest: OpenToolchainQualificationManifest,
    *,
    image_id: str,
    builder_id: str,
    docker_host: str,
) -> tuple[dict[str, Any], OpenToolchainImageLock]:
    scan, image_lock = v172._scan_and_lock_open_image(  # noqa: SLF001
        manifest,
        image_id=image_id,
        builder_id=builder_id,
        docker_host=docker_host,
    )
    scan_base = dict(scan)
    scan_base.pop("scan_hash")
    scan_base["scan_id"] = "v180-open-toolchain-scan-v1"
    scan = {**scan_base, "scan_hash": content_hash(scan_base)}
    lock_base = image_lock.model_dump(mode="json", exclude={"lock_hash"})
    lock_base["security_scan_id"] = scan["scan_id"]
    image_lock = OpenToolchainImageLock.model_validate(
        {**lock_base, "lock_hash": content_hash(lock_base)}
    )
    return scan, image_lock


def _success_cleanup(
    builder: OpenToolchainV178LocalBuilderManifest,
    *,
    manifest: OpenToolchainQualificationManifest,
    scratch: Path,
) -> dict[str, Any]:
    inherited = v178._success_cleanup(builder, manifest=manifest, scratch=scratch)  # noqa: SLF001
    base = dict(inherited)
    base.pop("receipt_hash")
    base["format_id"] = "verigym_deepseek_harness_hwe_v180_cleanup_v1"
    return {**base, "receipt_hash": content_hash(base)}


def _validate_predecessor_evidence(
    successor: OpenToolchainV180DindMountRepairManifest,
) -> None:
    if Path(successor.predecessor_result_root) != PREDECESSOR_ROOT:
        raise ConfigurationError("v180 predecessor result root changed")
    entries = (
        sorted(PREDECESSOR_ROOT.iterdir(), key=lambda item: item.name)
        if PREDECESSOR_ROOT.is_dir() and not PREDECESSOR_ROOT.is_symlink()
        else []
    )
    root_stat = PREDECESSOR_ROOT.stat() if entries else None
    if (
        [entry.name for entry in entries] != sorted(successor.predecessor_result_file_sha256)
        or root_stat is None
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.getuid()
        or root_stat.st_gid != os.getgid()
        or hash_directory(PREDECESSOR_ROOT) != successor.predecessor_result_tree_hash
    ):
        raise ConfigurationError("v180 predecessor result tree changed")
    for entry in entries:
        metadata = entry.stat() if entry.is_file() and not entry.is_symlink() else None
        if (
            metadata is None
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
            or _hash_file(entry) != successor.predecessor_result_file_sha256[entry.name]
        ):
            raise ConfigurationError("v180 predecessor result file changed")
    try:
        report = json.loads((PREDECESSOR_ROOT / "zero-provider-report.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v180 predecessor evidence is malformed") from exc
    report_base = dict(report) if isinstance(report, dict) else {}
    report_hash = report_base.pop("report_hash", None)
    required = {
        "format_id": "verigym_deepseek_harness_hwe_v178_progress_v1",
        "identity": successor.predecessor_identity,
        "status": "stopped_without_qualification_contract",
        "manifest_hash": successor.predecessor_manifest_hash,
        "source_commit": successor.predecessor_implementation_merge_commit,
        "post_merge_main_run_id": successor.predecessor_qualification_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "stop_reason": "ConfigurationError",
        "provider_calls": 0,
        "model_process_count": 0,
        "qualification_contract_published": False,
        "raw_exception_persisted": False,
        "cleanup_complete": True,
        **_closed_flags(),
    }
    if (
        report_hash != successor.predecessor_report_hash
        or content_hash(report_base) != report_hash
        or any(report_base.get(key) != value for key, value in required.items())
        or (PREDECESSOR_ROOT / "qualification-contract.json").exists()
    ):
        raise ConfigurationError("v180 predecessor report binding changed")
    audit = _REPOSITORY / successor.predecessor_audit_path
    if (
        audit.is_symlink()
        or not audit.is_file()
        or _hash_file(audit) != successor.predecessor_audit_sha256
    ):
        raise ConfigurationError("v180 predecessor audit changed")
    audit_text = audit.read_text(encoding="utf-8")
    if (
        successor.predecessor_stop_category not in audit_text
        or "invalid field 'rw' must be a key=value pair" not in audit_text
        or "provider_calls=0" not in audit_text
    ):
        raise ConfigurationError("v180 predecessor audit decision changed")


def _qualification_contract(
    successor: OpenToolchainV180DindMountRepairManifest,
    *,
    builder: OpenToolchainV178LocalBuilderManifest,
    manifest: OpenToolchainQualificationManifest,
    source_commit: str,
    post_merge_main_run_id: int,
    archive_receipt: dict[str, Any],
    patch_receipt: dict[str, Any],
    source_binding: dict[str, str],
    builder_receipt: dict[str, Any],
    builder_archive_receipt: dict[str, Any],
    image_lock: OpenToolchainImageLock,
    open_comparison: dict[str, Any],
    official: dict[str, Any],
    binding: dict[str, Any],
    cleanup: dict[str, Any],
) -> dict[str, Any]:
    eligible = (
        builder_receipt.get("binding_passed") is True
        and builder_archive_receipt.get("archive_structure_passed") is True
        and open_comparison.get("base_failed") is True
        and open_comparison.get("reference_passed") is True
        and official.get("base_failed") is True
        and official.get("reference_passed") is True
        and image_lock.identity == IDENTITY
        and image_lock.security_scan_passed is True
        and cleanup.get("cleanup_complete") is True
    )
    if not eligible:
        raise ConfigurationError("v180 refuses a partial qualification contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v180_qualification_contract_v1",
        "identity": IDENTITY,
        "manifest_hash": successor.manifest_hash,
        "upstream_manifest_hash": manifest.manifest_hash,
        "predecessor_report_hash": successor.predecessor_report_hash,
        "predecessor_result_tree_hash": successor.predecessor_result_tree_hash,
        "predecessor_audit_commit": successor.predecessor_audit_commit,
        "predecessor_audit_merge_commit": successor.predecessor_audit_merge_commit,
        "source_commit": source_commit,
        "post_merge_main_run_id": post_merge_main_run_id,
        "post_merge_main_all_eight_classes_passed": True,
        "task_id": manifest.task.task_id,
        "archive_receipt_hash": archive_receipt["receipt_hash"],
        "patch_compatibility_receipt_hash": patch_receipt["receipt_hash"],
        "task_hash": source_binding["task_hash"],
        "source_hash": source_binding["source_hash"],
        "local_builder_image_id": builder.local_builder_image_id,
        "local_builder_archive_receipt_hash": builder_archive_receipt["receipt_hash"],
        "local_builder_binding_hash": builder_receipt["binding_hash"],
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "agent_command_image": image_lock.image_id,
        "agent_command_image_lock_hash": image_lock.lock_hash,
        "agent_result_role": "agent_only_non_authoritative",
        "agent_base_failed": True,
        "agent_reference_passed": True,
        "official_verifier_image": manifest.official_verifier_image,
        "official_result_role": "benchmark_authoritative",
        "official_base_failed": True,
        "official_reference_passed": True,
        "toolchain_verifier_binding_hash": binding["binding_hash"],
        "repository_digest_parser": builder.repository_digest_parser,
        "dind_repository_digest": (
            f"{builder.dind_repository_name}@{builder.dind_repository_digest}"
        ),
        "dind_mount_repair": "omit-bare-rw-on-two-writable-bind-mounts",
        "all_runtime_and_build_networks": "none",
        "registry_accessed": False,
        "download_performed": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "partial_authorization_published": False,
        "requires_independent_v181_audit": True,
        "v182_canary_authorized": False,
        "retained_dind_reopen_budget": 1,
        **_closed_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


@contextmanager
def _patched_inherited_runtime() -> Iterator[None]:
    replacements = {
        "IDENTITY": IDENTITY,
        "OPT_IN_ENV": OPT_IN_ENV,
        "SANITIZED_CHILD_ENV": SANITIZED_CHILD_ENV,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "SCRATCH_ROOT": SCRATCH_ROOT,
        "DATA_BACKING": DATA_BACKING,
        "SOCKET_BACKING": SOCKET_BACKING,
        "FINAL_IMAGE_TAG": FINAL_IMAGE_TAG,
        "OWNER": OWNER,
        "_REQUIRED_MERGED_PATHS": _REQUIRED_MERGED_PATHS,
    }
    previous = {name: getattr(v178, name) for name in replacements}
    for name, value in replacements.items():
        setattr(v178, name, value)
    try:
        with v178._patched_v172_runtime():  # noqa: SLF001
            yield
    finally:
        for name, value in previous.items():
            setattr(v178, name, value)


def _require_execution_boundary(
    arguments: argparse.Namespace,
    manifest: OpenToolchainV180DindMountRepairManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v180 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v180 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v180 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v180 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= manifest.predecessor_audit_post_merge_main_run_id:
        raise ConfigurationError("v180 requires a new post-merge main run identity")


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
            raise ConfigurationError("v180 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        if subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=False).returncode != 0:
            raise ConfigurationError("v180 tracked repository state is dirty")
    if set(_git("ls-files", "--others", "--exclude-standard").splitlines()) != set(
        _ALLOWED_UNTRACKED_PATHS
    ):
        raise ConfigurationError("v180 untracked repository inventory changed")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "origin/main")
    if branch != "main" or head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("v180 requires clean merged origin/main")
    return head


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
        raise ConfigurationError(f"v180 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v180 {label} identity changed")
    return resolved


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_dir():
        raise ConfigurationError(f"v180 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v180 {label} identity changed")
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


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "qualification_contract_published": report["qualification_contract_published"],
                "provider_calls": report["provider_calls"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
