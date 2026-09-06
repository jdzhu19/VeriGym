"""Hash-bound projection from an agent workspace to synthesis source paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verigym.core.hashing import content_hash
from verigym.core.workspace import normalize_relative_path
from verigym.schemas.task import VeriTask

SYNTHESIS_SOURCE_PROJECTION_ID = "synthesis_source_projection.v1"
_METADATA_KEY = "synthesis_source_projection"


@dataclass(frozen=True)
class SynthesisSourceProjection:
    """Resolved source paths shared by profile resolution and synthesis execution."""

    workspace_to_profile: dict[str, str]
    projection_hash: str | None

    @property
    def profile_sources(self) -> list[str]:
        return list(self.workspace_to_profile.values())

    def workspace_source(self, profile_source: str) -> str:
        matches = [
            workspace
            for workspace, projected in self.workspace_to_profile.items()
            if projected == profile_source
        ]
        if len(matches) != 1:
            raise ValueError("resolved synthesis source is absent from the task projection")
        return matches[0]


def synthesis_source_projection_contract(mapping: dict[str, str]) -> dict[str, Any]:
    """Build the canonical metadata contract for a non-identity source projection."""

    normalized = _normalized_mapping(mapping)
    unsigned = {
        "format_id": SYNTHESIS_SOURCE_PROJECTION_ID,
        "workspace_to_profile": normalized,
    }
    return {**unsigned, "projection_hash": content_hash(unsigned)}


def resolve_synthesis_source_projection(task: VeriTask) -> SynthesisSourceProjection:
    """Resolve and validate the task projection, defaulting to historical identity paths."""

    raw = task.metadata.get(_METADATA_KEY)
    if raw is None:
        mapping = {path: path for path in task.workspace.entrypoints}
        return SynthesisSourceProjection(_normalized_mapping(mapping), None)
    if not isinstance(raw, dict) or set(raw) != {
        "format_id",
        "workspace_to_profile",
        "projection_hash",
    }:
        raise ValueError("synthesis source projection has an unexpected schema")
    if raw.get("format_id") != SYNTHESIS_SOURCE_PROJECTION_ID:
        raise ValueError("synthesis source projection format is unsupported")
    raw_mapping = raw.get("workspace_to_profile")
    if not isinstance(raw_mapping, dict) or not all(
        isinstance(source, str) and isinstance(target, str)
        for source, target in raw_mapping.items()
    ):
        raise ValueError("synthesis source projection mapping is malformed")
    mapping = {str(source): str(target) for source, target in raw_mapping.items()}
    normalized = _normalized_mapping(mapping)
    if list(normalized) != list(task.workspace.entrypoints):
        raise ValueError("synthesis source projection must cover the ordered task entrypoints")
    unsigned = {
        "format_id": SYNTHESIS_SOURCE_PROJECTION_ID,
        "workspace_to_profile": normalized,
    }
    projection_hash = raw.get("projection_hash")
    if not isinstance(projection_hash, str) or projection_hash != content_hash(unsigned):
        raise ValueError("synthesis source projection hash is invalid")
    return SynthesisSourceProjection(normalized, projection_hash)


def _normalized_mapping(mapping: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    projected: set[str] = set()
    for workspace, profile in mapping.items():
        workspace_path = normalize_relative_path(workspace)
        profile_path = normalize_relative_path(profile)
        if not workspace_path.lower().endswith((".v", ".sv")) or not profile_path.lower().endswith(
            (".v", ".sv")
        ):
            raise ValueError("synthesis source projection supports only Verilog source paths")
        if workspace_path in normalized or profile_path in projected:
            raise ValueError("synthesis source projection paths must be one-to-one")
        normalized[workspace_path] = profile_path
        projected.add(profile_path)
    if not normalized:
        raise ValueError("synthesis source projection cannot be empty")
    return normalized


__all__ = [
    "SYNTHESIS_SOURCE_PROJECTION_ID",
    "SynthesisSourceProjection",
    "resolve_synthesis_source_projection",
    "synthesis_source_projection_contract",
]
