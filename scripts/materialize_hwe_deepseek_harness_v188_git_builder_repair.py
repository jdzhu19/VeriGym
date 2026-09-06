#!/usr/bin/env python3
"""Run the one-use task-free v188 offline git builder repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
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

from scripts import materialize_hwe_deepseek_harness_v172_open_toolchain as v172  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v176_open_toolchain_repair as v176,
)
from scripts import materialize_hwe_deepseek_harness_v178_local_builder as v178  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v182_bounded_open_build as v182,
)
from scripts import materialize_hwe_deepseek_harness_v184_missing_command as v184  # noqa: E402
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v186_diagnostic_context as v186,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
)
from verigym.hwe.open_toolchain_build_diagnostic import (  # noqa: E402
    OpenToolchainV182BuildDiagnosticManifest,
)
from verigym.hwe.open_toolchain_diagnostic_context import (  # noqa: E402
    OpenToolchainV186DiagnosticContextManifest,
    load_v186_diagnostic_context_manifest,
)
from verigym.hwe.open_toolchain_git_builder_repair import (  # noqa: E402
    V188_IDENTITY,
    OpenToolchainV188GitBuilderRepairManifest,
    OpenToolchainV188ImageLock,
    load_v188_git_builder_repair_manifest,
)
from verigym.hwe.open_toolchain_local_builder import (  # noqa: E402
    OpenToolchainV178LocalBuilderManifest,
)
from verigym.hwe.open_toolchain_missing_command import (  # noqa: E402
    OpenToolchainV184MissingCommandManifest,
)

IDENTITY = V188_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V188_GIT_BUILDER_REPAIR"
SANITIZED_CHILD_ENV = "VERIGYM_V188_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v188_git_builder_repair_v1.json"
)
V186_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v186_diagnostic_context_refinement_v1.json"
)
V186_RESULT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v186-diagnostic-context-refinement-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v188-git-builder-repair-v1"
)
SCRATCH_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v188-git-builder-repair")
BACKING_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v188")
DATA_BACKING = BACKING_PARENT / "data"
SOCKET_BACKING = BACKING_PARENT / "socket"
OWNER = "deepseek-harness-hwe-v188-git-builder-repair"
_BASE_BUILDER_TAG = "verigym/open-rtl-tools:v178-builder"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_HASH = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_UNTRACKED_PATHS = v178._ALLOWED_UNTRACKED_PATHS  # noqa: SLF001
_BINARY_PATHS = {
    **v172._BINARY_PATHS,  # noqa: SLF001
    "git": "/usr/bin/git",
}
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v186_diagnostic_context_refinement_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v188_git_builder_repair_v1.json",
    "docker/open-rtl-tools-hwe/Dockerfile.v180",
    "docker/open-rtl-tools-hwe/Dockerfile.v188-builder",
    "docs/audits/2026-09-06_deepseek-harness-v187-v186-result.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v188_git_builder_repair.py",
    "scripts/launch_hwe_deepseek_harness_v188_git_builder_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v186_diagnostic_context.py",
    "scripts/materialize_hwe_deepseek_harness_v188_git_builder_repair.py",
    "src/verigym/hwe/open_toolchain_diagnostic_context.py",
    "src/verigym/hwe/open_toolchain_git_builder_repair.py",
    "tests/unit/test_hwe_open_toolchain_git_builder_repair.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the sole authorized repair and always seal a terminal report."""

    successor = load_v188_git_builder_repair_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    _require_execution_boundary(arguments, successor)
    with _patched_inherited_runtime():
        source_commit = v182._require_clean_merged_main()  # noqa: SLF001
        active_sensitive_values = v182._active_sensitive_values()  # noqa: SLF001
        with v182._sanitized_process_environment():  # noqa: SLF001
            predecessor, runtime, builder, archive_receipt, package_receipt, probe_proxy = (
                _preflight_inputs(successor)
            )
            root = v182._new_output(arguments.output, runtime)  # noqa: SLF001
            scratch = v182._new_scratch(runtime)  # noqa: SLF001
            return _execute(
                arguments,
                successor=successor,
                predecessor=predecessor,
                runtime=runtime,
                builder=builder,
                root=root,
                scratch=scratch,
                source_commit=source_commit,
                active_sensitive_values=active_sensitive_values,
                archive_receipt=archive_receipt,
                package_receipt=package_receipt,
                probe_proxy=probe_proxy,
            )


def _execute(
    arguments: argparse.Namespace,
    *,
    successor: OpenToolchainV188GitBuilderRepairManifest,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
    runtime: OpenToolchainV182BuildDiagnosticManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    root: Path,
    scratch: Path,
    source_commit: str,
    active_sensitive_values: tuple[bytes, ...],
    archive_receipt: dict[str, Any],
    package_receipt: dict[str, Any],
    probe_proxy: OpenToolchainV184MissingCommandManifest,
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v188_progress_v1",
        "identity": IDENTITY,
        "manifest_hash": successor.manifest_hash,
        "predecessor_report_hash": successor.predecessor_report_hash,
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
        "minimal_git_repair_authorized": True,
        **_closed_flags(),
    }
    _write_progress(root, progress)
    category = "controller_error"
    stop_reason: str | None = None
    derived_builder_id: str | None = None
    final_image_id: str | None = None
    image_lock: OpenToolchainV188ImageLock | None = None
    archive_exported = False
    try:
        atomic_dump_json(root / "headroom.json", _headroom_receipt(successor))
        atomic_dump_json(root / "local-builder-archive.json", archive_receipt)
        atomic_dump_json(root / "git-package-archive.json", package_receipt)
        progress["status"] = "local_transfer_prepare"
        _write_progress(root, progress)
        transfers = v182._save_transfer_inputs(  # noqa: SLF001
            runtime, builder=builder, scratch=scratch
        )
        v182._prepare_dind_backings(runtime)  # noqa: SLF001
        v182._create_bind_volume(runtime.dind_data_volume, DATA_BACKING)  # noqa: SLF001
        v182._create_bind_volume(runtime.dind_socket_volume, SOCKET_BACKING)  # noqa: SLF001
        dind_name = f"verigym-dind-v188-{secrets.token_hex(8)}"
        dind_receipt = _reissue(
            v182._start_dind(dind_name, runtime, root=root, scratch=scratch),  # noqa: SLF001
            format_id="verigym_deepseek_harness_hwe_v188_dind_runtime_v1",
            hash_field="receipt_hash",
        )
        atomic_dump_json(root / "dind-runtime.json", dind_receipt)
        docker_host = f"unix://{SOCKET_BACKING / 'docker.sock'}"

        progress["status"] = "base_builder_binding"
        _write_progress(root, progress)
        v182._load_transfer_inputs(  # noqa: SLF001
            runtime, builder=builder, transfers=transfers, docker_host=docker_host
        )
        v182._run_control(  # noqa: SLF001
            [
                "docker",
                "--host",
                docker_host,
                "image",
                "tag",
                builder.local_builder_image_id,
                _BASE_BUILDER_TAG,
            ],
            timeout=30,
        )
        base_binding = _reissue(
            v182._bind_and_probe_builder(  # noqa: SLF001
                builder, runtime, docker_host=docker_host
            ),
            format_id="verigym_deepseek_harness_hwe_v188_base_builder_binding_v1",
            hash_field="binding_hash",
        )
        atomic_dump_json(root / "base-builder-binding.json", base_binding)

        progress["status"] = "offline_git_builder_repair"
        _write_progress(root, progress)
        derived_builder_id, repair = _build_git_builder(
            successor,
            builder=builder,
            scratch=scratch,
            docker_host=docker_host,
            active_sensitive_values=active_sensitive_values,
        )
        atomic_dump_json(root / "git-builder-repair.json", repair)
        category = repair["category"]
        if derived_builder_id is None:
            raise _ExpectedBuildFailure(category)
        derived_binding = _bind_repaired_builder(
            successor,
            builder=builder,
            image_id=derived_builder_id,
            docker_host=docker_host,
            active_sensitive_values=active_sensitive_values,
        )
        atomic_dump_json(root / "git-builder-binding.json", derived_binding)
        v182._run_control(  # noqa: SLF001
            [
                "docker",
                "--host",
                docker_host,
                "image",
                "tag",
                derived_builder_id,
                successor.final_builder_tag,
            ],
            timeout=30,
        )

        progress["status"] = "closed_dictionary_regression"
        _write_progress(root, progress)
        derived_runtime = runtime.model_copy(update={"local_builder_image_id": derived_builder_id})
        availability, inherited_probe = v184._probe_builder_commands(  # noqa: SLF001
            probe_proxy,
            runtime=derived_runtime,
            docker_host=docker_host,
            active_sensitive_values=active_sensitive_values,
        )
        _validate_command_delta(availability)
        command_probe = _reissue(
            inherited_probe,
            format_id="verigym_deepseek_harness_hwe_v188_command_dictionary_probe_v1",
            hash_field="probe_hash",
        )
        atomic_dump_json(root / "command-dictionary-probe.json", command_probe)

        progress["status"] = "offline_final_image_build"
        _write_progress(root, progress)
        category, final_build = _build_final_image(
            successor,
            predecessor=predecessor,
            runtime=runtime,
            builder=builder,
            scratch=scratch,
            docker_host=docker_host,
            availability=availability,
            active_sensitive_values=active_sensitive_values,
        )
        atomic_dump_json(root / "final-image-build.json", final_build)
        if category != "success":
            raise _ExpectedBuildFailure(category)
        final_image_id = v172._docker_image_id(  # noqa: SLF001
            successor.final_image_tag, host=docker_host
        )
        if final_image_id is None:
            raise ConfigurationError("v188 final image identity is absent")

        progress["status"] = "final_image_security_scan"
        _write_progress(root, progress)
        scan, image_lock = _scan_and_lock_open_image(
            successor,
            image_id=final_image_id,
            derived_builder_id=derived_builder_id,
            docker_host=docker_host,
            active_sensitive_values=active_sensitive_values,
        )
        atomic_dump_json(root / "final-image-security-scan.json", scan)
        atomic_dump_json(root / "final-image-lock.json", image_lock.model_dump(mode="json"))

        progress["status"] = "atomic_image_export"
        _write_progress(root, progress)
        export = _export_image(
            successor,
            image_id=final_image_id,
            scratch=scratch,
            docker_host=docker_host,
        )
        archive_exported = True
        atomic_dump_json(root / "final-image-archive.json", export)
    except _ExpectedBuildFailure as exc:
        category = exc.category
        stop_reason = type(exc).__name__
    except (Exception, KeyboardInterrupt) as exc:
        stop_reason = type(exc).__name__
        category = "controller_error"

    cleanup = _reissue(
        v182._cleanup(  # noqa: SLF001
            runtime,
            scratch=scratch,
            active_sensitive_values=active_sensitive_values,
        ),
        format_id="verigym_deepseek_harness_hwe_v188_cleanup_v1",
        hash_field="cleanup_hash",
    )
    atomic_dump_json(root / "cleanup.json", cleanup)
    success = (
        category == "success"
        and image_lock is not None
        and archive_exported
        and cleanup["cleanup_complete"] is True
    )
    if cleanup["cleanup_complete"] is not True:
        status_value = "stopped_cleanup_incomplete"
    elif success:
        status_value = "completed_git_builder_repair_pending_v189_audit"
    elif category == "sensitive_output":
        status_value = "stopped_sensitive_output"
    else:
        status_value = "stopped_without_repaired_image"
    terminal = {
        **progress,
        "status": status_value,
        "repair_category": category,
        "repair_succeeded": success,
        "derived_builder_image_id": derived_builder_id,
        "final_image_id": final_image_id,
        "image_lock_hash": image_lock.lock_hash if image_lock else None,
        "archive_exported": archive_exported,
        "cleanup_complete": cleanup["cleanup_complete"],
        "cleanup_category": cleanup["category"],
        "cleanup_hash": cleanup["cleanup_hash"],
        "stop_reason": stop_reason,
        "hwe_image_import_count": 0,
        "task_source_prepare_count": 0,
        "verifier_run_count": 0,
        "provider_calls": 0,
        "model_process_count": 0,
        "qualification_contract_published": False,
        "raw_exception_persisted": False,
        "raw_output_persisted": False,
        "command_argv_persisted": False,
        "environment_names_persisted": False,
        "environment_values_persisted": False,
        "requires_independent_v189_audit": True,
    }
    sealed = _seal(terminal)
    _write_progress(root, terminal)
    atomic_dump_json(root / "zero-provider-report.json", sealed)
    v182._normalize_result_modes(root)  # noqa: SLF001
    return sealed


class _ExpectedBuildFailure(Exception):
    """Internal control-flow marker for a safely classified nonzero build."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _preflight_inputs(
    successor: OpenToolchainV188GitBuilderRepairManifest,
) -> tuple[
    OpenToolchainV182BuildDiagnosticManifest,
    OpenToolchainV182BuildDiagnosticManifest,
    OpenToolchainV178LocalBuilderManifest,
    dict[str, Any],
    dict[str, Any],
    OpenToolchainV184MissingCommandManifest,
]:
    predecessor_path = _REPOSITORY / successor.predecessor_manifest_path
    if (
        predecessor_path != V186_MANIFEST
        or _hash_file(predecessor_path) != successor.predecessor_manifest_sha256
    ):
        raise ConfigurationError("v188 predecessor manifest file changed")
    predecessor_v186 = load_v186_diagnostic_context_manifest(predecessor_path)
    if predecessor_v186.manifest_hash != successor.predecessor_manifest_hash:
        raise ConfigurationError("v188 predecessor manifest identity changed")
    _validate_predecessor_evidence(successor)
    expected = {
        _REPOSITORY / successor.inherited_runner_path: successor.inherited_runner_sha256,
        _REPOSITORY / successor.inherited_contract_path: successor.inherited_contract_sha256,
        _REPOSITORY / successor.predecessor_audit_path: successor.predecessor_audit_sha256,
        _REPOSITORY / successor.exact_final_dockerfile: successor.exact_final_dockerfile_sha256,
        _REPOSITORY / successor.builder_repair_dockerfile: (
            successor.builder_repair_dockerfile_sha256
        ),
    }
    for path, digest in expected.items():
        if path.is_symlink() or not path.is_file() or _hash_file(path) != digest:
            raise ConfigurationError("v188 frozen input changed")
    _validate_dockerfiles(successor)
    package_receipt = _git_package_archive_receipt(successor)

    probe_proxy = predecessor_v186.model_copy(
        update={
            "final_image_tag": successor.final_image_tag,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )
    predecessor, runtime, builder, inherited_archive, command_probe_proxy = v186._preflight_inputs(
        probe_proxy
    )  # noqa: SLF001
    runtime = runtime.model_copy(
        update={
            "identity": IDENTITY,
            "builder_tag": successor.final_builder_tag,
            "final_dockerfile": successor.exact_final_dockerfile,
            "final_dockerfile_sha256": successor.exact_final_dockerfile_sha256,
            "final_image_tag": successor.final_image_tag,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )
    if (
        builder.local_builder_image_id != successor.base_builder_image_id
        or runtime.accepted_open_tools_image_id != successor.accepted_open_tools_image_id
        or runtime.build_timeout_seconds != successor.final_build_timeout_seconds
        or runtime.build_output_max_bytes != successor.final_build_output_max_bytes
    ):
        raise ConfigurationError("v188 inherited build identity changed")
    final_parent = Path(successor.final_image_archive_path).parent
    paths = (OUTPUT_ROOT, SCRATCH_ROOT, BACKING_PARENT, final_parent)
    if any(path.exists() or path.is_symlink() for path in paths):
        raise ConfigurationError("v188 resource path must be fresh")
    inventory_ok, owned = v182._owned_containers()  # noqa: SLF001
    if (
        v182._volume_exists(successor.dind_data_volume)  # noqa: SLF001
        or v182._volume_exists(successor.dind_socket_volume)  # noqa: SLF001
        or v172._docker_image_id(successor.final_image_tag, required=False) is not None  # noqa: SLF001
        or v172._docker_image_id(successor.derived_builder_tag, required=False) is not None  # noqa: SLF001
        or not inventory_ok
        or owned
    ):
        raise ConfigurationError("v188 campaign resource identity is not fresh")
    archive_receipt = _reissue(
        inherited_archive,
        format_id="verigym_deepseek_harness_hwe_v188_local_builder_archive_v1",
        hash_field="receipt_hash",
    )
    return (
        predecessor,
        runtime,
        builder,
        archive_receipt,
        package_receipt,
        command_probe_proxy,
    )


def _validate_predecessor_evidence(
    successor: OpenToolchainV188GitBuilderRepairManifest,
) -> None:
    root = Path(successor.predecessor_result_root)
    entries = (
        sorted(root.iterdir(), key=lambda item: item.name)
        if root == V186_RESULT_ROOT and root.is_dir() and not root.is_symlink()
        else []
    )
    root_stat = root.stat() if entries else None
    if (
        [entry.name for entry in entries] != sorted(successor.predecessor_result_file_sha256)
        or root_stat is None
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.getuid()
        or root_stat.st_gid != os.getgid()
        or hash_directory(root) != successor.predecessor_result_tree_hash
    ):
        raise ConfigurationError("v188 predecessor result tree changed")
    for entry in entries:
        metadata = entry.stat() if entry.is_file() and not entry.is_symlink() else None
        if (
            metadata is None
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
            or _hash_file(entry) != successor.predecessor_result_file_sha256[entry.name]
        ):
            raise ConfigurationError("v188 predecessor result file changed")
    try:
        report = json.loads((root / "zero-provider-report.json").read_bytes())
        progress = json.loads((root / "materialization-progress.json").read_bytes())
        diagnostic = json.loads((root / "diagnostic-context.json").read_bytes())
        cleanup = json.loads((root / "cleanup.json").read_bytes())
        probe = json.loads((root / "command-dictionary-probe.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v188 predecessor evidence is malformed") from exc
    required = {
        "identity": successor.predecessor_identity,
        "manifest_hash": successor.predecessor_manifest_hash,
        "source_commit": successor.predecessor_source_commit,
        "post_merge_main_run_id": successor.predecessor_post_merge_main_run_id,
        "status": "completed_diagnostic_context_refinement",
        "diagnostic_category": successor.predecessor_diagnostic_category,
        "diagnostic_context": successor.predecessor_diagnostic_context,
        "missing_command": successor.predecessor_missing_command,
        "cleanup_complete": True,
        "provider_calls": 0,
        "model_process_count": 0,
        "hwe_image_import_count": 0,
        "task_source_prepare_count": 0,
        "verifier_run_count": 0,
        "qualification_contract_published": False,
        **_closed_flags(),
    }
    if (
        report != progress
        or any(report.get(name) != value for name, value in required.items())
        or _embedded_hash(report, "report_hash") != successor.predecessor_report_hash
        or _embedded_hash(diagnostic, "diagnostic_hash") != successor.predecessor_diagnostic_hash
        or _embedded_hash(cleanup, "cleanup_hash") != successor.predecessor_cleanup_hash
        or _embedded_hash(probe, "probe_hash") != successor.predecessor_probe_hash
        or probe.get("command_availability", {}).get("git") is not False
        or diagnostic.get("raw_output_persisted") is not False
        or report.get("raw_exception_persisted") is not False
        or (root / "qualification-contract.json").exists()
    ):
        raise ConfigurationError("v188 predecessor terminal boundary changed")
    audit = _REPOSITORY / successor.predecessor_audit_path
    text = audit.read_text(encoding="utf-8")
    if (
        _hash_file(audit) != successor.predecessor_audit_sha256
        or "minimal builder-dependency" not in text
        or "repair whose only functional change" not in text
        or "V188 may not import an HWE image" not in text
    ):
        raise ConfigurationError("v188 audit authorization changed")


def _validate_dockerfiles(successor: OpenToolchainV188GitBuilderRepairManifest) -> None:
    repair = (_REPOSITORY / successor.builder_repair_dockerfile).read_text(encoding="utf-8")
    final = (_REPOSITORY / successor.exact_final_dockerfile).read_text(encoding="utf-8")
    if (
        f"FROM {_BASE_BUILDER_TAG}" not in repair
        or successor.git_package_archive_sha256 not in repair
        or successor.git_binary_sha256 not in repair
        or "dpkg --install /inputs/git/*.deb" not in repair
        or "RUN curl" in repair
        or "RUN wget" in repair
        or "apt-get" in repair
        or "git clone" in repair
        or f"FROM {successor.final_builder_tag} AS verilator-builder" not in final
        or "RUN curl" in final
        or "RUN wget" in final
        or "ghcr.io/pku-liang" in final
    ):
        raise ConfigurationError("v188 offline Dockerfile boundary changed")


def _git_package_archive_receipt(
    successor: OpenToolchainV188GitBuilderRepairManifest,
) -> dict[str, Any]:
    archive = Path(successor.git_package_archive_path)
    sidecar = Path(successor.git_package_archive_sidecar_path)
    archive_stat = archive.stat() if archive.is_file() and not archive.is_symlink() else None
    sidecar_stat = sidecar.stat() if sidecar.is_file() and not sidecar.is_symlink() else None
    if (
        archive_stat is None
        or sidecar_stat is None
        or archive.name.endswith(".partial")
        or archive_stat.st_size != successor.git_package_archive_bytes
        or stat.S_IMODE(archive_stat.st_mode) != 0o600
        or stat.S_IMODE(sidecar_stat.st_mode) != 0o600
        or archive_stat.st_uid != os.getuid()
        or archive_stat.st_gid != os.getgid()
        or sidecar_stat.st_uid != os.getuid()
        or sidecar_stat.st_gid != os.getgid()
        or _hash_file(archive) != successor.git_package_archive_sha256
        or _hash_file(sidecar) != successor.git_package_archive_sidecar_sha256
        or sidecar.read_bytes()
        != f"{successor.git_package_archive_sha256}  {archive.name}\n".encode("ascii")
    ):
        raise ConfigurationError("v188 git package archive identity changed")
    expected = {
        successor.git_package_manifest_name,
        *(item.file for item in successor.git_packages),
    }
    try:
        with tarfile.open(archive, mode="r:") as bundle:
            members = bundle.getmembers()
            names = [item.name for item in members]
            if (
                len(names) != len(set(names))
                or set(names) != expected
                or any(
                    not item.isfile()
                    or item.uid != 0
                    or item.gid != 0
                    or PurePosixPath(item.name).is_absolute()
                    or ".." in PurePosixPath(item.name).parts
                    for item in members
                )
            ):
                raise ConfigurationError("v188 git package archive inventory changed")
            for package in successor.git_packages:
                member = bundle.getmember(package.file)
                handle = bundle.extractfile(member)
                if handle is None:
                    raise ConfigurationError("v188 git package member is absent")
                value = handle.read(package.bytes + 1)
                if (
                    len(value) != package.bytes
                    or hashlib.sha256(value).hexdigest() != package.sha256
                ):
                    raise ConfigurationError("v188 git package member changed")
            metadata_member = bundle.getmember(successor.git_package_manifest_name)
            metadata_handle = bundle.extractfile(metadata_member)
            if metadata_handle is None:
                raise ConfigurationError("v188 git package manifest is absent")
            metadata_bytes = metadata_handle.read(1024 * 1024 + 1)
            metadata = json.loads(metadata_bytes)
    except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError) as exc:
        raise ConfigurationError("v188 git package archive is malformed") from exc
    metadata_base = dict(metadata)
    metadata_hash = metadata_base.pop("manifest_hash", None)
    packages = [item.model_dump(mode="json") for item in successor.git_packages]
    if (
        len(metadata_bytes) > 1024 * 1024
        or hashlib.sha256(metadata_bytes).hexdigest() != successor.git_package_manifest_sha256
        or metadata_hash != successor.git_package_manifest_hash
        or content_hash(metadata_base) != metadata_hash
        or metadata.get("identity") != IDENTITY
        or metadata.get("base_builder_image_id") != successor.base_builder_image_id
        or metadata.get("packages") != packages
        or metadata.get("git_binary_sha256") != successor.git_binary_sha256
        or metadata.get("git_package_payload_file_count")
        != successor.git_package_payload_file_count
        or metadata.get("git_package_payload_inventory_sha256")
        != successor.git_package_payload_inventory_sha256
        or metadata.get("container_credentials_available") is not False
        or metadata.get("registry_accessed") is not False
        or metadata.get("hwe_image_used") is not False
        or metadata.get("partial_input_present") is not False
    ):
        raise ConfigurationError("v188 git package manifest changed")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v188_git_package_archive_v1",
        "identity": IDENTITY,
        "archive_sha256": successor.git_package_archive_sha256,
        "archive_bytes": successor.git_package_archive_bytes,
        "sidecar_sha256": successor.git_package_archive_sidecar_sha256,
        "package_manifest_sha256": successor.git_package_manifest_sha256,
        "package_manifest_hash": successor.git_package_manifest_hash,
        "package_count": len(successor.git_packages),
        "download_command_count": successor.package_acquisition_download_command_count,
        "acquisition_complete": True,
        "registry_accessed": False,
        "hwe_image_used": False,
        "partial_input_present": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _builder_build_command(
    successor: OpenToolchainV188GitBuilderRepairManifest,
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
        successor.derived_builder_tag,
        "--file",
        str(_REPOSITORY / successor.builder_repair_dockerfile),
        str(context),
    ]


def _build_git_builder(
    successor: OpenToolchainV188GitBuilderRepairManifest,
    *,
    builder: OpenToolchainV178LocalBuilderManifest,
    scratch: Path,
    docker_host: str,
    active_sensitive_values: tuple[bytes, ...],
) -> tuple[str | None, dict[str, Any]]:
    context = scratch / "git-builder-context"
    context.mkdir(mode=0o700)
    shutil.copy2(successor.git_package_archive_path, context / "git-package-closure.tar")
    result = v176._run_bounded_process(  # noqa: SLF001
        _builder_build_command(successor, context=context, docker_host=docker_host),
        timeout=successor.builder_build_timeout_seconds,
        maximum=successor.builder_build_output_max_bytes,
    )
    sensitive = v182._contains_sensitive_output(  # noqa: SLF001
        result.stdout,
        result.stderr,
        active_sensitive_values=active_sensitive_values,
    )
    if sensitive:
        category = "sensitive_output"
    elif not result.output_within_bound:
        category = "output_overflow"
    elif result.timed_out:
        category = "timeout"
    elif result.returncode == 0:
        category = "success"
    elif b"no space left on device" in (result.stdout + result.stderr).lower():
        category = "storage_exhausted"
    else:
        category = "builder_repair_failed"
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v188_git_builder_repair_v1",
        "identity": IDENTITY,
        "category": category,
        "base_builder_image_id": builder.local_builder_image_id,
        "network": "none",
        "pull": False,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "output_within_bound": result.output_within_bound,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "stdout_sha256": _EMPTY_SHA256 if sensitive else hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": _EMPTY_SHA256 if sensitive else hashlib.sha256(result.stderr).hexdigest(),
        "sensitive_output_detected": sensitive,
        "raw_output_persisted": False,
    }
    receipt = {**base, "repair_hash": content_hash(base)}
    if category != "success":
        return None, receipt
    image_id = v172._docker_image_id(successor.derived_builder_tag, host=docker_host)  # noqa: SLF001
    if image_id is None or image_id in {
        successor.base_builder_image_id,
        successor.accepted_open_tools_image_id,
        successor.official_verifier_image,
    }:
        raise ConfigurationError("v188 derived builder identity is invalid")
    return image_id, receipt


def _bind_repaired_builder(
    successor: OpenToolchainV188GitBuilderRepairManifest,
    *,
    builder: OpenToolchainV178LocalBuilderManifest,
    image_id: str,
    docker_host: str,
    active_sensitive_values: tuple[bytes, ...],
) -> dict[str, Any]:
    image = v172._inspect_image(image_id, host=docker_host)  # noqa: SLF001
    parent = v172._inspect_image(builder.local_builder_image_id, host=docker_host)  # noqa: SLF001
    config = image.get("Config") or {}
    labels = config.get("Labels") or {}
    checks = {
        "image_id": image.get("Id") == image_id,
        "linux_amd64": (image.get("Os"), image.get("Architecture")) == ("linux", "amd64"),
        "base_builder_ancestor": v172._is_ancestor_layers(parent, image),  # noqa: SLF001
        "root_user_unchanged": config.get("User") == "",
        "inert_command": config.get("Cmd") == ["bash"],
        "role_label": labels.get("org.verigym.role") == "dependency-only-git-builder",
        "version_label": labels.get("org.verigym.git-package-version")
        == successor.git_debian_version,
        "hwe_ancestor_false": labels.get("org.verigym.hwe-task-image-ancestor") == "false",
        "credential_label_false": labels.get("org.verigym.provider-credentials-included")
        == "false",
        "official_image_absent": v172._inspect_image(  # noqa: SLF001
            successor.official_verifier_image, host=docker_host, required=False
        )
        is None,
    }
    package_commands = [
        f"test \"$(dpkg-query -W -f='${{Version}}' {item.package})\" = '{item.version}'"
        for item in successor.git_packages
    ]
    script = "; ".join(
        [
            "set -eu",
            f"sha256sum {successor.git_binary_path}",
            "git --version",
            *package_commands,
            "! command -v iverilog",
            "! command -v yosys",
            "! command -v verilator",
            "! command -v codex",
            "test ! -e /hwe",
        ]
    )
    probe = _run_builder_probe(
        docker_host=docker_host,
        image_id=image_id,
        command=["/bin/sh", "-c", script],
        timeout=successor.probe_timeout_seconds,
        output_limit=successor.probe_output_max_bytes,
    )
    output = probe.pop("output")
    if v182._contains_sensitive_output(  # noqa: SLF001
        output,
        b"",
        active_sensitive_values=active_sensitive_values,
    ):
        raise ConfigurationError("v188 repaired builder probe contained sensitive output")
    text = output.decode("utf-8", errors="strict")
    checks.update(
        {
            "probe_success": probe["returncode"] == 0,
            "git_binary_hash": (
                f"{successor.git_binary_sha256}  {successor.git_binary_path}" in text
            ),
            "git_version": f"git version {successor.git_version}" in text,
            "network_none": probe["network"] == "none",
            "read_only_root": probe["read_only_root"] is True,
            "cap_drop_all": probe["cap_drop_all"] is True,
            "no_new_privileges": probe["no_new_privileges"] is True,
            "mount_count_zero": probe["mount_count"] == 0,
            "probe_cleanup": probe["container_removed"] is True,
        }
    )
    if not all(checks.values()):
        raise ConfigurationError("v188 repaired builder binding failed")
    history = v182._run_control(  # noqa: SLF001
        [
            "docker",
            "--host",
            docker_host,
            "history",
            "--no-trunc",
            "--format",
            "{{json .CreatedBy}}",
            image_id,
        ],
        timeout=60,
    ).stdout
    if any(marker in history.lower() for marker in (b"http://", b"https://", b"proxy=", b"token=")):
        raise ConfigurationError("v188 repaired builder history crossed the offline boundary")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v188_git_builder_binding_v1",
        "identity": IDENTITY,
        "image_id": image_id,
        "base_builder_image_id": builder.local_builder_image_id,
        "checks": checks,
        "history_sha256": hashlib.sha256(history).hexdigest(),
        "history_bytes": len(history),
        "probe_output_sha256": hashlib.sha256(output).hexdigest(),
        "probe_output_bytes": len(output),
        "raw_history_persisted": False,
        "raw_probe_output_persisted": False,
        "registry_accessed": False,
        "download_performed": False,
        "binding_passed": True,
    }
    return {**base, "binding_hash": content_hash(base)}


def _run_builder_probe(
    *,
    docker_host: str,
    image_id: str,
    command: list[str],
    timeout: int,
    output_limit: int,
) -> dict[str, Any]:
    name = f"verigym-v188-git-builder-probe-{secrets.token_hex(6)}"
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
        "verigym.role=git-builder-binding",
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
        "128",
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
        image_id,
        *command,
    ]
    container_id = v182._run_control(create, timeout=60).stdout.decode().strip()  # noqa: SLF001
    try:
        inspection = v172._inspect_container(container_id, host=docker_host)  # noqa: SLF001
        host = inspection.get("HostConfig") or {}
        config = inspection.get("Config") or {}
        if (
            config.get("Image") != image_id
            or config.get("User") != f"{os.getuid()}:{os.getgid()}"
            or config.get("WorkingDir") != "/"
            or config.get("Labels", {}).get("verigym.owner") != OWNER
            or config.get("Labels", {}).get("verigym.role") != "git-builder-binding"
            or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("CapAdd") not in (None, [])
            or set(host.get("CapDrop") or []) != {"ALL"}
            or not any(
                str(item).startswith("no-new-privileges") for item in host.get("SecurityOpt") or []
            )
            or inspection.get("Mounts") not in (None, [])
        ):
            raise ConfigurationError("v188 repaired builder probe isolation changed")
        result = v176._run_bounded_process(  # noqa: SLF001
            ["docker", "--host", docker_host, "container", "start", "--attach", container_id],
            timeout=timeout,
            maximum=output_limit,
        )
        output = result.stdout + result.stderr
        if result.timed_out or not result.output_within_bound or len(output) > output_limit:
            raise ConfigurationError("v188 repaired builder probe exceeded its bound")
        return {
            "returncode": result.returncode,
            "output": output,
            "network": "none",
            "read_only_root": True,
            "cap_drop_all": True,
            "no_new_privileges": True,
            "effective_user": f"{os.getuid()}:{os.getgid()}",
            "mount_count": 0,
            "container_removed": True,
        }
    finally:
        removed = v182._run_control(  # noqa: SLF001
            ["docker", "--host", docker_host, "container", "rm", "--force", container_id],
            timeout=60,
            check=False,
        )
        if removed.returncode != 0:
            raise ConfigurationError("v188 repaired builder probe cleanup failed")


def _validate_command_delta(availability: dict[str, bool]) -> None:
    predecessor_path = V186_RESULT_ROOT / "command-dictionary-probe.json"
    before = json.loads(predecessor_path.read_bytes()).get("command_availability")
    expected = dict(before) if isinstance(before, dict) else {}
    expected["git"] = True
    if availability != expected:
        raise ConfigurationError("v188 repaired builder changed more than the git command")


def _build_final_image(
    successor: OpenToolchainV188GitBuilderRepairManifest,
    *,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
    runtime: OpenToolchainV182BuildDiagnosticManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    scratch: Path,
    docker_host: str,
    availability: dict[str, bool],
    active_sensitive_values: tuple[bytes, ...],
) -> tuple[str, dict[str, Any]]:
    context = scratch / "final-build-context"
    context.mkdir(mode=0o700)
    shutil.copy2(runtime.verilator_archive_path, context / "verilator-v5.008.tar.gz")
    shutil.copy2(
        runtime.ripgrep_archive_path,
        context / "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz",
    )
    result = v176._run_bounded_process(  # noqa: SLF001
        v182._build_command(runtime, context=context, docker_host=docker_host),  # noqa: SLF001
        timeout=successor.final_build_timeout_seconds,
        maximum=successor.final_build_output_max_bytes,
    )
    sensitive = v182._contains_sensitive_output(  # noqa: SLF001
        result.stdout,
        result.stderr,
        active_sensitive_values=active_sensitive_values,
    )
    resolution = v186._classify_build_result(  # noqa: SLF001
        result,
        sensitive=sensitive,
        successor=probe_proxy_from(successor),
        availability=availability,
    )
    category = resolution["category"]
    if category == "success":
        image_id = v172._docker_image_id(  # noqa: SLF001
            runtime.final_image_tag, host=docker_host
        )
        if image_id in {
            runtime.accepted_open_tools_image_id,
            runtime.dind_image_id,
            builder.local_builder_image_id,
        }:
            category = "controller_error"
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v188_final_image_build_v1",
        "identity": IDENTITY,
        "predecessor_manifest_hash": predecessor.manifest_hash,
        "category": category,
        "network": "none",
        "pull": False,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "output_within_bound": result.output_within_bound,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "stdout_sha256": _EMPTY_SHA256 if sensitive else hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": _EMPTY_SHA256 if sensitive else hashlib.sha256(result.stderr).hexdigest(),
        "sensitive_output_detected": sensitive,
        "diagnostic_context": resolution["diagnostic_context"],
        "missing_command": resolution["missing_command"],
        "marker_count": resolution["marker_count"],
        "raw_output_persisted": False,
    }
    return category, {**base, "build_hash": content_hash(base)}


def probe_proxy_from(
    successor: OpenToolchainV188GitBuilderRepairManifest,
) -> OpenToolchainV186DiagnosticContextManifest:
    predecessor = load_v186_diagnostic_context_manifest(V186_MANIFEST)
    return predecessor.model_copy(
        update={
            "final_image_tag": successor.final_image_tag,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )


def _scan_and_lock_open_image(
    successor: OpenToolchainV188GitBuilderRepairManifest,
    *,
    image_id: str,
    derived_builder_id: str,
    docker_host: str,
    active_sensitive_values: tuple[bytes, ...],
    identity: str = IDENTITY,
    lock_type: type[OpenToolchainV188ImageLock] = OpenToolchainV188ImageLock,
) -> tuple[dict[str, Any], OpenToolchainV188ImageLock]:
    image = v172._inspect_image(image_id, host=docker_host)  # noqa: SLF001
    derived = v172._inspect_image(derived_builder_id, host=docker_host)  # noqa: SLF001
    config = image.get("Config") or {}
    labels = config.get("Labels") or {}
    environment = config.get("Env") or []
    env_names = {item.partition("=")[0] for item in environment if isinstance(item, str)}
    expected_user = f"{os.getuid()}:{os.getgid()}"
    official_loaded = (
        v172._inspect_image(  # noqa: SLF001
            successor.official_verifier_image, host=docker_host, required=False
        )
        is not None
    )
    checks = {
        "image_id": image.get("Id") == image_id,
        "linux_amd64": (image.get("Os"), image.get("Architecture")) == ("linux", "amd64"),
        "derived_builder_ancestor": v172._is_ancestor_layers(derived, image),  # noqa: SLF001
        "non_root_user": config.get("User") == expected_user,
        "working_directory": config.get("WorkingDir") == "/workspace/repository",
        "inert_command": config.get("Cmd") == ["tail", "-f", "/dev/null"],
        "entrypoint_absent": config.get("Entrypoint") in (None, []),
        "ports_absent": config.get("ExposedPorts") in (None, {}),
        "volumes_absent": config.get("Volumes") in (None, {}),
        "agent_toolchain_label": labels.get("org.verigym.agent-toolchain-id")
        == successor.agent_toolchain_id,
        "non_authoritative_label": labels.get("org.verigym.role") == "agent-only-non-authoritative",
        "official_verifier_label": labels.get("org.verigym.official-verifier-included") == "false",
        "provider_environment_absent": not env_names.intersection(
            ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
        ),
        "proxy_environment_absent": not env_names.intersection(
            {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}
        ),
        "official_image_not_loaded": not official_loaded,
        "official_image_not_equal": image_id != successor.official_verifier_image,
    }
    script = "set -eu; " + "; ".join(
        [f"sha256sum {_BINARY_PATHS[name]}" for name in _BINARY_PATHS]
        + [
            "verigym-open-toolchain-identity",
            "verilator --version",
            "iverilog -V 2>&1 | head -n 1",
            "vvp -V 2>&1 | head -n 1",
            "yosys -V",
            "rg --version | head -n 1",
            "make --version | head -n 1",
            "g++ --version | head -n 1",
            "git --version",
            "! command -v codex",
            "test ! -e /root/.codex",
            "test ! -e /home/verigym/.codex",
            "test ! -e /hwe",
        ]
    )
    probe = v172._run_secure_container(  # noqa: SLF001
        docker_host=docker_host,
        image_id=image_id,
        role=f"{identity}-security-scan",
        command=["/bin/bash", "-c", script],
        mounts=[],
        timeout=successor.probe_timeout_seconds,
        output_limit=successor.probe_output_max_bytes,
    )
    output = probe.pop("output")
    if v182._contains_sensitive_output(  # noqa: SLF001
        output,
        b"",
        active_sensitive_values=active_sensitive_values,
    ):
        raise ConfigurationError("v188 final image probe contained sensitive output")
    text = output.decode("utf-8", errors="strict")
    binary_hashes: dict[str, str] = {}
    for line in text.splitlines():
        digest, separator, path = line.partition("  ")
        for name, expected_path in _BINARY_PATHS.items():
            if separator and path == expected_path and _HASH.fullmatch(digest):
                binary_hashes[name] = digest
    checks.update(
        {
            "binary_inventory_complete": set(binary_hashes) == set(_BINARY_PATHS),
            "git_binary_hash": binary_hashes.get("git") == successor.git_binary_sha256,
            "identity_command": "agent_toolchain_id=verigym-open-rtl-tools-v1" in text,
            "verilator_version": "Verilator 5.008" in text,
            "iverilog_version": "Icarus Verilog version 12.0" in text,
            "vvp_version": "Icarus Verilog runtime version 12.0" in text,
            "yosys_version": "Yosys 0.67" in text,
            "ripgrep_version": "ripgrep 15.2.0" in text,
            "make_present": "GNU Make" in text,
            "compiler_present": "g++" in text,
            "git_version": f"git version {successor.git_version}" in text,
            "probe_success": probe["returncode"] == 0,
            "runtime_read_only": probe["read_only_root"] is True,
            "runtime_cap_drop_all": probe["cap_drop_all"] is True,
            "runtime_no_new_privileges": probe["no_new_privileges"] is True,
            "runtime_no_mounts": probe["mount_count"] == 0,
            "runtime_cleanup": probe["container_removed"] is True,
        }
    )
    passed = all(checks.values())
    scan_base = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_security_scan_v2",
        "identity": identity,
        "scanner_profile_id": successor.scanner_profile_id,
        "image_id": image_id,
        "check_count": len(checks),
        "checks": checks,
        "scan_passed": passed,
        "probe_output_sha256": hashlib.sha256(output).hexdigest(),
        "probe_output_bytes": len(output),
        "raw_probe_output_persisted": False,
    }
    scan = {**scan_base, "scan_hash": content_hash(scan_base)}
    if not passed:
        raise ConfigurationError("v188 open-tool image security scan failed")
    versions = {
        "verilator": "5.008",
        "iverilog": "12.0",
        "vvp": "12.0",
        "yosys": "0.67",
        "rg": "15.2.0",
        "make": "present",
        "g++": "present",
        "git": successor.git_version,
        "verilator_bin": "5.008",
    }
    lock_base = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v2",
        "identity": identity,
        "scanner_profile_id": successor.scanner_profile_id,
        "agent_toolchain_id": successor.agent_toolchain_id,
        "image_id": image_id,
        "accepted_open_tools_image_id": successor.accepted_open_tools_image_id,
        "base_builder_image_id": successor.base_builder_image_id,
        "derived_builder_image_id": derived_builder_id,
        "official_verifier_image": successor.official_verifier_image,
        "binary_sha256": binary_hashes,
        "binary_versions": versions,
        "build_network": "none",
        "runtime_network": "none",
        "effective_user": expected_user,
        "read_only_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "mount_count": 0,
        "provider_credentials_present": False,
        "codex_present": False,
        "hwe_image_loaded": False,
        "official_verifier_included": False,
        "security_scan_passed": True,
    }
    lock = lock_type.model_validate({**lock_base, "lock_hash": content_hash(lock_base)})
    return scan, lock


def _export_image(
    successor: OpenToolchainV188GitBuilderRepairManifest,
    *,
    image_id: str,
    scratch: Path,
    docker_host: str,
) -> dict[str, Any]:
    persistent = Path(successor.final_image_archive_path)
    parent = persistent.parent
    parent_parent = parent.parent
    temporary = parent_parent / f".{parent.name}.partial-{secrets.token_hex(8)}"
    if parent.exists() or parent.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise ConfigurationError("v188 final image archive identity is not fresh")
    temporary.mkdir(mode=0o700)
    archive = temporary / persistent.name
    sidecar = temporary / Path(successor.final_image_archive_sidecar_path).name
    try:
        v182._run_control(  # noqa: SLF001
            [
                "docker",
                "--host",
                docker_host,
                "image",
                "save",
                "--output",
                str(archive),
                successor.final_image_tag,
            ],
            timeout=1800,
        )
        size = archive.stat().st_size if archive.is_file() and not archive.is_symlink() else 0
        if not 0 < size <= successor.final_image_archive_max_bytes:
            raise ConfigurationError("v188 final image archive size is unsafe")
        digest = _hash_file(archive)
        _validate_saved_image_archive(archive, image_id=image_id, tag=successor.final_image_tag)
        sidecar.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
        archive.chmod(0o600)
        sidecar.chmod(0o600)
        temporary.chmod(0o700)
        os.replace(temporary, parent)
    except BaseException:
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v188_final_image_archive_v1",
        "identity": IDENTITY,
        "image_id": image_id,
        "archive_path": successor.final_image_archive_path,
        "archive_sha256": digest,
        "archive_bytes": size,
        "sidecar_path": successor.final_image_archive_sidecar_path,
        "sidecar_sha256": _hash_file(Path(successor.final_image_archive_sidecar_path)),
        "atomic_directory_publish": True,
        "partial_archive_present": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _validate_saved_image_archive(archive: Path, *, image_id: str, tag: str) -> None:
    expected_config = f"{image_id.removeprefix('sha256:')}.json"
    try:
        with tarfile.open(archive, mode="r:") as bundle:
            members = bundle.getmembers()
            names = [item.name for item in members]
            if (
                len(names) != len(set(names))
                or any(
                    PurePosixPath(name).is_absolute()
                    or ".." in PurePosixPath(name).parts
                    or item.issym()
                    or item.islnk()
                    or item.isdev()
                    for name, item in zip(names, members, strict=True)
                )
                or expected_config not in names
                or "manifest.json" not in names
            ):
                raise ConfigurationError("v188 final image archive inventory is unsafe")
            handle = bundle.extractfile("manifest.json")
            if handle is None:
                raise ConfigurationError("v188 final image archive manifest is absent")
            manifest = json.loads(handle.read(65537))
    except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError) as exc:
        raise ConfigurationError("v188 final image archive is malformed") from exc
    if (
        not isinstance(manifest, list)
        or len(manifest) != 1
        or manifest[0].get("Config") != expected_config
        or manifest[0].get("RepoTags") != [tag]
    ):
        raise ConfigurationError("v188 final image archive binding changed")


def _headroom_receipt(
    successor: OpenToolchainV188GitBuilderRepairManifest,
) -> dict[str, Any]:
    control_root = shutil.disk_usage("/")
    data2 = shutil.disk_usage("/data2")
    control_root_stat = os.statvfs("/")
    data2_stat = os.statvfs("/data2")
    passed = (
        control_root.free >= successor.control_root_min_available_bytes
        and data2.free >= successor.data2_min_available_bytes
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v188_headroom_v1",
        "identity": IDENTITY,
        "control_root_available_bytes": control_root.free,
        "control_root_min_available_bytes": successor.control_root_min_available_bytes,
        "data2_available_bytes": data2.free,
        "data2_min_available_bytes": successor.data2_min_available_bytes,
        "control_root_available_inodes": control_root_stat.f_bavail,
        "data2_available_inodes": data2_stat.f_bavail,
        "all_bulk_storage_on_data2": True,
        "capacity_satisfied": passed,
    }
    if not passed:
        raise ConfigurationError("v188 absolute headroom gate failed")
    return {**base, "receipt_hash": content_hash(base)}


def _require_execution_boundary(
    arguments: argparse.Namespace,
    successor: OpenToolchainV188GitBuilderRepairManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v188 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v188 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v188 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v188 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= successor.predecessor_audit_post_merge_main_run_id:
        raise ConfigurationError("v188 requires a new post-merge main run identity")


@contextmanager
def _patched_inherited_runtime() -> Iterator[None]:
    bindings = {
        "IDENTITY": IDENTITY,
        "OPT_IN_ENV": OPT_IN_ENV,
        "SANITIZED_CHILD_ENV": SANITIZED_CHILD_ENV,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "SCRATCH_ROOT": SCRATCH_ROOT,
        "BACKING_PARENT": BACKING_PARENT,
        "DATA_BACKING": DATA_BACKING,
        "SOCKET_BACKING": SOCKET_BACKING,
        "OWNER": OWNER,
        "_REQUIRED_MERGED_PATHS": _REQUIRED_MERGED_PATHS,
    }
    previous = {name: getattr(v186, name) for name in bindings}
    previous_leaf_bindings = (v172.OWNER, v172.IDENTITY, v178.OWNER, v178.IDENTITY)
    for name, value in bindings.items():
        setattr(v186, name, value)
    v172.OWNER = OWNER
    v172.IDENTITY = IDENTITY
    v178.OWNER = OWNER
    v178.IDENTITY = IDENTITY
    try:
        with v186._patched_inherited_runtime():  # noqa: SLF001
            yield
    finally:
        v172.OWNER, v172.IDENTITY, v178.OWNER, v178.IDENTITY = previous_leaf_bindings
        for name, value in previous.items():
            setattr(v186, name, value)


def _closed_flags() -> dict[str, bool]:
    return {
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }


def _embedded_hash(value: dict[str, Any], field: str) -> str | None:
    base = dict(value)
    observed = base.pop(field, None)
    return observed if isinstance(observed, str) and content_hash(base) == observed else None


def _reissue(value: dict[str, Any], *, format_id: str, hash_field: str) -> dict[str, Any]:
    base = dict(value)
    base.pop(hash_field, None)
    base["format_id"] = format_id
    base["identity"] = IDENTITY
    return {**base, hash_field: content_hash(base)}


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    base = dict(value)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_progress(root: Path, value: dict[str, Any]) -> None:
    atomic_dump_json(root / "materialization-progress.json", _seal(value))
    (root / "materialization-progress.json").chmod(0o600)


def _hash_file(path: Path) -> str:
    return v172._hash_file(path)  # noqa: SLF001


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_file():
        raise ConfigurationError(f"v188 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v188 {label} identity changed")
    return resolved


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "repair_category": report["repair_category"],
                "repair_succeeded": report["repair_succeeded"],
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
