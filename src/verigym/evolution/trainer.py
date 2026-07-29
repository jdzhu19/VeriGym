"""Manifest-only future external-trainer bridge; no trainer is executed."""

from __future__ import annotations

from collections.abc import Mapping

from verigym.core.hashing import content_hash
from verigym.schemas.evolution import (
    ExternalAgentVersionImportManifest,
    ExternalTrainerExportManifest,
)
from verigym.schemas.options import JsonValue


def build_trainer_export_manifest(
    *,
    trajectory_dataset_hash: str,
    split_manifest_hash: str,
    reward_schema_hash: str,
    reward_profile_hash: str | None,
) -> ExternalTrainerExportManifest:
    base = {
        "schema_version": "1.0",
        "bridge_id": "observable_trajectory_external_trainer_v1",
        "trajectory_dataset_hash": trajectory_dataset_hash,
        "split_manifest_hash": split_manifest_hash,
        "reward_schema_hash": reward_schema_hash,
        "reward_profile_hash": reward_profile_hash,
        "executable_artifacts_included": False,
        "secrets_included": False,
    }
    return ExternalTrainerExportManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )


def build_agent_import_manifest(
    *,
    import_id: str,
    update_type: str,
    parent_version_hash: str,
    trainer_identity_hash: str,
    training_dataset_hash: str,
    artifact_hash: str,
    compatible_runtime_hash: str,
    license: str,
    provenance: str,
    loading_configuration: Mapping[str, JsonValue],
) -> ExternalAgentVersionImportManifest:
    base = {
        "schema_version": "1.0",
        "import_id": import_id,
        "update_type": update_type,
        "parent_version_hash": parent_version_hash,
        "trainer_identity_hash": trainer_identity_hash,
        "training_dataset_hash": training_dataset_hash,
        "artifact_hash": artifact_hash,
        "compatible_runtime_hash": compatible_runtime_hash,
        "license": license,
        "provenance": provenance,
        "loading_configuration": dict(loading_configuration),
        "executable_in_m10b": update_type == "context_memory",
    }
    return ExternalAgentVersionImportManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )


def validate_agent_import_manifest(
    manifest: ExternalAgentVersionImportManifest,
) -> ExternalAgentVersionImportManifest:
    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ValueError("external agent-version import identity changed")
    forbidden = {
        key
        for key in manifest.loading_configuration
        if any(
            marker in key.casefold()
            for marker in ("token", "key", "secret", "password", "credential", "auth", "proxy")
        )
    }
    if forbidden:
        raise ValueError("external agent-version import loading configuration is not secret-free")
    return manifest


__all__ = [
    "build_agent_import_manifest",
    "build_trainer_export_manifest",
    "validate_agent_import_manifest",
]
