#!/usr/bin/env python3
"""Run the one-use task-free v184 missing-command disambiguation."""

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
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v182_bounded_open_build as v182,
)
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_directory  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
)
from verigym.hwe.open_toolchain_build_diagnostic import (  # noqa: E402
    OpenToolchainV182BuildDiagnosticManifest,
    load_v182_build_diagnostic_manifest,
)
from verigym.hwe.open_toolchain_local_builder import (  # noqa: E402
    OpenToolchainV178LocalBuilderManifest,
)
from verigym.hwe.open_toolchain_missing_command import (  # noqa: E402
    V184_IDENTITY,
    OpenToolchainV184MissingCommandManifest,
    load_v184_missing_command_manifest,
)

IDENTITY = V184_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V184_MISSING_COMMAND"
SANITIZED_CHILD_ENV = "VERIGYM_V184_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v184_missing_command_disambiguation_v1.json"
)
V182_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json"
)
V182_RESULT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v184-missing-command-disambiguation-v1"
)
SCRATCH_ROOT = Path(
    "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v184-missing-command-disambiguation"
)
BACKING_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v184")
DATA_BACKING = BACKING_PARENT / "data"
SOCKET_BACKING = BACKING_PARENT / "socket"
OWNER = "deepseek-harness-hwe-v184-missing-command"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_ALLOWED_UNTRACKED_PATHS = v178._ALLOWED_UNTRACKED_PATHS  # noqa: SLF001
_MISSING_COMMAND = re.compile(
    rb"(?<![A-Za-z0-9_+./-])"
    rb"(?P<command>[A-Za-z0-9_+./-]+): (?:command )?not found(?=\r?$)",
    re.MULTILINE,
)
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v184_missing_command_disambiguation_v1.json",
    "docs/audits/2026-09-06_deepseek-harness-v183-v182-result.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v184_missing_command.py",
    "scripts/launch_hwe_deepseek_harness_v184_missing_command.py",
    "scripts/materialize_hwe_deepseek_harness_v176_open_toolchain_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v178_local_builder.py",
    "scripts/materialize_hwe_deepseek_harness_v182_bounded_open_build.py",
    "scripts/materialize_hwe_deepseek_harness_v184_missing_command.py",
    "src/verigym/hwe/open_toolchain_build_diagnostic.py",
    "src/verigym/hwe/open_toolchain_missing_command.py",
    "tests/unit/test_hwe_open_toolchain_missing_command.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the sole authorized disambiguation and always seal a terminal report."""

    successor = load_v184_missing_command_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    _require_execution_boundary(arguments, successor)
    with _patched_v182_runtime():
        source_commit = v182._require_clean_merged_main()  # noqa: SLF001
        active_sensitive_values = v182._active_sensitive_values()  # noqa: SLF001
        with v182._sanitized_process_environment():  # noqa: SLF001
            predecessor, runtime, builder, archive_receipt = _preflight_inputs(successor)
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
            )


def _execute(
    arguments: argparse.Namespace,
    *,
    successor: OpenToolchainV184MissingCommandManifest,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
    runtime: OpenToolchainV182BuildDiagnosticManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    root: Path,
    scratch: Path,
    source_commit: str,
    active_sensitive_values: tuple[bytes, ...],
    archive_receipt: dict[str, Any],
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v184_progress_v1",
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
        "repair_authorized": False,
        **_closed_flags(),
    }
    _write_progress(root, progress)
    diagnostic: dict[str, Any] | None = None
    stop_reason: str | None = None
    try:
        headroom = _headroom_receipt(successor)
        atomic_dump_json(root / "headroom.json", headroom)
        atomic_dump_json(root / "local-builder-archive.json", archive_receipt)
        progress["status"] = "local_transfer_prepare"
        _write_progress(root, progress)
        transfers = v182._save_transfer_inputs(  # noqa: SLF001
            runtime, builder=builder, scratch=scratch
        )
        v182._prepare_dind_backings(runtime)  # noqa: SLF001
        v182._create_bind_volume(runtime.dind_data_volume, DATA_BACKING)  # noqa: SLF001
        v182._create_bind_volume(runtime.dind_socket_volume, SOCKET_BACKING)  # noqa: SLF001
        dind_name = f"verigym-dind-v184-{secrets.token_hex(8)}"
        dind_receipt = _reissue(
            v182._start_dind(dind_name, runtime, root=root, scratch=scratch),  # noqa: SLF001
            format_id="verigym_deepseek_harness_hwe_v184_dind_runtime_v1",
            hash_field="receipt_hash",
        )
        atomic_dump_json(root / "dind-runtime.json", dind_receipt)
        docker_host = f"unix://{SOCKET_BACKING / 'docker.sock'}"

        progress["status"] = "local_builder_binding"
        _write_progress(root, progress)
        v182._load_transfer_inputs(  # noqa: SLF001
            runtime, builder=builder, transfers=transfers, docker_host=docker_host
        )
        builder_receipt = _reissue(
            v182._bind_and_probe_builder(  # noqa: SLF001
                builder, runtime, docker_host=docker_host
            ),
            format_id="verigym_deepseek_harness_hwe_v184_local_builder_binding_v1",
            hash_field="binding_hash",
        )
        atomic_dump_json(root / "local-builder-binding.json", builder_receipt)

        progress["status"] = "builder_command_probe"
        _write_progress(root, progress)
        availability, probe_receipt = _probe_builder_commands(
            successor,
            runtime=runtime,
            docker_host=docker_host,
            active_sensitive_values=active_sensitive_values,
        )
        atomic_dump_json(root / "builder-command-probe.json", probe_receipt)

        progress["status"] = "bounded_missing_command_disambiguation"
        _write_progress(root, progress)
        diagnostic = _run_build_diagnostic(
            successor,
            predecessor=predecessor,
            runtime=runtime,
            builder=builder,
            scratch=scratch,
            docker_host=docker_host,
            availability=availability,
            active_sensitive_values=active_sensitive_values,
        )
        atomic_dump_json(root / "missing-command-diagnostic.json", diagnostic)
        progress["status"] = "missing_command_disambiguated"
        _write_progress(root, progress)
    except Exception as exc:
        stop_reason = type(exc).__name__
        if diagnostic is None:
            diagnostic = _diagnostic_receipt(
                successor,
                predecessor=predecessor,
                result=None,
                category="controller_error",
                sensitive=False,
                missing_command=None,
                marker_count=0,
                distinct_allowlisted_count=0,
                unknown_marker_present=False,
                command_available_before_build=None,
            )
            atomic_dump_json(root / "missing-command-diagnostic.json", diagnostic)

    cleanup = _reissue(
        v182._cleanup(  # noqa: SLF001
            runtime,
            scratch=scratch,
            active_sensitive_values=active_sensitive_values,
        ),
        format_id="verigym_deepseek_harness_hwe_v184_cleanup_v1",
        hash_field="cleanup_hash",
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
        status_value = "completed_missing_command_disambiguation"
    terminal = {
        **progress,
        "status": status_value,
        "diagnostic_category": category,
        "diagnostic_hash": diagnostic["diagnostic_hash"],
        "missing_command": diagnostic["missing_command"],
        "build_succeeded": category == "success",
        "diagnostic_complete": category != "controller_error",
        "cleanup_complete": cleanup["cleanup_complete"],
        "cleanup_category": cleanup["category"],
        "cleanup_hash": cleanup["cleanup_hash"],
        "stop_reason": stop_reason,
        "raw_exception_persisted": False,
        "raw_output_persisted": False,
        "raw_matching_line_persisted": False,
        "arbitrary_token_persisted": False,
        "path_persisted": False,
        "command_argv_persisted": False,
        "environment_names_persisted": False,
        "environment_values_persisted": False,
        "requires_independent_v185_audit": True,
    }
    sealed = _seal(terminal)
    _write_progress(root, terminal)
    atomic_dump_json(root / "zero-provider-report.json", sealed)
    v182._normalize_result_modes(root)  # noqa: SLF001
    return sealed


def _preflight_inputs(
    successor: OpenToolchainV184MissingCommandManifest,
) -> tuple[
    OpenToolchainV182BuildDiagnosticManifest,
    OpenToolchainV182BuildDiagnosticManifest,
    OpenToolchainV178LocalBuilderManifest,
    dict[str, Any],
]:
    predecessor_path = _REPOSITORY / successor.predecessor_manifest_path
    if (
        predecessor_path != V182_MANIFEST
        or _hash_file(predecessor_path) != successor.predecessor_manifest_sha256
    ):
        raise ConfigurationError("v184 predecessor manifest file changed")
    predecessor = load_v182_build_diagnostic_manifest(predecessor_path)
    if predecessor.manifest_hash != successor.predecessor_manifest_hash:
        raise ConfigurationError("v184 predecessor manifest identity changed")
    _validate_predecessor_evidence(successor)
    expected = {
        _REPOSITORY / successor.inherited_runner_path: successor.inherited_runner_sha256,
        _REPOSITORY / successor.inherited_contract_path: successor.inherited_contract_sha256,
        _REPOSITORY / successor.bounded_process_runner_path: (
            successor.bounded_process_runner_sha256
        ),
        _REPOSITORY / successor.predecessor_audit_path: successor.predecessor_audit_sha256,
    }
    for path, digest in expected.items():
        if path.is_symlink() or not path.is_file() or _hash_file(path) != digest:
            raise ConfigurationError("v184 frozen predecessor input changed")
    if (
        predecessor.build_timeout_seconds != successor.build_timeout_seconds
        or predecessor.build_output_max_bytes != successor.build_output_max_bytes
        or predecessor.cleanup_timeout_seconds != successor.cleanup_timeout_seconds
        or predecessor.cleanup_output_max_bytes != successor.cleanup_output_max_bytes
        or predecessor.build_network != "none"
        or predecessor.outer_dind_network != "none"
        or predecessor.cleanup_network != "none"
        or predecessor.pull is not False
        or predecessor.progress_mode != "plain"
    ):
        raise ConfigurationError("v184 exact v182 runtime bounds changed")

    builder, inherited_archive = v182._preflight_inputs(predecessor)  # noqa: SLF001
    runtime = _runtime_manifest(successor, predecessor)
    if (
        v182._volume_exists(runtime.dind_data_volume)  # noqa: SLF001
        or v182._volume_exists(runtime.dind_socket_volume)  # noqa: SLF001
        or v172._docker_image_id(runtime.final_image_tag, required=False) is not None  # noqa: SLF001
    ):
        raise ConfigurationError("v184 campaign resource identity is not fresh")
    archive_receipt = _reissue(
        inherited_archive,
        format_id="verigym_deepseek_harness_hwe_v184_local_builder_archive_v1",
        hash_field="receipt_hash",
    )
    return predecessor, runtime, builder, archive_receipt


def _runtime_manifest(
    successor: OpenToolchainV184MissingCommandManifest,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
) -> OpenToolchainV182BuildDiagnosticManifest:
    return predecessor.model_copy(
        update={
            "identity": IDENTITY,
            "final_image_tag": successor.final_image_tag,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )


def _validate_predecessor_evidence(
    successor: OpenToolchainV184MissingCommandManifest,
) -> None:
    root = Path(successor.predecessor_result_root)
    entries = (
        sorted(root.iterdir(), key=lambda item: item.name)
        if root == V182_RESULT_ROOT and root.is_dir() and not root.is_symlink()
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
        raise ConfigurationError("v184 predecessor result tree changed")
    for entry in entries:
        metadata = entry.stat() if entry.is_file() and not entry.is_symlink() else None
        if (
            metadata is None
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
            or _hash_file(entry) != successor.predecessor_result_file_sha256[entry.name]
        ):
            raise ConfigurationError("v184 predecessor result file changed")
    try:
        report = json.loads((root / "zero-provider-report.json").read_bytes())
        progress = json.loads((root / "materialization-progress.json").read_bytes())
        diagnostic = json.loads((root / "build-diagnostic.json").read_bytes())
        cleanup = json.loads((root / "cleanup.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v184 predecessor evidence is malformed") from exc
    required = {
        "identity": successor.predecessor_identity,
        "manifest_hash": successor.predecessor_manifest_hash,
        "source_commit": successor.predecessor_implementation_merge_commit,
        "post_merge_main_run_id": successor.predecessor_post_merge_main_run_id,
        "status": "completed_build_diagnostic",
        "diagnostic_category": successor.predecessor_diagnostic_category,
        "diagnostic_hash": successor.predecessor_diagnostic_hash,
        "cleanup_complete": True,
        "provider_calls": 0,
        "model_process_count": 0,
        "hwe_image_import_count": 0,
        "task_source_prepare_count": 0,
        "verifier_run_count": 0,
        "qualification_contract_published": False,
        **_closed_flags(),
    }
    report_base = dict(report)
    report_hash = report_base.pop("report_hash", None)
    diagnostic_base = dict(diagnostic)
    diagnostic_hash = diagnostic_base.pop("diagnostic_hash", None)
    cleanup_base = dict(cleanup)
    cleanup_hash = cleanup_base.pop("cleanup_hash", None)
    if (
        report != progress
        or any(report.get(name) != value for name, value in required.items())
        or report_hash != successor.predecessor_report_hash
        or content_hash(report_base) != report_hash
        or diagnostic.get("category") != successor.predecessor_diagnostic_category
        or diagnostic_hash != successor.predecessor_diagnostic_hash
        or content_hash(diagnostic_base) != diagnostic_hash
        or diagnostic.get("raw_output_persisted") is not False
        or cleanup.get("cleanup_complete") is not True
        or report.get("cleanup_hash") != cleanup_hash
        or content_hash(cleanup_base) != cleanup_hash
        or (root / "qualification-contract.json").exists()
    ):
        raise ConfigurationError("v184 predecessor terminal boundary changed")
    audit = _REPOSITORY / successor.predecessor_audit_path
    audit_text = audit.read_text(encoding="utf-8")
    if (
        _hash_file(audit) != successor.predecessor_audit_sha256
        or "missing-executable disambiguation" not in audit_text
        or "Unknown or multiple matches must fail closed" not in audit_text
        or "PR-1816" not in audit_text
    ):
        raise ConfigurationError("v184 audit authorization changed")


def _probe_builder_commands(
    successor: OpenToolchainV184MissingCommandManifest,
    *,
    runtime: OpenToolchainV182BuildDiagnosticManifest,
    docker_host: str,
    active_sensitive_values: tuple[bytes, ...],
) -> tuple[dict[str, bool], dict[str, Any]]:
    name = f"verigym-v184-command-probe-{secrets.token_hex(6)}"
    command_words = " ".join(successor.command_allowlist)
    script = (
        f"for candidate in {command_words}; do "
        'if command -v "$candidate" >/dev/null 2>&1; then printf 1; else printf 0; fi; '
        "done; printf '\\n'"
    )
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
        "verigym.role=builder-command-probe",
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
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "1",
        "--ipc",
        "none",
        "--workdir",
        "/",
        "--entrypoint",
        "/bin/sh",
        runtime.local_builder_image_id,
        "-ceu",
        script,
    ]
    container_id = v182._run_control(create, timeout=60).stdout.decode().strip()  # noqa: SLF001
    try:
        if not _inspect_command_probe(container_id, runtime, docker_host=docker_host):
            raise ConfigurationError("v184 command probe isolation changed")
        result = v176._run_bounded_process(  # noqa: SLF001
            ["docker", "--host", docker_host, "container", "start", "--attach", container_id],
            timeout=successor.command_probe_timeout_seconds,
            maximum=successor.command_probe_output_max_bytes,
        )
        sensitive = v182._contains_sensitive_output(  # noqa: SLF001
            result.stdout,
            result.stderr,
            active_sensitive_values=active_sensitive_values,
        )
        bits = result.stdout.rstrip(b"\n")
        if (
            sensitive
            or result.returncode != 0
            or result.timed_out
            or not result.output_within_bound
            or result.stderr
            or len(bits) != len(successor.command_allowlist)
            or any(bit not in b"01" for bit in bits)
        ):
            raise ConfigurationError("v184 command probe failed closed")
        availability = {
            command: bits[index : index + 1] == b"1"
            for index, command in enumerate(successor.command_allowlist)
        }
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_deepseek_harness_hwe_v184_builder_command_probe_v1",
            "identity": IDENTITY,
            "command_availability": availability,
            "command_count": len(availability),
            "network": "none",
            "read_only_root": True,
            "non_root": True,
            "cap_drop_all": True,
            "no_new_privileges": True,
            "mount_count": 0,
            "probe_output_bytes": len(result.stdout),
            "probe_output_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "sensitive_output_detected": False,
            "raw_probe_output_persisted": False,
            "command_argv_persisted": False,
            "environment_names_persisted": False,
            "environment_values_persisted": False,
        }
        return availability, {**base, "probe_hash": content_hash(base)}
    finally:
        removed = v182._run_control(  # noqa: SLF001
            ["docker", "--host", docker_host, "container", "rm", "--force", container_id],
            timeout=60,
            check=False,
        )
        if removed.returncode != 0:
            raise ConfigurationError("v184 command probe cleanup failed")


def _inspect_command_probe(
    name: str,
    runtime: OpenToolchainV182BuildDiagnosticManifest,
    *,
    docker_host: str,
) -> bool:
    inspection = v172._inspect_container(name, host=docker_host)  # noqa: SLF001
    host = inspection.get("HostConfig") or {}
    config = inspection.get("Config") or {}
    environment_names = {
        item.partition("=")[0] for item in config.get("Env") or [] if isinstance(item, str)
    }
    return bool(
        config.get("Image") == runtime.local_builder_image_id
        and config.get("User") == f"{os.getuid()}:{os.getgid()}"
        and config.get("Entrypoint") == ["/bin/sh"]
        and config.get("Labels", {}).get("verigym.owner") == OWNER
        and config.get("Labels", {}).get("verigym.role") == "builder-command-probe"
        and host.get("NetworkMode") == "none"
        and host.get("ReadonlyRootfs") is True
        and host.get("Privileged") is False
        and host.get("CapAdd") in (None, [])
        and set(host.get("CapDrop") or []) == {"ALL"}
        and any(str(item).startswith("no-new-privileges") for item in host.get("SecurityOpt") or [])
        and host.get("PidsLimit") == 64
        and host.get("Memory") == 256 * 1024**2
        and host.get("MemorySwap") == 256 * 1024**2
        and host.get("NanoCpus") == 1_000_000_000
        and host.get("IpcMode") == "none"
        and inspection.get("Mounts") in (None, [])
        and not any(v182._SENSITIVE_NAME.search(item) for item in environment_names)  # noqa: SLF001
    )


def _run_build_diagnostic(
    successor: OpenToolchainV184MissingCommandManifest,
    *,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
    runtime: OpenToolchainV182BuildDiagnosticManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    scratch: Path,
    docker_host: str,
    availability: dict[str, bool],
    active_sensitive_values: tuple[bytes, ...],
) -> dict[str, Any]:
    context = scratch / "build-context"
    context.mkdir(mode=0o700)
    shutil.copy2(runtime.verilator_archive_path, context / "verilator-v5.008.tar.gz")
    shutil.copy2(
        runtime.ripgrep_archive_path,
        context / "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz",
    )
    result = v176._run_bounded_process(  # noqa: SLF001
        v182._build_command(runtime, context=context, docker_host=docker_host),  # noqa: SLF001
        timeout=successor.build_timeout_seconds,
        maximum=successor.build_output_max_bytes,
    )
    sensitive = v182._contains_sensitive_output(  # noqa: SLF001
        result.stdout,
        result.stderr,
        active_sensitive_values=active_sensitive_values,
    )
    resolution = _classify_build_result(
        result,
        sensitive=sensitive,
        successor=successor,
        availability=availability,
    )
    category = resolution["category"]
    if category == "success":
        image_id = v172._docker_image_id(runtime.final_image_tag, host=docker_host)  # noqa: SLF001
        if image_id in {
            runtime.accepted_open_tools_image_id,
            runtime.dind_image_id,
            builder.local_builder_image_id,
        }:
            category = "controller_error"
    return _diagnostic_receipt(
        successor,
        predecessor=predecessor,
        result=result,
        category=category,
        sensitive=sensitive,
        missing_command=resolution["missing_command"],
        marker_count=resolution["marker_count"],
        distinct_allowlisted_count=resolution["distinct_allowlisted_count"],
        unknown_marker_present=resolution["unknown_marker_present"],
        command_available_before_build=resolution["command_available_before_build"],
    )


def _classify_build_result(
    result: Any,
    *,
    sensitive: bool,
    successor: OpenToolchainV184MissingCommandManifest,
    availability: dict[str, bool],
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "missing_command": None,
        "marker_count": 0,
        "distinct_allowlisted_count": 0,
        "unknown_marker_present": False,
        "command_available_before_build": None,
    }
    if sensitive:
        return {**base, "category": "sensitive_output"}
    if not result.output_within_bound:
        return {**base, "category": "output_overflow"}
    if result.timed_out:
        return {**base, "category": "timeout"}
    if result.returncode == 0:
        return {**base, "category": "success"}
    output = result.stdout + b"\0" + result.stderr
    lowered = output.lower()
    if b"no space left on device" in lowered or b"disk quota exceeded" in lowered:
        return {**base, "category": "storage_exhausted"}
    if any(
        marker in lowered
        for marker in (
            b"killed signal terminated program cc1plus",
            b"fatal error: killed",
            b"out of memory",
        )
    ):
        return {**base, "category": "compiler_killed"}
    if b"no rule to make target" in lowered:
        return {**base, "category": "missing_make_target"}

    matches = [match.group("command") for match in _MISSING_COMMAND.finditer(output)]
    allowlist = set(successor.command_allowlist)
    allowed: set[str] = set()
    unknown = False
    for token in matches:
        try:
            name = token.rsplit(b"/", 1)[-1].decode("ascii")
        except UnicodeDecodeError:
            unknown = True
            continue
        if name in allowlist:
            allowed.add(name)
        else:
            unknown = True
    counts = {
        **base,
        "marker_count": len(matches),
        "distinct_allowlisted_count": len(allowed),
        "unknown_marker_present": unknown,
    }
    if not matches:
        return {**counts, "category": "no_missing_executable_marker"}
    if unknown:
        return {**counts, "category": "unknown_missing_executable"}
    if len(allowed) != 1:
        return {**counts, "category": "multiple_missing_executables"}
    missing_command = next(iter(allowed))
    command_available = availability[missing_command]
    details = {
        **counts,
        "missing_command": missing_command,
        "command_available_before_build": command_available,
    }
    if missing_command in successor.generated_commands:
        category = "generated_binary_absent_after_prior_build_failure"
    elif missing_command in successor.dockerfile_injected_commands:
        category = "dockerfile_injected_command_absent"
    elif not command_available:
        category = "missing_builder_prerequisite"
    else:
        category = "allowlisted_command_present_but_not_found"
    return {**details, "category": category}


def _diagnostic_receipt(
    successor: OpenToolchainV184MissingCommandManifest,
    *,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
    result: Any | None,
    category: str,
    sensitive: bool,
    missing_command: str | None,
    marker_count: int,
    distinct_allowlisted_count: int,
    unknown_marker_present: bool,
    command_available_before_build: bool | None,
) -> dict[str, Any]:
    if category not in successor.result_categories:
        raise ConfigurationError("v184 refuses an unknown result category")
    if missing_command is not None and missing_command not in successor.command_allowlist:
        raise ConfigurationError("v184 refuses a non-allowlisted command")
    command_categories = {
        "missing_builder_prerequisite",
        "generated_binary_absent_after_prior_build_failure",
        "allowlisted_command_present_but_not_found",
        "dockerfile_injected_command_absent",
    }
    if (category in command_categories) != (missing_command is not None):
        raise ConfigurationError("v184 command identity and category disagree")
    stdout = b"" if result is None else result.stdout
    stderr = b"" if result is None else result.stderr
    safe_to_hash = not sensitive
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v184_missing_command_diagnostic_v1",
        "identity": IDENTITY,
        "predecessor_diagnostic_hash": successor.predecessor_diagnostic_hash,
        "final_dockerfile_sha256": predecessor.final_dockerfile_sha256,
        "local_builder_image_id": predecessor.local_builder_image_id,
        "accepted_open_tools_image_id": predecessor.accepted_open_tools_image_id,
        "build_network": "none",
        "pull": False,
        "progress_mode": "plain",
        "timeout_seconds": successor.build_timeout_seconds,
        "output_max_bytes": successor.build_output_max_bytes,
        "category": category,
        "missing_command": missing_command,
        "marker_count": marker_count,
        "distinct_allowlisted_count": distinct_allowlisted_count,
        "unknown_marker_present": unknown_marker_present,
        "command_available_before_build": command_available_before_build,
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
        "raw_matching_line_persisted": False,
        "arbitrary_token_persisted": False,
        "path_persisted": False,
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


def _reissue(receipt: dict[str, Any], *, format_id: str, hash_field: str) -> dict[str, Any]:
    base = dict(receipt)
    base.pop(hash_field, None)
    base.update({"format_id": format_id, "identity": IDENTITY})
    return {**base, hash_field: content_hash(base)}


def _headroom_receipt(
    successor: OpenToolchainV184MissingCommandManifest,
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
        "format_id": "verigym_deepseek_harness_hwe_v184_headroom_v1",
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
        raise ConfigurationError("v184 absolute headroom gate failed")
    return {**base, "receipt_hash": content_hash(base)}


def _require_execution_boundary(
    arguments: argparse.Namespace,
    successor: OpenToolchainV184MissingCommandManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v184 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v184 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v184 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v184 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= successor.predecessor_audit_post_merge_main_run_id:
        raise ConfigurationError("v184 requires a new post-merge main run identity")


@contextmanager
def _patched_v182_runtime() -> Iterator[None]:
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
    previous = {name: getattr(v182, name) for name in bindings}
    for name, value in bindings.items():
        setattr(v182, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(v182, name, value)


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


def _hash_file(path: Path) -> str:
    return v172._hash_file(path)  # noqa: SLF001


def _exact_file(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or expected.is_symlink() or not path.is_file():
        raise ConfigurationError(f"v184 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v184 {label} identity changed")
    return resolved


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_category": report["diagnostic_category"],
                "missing_command": report["missing_command"],
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
