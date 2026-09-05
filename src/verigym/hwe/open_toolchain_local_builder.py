"""Contracts for the v178 local complete-builder open-toolchain qualification."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V178_IDENTITY = "deepseek-harness-hwe-v178-local-builder-qualification-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 1024 * 1024
_V176_FILES = frozenset(
    {
        "archive-receipt.json",
        "builder-diagnostic.json",
        "headroom.json",
        "materialization-progress.json",
        "reference-patch-compatibility.json",
        "zero-provider-report.json",
    }
)
_BUILDER_LAYERS = (
    "sha256:f2ec4de84f559f5c7be4233b589cdbdbb5507807e05621b77320edd55a1f2a0f",
    "sha256:d5680632276d406abb3910cbc6c6d32ffad3735db3a49b2f67d9bcd292620e01",
)
_BUILDER_BINARY_NAMES = frozenset({"autoconf", "bison", "flex", "g++", "make", "perl"})
_BUILDER_VERSION_NAMES = _BUILDER_BINARY_NAMES


class OpenToolchainV178LocalBuilderManifest(StrictModel):
    """One-use zero-provider successor bound to an existing complete builder image."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v178_local_builder_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v178-local-builder-qualification-v1"]
    upstream_identity: Literal["deepseek-harness-hwe-v172-open-toolchain-qualification-v1"]
    upstream_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
    ]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_identity: Literal[
        "deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1"
    ]
    predecessor_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v176_open_toolchain_repair_v1.json"
    ]
    predecessor_manifest_sha256: str
    predecessor_manifest_hash: str
    predecessor_result_root: str
    predecessor_result_tree_hash: str
    predecessor_result_file_sha256: dict[str, str]
    predecessor_report_hash: str
    predecessor_builder_diagnostic_hash: str
    predecessor_builder_diagnostic_category: Literal["offline_cache_miss"]
    predecessor_implementation_commit: str
    predecessor_implementation_merge_commit: str
    predecessor_qualification_main_run_id: Literal[33985343935]
    predecessor_audit_path: Literal[
        "docs/audits/2026-09-06_deepseek-harness-v177-v176-offline-cache-stop.md"
    ]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_audit_merge_commit: str
    predecessor_audit_post_merge_main_run_id: Literal[33986069560]
    predecessor_audit_post_merge_all_eight_classes_passed: Literal[True]
    dind_repository_name: Literal["docker"]
    dind_repository_digest: Literal[
        "sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca"
    ]
    repository_digest_parser: Literal["exact-single-repository-at-sha256-v1"]
    local_builder_acquisition: Literal["completed-data2-docker-archive-v1"]
    local_builder_origin: Literal["opensta-build-dependency-stage-v1"]
    local_builder_image_id: Literal[
        "sha256:427a3ced88ef7857f74020c7d36bfb2a772dd67e22ee3dc20b24dce06e667ba3"
    ]
    local_builder_provenance_tag: Literal["verigym/open-rtl-tools:v178-provenance-builder"]
    local_builder_created: Literal["2026-08-28T08:16:23.797798019Z"]
    local_builder_parent_image_id: Literal[
        "sha256:b284c9506fab13ae9bd94af562184978810b692f089901bdea8f21b074681576"
    ]
    local_builder_rootfs_layers: tuple[str, ...]
    local_builder_history_format: Literal["docker-json-created-by-lines-v1"]
    local_builder_history_sha256: str
    local_builder_history_bytes: Literal[848]
    local_builder_history_lines: Literal[5]
    local_builder_archive_path: Literal[
        "/data2/jiadongzhu/Agent/datasets/tools/open-builder/v178/verilator-build-deps.tar"
    ]
    local_builder_archive_sha256: str
    local_builder_archive_bytes: Literal[519838720]
    local_builder_archive_sidecar_path: Literal[
        "/data2/jiadongzhu/Agent/datasets/tools/open-builder/v178/verilator-build-deps.tar.sha256"
    ]
    local_builder_archive_sidecar_sha256: str
    local_builder_archive_config: Literal[
        "427a3ced88ef7857f74020c7d36bfb2a772dd67e22ee3dc20b24dce06e667ba3.json"
    ]
    local_builder_archive_layers: tuple[
        Literal["e855c081334e51c88c77ad82bf2c8e32efaccd8683f2c5c6c2a8cf14855767db/layer.tar"],
        Literal["bd8b0481defffbd73d6471c6466028fd1dd9b669f0b836e4f3813601fb0098a7/layer.tar"],
    ]
    local_builder_package_inventory_format: Literal["dpkg-query-W-c-locale-v1"]
    local_builder_package_inventory_sha256: str
    local_builder_package_inventory_bytes: Literal[4803]
    local_builder_package_inventory_lines: Literal[189]
    local_builder_required_binary_sha256: dict[str, str]
    local_builder_required_versions: dict[str, str]
    generic_builder_dockerfile_executed: Literal[False]
    builder_tag: Literal["verigym/open-rtl-tools:v178-builder"]
    builder_probe_max_bytes: Literal[65536]
    final_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile.v178"]
    final_dockerfile_sha256: str
    final_image_tag: Literal["verigym/open-rtl-tools:hwe-v178-pr1816"]
    dind_data_volume: Literal["verigym-deepseek-harness-v178-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v178-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v178/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v178/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v178-local-builder-qualification-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v178-local-builder"
    ]
    outer_dind_network: Literal["none"]
    local_builder_probe_network: Literal["none"]
    build_network: Literal["none"]
    agent_command_network: Literal["none"]
    official_verifier_network: Literal["none"]
    retained_dind_reopen_budget: Literal[1]
    provider_clients_available: Literal[False]
    provider_calls: Literal[0]
    registry_access_allowed: Literal[False]
    download_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    local_runtime_allowed: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    requires_independent_v179_audit: Literal[True]
    v180_canary_authorized: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_manifest_sha256",
        "predecessor_manifest_hash",
        "predecessor_result_tree_hash",
        "predecessor_report_hash",
        "predecessor_builder_diagnostic_hash",
        "predecessor_audit_sha256",
        "local_builder_history_sha256",
        "local_builder_archive_sha256",
        "local_builder_archive_sidecar_sha256",
        "local_builder_package_inventory_sha256",
        "final_dockerfile_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v178 local-builder manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_result_file_sha256")
    @classmethod
    def validate_result_files(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _V176_FILES or any(
            _SHA256.fullmatch(item) is None for item in value.values()
        ):
            raise ValueError("v178 predecessor result file inventory changed")
        return value

    @field_validator("local_builder_rootfs_layers")
    @classmethod
    def validate_builder_layers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != _BUILDER_LAYERS:
            raise ValueError("v178 local builder layer inventory changed")
        return value

    @field_validator("local_builder_required_binary_sha256")
    @classmethod
    def validate_builder_binaries(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _BUILDER_BINARY_NAMES or any(
            _SHA256.fullmatch(item) is None for item in value.values()
        ):
            raise ValueError("v178 local builder binary inventory changed")
        return value

    @field_validator("local_builder_required_versions")
    @classmethod
    def validate_builder_versions(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _BUILDER_VERSION_NAMES or any(not item for item in value.values()):
            raise ValueError("v178 local builder version inventory changed")
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
            raise ValueError("v178 local-builder manifest requires a full git commit")
        return value

    @field_validator("predecessor_result_root")
    @classmethod
    def validate_result_root(cls, value: str) -> str:
        expected = (
            "/data2/jiadongzhu/Agent/experiments/"
            "deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1"
        )
        path = PurePosixPath(value)
        if not path.is_absolute() or path.as_posix() != expected:
            raise ValueError("v178 predecessor result root changed")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v178 local-builder manifest content hash changed")
        return self


def load_v178_local_builder_manifest(path: Path) -> OpenToolchainV178LocalBuilderManifest:
    """Load a bounded ordinary-file v178 local-builder manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v178 local-builder manifest path is unsafe")
    try:
        return OpenToolchainV178LocalBuilderManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v178 local-builder manifest is invalid") from exc
