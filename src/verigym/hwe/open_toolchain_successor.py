"""Successor contracts for the v174 open-toolchain qualification repair."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

V174_IDENTITY = "deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_DIGEST = re.compile(
    r"^(?P<repository>[a-z0-9]+(?:[._/-][a-z0-9]+)*)@(?P<digest>sha256:[0-9a-f]{64})$"
)
_MAX_JSON_BYTES = 1024 * 1024


class OpenToolchainV174SuccessorManifest(StrictModel):
    """One-use v174 repair authorization layered on the frozen v172 inputs."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_deepseek_harness_hwe_v174_open_toolchain_successor_manifest_v1"]
    identity: Literal["deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1"]
    upstream_identity: Literal["deepseek-harness-hwe-v172-open-toolchain-qualification-v1"]
    upstream_manifest_path: Literal[
        "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
    ]
    upstream_manifest_sha256: str
    upstream_manifest_hash: str
    predecessor_stop_root: str
    predecessor_stop_receipt_sha256: str
    predecessor_stop_receipt_hash: str
    predecessor_stop_tree_hash: str
    predecessor_audit_path: Literal[
        "docs/audits/2026-09-06_deepseek-harness-v173-v172-pre-output-stop.md"
    ]
    predecessor_audit_sha256: str
    predecessor_audit_commit: str
    predecessor_merge_commit: str
    predecessor_post_merge_main_run_id: Literal[33980858187]
    predecessor_post_merge_all_eight_classes_passed: Literal[True]
    dind_repository_name: Literal["docker"]
    dind_repository_digest: Literal[
        "sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca"
    ]
    repository_digest_parser: Literal["exact-single-repository-at-sha256-v1"]
    builder_tag: Literal["verigym/open-rtl-tools:v174-builder"]
    final_dockerfile: Literal["docker/open-rtl-tools-hwe/Dockerfile.v174"]
    final_dockerfile_sha256: str
    final_image_tag: Literal["verigym/open-rtl-tools:hwe-v174-pr1816"]
    dind_data_volume: Literal["verigym-deepseek-harness-v174-dind-data"]
    dind_socket_volume: Literal["verigym-deepseek-harness-v174-dind-socket"]
    dind_data_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v174/data"]
    dind_socket_backing: Literal["/data2/jiadongzhu/docker/deepseek-harness-hwe-v174/socket"]
    output_root: Literal[
        "/data2/jiadongzhu/Agent/experiments/"
        "deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1"
    ]
    scratch_root: Literal[
        "/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v174-open-toolchain-repair"
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
    requires_independent_v175_audit: Literal[True]
    v176_canary_authorized: Literal[False]
    manifest_hash: str

    @field_validator(
        "upstream_manifest_sha256",
        "upstream_manifest_hash",
        "predecessor_stop_receipt_sha256",
        "predecessor_stop_receipt_hash",
        "predecessor_stop_tree_hash",
        "predecessor_audit_sha256",
        "final_dockerfile_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("v174 successor requires lowercase SHA-256")
        return value

    @field_validator("predecessor_audit_commit", "predecessor_merge_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if _COMMIT.fullmatch(value) is None:
            raise ValueError("v174 successor requires a full git commit")
        return value

    @field_validator("predecessor_stop_root")
    @classmethod
    def validate_stop_root(cls, value: str) -> str:
        path = PurePosixPath(value)
        expected = (
            "/data2/jiadongzhu/Agent/experiments/"
            "deepseek-harness-hwe-v172-open-toolchain-qualification-pre-output-stop-v1"
        )
        if path.as_posix() != expected or not path.is_absolute():
            raise ValueError("v174 predecessor stop root changed")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("v174 successor manifest content hash changed")
        return self


def exact_repository_digest(
    entries: Any,
    *,
    expected_repository: str,
    expected_digest: str,
) -> str:
    """Require one canonical Docker repository@digest entry and return it."""

    if (
        not isinstance(entries, list)
        or len(entries) != 1
        or not isinstance(entries[0], str)
        or _DIGEST.fullmatch(expected_digest) is None
    ):
        raise ConfigurationError("repository digest inventory is not exactly one string")
    matched = _REPOSITORY_DIGEST.fullmatch(entries[0])
    if (
        matched is None
        or matched.group("repository") != expected_repository
        or matched.group("digest") != expected_digest
    ):
        raise ConfigurationError("repository name or digest component changed")
    return entries[0]


def load_v174_successor_manifest(path: Path) -> OpenToolchainV174SuccessorManifest:
    """Load a bounded ordinary-file v174 successor manifest."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError("v174 successor manifest path is unsafe")
    try:
        return OpenToolchainV174SuccessorManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigurationError("v174 successor manifest is invalid") from exc
