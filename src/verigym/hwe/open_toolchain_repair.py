"""Contracts for the v176 offline open-toolchain qualification repair."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V176_IDENTITY = "deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 1024 * 1024
_V174_FILES = frozenset(
    {
        "archive-receipt.json",
        "headroom.json",
        "materialization-progress.json",
        "reference-patch-compatibility.json",
        "zero-provider-report.json",
    }
)


class OpenToolchainV176RepairManifest(StrictModel):
    """One-use zero-provider repair bound to the complete v174/v175 result chain."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v176_open_toolchain_repair_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1"]
    upstream_identity: Literal["deepseek-harness-hwe-v172-open-toolchain-qualification-v1"]
    upstream_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
    ]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_identity: Literal[
        "deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1"
    ]
    predecessor_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v174_open_toolchain_repair_v1.json"
    ]
    predecessor_manifest_sha256: str
    predecessor_manifest_hash: str
    predecessor_result_root: str
    predecessor_result_tree_hash: str
    predecessor_result_file_sha256: dict[str, str]
    predecessor_report_hash: str
    predecessor_implementation_commit: str
    predecessor_implementation_merge_commit: str
    predecessor_qualification_main_run_id: Literal[33983004262]
    predecessor_audit_path: Literal[
        "docs/audits/2026-09-06_deepseek-harness-v175-v174-builder-stop.md"
    ]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_audit_merge_commit: str
    predecessor_audit_post_merge_main_run_id: Literal[33983817261]
    predecessor_audit_post_merge_all_eight_classes_passed: Literal[True]
    dind_repository_name: Literal["docker"]
    dind_repository_digest: Literal[
        "sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca"
    ]
    repository_digest_parser: Literal["exact-single-repository-at-sha256-v1"]
    builder_source_dockerfile: Literal["docker/open-rtl-tools/Dockerfile.v176"]
    builder_source_dockerfile_sha256: str
    builder_external_frontend_allowed: Literal[False]
    builder_target: Literal["iverilog-builder"]
    builder_tag: Literal["verigym/open-rtl-tools:v176-builder"]
    builder_diagnostic_max_bytes: Literal[1048576]
    final_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile.v176"]
    final_dockerfile_sha256: str
    final_image_tag: Literal["verigym/open-rtl-tools:hwe-v176-pr1816"]
    dind_data_volume: Literal["verigym-deepseek-harness-v176-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v176-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v176/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v176/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v176-open-toolchain-repair"
    ]
    outer_dind_network: Literal["none"]
    build_network: Literal["none"]
    agent_command_network: Literal["none"]
    official_verifier_network: Literal["none"]
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
    requires_independent_v177_audit: Literal[True]
    v178_canary_authorized: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_manifest_sha256",
        "predecessor_manifest_hash",
        "predecessor_result_tree_hash",
        "predecessor_report_hash",
        "predecessor_audit_sha256",
        "builder_source_dockerfile_sha256",
        "final_dockerfile_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v176 repair requires lowercase SHA-256")
        return value

    @field_validator("predecessor_result_file_sha256")
    @classmethod
    def validate_result_files(cls, value: dict[str, str]) -> dict[str, str]:
        invalid_hash = any(_SHA256.fullmatch(item) is None for item in value.values())
        if set(value) != _V174_FILES or invalid_hash:
            raise ValueError("v176 predecessor result file inventory changed")
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
            raise ValueError("v176 repair requires a full git commit")
        return value

    @field_validator("predecessor_result_root")
    @classmethod
    def validate_result_root(cls, value: str) -> str:
        path = PurePosixPath(value)
        expected = (
            "/data2/jiadongzhu/Agent/experiments/"
            "deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1"
        )
        if not path.is_absolute() or path.as_posix() != expected:
            raise ValueError("v176 predecessor result root changed")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v176 repair manifest content hash changed")
        return self


def load_v176_repair_manifest(path: Path) -> OpenToolchainV176RepairManifest:
    """Load a bounded ordinary-file v176 repair manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v176 repair manifest path is unsafe")
    try:
        return OpenToolchainV176RepairManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v176 repair manifest is invalid") from exc
