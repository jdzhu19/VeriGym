"""Redacted identity comparison for resolved toolchain profiles.

The comparison is deliberately hash-only at its persistence boundary.  The
component payloads are useful while validating a profile, but callers should
persist only :class:`ResolvedProfileComparisonEvidence` so that paths,
versions, and site-owned asset metadata cannot leak into campaign evidence.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import field_validator, model_validator

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.base import StrictModel

from .base import ResolvedToolchainProfile

ResolvedProfileIdentityComponent = Literal[
    "runtime",
    "transport",
    "server_release",
    "remote_tools",
    "remote_assets",
    "flow",
    "reference",
    "worker_contract",
    "source_projection",
]

RESOLVED_PROFILE_IDENTITY_COMPONENTS: tuple[ResolvedProfileIdentityComponent, ...] = (
    "runtime",
    "transport",
    "server_release",
    "remote_tools",
    "remote_assets",
    "flow",
    "reference",
    "worker_contract",
    "source_projection",
)


class ResolvedProfileComparisonEvidence(StrictModel):
    """The complete redacted result of comparing two resolved identities."""

    expected_hash: str
    observed_hash: str
    changed_components: list[ResolvedProfileIdentityComponent]

    @field_validator("expected_hash", "observed_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("resolved profile comparison requires lowercase SHA-256 identities")
        return value

    @model_validator(mode="after")
    def validate_changed_components(self) -> ResolvedProfileComparisonEvidence:
        changed = set(self.changed_components)
        canonical = [
            component for component in RESOLVED_PROFILE_IDENTITY_COMPONENTS if component in changed
        ]
        if self.changed_components != canonical:
            raise ValueError("resolved profile changes must be unique and canonically ordered")
        if (self.expected_hash == self.observed_hash) != (not self.changed_components):
            raise ValueError("resolved profile hashes and changed components are inconsistent")
        return self

    @property
    def matches(self) -> bool:
        return self.expected_hash == self.observed_hash and not self.changed_components

    @property
    def expected_resolved_profile_hash(self) -> str:
        """Compatibility spelling for callers that use the profile field name."""

        return self.expected_hash

    @property
    def observed_resolved_profile_hash(self) -> str:
        """Compatibility spelling for callers that use the profile field name."""

        return self.observed_hash


def _resolved_profile_identity_components(
    profile: ResolvedToolchainProfile,
) -> dict[ResolvedProfileIdentityComponent, dict[str, Any]]:
    """Return comparison components without persisting their raw values.

    The grouping intentionally follows the remote DC contract as well as the
    ordinary local profile fields.  Unknown metadata is conservatively bound
    to the flow component; a mismatch can therefore never be silently ignored.
    """

    metadata = profile.metadata
    remote_tool_versions = metadata.get("remote_tool_versions", {})
    remote_asset_hashes = metadata.get("remote_asset_hashes", {})
    worker_metadata = {
        key: value
        for key, value in metadata.items()
        if key.startswith("agent_feedback_worker_") or key.startswith("commercial_worker_release")
    }
    server_metadata = {
        key: value
        for key, value in metadata.items()
        if key.startswith("mcp_server_")
        or key
        in {
            "mcp_service_protocol",
            "mcp_server_version",
            "remote_design_compiler_version",
        }
    }
    transport_metadata = {
        key: value
        for key, value in metadata.items()
        if key
        in {
            "mcp_transport_sha256",
            "mcp_transport_execution_boundary",
        }
    }
    known_metadata = {
        *worker_metadata,
        *server_metadata,
        *transport_metadata,
        "remote_tool_versions",
        "remote_asset_hashes",
        "prepared_image_id",
        "clock_period",
        "power_activity_mode",
        "power_activity",
        "power_static_probability",
        "power_base_clock",
        "source_liberty_sha256",
    }
    unknown_metadata = {key: value for key, value in metadata.items() if key not in known_metadata}
    tool_payload = [item.model_dump(mode="json") for item in profile.tool_identities]
    transport_tools = [
        item
        for item in tool_payload
        if item.get("logical_name") in {"synopsys-dc-mcp", "synopsys-vcs-mcp"}
    ]
    other_tools = [item for item in tool_payload if item not in transport_tools]
    return {
        "runtime": profile.runtime_identity.model_dump(mode="json"),
        "transport": {"metadata": transport_metadata, "tools": transport_tools},
        "server_release": server_metadata,
        "remote_tools": {"versions": remote_tool_versions, "tools": other_tools},
        "remote_assets": {
            "assets": [item.model_dump(mode="json") for item in profile.asset_identities],
            "hashes": remote_asset_hashes,
        },
        "flow": {
            "flow_hash": profile.flow_hash,
            "metric_contract_hash": profile.metric_contract_hash,
            "flow_template_id": profile.flow_template_id,
            "generated_script_hash": profile.generated_script_hash,
            "metric_scope": profile.metric_scope,
            "area_unit": profile.area_unit,
            "timing_unit": profile.timing_unit,
            "power_unit": profile.power_unit,
            "artifact_visibility_policy": profile.artifact_visibility_policy,
            "unknown_metadata": unknown_metadata,
        },
        "reference": {
            "reference_contract_hash": profile.reference_contract_hash,
            "reference_strategy": profile.reference_strategy,
            "reference_candidate_hash": profile.reference_candidate_hash,
        },
        "worker_contract": worker_metadata,
        "source_projection": {
            "source_paths": profile.source_paths,
            "synthesis_source_projection_hash": profile.synthesis_source_projection_hash,
            "top_module": profile.top_module,
        },
    }


def resolved_profile_component_hashes(
    profile: ResolvedToolchainProfile,
) -> dict[ResolvedProfileIdentityComponent, str]:
    """Hash each identity component without exposing its payload."""

    components = _resolved_profile_identity_components(profile)
    return {name: content_hash(components[name]) for name in RESOLVED_PROFILE_IDENTITY_COMPONENTS}


def compare_resolved_profile_identity(
    expected: ResolvedToolchainProfile,
    observed: ResolvedToolchainProfile,
) -> ResolvedProfileComparisonEvidence:
    """Compare two profiles and return only hashes plus changed component names."""

    expected_hashes = resolved_profile_component_hashes(expected)
    observed_hashes = resolved_profile_component_hashes(observed)
    changed = [
        name
        for name in RESOLVED_PROFILE_IDENTITY_COMPONENTS
        if expected_hashes[name] != observed_hashes[name]
    ]
    if expected.resolved_profile_hash != observed.resolved_profile_hash and not changed:
        # A profile hash mismatch not explained by a known component is itself
        # a fail-closed identity drift.  Do not add an unbounded free-form label
        # to the evidence; conservatively attribute it to every known component.
        changed = list(RESOLVED_PROFILE_IDENTITY_COMPONENTS)
    return ResolvedProfileComparisonEvidence(
        expected_hash=expected.resolved_profile_hash,
        observed_hash=observed.resolved_profile_hash,
        changed_components=changed,
    )


def require_resolved_profile_identity(
    expected: ResolvedToolchainProfile,
    observed: ResolvedToolchainProfile,
) -> ResolvedProfileComparisonEvidence:
    """Require an exact identity and raise without embedding sensitive values."""

    evidence = compare_resolved_profile_identity(expected, observed)
    if not evidence.matches:
        components = ",".join(evidence.changed_components) or "unknown"
        raise ConfigurationError(f"resolved profile identity drift ({components})")
    return evidence


__all__ = [
    "RESOLVED_PROFILE_IDENTITY_COMPONENTS",
    "ResolvedProfileComparisonEvidence",
    "ResolvedProfileIdentityComponent",
    "compare_resolved_profile_identity",
    "require_resolved_profile_identity",
    "resolved_profile_component_hashes",
]
