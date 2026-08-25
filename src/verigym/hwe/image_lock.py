"""Task-keyed identity for offline CVA6 verifier-to-agent image derivation."""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from verigym.core.hashing import content_hash
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_ID,
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_TOOL_CONTRACT_ID,
    HWE_TOOL_CONTRACT_V2_ID,
)
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class HweAllowlistedArtifact(StrictModel):
    """One public toolchain artifact retained from the official task image."""

    path: str = Field(min_length=1, max_length=512)
    sha256: str
    role: Literal["compiler", "simulator", "build_tool", "runtime_library", "public_asset"]

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/") or ".." in value.split("/") or "\x00" in value:
            raise ValueError(
                "HWE allowlisted artifact path must be canonical absolute container path"
            )
        if value.startswith(("/home/cva6", "/workspace", "/root")):
            raise ValueError("HWE allowlist cannot retain source, workspace, or root-home content")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("HWE allowlisted artifact requires SHA-256")
        return value


class HweAgentImageLock(StrictModel):
    """Fail-closed binding for one official CVA6 task and its derived agent image."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_hwe_agent_image_lock_v1", "verigym_hwe_agent_image_lock_v2"] = (
        "verigym_hwe_agent_image_lock_v2"
    )
    task_id: str
    task_hash: str
    source_hash: str
    verifier_base_image_id: str
    derived_agent_image_id: str
    codex_version: Literal["codex-cli 0.147.0"] = "codex-cli 0.147.0"
    host_codex_sha256: str
    agent_codex_sha256: str
    agent_rg_sha256: str
    collection_profile_id: Literal["hwe_standard_v1", "hwe_standard_v2"] = "hwe_standard_v2"
    tool_contract_id: Literal["hwe_native_shell_v1", "hwe_native_shell_v2"] = "hwe_native_shell_v2"
    toolchain_profile_id: str = Field(min_length=1, max_length=128)
    allowlisted_artifacts: list[HweAllowlistedArtifact] = Field(min_length=1, max_length=512)
    source_whiteout_path: Literal["/home/cva6"] = "/home/cva6"
    visible_workspace_path: Literal["/workspace/repository"] = "/workspace/repository"
    build_network: Literal["none"] = "none"
    runtime_network: Literal["none"] = "none"
    provider_credentials_present: Literal[False] = False
    hidden_assets_present: Literal[False] = False
    verifier_payload_present: Literal[False] = False
    reference_patch_present: Literal[False] = False
    security_scan_id: str
    security_scan_passed: Literal[True] = True
    lock_hash: str

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        if not _TASK_ID.fullmatch(value):
            raise ValueError("HWE task ID is not portable")
        return value

    @field_validator(
        "task_hash",
        "source_hash",
        "host_codex_sha256",
        "agent_codex_sha256",
        "agent_rg_sha256",
        "security_scan_id",
        "lock_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("HWE image lock identity must be SHA-256")
        return value

    @field_validator("verifier_base_image_id", "derived_agent_image_id")
    @classmethod
    def validate_image_id(cls, value: str) -> str:
        if not _IMAGE_ID.fullmatch(value):
            raise ValueError("HWE image identity must be sha256:<64 lowercase hex>")
        return value

    @model_validator(mode="after")
    def validate_lock(self) -> Self:
        expected_identity = {
            "verigym_hwe_agent_image_lock_v1": (
                HWE_COLLECTION_PROFILE_ID,
                HWE_TOOL_CONTRACT_ID,
            ),
            "verigym_hwe_agent_image_lock_v2": (
                HWE_COLLECTION_PROFILE_V2_ID,
                HWE_TOOL_CONTRACT_V2_ID,
            ),
        }[self.format_id]
        if (self.collection_profile_id, self.tool_contract_id) != expected_identity:
            raise ValueError("HWE image lock profile and format identities differ")
        if self.verifier_base_image_id == self.derived_agent_image_id:
            raise ValueError("HWE verifier and agent images must be independently identified")
        paths = [artifact.path for artifact in self.allowlisted_artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("HWE image allowlist contains duplicate paths")
        roles = {artifact.role for artifact in self.allowlisted_artifacts}
        if not {"build_tool", "simulator"}.issubset(roles):
            raise ValueError("HWE image allowlist must bind the build and simulation toolchain")
        identity = self.model_dump(mode="json", exclude={"lock_hash"})
        if content_hash(identity) != self.lock_hash:
            raise ValueError("HWE image lock identity changed")
        return self


def build_hwe_agent_image_lock(**values: object) -> HweAgentImageLock:
    base = {
        "schema_version": SCHEMA_VERSION,
        "format_id": "verigym_hwe_agent_image_lock_v2",
        **values,
    }
    artifacts = base.get("allowlisted_artifacts")
    if isinstance(artifacts, list):
        base["allowlisted_artifacts"] = [
            item
            if isinstance(item, HweAllowlistedArtifact)
            else HweAllowlistedArtifact.model_validate(item)
            for item in artifacts
        ]
    provisional = HweAgentImageLock.model_construct(None, **base, lock_hash="0" * 64)
    normalized = provisional.model_dump(mode="json", exclude={"lock_hash"})
    return HweAgentImageLock.model_validate({**normalized, "lock_hash": content_hash(normalized)})


__all__ = ["HweAgentImageLock", "HweAllowlistedArtifact", "build_hwe_agent_image_lock"]
