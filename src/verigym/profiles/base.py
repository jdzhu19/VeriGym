"""Persistent resolved-profile identity models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel


class ResolvedRuntimeIdentity(StrictModel):
    runtime_slug: str
    isolation_level: str
    deterministic: bool
    os: str | None = None
    architecture: str | None = None
    requested_image_reference: str | None = None
    resolved_image_id: str | None = None
    configuration_fingerprint: str | None = None
    network_policy: str | None = None
    resource_controls: bool = False
    security_hash: str | None = None
    resource_contract_hash: str | None = None


class ResolvedToolIdentity(StrictModel):
    logical_name: str
    executable: str
    version: str
    version_output: str
    git_hash: str | None = None
    executable_sha256: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    identity_kind: Literal["immutable_image_observation", "local_executable"]


class ResolvedArtifactIdentity(StrictModel):
    logical_id: str
    media_type: str
    source_kind: str
    content_hash: str
    license: str | None = None
    attribution: str | None = None
    redistributable: bool
    unit: str | None = None
    semantics: str | None = None
    copy_permitted: bool
    replay_locator: str | None = None


class ResolvedToolchainProfile(StrictModel):
    schema_version: str = SCHEMA_VERSION
    profile_id: str
    profile_version: str
    declared_profile_hash: str
    resolved_profile_hash: str
    reproducibility_scope: Literal["public", "site_specific", "private"]
    deterministic: bool
    runtime_identity: ResolvedRuntimeIdentity
    tool_identities: list[ResolvedToolIdentity]
    asset_identities: list[ResolvedArtifactIdentity]
    flow_hash: str
    metric_contract_hash: str
    reference_contract_hash: str | None
    flow_template_id: str
    generated_script_hash: str
    top_module: str
    source_paths: list[str]
    metric_scope: Literal["synthesis_area_only"]
    area_unit: str
    reference_strategy: str
    reference_candidate_hash: str | None = None
    artifact_visibility_policy: str = "candidate_public_reference_summary_only"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def identity_payload(self) -> dict[str, Any]:
        """Return only comparison-relevant, timestamp-free profile state."""

        payload = self.model_dump(mode="json")
        payload.pop("resolved_profile_hash", None)
        runtime = payload.get("runtime_identity")
        if isinstance(runtime, dict):
            # Mutable human-facing tags are audit metadata, never resolved identity.
            runtime.pop("requested_image_reference", None)
            # The exact security/resource contracts are hashed separately. The runtime
            # configuration fingerprint also includes the mutable requested tag.
            runtime.pop("configuration_fingerprint", None)
        return payload


__all__ = [
    "ResolvedArtifactIdentity",
    "ResolvedRuntimeIdentity",
    "ResolvedToolIdentity",
    "ResolvedToolchainProfile",
]
