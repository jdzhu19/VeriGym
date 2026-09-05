"""Contracts for the v184 task-free missing-command disambiguation."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V184_IDENTITY = "deepseek-harness-hwe-v184-missing-command-disambiguation-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_COMMAND = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9+_.-]*$")
_MAX_JSON_BYTES = 1024 * 1024
_V182_FILES = frozenset(
    {
        "build-diagnostic.json",
        "cleanup.json",
        "dind-runtime.json",
        "headroom.json",
        "local-builder-archive.json",
        "local-builder-binding.json",
        "materialization-progress.json",
        "zero-provider-report.json",
    }
)
_COMMAND_ALLOWLIST = (
    "ar",
    "autoconf",
    "automake",
    "awk",
    "bison",
    "c++",
    "cc",
    "cd",
    "chmod",
    "chown",
    "cmake",
    "command",
    "flex",
    "g++",
    "gcc",
    "grep",
    "help2man",
    "install",
    "ln",
    "m4",
    "make",
    "perl",
    "pkg-config",
    "pod2man",
    "printf",
    "python3",
    "ranlib",
    "rm",
    "sed",
    "sha256sum",
    "tail",
    "tar",
    "test",
    "verilator",
    "verilator_bin",
)
_DOCKERFILE_INJECTED_COMMANDS = ("python3",)
_BUILDER_PREREQUISITES = tuple(
    item for item in _COMMAND_ALLOWLIST[:-2] if item not in _DOCKERFILE_INJECTED_COMMANDS
)
_GENERATED_COMMANDS = _COMMAND_ALLOWLIST[-2:]
_RESULT_CATEGORIES = (
    "success",
    "sensitive_output",
    "output_overflow",
    "timeout",
    "storage_exhausted",
    "compiler_killed",
    "missing_make_target",
    "missing_builder_prerequisite",
    "generated_binary_absent_after_prior_build_failure",
    "allowlisted_command_present_but_not_found",
    "dockerfile_injected_command_absent",
    "unknown_missing_executable",
    "multiple_missing_executables",
    "no_missing_executable_marker",
    "controller_error",
)


class OpenToolchainV184MissingCommandManifest(StrictModel):
    """Immutable one-use manifest for the task-free v184 disambiguation."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v184_missing_command_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v184-missing-command-disambiguation-v1"]
    predecessor_identity: Literal["deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1"]
    predecessor_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json"
    ]
    predecessor_manifest_sha256: str
    predecessor_manifest_hash: str
    predecessor_result_root: str
    predecessor_result_tree_hash: str
    predecessor_result_file_sha256: dict[str, str]
    predecessor_report_hash: str
    predecessor_diagnostic_hash: str
    predecessor_diagnostic_category: Literal["missing_executable"]
    predecessor_implementation_commit: str
    predecessor_implementation_merge_commit: str
    predecessor_post_merge_main_run_id: Literal[33994458259]
    predecessor_audit_path: Literal["docs/audits/2026-09-06_deepseek-harness-v183-v182-result.md"]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_audit_merge_commit: str
    predecessor_audit_post_merge_main_run_id: Literal[33995979993]
    predecessor_audit_post_merge_all_eight_classes_passed: Literal[True]
    inherited_runner_path: Literal[
        "scripts/materialize_hwe_deepseek_harness_v182_bounded_open_build.py"
    ]
    inherited_runner_sha256: str
    inherited_contract_path: Literal["src/verigym/hwe/open_toolchain_build_diagnostic.py"]
    inherited_contract_sha256: str
    bounded_process_runner_path: Literal[
        "scripts/materialize_hwe_deepseek_harness_v176_open_toolchain_repair.py"
    ]
    bounded_process_runner_sha256: str
    exact_input_binding: Literal["exact-v182-manifest-derived-v1"]
    command_allowlist: tuple[str, ...]
    builder_prerequisite_commands: tuple[str, ...]
    generated_commands: tuple[str, ...]
    dockerfile_injected_commands: tuple[str, ...]
    result_categories: tuple[str, ...]
    final_image_tag: Literal["verigym/open-rtl-tools:hwe-v184-missing-command-disambiguation"]
    dind_data_volume: Literal["verigym-deepseek-harness-v184-missing-command-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v184-missing-command-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v184/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v184/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v184-missing-command-disambiguation-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v184-missing-command-disambiguation"
    ]
    build_timeout_seconds: Literal[3600]
    build_output_max_bytes: Literal[16777216]
    command_probe_timeout_seconds: Literal[120]
    command_probe_output_max_bytes: Literal[4096]
    cleanup_timeout_seconds: Literal[120]
    cleanup_output_max_bytes: Literal[1048576]
    build_network: Literal["none"]
    command_probe_network: Literal["none"]
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
    repair_authorized: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    requires_independent_v185_audit: Literal[True]
    manifest_hash: str

    @field_validator(
        "predecessor_manifest_sha256",
        "predecessor_manifest_hash",
        "predecessor_result_tree_hash",
        "predecessor_report_hash",
        "predecessor_diagnostic_hash",
        "predecessor_audit_sha256",
        "inherited_runner_sha256",
        "inherited_contract_sha256",
        "bounded_process_runner_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v184 manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_result_file_sha256")
    @classmethod
    def validate_result_files(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _V182_FILES or any(
            _SHA256.fullmatch(digest) is None for digest in value.values()
        ):
            raise ValueError("v184 predecessor evidence inventory changed")
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
            raise ValueError("v184 manifest requires a full git commit")
        return value

    @field_validator("predecessor_result_root")
    @classmethod
    def validate_result_root(cls, value: str) -> str:
        expected = (
            "/data2/jiadongzhu/Agent/experiments/"
            "deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1"
        )
        path = PurePosixPath(value)
        if not path.is_absolute() or path.as_posix() != expected:
            raise ValueError("v184 predecessor result root changed")
        return value

    @field_validator(
        "command_allowlist",
        "builder_prerequisite_commands",
        "generated_commands",
        "dockerfile_injected_commands",
    )
    @classmethod
    def validate_commands(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(_COMMAND.fullmatch(item) is None for item in value):
            raise ValueError("v184 command enum is invalid")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (
            self.command_allowlist != _COMMAND_ALLOWLIST
            or self.builder_prerequisite_commands != _BUILDER_PREREQUISITES
            or self.generated_commands != _GENERATED_COMMANDS
            or self.dockerfile_injected_commands != _DOCKERFILE_INJECTED_COMMANDS
            or self.result_categories != _RESULT_CATEGORIES
        ):
            raise ValueError("v184 fixed command or result enums changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v184 manifest content hash changed")
        return self


def load_v184_missing_command_manifest(
    path: Path,
) -> OpenToolchainV184MissingCommandManifest:
    """Load a bounded ordinary-file v184 disambiguation manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v184 manifest path is unsafe")
    try:
        return OpenToolchainV184MissingCommandManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v184 manifest is invalid") from exc
