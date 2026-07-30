"""Deterministic all-or-none decisions for immutable historical training episodes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from verigym.core.hashing import content_hash
from verigym.schemas.evolution import (
    HistoricalTrainingEpisodeImportEligibility,
    HistoricalTrainingImportManifest,
)


def build_training_episode_import_eligibility(
    *,
    run_id: str,
    task_id: str,
    outcome_kind: str,
    checks: Mapping[str, bool],
    original_run_manifest_hash: str,
    original_artifact_manifest_hash: str,
    original_source_commit: str,
    exporter_source_commit: str,
    trajectory_hash: str,
    reward_hash: str,
) -> HistoricalTrainingEpisodeImportEligibility:
    """Freeze one transparent eligibility decision from named fail-closed checks."""

    normalized_checks = dict(sorted(checks.items()))
    reasons = sorted(name for name, passed in normalized_checks.items() if not passed)
    base = {
        "schema_version": "1.0",
        "run_id": run_id,
        "task_id": task_id,
        "outcome_kind": outcome_kind,
        "eligible": not reasons,
        "checks": normalized_checks,
        "ineligible_reasons": reasons,
        "original_run_manifest_hash": original_run_manifest_hash,
        "original_artifact_manifest_hash": original_artifact_manifest_hash,
        "original_source_commit": original_source_commit,
        "exporter_source_commit": exporter_source_commit,
        "trajectory_hash": trajectory_hash,
        "reward_hash": reward_hash,
    }
    return HistoricalTrainingEpisodeImportEligibility.model_validate(
        {**base, "record_hash": content_hash(base)}
    )


def build_historical_training_import_manifest(
    *,
    import_id: str,
    source_bundle_sha256sums_hash: str,
    exporter_source_commit: str,
    episodes: Sequence[HistoricalTrainingEpisodeImportEligibility],
) -> HistoricalTrainingImportManifest:
    """Apply the immutable triplet-level all-or-none selection rule."""

    ordered = sorted(episodes, key=lambda value: value.task_id)
    import_all = len(ordered) == 3 and all(record.eligible for record in ordered)
    base = {
        "schema_version": "1.0",
        "import_id": import_id,
        "source_bundle_sha256sums_hash": source_bundle_sha256sums_hash,
        "exporter_source_commit": exporter_source_commit,
        "episodes": [record.model_dump(mode="json") for record in ordered],
        "all_or_none_policy": True,
        "import_all": import_all,
        "rerun_all": not import_all,
        "mixed_sources": False,
    }
    return HistoricalTrainingImportManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )


def validate_historical_training_import_manifest(
    manifest: HistoricalTrainingImportManifest,
) -> HistoricalTrainingImportManifest:
    """Recompute the manifest and reject mixed imported/rerun provenance."""

    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ValueError("historical training import manifest identity changed")
    for episode in manifest.episodes:
        record = episode.model_dump(mode="json")
        record_hash = record.pop("record_hash")
        if content_hash(record) != record_hash:
            raise ValueError("historical training episode import identity changed")
    return manifest


__all__ = [
    "build_historical_training_import_manifest",
    "build_training_episode_import_eligibility",
    "validate_historical_training_import_manifest",
]
