#!/usr/bin/env python3
"""Qualify PR-1816 with one exact, complete, already-local open-tool builder."""

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
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
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
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v176_open_toolchain_repair as v176,
)
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
    load_open_toolchain_manifest,
)
from verigym.hwe.open_toolchain_local_builder import (  # noqa: E402
    V178_IDENTITY,
    OpenToolchainV178LocalBuilderManifest,
    load_v178_local_builder_manifest,
)
from verigym.hwe.open_toolchain_repair import load_v176_repair_manifest  # noqa: E402
from verigym.hwe.open_toolchain_successor import exact_repository_digest  # noqa: E402

IDENTITY = V178_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V178_LOCAL_BUILDER"
SANITIZED_CHILD_ENV = "VERIGYM_V178_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / ("configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json")
UPSTREAM_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
)
PREDECESSOR_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v176_open_toolchain_repair_v1.json"
)
ARCHIVE_ROOT = Path("/data2/jiadongzhu/Agent/hwe-bench-public-images")
PREDECESSOR_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v178-local-builder-qualification-v1"
)
SCRATCH_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v178-local-builder")
DATA_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v178/data")
SOCKET_BACKING = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v178/socket")
FINAL_IMAGE_TAG = "verigym/open-rtl-tools:hwe-v178-pr1816"
OWNER = "deepseek-harness-hwe-v178-local-builder"
_DIND_TAG = "docker:23.0.6-dind"
_HISTORY_FORMAT = "{{json .CreatedBy}}"
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json",
    "docker/open-rtl-tools/Dockerfile",
    "docker/open-rtl-tools-hwe/Dockerfile.v178",
    "docs/audits/2026-09-06_deepseek-harness-v177-v176-offline-cache-stop.md",
    "docs/audits/2026-09-06_deepseek-harness-v178-local-builder-authorization.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v178_local_builder.py",
    "scripts/launch_hwe_deepseek_harness_v178_local_builder.py",
    "scripts/materialize_hwe_deepseek_harness_v178_local_builder.py",
    "src/verigym/hwe/open_toolchain_local_builder.py",
    "tests/unit/test_hwe_open_toolchain_local_builder.py",
)
_ALLOWED_UNTRACKED_PATHS = frozenset(
    {
        "configs/training/qwen35_hwe_openhands_v56_direct_oci_provisioning_v1.json",
        "integrations/verigym-openhands/src/verigym_openhands/hwe_v56_direct_oci_provisioning.py",
        "scripts/download_hwe_bench_public_images.txt",
        "src/verigym/hwe/oci_resumable.py",
        "src/verigym/hwe/public_ghcr.py",
        "tests/unit/test_hwe_oci_resumable.py",
        "tests/unit/test_hwe_public_ghcr.py",
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
    """Run the one authorized v178 qualification with zero provider surface."""

    successor = load_v178_local_builder_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    upstream = _load_and_bind_upstream(successor)
    runtime = _runtime_manifest(successor, upstream)
    _require_execution_boundary(arguments, successor)
    source_commit = _require_clean_merged_main()
    archive_root = _exact_directory(arguments.archive_root, ARCHIVE_ROOT, "archive root")
    with _patched_v172_runtime():
        builder_archive_receipt = _preflight_inputs(successor, runtime, archive_root=archive_root)
        root = v172._new_output(arguments.output, runtime)  # noqa: SLF001
        scratch = v172._new_scratch(runtime)  # noqa: SLF001
        return _execute(
            arguments,
            successor=successor,
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
    successor: OpenToolchainV178LocalBuilderManifest,
    manifest: OpenToolchainQualificationManifest,
    archive_root: Path,
    root: Path,
    scratch: Path,
    source_commit: str,
    builder_archive_receipt: dict[str, Any],
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v178_progress_v1",
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

        builder_id = successor.local_builder_image_id
        transfers = _save_transfer_images(successor, manifest=manifest, scratch=scratch)
        progress["status"] = "isolated_dind_start"
        _write_progress(root, progress)
        v172._prepare_dind_backings(manifest)  # noqa: SLF001
        v172._create_bind_volume(manifest.dind_data_volume, DATA_BACKING)  # noqa: SLF001
        v172._create_bind_volume(manifest.dind_socket_volume, SOCKET_BACKING)  # noqa: SLF001
        dind_name = f"verigym-dind-v178-{secrets.token_hex(8)}"
        dind_receipt = v172._start_dind(  # noqa: SLF001
            dind_name, manifest, root=root, scratch=scratch
        )
        atomic_dump_json(root / "dind-runtime.json", dind_receipt)
        docker_host = f"unix://{SOCKET_BACKING / 'docker.sock'}"

        progress["status"] = "open_toolchain_build"
        _write_progress(root, progress)
        with v172._docker_host(docker_host):  # noqa: SLF001
            v172._load_transfer_images(  # noqa: SLF001
                manifest,
                builder_id=builder_id,
                transfers=transfers,
                docker_host=docker_host,
            )
            progress["status"] = "local_complete_builder_binding"
            _write_progress(root, progress)
            builder_id, builder_receipt = _bind_and_probe_local_builder(
                successor, manifest, docker_host=docker_host
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
                raise ConfigurationError("v178 official route is not base-FAIL/reference-PASS")
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
        cleanup = _success_cleanup(successor, manifest=manifest, scratch=scratch)
        data_retained = True
        atomic_dump_json(root / "cleanup.json", cleanup)
        contract = _qualification_contract(
            successor,
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
                "status": "completed_pending_independent_v179_audit",
                "qualification_contract_published": True,
                "qualification_contract_hash": contract["contract_hash"],
                "retained_dind_reopen_budget": 1,
                "v180_canary_authorized": False,
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


def _load_and_bind_upstream(
    successor: OpenToolchainV178LocalBuilderManifest,
) -> OpenToolchainQualificationManifest:
    path = _REPOSITORY / successor.upstream_manifest_path
    if path != UPSTREAM_MANIFEST or _hash_file(path) != successor.upstream_manifest_sha256:
        raise ConfigurationError("v178 frozen upstream manifest file changed")
    manifest = load_open_toolchain_manifest(path)
    if manifest.manifest_hash != successor.upstream_manifest_hash:
        raise ConfigurationError("v178 frozen upstream manifest identity changed")
    return manifest


def _runtime_manifest(
    successor: OpenToolchainV178LocalBuilderManifest,
    upstream: OpenToolchainQualificationManifest,
) -> OpenToolchainQualificationManifest:
    """Apply only reviewed v178 builder, Dockerfile, and resource identities."""

    return upstream.model_copy(
        update={
            "builder_tag": successor.builder_tag,
            "final_dockerfile": successor.final_dockerfile,
            "final_dockerfile_sha256": successor.final_dockerfile_sha256,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )


def _preflight_inputs(
    successor: OpenToolchainV178LocalBuilderManifest,
    manifest: OpenToolchainQualificationManifest,
    *,
    archive_root: Path,
) -> dict[str, Any]:
    _validate_predecessor_evidence(successor)
    expected = {
        _REPOSITORY / manifest.builder_source_dockerfile: manifest.builder_source_dockerfile_sha256,
        _REPOSITORY / manifest.final_dockerfile: manifest.final_dockerfile_sha256,
        Path(manifest.verilator_archive_path): manifest.verilator_archive_sha256,
        Path(manifest.ripgrep_archive_path): manifest.ripgrep_archive_sha256,
        _REPOSITORY / manifest.predecessor_audit_path: manifest.predecessor_audit_sha256,
    }
    for path, digest in expected.items():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name.endswith(".partial")
            or _hash_file(path) != digest
        ):
            raise ConfigurationError("v178 frozen input identity changed")
    final_text = (_REPOSITORY / manifest.final_dockerfile).read_text(encoding="utf-8")
    if (
        "verigym/open-rtl-tools:v178-builder" not in final_text
        or "ghcr.io/pku-liang" in final_text
        or "RUN curl" in final_text
        or "RUN wget" in final_text
    ):
        raise ConfigurationError("v178 final Dockerfile boundary changed")
    rg_binary = Path(manifest.ripgrep_archive_path).parent / (
        "ripgrep-15.2.0-x86_64-unknown-linux-musl/rg"
    )
    if (
        rg_binary.is_symlink()
        or not rg_binary.is_file()
        or _hash_file(rg_binary) != manifest.ripgrep_binary_sha256
    ):
        raise ConfigurationError("v178 ripgrep executable identity changed")
    if v172._docker_image_id(manifest.accepted_open_tools_tag) != (  # noqa: SLF001
        manifest.accepted_open_tools_image_id
    ):
        raise ConfigurationError("v178 accepted open-tools image identity changed")
    if v172._docker_image_id(_DIND_TAG) != manifest.dind_image_id:  # noqa: SLF001
        raise ConfigurationError("v178 DinD tag identity changed")
    dind = v172._inspect_image(_DIND_TAG)  # noqa: SLF001
    if dind is None:
        raise ConfigurationError("v178 DinD image inspection is missing")
    exact_repository_digest(
        dind.get("RepoDigests"),
        expected_repository=successor.dind_repository_name,
        expected_digest=successor.dind_repository_digest,
    )
    if dind.get("Id") != manifest.dind_image_id or (dind.get("Os"), dind.get("Architecture")) != (
        "linux",
        "amd64",
    ):
        raise ConfigurationError("v178 DinD immutable identity or platform changed")
    builder_archive_receipt = _builder_archive_receipt(successor)
    for path in (OUTPUT_ROOT, SCRATCH_ROOT, DATA_BACKING, SOCKET_BACKING):
        if path.exists() or path.is_symlink():
            raise ConfigurationError("v178 resource path must be fresh")
    if (
        v172._volume_exists(manifest.dind_data_volume)  # noqa: SLF001
        or v172._volume_exists(manifest.dind_socket_volume)  # noqa: SLF001
        or v172._docker_image_id(manifest.builder_tag, required=False) is not None  # noqa: SLF001
        or v172._docker_image_id(FINAL_IMAGE_TAG, required=False) is not None  # noqa: SLF001
        or v172._owned_containers()  # noqa: SLF001
    ):
        raise ConfigurationError("v178 campaign resource identity is not fresh")
    inspect_offline_image_archive(manifest.task, archive_root=archive_root)
    return builder_archive_receipt


def _builder_archive_receipt(
    successor: OpenToolchainV178LocalBuilderManifest,
) -> dict[str, Any]:
    archive = Path(successor.local_builder_archive_path)
    sidecar = Path(successor.local_builder_archive_sidecar_path)
    parent = archive.parent
    archive_stat = archive.stat() if archive.is_file() and not archive.is_symlink() else None
    sidecar_stat = sidecar.stat() if sidecar.is_file() and not sidecar.is_symlink() else None
    parent_stat = parent.stat() if parent.is_dir() and not parent.is_symlink() else None
    if (
        archive_stat is None
        or sidecar_stat is None
        or parent_stat is None
        or archive.name.endswith(".partial")
        or archive_stat.st_size != successor.local_builder_archive_bytes
        or stat.S_IMODE(archive_stat.st_mode) != 0o600
        or stat.S_IMODE(sidecar_stat.st_mode) != 0o600
        or stat.S_IMODE(parent_stat.st_mode) != 0o700
        or any(
            metadata.st_uid != os.getuid() or metadata.st_gid != os.getgid()
            for metadata in (archive_stat, sidecar_stat, parent_stat)
        )
        or _hash_file(archive) != successor.local_builder_archive_sha256
        or _hash_file(sidecar) != successor.local_builder_archive_sidecar_sha256
    ):
        raise ConfigurationError("v178 local builder archive identity changed")
    expected_sidecar = f"{successor.local_builder_archive_sha256}  {archive.name}\n".encode("ascii")
    if sidecar.read_bytes() != expected_sidecar:
        raise ConfigurationError("v178 local builder archive sidecar changed")

    layer_directories = {
        PurePosixPath(item).parts[0] for item in successor.local_builder_archive_layers
    }
    expected_files = {
        successor.local_builder_archive_config,
        "manifest.json",
        "repositories",
        *(f"{directory}/{name}" for directory in layer_directories for name in ("VERSION", "json")),
        *successor.local_builder_archive_layers,
    }
    expected_members = expected_files | layer_directories
    try:
        with tarfile.open(archive, mode="r:") as bundle:
            members = bundle.getmembers()
            names = [member.name for member in members]
            if (
                len(names) != len(set(names))
                or set(names) != expected_members
                or any(
                    PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                    for name in names
                )
                or any(
                    member.uid != 0
                    or member.gid != 0
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or (member.name in layer_directories) != member.isdir()
                    or (member.name in expected_files) != member.isfile()
                    for member in members
                )
            ):
                raise ConfigurationError("v178 local builder archive inventory changed")
            manifest_value = _read_tar_json(bundle, "manifest.json", maximum=4096)
            repositories = _read_tar_json(bundle, "repositories", maximum=4096)
            config_bytes = _read_tar_member(
                bundle, successor.local_builder_archive_config, maximum=65536
            )
            config_value = json.loads(config_bytes)
    except (OSError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v178 local builder archive is malformed") from exc

    expected_manifest = [
        {
            "Config": successor.local_builder_archive_config,
            "RepoTags": [successor.local_builder_provenance_tag],
            "Layers": list(successor.local_builder_archive_layers),
        }
    ]
    repository, _, tag = successor.local_builder_provenance_tag.partition(":")
    expected_repositories = {
        repository: {tag: PurePosixPath(successor.local_builder_archive_layers[-1]).parts[0]}
    }
    config_document = config_value if isinstance(config_value, dict) else {}
    config = config_document.get("config")
    rootfs = config_document.get("rootfs")
    if (
        manifest_value != expected_manifest
        or repositories != expected_repositories
        or hashlib.sha256(config_bytes).hexdigest()
        != successor.local_builder_image_id.removeprefix("sha256:")
        or config_document.get("created") != successor.local_builder_created
        or (config_document.get("os"), config_document.get("architecture")) != ("linux", "amd64")
        or not isinstance(config, dict)
        or not isinstance(rootfs, dict)
        or config.get("Image") != successor.local_builder_parent_image_id
        or config.get("User") != ""
        or config.get("Env")
        != ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
        or config.get("Cmd") != ["bash"]
        or config.get("Entrypoint") not in (None, [])
        or config.get("WorkingDir") != ""
        or config.get("Labels") not in (None, {})
        or config.get("Volumes") not in (None, {})
        or rootfs.get("type") != "layers"
        or tuple(rootfs.get("diff_ids") or ()) != successor.local_builder_rootfs_layers
    ):
        raise ConfigurationError("v178 local builder archive metadata changed")
    history_values = config_document.get("history")
    if not isinstance(history_values, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("created_by"), str)
        for item in history_values
    ):
        raise ConfigurationError("v178 local builder archive history is malformed")
    history = b"".join(
        (json.dumps(item["created_by"], separators=(",", ":"), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        for item in reversed(history_values)
    )
    _validate_builder_history(successor, history)
    inventory = [
        {
            "name": member.name,
            "size": member.size,
            "mode": member.mode,
            "type": member.type.decode("ascii"),
        }
        for member in members
    ]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v178_local_builder_archive_v1",
        "identity": IDENTITY,
        "archive_path": archive.as_posix(),
        "archive_sha256": successor.local_builder_archive_sha256,
        "archive_bytes": archive_stat.st_size,
        "archive_sidecar_sha256": successor.local_builder_archive_sidecar_sha256,
        "archive_member_count": len(members),
        "archive_member_inventory_hash": content_hash(inventory),
        "image_id": successor.local_builder_image_id,
        "rootfs_layers_hash": content_hash(list(successor.local_builder_rootfs_layers)),
        "history_sha256": successor.local_builder_history_sha256,
        "archive_structure_passed": True,
        "raw_config_persisted": False,
        "raw_history_persisted": False,
        "partial_archive_used": False,
        "registry_accessed": False,
        "download_performed": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _read_tar_member(bundle: tarfile.TarFile, name: str, *, maximum: int) -> bytes:
    member = bundle.getmember(name)
    if not member.isfile() or not 0 < member.size <= maximum:
        raise ConfigurationError("v178 local builder archive control member changed")
    stream = bundle.extractfile(member)
    if stream is None:
        raise ConfigurationError("v178 local builder archive control member is unavailable")
    value = stream.read(maximum + 1)
    if len(value) != member.size:
        raise ConfigurationError("v178 local builder archive control member is truncated")
    return value


def _read_tar_json(bundle: tarfile.TarFile, name: str, *, maximum: int) -> Any:
    return json.loads(_read_tar_member(bundle, name, maximum=maximum))


def _save_transfer_images(
    successor: OpenToolchainV178LocalBuilderManifest,
    *,
    manifest: OpenToolchainQualificationManifest,
    scratch: Path,
) -> dict[str, Path]:
    accepted = scratch / "accepted-open-tools.tar"
    v172._run_quiet(  # noqa: SLF001
        [
            "docker",
            "image",
            "save",
            "--output",
            str(accepted),
            manifest.accepted_open_tools_image_id,
        ],
        timeout=1800,
    )
    builder = Path(successor.local_builder_archive_path)
    if (
        accepted.is_symlink()
        or not accepted.is_file()
        or not 0 < accepted.stat().st_size <= 8 * 1024**3
        or builder.is_symlink()
        or not builder.is_file()
        or builder.stat().st_size != successor.local_builder_archive_bytes
        or _hash_file(builder) != successor.local_builder_archive_sha256
    ):
        raise ConfigurationError("v178 image transfer archive is unsafe")
    return {"accepted": accepted, "builder": builder}


def _validate_local_builder(
    successor: OpenToolchainV178LocalBuilderManifest,
    manifest: OpenToolchainQualificationManifest,
    *,
    docker_host: str,
) -> None:
    image = v172._inspect_image(  # noqa: SLF001
        successor.local_builder_image_id, host=docker_host, required=False
    )
    official = v172._inspect_image(  # noqa: SLF001
        manifest.official_verifier_image, host=docker_host, required=False
    )
    if image is None:
        raise ConfigurationError("v178 exact local builder image is missing")
    config = image.get("Config") or {}
    rootfs = image.get("RootFS") or {}
    checks = {
        "image_id": image.get("Id") == successor.local_builder_image_id,
        "created": image.get("Created") == successor.local_builder_created,
        "platform": (image.get("Os"), image.get("Architecture")) == ("linux", "amd64"),
        "layers": tuple(rootfs.get("Layers") or ()) == successor.local_builder_rootfs_layers,
        "parent": config.get("Image") == successor.local_builder_parent_image_id,
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
        raise ConfigurationError("v178 exact local builder metadata changed")
    history = _local_builder_history(successor, docker_host=docker_host)
    _validate_builder_history(successor, history)
    if official is not None and v172._is_ancestor_layers(official, image):  # noqa: SLF001
        raise ConfigurationError("v178 local builder descends from the HWE task image")


def _validate_builder_history(
    successor: OpenToolchainV178LocalBuilderManifest, history: bytes
) -> None:
    sensitive = v176._contains_sensitive_output(history, b"")  # noqa: SLF001
    text = history.decode("utf-8", errors="strict")
    required = (
        "apt-get install --yes --no-install-recommends",
        "autoconf automake bison ca-certificates cmake curl flex g++ libeigen3-dev",
        "libtool make ninja-build swig tcl-dev zlib1g-dev",
        "OPENSTA_COMMIT=be771a0116985d57effb4120668ae98e8a7b0f79",
        "# debian.sh --arch 'amd64' out/ 'trixie' '@1783900800'",
    )
    if (
        sensitive
        or len(history) != successor.local_builder_history_bytes
        or history.count(b"\n") != successor.local_builder_history_lines
        or hashlib.sha256(history).hexdigest() != successor.local_builder_history_sha256
        or any(value not in text for value in required)
        or "hwe" in text.lower()
        or "codex" in text.lower()
    ):
        raise ConfigurationError("v178 local builder provenance history changed")


def _local_builder_history(
    successor: OpenToolchainV178LocalBuilderManifest, *, docker_host: str
) -> bytes:
    result = v176._run_bounded_process(  # noqa: SLF001
        [
            "docker",
            "--host",
            docker_host,
            "history",
            "--no-trunc",
            "--format",
            _HISTORY_FORMAT,
            successor.local_builder_image_id,
        ],
        timeout=60,
        maximum=successor.builder_probe_max_bytes,
    )
    if (
        result.returncode != 0
        or result.timed_out
        or not result.output_within_bound
        or result.stderr
    ):
        raise ConfigurationError("v178 local builder history binding changed")
    return result.stdout


def _bind_and_probe_local_builder(
    successor: OpenToolchainV178LocalBuilderManifest,
    manifest: OpenToolchainQualificationManifest,
    *,
    docker_host: str,
) -> tuple[str, dict[str, Any]]:
    _validate_local_builder(successor, manifest, docker_host=docker_host)
    if (
        v172._docker_image_id(manifest.builder_tag, host=docker_host)  # noqa: SLF001
        != successor.local_builder_image_id
    ):
        raise ConfigurationError("v178 inner builder tag identity changed")
    probe = _probe_local_builder(successor, docker_host=docker_host)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v178_local_builder_binding_v1",
        "identity": IDENTITY,
        "acquisition": successor.local_builder_acquisition,
        "origin": successor.local_builder_origin,
        "image_id": successor.local_builder_image_id,
        "archive_sha256": successor.local_builder_archive_sha256,
        "rootfs_layer_count": len(successor.local_builder_rootfs_layers),
        "rootfs_layers_hash": content_hash(list(successor.local_builder_rootfs_layers)),
        "history_sha256": successor.local_builder_history_sha256,
        "history_bytes": successor.local_builder_history_bytes,
        "history_lines": successor.local_builder_history_lines,
        "package_inventory_sha256": successor.local_builder_package_inventory_sha256,
        "package_inventory_bytes": successor.local_builder_package_inventory_bytes,
        "package_inventory_lines": successor.local_builder_package_inventory_lines,
        "required_binary_sha256": successor.local_builder_required_binary_sha256,
        "required_versions": successor.local_builder_required_versions,
        "probe_output_sha256": probe["output_sha256"],
        "probe_output_bytes": probe["output_bytes"],
        "network": "none",
        "read_only_root": True,
        "non_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "mount_count": 0,
        "hwe_task_image_ancestor": False,
        "raw_history_persisted": False,
        "raw_probe_output_persisted": False,
        "registry_accessed": False,
        "download_performed": False,
        "binding_passed": True,
    }
    return successor.local_builder_image_id, {**base, "binding_hash": content_hash(base)}


def _probe_local_builder(
    successor: OpenToolchainV178LocalBuilderManifest, *, docker_host: str
) -> dict[str, Any]:
    name = f"verigym-v178-builder-probe-{secrets.token_hex(6)}"
    binary_paths = {
        name: f"/usr/bin/{name}" for name in successor.local_builder_required_binary_sha256
    }
    commands = [
        "set -eu",
        f"sha256sum {' '.join(binary_paths.values())}",
        "LC_ALL=C dpkg-query -W | LC_ALL=C sort > /tmp/packages",
        "printf 'package.sha256='; sha256sum /tmp/packages",
        "printf 'package.count='; wc -c -l /tmp/packages",
        "printf 'version.autoconf='; autoconf --version | sed -n '1p'",
        "printf 'version.bison='; bison --version | sed -n '1p'",
        "printf 'version.flex='; flex --version",
        "printf 'version.g++='; g++ --version | sed -n '1p'",
        "printf 'version.make='; make --version | sed -n '1p'",
        "printf 'version.perl='; perl -e 'print qq(perl $^V\\n)'",
        "! command -v iverilog",
        "! command -v vvp",
        "! command -v yosys",
        "! command -v verilator",
        "! command -v opensta",
        "test ! -e /opt/iverilog",
        "test ! -e /opt/yosys",
        "test ! -e /tools",
        "test ! -e /root/.codex",
        "test ! -e /hwe",
    ]
    create = [
        "docker",
        "--host",
        docker_host,
        "container",
        "create",
        "--name",
        name,
        "--label",
        f"verigym.owner={OWNER}",
        "--label",
        "verigym.role=local-builder-probe",
        "--network",
        "none",
        "--read-only",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--cpus",
        "1",
        "--ipc",
        "none",
        "--init",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=32m",
        "--workdir",
        "/",
        successor.local_builder_image_id,
        "/bin/sh",
        "-c",
        "; ".join(commands),
    ]
    container_id = v172._run(create, timeout=60).decode().strip()  # noqa: SLF001
    try:
        inspection = v172._inspect_container(container_id, host=docker_host)  # noqa: SLF001
        host = inspection.get("HostConfig") or {}
        config = inspection.get("Config") or {}
        if (
            host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("CapAdd") not in (None, [])
            or host.get("CapDrop") != ["ALL"]
            or "no-new-privileges" not in (host.get("SecurityOpt") or [])
            or config.get("User") != f"{os.getuid()}:{os.getgid()}"
            or inspection.get("Mounts") not in (None, [])
        ):
            raise ConfigurationError("v178 local builder probe isolation changed")
        result = v176._run_bounded_process(  # noqa: SLF001
            ["docker", "--host", docker_host, "start", "--attach", container_id],
            timeout=120,
            maximum=successor.builder_probe_max_bytes,
        )
        sensitive = v176._contains_sensitive_output(result.stdout, result.stderr)  # noqa: SLF001
        output = result.stdout + result.stderr
        text = output.decode("utf-8", errors="strict")
        observed: dict[str, str] = {}
        for line in text.splitlines():
            digest, separator, path = line.partition("  ")
            for name, expected_path in binary_paths.items():
                if separator and path == expected_path:
                    observed[name] = digest
        package_hash_line = next(
            (line for line in text.splitlines() if line.startswith("package.sha256=")), ""
        )
        package_count_line = next(
            (line for line in text.splitlines() if line.startswith("package.count=")), ""
        )
        version_lines = {
            name: next(
                (line for line in text.splitlines() if line.startswith(f"version.{name}=")), ""
            )
            for name in successor.local_builder_required_versions
        }
        if (
            sensitive
            or result.returncode != 0
            or result.timed_out
            or not result.output_within_bound
            or observed != successor.local_builder_required_binary_sha256
            or package_hash_line
            != f"package.sha256={successor.local_builder_package_inventory_sha256}  /tmp/packages"
            or package_count_line.split()[1:3]
            != [
                str(successor.local_builder_package_inventory_lines),
                str(successor.local_builder_package_inventory_bytes),
            ]
            or any(
                version not in version_lines[name]
                for name, version in successor.local_builder_required_versions.items()
            )
        ):
            raise ConfigurationError("v178 local builder probe failed")
        return {
            "output_sha256": hashlib.sha256(output).hexdigest(),
            "output_bytes": len(output),
        }
    finally:
        removed = v172._run_result(  # noqa: SLF001
            ["docker", "--host", docker_host, "container", "rm", "--force", container_id],
            timeout=60,
        )
        if removed.returncode != 0:
            raise ConfigurationError("v178 local builder probe cleanup failed")


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
    scan_base["scan_id"] = "v178-open-toolchain-scan-v1"
    scan = {**scan_base, "scan_hash": content_hash(scan_base)}
    lock_base = image_lock.model_dump(mode="json", exclude={"lock_hash"})
    lock_base["security_scan_id"] = scan["scan_id"]
    image_lock = OpenToolchainImageLock.model_validate(
        {**lock_base, "lock_hash": content_hash(lock_base)}
    )
    return scan, image_lock


def _success_cleanup(
    successor: OpenToolchainV178LocalBuilderManifest,
    *,
    manifest: OpenToolchainQualificationManifest,
    scratch: Path,
) -> dict[str, Any]:
    inherited = v172._success_cleanup(manifest, scratch=scratch)  # noqa: SLF001
    inherited_base = dict(inherited)
    inherited_base.pop("receipt_hash")
    inherited_base.update(
        {
            "format_id": "verigym_deepseek_harness_hwe_v178_cleanup_v1",
            "temporary_transfer_archives_removed": True,
            "persistent_builder_archive_retained": True,
            "persistent_builder_archive_sha256": successor.local_builder_archive_sha256,
        }
    )
    archive = Path(successor.local_builder_archive_path)
    if (
        not archive.is_file()
        or archive.is_symlink()
        or archive.stat().st_size != successor.local_builder_archive_bytes
        or _hash_file(archive) != successor.local_builder_archive_sha256
    ):
        raise ConfigurationError("v178 persistent builder archive was not retained")
    return {**inherited_base, "receipt_hash": content_hash(inherited_base)}


def _validate_predecessor_evidence(successor: OpenToolchainV178LocalBuilderManifest) -> None:
    predecessor_manifest = _REPOSITORY / successor.predecessor_manifest_path
    if (
        predecessor_manifest != PREDECESSOR_MANIFEST
        or _hash_file(predecessor_manifest) != successor.predecessor_manifest_sha256
        or load_v176_repair_manifest(predecessor_manifest).manifest_hash
        != successor.predecessor_manifest_hash
    ):
        raise ConfigurationError("v178 predecessor manifest changed")
    if Path(successor.predecessor_result_root) != PREDECESSOR_ROOT:
        raise ConfigurationError("v178 predecessor result root changed")
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
        raise ConfigurationError("v178 predecessor result tree changed")
    for entry in entries:
        metadata = entry.stat() if entry.is_file() and not entry.is_symlink() else None
        if (
            metadata is None
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
            or _hash_file(entry) != successor.predecessor_result_file_sha256[entry.name]
        ):
            raise ConfigurationError("v178 predecessor result file changed")
    try:
        report = json.loads((PREDECESSOR_ROOT / "zero-provider-report.json").read_bytes())
        diagnostic = json.loads((PREDECESSOR_ROOT / "builder-diagnostic.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v178 predecessor evidence is malformed") from exc
    report_base = dict(report) if isinstance(report, dict) else {}
    report_hash = report_base.pop("report_hash", None)
    required = {
        "format_id": "verigym_deepseek_harness_hwe_v176_progress_v1",
        "identity": successor.predecessor_identity,
        "status": "stopped_without_qualification_contract",
        "manifest_hash": successor.predecessor_manifest_hash,
        "upstream_manifest_hash": successor.upstream_manifest_hash,
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
    ):
        raise ConfigurationError("v178 predecessor report binding changed")
    diagnostic_base = dict(diagnostic) if isinstance(diagnostic, dict) else {}
    diagnostic_hash = diagnostic_base.pop("diagnostic_hash", None)
    if (
        diagnostic_hash != successor.predecessor_builder_diagnostic_hash
        or content_hash(diagnostic_base) != diagnostic_hash
        or diagnostic_base.get("category") != successor.predecessor_builder_diagnostic_category
        or diagnostic_base.get("credential_scan_passed") is not True
        or diagnostic_base.get("raw_output_persisted") is not False
    ):
        raise ConfigurationError("v178 predecessor builder diagnostic changed")
    audit = _REPOSITORY / successor.predecessor_audit_path
    if (
        audit.is_symlink()
        or not audit.is_file()
        or _hash_file(audit) != successor.predecessor_audit_sha256
    ):
        raise ConfigurationError("v178 predecessor audit changed")


def _qualification_contract(
    successor: OpenToolchainV178LocalBuilderManifest,
    *,
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
        raise ConfigurationError("v178 refuses a partial qualification contract")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v178_qualification_contract_v1",
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
        "local_builder_image_id": successor.local_builder_image_id,
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
        "repository_digest_parser": successor.repository_digest_parser,
        "dind_repository_digest": (
            f"{successor.dind_repository_name}@{successor.dind_repository_digest}"
        ),
        "all_runtime_and_build_networks": "none",
        "registry_accessed": False,
        "download_performed": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "partial_authorization_published": False,
        "requires_independent_v179_audit": True,
        "v180_canary_authorized": False,
        "retained_dind_reopen_budget": 1,
        **_closed_flags(),
    }
    return {**base, "contract_hash": content_hash(base)}


@contextmanager
def _patched_v172_runtime() -> Iterator[None]:
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
    previous = {name: getattr(v172, name) for name in replacements}
    for name, value in replacements.items():
        setattr(v172, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(v172, name, value)


def _require_execution_boundary(
    arguments: argparse.Namespace,
    manifest: OpenToolchainV178LocalBuilderManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v178 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v178 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v178 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v178 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= manifest.predecessor_audit_post_merge_main_run_id:
        raise ConfigurationError("v178 requires a new post-merge main run identity")


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
            raise ConfigurationError("v178 required merged path is not tracked")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        if subprocess.run(["git", *arguments], cwd=_REPOSITORY, check=False).returncode != 0:
            raise ConfigurationError("v178 tracked repository state is dirty")
    if set(_git("ls-files", "--others", "--exclude-standard").splitlines()) != set(
        _ALLOWED_UNTRACKED_PATHS
    ):
        raise ConfigurationError("v178 untracked repository inventory changed")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "origin/main")
    if branch != "main" or head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("v178 requires clean merged origin/main")
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
        raise ConfigurationError(f"v178 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v178 {label} identity changed")
    return resolved


def _exact_directory(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_dir():
        raise ConfigurationError(f"v178 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v178 {label} identity changed")
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
