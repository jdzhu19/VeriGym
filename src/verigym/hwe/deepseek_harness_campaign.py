"""Fail-closed contracts for multi-task DeepSeek Harness HWE campaigns."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V69_PRIMARY_TASK_IDS = (
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465",
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135",
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711",
)
V69_IBEX_FALLBACK_TASK_IDS = (
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-48",
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-293",
)
V69_CVA6_FALLBACK_TASK_IDS = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3042",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3137",
)
V69_OPEN_TOOL_TASK_ID = "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1816"
V71_MATRIX_TASK_IDS = V69_PRIMARY_TASK_IDS

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID = re.compile(
    r"^hwe-bench/repo-repair-v1/"
    r"(?P<org>[A-Za-z0-9_.-]+)__(?P<repo>[A-Za-z0-9_.-]+)__pr-(?P<pr>[1-9][0-9]*)$"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 512
_MAX_JSON_BYTES = 16 * 1024 * 1024

Disposition = Literal[
    "historical",
    "held_out",
    "authorized",
    "provider_consumed",
    "planned_primary",
    "zero_provider_fallback",
    "archive_incomplete_fallback",
    "alternative_toolchain_reserved",
]
Repository = Literal["ibex", "cva6"]
ProviderMarker = Literal["not_started", "started_valid", "invalid", "unreadable"]
AttemptOutcome = Literal[
    "passed",
    "ordinary_model_failure",
    "verifier_rejection",
    "no_effective_modification",
    "no_progress",
    "trajectory_structure_failure",
    "infrastructure_failure",
    "security_failure",
]


class HweTaskDisposition(StrictModel):
    """One immutable task-use fact considered before campaign materialization."""

    task_id: str
    disposition: Disposition
    provider_boundary_crossed: bool = False
    provider_consumed: bool = False

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        if _TASK_ID.fullmatch(value) is None:
            raise ValueError("HWE campaign ledger task ID is invalid")
        return value

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.provider_consumed and not self.provider_boundary_crossed:
            raise ValueError("a provider-consumed task must have crossed the provider boundary")
        if self.disposition == "provider_consumed" and not self.provider_consumed:
            raise ValueError("provider-consumed disposition requires consumed=true")
        if self.disposition in {
            "planned_primary",
            "zero_provider_fallback",
            "archive_incomplete_fallback",
            "alternative_toolchain_reserved",
        } and (self.provider_boundary_crossed or self.provider_consumed):
            raise ValueError("an available campaign task cannot have prior provider use")
        return self


class HweOfflineTaskLock(StrictModel):
    """Static public-data and completed-archive identity for one HWE task."""

    task_id: str
    instance_id: str
    repository: Repository
    pr_number: int = Field(ge=1)
    dataset_relpath: str
    dataset_sha256: str
    selected_row_sha256: str
    source_commit: str
    archive_relpath: str
    archive_sha256_relpath: str
    archive_sha256: str
    registry_digest_relpath: str
    registry_reference: str
    registry_manifest_digest: str
    image_config_digest: str
    archive_repository_tag: str
    official_verifier_image: str
    agent_toolchain_id: Literal["hwe-official-task-toolchain-v1"] = "hwe-official-task-toolchain-v1"

    @field_validator(
        "dataset_sha256",
        "selected_row_sha256",
        "archive_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("HWE offline task lock requires lowercase SHA-256")
        return value

    @field_validator(
        "registry_manifest_digest",
        "image_config_digest",
        "official_verifier_image",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("HWE offline task lock requires a sha256 digest")
        return value

    @field_validator("source_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("HWE offline task lock requires a full source commit")
        return value

    @field_validator(
        "dataset_relpath",
        "archive_relpath",
        "archive_sha256_relpath",
        "registry_digest_relpath",
    )
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or value != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
            or value.endswith(".partial")
        ):
            raise ValueError("HWE offline task paths must be canonical completed relative paths")
        return value

    @model_validator(mode="after")
    def bind_task(self) -> Self:
        matched = _TASK_ID.fullmatch(self.task_id)
        if matched is None:
            raise ValueError("HWE offline task ID is invalid")
        expected = {
            "ibex": ("lowRISC", "ibex"),
            "cva6": ("openhwgroup", "cva6"),
        }[self.repository]
        org, repo = expected
        if (
            matched.group("org") != org
            or matched.group("repo") != repo
            or int(matched.group("pr")) != self.pr_number
            or self.instance_id != f"{org}/{repo}:pr-{self.pr_number}"
        ):
            raise ValueError("HWE task, repository, PR, and instance identities differ")
        repository_slug = {"ibex": "lowrisc_m_ibex", "cva6": "openhwgroup_m_cva6"}[self.repository]
        expected_reference = f"ghcr.io/pku-liang/{repository_slug}:pr-{self.pr_number}"
        expected_archive_tag = f"ghcr.io/pku-liang/{repository_slug}:i-was-a-digest"
        expected_archive = f"docker-tar-archives/{repository_slug}/pr-{self.pr_number}.tar"
        if (
            self.registry_reference != expected_reference
            or self.archive_repository_tag != expected_archive_tag
            or self.archive_relpath != expected_archive
            or self.archive_sha256_relpath != f"{expected_archive}.sha256"
            or self.registry_digest_relpath
            != f"digest-locks/{repository_slug}/pr-{self.pr_number}.digest"
            or self.official_verifier_image != self.image_config_digest
        ):
            raise ValueError("HWE offline archive, repository, or verifier binding differs")
        return self


class DeepSeekHarnessV69Manifest(StrictModel):
    """Reviewed zero-provider materialization manifest for the v69 five-task matrix."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v69_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v69-multitask-zero-provider-v1"]
    primary_tasks: list[HweOfflineTaskLock] = Field(min_length=5, max_length=5)
    ibex_fallback_order: list[str] = Field(min_length=2, max_length=2)
    cva6_fallback_order: list[str] = Field(min_length=2, max_length=2)
    alternative_toolchain_task_id: str
    task_ledger: list[HweTaskDisposition] = Field(min_length=1, max_length=256)
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    atomic_provider_contract: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator("manifest_hash")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v69 manifest hash must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_campaign(self) -> Self:
        primary_ids = tuple(item.task_id for item in self.primary_tasks)
        if primary_ids != V69_PRIMARY_TASK_IDS:
            raise ValueError("v69 primary task order changed")
        if tuple(self.ibex_fallback_order) != V69_IBEX_FALLBACK_TASK_IDS:
            raise ValueError("v69 Ibex fallback order changed")
        if tuple(self.cva6_fallback_order) != V69_CVA6_FALLBACK_TASK_IDS:
            raise ValueError("v69 CVA6 fallback order changed")
        if self.alternative_toolchain_task_id != V69_OPEN_TOOL_TASK_ID:
            raise ValueError("v69 alternative-toolchain reservation changed")
        entries = {entry.task_id: entry for entry in self.task_ledger}
        if len(entries) != len(self.task_ledger):
            raise ValueError("v69 task ledger contains duplicate tasks")
        expected_available = {
            **{task_id: "planned_primary" for task_id in V69_PRIMARY_TASK_IDS},
            **{task_id: "zero_provider_fallback" for task_id in V69_IBEX_FALLBACK_TASK_IDS},
            **{task_id: "archive_incomplete_fallback" for task_id in V69_CVA6_FALLBACK_TASK_IDS},
            V69_OPEN_TOOL_TASK_ID: "alternative_toolchain_reserved",
        }
        for task_id, disposition in expected_available.items():
            entry = entries.get(task_id)
            if entry is None or entry.disposition != disposition:
                raise ValueError("v69 task ledger does not bind the planned task dispositions")
        forbidden = {
            task_id
            for task_id, entry in entries.items()
            if entry.disposition
            in {
                "historical",
                "held_out",
                "authorized",
                "provider_consumed",
            }
            or entry.provider_boundary_crossed
            or entry.provider_consumed
        }
        if forbidden.intersection(expected_available):
            raise ValueError("v69 schedule reuses an excluded task")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v69 manifest content hash changed")
        return self


class DeepSeekHarnessV71DindSuccessorManifest(StrictModel):
    """Frozen successor authorization for v69 materialization on isolated DinD storage."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v71_dind_successor_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v71-dind-zero-provider-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_identity: Literal["deepseek-harness-hwe-v69-multitask-zero-provider-v1"]
    predecessor_report_sha256: str
    predecessor_report_hash: str
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v71-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v71-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/socket"]
    outer_dind_network: Literal["none"]
    host_docker_root_used_for_task_layers: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    atomic_provider_contract: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_report_sha256",
        "predecessor_report_hash",
        "predecessor_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v71 successor manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v71 successor manifest requires a full audit commit")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v71 successor manifest requires immutable DinD digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v71 successor manifest content hash changed")
        return self


class DeepSeekHarnessV73DindSuccessorManifest(StrictModel):
    """Frozen clean-room successor after the audited v71 DinD infrastructure stop."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v73_dind_successor_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v73-dind-zero-provider-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_identity: Literal["deepseek-harness-hwe-v71-dind-zero-provider-successor-v1"]
    predecessor_report_sha256: str
    predecessor_report_hash: str
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    retired_dind_data_volume: Literal["verigym-deepseek-harness-v71-dind-data"]
    retired_dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data"]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v73-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v73-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/socket"]
    command_diagnostic_max_bytes: Literal[33554432]
    socket_cleanup_strategy: Literal["networkless-readonly-fixed-path-v1"]
    outer_dind_network: Literal["none"]
    host_docker_root_used_for_task_layers: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    atomic_provider_contract: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_report_sha256",
        "predecessor_report_hash",
        "predecessor_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v73 successor manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v73 successor manifest requires a full audit commit")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v73 successor manifest requires immutable DinD digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v73 successor manifest content hash changed")
        return self


class DeepSeekHarnessV75DindSuccessorManifest(StrictModel):
    """Frozen clean-room successor after the audited v73 scanner-path stop."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v75_dind_successor_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v75-dind-zero-provider-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_identity: Literal["deepseek-harness-hwe-v73-dind-zero-provider-successor-v1"]
    predecessor_report_sha256: str
    predecessor_report_hash: str
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    retired_dind_data_volume: Literal["verigym-deepseek-harness-v73-dind-data"]
    retired_dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/data"]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v75-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v75-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/socket"]
    scanner_workspace_policy: Literal["successor-output-root-only-v1"]
    scanner_workspace_relative_path: Literal["scan-workspaces"]
    command_diagnostic_max_bytes: Literal[33554432]
    socket_cleanup_strategy: Literal["networkless-readonly-fixed-path-v2"]
    outer_dind_network: Literal["none"]
    host_docker_root_used_for_task_layers: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    atomic_provider_contract: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_report_sha256",
        "predecessor_report_hash",
        "predecessor_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v75 successor manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v75 successor manifest requires a full audit commit")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v75 successor manifest requires immutable DinD digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v75 successor manifest content hash changed")
        return self


class DeepSeekHarnessV77DindSuccessorManifest(StrictModel):
    """Fresh successor after the audited v75 CVA6 source-profile safety stop."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v77_dind_successor_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v77-dind-zero-provider-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_identity: Literal["deepseek-harness-hwe-v75-dind-zero-provider-successor-v1"]
    predecessor_report_sha256: str
    predecessor_report_hash: str
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    retired_dind_data_volume: Literal["verigym-deepseek-harness-v75-dind-data"]
    retired_dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/data"]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v77-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v77-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/socket"]
    scanner_workspace_policy: Literal["successor-output-root-only-v1"]
    scanner_workspace_relative_path: Literal["scan-workspaces"]
    source_profile_repair: Literal["cva6-task-image-tool-bridge-exclusion-v1"]
    cva6_repository_profile_id: Literal["hwe-openhwgroup-cva6-v1"]
    cva6_repository_profile_hash: str
    cva6_workspace_tool_bridge_exclusion: Literal[".hwe_tools"]
    escaping_symlink_policy: Literal["reject-unlisted-v1"]
    command_diagnostic_max_bytes: Literal[33554432]
    socket_cleanup_strategy: Literal["networkless-readonly-fixed-path-v2"]
    outer_dind_network: Literal["none"]
    host_docker_root_used_for_task_layers: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    atomic_provider_contract: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_report_sha256",
        "predecessor_report_hash",
        "predecessor_audit_sha256",
        "cva6_repository_profile_hash",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v77 successor manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v77 successor manifest requires a full audit commit")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v77 successor manifest requires immutable DinD digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v77 successor manifest content hash changed")
        return self


class DeepSeekHarnessV79DindSuccessorManifest(StrictModel):
    """Fresh successor after the audited v77 runtime-baseline binding stop."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v79_dind_successor_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v79-dind-zero-provider-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_identity: Literal["deepseek-harness-hwe-v77-dind-zero-provider-successor-v1"]
    predecessor_report_sha256: str
    predecessor_report_hash: str
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_prepared_source_image_lock_sha256: str
    predecessor_pr_2017_source_hash: str
    predecessor_pr_2017_task_bundle_hash: str
    pr_2711_offline_archive_receipt_hash: str
    retired_dind_data_volume: Literal["verigym-deepseek-harness-v77-dind-data"]
    retired_dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/data"]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v79-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v79-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v79/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v79/socket"]
    scanner_workspace_policy: Literal["successor-output-root-only-v1"]
    scanner_workspace_relative_path: Literal["scan-workspaces"]
    source_profile_repair: Literal["cva6-task-image-tool-bridge-exclusion-v1"]
    cva6_repository_profile_id: Literal["hwe-openhwgroup-cva6-v1"]
    cva6_repository_profile_hash: str
    cva6_workspace_tool_bridge_exclusion: Literal[".hwe_tools"]
    escaping_symlink_policy: Literal["reject-unlisted-v1"]
    runtime_baseline_repair: Literal["pr-2017-digest-locked-runtime-marker-v1"]
    runtime_baseline_policy: Literal["exact-task-override-otherwise-dataset-base-v1"]
    runtime_base_commit_overrides: dict[str, str]
    tasks_without_runtime_override_match_dataset_base: Literal[True]
    command_diagnostic_max_bytes: Literal[33554432]
    socket_cleanup_strategy: Literal["networkless-readonly-fixed-path-v2"]
    outer_dind_network: Literal["none"]
    host_docker_root_used_for_task_layers: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    atomic_provider_contract: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_report_sha256",
        "predecessor_report_hash",
        "predecessor_audit_sha256",
        "predecessor_prepared_source_image_lock_sha256",
        "predecessor_pr_2017_source_hash",
        "predecessor_pr_2017_task_bundle_hash",
        "pr_2711_offline_archive_receipt_hash",
        "cva6_repository_profile_hash",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v79 successor manifest requires lowercase SHA-256")
        return value

    @field_validator("predecessor_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v79 successor manifest requires a full audit commit")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v79 successor manifest requires immutable DinD digests")
        return value

    @field_validator("runtime_base_commit_overrides")
    @classmethod
    def exact_runtime_override(cls, value: dict[str, str]) -> dict[str, str]:
        expected = {
            "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017": (
                "d87707a81fe8926dda2deff844797a491811983a"
            )
        }
        if value != expected:
            raise ValueError("v79 successor manifest requires the exact PR-2017 runtime override")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v79 successor manifest content hash changed")
        return self


class DeepSeekHarnessV81ExecutionScaffoldManifest(StrictModel):
    """Credential-free execution scaffold for the audited five-task provider matrix."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v81_execution_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v81-provider-execution-scaffold-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    v79_provider_contract_sha256: str
    v79_provider_contract_hash: str
    v80_audit_sha256: str
    v80_audit_commit: str
    v80_post_merge_main_run_id: Literal[33735930859]
    v80_post_merge_main_all_eight_classes_passed: Literal[True]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v81-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v81-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v81/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v81/socket"]
    scaffold_outer_network: Literal["none"]
    provider_outer_network: Literal["verigym-hwe-net"]
    provider_inner_network: Literal["verigym-hwe-net"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_transfer: Literal["content_free_read_only_outer_image_pipe_v1"]
    provider_successor_identity: Literal["deepseek-harness-hwe-v83-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    host_docker_root_used_for_task_layers: Literal[False]
    v79_data_volume_reused: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "v79_provider_contract_sha256",
        "v79_provider_contract_hash",
        "v80_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v81 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v80_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v81 scaffold manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v81 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v81 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV83ExecutionScaffoldManifest(StrictModel):
    """Fresh scaffold successor after the audited v81 controller-tag stop."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v83_execution_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v83-controller-tag-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    v79_provider_contract_sha256: str
    v79_provider_contract_hash: str
    v81_manifest_sha256: str
    v81_manifest_hash: str
    v81_report_sha256: str
    v81_report_hash: str
    v82_audit_sha256: str
    v82_audit_commit: str
    v82_post_merge_main_run_id: Literal[33742071653]
    v82_post_merge_main_all_eight_classes_passed: Literal[True]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v83-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v83-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/socket"]
    scaffold_outer_network: Literal["none"]
    provider_outer_network: Literal["verigym-hwe-net"]
    provider_inner_network: Literal["verigym-hwe-net"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_transfer: Literal["content_free_read_only_outer_canonical_tag_pipe_v2"]
    provider_successor_identity: Literal["deepseek-harness-hwe-v85-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    host_docker_root_used_for_task_layers: Literal[False]
    v79_data_volume_reused: Literal[False]
    v81_data_volume_reused: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "v79_provider_contract_sha256",
        "v79_provider_contract_hash",
        "v81_manifest_sha256",
        "v81_manifest_hash",
        "v81_report_sha256",
        "v81_report_hash",
        "v82_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v83 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v82_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v83 scaffold manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v83 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v83 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV85TaskBinding(StrictModel):
    """One immutable task/source/image binding in the official v85 matrix."""

    task_id: str
    repository: Repository
    pr_number: int = Field(ge=1)
    seed: Literal[502]
    sample_index: Literal[18]
    task_hash: str
    source_hash: str
    task_receipt_hash: str
    prepared_source_image_lock_sha256: str
    command_image_lock_file_sha256: str
    command_image_lock_hash: str
    command_image: str
    security_scan_file_sha256: str
    security_scan_id: str
    official_verifier_image: str
    agent_toolchain_id: Literal["hwe-official-task-toolchain-v1"]
    toolchain_profile_id: Literal[
        "ibex-verilator-system-container-native-v1",
        "cva6-verilator-5.008-container-native-v2",
    ]

    @field_validator(
        "task_hash",
        "source_hash",
        "task_receipt_hash",
        "prepared_source_image_lock_sha256",
        "command_image_lock_file_sha256",
        "command_image_lock_hash",
        "security_scan_file_sha256",
        "security_scan_id",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v85 task binding requires lowercase SHA-256")
        return value

    @field_validator("command_image", "official_verifier_image")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v85 task binding requires immutable image IDs")
        return value

    @model_validator(mode="after")
    def bind_task(self) -> Self:
        matched = _TASK_ID.fullmatch(self.task_id)
        expected_repository = "ibex" if "lowRISC__ibex" in self.task_id else "cva6"
        expected_profile = (
            "ibex-verilator-system-container-native-v1"
            if self.repository == "ibex"
            else "cva6-verilator-5.008-container-native-v2"
        )
        if (
            matched is None
            or self.repository != expected_repository
            or int(matched.group("pr")) != self.pr_number
            or self.toolchain_profile_id != expected_profile
        ):
            raise ValueError("v85 task, repository, PR, or toolchain binding differs")
        return self


class DeepSeekHarnessV85OfficialMatrixManifest(StrictModel):
    """One-use official five-task provider matrix authorized by the v84 audit."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v85_official_matrix_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v85-official-matrix-v1"]
    v83_manifest_sha256: str
    v83_manifest_hash: str
    v83_report_sha256: str
    v83_report_hash: str
    v83_contract_sha256: str
    v83_contract_hash: str
    v83_inventory_sha256: str
    v83_inventory_hash: str
    v83_controller_receipt_sha256: str
    v83_controller_receipt_hash: str
    v83_runtime_receipt_sha256: str
    v83_runtime_receipt_hash: str
    v83_cleanup_receipt_sha256: str
    v83_cleanup_receipt_hash: str
    v84_audit_sha256: str
    v84_audit_commit: str
    v84_post_merge_main_run_id: Literal[33747143064]
    v84_post_merge_main_all_eight_classes_passed: Literal[True]
    schedule: list[DeepSeekHarnessV85TaskBinding] = Field(min_length=5, max_length=5)
    provider: Literal["deepseek-official"]
    model: Literal["deepseek-v4-flash"]
    harness_version: Literal["0.1.1-rc.2"]
    integration_version: Literal["0.5.0"]
    harness_revision: Literal["b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"]
    seed: Literal[502]
    sample_index: Literal[18]
    max_provider_calls_per_task: Literal[64]
    max_provider_tokens_per_task: Literal[1000000]
    max_context_tokens: Literal[65536]
    max_output_tokens: Literal[2048]
    temperature: Literal[0]
    provider_request_retries: Literal[0]
    whole_episode_retries: Literal[0]
    ordinary_tool_choice: Literal["auto"]
    public_rationale_allowed: Literal[True]
    sibling_calls_allowed: Literal[True]
    provider_hidden_thinking: Literal["disabled"]
    foreign_tools_rejected: Literal[True]
    illegal_paths_rejected: Literal[True]
    unpaired_observations_rejected: Literal[True]
    decision_only_loss_mask: Literal[True]
    exact_tokenizer_hash: str
    base_model_snapshot_hash: str
    base_model_lock_sha256: str
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v83-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v83-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/socket"]
    provider_outer_network: Literal["verigym-hwe-net"]
    provider_inner_network: Literal["verigym-hwe-net"]
    task_network: Literal["none"]
    verifier_network: Literal["none"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_image_provenance: Literal["audited_v83_offline_canonical_tag_load_v1"]
    v83_data_volume_reopen_budget: Literal[1]
    v83_data_volume_reopen_count_before: Literal[0]
    atomic_progress: Literal[True]
    stop_on_infrastructure_or_security_failure: Literal[True]
    continue_after_ordinary_model_or_verifier_failure: Literal[True]
    consecutive_no_progress_stop_limit: Literal[2]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v83_manifest_sha256",
        "v83_manifest_hash",
        "v83_report_sha256",
        "v83_report_hash",
        "v83_contract_sha256",
        "v83_contract_hash",
        "v83_inventory_sha256",
        "v83_inventory_hash",
        "v83_controller_receipt_sha256",
        "v83_controller_receipt_hash",
        "v83_runtime_receipt_sha256",
        "v83_runtime_receipt_hash",
        "v83_cleanup_receipt_sha256",
        "v83_cleanup_receipt_hash",
        "v84_audit_sha256",
        "exact_tokenizer_hash",
        "base_model_snapshot_hash",
        "base_model_lock_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v85 official matrix manifest requires lowercase SHA-256")
        return value

    @field_validator("v84_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v85 official matrix manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v85 official matrix manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        if tuple(item.task_id for item in self.schedule) != V71_MATRIX_TASK_IDS:
            raise ValueError("v85 official matrix schedule changed")
        if any(
            item.seed != self.seed or item.sample_index != self.sample_index
            for item in self.schedule
        ):
            raise ValueError("v85 task seed/sample differs from the matrix identity")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v85 official matrix manifest content hash changed")
        return self


class DeepSeekHarnessV87FreshScaffoldManifest(StrictModel):
    """Fresh zero-provider scaffold after the audited v85 readiness stop."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v87_fresh_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v87-fresh-scaffold-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    v79_manifest_sha256: str
    v79_manifest_hash: str
    v79_provider_contract_sha256: str
    v79_provider_contract_hash: str
    v85_report_sha256: str
    v85_report_hash: str
    v86_audit_sha256: str
    v86_audit_commit: str
    v86_post_merge_main_run_id: Literal[33753098955]
    v86_post_merge_main_all_eight_classes_passed: Literal[True]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v87-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v87-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v87/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v87/socket"]
    scaffold_outer_network: Literal["none"]
    provider_outer_network: Literal["verigym-hwe-net"]
    provider_inner_network: Literal["verigym-hwe-net"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_transfer: Literal["content_free_read_only_outer_canonical_tag_pipe_v2"]
    provider_successor_identity: Literal["deepseek-harness-hwe-v89-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    physical_volume_open_accounting: Literal["immediate_after_container_start_v1"]
    readiness_probe_timeout_retryable: Literal[True]
    host_docker_root_used_for_task_layers: Literal[False]
    v83_data_volume_reused: Literal[False]
    v85_data_volume_reused: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "v79_manifest_sha256",
        "v79_manifest_hash",
        "v79_provider_contract_sha256",
        "v79_provider_contract_hash",
        "v85_report_sha256",
        "v85_report_hash",
        "v86_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v87 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v86_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v87 scaffold manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v87 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v87 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV90FreshScaffoldManifest(StrictModel):
    """Fresh zero-provider scaffold after the audited v87 cold-VFS stop."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v90_fresh_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1"]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    v79_manifest_sha256: str
    v79_manifest_hash: str
    v79_provider_contract_sha256: str
    v79_provider_contract_hash: str
    v87_report_sha256: str
    v87_report_hash: str
    v88_audit_sha256: str
    v88_audit_commit: str
    v88_post_merge_main_run_id: Literal[33757519337]
    v88_post_merge_main_all_eight_classes_passed: Literal[True]
    source_preparation_docker_control_timeout_seconds: Literal[300]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v90-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v90-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/socket"]
    scaffold_outer_network: Literal["none"]
    provider_outer_network: Literal["verigym-hwe-net"]
    provider_inner_network: Literal["verigym-hwe-net"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_transfer: Literal["content_free_read_only_outer_canonical_tag_pipe_v2"]
    provider_successor_identity: Literal["deepseek-harness-hwe-v92-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    physical_volume_open_accounting: Literal["immediate_after_container_start_v1"]
    readiness_probe_timeout_retryable: Literal[True]
    host_docker_root_used_for_task_layers: Literal[False]
    v83_data_volume_reused: Literal[False]
    v85_data_volume_reused: Literal[False]
    v87_data_volume_reused: Literal[False]
    provider_clients_available: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "v79_manifest_sha256",
        "v79_manifest_hash",
        "v79_provider_contract_sha256",
        "v79_provider_contract_hash",
        "v87_report_sha256",
        "v87_report_hash",
        "v88_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v90 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v88_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v90 scaffold manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v90 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v90 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV92TaskBinding(StrictModel):
    """One immutable task/source/image binding in the official v92 matrix."""

    task_id: str
    repository: Repository
    pr_number: int = Field(ge=1)
    seed: Literal[502]
    sample_index: Literal[18]
    source_preparation_docker_control_timeout_seconds: Literal[300]
    task_hash: str
    source_hash: str
    task_receipt_hash: str
    prepared_source_image_lock_sha256: str
    command_image_lock_file_sha256: str
    command_image_lock_hash: str
    command_image: str
    security_scan_file_sha256: str
    security_scan_id: str
    official_verifier_image: str
    agent_toolchain_id: Literal["hwe-official-task-toolchain-v1"]
    toolchain_profile_id: Literal[
        "ibex-verilator-system-container-native-v1",
        "cva6-verilator-5.008-container-native-v2",
    ]

    @field_validator(
        "task_hash",
        "source_hash",
        "task_receipt_hash",
        "prepared_source_image_lock_sha256",
        "command_image_lock_file_sha256",
        "command_image_lock_hash",
        "security_scan_file_sha256",
        "security_scan_id",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v92 task binding requires lowercase SHA-256")
        return value

    @field_validator("command_image", "official_verifier_image")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v92 task binding requires immutable image IDs")
        return value

    @model_validator(mode="after")
    def bind_task(self) -> Self:
        matched = _TASK_ID.fullmatch(self.task_id)
        expected_repository = "ibex" if "lowRISC__ibex" in self.task_id else "cva6"
        expected_profile = (
            "ibex-verilator-system-container-native-v1"
            if self.repository == "ibex"
            else "cva6-verilator-5.008-container-native-v2"
        )
        if (
            matched is None
            or self.repository != expected_repository
            or int(matched.group("pr")) != self.pr_number
            or self.toolchain_profile_id != expected_profile
        ):
            raise ValueError("v92 task, repository, PR, or toolchain binding differs")
        return self


class DeepSeekHarnessV92OfficialMatrixManifest(StrictModel):
    """One-use official five-task provider matrix authorized by the v91 audit."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v92_official_matrix_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v92-official-matrix-v1"]
    v90_manifest_sha256: str
    v90_manifest_hash: str
    v90_report_sha256: str
    v90_report_hash: str
    v90_contract_sha256: str
    v90_contract_hash: str
    v90_inventory_sha256: str
    v90_inventory_hash: str
    v90_controller_receipt_sha256: str
    v90_controller_receipt_hash: str
    v90_runtime_receipt_sha256: str
    v90_runtime_receipt_hash: str
    v90_cleanup_receipt_sha256: str
    v90_cleanup_receipt_hash: str
    v91_audit_sha256: str
    v91_audit_commit: str
    v91_post_merge_main_run_id: Literal[33762766907]
    v91_post_merge_main_all_eight_classes_passed: Literal[True]
    source_preparation_docker_control_timeout_seconds: Literal[300]
    schedule: list[DeepSeekHarnessV92TaskBinding] = Field(min_length=5, max_length=5)
    provider: Literal["deepseek-official"]
    model: Literal["deepseek-v4-flash"]
    harness_version: Literal["0.1.1-rc.2"]
    integration_version: Literal["0.5.0"]
    harness_revision: Literal["b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"]
    seed: Literal[502]
    sample_index: Literal[18]
    max_provider_calls_per_task: Literal[64]
    max_provider_tokens_per_task: Literal[1000000]
    max_context_tokens: Literal[65536]
    max_output_tokens: Literal[2048]
    temperature: Literal[0]
    provider_request_retries: Literal[0]
    whole_episode_retries: Literal[0]
    ordinary_tool_choice: Literal["auto"]
    public_rationale_allowed: Literal[True]
    sibling_calls_allowed: Literal[True]
    provider_hidden_thinking: Literal["disabled"]
    foreign_tools_rejected: Literal[True]
    illegal_paths_rejected: Literal[True]
    unpaired_observations_rejected: Literal[True]
    decision_only_loss_mask: Literal[True]
    exact_tokenizer_hash: str
    base_model_snapshot_hash: str
    base_model_lock_sha256: str
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v90-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v90-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/socket"]
    provider_outer_network: Literal["verigym-hwe-net"]
    provider_inner_network: Literal["verigym-hwe-net"]
    task_network: Literal["none"]
    verifier_network: Literal["none"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_image_provenance: Literal["audited_v90_offline_canonical_tag_load_v1"]
    v90_data_volume_reopen_budget: Literal[1]
    v90_data_volume_reopen_count_before: Literal[0]
    atomic_progress: Literal[True]
    stop_on_infrastructure_or_security_failure: Literal[True]
    continue_after_ordinary_model_or_verifier_failure: Literal[True]
    consecutive_no_progress_stop_limit: Literal[2]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v90_manifest_sha256",
        "v90_manifest_hash",
        "v90_report_sha256",
        "v90_report_hash",
        "v90_contract_sha256",
        "v90_contract_hash",
        "v90_inventory_sha256",
        "v90_inventory_hash",
        "v90_controller_receipt_sha256",
        "v90_controller_receipt_hash",
        "v90_runtime_receipt_sha256",
        "v90_runtime_receipt_hash",
        "v90_cleanup_receipt_sha256",
        "v90_cleanup_receipt_hash",
        "v91_audit_sha256",
        "exact_tokenizer_hash",
        "base_model_snapshot_hash",
        "base_model_lock_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v92 official matrix manifest requires lowercase SHA-256")
        return value

    @field_validator("v91_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v92 official matrix manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v92 official matrix manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        if tuple(item.task_id for item in self.schedule) != V71_MATRIX_TASK_IDS:
            raise ValueError("v92 official matrix schedule changed")
        if any(
            item.seed != self.seed or item.sample_index != self.sample_index
            for item in self.schedule
        ):
            raise ValueError("v92 task seed/sample differs from the matrix identity")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v92 official matrix manifest content hash changed")
        return self


class DeepSeekHarnessV94RuntimeCompleteScaffoldManifest(StrictModel):
    """Fresh zero-provider scaffold that includes the fixed workspace runtime image."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v94_runtime_complete_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v94-runtime-complete-scaffold-v1"]
    v92_manifest_sha256: str
    v92_manifest_hash: str
    v92_report_sha256: str
    v92_report_hash: str
    v93_audit_sha256: str
    v93_audit_commit: str
    v93_post_merge_main_run_id: Literal[33766642633]
    v93_post_merge_main_all_eight_classes_passed: Literal[True]
    schedule: list[DeepSeekHarnessV92TaskBinding] = Field(min_length=5, max_length=5)
    seed: Literal[502]
    sample_index: Literal[18]
    v90_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1"
    ]
    v92_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v92-official-matrix-v1"
    ]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v94-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v94-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v94/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v94/socket"]
    scaffold_outer_network: Literal["none"]
    preflight_inner_network: Literal["verigym-hwe-net"]
    preflight_inner_network_internal: Literal[True]
    task_network: Literal["none"]
    verifier_network: Literal["none"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_transfer: Literal["content_free_read_only_outer_canonical_tag_pipe_v2"]
    workspace_runtime_image_id: str
    workspace_runtime_host_repo_tags: list[str] = Field(min_length=2, max_length=2)
    workspace_runtime_transfer: Literal["content_free_read_only_outer_image_id_pipe_v1"]
    required_inner_image_count: Literal[12]
    runtime_prepare_task_count: Literal[5]
    harness_initialize_required: Literal[True]
    synthetic_provider_values_only: Literal[True]
    v90_task_qualification_reused_as_expected_binding: Literal[True]
    tasks_rematerialized_from_completed_local_archives: Literal[True]
    v90_data_volume_reused: Literal[False]
    v92_data_volume_reused: Literal[False]
    host_docker_root_used_for_task_layers: Literal[False]
    provider_successor_identity: Literal["deepseek-harness-hwe-v96-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v92_manifest_sha256",
        "v92_manifest_hash",
        "v92_report_sha256",
        "v92_report_hash",
        "v93_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v94 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v93_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v94 scaffold manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
        "workspace_runtime_image_id",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v94 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        if tuple(item.task_id for item in self.schedule) != V71_MATRIX_TASK_IDS:
            raise ValueError("v94 scaffold schedule changed")
        if any(
            item.seed != self.seed or item.sample_index != self.sample_index
            for item in self.schedule
        ):
            raise ValueError("v94 task seed/sample differs from the scaffold identity")
        if self.workspace_runtime_host_repo_tags != [
            "verigym/rtl-iverilog:12.0",
            "verigym/rtl-iverilog:m10a-pre-ci",
        ]:
            raise ValueError("v94 workspace runtime tags changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v94 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV97RebuildIdentityScaffoldManifest(StrictModel):
    """Fresh zero-provider scaffold that freezes identities produced by its own build."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v97_rebuild_identity_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1"]
    v92_manifest_sha256: str
    v92_manifest_hash: str
    v92_report_sha256: str
    v92_report_hash: str
    v93_audit_sha256: str
    v93_audit_commit: str
    v93_post_merge_main_run_id: Literal[33766642633]
    v93_post_merge_main_all_eight_classes_passed: Literal[True]
    v94_manifest_sha256: str
    v94_manifest_hash: str
    v94_report_sha256: str
    v94_report_hash: str
    v95_audit_sha256: str
    v95_audit_commit: str
    v95_post_merge_main_run_id: Literal[33776059453]
    v95_post_merge_main_all_eight_classes_passed: Literal[True]
    schedule: list[DeepSeekHarnessV92TaskBinding] = Field(min_length=5, max_length=5)
    seed: Literal[502]
    sample_index: Literal[18]
    v90_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1"
    ]
    v92_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v92-official-matrix-v1"
    ]
    v94_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v94-runtime-complete-scaffold-v1"
    ]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v97-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v97-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v97/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v97/socket"]
    scaffold_outer_network: Literal["none"]
    preflight_inner_network: Literal["verigym-hwe-net"]
    preflight_inner_network_internal: Literal[True]
    task_network: Literal["none"]
    verifier_network: Literal["none"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    controller_transfer: Literal["content_free_read_only_outer_canonical_tag_pipe_v2"]
    workspace_runtime_image_id: str
    workspace_runtime_host_repo_tags: list[str] = Field(min_length=2, max_length=2)
    workspace_runtime_transfer: Literal["content_free_read_only_outer_image_id_pipe_v1"]
    required_inner_image_count: Literal[12]
    runtime_prepare_task_count: Literal[5]
    harness_initialize_required: Literal[True]
    synthetic_provider_values_only: Literal[True]
    cross_build_command_image_identity_policy: Literal["fresh-materialization-lock-v1"]
    historical_derived_image_identity_required: Literal[False]
    historical_task_semantics_required: Literal[True]
    v90_task_qualification_reused_as_expected_binding: Literal[True]
    tasks_rematerialized_from_completed_local_archives: Literal[True]
    v90_data_volume_reused: Literal[False]
    v92_data_volume_reused: Literal[False]
    v94_data_volume_reused: Literal[False]
    v96_identity_retired: Literal[True]
    host_docker_root_used_for_task_layers: Literal[False]
    provider_successor_identity: Literal["deepseek-harness-hwe-v99-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v92_manifest_sha256",
        "v92_manifest_hash",
        "v92_report_sha256",
        "v92_report_hash",
        "v93_audit_sha256",
        "v94_manifest_sha256",
        "v94_manifest_hash",
        "v94_report_sha256",
        "v94_report_hash",
        "v95_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v97 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v93_audit_commit", "v95_audit_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v97 scaffold manifest requires a full audit commit")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
        "workspace_runtime_image_id",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v97 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_manifest_identity(self) -> Self:
        if tuple(item.task_id for item in self.schedule) != V71_MATRIX_TASK_IDS:
            raise ValueError("v97 scaffold schedule changed")
        if any(
            item.seed != self.seed or item.sample_index != self.sample_index
            for item in self.schedule
        ):
            raise ValueError("v97 task seed/sample differs from the scaffold identity")
        if self.workspace_runtime_host_repo_tags != [
            "verigym/rtl-iverilog:12.0",
            "verigym/rtl-iverilog:m10a-pre-ci",
        ]:
            raise ValueError("v97 workspace runtime tags changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v97 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV100InventoryTimeoutScaffoldManifest(
    DeepSeekHarnessV97RebuildIdentityScaffoldManifest
):
    """Fresh zero-provider scaffold with bounded task-inventory Docker controls."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_deepseek_harness_hwe_v100_inventory_timeout_scaffold_manifest_v1"
    ]
    identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1"
    ]
    v97_manifest_sha256: str
    v97_manifest_hash: str
    v97_report_sha256: str
    v97_report_hash: str
    v98_audit_sha256: str
    v98_audit_commit: str
    v98_post_merge_main_run_id: Literal[33782913003]
    v98_post_merge_main_all_eight_classes_passed: Literal[True]
    v97_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1"
    ]
    dind_data_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v100-dind-data"
    ]
    dind_socket_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v100-dind-socket"
    ]
    dind_data_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v100/data"
    ]
    dind_socket_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v100/socket"
    ]
    toolchain_inventory_create_timeout_seconds: Literal[300]
    toolchain_inventory_inspect_timeout_seconds: Literal[300]
    toolchain_inventory_execute_timeout_seconds: Literal[120]
    toolchain_inventory_remove_timeout_seconds: Literal[300]
    v97_data_volume_reused: Literal[False]
    v99_identity_retired: Literal[True]
    provider_successor_identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v102-official-matrix-v1"
    ]

    @field_validator(
        "v97_manifest_sha256",
        "v97_manifest_hash",
        "v97_report_sha256",
        "v97_report_hash",
        "v98_audit_sha256",
    )
    @classmethod
    def validate_v100_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v100 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v98_audit_commit")
    @classmethod
    def validate_v100_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v100 scaffold manifest requires a full audit commit")
        return value

    @model_validator(mode="after")
    def validate_v100_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v100 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV103InspectOutputBoundScaffoldManifest(
    DeepSeekHarnessV100InventoryTimeoutScaffoldManifest
):
    """Fresh zero-provider scaffold with the dedicated Docker inspect output bound."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_deepseek_harness_hwe_v103_inspect_output_bound_scaffold_manifest_v1"
    ]
    identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1"
    ]
    v100_manifest_sha256: str
    v100_manifest_hash: str
    v100_runner_sha256: str
    v100_report_sha256: str
    v100_report_hash: str
    v101_audit_sha256: str
    v101_audit_commit: str
    v101_post_merge_main_run_id: Literal[33789571225]
    v101_post_merge_main_all_eight_classes_passed: Literal[True]
    v100_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1"
    ]
    dind_data_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v103-dind-data"
    ]
    dind_socket_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v103-dind-socket"
    ]
    dind_data_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v103/data"
    ]
    dind_socket_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v103/socket"
    ]
    v100_failed_inspect_output_bound_bytes: Literal[4096]
    toolchain_inventory_inspect_output_bound_bytes: Literal[1_048_576]
    v100_data_volume_reused: Literal[False]
    v102_identity_retired: Literal[True]
    provider_successor_identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v105-official-matrix-v1"
    ]

    @field_validator(
        "v100_manifest_sha256",
        "v100_manifest_hash",
        "v100_runner_sha256",
        "v100_report_sha256",
        "v100_report_hash",
        "v101_audit_sha256",
    )
    @classmethod
    def validate_v103_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v103 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v101_audit_commit")
    @classmethod
    def validate_v103_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v103 scaffold manifest requires a full audit commit")
        return value

    @model_validator(mode="after")
    def validate_v103_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v103 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest(
    DeepSeekHarnessV103InspectOutputBoundScaffoldManifest
):
    """Fresh zero-provider scaffold binding final inventory to fresh image locks."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_deepseek_harness_hwe_v106_fresh_inventory_binding_scaffold_manifest_v1"
    ]
    identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1"
    ]
    v103_manifest_sha256: str
    v103_manifest_hash: str
    v103_runner_sha256: str
    v103_report_sha256: str
    v103_report_hash: str
    v103_task_materialization_sha256: str
    v103_task_materialization_hash: str
    v104_audit_sha256: str
    v104_audit_commit: str
    v104_post_merge_main_run_id: Literal[33795946043]
    v104_post_merge_main_all_eight_classes_passed: Literal[True]
    v103_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1"
    ]
    dind_data_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v106-dind-data"
    ]
    dind_socket_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v106-dind-socket"
    ]
    dind_data_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v106/data"
    ]
    dind_socket_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v106/socket"
    ]
    final_inventory_command_image_source: Literal["fresh-materialization-locks"]
    final_inventory_fresh_command_image_count: Literal[5]
    v103_data_volume_reused: Literal[False]
    v105_identity_retired: Literal[True]
    provider_successor_identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v108-official-matrix-v1"
    ]

    @field_validator(
        "v103_manifest_sha256",
        "v103_manifest_hash",
        "v103_runner_sha256",
        "v103_report_sha256",
        "v103_report_hash",
        "v103_task_materialization_sha256",
        "v103_task_materialization_hash",
        "v104_audit_sha256",
    )
    @classmethod
    def validate_v106_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v106 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v104_audit_commit")
    @classmethod
    def validate_v106_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v106 scaffold manifest requires a full audit commit")
        return value

    @model_validator(mode="after")
    def validate_v106_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v106 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV109ProgressWriterScaffoldManifest(
    DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest
):
    """Fresh zero-provider scaffold with a directly tested progress writer."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_deepseek_harness_hwe_v109_progress_writer_scaffold_manifest_v1"
    ]
    identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v109-progress-writer-scaffold-v1"
    ]
    v106_manifest_sha256: str
    v106_manifest_hash: str
    v106_runner_sha256: str
    v106_authorization_sha256: str
    v106_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1"
    ]
    v106_evidence_directory_count: Literal[14]
    v106_evidence_regular_file_count: Literal[0]
    v106_evidence_symlink_count: Literal[0]
    v107_audit_sha256: str
    v107_audit_commit: str
    v107_post_merge_main_run_id: Literal[33800282289]
    v107_post_merge_main_all_eight_classes_passed: Literal[True]
    progress_writer_source: Literal["v97-captured-v94-base-writer"]
    dind_data_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v109-dind-data"
    ]
    dind_socket_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v109-dind-socket"
    ]
    dind_data_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v109/data"
    ]
    dind_socket_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v109/socket"
    ]
    v106_data_volume_reused: Literal[False]
    v108_identity_retired: Literal[True]
    provider_successor_identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v111-official-matrix-v1"
    ]

    @field_validator(
        "v106_manifest_sha256",
        "v106_manifest_hash",
        "v106_runner_sha256",
        "v106_authorization_sha256",
        "v107_audit_sha256",
    )
    @classmethod
    def validate_v109_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v109 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v107_audit_commit")
    @classmethod
    def validate_v109_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v109 scaffold manifest requires a full audit commit")
        return value

    @model_validator(mode="after")
    def validate_v109_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v109 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest(
    DeepSeekHarnessV109ProgressWriterScaffoldManifest
):
    """Fresh scaffold measuring its actual data2 control workspace."""

    format_id: Literal[  # type: ignore[assignment]
        "verigym_deepseek_harness_hwe_v112_data2_control_headroom_scaffold_manifest_v1"
    ]
    identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1"
    ]
    v109_manifest_sha256: str
    v109_manifest_hash: str
    v109_runner_sha256: str
    v109_authorization_sha256: str
    v109_report_sha256: str
    v109_report_hash: str
    v109_headroom_sha256: str
    v109_headroom_hash: str
    v109_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v109-progress-writer-scaffold-v1"
    ]
    v110_audit_sha256: str
    v110_audit_commit: str
    v110_post_merge_main_run_id: Literal[33804279053]
    v110_post_merge_main_all_eight_classes_passed: Literal[True]
    inherited_control_headroom_root: Literal["/"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-control"
    ]
    system_root_headroom_required: Literal[False]
    all_campaign_writable_roots_under_data2: Literal[True]
    dind_data_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v112-dind-data"
    ]
    dind_socket_volume: Literal[  # type: ignore[assignment]
        "verigym-deepseek-harness-v112-dind-socket"
    ]
    dind_data_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v112/data"
    ]
    dind_socket_backing: Literal[  # type: ignore[assignment]
        "/data2/jiadongzhu/docker/deepseek-harness-hwe-v112/socket"
    ]
    v109_data_volume_reused: Literal[False]
    v111_identity_retired: Literal[True]
    provider_successor_identity: Literal[  # type: ignore[assignment]
        "deepseek-harness-hwe-v114-official-matrix-v1"
    ]

    @field_validator(
        "v109_manifest_sha256",
        "v109_manifest_hash",
        "v109_runner_sha256",
        "v109_authorization_sha256",
        "v109_report_sha256",
        "v109_report_hash",
        "v109_headroom_sha256",
        "v109_headroom_hash",
        "v110_audit_sha256",
    )
    @classmethod
    def validate_v112_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v112 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("v110_audit_commit")
    @classmethod
    def validate_v112_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v112 scaffold manifest requires a full audit commit")
        return value

    @model_validator(mode="after")
    def validate_v112_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v112 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV115ExplicitNestedDockerSocketScaffoldManifest(StrictModel):
    """One-use zero-provider scaffold with an explicit local DinD socket binding."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal[
        "verigym_deepseek_harness_hwe_v115_explicit_nested_docker_socket_scaffold_manifest_v1"
    ]
    identity: Literal["deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1"]
    v112_manifest_sha256: str
    v112_manifest_hash: str
    v112_runner_sha256: str
    v112_authorization_sha256: str
    v112_report_sha256: str
    v112_report_hash: str
    v112_headroom_sha256: str
    v112_headroom_hash: str
    v112_task_materialization_sha256: str
    v112_task_materialization_hash: str
    v112_inventory_sha256: str
    v112_inventory_hash: str
    v112_cleanup_sha256: str
    v112_cleanup_hash: str
    v112_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1"
    ]
    v112_evidence_directory_count: Literal[1780]
    v112_evidence_regular_file_count: Literal[10477]
    v112_evidence_symlink_count: Literal[0]
    v113_audit_sha256: str
    v113_audit_commit: Literal["9f79f54725c365bd0ab9ba9389f2ac421db1b155"]
    v113_post_merge_main_run_id: Literal[33810326256]
    v113_post_merge_main_all_eight_classes_passed: Literal[True]
    schedule_source: Literal["exact-audited-v112-manifest"]
    schedule_task_ids: list[str] = Field(min_length=5, max_length=5)
    seed: Literal[502]
    sample_index: Literal[18]
    dind_data_volume: Literal["verigym-deepseek-harness-v115-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v115-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v115/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-control"
    ]
    runtime_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-runtime"
    ]
    nested_docker_host: Literal[
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket/docker.sock"
    ]
    docker_host_binding_policy: Literal["explicit-canonical-local-unix-socket-v1"]
    docker_cli_explicit_binding_required: Literal[True]
    harness_helper_explicit_binding_required: Literal[True]
    inherited_docker_environment_allowed: Literal[False]
    remote_docker_endpoint_allowed: Literal[False]
    v112_data_volume_reused: Literal[False]
    v114_identity_retired: Literal[True]
    provider_successor_identity: Literal["deepseek-harness-hwe-v117-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v112_manifest_sha256",
        "v112_manifest_hash",
        "v112_runner_sha256",
        "v112_authorization_sha256",
        "v112_report_sha256",
        "v112_report_hash",
        "v112_headroom_sha256",
        "v112_headroom_hash",
        "v112_task_materialization_sha256",
        "v112_task_materialization_hash",
        "v112_inventory_sha256",
        "v112_inventory_hash",
        "v112_cleanup_sha256",
        "v112_cleanup_hash",
        "v113_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v115_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v115 scaffold manifest requires lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_v115_identity(self) -> Self:
        if tuple(self.schedule_task_ids) != V71_MATRIX_TASK_IDS:
            raise ValueError("v115 scaffold schedule changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v115 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV118ExplicitInnerInventoryScaffoldManifest(StrictModel):
    """One-use scaffold with all inner inventory bound to the explicit DinD endpoint."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal[
        "verigym_deepseek_harness_hwe_v118_explicit_inner_inventory_scaffold_manifest_v1"
    ]
    identity: Literal["deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1"]
    v112_manifest_sha256: str
    v112_manifest_hash: str
    v112_runner_sha256: str
    v112_authorization_sha256: str
    v112_report_sha256: str
    v112_report_hash: str
    v112_headroom_sha256: str
    v112_headroom_hash: str
    v112_task_materialization_sha256: str
    v112_task_materialization_hash: str
    v112_inventory_sha256: str
    v112_inventory_hash: str
    v112_cleanup_sha256: str
    v112_cleanup_hash: str
    v112_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1"
    ]
    v112_evidence_directory_count: Literal[1780]
    v112_evidence_regular_file_count: Literal[10477]
    v112_evidence_symlink_count: Literal[0]
    v113_audit_sha256: str
    v113_audit_commit: Literal["9f79f54725c365bd0ab9ba9389f2ac421db1b155"]
    v113_post_merge_main_run_id: Literal[33810326256]
    v113_post_merge_main_all_eight_classes_passed: Literal[True]
    v115_manifest_sha256: str
    v115_manifest_hash: str
    v115_runner_sha256: str
    v115_authorization_sha256: str
    v115_engine_sha256: str
    v115_process_sha256: str
    v115_report_sha256: str
    v115_report_hash: str
    v115_headroom_sha256: str
    v115_headroom_hash: str
    v115_task_materialization_sha256: str
    v115_task_materialization_hash: str
    v115_inventory_sha256: str
    v115_inventory_hash: str
    v115_runtime_receipt_sha256: str
    v115_runtime_receipt_hash: str
    v115_transfer_set_sha256: str
    v115_transfer_set_hash: str
    v115_cleanup_sha256: str
    v115_cleanup_hash: str
    v115_authorization_commit: Literal["48bc47f0dbb020e41f330bf5350bad621d01df1c"]
    v115_post_merge_main_run_id: Literal[33812788683]
    v115_post_merge_main_all_eight_classes_passed: Literal[True]
    v115_evidence_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1"
    ]
    v115_evidence_directory_count: Literal[1780]
    v115_evidence_regular_file_count: Literal[10477]
    v115_evidence_symlink_count: Literal[0]
    v116_audit_sha256: str
    v116_audit_commit: Literal["7faf47a4ba49139bf9e93200e104b8b9e9cbfea2"]
    v116_post_merge_main_run_id: Literal[33815411217]
    v116_post_merge_main_all_eight_classes_passed: Literal[True]
    schedule_source: Literal["exact-audited-v115-manifest"]
    schedule_task_ids: list[str] = Field(min_length=5, max_length=5)
    seed: Literal[502]
    sample_index: Literal[18]
    dind_data_volume: Literal["verigym-deepseek-harness-v118-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v118-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v118/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v118/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v118-control"
    ]
    runtime_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v118-runtime"
    ]
    nested_docker_host: Literal[
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v118/socket/docker.sock"
    ]
    docker_host_binding_policy: Literal["explicit-canonical-local-unix-socket-v1"]
    docker_cli_explicit_binding_required: Literal[True]
    harness_helper_explicit_binding_required: Literal[True]
    inherited_docker_environment_allowed: Literal[False]
    remote_docker_endpoint_allowed: Literal[False]
    inner_inventory_transport_policy: Literal["explicit-bound-engine-all-resources-v1"]
    inner_inventory_all_containers_required: Literal[True]
    inner_inventory_all_volumes_required: Literal[True]
    host_sidecar_inventory_for_inner_allowed: Literal[False]
    inner_network_transport_policy: Literal["explicit-bound-engine-v1"]
    host_sidecar_network_control_for_inner_allowed: Literal[False]
    streaming_attach_explicit_binding_required: Literal[True]
    v112_data_volume_reused: Literal[False]
    v114_identity_retired: Literal[True]
    v115_data_volume_reused: Literal[False]
    v115_socket_control_runtime_empty_required: Literal[True]
    v117_identity_retired: Literal[True]
    provider_successor_identity: Literal["deepseek-harness-hwe-v120-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v112_manifest_sha256",
        "v112_manifest_hash",
        "v112_runner_sha256",
        "v112_authorization_sha256",
        "v112_report_sha256",
        "v112_report_hash",
        "v112_headroom_sha256",
        "v112_headroom_hash",
        "v112_task_materialization_sha256",
        "v112_task_materialization_hash",
        "v112_inventory_sha256",
        "v112_inventory_hash",
        "v112_cleanup_sha256",
        "v112_cleanup_hash",
        "v113_audit_sha256",
        "v115_manifest_sha256",
        "v115_manifest_hash",
        "v115_runner_sha256",
        "v115_authorization_sha256",
        "v115_engine_sha256",
        "v115_process_sha256",
        "v115_report_sha256",
        "v115_report_hash",
        "v115_headroom_sha256",
        "v115_headroom_hash",
        "v115_task_materialization_sha256",
        "v115_task_materialization_hash",
        "v115_inventory_sha256",
        "v115_inventory_hash",
        "v115_runtime_receipt_sha256",
        "v115_runtime_receipt_hash",
        "v115_transfer_set_sha256",
        "v115_transfer_set_hash",
        "v115_cleanup_sha256",
        "v115_cleanup_hash",
        "v116_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v118_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v118 scaffold manifest requires lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_v118_identity(self) -> Self:
        if tuple(self.schedule_task_ids) != V71_MATRIX_TASK_IDS:
            raise ValueError("v118 scaffold schedule changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v118 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV121BoundedDindStartDiagnosticManifest(StrictModel):
    """One-use, provider-free diagnosis of the outer DinD startup boundary."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal[
        "verigym_deepseek_harness_hwe_v121_bounded_dind_start_diagnostic_manifest_v1"
    ]
    identity: Literal["deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1"]
    v118_manifest_sha256: str
    v118_manifest_hash: str
    v118_authorization_sha256: str
    v118_authorization_merge: Literal["928b117882ae8be4c60520f8d4a49d82edc548b8"]
    v118_post_merge_main_run_id: Literal[33819300080]
    v118_report_sha256: str
    v118_report_hash: str
    v118_headroom_sha256: str
    v118_headroom_hash: str
    v118_evidence_directory_count: Literal[14]
    v118_evidence_regular_file_count: Literal[8]
    v118_evidence_symlink_count: Literal[0]
    v119_audit_sha256: str
    v119_audit_commit: Literal["c22066916ba51e8c74678be2b0af6ac8d438ac9a"]
    v119_post_merge_main_run_id: Literal[33820413201]
    v119_post_merge_main_all_eight_classes_passed: Literal[True]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v121-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v121-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v121/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v121/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v121-control"
    ]
    diagnostic_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v121-scratch"
    ]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1"
    ]
    frozen_v118_data_volume: Literal["verigym-deepseek-harness-v118-dind-data"]
    frozen_v118_socket_volume: Literal["verigym-deepseek-harness-v118-dind-socket"]
    v118_volume_inspection_allowed: Literal[False]
    v118_volume_mutation_allowed: Literal[False]
    startup_attempt_limit: Literal[1]
    startup_command_timeout_seconds: Literal[60]
    readiness_timeout_seconds: Literal[120]
    cleanup_command_timeout_seconds: Literal[60]
    maximum_diagnostic_output_bytes: Literal[65536]
    diagnostic_classification_policy: Literal["allowlisted-content-free-v1"]
    raw_docker_output_persisted: Literal[False]
    container_identity_persisted: Literal[False]
    fresh_bind_backed_volumes_required: Literal[True]
    scaffold_outer_network: Literal["none"]
    task_archive_access_allowed: Literal[False]
    task_materialization_allowed: Literal[False]
    base_reference_verification_allowed: Literal[False]
    harness_controller_allowed: Literal[False]
    docker_network_creation_allowed: Literal[False]
    registry_access_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    provider_request_started: Literal[False]
    provider_calls: Literal[0]
    requires_independent_result_audit: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v118_manifest_sha256",
        "v118_manifest_hash",
        "v118_authorization_sha256",
        "v118_report_sha256",
        "v118_report_hash",
        "v118_headroom_sha256",
        "v118_headroom_hash",
        "v119_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v121_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v121 diagnostic manifest requires lowercase SHA-256")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_v121_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v121 diagnostic manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_v121_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v121 diagnostic manifest content hash changed")
        return self


class DeepSeekHarnessV123BoundedDindIdentityProbeManifest(StrictModel):
    """One-use, provider-free probe of the inner DinD identity fields."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v123_bounded_dind_identity_probe_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1"]
    v121_manifest_sha256: str
    v121_manifest_hash: str
    v121_authorization_sha256: str
    v121_authorization_merge: Literal["0cc0f14af875ade980a2f9914d63a8d51c8a9730"]
    v121_post_merge_main_run_id: Literal[33822511727]
    v121_report_sha256: str
    v121_report_hash: str
    v121_startup_sha256: str
    v121_startup_hash: str
    v121_cleanup_sha256: str
    v121_cleanup_hash: str
    v121_host_image_sha256: str
    v121_host_image_hash: str
    v121_headroom_sha256: str
    v121_headroom_hash: str
    v121_volume_setup_sha256: str
    v121_volume_setup_hash: str
    v121_predecessor_sha256: str
    v121_predecessor_hash: str
    v121_evidence_directory_count: Literal[1]
    v121_evidence_regular_file_count: Literal[8]
    v121_evidence_symlink_count: Literal[0]
    v122_audit_sha256: str
    v122_audit_commit: Literal["34a2854afcaa64a6de8a0fbca94ffd50dbb168db"]
    v122_post_merge_main_run_id: Literal[33823592366]
    v122_post_merge_main_all_eight_classes_passed: Literal[True]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v123-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v123-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v123/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v123/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v123-control"
    ]
    diagnostic_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v123-scratch"
    ]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v123-bounded-dind-identity-probe-v1"
    ]
    predecessor_volume_inspection_allowed: Literal[False]
    predecessor_volume_mutation_allowed: Literal[False]
    startup_attempt_limit: Literal[1]
    startup_command_timeout_seconds: Literal[60]
    readiness_timeout_seconds: Literal[120]
    probe_command_timeout_seconds: Literal[30]
    cleanup_command_timeout_seconds: Literal[60]
    maximum_diagnostic_output_bytes: Literal[65536]
    identity_probe_policy: Literal["explicit-info-fields-and-legacy-classification-v1"]
    raw_docker_output_persisted: Literal[False]
    raw_docker_output_hashed: Literal[False]
    raw_exception_persisted: Literal[False]
    container_identity_persisted: Literal[False]
    host_paths_persisted_in_diagnostics: Literal[False]
    fresh_bind_backed_volumes_required: Literal[True]
    scaffold_outer_network: Literal["none"]
    task_archive_access_allowed: Literal[False]
    task_materialization_allowed: Literal[False]
    base_reference_verification_allowed: Literal[False]
    harness_controller_allowed: Literal[False]
    docker_network_creation_allowed: Literal[False]
    registry_access_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    provider_request_started: Literal[False]
    provider_calls: Literal[0]
    requires_independent_result_audit: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v121_manifest_sha256",
        "v121_manifest_hash",
        "v121_authorization_sha256",
        "v121_report_sha256",
        "v121_report_hash",
        "v121_startup_sha256",
        "v121_startup_hash",
        "v121_cleanup_sha256",
        "v121_cleanup_hash",
        "v121_host_image_sha256",
        "v121_host_image_hash",
        "v121_headroom_sha256",
        "v121_headroom_hash",
        "v121_volume_setup_sha256",
        "v121_volume_setup_hash",
        "v121_predecessor_sha256",
        "v121_predecessor_hash",
        "v122_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v123_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v123 identity-probe manifest requires lowercase SHA-256")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_v123_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v123 identity-probe manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_v123_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v123 identity-probe manifest content hash changed")
        return self


class DeepSeekHarnessV125BoundedDindReadinessProbeManifest(StrictModel):
    """One-use, provider-free probe with an exact explicit DinD readiness predicate."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v125_bounded_dind_readiness_probe_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1"]
    v123_manifest_sha256: str
    v123_manifest_hash: str
    v123_runner_sha256: str
    v123_authorization_sha256: str
    v123_authorization_merge: Literal["2489465550af18c994e449eecc2bdd8ae142c5e6"]
    v123_post_merge_main_run_id: Literal[33825382724]
    v123_report_sha256: str
    v123_report_hash: str
    v123_probe_sha256: str
    v123_probe_hash: str
    v123_cleanup_sha256: str
    v123_cleanup_hash: str
    v123_host_image_sha256: str
    v123_host_image_hash: str
    v123_headroom_sha256: str
    v123_headroom_hash: str
    v123_volume_setup_sha256: str
    v123_volume_setup_hash: str
    v123_predecessor_sha256: str
    v123_predecessor_hash: str
    v123_evidence_directory_count: Literal[1]
    v123_evidence_regular_file_count: Literal[8]
    v123_evidence_symlink_count: Literal[0]
    v124_audit_sha256: str
    v124_audit_commit: Literal["013154e899b4a0622dabf75f51d87a309d1b5b3b"]
    v124_post_merge_main_run_id: Literal[33826887799]
    v124_post_merge_main_all_eight_classes_passed: Literal[True]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v125-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v125-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v125/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v125/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v125-control"
    ]
    diagnostic_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v125-scratch"
    ]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v125-bounded-dind-readiness-probe-v1"
    ]
    predecessor_volume_inspection_allowed: Literal[False]
    predecessor_volume_mutation_allowed: Literal[False]
    startup_attempt_limit: Literal[1]
    startup_command_timeout_seconds: Literal[60]
    readiness_timeout_seconds: Literal[120]
    readiness_command_timeout_seconds: Literal[5]
    readiness_poll_interval_seconds: Literal[1]
    cleanup_command_timeout_seconds: Literal[60]
    maximum_diagnostic_output_bytes: Literal[65536]
    readiness_probe_policy: Literal["explicit-three-field-exact-monotonic-deadline-v1"]
    json_info_readiness_allowed: Literal[False]
    fixed_poll_count_cap_allowed: Literal[False]
    explicit_readiness_requires_empty_stderr: Literal[True]
    explicit_readiness_requires_three_values: Literal[True]
    explicit_readiness_requires_exact_identity: Literal[True]
    raw_docker_output_persisted: Literal[False]
    raw_docker_output_hashed: Literal[False]
    raw_exception_persisted: Literal[False]
    container_identity_persisted: Literal[False]
    host_paths_persisted_in_diagnostics: Literal[False]
    fresh_bind_backed_volumes_required: Literal[True]
    scaffold_outer_network: Literal["none"]
    task_archive_access_allowed: Literal[False]
    task_materialization_allowed: Literal[False]
    base_reference_verification_allowed: Literal[False]
    harness_controller_allowed: Literal[False]
    docker_network_creation_allowed: Literal[False]
    registry_access_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    provider_request_started: Literal[False]
    provider_calls: Literal[0]
    requires_independent_result_audit: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v123_manifest_sha256",
        "v123_manifest_hash",
        "v123_runner_sha256",
        "v123_authorization_sha256",
        "v123_report_sha256",
        "v123_report_hash",
        "v123_probe_sha256",
        "v123_probe_hash",
        "v123_cleanup_sha256",
        "v123_cleanup_hash",
        "v123_host_image_sha256",
        "v123_host_image_hash",
        "v123_headroom_sha256",
        "v123_headroom_hash",
        "v123_volume_setup_sha256",
        "v123_volume_setup_hash",
        "v123_predecessor_sha256",
        "v123_predecessor_hash",
        "v124_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v125_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v125 readiness-probe manifest requires lowercase SHA-256")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_v125_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v125 readiness-probe manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_v125_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v125 readiness-probe manifest content hash changed")
        return self


class DeepSeekHarnessV127ReadinessGatedScaffoldManifest(StrictModel):
    """One-use five-task scaffold gated by the audited exact DinD readiness predicate."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v127_readiness_gated_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v127-readiness-gated-scaffold-v1"]
    v118_manifest_sha256: str
    v118_manifest_hash: str
    v118_runner_sha256: str
    v118_authorization_sha256: str
    v118_authorization_merge: Literal["928b117882ae8be4c60520f8d4a49d82edc548b8"]
    v118_post_merge_main_run_id: Literal[33819300080]
    v119_audit_sha256: str
    v119_audit_commit: Literal["c22066916ba51e8c74678be2b0af6ac8d438ac9a"]
    v119_post_merge_main_run_id: Literal[33820413201]
    v125_manifest_sha256: str
    v125_manifest_hash: str
    v125_runner_sha256: str
    v125_authorization_sha256: str
    v125_source_commit: Literal["70cfa0393b3d2bfa06e26ca11fdccc09cde69d1f"]
    v125_post_merge_main_run_id: Literal[33829039148]
    v125_report_sha256: str
    v125_report_hash: str
    v125_probe_sha256: str
    v125_probe_hash: str
    v125_readiness_poll_count: Literal[16]
    v125_cleanup_sha256: str
    v125_cleanup_hash: str
    v125_evidence_directory_count: Literal[1]
    v125_evidence_regular_file_count: Literal[8]
    v125_evidence_symlink_count: Literal[0]
    v126_audit_sha256: str
    v126_audit_commit: Literal["084afb7c6e690f222d8274871c4fcc51ecf1a56a"]
    v126_post_merge_main_run_id: Literal[33830266674]
    v126_post_merge_main_all_eight_classes_passed: Literal[True]
    schedule_source: Literal["exact-audited-v118-manifest"]
    schedule_task_ids: list[str] = Field(min_length=5, max_length=5)
    seed: Literal[502]
    sample_index: Literal[18]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v127-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v127-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v127/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v127/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v127-control"
    ]
    runtime_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v127-runtime"
    ]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v127-readiness-gated-scaffold-v1"
    ]
    nested_docker_host: Literal[
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v127/socket/docker.sock"
    ]
    dind_owner: Literal["deepseek-harness-hwe-v127-readiness-gated-scaffold-v1"]
    startup_attempt_limit: Literal[1]
    startup_command_timeout_seconds: Literal[60]
    readiness_timeout_seconds: Literal[120]
    readiness_command_timeout_seconds: Literal[5]
    readiness_poll_interval_seconds: Literal[1]
    readiness_probe_policy: Literal["explicit-three-field-exact-monotonic-deadline-v1"]
    json_info_readiness_allowed: Literal[False]
    fixed_poll_count_cap_allowed: Literal[False]
    explicit_readiness_requires_empty_stderr: Literal[True]
    explicit_readiness_requires_three_values: Literal[True]
    explicit_readiness_requires_exact_identity: Literal[True]
    docker_host_binding_policy: Literal["explicit-canonical-local-unix-socket-v1"]
    docker_cli_explicit_binding_required: Literal[True]
    harness_helper_explicit_binding_required: Literal[True]
    inherited_docker_environment_allowed: Literal[False]
    remote_docker_endpoint_allowed: Literal[False]
    inner_inventory_transport_policy: Literal["explicit-bound-engine-all-resources-v1"]
    inner_inventory_all_containers_required: Literal[True]
    inner_inventory_all_volumes_required: Literal[True]
    host_sidecar_inventory_for_inner_allowed: Literal[False]
    inner_network_transport_policy: Literal["explicit-bound-engine-v1"]
    host_sidecar_network_control_for_inner_allowed: Literal[False]
    streaming_attach_explicit_binding_required: Literal[True]
    fresh_bind_backed_volumes_required: Literal[True]
    predecessor_volume_inspection_allowed: Literal[False]
    predecessor_volume_mutation_allowed: Literal[False]
    provider_successor_identity: Literal["deepseek-harness-hwe-v129-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    requires_independent_v128_audit: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v118_manifest_sha256",
        "v118_manifest_hash",
        "v118_runner_sha256",
        "v118_authorization_sha256",
        "v119_audit_sha256",
        "v125_manifest_sha256",
        "v125_manifest_hash",
        "v125_runner_sha256",
        "v125_authorization_sha256",
        "v125_report_sha256",
        "v125_report_hash",
        "v125_probe_sha256",
        "v125_probe_hash",
        "v125_cleanup_sha256",
        "v125_cleanup_hash",
        "v126_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v127_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v127 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_v127_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v127 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_v127_identity(self) -> Self:
        if tuple(self.schedule_task_ids) != V71_MATRIX_TASK_IDS:
            raise ValueError("v127 scaffold schedule changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v127 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV130BoundedCommandScanProbeManifest(StrictModel):
    """One-use provider-free probe for the VFS command-image create boundary."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v130_bounded_command_scan_probe_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1"]
    v127_manifest_sha256: str
    v127_manifest_hash: str
    v127_runner_sha256: str
    v127_authorization_sha256: str
    v127_source_commit: Literal["def5d9d086203c83e39842534c999c5004dc27f1"]
    v127_post_merge_main_run_id: Literal[33832410957]
    v127_report_sha256: str
    v127_report_hash: str
    v127_runtime_receipt_sha256: str
    v127_runtime_receipt_hash: str
    v127_archive_receipt_sha256: str
    v127_archive_receipt_hash: str
    v127_source_lock_sha256: str
    v127_source_lock_hash: str
    v127_failed_scan_sha256: str
    v127_failed_scan_id: str
    v127_failed_diagnostic_hash: str
    v127_derived_command_image_id: str
    v127_cleanup_sha256: str
    v127_cleanup_hash: str
    v127_evidence_directory_count: Literal[81]
    v127_evidence_regular_file_count: Literal[281]
    v127_evidence_symlink_count: Literal[0]
    v128_audit_sha256: str
    v128_audit_merge: Literal["dafe5a4fd3a5b64690a9b352ffc93556abba7425"]
    v128_post_merge_main_run_id: Literal[33835870104]
    v128_post_merge_main_all_eight_classes_passed: Literal[True]
    task_id: Literal["hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465"]
    archive_root: Literal["/data2/jiadongzhu/Agent/hwe-bench-public-images"]
    archive_relpath: Literal["docker-tar-archives/lowrisc_m_ibex/pr-465.tar"]
    archive_sha256_relpath: Literal["docker-tar-archives/lowrisc_m_ibex/pr-465.tar.sha256"]
    archive_sha256: str
    registry_digest_relpath: Literal["digest-locks/lowrisc_m_ibex/pr-465.digest"]
    registry_manifest_digest: str
    image_config_digest: str
    official_verifier_image: str
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v130-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v130-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v130/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v130/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1"
    ]
    runtime_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v130-runtime"
    ]
    nested_docker_host: Literal[
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v130/socket/docker.sock"
    ]
    scanner_policy_id: Literal["deepseek-harness-v130-bounded-command-scan-v1"]
    scanner_container_name: Literal["verigym-hwe-v130-command-scan-pr-465"]
    create_timeout_seconds: Literal[300]
    inspect_timeout_seconds: Literal[60]
    start_timeout_seconds: Literal[180]
    remove_timeout_seconds: Literal[120]
    overall_timeout_seconds: Literal[720]
    startup_attempt_limit: Literal[1]
    startup_command_timeout_seconds: Literal[60]
    readiness_timeout_seconds: Literal[120]
    readiness_command_timeout_seconds: Literal[5]
    readiness_poll_interval_seconds: Literal[1]
    task_archive_access_allowed: Literal[True]
    task_image_import_allowed: Literal[True]
    command_image_build_allowed: Literal[True]
    task_execution_allowed: Literal[False]
    base_reference_verification_allowed: Literal[False]
    harness_controller_allowed: Literal[False]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    predecessor_volume_inspection_allowed: Literal[False]
    predecessor_volume_mutation_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    provider_request_started: Literal[False]
    provider_calls: Literal[0]
    requires_independent_v131_audit: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v127_manifest_sha256",
        "v127_manifest_hash",
        "v127_runner_sha256",
        "v127_authorization_sha256",
        "v127_report_sha256",
        "v127_report_hash",
        "v127_runtime_receipt_sha256",
        "v127_runtime_receipt_hash",
        "v127_archive_receipt_sha256",
        "v127_archive_receipt_hash",
        "v127_source_lock_sha256",
        "v127_source_lock_hash",
        "v127_failed_scan_sha256",
        "v127_failed_scan_id",
        "v127_failed_diagnostic_hash",
        "v127_cleanup_sha256",
        "v127_cleanup_hash",
        "v128_audit_sha256",
        "archive_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v130_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v130 command-scan probe manifest requires lowercase SHA-256")
        return value

    @field_validator(
        "v127_derived_command_image_id",
        "registry_manifest_digest",
        "image_config_digest",
        "official_verifier_image",
        "dind_image_id",
        "dind_repository_digest",
    )
    @classmethod
    def validate_v130_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v130 command-scan probe manifest requires immutable digests")
        return value

    @model_validator(mode="after")
    def validate_v130_identity(self) -> Self:
        if self.image_config_digest != self.official_verifier_image:
            raise ValueError("v130 command-scan probe verifier image binding changed")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v130 command-scan probe manifest content hash changed")
        return self


class DeepSeekHarnessV132BoundedScanScaffoldManifest(StrictModel):
    """One-use five-task scaffold with the audited bounded command-image scanner."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v132_bounded_scan_scaffold_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"]
    v127_manifest_sha256: str
    v127_manifest_hash: str
    v127_runner_sha256: str
    v127_authorization_sha256: str
    v127_source_commit: Literal["def5d9d086203c83e39842534c999c5004dc27f1"]
    v127_post_merge_main_run_id: Literal[33832410957]
    v128_audit_sha256: str
    v128_audit_merge: Literal["dafe5a4fd3a5b64690a9b352ffc93556abba7425"]
    v128_post_merge_main_run_id: Literal[33835870104]
    v130_manifest_sha256: str
    v130_manifest_hash: str
    v130_runner_sha256: str
    v130_authorization_sha256: str
    v130_source_commit: Literal["f0b94f4d27cccc00b49e6ffcf156f0eddfac0983"]
    v130_post_merge_main_run_id: Literal[33844057740]
    v130_report_sha256: str
    v130_report_hash: str
    v130_security_scan_sha256: str
    v130_security_scan_id: str
    v130_scan_diagnostic_hash: str
    v130_command_lock_sha256: str
    v130_command_lock_hash: str
    v130_runtime_receipt_sha256: str
    v130_runtime_receipt_hash: str
    v130_cleanup_sha256: str
    v130_cleanup_hash: str
    v130_late_cleanup_sha256: str
    v130_late_cleanup_hash: str
    v130_evidence_directory_count: Literal[5]
    v130_evidence_regular_file_count: Literal[15]
    v130_evidence_symlink_count: Literal[0]
    v131_audit_sha256: str
    v131_audit_merge: Literal["5c0022521ffd513c726a4d0f8d0a6f02e94eaecf"]
    v131_post_merge_main_run_id: Literal[33846866494]
    v131_post_merge_main_all_eight_classes_passed: Literal[True]
    schedule_source: Literal["exact-audited-v127-manifest"]
    schedule_task_ids: list[str] = Field(min_length=5, max_length=5)
    seed: Literal[502]
    sample_index: Literal[18]
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v132-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v132-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v132-control"
    ]
    runtime_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v132-runtime"
    ]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"
    ]
    nested_docker_host: Literal[
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v132/socket/docker.sock"
    ]
    dind_owner: Literal["deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"]
    startup_attempt_limit: Literal[1]
    startup_command_timeout_seconds: Literal[60]
    readiness_timeout_seconds: Literal[120]
    readiness_command_timeout_seconds: Literal[5]
    readiness_poll_interval_seconds: Literal[1]
    readiness_probe_policy: Literal["explicit-three-field-exact-monotonic-deadline-v1"]
    scanner_policy_source: Literal["exact-audited-v130-policy"]
    scanner_policy_id: Literal["deepseek-harness-v132-bounded-command-scan-v1"]
    scanner_container_prefix: Literal["verigym-hwe-v132-command-scan-pr-"]
    scanner_create_timeout_seconds: Literal[300]
    scanner_inspect_timeout_seconds: Literal[60]
    scanner_start_timeout_seconds: Literal[180]
    scanner_remove_timeout_seconds: Literal[120]
    scanner_overall_timeout_seconds: Literal[720]
    scanner_all_five_tasks_required: Literal[True]
    scanner_deterministic_owner_cleanup_required: Literal[True]
    scanner_nonempty_output_hashing_allowed: Literal[False]
    json_info_readiness_allowed: Literal[False]
    fixed_poll_count_cap_allowed: Literal[False]
    docker_cli_explicit_binding_required: Literal[True]
    harness_helper_explicit_binding_required: Literal[True]
    inherited_docker_environment_allowed: Literal[False]
    remote_docker_endpoint_allowed: Literal[False]
    inner_inventory_all_containers_required: Literal[True]
    inner_inventory_all_volumes_required: Literal[True]
    host_sidecar_inventory_for_inner_allowed: Literal[False]
    host_sidecar_network_control_for_inner_allowed: Literal[False]
    streaming_attach_explicit_binding_required: Literal[True]
    fresh_bind_backed_volumes_required: Literal[True]
    predecessor_volume_inspection_allowed: Literal[False]
    predecessor_volume_mutation_allowed: Literal[False]
    failed_data_volume_policy: Literal["freeze-exact-owned-volume"]
    provider_successor_identity: Literal["deepseek-harness-hwe-v134-official-matrix-v1"]
    provider_successor_reopen_budget: Literal[1]
    registry_access_allowed: Literal[False]
    partial_archive_allowed: Literal[False]
    provider_credentials_available: Literal[False]
    requires_independent_v133_audit: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "v127_manifest_sha256",
        "v127_manifest_hash",
        "v127_runner_sha256",
        "v127_authorization_sha256",
        "v128_audit_sha256",
        "v130_manifest_sha256",
        "v130_manifest_hash",
        "v130_runner_sha256",
        "v130_authorization_sha256",
        "v130_report_sha256",
        "v130_report_hash",
        "v130_security_scan_sha256",
        "v130_security_scan_id",
        "v130_scan_diagnostic_hash",
        "v130_command_lock_sha256",
        "v130_command_lock_hash",
        "v130_runtime_receipt_sha256",
        "v130_runtime_receipt_hash",
        "v130_cleanup_sha256",
        "v130_cleanup_hash",
        "v130_late_cleanup_sha256",
        "v130_late_cleanup_hash",
        "v131_audit_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v132_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v132 scaffold manifest requires lowercase SHA-256")
        return value

    @field_validator("dind_image_id", "dind_repository_digest")
    @classmethod
    def validate_v132_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v132 scaffold manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_v132_identity(self) -> Self:
        if tuple(self.schedule_task_ids) != V71_MATRIX_TASK_IDS:
            raise ValueError("v132 scaffold schedule changed")
        if self.scanner_overall_timeout_seconds != sum(
            (
                self.scanner_create_timeout_seconds,
                2 * self.scanner_inspect_timeout_seconds,
                self.scanner_start_timeout_seconds,
                self.scanner_remove_timeout_seconds,
            )
        ):
            raise ValueError("v132 scanner operation and overall bounds differ")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v132 scaffold manifest content hash changed")
        return self


class DeepSeekHarnessV134TaskBinding(DeepSeekHarnessV92TaskBinding):
    """One immutable v132-derived task/source/image binding for v134."""


class DeepSeekHarnessV134OfficialMatrixManifest(StrictModel):
    """One-use official five-task provider matrix authorized by the v133 audit."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v134_official_matrix_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v134-official-matrix-v1"]
    protocol_baseline_identity: Literal["deepseek-harness-hwe-v92-official-matrix-v1"]
    protocol_baseline_manifest_sha256: str
    protocol_baseline_manifest_hash: str
    protocol_baseline_runner_sha256: str
    v132_manifest_sha256: str
    v132_manifest_hash: str
    v132_report_sha256: str
    v132_report_hash: str
    v132_contract_sha256: str
    v132_contract_hash: str
    v132_task_set_sha256: str
    v132_task_set_hash: str
    v132_inventory_sha256: str
    v132_inventory_hash: str
    v132_final_inventory_sha256: str
    v132_final_inventory_hash: str
    v132_image_transfer_set_sha256: str
    v132_image_transfer_set_hash: str
    v132_controller_receipt_sha256: str
    v132_controller_receipt_hash: str
    v132_workspace_runtime_receipt_sha256: str
    v132_workspace_runtime_receipt_hash: str
    v132_runtime_preflight_sha256: str
    v132_runtime_preflight_hash: str
    v132_harness_preflight_sha256: str
    v132_harness_preflight_hash: str
    v132_runtime_receipt_sha256: str
    v132_runtime_receipt_hash: str
    v132_cleanup_receipt_sha256: str
    v132_cleanup_receipt_hash: str
    v132_evidence_directory_count: Literal[1782]
    v132_evidence_regular_file_count: Literal[10481]
    v132_evidence_symlink_count: Literal[0]
    v133_audit_sha256: str
    v133_audit_commit: Literal["270fc62c2b6c9d970b435609607a2e24c13aac87"]
    v133_audit_merge: Literal["7fe5de7dd116b01e9e74925aea5af11327924094"]
    v133_post_merge_main_run_id: Literal[33852258490]
    v133_post_merge_main_all_eight_classes_passed: Literal[True]
    source_preparation_docker_control_timeout_seconds: Literal[300]
    schedule: list[DeepSeekHarnessV134TaskBinding] = Field(min_length=5, max_length=5)
    provider: Literal["deepseek-official"]
    model: Literal["deepseek-v4-flash"]
    harness_version: Literal["0.1.1-rc.2"]
    integration_version: Literal["0.5.0"]
    harness_revision: Literal["b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"]
    seed: Literal[502]
    sample_index: Literal[18]
    max_provider_calls_per_task: Literal[64]
    max_provider_tokens_per_task: Literal[1000000]
    max_context_tokens: Literal[65536]
    max_output_tokens: Literal[2048]
    temperature: Literal[0]
    provider_request_retries: Literal[0]
    whole_episode_retries: Literal[0]
    ordinary_tool_choice: Literal["auto"]
    public_rationale_allowed: Literal[True]
    sibling_calls_allowed: Literal[True]
    provider_hidden_thinking: Literal["disabled"]
    foreign_tools_rejected: Literal[True]
    illegal_paths_rejected: Literal[True]
    unpaired_observations_rejected: Literal[True]
    decision_only_loss_mask: Literal[True]
    exact_tokenizer_hash: str
    base_model_snapshot_hash: str
    base_model_lock_sha256: str
    dind_image_id: str
    dind_repository_digest: str
    dind_server_version: Literal["23.0.6"]
    dind_storage_driver: Literal["vfs"]
    dind_default_runtime: Literal["runc"]
    dind_data_volume: Literal["verigym-deepseek-harness-v132-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v132-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/socket"]
    control_headroom_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v134-control"
    ]
    runtime_scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v134-runtime"
    ]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v134-official-matrix-v1"
    ]
    nested_docker_host: Literal[
        "unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v132/socket/docker.sock"
    ]
    predecessor_data_volume_owner: Literal["deepseek-harness-hwe-v132-bounded-scan-scaffold-v1"]
    runtime_resource_owner: Literal["deepseek-harness-hwe-v134-official-matrix-v1"]
    provider_outer_network: Literal["verigym-hwe-net"]
    provider_inner_network: Literal["verigym-hwe-net"]
    task_network: Literal["none"]
    verifier_network: Literal["none"]
    controller_image_tag: Literal["node:22.19.0-bookworm-slim"]
    controller_image_id: str
    controller_image_repository_digest: str
    workspace_runtime_image_id: str
    controller_image_provenance: Literal["audited_v132_offline_transfer_v1"]
    v132_data_volume_reopen_budget: Literal[1]
    v132_data_volume_reopen_count_before: Literal[0]
    atomic_progress: Literal[True]
    zero_partial_authorization: Literal[True]
    deterministic_task_order: Literal[True]
    stop_on_infrastructure_or_security_failure: Literal[True]
    continue_after_ordinary_model_or_verifier_failure: Literal[True]
    consecutive_no_progress_stop_limit: Literal[2]
    requires_independent_v135_audit: Literal[True]
    formal_collection_allowed: Literal[False]
    formal_collection_started: Literal[False]
    collection_started: Literal[False]
    training_started: Literal[False]
    production_training_ready: Literal[False]
    manifest_hash: str

    @field_validator(
        "protocol_baseline_manifest_sha256",
        "protocol_baseline_manifest_hash",
        "protocol_baseline_runner_sha256",
        "v132_manifest_sha256",
        "v132_manifest_hash",
        "v132_report_sha256",
        "v132_report_hash",
        "v132_contract_sha256",
        "v132_contract_hash",
        "v132_task_set_sha256",
        "v132_task_set_hash",
        "v132_inventory_sha256",
        "v132_inventory_hash",
        "v132_final_inventory_sha256",
        "v132_final_inventory_hash",
        "v132_image_transfer_set_sha256",
        "v132_image_transfer_set_hash",
        "v132_controller_receipt_sha256",
        "v132_controller_receipt_hash",
        "v132_workspace_runtime_receipt_sha256",
        "v132_workspace_runtime_receipt_hash",
        "v132_runtime_preflight_sha256",
        "v132_runtime_preflight_hash",
        "v132_harness_preflight_sha256",
        "v132_harness_preflight_hash",
        "v132_runtime_receipt_sha256",
        "v132_runtime_receipt_hash",
        "v132_cleanup_receipt_sha256",
        "v132_cleanup_receipt_hash",
        "v133_audit_sha256",
        "exact_tokenizer_hash",
        "base_model_snapshot_hash",
        "base_model_lock_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_v134_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v134 official matrix manifest requires lowercase SHA-256")
        return value

    @field_validator(
        "dind_image_id",
        "dind_repository_digest",
        "controller_image_id",
        "controller_image_repository_digest",
        "workspace_runtime_image_id",
    )
    @classmethod
    def validate_v134_digest(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("v134 official matrix manifest requires immutable image digests")
        return value

    @model_validator(mode="after")
    def validate_v134_identity(self) -> Self:
        if tuple(item.task_id for item in self.schedule) != V71_MATRIX_TASK_IDS:
            raise ValueError("v134 official matrix schedule changed")
        if any(
            item.seed != self.seed or item.sample_index != self.sample_index
            for item in self.schedule
        ):
            raise ValueError("v134 task seed/sample differs from the matrix identity")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v134 official matrix manifest content hash changed")
        return self


class HweAdmissionPlanes(StrictModel):
    """Independent result planes required for SFT admission."""

    benchmark_verifier_pass: bool
    agent_protocol_valid: bool
    trajectory_eligible: bool
    infrastructure_valid: bool
    security_valid: bool
    sft_admitted: bool

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        prerequisites = (
            self.benchmark_verifier_pass
            and self.agent_protocol_valid
            and self.trajectory_eligible
            and self.infrastructure_valid
            and self.security_valid
        )
        if self.sft_admitted != prerequisites:
            raise ValueError("SFT admission must equal the conjunction of its five result planes")
        return self


class DeepSeekHarnessMatrixAttempt(StrictModel):
    """Sanitized receipt for one v71 or open-tool canary attempt."""

    task_id: str
    repository: Repository
    agent_toolchain_id: str
    official_verifier_image: str
    provider_marker: ProviderMarker
    provider_call_count: int = Field(ge=0, le=64)
    provider_total_tokens: int = Field(ge=0, le=1_000_000)
    first_effective_modification_action: int | None = Field(default=None, ge=1, le=64)
    outcome: AttemptOutcome
    planes: HweAdmissionPlanes
    exact_64k_eligible: bool
    maximum_decision_tokens: int | None = Field(default=None, ge=1, le=65_536)
    truncation_applied: Literal[False]
    decision_only_loss_mask: bool

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        if _TASK_ID.fullmatch(value) is None:
            raise ValueError("matrix attempt task ID is invalid")
        return value

    @field_validator("agent_toolchain_id")
    @classmethod
    def validate_toolchain_id(cls, value: str) -> str:
        if _SAFE_ID.fullmatch(value) is None:
            raise ValueError("matrix attempt toolchain ID is invalid")
        return value

    @field_validator("official_verifier_image")
    @classmethod
    def validate_verifier_image(cls, value: str) -> str:
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("matrix attempt verifier image is not immutable")
        return value

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        expected_repository = "ibex" if "lowRISC__ibex" in self.task_id else "cva6"
        if self.repository != expected_repository:
            raise ValueError("matrix task and repository differ")
        if self.provider_marker == "not_started" and (
            self.provider_call_count != 0 or self.provider_total_tokens != 0
        ):
            raise ValueError("pre-provider attempt cannot report provider consumption")
        if self.provider_marker == "started_valid" and self.provider_call_count < 1:
            raise ValueError("started provider marker requires a provider call")
        if self.exact_64k_eligible:
            if (
                self.maximum_decision_tokens is None
                or not self.decision_only_loss_mask
                or not self.planes.trajectory_eligible
            ):
                raise ValueError("exact-64K admission lacks its decision evidence")
        elif self.planes.sft_admitted:
            raise ValueError("SFT admission requires exact-64K eligibility")
        if self.outcome == "passed" and not self.planes.sft_admitted:
            raise ValueError("a passing attempt must pass all six planes")
        if self.outcome in {"infrastructure_failure", "security_failure"}:
            valid = (
                self.planes.infrastructure_valid
                if self.outcome == "infrastructure_failure"
                else self.planes.security_valid
            )
            if valid:
                raise ValueError("failure outcome disagrees with its result plane")
        return self


class DeepSeekHarnessMatrixState(StrictModel):
    """Atomic progress state for the fixed v71 matrix."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_matrix_progress_v1"] = (
        "verigym_deepseek_harness_hwe_matrix_progress_v1"
    )
    schedule: list[str] = Field(min_length=1, max_length=16)
    next_index: int = Field(ge=0)
    consecutive_no_progress: int = Field(ge=0, le=2)
    status: Literal["running", "completed", "stopped"]
    stop_reason: str | None = None
    attempts: list[dict[str, Any]] = Field(default_factory=list, max_length=16)
    formal_collection_allowed: Literal[False] = False
    formal_collection_started: Literal[False] = False
    collection_started: Literal[False] = False
    training_started: Literal[False] = False
    production_training_ready: Literal[False] = False

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if len(self.schedule) != len(set(self.schedule)):
            raise ValueError("matrix schedule contains duplicate tasks")
        if self.next_index > len(self.schedule) or len(self.attempts) != self.next_index:
            raise ValueError("matrix progress index and attempt count differ")
        if self.status == "running" and self.next_index >= len(self.schedule):
            raise ValueError("a finished matrix cannot remain running")
        if self.status == "completed" and self.next_index != len(self.schedule):
            raise ValueError("an incomplete matrix cannot be completed")
        if (self.status == "stopped") != (self.stop_reason is not None):
            raise ValueError("matrix stop status and reason differ")
        return self


def new_matrix_state(
    schedule: Sequence[str] = V71_MATRIX_TASK_IDS,
) -> DeepSeekHarnessMatrixState:
    """Create new deterministic campaign state without starting a provider."""

    if not schedule:
        raise ConfigurationError("DeepSeek Harness matrix schedule must not be empty")
    return DeepSeekHarnessMatrixState(
        schedule=list(schedule),
        next_index=0,
        consecutive_no_progress=0,
        status="running",
    )


def record_matrix_attempt(
    state: DeepSeekHarnessMatrixState,
    attempt: DeepSeekHarnessMatrixAttempt,
) -> DeepSeekHarnessMatrixState:
    """Apply the frozen provider-boundary and bounded-continuation policy."""

    if state.status != "running" or state.schedule[state.next_index] != attempt.task_id:
        raise ConfigurationError("DeepSeek Harness matrix attempt is out of order")
    provider_proven_not_started = attempt.provider_marker == "not_started"
    infrastructure_or_security = attempt.outcome in {
        "infrastructure_failure",
        "security_failure",
    }
    consumed = not (provider_proven_not_started and infrastructure_or_security)
    stop_reason: str | None = None
    if infrastructure_or_security:
        boundary = "pre_provider" if provider_proven_not_started else "post_provider"
        stop_reason = f"{boundary}_{attempt.outcome}"

    no_progress_outcomes = {
        "no_effective_modification",
        "no_progress",
        "trajectory_structure_failure",
    }
    consecutive = (
        state.consecutive_no_progress + 1 if attempt.outcome in no_progress_outcomes else 0
    )
    if stop_reason is None and consecutive >= 2:
        stop_reason = "two_consecutive_no_progress_or_trajectory_failures"

    receipt = {
        "task_id": attempt.task_id,
        "repository": attempt.repository,
        "provider_marker": attempt.provider_marker,
        "provider_consumed": consumed,
        "outcome": attempt.outcome,
        "first_effective_modification_action": attempt.first_effective_modification_action,
        "planes": attempt.planes.model_dump(mode="json"),
        "exact_64k_eligible": attempt.exact_64k_eligible,
        "agent_toolchain_id": attempt.agent_toolchain_id,
        "official_verifier_image": attempt.official_verifier_image,
    }
    next_index = state.next_index + 1
    status: Literal["running", "completed", "stopped"]
    if stop_reason is not None:
        status = "stopped"
    elif next_index == len(state.schedule):
        status = "completed"
    else:
        status = "running"
    return state.model_copy(
        update={
            "next_index": next_index,
            "consecutive_no_progress": min(consecutive, 2),
            "status": status,
            "stop_reason": stop_reason,
            "attempts": [*copy.deepcopy(state.attempts), receipt],
        },
        deep=True,
    )


def migration_conclusions(
    attempts: Sequence[DeepSeekHarnessMatrixAttempt],
) -> dict[str, bool | int]:
    """Report trajectory and SFT migration independently, never as a benchmark score."""

    useful = [
        item
        for item in attempts
        if item.planes.agent_protocol_valid
        and item.planes.trajectory_eligible
        and item.planes.infrastructure_valid
        and item.planes.security_valid
        and item.first_effective_modification_action is not None
    ]
    sft = [item for item in attempts if item.planes.sft_admitted and item.exact_64k_eligible]
    ibex_useful = sum(item.repository == "ibex" for item in useful)
    cva6_useful = sum(item.repository == "cva6" for item in useful)
    ibex_sft = sum(item.repository == "ibex" for item in sft)
    cva6_sft = sum(item.repository == "cva6" for item in sft)
    return {
        "ibex_trajectory_count": ibex_useful,
        "cva6_trajectory_count": cva6_useful,
        "trajectory_collection_migratable": ibex_useful >= 2 and cva6_useful >= 1,
        "ibex_sft_count": ibex_sft,
        "cva6_sft_count": cva6_sft,
        "sft_path_migratable": ibex_sft >= 1 and cva6_sft >= 1,
    }


def require_toolchain_verifier_binding(
    *,
    attempt: Mapping[str, Any],
    expected_agent_toolchain_id: str,
    expected_official_verifier_image: str,
) -> None:
    """Prevent agent diagnostics from being reported as an official verifier result."""

    if (
        attempt.get("agent_toolchain_id") != expected_agent_toolchain_id
        or attempt.get("official_verifier_image") != expected_official_verifier_image
        or attempt.get("official_verifier_executed") is not True
        or attempt.get("agent_diagnostic_result_role") != "agent_only_non_authoritative"
        or attempt.get("official_verifier_result_role") != "benchmark_authoritative"
        or attempt.get("agent_diagnostic_receipt_hash")
        == attempt.get("official_verifier_receipt_hash")
    ):
        raise ConfigurationError("agent toolchain and official verifier identities are confused")


def load_v69_manifest(path: Path) -> DeepSeekHarnessV69Manifest:
    """Load a bounded ordinary-file manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v69 manifest path is unsafe")
    try:
        return DeepSeekHarnessV69Manifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v69 manifest is invalid") from exc


def load_v71_dind_successor_manifest(path: Path) -> DeepSeekHarnessV71DindSuccessorManifest:
    """Load a bounded ordinary-file successor authorization manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v71 successor manifest path is unsafe")
    try:
        return DeepSeekHarnessV71DindSuccessorManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v71 successor manifest is invalid") from exc


def load_v73_dind_successor_manifest(path: Path) -> DeepSeekHarnessV73DindSuccessorManifest:
    """Load the bounded v73 clean-room successor authorization manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v73 successor manifest path is unsafe")
    try:
        return DeepSeekHarnessV73DindSuccessorManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v73 successor manifest is invalid") from exc


def load_v75_dind_successor_manifest(path: Path) -> DeepSeekHarnessV75DindSuccessorManifest:
    """Load the bounded v75 scanner-path successor authorization manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v75 successor manifest path is unsafe")
    try:
        return DeepSeekHarnessV75DindSuccessorManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v75 successor manifest is invalid") from exc


def load_v77_dind_successor_manifest(path: Path) -> DeepSeekHarnessV77DindSuccessorManifest:
    """Load the bounded v77 CVA6 source-profile successor authorization manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v77 successor manifest path is unsafe")
    try:
        return DeepSeekHarnessV77DindSuccessorManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v77 successor manifest is invalid") from exc


def load_v79_dind_successor_manifest(path: Path) -> DeepSeekHarnessV79DindSuccessorManifest:
    """Load the bounded v79 runtime-baseline successor authorization manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v79 successor manifest path is unsafe")
    try:
        return DeepSeekHarnessV79DindSuccessorManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v79 successor manifest is invalid") from exc


def load_v81_execution_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV81ExecutionScaffoldManifest:
    """Load the bounded v81 credential-free execution-scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v81 scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV81ExecutionScaffoldManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v81 scaffold manifest is invalid") from exc


def load_v83_execution_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV83ExecutionScaffoldManifest:
    """Load the bounded v83 credential-free execution-scaffold successor manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v83 scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV83ExecutionScaffoldManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v83 scaffold manifest is invalid") from exc


def load_v85_official_matrix_manifest(path: Path) -> DeepSeekHarnessV85OfficialMatrixManifest:
    """Load the bounded one-use v85 official provider-matrix manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v85 official matrix manifest path is unsafe")
    try:
        return DeepSeekHarnessV85OfficialMatrixManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v85 official matrix manifest is invalid") from exc


def load_v87_fresh_scaffold_manifest(path: Path) -> DeepSeekHarnessV87FreshScaffoldManifest:
    """Load the bounded one-use v87 zero-provider scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v87 fresh scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV87FreshScaffoldManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v87 fresh scaffold manifest is invalid") from exc


def load_v90_fresh_scaffold_manifest(path: Path) -> DeepSeekHarnessV90FreshScaffoldManifest:
    """Load the bounded one-use v90 zero-provider scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v90 fresh scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV90FreshScaffoldManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v90 fresh scaffold manifest is invalid") from exc


def load_v92_official_matrix_manifest(path: Path) -> DeepSeekHarnessV92OfficialMatrixManifest:
    """Load the bounded one-use v92 official provider-matrix manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v92 official matrix manifest path is unsafe")
    try:
        return DeepSeekHarnessV92OfficialMatrixManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v92 official matrix manifest is invalid") from exc


def load_v94_runtime_complete_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV94RuntimeCompleteScaffoldManifest:
    """Load the bounded one-use v94 runtime-complete zero-provider scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v94 runtime-complete scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV94RuntimeCompleteScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v94 runtime-complete scaffold manifest is invalid") from exc


def load_v97_rebuild_identity_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV97RebuildIdentityScaffoldManifest:
    """Load the bounded one-use v97 rebuild-identity zero-provider scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v97 rebuild-identity scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV97RebuildIdentityScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v97 rebuild-identity scaffold manifest is invalid") from exc


def load_v100_inventory_timeout_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV100InventoryTimeoutScaffoldManifest:
    """Load the bounded one-use v100 task-inventory-timeout scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v100 inventory-timeout scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV100InventoryTimeoutScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v100 inventory-timeout scaffold manifest is invalid") from exc


def load_v103_inspect_output_bound_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV103InspectOutputBoundScaffoldManifest:
    """Load the bounded one-use v103 task-inventory-inspect scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v103 inspect-output-bound scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV103InspectOutputBoundScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v103 inspect-output-bound scaffold manifest is invalid") from exc


def load_v106_fresh_inventory_binding_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest:
    """Load the bounded one-use v106 fresh-inventory-binding scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v106 fresh-inventory-binding scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError(
            "v106 fresh-inventory-binding scaffold manifest is invalid"
        ) from exc


def load_v109_progress_writer_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV109ProgressWriterScaffoldManifest:
    """Load the bounded one-use v109 progress-writer scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v109 progress-writer scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV109ProgressWriterScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v109 progress-writer scaffold manifest is invalid") from exc


def load_v112_data2_control_headroom_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest:
    """Load the bounded one-use v112 data2-control-headroom scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v112 data2-control-headroom scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError(
            "v112 data2-control-headroom scaffold manifest is invalid"
        ) from exc


def load_v115_explicit_nested_docker_socket_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV115ExplicitNestedDockerSocketScaffoldManifest:
    """Load the one-use v115 explicit nested-Docker-socket scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v115 nested-Docker-socket scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV115ExplicitNestedDockerSocketScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v115 nested-Docker-socket scaffold manifest is invalid") from exc


def load_v118_explicit_inner_inventory_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV118ExplicitInnerInventoryScaffoldManifest:
    """Load the one-use v118 explicit inner-inventory scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v118 explicit inner-inventory scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV118ExplicitInnerInventoryScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError(
            "v118 explicit inner-inventory scaffold manifest is invalid"
        ) from exc


def load_v121_bounded_dind_start_diagnostic_manifest(
    path: Path,
) -> DeepSeekHarnessV121BoundedDindStartDiagnosticManifest:
    """Load the one-use v121 provider-free DinD startup diagnostic manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v121 DinD startup diagnostic manifest path is unsafe")
    try:
        return DeepSeekHarnessV121BoundedDindStartDiagnosticManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v121 DinD startup diagnostic manifest is invalid") from exc


def load_v123_bounded_dind_identity_probe_manifest(
    path: Path,
) -> DeepSeekHarnessV123BoundedDindIdentityProbeManifest:
    """Load the one-use v123 provider-free DinD identity-probe manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v123 DinD identity-probe manifest path is unsafe")
    try:
        return DeepSeekHarnessV123BoundedDindIdentityProbeManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v123 DinD identity-probe manifest is invalid") from exc


def load_v125_bounded_dind_readiness_probe_manifest(
    path: Path,
) -> DeepSeekHarnessV125BoundedDindReadinessProbeManifest:
    """Load the one-use v125 provider-free DinD readiness-probe manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v125 DinD readiness-probe manifest path is unsafe")
    try:
        return DeepSeekHarnessV125BoundedDindReadinessProbeManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v125 DinD readiness-probe manifest is invalid") from exc


def load_v127_readiness_gated_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV127ReadinessGatedScaffoldManifest:
    """Load the one-use v127 zero-provider readiness-gated scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v127 readiness-gated scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV127ReadinessGatedScaffoldManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v127 readiness-gated scaffold manifest is invalid") from exc


def load_v130_bounded_command_scan_probe_manifest(
    path: Path,
) -> DeepSeekHarnessV130BoundedCommandScanProbeManifest:
    """Load the one-use v130 provider-free command-image scan probe manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v130 command-scan probe manifest path is unsafe")
    try:
        return DeepSeekHarnessV130BoundedCommandScanProbeManifest.model_validate_json(
            path.read_bytes()
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v130 command-scan probe manifest is invalid") from exc


def load_v132_bounded_scan_scaffold_manifest(
    path: Path,
) -> DeepSeekHarnessV132BoundedScanScaffoldManifest:
    """Load the one-use v132 bounded-scanner five-task scaffold manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v132 bounded-scan scaffold manifest path is unsafe")
    try:
        return DeepSeekHarnessV132BoundedScanScaffoldManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v132 bounded-scan scaffold manifest is invalid") from exc


def load_v134_official_matrix_manifest(path: Path) -> DeepSeekHarnessV134OfficialMatrixManifest:
    """Load the bounded one-use v134 official provider-matrix manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v134 official matrix manifest path is unsafe")
    try:
        return DeepSeekHarnessV134OfficialMatrixManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v134 official matrix manifest is invalid") from exc


def inspect_offline_image_archive(
    lock: HweOfflineTaskLock,
    *,
    archive_root: Path,
) -> dict[str, Any]:
    """Validate one completed Docker/OCI-compatible image archive without registry access."""

    root = archive_root.resolve(strict=True)
    if archive_root.is_symlink() or not root.is_dir():
        raise ConfigurationError("HWE archive root is unsafe")
    archive = _contained_regular_file(root, lock.archive_relpath, maximum=_MAX_ARCHIVE_BYTES)
    sidecar = _contained_regular_file(root, lock.archive_sha256_relpath, maximum=1024)
    digest_lock = _contained_regular_file(root, lock.registry_digest_relpath, maximum=1024)
    expected_sidecar = f"{lock.archive_sha256}  {archive.name}\n".encode()
    if sidecar.read_bytes() != expected_sidecar:
        raise ConfigurationError("HWE archive SHA-256 sidecar changed")
    if digest_lock.read_bytes() != f"{lock.registry_manifest_digest}\n".encode():
        raise ConfigurationError("HWE registry manifest digest lock changed")
    if _hash_file(archive) != lock.archive_sha256:
        raise ConfigurationError("HWE completed archive SHA-256 changed")

    try:
        with tarfile.open(archive, mode="r:") as tar:
            members = tar.getmembers()
            if not 1 <= len(members) <= _MAX_ARCHIVE_MEMBERS:
                raise ConfigurationError("HWE archive inventory is unbounded")
            names = [member.name for member in members]
            if len(names) != len(set(names)) or any(
                not member.isfile() or not _safe_tar_name(member.name) for member in members
            ):
                raise ConfigurationError("HWE archive member is unsafe")
            if names.count("manifest.json") != 1:
                raise ConfigurationError("HWE archive manifest inventory changed")
            manifest_raw = _tar_bytes(tar, "manifest.json", maximum=1024 * 1024)
            manifest = json.loads(manifest_raw)
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise ConfigurationError("HWE archive manifest is malformed")
            entry = manifest[0]
            if not isinstance(entry, dict) or set(entry) != {"Config", "RepoTags", "Layers"}:
                raise ConfigurationError("HWE archive manifest fields changed")
            config_name = entry.get("Config")
            repo_tags = entry.get("RepoTags")
            layers = entry.get("Layers")
            if (
                config_name != lock.image_config_digest
                or repo_tags != [lock.archive_repository_tag]
                or not isinstance(layers, list)
                or not layers
                or len(layers) != len(set(layers))
                or any(not isinstance(item, str) or not _safe_layer_name(item) for item in layers)
            ):
                raise ConfigurationError("HWE archive image identity changed")
            expected_members = {"manifest.json", config_name, *layers}
            if set(names) != expected_members:
                raise ConfigurationError("HWE archive contains unexpected members")
            config = _tar_bytes(tar, config_name, maximum=4 * 1024 * 1024)
            if hashlib.sha256(config).hexdigest() != lock.image_config_digest.removeprefix(
                "sha256:"
            ):
                raise ConfigurationError("HWE archive config digest changed")
            config_value = json.loads(config)
            if not isinstance(config_value, dict):
                raise ConfigurationError("HWE archive config is malformed")
            working_dir = (config_value.get("config") or {}).get("WorkingDir")
            expected_working_dir = "/home/ibex" if lock.repository == "ibex" else "/home/cva6"
            if working_dir != expected_working_dir:
                raise ConfigurationError("HWE archive repository base changed")
    except (json.JSONDecodeError, tarfile.TarError, UnicodeError) as exc:
        raise ConfigurationError("HWE completed archive is malformed") from exc

    base = {
        "schema_version": SCHEMA_VERSION,
        "format_id": "verigym_hwe_offline_archive_receipt_v1",
        "task_id": lock.task_id,
        "archive_sha256": lock.archive_sha256,
        "archive_sha256_sidecar_valid": True,
        "registry_manifest_digest": lock.registry_manifest_digest,
        "registry_manifest_digest_lock_valid": True,
        "docker_archive_manifest_valid": True,
        "image_config_digest": lock.image_config_digest,
        "image_config_digest_valid": True,
        "official_verifier_image": lock.official_verifier_image,
        "repository_base": expected_working_dir,
        "repository_base_valid": True,
        "layer_count": len(layers),
        "registry_accessed": False,
        "partial_archive_used": False,
    }
    return {**base, "receipt_hash": content_hash(base)}


def _contained_regular_file(root: Path, relative: str, *, maximum: int) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("HWE archive input is not a regular file")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not 0 < resolved.stat().st_size <= maximum:
        raise ConfigurationError("HWE archive input escaped or exceeded its bound")
    return resolved


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_tar_name(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _safe_layer_name(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}\.tar\.gz", value))


def _tar_bytes(tar: tarfile.TarFile, name: str, *, maximum: int) -> bytes:
    member = tar.getmember(name)
    if not member.isfile() or not 0 < member.size <= maximum:
        raise ConfigurationError("HWE archive structured member is invalid")
    stream = tar.extractfile(member)
    if stream is None:
        raise ConfigurationError("HWE archive structured member is unavailable")
    value = stream.read(maximum + 1)
    if len(value) != member.size:
        raise ConfigurationError("HWE archive structured member size changed")
    return value


__all__ = [
    "DeepSeekHarnessMatrixAttempt",
    "DeepSeekHarnessMatrixState",
    "DeepSeekHarnessV69Manifest",
    "DeepSeekHarnessV71DindSuccessorManifest",
    "DeepSeekHarnessV73DindSuccessorManifest",
    "DeepSeekHarnessV75DindSuccessorManifest",
    "DeepSeekHarnessV77DindSuccessorManifest",
    "DeepSeekHarnessV79DindSuccessorManifest",
    "DeepSeekHarnessV81ExecutionScaffoldManifest",
    "DeepSeekHarnessV83ExecutionScaffoldManifest",
    "DeepSeekHarnessV85OfficialMatrixManifest",
    "DeepSeekHarnessV85TaskBinding",
    "DeepSeekHarnessV87FreshScaffoldManifest",
    "DeepSeekHarnessV90FreshScaffoldManifest",
    "DeepSeekHarnessV92OfficialMatrixManifest",
    "DeepSeekHarnessV92TaskBinding",
    "DeepSeekHarnessV94RuntimeCompleteScaffoldManifest",
    "DeepSeekHarnessV97RebuildIdentityScaffoldManifest",
    "DeepSeekHarnessV100InventoryTimeoutScaffoldManifest",
    "DeepSeekHarnessV103InspectOutputBoundScaffoldManifest",
    "DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest",
    "DeepSeekHarnessV109ProgressWriterScaffoldManifest",
    "DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest",
    "DeepSeekHarnessV115ExplicitNestedDockerSocketScaffoldManifest",
    "DeepSeekHarnessV118ExplicitInnerInventoryScaffoldManifest",
    "DeepSeekHarnessV121BoundedDindStartDiagnosticManifest",
    "DeepSeekHarnessV123BoundedDindIdentityProbeManifest",
    "DeepSeekHarnessV125BoundedDindReadinessProbeManifest",
    "DeepSeekHarnessV127ReadinessGatedScaffoldManifest",
    "DeepSeekHarnessV130BoundedCommandScanProbeManifest",
    "DeepSeekHarnessV132BoundedScanScaffoldManifest",
    "DeepSeekHarnessV134OfficialMatrixManifest",
    "DeepSeekHarnessV134TaskBinding",
    "HweAdmissionPlanes",
    "HweOfflineTaskLock",
    "HweTaskDisposition",
    "ProviderMarker",
    "V69_CVA6_FALLBACK_TASK_IDS",
    "V69_IBEX_FALLBACK_TASK_IDS",
    "V69_OPEN_TOOL_TASK_ID",
    "V69_PRIMARY_TASK_IDS",
    "V71_MATRIX_TASK_IDS",
    "inspect_offline_image_archive",
    "load_v69_manifest",
    "load_v71_dind_successor_manifest",
    "load_v73_dind_successor_manifest",
    "load_v75_dind_successor_manifest",
    "load_v77_dind_successor_manifest",
    "load_v79_dind_successor_manifest",
    "load_v81_execution_scaffold_manifest",
    "load_v83_execution_scaffold_manifest",
    "load_v85_official_matrix_manifest",
    "load_v87_fresh_scaffold_manifest",
    "load_v90_fresh_scaffold_manifest",
    "load_v92_official_matrix_manifest",
    "load_v94_runtime_complete_scaffold_manifest",
    "load_v97_rebuild_identity_scaffold_manifest",
    "load_v100_inventory_timeout_scaffold_manifest",
    "load_v103_inspect_output_bound_scaffold_manifest",
    "load_v106_fresh_inventory_binding_scaffold_manifest",
    "load_v109_progress_writer_scaffold_manifest",
    "load_v112_data2_control_headroom_scaffold_manifest",
    "load_v115_explicit_nested_docker_socket_scaffold_manifest",
    "load_v118_explicit_inner_inventory_scaffold_manifest",
    "load_v121_bounded_dind_start_diagnostic_manifest",
    "load_v123_bounded_dind_identity_probe_manifest",
    "load_v125_bounded_dind_readiness_probe_manifest",
    "load_v127_readiness_gated_scaffold_manifest",
    "load_v130_bounded_command_scan_probe_manifest",
    "load_v132_bounded_scan_scaffold_manifest",
    "load_v134_official_matrix_manifest",
    "migration_conclusions",
    "new_matrix_state",
    "record_matrix_attempt",
    "require_toolchain_verifier_binding",
]
