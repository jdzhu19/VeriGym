"""Contracts for the v188 task-free git builder repair."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V188_IDENTITY = "deepseek-harness-hwe-v188-git-builder-repair-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 1024 * 1024
_V186_FILES = frozenset(
    {
        "cleanup.json",
        "command-dictionary-probe.json",
        "diagnostic-context.json",
        "dind-runtime.json",
        "headroom.json",
        "local-builder-archive.json",
        "local-builder-binding.json",
        "materialization-progress.json",
        "zero-provider-report.json",
    }
)
_PACKAGES = {
    "git-man_1%3a2.47.3-0+deb13u1_all.deb": (
        "git-man",
        "1:2.47.3-0+deb13u1",
        "all",
        2_204_692,
        "b58306b60e1dff920e1e18bc7e1e499f2ef75184190ab3d98657b165969bf7c9",
    ),
    "git_1%3a2.47.3-0+deb13u1_amd64.deb": (
        "git",
        "1:2.47.3-0+deb13u1",
        "amd64",
        8_861_572,
        "3e35662fd5c46add561703e54031a1d8ad9df45811927689f0a51122b13be722",
    ),
    "libcurl3t64-gnutls_8.14.1-2+deb13u4_amd64.deb": (
        "libcurl3t64-gnutls",
        "8.14.1-2+deb13u4",
        "amd64",
        384_336,
        "351bf3bb1c816c1d88900cbfe59dc79433f20fb962947d78313028a00f97c856",
    ),
    "liberror-perl_0.17030-1_all.deb": (
        "liberror-perl",
        "0.17030-1",
        "all",
        26_872,
        "06110a972bdc52f6c6d6615dddbe97f836c61d0e36c685ef4107c2eaa81f871f",
    ),
    "libngtcp2-16_1.11.0-1+deb13u1_amd64.deb": (
        "libngtcp2-16",
        "1.11.0-1+deb13u1",
        "amd64",
        131_904,
        "627eec81ebbd48c4e6091f5cd9dc5070b792b7075000eed60ab08c7daa961caf",
    ),
    "libngtcp2-crypto-gnutls8_1.11.0-1+deb13u1_amd64.deb": (
        "libngtcp2-crypto-gnutls8",
        "1.11.0-1+deb13u1",
        "amd64",
        29_524,
        "2a7f109c0c4db6a800e4661c5e5e34e1f1f83c8162482276183d1ada9da7c96c",
    ),
}
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
    "unknown_closed_dictionary_command",
    "multiple_closed_dictionary_commands",
    "mixed_diagnostic_contexts",
    "unscoped_colon_not_found",
    "no_command_context_marker",
    "builder_repair_failed",
    "builder_binding_failed",
    "security_scan_failed",
    "archive_export_failed",
    "controller_error",
)


class GitPackageInput(StrictModel):
    """One exact Debian package in the offline git closure."""

    file: str
    package: str
    version: str
    architecture: Literal["all", "amd64"]
    bytes: int
    sha256: str

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or len(path.parts) != 1 or value.endswith(".partial"):
            raise ValueError("v188 package filename is unsafe")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v188 package hash must be lowercase SHA-256")
        return value


class OpenToolchainV188GitBuilderRepairManifest(StrictModel):
    """Immutable one-use boundary for the minimal offline git repair."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v188_git_builder_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v188-git-builder-repair-v1"]
    predecessor_identity: Literal["deepseek-harness-hwe-v186-diagnostic-context-refinement-v1"]
    predecessor_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v186_diagnostic_context_refinement_v1.json"
    ]
    predecessor_manifest_sha256: str
    predecessor_manifest_hash: str
    predecessor_result_root: str
    predecessor_result_tree_hash: str
    predecessor_result_file_sha256: dict[str, str]
    predecessor_report_hash: str
    predecessor_diagnostic_hash: str
    predecessor_cleanup_hash: str
    predecessor_probe_hash: str
    predecessor_diagnostic_category: Literal["missing_builder_prerequisite"]
    predecessor_diagnostic_context: Literal["posix_sh_command_not_found"]
    predecessor_missing_command: Literal["git"]
    predecessor_source_commit: str
    predecessor_implementation_commit: str
    predecessor_implementation_merge_commit: str
    predecessor_post_merge_main_run_id: Literal[34000582990]
    predecessor_audit_path: Literal["docs/audits/2026-09-06_deepseek-harness-v187-v186-result.md"]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_audit_merge_commit: str
    predecessor_audit_post_merge_main_run_id: Literal[34002140333]
    predecessor_audit_post_merge_all_eight_classes_passed: Literal[True]
    inherited_runner_path: Literal[
        "scripts/materialize_hwe_deepseek_harness_v186_diagnostic_context.py"
    ]
    inherited_runner_sha256: str
    inherited_contract_path: Literal["src/verigym/hwe/open_toolchain_diagnostic_context.py"]
    inherited_contract_sha256: str
    exact_final_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile.v180"]
    exact_final_dockerfile_sha256: str
    builder_repair_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile.v188-builder"]
    builder_repair_dockerfile_sha256: str
    base_builder_image_id: str
    accepted_open_tools_image_id: str
    official_verifier_image: str
    agent_toolchain_id: Literal["verigym-open-rtl-tools-v1"]
    git_package_archive_path: str
    git_package_archive_sha256: str
    git_package_archive_bytes: Literal[11653120]
    git_package_archive_sidecar_path: str
    git_package_archive_sidecar_sha256: str
    git_package_manifest_name: Literal["git-package-closure.json"]
    git_package_manifest_sha256: str
    git_package_manifest_hash: str
    git_binary_path: Literal["/usr/bin/git"]
    git_binary_sha256: str
    git_version: Literal["2.47.3"]
    git_debian_version: Literal["1:2.47.3-0+deb13u1"]
    git_package_payload_file_count: Literal[741]
    git_package_payload_inventory_sha256: str
    git_packages: tuple[GitPackageInput, ...]
    package_acquisition_network: Literal["verigym-hwe-net"]
    package_acquisition_route_interface: Literal["enp33s0f0"]
    package_acquisition_direct_non_vpn: Literal[True]
    package_acquisition_daemon_proxy_absent: Literal[True]
    package_acquisition_host_proxy_not_forwarded: Literal[True]
    package_acquisition_download_command_count: Literal[1]
    package_acquisition_complete: Literal[True]
    derived_builder_tag: Literal["verigym/open-rtl-tools:v188-builder"]
    final_builder_tag: Literal["verigym/open-rtl-tools:v180-builder"]
    final_image_tag: Literal["verigym/open-rtl-tools:hwe-v188-git-repair"]
    final_image_archive_path: str
    final_image_archive_sidecar_path: str
    final_image_archive_max_bytes: Literal[8589934592]
    scanner_profile_id: Literal["open-hwe-agent-toolchain-offline-v2"]
    dind_data_volume: Literal["verigym-deepseek-harness-v188-git-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v188-git-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v188/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v188/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v188-git-builder-repair-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v188-git-builder-repair"
    ]
    builder_build_timeout_seconds: Literal[600]
    builder_build_output_max_bytes: Literal[4194304]
    final_build_timeout_seconds: Literal[3600]
    final_build_output_max_bytes: Literal[16777216]
    probe_timeout_seconds: Literal[300]
    probe_output_max_bytes: Literal[1048576]
    cleanup_timeout_seconds: Literal[120]
    cleanup_output_max_bytes: Literal[1048576]
    control_root_min_available_bytes: Literal[4294967296]
    data2_min_available_bytes: Literal[53687091200]
    result_categories: tuple[str, ...]
    builder_build_network: Literal["none"]
    final_build_network: Literal["none"]
    probe_network: Literal["none"]
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
    minimal_git_repair_authorized: Literal[True]
    qualification_authorized: Literal[False]
    canary_authorized: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    requires_independent_v189_audit: Literal[True]
    manifest_hash: str

    @field_validator(
        "predecessor_manifest_sha256",
        "predecessor_manifest_hash",
        "predecessor_result_tree_hash",
        "predecessor_report_hash",
        "predecessor_diagnostic_hash",
        "predecessor_cleanup_hash",
        "predecessor_probe_hash",
        "predecessor_audit_sha256",
        "inherited_runner_sha256",
        "inherited_contract_sha256",
        "exact_final_dockerfile_sha256",
        "builder_repair_dockerfile_sha256",
        "git_package_archive_sha256",
        "git_package_archive_sidecar_sha256",
        "git_package_manifest_sha256",
        "git_package_manifest_hash",
        "git_binary_sha256",
        "git_package_payload_inventory_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v188 manifest requires lowercase SHA-256")
        return value

    @field_validator(
        "predecessor_source_commit",
        "predecessor_implementation_commit",
        "predecessor_implementation_merge_commit",
        "predecessor_audit_commit",
        "predecessor_audit_merge_commit",
    )
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v188 manifest requires a full git commit")
        return value

    @field_validator(
        "base_builder_image_id",
        "accepted_open_tools_image_id",
        "official_verifier_image",
    )
    @classmethod
    def validate_image_id(cls, value: str) -> str:
        if _IMAGE_ID.fullmatch(value) is None:
            raise ValueError("v188 manifest requires immutable image IDs")
        return value

    @field_validator("predecessor_result_file_sha256")
    @classmethod
    def validate_predecessor_files(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _V186_FILES or any(
            _SHA256.fullmatch(item) is None for item in value.values()
        ):
            raise ValueError("v188 predecessor evidence inventory changed")
        return value

    @field_validator(
        "predecessor_result_root",
        "git_package_archive_path",
        "git_package_archive_sidecar_path",
        "final_image_archive_path",
        "final_image_archive_sidecar_path",
    )
    @classmethod
    def validate_absolute_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or value.endswith(".partial"):
            raise ValueError("v188 manifest path is unsafe")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        observed_packages = {
            item.file: (
                item.package,
                item.version,
                item.architecture,
                item.bytes,
                item.sha256,
            )
            for item in self.git_packages
        }
        if (
            observed_packages != _PACKAGES
            or self.result_categories != _RESULT_CATEGORIES
            or self.predecessor_source_commit != self.predecessor_implementation_merge_commit
            or self.predecessor_missing_command != "git"
            or self.base_builder_image_id == self.accepted_open_tools_image_id
            or self.accepted_open_tools_image_id == self.official_verifier_image
            or Path(self.final_image_archive_path).with_suffix(".tar.sha256").as_posix()
            != self.final_image_archive_sidecar_path
        ):
            raise ValueError("v188 minimal repair identity changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v188 manifest content hash changed")
        return self


class OpenToolchainV188ImageLock(StrictModel):
    """Immutable lock for a successfully repaired, non-authoritative open-tool image."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_open_hwe_toolchain_image_lock_v2"]
    identity: Literal["deepseek-harness-hwe-v188-git-builder-repair-v1"]
    scanner_profile_id: Literal["open-hwe-agent-toolchain-offline-v2"]
    agent_toolchain_id: Literal["verigym-open-rtl-tools-v1"]
    image_id: str
    accepted_open_tools_image_id: str
    base_builder_image_id: str
    derived_builder_image_id: str
    official_verifier_image: str
    binary_sha256: dict[str, str]
    binary_versions: dict[str, str]
    build_network: Literal["none"]
    runtime_network: Literal["none"]
    effective_user: str
    read_only_root: Literal[True]
    cap_drop_all: Literal[True]
    no_new_privileges: Literal[True]
    mount_count: Literal[0]
    provider_credentials_present: Literal[False]
    codex_present: Literal[False]
    hwe_image_loaded: Literal[False]
    official_verifier_included: Literal[False]
    security_scan_passed: Literal[True]
    lock_hash: str

    @field_validator(
        "image_id",
        "accepted_open_tools_image_id",
        "base_builder_image_id",
        "derived_builder_image_id",
        "official_verifier_image",
    )
    @classmethod
    def validate_lock_image_id(cls, value: str) -> str:
        if _IMAGE_ID.fullmatch(value) is None:
            raise ValueError("v188 image lock requires immutable image IDs")
        return value

    @field_validator("binary_sha256")
    @classmethod
    def validate_binary_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        required = {
            "g++",
            "git",
            "iverilog",
            "make",
            "rg",
            "verilator",
            "verilator_bin",
            "vvp",
            "yosys",
        }
        if set(value) != required or any(
            _SHA256.fullmatch(item) is None for item in value.values()
        ):
            raise ValueError("v188 executable inventory changed")
        return value

    @model_validator(mode="after")
    def validate_lock(self) -> Self:
        if len(
            {
                self.image_id,
                self.accepted_open_tools_image_id,
                self.base_builder_image_id,
                self.derived_builder_image_id,
                self.official_verifier_image,
            }
        ) != 5 or self.effective_user in {"", "0", "0:0", "root"}:
            raise ValueError("v188 image role or non-root identity changed")
        identity = self.model_dump(mode="json", exclude={"lock_hash"})
        if content_hash(identity) != self.lock_hash:
            raise ValueError("v188 image lock content hash changed")
        return self


def load_v188_git_builder_repair_manifest(
    path: Path,
) -> OpenToolchainV188GitBuilderRepairManifest:
    """Load a bounded ordinary-file v188 manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v188 manifest path is unsafe")
    try:
        return OpenToolchainV188GitBuilderRepairManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v188 manifest is invalid") from exc
