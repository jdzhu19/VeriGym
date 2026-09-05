"""Contracts for the v182 task-free bounded open-toolchain build diagnostic."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V182_IDENTITY = "deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 1024 * 1024
_V180_FILES = frozenset(
    {
        "archive-receipt.json",
        "dind-runtime.json",
        "headroom.json",
        "local-builder-archive.json",
        "local-builder-binding.json",
        "materialization-progress.json",
        "reference-patch-compatibility.json",
    }
)
_DIAGNOSTIC_CATEGORIES = (
    "success",
    "sensitive_output",
    "output_overflow",
    "timeout",
    "storage_exhausted",
    "compiler_killed",
    "compiler_error",
    "linker_error",
    "missing_make_target",
    "missing_executable",
    "docker_daemon_error",
    "unknown_nonzero",
    "controller_error",
)


class OpenToolchainV182BuildDiagnosticManifest(StrictModel):
    """Immutable one-use manifest for the task-free v182 diagnostic."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v182_build_diagnostic_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1"]
    predecessor_identity: Literal["deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1"]
    predecessor_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v180_dind_mount_repair_v1.json"
    ]
    predecessor_manifest_sha256: str
    predecessor_manifest_hash: str
    predecessor_result_root: str
    predecessor_result_tree_hash: str
    predecessor_result_file_sha256: dict[str, str]
    predecessor_stop_category: Literal["offline_final_image_build_nonzero"]
    predecessor_implementation_commit: str
    predecessor_implementation_merge_commit: str
    predecessor_qualification_main_run_id: Literal[33991118409]
    predecessor_audit_path: Literal[
        "docs/audits/2026-09-06_deepseek-harness-v181-v180-build-cleanup-stop.md"
    ]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_audit_merge_commit: str
    predecessor_audit_post_merge_main_run_id: Literal[33992761071]
    predecessor_audit_post_merge_all_eight_classes_passed: Literal[True]
    inherited_runner_path: Literal[
        "scripts/materialize_hwe_deepseek_harness_v180_dind_mount_repair.py"
    ]
    inherited_runner_sha256: str
    bounded_process_runner_path: Literal[
        "scripts/materialize_hwe_deepseek_harness_v176_open_toolchain_repair.py"
    ]
    bounded_process_runner_sha256: str
    local_builder_runner_path: Literal[
        "scripts/materialize_hwe_deepseek_harness_v178_local_builder.py"
    ]
    local_builder_runner_sha256: str
    final_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile.v180"]
    final_dockerfile_sha256: str
    builder_tag: Literal["verigym/open-rtl-tools:v180-builder"]
    final_image_tag: Literal["verigym/open-rtl-tools:hwe-v182-build-diagnostic"]
    local_builder_archive_path: Literal[
        "/data2/jiadongzhu/Agent/datasets/tools/open-builder/v178/verilator-build-deps.tar"
    ]
    local_builder_archive_sha256: str
    local_builder_image_id: str
    accepted_open_tools_tag: Literal["verigym/open-rtl-tools:iverilog12-yosys067"]
    accepted_open_tools_image_id: str
    verilator_archive_path: Literal[
        "/data2/jiadongzhu/Agent/datasets/tools/verilator/5.008/verilator-v5.008.tar.gz"
    ]
    verilator_archive_sha256: str
    verilator_commit: Literal["21093fd1bd36fed8943f67868ddc8f75f41e4488"]
    ripgrep_archive_path: Literal[
        "/data2/jiadongzhu/Agent/datasets/tools/ripgrep/15.2.0/"
        "ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz"
    ]
    ripgrep_archive_sha256: str
    ripgrep_binary_sha256: str
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v182-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v182-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v182/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v182/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v182-bounded-open-build-diagnostic"
    ]
    build_timeout_seconds: Literal[3600]
    build_output_max_bytes: Literal[16777216]
    cleanup_timeout_seconds: Literal[120]
    cleanup_output_max_bytes: Literal[1048576]
    diagnostic_categories: tuple[str, ...]
    build_network: Literal["none"]
    outer_dind_network: Literal["none"]
    cleanup_network: Literal["none"]
    pull: Literal[False]
    progress_mode: Literal["plain"]
    task_metadata_loaded: Literal[False]
    hwe_image_inspected: Literal[False]
    hwe_image_imported: Literal[False]
    task_source_prepared: Literal[False]
    verifier_run: Literal[False]
    model_process_count: Literal[0]
    provider_clients_available: Literal[False]
    provider_calls: Literal[0]
    registry_access_allowed: Literal[False]
    download_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    local_runtime_allowed: Literal[False]
    qualification_authorized: Literal[False]
    canary_authorized: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    requires_independent_v183_audit: Literal[True]
    manifest_hash: str

    @field_validator(
        "predecessor_manifest_sha256",
        "predecessor_manifest_hash",
        "predecessor_result_tree_hash",
        "predecessor_audit_sha256",
        "inherited_runner_sha256",
        "bounded_process_runner_sha256",
        "local_builder_runner_sha256",
        "final_dockerfile_sha256",
        "local_builder_archive_sha256",
        "verilator_archive_sha256",
        "ripgrep_archive_sha256",
        "ripgrep_binary_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v182 manifest requires lowercase SHA-256")
        return value

    @field_validator("local_builder_image_id", "accepted_open_tools_image_id", "dind_image_id")
    @classmethod
    def validate_image_id(cls, value: str) -> str:
        if (
            not value.startswith("sha256:")
            or _SHA256.fullmatch(value.removeprefix("sha256:")) is None
        ):
            raise ValueError("v182 manifest requires immutable image IDs")
        return value

    @field_validator("dind_repository_digest")
    @classmethod
    def validate_repository_digest(cls, value: str) -> str:
        if (
            not value.startswith("sha256:")
            or _SHA256.fullmatch(value.removeprefix("sha256:")) is None
        ):
            raise ValueError("v182 manifest requires an immutable repository digest")
        return value

    @field_validator("predecessor_result_file_sha256")
    @classmethod
    def validate_result_files(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _V180_FILES or any(
            _SHA256.fullmatch(digest) is None for digest in value.values()
        ):
            raise ValueError("v182 predecessor evidence inventory changed")
        return value

    @field_validator(
        "predecessor_implementation_commit",
        "predecessor_implementation_merge_commit",
        "predecessor_audit_commit",
        "predecessor_audit_merge_commit",
    )
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v182 manifest requires a full git commit")
        return value

    @field_validator("predecessor_result_root")
    @classmethod
    def validate_result_root(cls, value: str) -> str:
        expected = (
            "/data2/jiadongzhu/Agent/experiments/"
            "deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1"
        )
        path = PurePosixPath(value)
        if not path.is_absolute() or path.as_posix() != expected:
            raise ValueError("v182 predecessor result root changed")
        return value

    @field_validator("diagnostic_categories")
    @classmethod
    def validate_categories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != _DIAGNOSTIC_CATEGORIES:
            raise ValueError("v182 diagnostic categories changed")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v182 manifest content hash changed")
        return self


def load_v182_build_diagnostic_manifest(
    path: Path,
) -> OpenToolchainV182BuildDiagnosticManifest:
    """Load a bounded ordinary-file v182 diagnostic manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v182 manifest path is unsafe")
    try:
        return OpenToolchainV182BuildDiagnosticManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v182 manifest is invalid") from exc
