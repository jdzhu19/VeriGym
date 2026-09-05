"""Contracts for the v180 outer-DinD writable-mount syntax repair."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V180_IDENTITY = "deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 1024 * 1024
_V178_FILES = frozenset(
    {
        "archive-receipt.json",
        "headroom.json",
        "local-builder-archive.json",
        "materialization-progress.json",
        "reference-patch-compatibility.json",
        "zero-provider-report.json",
    }
)


class OpenToolchainV180DindMountRepairManifest(StrictModel):
    """One-use zero-provider repair for the rejected v178 Docker mount syntax."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v180_dind_mount_repair_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1"]
    predecessor_identity: Literal["deepseek-harness-hwe-v178-local-builder-qualification-v1"]
    predecessor_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json"
    ]
    predecessor_manifest_sha256: str
    predecessor_manifest_hash: str
    predecessor_result_root: str
    predecessor_result_tree_hash: str
    predecessor_result_file_sha256: dict[str, str]
    predecessor_report_hash: str
    predecessor_stop_category: Literal["invalid_mount_write_flag"]
    predecessor_implementation_commit: str
    predecessor_implementation_merge_commit: str
    predecessor_qualification_main_run_id: Literal[33988896836]
    predecessor_audit_path: Literal[
        "docs/audits/2026-09-06_deepseek-harness-v179-v178-dind-start-stop.md"
    ]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_audit_merge_commit: str
    predecessor_audit_post_merge_main_run_id: Literal[33989708246]
    predecessor_audit_post_merge_all_eight_classes_passed: Literal[True]
    inherited_runner_path: Literal["scripts/materialize_hwe_deepseek_harness_v178_local_builder.py"]
    inherited_runner_sha256: str
    inherited_dind_runner_path: Literal[
        "scripts/materialize_hwe_deepseek_harness_v172_open_toolchain.py"
    ]
    inherited_dind_runner_sha256: str
    rejected_write_mount_syntax: Literal["type=bind,src=<path>,dst=<path>,rw"]
    repaired_write_mount_syntax: Literal["type=bind,src=<path>,dst=<path>"]
    writable_bind_mount_count: Literal[2]
    readonly_bind_mount_count: Literal[1]
    readonly_mount_syntax_unchanged: Literal[True]
    builder_tag: Literal["verigym/open-rtl-tools:v180-builder"]
    final_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile.v180"]
    final_dockerfile_sha256: str
    final_image_tag: Literal["verigym/open-rtl-tools:hwe-v180-pr1816"]
    dind_data_volume: Literal["verigym-deepseek-harness-v180-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v180-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v180/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v180/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v180-dind-mount-repair"
    ]
    outer_dind_network: Literal["none"]
    builder_probe_network: Literal["none"]
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
    requires_independent_v181_audit: Literal[True]
    v182_canary_authorized: Literal[False]
    manifest_hash: str

    @field_validator(
        "predecessor_manifest_sha256",
        "predecessor_manifest_hash",
        "predecessor_result_tree_hash",
        "predecessor_report_hash",
        "predecessor_audit_sha256",
        "inherited_runner_sha256",
        "inherited_dind_runner_sha256",
        "final_dockerfile_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v180 manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_result_file_sha256")
    @classmethod
    def validate_result_files(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != _V178_FILES or any(
            _SHA256.fullmatch(item) is None for item in value.values()
        ):
            raise ValueError("v180 predecessor result inventory changed")
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
            raise ValueError("v180 manifest requires a full git commit")
        return value

    @field_validator("predecessor_result_root")
    @classmethod
    def validate_result_root(cls, value: str) -> str:
        expected = (
            "/data2/jiadongzhu/Agent/experiments/"
            "deepseek-harness-hwe-v178-local-builder-qualification-v1"
        )
        path = PurePosixPath(value)
        if not path.is_absolute() or path.as_posix() != expected:
            raise ValueError("v180 predecessor result root changed")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v180 manifest content hash changed")
        return self


def load_v180_dind_mount_repair_manifest(
    path: Path,
) -> OpenToolchainV180DindMountRepairManifest:
    """Load a bounded ordinary-file v180 repair manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v180 manifest path is unsafe")
    try:
        return OpenToolchainV180DindMountRepairManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v180 manifest is invalid") from exc
