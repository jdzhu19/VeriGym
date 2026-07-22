"""Immutable synthesis-profile declarations, resolution, and comparison guards."""

from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.profiles.registry import ToolchainProfileRegistry, builtin_profiles

__all__ = [
    "ResolvedArtifactIdentity",
    "ResolvedRuntimeIdentity",
    "ResolvedToolIdentity",
    "ResolvedToolchainProfile",
    "ToolchainProfileRegistry",
    "builtin_profiles",
]
