"""Immutable synthesis-profile declarations, resolution, and comparison guards."""

from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.profiles.identity import (
    RESOLVED_PROFILE_IDENTITY_COMPONENTS,
    ResolvedProfileComparisonEvidence,
    compare_resolved_profile_identity,
    require_resolved_profile_identity,
    resolved_profile_component_hashes,
)
from verigym.profiles.registry import ToolchainProfileRegistry, builtin_profiles

__all__ = [
    "ResolvedArtifactIdentity",
    "ResolvedRuntimeIdentity",
    "ResolvedToolIdentity",
    "ResolvedToolchainProfile",
    "ToolchainProfileRegistry",
    "builtin_profiles",
    "RESOLVED_PROFILE_IDENTITY_COMPONENTS",
    "ResolvedProfileComparisonEvidence",
    "compare_resolved_profile_identity",
    "require_resolved_profile_identity",
    "resolved_profile_component_hashes",
]
