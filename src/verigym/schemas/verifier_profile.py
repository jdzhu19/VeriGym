"""Hash-bound model-invisible backend and transport profiles."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TRANSPORT_ENVIRONMENT = frozenset({"SSH_AUTH_SOCK", "KRB5CCNAME"})


class VerifierToolProfile(StrictModel):
    """Sanitized client contract for one fixed model-invisible tool backend."""

    schema_version: str = SCHEMA_VERSION
    id: str
    version: str
    description: str = ""
    task_id: str
    source_plugin: str
    target_plugin: str
    runtime: Literal["local"] = "local"
    transport_executable: str
    transport_sha256: str
    transport_environment: list[str] = Field(default_factory=list, max_length=2)
    service_protocol: str
    server_version: str
    server_profile_id: str
    server_declared_profile_hash: str
    server_contract_hash: str
    accepted_tool_version: str

    @field_validator("id", "server_profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if _PROFILE_ID.fullmatch(value) is None:
            raise ValueError("verifier profile IDs must use stable ASCII components")
        return value

    @field_validator("source_plugin", "target_plugin")
    @classmethod
    def validate_plugin(cls, value: str) -> str:
        if _SLUG.fullmatch(value) is None:
            raise ValueError("verifier plugin names must be stable lowercase slugs")
        return value

    @field_validator("transport_sha256", "server_declared_profile_hash", "server_contract_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("verifier profile identities must be lowercase SHA-256 values")
        return value

    @field_validator("transport_environment")
    @classmethod
    def validate_transport_environment(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or not set(value).issubset(_TRANSPORT_ENVIRONMENT):
            raise ValueError("unsupported verifier transport environment allowlist")
        return sorted(value)

    @model_validator(mode="after")
    def validate_backend_change(self) -> VerifierToolProfile:
        if self.source_plugin == self.target_plugin:
            raise ValueError("verifier profile must select a distinct target backend")
        return self


class ResolvedVerifierToolProfile(StrictModel):
    """Pre-model identity returned by the selected verifier backend."""

    schema_version: str = SCHEMA_VERSION
    profile_id: str
    profile_version: str
    declared_profile_hash: str
    resolved_profile_hash: str
    task_id: str
    source_plugin: str
    target_plugin: str
    runtime: Literal["local"] = "local"
    transport_sha256: str
    service_protocol: str
    server_version: str
    server_profile_id: str
    server_declared_profile_hash: str
    server_resolved_profile_hash: str
    server_contract_hash: str
    tool_version: str

    @field_validator(
        "declared_profile_hash",
        "resolved_profile_hash",
        "transport_sha256",
        "server_declared_profile_hash",
        "server_resolved_profile_hash",
        "server_contract_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("resolved verifier identities must be lowercase SHA-256 values")
        return value

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"schema_version", "resolved_profile_hash"})


__all__ = ["ResolvedVerifierToolProfile", "VerifierToolProfile"]
