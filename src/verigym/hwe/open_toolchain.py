"""Fail-closed contracts for the offline open-HWE toolchain qualification."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import V69_OPEN_TOOL_TASK_ID, HweOfflineTaskLock
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V172_IDENTITY = "deepseek-harness-hwe-v172-open-toolchain-qualification-v1"
V172_AGENT_TOOLCHAIN_ID = "verigym-open-rtl-tools-v1"
V172_TASK_ID = V69_OPEN_TOOL_TASK_ID

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_MAX_JSON_BYTES = 4 * 1024 * 1024


class OpenToolchainQualificationManifest(StrictModel):
    """Reviewed one-use, zero-provider authorization for the PR-1816 comparison."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v172_open_toolchain_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v172-open-toolchain-qualification-v1"]
    task: HweOfflineTaskLock
    agent_toolchain_id: Literal["verigym-open-rtl-tools-v1"]
    official_verifier_image: str
    accepted_open_tools_tag: Literal["verigym/open-rtl-tools:iverilog12-yosys067"]
    accepted_open_tools_image_id: str
    builder_tag: Literal["verigym/open-rtl-tools:v172-builder"]
    builder_target: Literal["iverilog-builder"]
    builder_source_dockerfile: Literal["docker/open-rtl-tools/Dockerfile"]
    builder_source_dockerfile_sha256: str
    final_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile"]
    final_dockerfile_sha256: str
    verilator_release: Literal["v5.008"]
    verilator_archive_path: str
    verilator_archive_sha256: str
    verilator_tag_object: str
    verilator_commit: str
    iverilog_release: Literal["v12_0"]
    iverilog_commit: str
    yosys_release: Literal["v0.67"]
    yosys_commit: str
    ripgrep_release: Literal["15.2.0"]
    ripgrep_archive_path: str
    ripgrep_archive_sha256: str
    ripgrep_binary_sha256: str
    predecessor_audit_path: Literal["docs/audits/2026-09-06_deepseek-harness-v171-v170-result.md"]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_merge_commit: str
    predecessor_post_merge_main_run_id: int = Field(ge=1)
    predecessor_post_merge_all_eight_classes_passed: Literal[True]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v172-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v172-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v172/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v172/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v172-open-toolchain-qualification-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v172-open-toolchain"
    ]
    outer_dind_network: Literal["none"]
    build_network: Literal["none"]
    agent_command_network: Literal["none"]
    official_verifier_network: Literal["none"]
    host_docker_root_used_for_task_layers: Literal[False]
    retained_dind_reopen_budget: Literal[1]
    provider_clients_available: Literal[False]
    provider_calls: Literal[0]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    local_runtime_allowed: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    requires_independent_v173_audit: Literal[True]
    v174_canary_authorized: Literal[False]
    manifest_hash: str

    @field_validator(
        "builder_source_dockerfile_sha256",
        "final_dockerfile_sha256",
        "verilator_archive_sha256",
        "ripgrep_archive_sha256",
        "ripgrep_binary_sha256",
        "predecessor_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v172 requires lowercase SHA-256")
        return value

    @field_validator(
        "official_verifier_image",
        "accepted_open_tools_image_id",
        "dind_image_id",
        "dind_repository_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v172 requires an immutable sha256 image identity")
        return value

    @field_validator(
        "verilator_tag_object",
        "verilator_commit",
        "iverilog_commit",
        "yosys_commit",
        "predecessor_audit_commit",
        "predecessor_merge_commit",
    )
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v172 requires a full git object identity")
        return value

    @field_validator("verilator_archive_path", "ripgrep_archive_path")
    @classmethod
    def validate_data2_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not path.is_absolute()
            or not value.startswith("/data2/jiadongzhu/Agent/datasets/tools/")
            or value != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts[1:])
            or value.endswith(".partial")
        ):
            raise ValueError("v172 tool input must be a completed canonical /data2 path")
        return value

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            self.task.task_id != V172_TASK_ID
            or self.task.instance_id != "lowRISC/ibex:pr-1816"
            or self.task.pr_number != 1816
            or self.task.repository != "ibex"
            or self.task.official_verifier_image != self.official_verifier_image
            or self.agent_toolchain_id == str(self.task.agent_toolchain_id)
            or self.accepted_open_tools_image_id == self.official_verifier_image
        ):
            raise ValueError("v172 agent-toolchain and official-verifier binding changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v172 manifest content hash changed")
        return self


class OpenToolchainImageLock(StrictModel):
    """Immutable output identity for the non-authoritative open command image."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_open_hwe_toolchain_image_lock_v1"]
    identity: str
    agent_toolchain_id: Literal["verigym-open-rtl-tools-v1"]
    image_id: str
    accepted_open_tools_image_id: str
    builder_image_id: str
    official_verifier_image: str
    binary_sha256: dict[str, str]
    binary_versions: dict[str, str]
    build_network: Literal["none"]
    runtime_network: Literal["none"]
    effective_user: str
    read_only_root: Literal[True]
    cap_drop_all: Literal[True]
    no_new_privileges: Literal[True]
    single_workspace_mount: Literal[True]
    provider_credentials_present: Literal[False]
    codex_present: Literal[False]
    hwe_task_image_ancestor: Literal[False]
    official_verifier_included: Literal[False]
    security_scan_id: str
    security_check_count: int = Field(ge=24)
    security_scan_passed: Literal[True]
    lock_hash: str

    @field_validator("image_id", "accepted_open_tools_image_id", "builder_image_id")
    @classmethod
    def validate_image_id(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("open toolchain image lock requires immutable image IDs")
        return value

    @field_validator("official_verifier_image")
    @classmethod
    def validate_verifier_id(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("open toolchain image lock requires an official verifier ID")
        return value

    @field_validator("security_scan_id")
    @classmethod
    def validate_scan_id(cls, value: str) -> str:
        if _SAFE_ID.fullmatch(value) is None:
            raise ValueError("open toolchain image lock has an invalid scan ID")
        return value

    @field_validator("binary_sha256")
    @classmethod
    def validate_binary_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        required = {"verilator", "verilator_bin", "iverilog", "vvp", "yosys", "rg", "make", "g++"}
        if set(value) != required or any(
            _SHA256.fullmatch(item) is None for item in value.values()
        ):
            raise ValueError("open toolchain executable inventory changed")
        return value

    @model_validator(mode="after")
    def validate_lock(self) -> Self:
        if (
            self.image_id in {self.accepted_open_tools_image_id, self.official_verifier_image}
            or self.builder_image_id == self.official_verifier_image
            or self.effective_user in {"", "0", "0:0", "root"}
        ):
            raise ValueError("open toolchain role or non-root identity changed")
        identity = self.model_dump(mode="json", exclude={"lock_hash"})
        if content_hash(identity) != self.lock_hash:
            raise ValueError("open toolchain image lock content hash changed")
        return self


def load_open_toolchain_manifest(path: Path) -> OpenToolchainQualificationManifest:
    """Load a bounded ordinary-file v172 manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v172 manifest path is unsafe")
    try:
        return OpenToolchainQualificationManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v172 manifest is invalid") from exc


def load_open_toolchain_image_lock(path: Path) -> OpenToolchainImageLock:
    """Load a bounded ordinary-file open-toolchain image lock."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("open toolchain image lock path is unsafe")
    try:
        return OpenToolchainImageLock.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("open toolchain image lock is invalid") from exc
