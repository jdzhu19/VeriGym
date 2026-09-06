#!/usr/bin/env python3
"""Run the one-use task-free v186 diagnostic-context refinement."""

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
from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v184_missing_command as v184,
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
    V186_IDENTITY,
    OpenToolchainV186DiagnosticContextManifest,
    load_v186_diagnostic_context_manifest,
)
from verigym.hwe.open_toolchain_local_builder import (  # noqa: E402
    OpenToolchainV178LocalBuilderManifest,
)
from verigym.hwe.open_toolchain_missing_command import (  # noqa: E402
    OpenToolchainV184MissingCommandManifest,
    load_v184_missing_command_manifest,
)

IDENTITY = V186_IDENTITY
OPT_IN_ENV = "VERIGYM_RUN_DEEPSEEK_HARNESS_V186_DIAGNOSTIC_CONTEXT"
SANITIZED_CHILD_ENV = "VERIGYM_V186_SANITIZED_CHILD"
MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v186_diagnostic_context_refinement_v1.json"
)
V184_MANIFEST = _REPOSITORY / (
    "configs/training/qwen35_hwe_deepseek_harness_v184_missing_command_disambiguation_v1.json"
)
V184_RESULT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/"
    "deepseek-harness-hwe-v184-missing-command-disambiguation-v1"
)
OUTPUT_ROOT = Path(
    "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v186-diagnostic-context-refinement-v1"
)
SCRATCH_ROOT = Path(
    "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v186-diagnostic-context-refinement"
)
BACKING_PARENT = Path("/data2/jiadongzhu/docker/deepseek-harness-hwe-v186")
DATA_BACKING = BACKING_PARENT / "data"
SOCKET_BACKING = BACKING_PARENT / "socket"
OWNER = "deepseek-harness-hwe-v186-diagnostic-context"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_ALLOWED_UNTRACKED_PATHS = v178._ALLOWED_UNTRACKED_PATHS  # noqa: SLF001
_TOKEN = rb"[A-Za-z0-9_+./-]+"
_COLON_NOT_FOUND = re.compile(
    rb"(?<![A-Za-z0-9_+./-])(?P<command>" + _TOKEN + rb"): (?:command )?not found(?=\r?$)",
    re.MULTILINE,
)
_CONTEXT_PATTERNS = (
    (
        "posix_sh_command_not_found",
        re.compile(
            rb"(?<![A-Za-z0-9_./-])(?:/bin/)?sh: [0-9]+: (?P<command>"
            + _TOKEN
            + rb"): (?:command )?not found(?=\r?$)",
            re.MULTILINE,
        ),
    ),
    (
        "bash_command_not_found",
        re.compile(
            rb"(?<![A-Za-z0-9_./-])(?:/bin/)?bash: (?:line )?[0-9]+: (?P<command>"
            + _TOKEN
            + rb"): command not found(?=\r?$)",
            re.MULTILINE,
        ),
    ),
    (
        "make_command_not_found",
        re.compile(
            rb"(?<![A-Za-z0-9_])make(?:\[[0-9]+\])?: (?P<command>"
            + _TOKEN
            + rb"): (?:command )?not found(?=\r?$)",
            re.MULTILINE,
        ),
    ),
)
_REQUIRED_MERGED_PATHS = (
    "SECURITY.md",
    "configs/training/qwen35_hwe_deepseek_harness_v184_missing_command_disambiguation_v1.json",
    "configs/training/qwen35_hwe_deepseek_harness_v186_diagnostic_context_refinement_v1.json",
    "docs/audits/2026-09-06_deepseek-harness-v185-v184-result.md",
    "docs/hwe_deepseek_harness_collection.md",
    "integrations/verigym-deepseek-harness/tests/test_v186_diagnostic_context.py",
    "scripts/launch_hwe_deepseek_harness_v186_diagnostic_context.py",
    "scripts/materialize_hwe_deepseek_harness_v176_open_toolchain_repair.py",
    "scripts/materialize_hwe_deepseek_harness_v178_local_builder.py",
    "scripts/materialize_hwe_deepseek_harness_v182_bounded_open_build.py",
    "scripts/materialize_hwe_deepseek_harness_v184_missing_command.py",
    "scripts/materialize_hwe_deepseek_harness_v186_diagnostic_context.py",
    "src/verigym/hwe/open_toolchain_diagnostic_context.py",
    "src/verigym/hwe/open_toolchain_missing_command.py",
    "tests/unit/test_hwe_open_toolchain_diagnostic_context.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--post-merge-main-run-id", type=int, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run the sole authorized refinement and always seal a terminal report."""

    successor = load_v186_diagnostic_context_manifest(
        _exact_file(arguments.manifest, MANIFEST, "manifest")
    )
    _require_execution_boundary(arguments, successor)
    with _patched_inherited_runtime():
        source_commit = v182._require_clean_merged_main()  # noqa: SLF001
        active_sensitive_values = v182._active_sensitive_values()  # noqa: SLF001
        with v182._sanitized_process_environment():  # noqa: SLF001
            predecessor, runtime, builder, archive_receipt, probe_proxy = _preflight_inputs(
                successor
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
                probe_proxy=probe_proxy,
            )


def _execute(
    arguments: argparse.Namespace,
    *,
    successor: OpenToolchainV186DiagnosticContextManifest,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
    runtime: OpenToolchainV182BuildDiagnosticManifest,
    builder: OpenToolchainV178LocalBuilderManifest,
    root: Path,
    scratch: Path,
    source_commit: str,
    active_sensitive_values: tuple[bytes, ...],
    archive_receipt: dict[str, Any],
    probe_proxy: OpenToolchainV184MissingCommandManifest,
) -> dict[str, Any]:
    progress: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v186_progress_v1",
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
        atomic_dump_json(root / "headroom.json", _headroom_receipt(successor))
        atomic_dump_json(root / "local-builder-archive.json", archive_receipt)
        progress["status"] = "local_transfer_prepare"
        _write_progress(root, progress)
        transfers = v182._save_transfer_inputs(  # noqa: SLF001
            runtime, builder=builder, scratch=scratch
        )
        v182._prepare_dind_backings(runtime)  # noqa: SLF001
        v182._create_bind_volume(runtime.dind_data_volume, DATA_BACKING)  # noqa: SLF001
        v182._create_bind_volume(runtime.dind_socket_volume, SOCKET_BACKING)  # noqa: SLF001
        dind_name = f"verigym-dind-v186-{secrets.token_hex(8)}"
        dind_receipt = _reissue(
            v182._start_dind(dind_name, runtime, root=root, scratch=scratch),  # noqa: SLF001
            format_id="verigym_deepseek_harness_hwe_v186_dind_runtime_v1",
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
            format_id="verigym_deepseek_harness_hwe_v186_local_builder_binding_v1",
            hash_field="binding_hash",
        )
        atomic_dump_json(root / "local-builder-binding.json", builder_receipt)

        progress["status"] = "closed_dictionary_probe"
        _write_progress(root, progress)
        availability, inherited_probe = v184._probe_builder_commands(  # noqa: SLF001
            probe_proxy,
            runtime=runtime,
            docker_host=docker_host,
            active_sensitive_values=active_sensitive_values,
        )
        probe_receipt = _reissue(
            inherited_probe,
            format_id="verigym_deepseek_harness_hwe_v186_command_dictionary_probe_v1",
            hash_field="probe_hash",
        )
        atomic_dump_json(root / "command-dictionary-probe.json", probe_receipt)

        progress["status"] = "bounded_diagnostic_context_refinement"
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
        atomic_dump_json(root / "diagnostic-context.json", diagnostic)
        progress["status"] = "diagnostic_context_refined"
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
                resolution=_base_resolution(),
            )
            atomic_dump_json(root / "diagnostic-context.json", diagnostic)

    cleanup = _reissue(
        v182._cleanup(  # noqa: SLF001
            runtime,
            scratch=scratch,
            active_sensitive_values=active_sensitive_values,
        ),
        format_id="verigym_deepseek_harness_hwe_v186_cleanup_v1",
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
        status_value = "completed_diagnostic_context_refinement"
    terminal = {
        **progress,
        "status": status_value,
        "diagnostic_category": category,
        "diagnostic_hash": diagnostic["diagnostic_hash"],
        "diagnostic_context": diagnostic["diagnostic_context"],
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
        "arbitrary_token_hash_persisted": False,
        "path_persisted": False,
        "command_argv_persisted": False,
        "environment_names_persisted": False,
        "environment_values_persisted": False,
        "requires_independent_v187_audit": True,
    }
    sealed = _seal(terminal)
    _write_progress(root, terminal)
    atomic_dump_json(root / "zero-provider-report.json", sealed)
    v182._normalize_result_modes(root)  # noqa: SLF001
    return sealed


def _preflight_inputs(
    successor: OpenToolchainV186DiagnosticContextManifest,
) -> tuple[
    OpenToolchainV182BuildDiagnosticManifest,
    OpenToolchainV182BuildDiagnosticManifest,
    OpenToolchainV178LocalBuilderManifest,
    dict[str, Any],
    OpenToolchainV184MissingCommandManifest,
]:
    predecessor_path = _REPOSITORY / successor.predecessor_manifest_path
    if (
        predecessor_path != V184_MANIFEST
        or _hash_file(predecessor_path) != successor.predecessor_manifest_sha256
    ):
        raise ConfigurationError("v186 predecessor manifest file changed")
    predecessor_v184 = load_v184_missing_command_manifest(predecessor_path)
    if predecessor_v184.manifest_hash != successor.predecessor_manifest_hash:
        raise ConfigurationError("v186 predecessor manifest identity changed")
    _validate_predecessor_evidence(successor)
    expected = {
        _REPOSITORY / successor.inherited_runner_path: successor.inherited_runner_sha256,
        _REPOSITORY / successor.inherited_contract_path: successor.inherited_contract_sha256,
        _REPOSITORY / successor.predecessor_audit_path: successor.predecessor_audit_sha256,
    }
    for path, digest in expected.items():
        if path.is_symlink() or not path.is_file() or _hash_file(path) != digest:
            raise ConfigurationError("v186 frozen predecessor input changed")
    if (
        predecessor_v184.build_timeout_seconds != successor.build_timeout_seconds
        or predecessor_v184.build_output_max_bytes != successor.build_output_max_bytes
        or predecessor_v184.command_probe_timeout_seconds != successor.command_probe_timeout_seconds
        or predecessor_v184.command_probe_output_max_bytes
        != successor.command_probe_output_max_bytes
        or predecessor_v184.cleanup_timeout_seconds != successor.cleanup_timeout_seconds
        or predecessor_v184.cleanup_output_max_bytes != successor.cleanup_output_max_bytes
        or predecessor_v184.control_root_min_available_bytes
        != successor.control_root_min_available_bytes
        or predecessor_v184.data2_min_available_bytes != successor.data2_min_available_bytes
        or predecessor_v184.build_network != "none"
        or predecessor_v184.command_probe_network != "none"
        or predecessor_v184.outer_dind_network != "none"
        or predecessor_v184.cleanup_network != "none"
        or predecessor_v184.pull is not False
        or predecessor_v184.progress_mode != "plain"
    ):
        raise ConfigurationError("v186 exact v184 runtime bounds changed")

    probe_proxy = predecessor_v184.model_copy(
        update={
            "command_allowlist": successor.command_dictionary,
            "builder_prerequisite_commands": successor.builder_prerequisite_commands,
            "generated_commands": successor.generated_commands,
            "dockerfile_injected_commands": successor.dockerfile_injected_commands,
            "final_image_tag": successor.final_image_tag,
            "dind_data_volume": successor.dind_data_volume,
            "dind_socket_volume": successor.dind_socket_volume,
            "dind_data_backing": successor.dind_data_backing,
            "dind_socket_backing": successor.dind_socket_backing,
            "output_root": successor.output_root,
            "scratch_root": successor.scratch_root,
        }
    )
    predecessor, runtime, builder, inherited_archive = v184._preflight_inputs(  # noqa: SLF001
        probe_proxy
    )
    archive_receipt = _reissue(
        inherited_archive,
        format_id="verigym_deepseek_harness_hwe_v186_local_builder_archive_v1",
        hash_field="receipt_hash",
    )
    return predecessor, runtime, builder, archive_receipt, probe_proxy


def _validate_predecessor_evidence(
    successor: OpenToolchainV186DiagnosticContextManifest,
) -> None:
    root = Path(successor.predecessor_result_root)
    entries = (
        sorted(root.iterdir(), key=lambda item: item.name)
        if root == V184_RESULT_ROOT and root.is_dir() and not root.is_symlink()
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
        raise ConfigurationError("v186 predecessor result tree changed")
    for entry in entries:
        metadata = entry.stat() if entry.is_file() and not entry.is_symlink() else None
        if (
            metadata is None
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_gid != os.getgid()
            or _hash_file(entry) != successor.predecessor_result_file_sha256[entry.name]
        ):
            raise ConfigurationError("v186 predecessor result file changed")
    try:
        report = json.loads((root / "zero-provider-report.json").read_bytes())
        progress = json.loads((root / "materialization-progress.json").read_bytes())
        diagnostic = json.loads((root / "missing-command-diagnostic.json").read_bytes())
        cleanup = json.loads((root / "cleanup.json").read_bytes())
        probe = json.loads((root / "builder-command-probe.json").read_bytes())
        archive = json.loads((root / "local-builder-archive.json").read_bytes())
        binding = json.loads((root / "local-builder-binding.json").read_bytes())
        headroom = json.loads((root / "headroom.json").read_bytes())
        dind = json.loads((root / "dind-runtime.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("v186 predecessor evidence is malformed") from exc
    required = {
        "identity": successor.predecessor_identity,
        "manifest_hash": successor.predecessor_manifest_hash,
        "source_commit": successor.predecessor_source_commit,
        "post_merge_main_run_id": successor.predecessor_post_merge_main_run_id,
        "status": "completed_missing_command_disambiguation",
        "diagnostic_category": successor.predecessor_diagnostic_category,
        "diagnostic_hash": successor.predecessor_diagnostic_hash,
        "missing_command": None,
        "cleanup_complete": True,
        "provider_calls": 0,
        "model_process_count": 0,
        "hwe_image_import_count": 0,
        "task_source_prepare_count": 0,
        "verifier_run_count": 0,
        "qualification_contract_published": False,
        **_closed_flags(),
    }
    report_hash = _embedded_hash(report, "report_hash")
    diagnostic_hash = _embedded_hash(diagnostic, "diagnostic_hash")
    cleanup_hash = _embedded_hash(cleanup, "cleanup_hash")
    probe_hash = _embedded_hash(probe, "probe_hash")
    archive_hash = _embedded_hash(archive, "receipt_hash")
    binding_hash = _embedded_hash(binding, "binding_hash")
    headroom_hash = _embedded_hash(headroom, "receipt_hash")
    dind_hash = _embedded_hash(dind, "receipt_hash")
    if (
        report != progress
        or any(report.get(name) != value for name, value in required.items())
        or report_hash != successor.predecessor_report_hash
        or report.get("raw_output_persisted") is not False
        or report.get("raw_matching_line_persisted") is not False
        or report.get("arbitrary_token_persisted") is not False
        or diagnostic.get("category") != successor.predecessor_diagnostic_category
        or diagnostic.get("marker_count") != 2
        or diagnostic.get("distinct_allowlisted_count") != 0
        or diagnostic.get("unknown_marker_present") is not True
        or diagnostic.get("raw_output_persisted") is not False
        or diagnostic.get("raw_matching_line_persisted") is not False
        or diagnostic.get("arbitrary_token_persisted") is not False
        or diagnostic_hash != successor.predecessor_diagnostic_hash
        or cleanup.get("cleanup_complete") is not True
        or cleanup_hash != successor.predecessor_cleanup_hash
        or probe_hash != successor.predecessor_probe_hash
        or probe.get("raw_probe_output_persisted") is not False
        or archive_hash is None
        or binding_hash is None
        or headroom_hash is None
        or dind_hash is None
        or (root / "qualification-contract.json").exists()
    ):
        raise ConfigurationError("v186 predecessor terminal boundary changed")
    audit = _REPOSITORY / successor.predecessor_audit_path
    audit_text = audit.read_text(encoding="utf-8")
    if (
        _hash_file(audit) != successor.predecessor_audit_sha256
        or "diagnostic-context refinement" not in audit_text
        or "arbitrary token or its hash" not in audit_text
        or "V186 may not change the Dockerfile" not in audit_text
        or "PR-1816" not in audit_text
    ):
        raise ConfigurationError("v186 audit authorization changed")


def _embedded_hash(value: dict[str, Any], field: str) -> str | None:
    base = dict(value)
    observed = base.pop(field, None)
    return observed if observed == content_hash(base) else None


def _run_build_diagnostic(
    successor: OpenToolchainV186DiagnosticContextManifest,
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
            resolution = {**resolution, "category": category}
    return _diagnostic_receipt(
        successor,
        predecessor=predecessor,
        result=result,
        category=category,
        sensitive=sensitive,
        resolution=resolution,
    )


def _base_resolution() -> dict[str, Any]:
    return {
        "category": "controller_error",
        "missing_command": None,
        "marker_count": 0,
        "contextual_marker_count": 0,
        "unscoped_marker_count": 0,
        "distinct_dictionary_count": 0,
        "unknown_dictionary_token_present": False,
        "diagnostic_context": "none",
        "context_counts": {
            "posix_sh_command_not_found": 0,
            "bash_command_not_found": 0,
            "make_command_not_found": 0,
            "unscoped_colon_not_found": 0,
        },
        "command_available_before_build": None,
    }


def _classify_build_result(
    result: Any,
    *,
    sensitive: bool,
    successor: OpenToolchainV186DiagnosticContextManifest,
    availability: dict[str, bool],
) -> dict[str, Any]:
    base = _base_resolution()
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

    legacy = list(_COLON_NOT_FOUND.finditer(output))
    contextual: dict[tuple[int, int], tuple[str, bytes]] = {}
    for context_name, pattern in _CONTEXT_PATTERNS:
        for match in pattern.finditer(output):
            contextual[match.span("command")] = (context_name, match.group("command"))
    context_counts = dict(base["context_counts"])
    dictionary = set(successor.command_dictionary)
    dictionary_commands: set[str] = set()
    unknown_dictionary_token = False
    for match in legacy:
        item = contextual.get(match.span("command"))
        if item is None:
            context_counts["unscoped_colon_not_found"] += 1
            continue
        context_name, token = item
        context_counts[context_name] += 1
        try:
            command = token.rsplit(b"/", 1)[-1].decode("ascii")
        except UnicodeDecodeError:
            unknown_dictionary_token = True
            continue
        if command in dictionary:
            dictionary_commands.add(command)
        else:
            unknown_dictionary_token = True

    present_contexts = {name for name, count in context_counts.items() if count}
    diagnostic_context = (
        "none"
        if not present_contexts
        else next(iter(present_contexts))
        if len(present_contexts) == 1
        else "mixed"
    )
    details = {
        **base,
        "marker_count": len(legacy),
        "contextual_marker_count": sum(
            count for name, count in context_counts.items() if name != "unscoped_colon_not_found"
        ),
        "unscoped_marker_count": context_counts["unscoped_colon_not_found"],
        "distinct_dictionary_count": len(dictionary_commands),
        "unknown_dictionary_token_present": unknown_dictionary_token,
        "diagnostic_context": diagnostic_context,
        "context_counts": context_counts,
    }
    if not legacy:
        return {**details, "category": "no_command_context_marker"}
    if "unscoped_colon_not_found" in present_contexts:
        category = (
            "unscoped_colon_not_found"
            if len(present_contexts) == 1
            else "mixed_diagnostic_contexts"
        )
        return {**details, "category": category}
    if len(present_contexts) != 1:
        return {**details, "category": "mixed_diagnostic_contexts"}
    if unknown_dictionary_token:
        return {**details, "category": "unknown_closed_dictionary_command"}
    if len(dictionary_commands) != 1:
        return {**details, "category": "multiple_closed_dictionary_commands"}
    missing_command = next(iter(dictionary_commands))
    command_available = availability[missing_command]
    details.update(
        {
            "missing_command": missing_command,
            "command_available_before_build": command_available,
        }
    )
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
    successor: OpenToolchainV186DiagnosticContextManifest,
    *,
    predecessor: OpenToolchainV182BuildDiagnosticManifest,
    result: Any | None,
    category: str,
    sensitive: bool,
    resolution: dict[str, Any],
) -> dict[str, Any]:
    if category not in successor.result_categories:
        raise ConfigurationError("v186 refuses an unknown result category")
    missing_command = resolution["missing_command"]
    if missing_command is not None and missing_command not in successor.command_dictionary:
        raise ConfigurationError("v186 refuses a command outside the closed dictionary")
    command_categories = {
        "missing_builder_prerequisite",
        "generated_binary_absent_after_prior_build_failure",
        "allowlisted_command_present_but_not_found",
        "dockerfile_injected_command_absent",
    }
    if (category in command_categories) != (missing_command is not None):
        raise ConfigurationError("v186 command identity and category disagree")
    if resolution["diagnostic_context"] not in successor.diagnostic_contexts:
        raise ConfigurationError("v186 refuses an unknown diagnostic context")
    stdout = b"" if result is None else result.stdout
    stderr = b"" if result is None else result.stderr
    safe_to_hash = not sensitive
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_deepseek_harness_hwe_v186_diagnostic_context_v1",
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
        "marker_count": resolution["marker_count"],
        "contextual_marker_count": resolution["contextual_marker_count"],
        "unscoped_marker_count": resolution["unscoped_marker_count"],
        "distinct_dictionary_count": resolution["distinct_dictionary_count"],
        "unknown_dictionary_token_present": resolution["unknown_dictionary_token_present"],
        "diagnostic_context": resolution["diagnostic_context"],
        "context_counts": resolution["context_counts"],
        "command_available_before_build": resolution["command_available_before_build"],
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
        "arbitrary_token_hash_persisted": False,
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
    successor: OpenToolchainV186DiagnosticContextManifest,
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
        "format_id": "verigym_deepseek_harness_hwe_v186_headroom_v1",
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
        raise ConfigurationError("v186 absolute headroom gate failed")
    return {**base, "receipt_hash": content_hash(base)}


def _require_execution_boundary(
    arguments: argparse.Namespace,
    successor: OpenToolchainV186DiagnosticContextManifest,
) -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or os.environ.get(SANITIZED_CHILD_ENV) != "1":
        raise ConfigurationError("v186 exact opt-in launcher boundary is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("v186 requires a non-root host identity")
    if any(name in os.environ for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES):
        raise ConfigurationError("v186 refuses provider configuration")
    if "DOCKER_HOST" in os.environ or "DOCKER_CONTEXT" in os.environ:
        raise ConfigurationError("v186 requires the default host Docker endpoint")
    if arguments.post_merge_main_run_id <= successor.predecessor_audit_post_merge_main_run_id:
        raise ConfigurationError("v186 requires a new post-merge main run identity")


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
    previous = {name: getattr(v184, name) for name in bindings}
    for name, value in bindings.items():
        setattr(v184, name, value)
    try:
        with v184._patched_v182_runtime():  # noqa: SLF001
            yield
    finally:
        for name, value in previous.items():
            setattr(v184, name, value)


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
        raise ConfigurationError(f"v186 {label} path is unsafe")
    resolved = path.resolve(strict=True)
    if resolved != expected.resolve(strict=True):
        raise ConfigurationError(f"v186 {label} identity changed")
    return resolved


def main() -> int:
    report = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_category": report["diagnostic_category"],
                "diagnostic_context": report["diagnostic_context"],
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
