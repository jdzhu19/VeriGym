from __future__ import annotations

import pytest
from pydantic import ValidationError

from verigym.evolution.training_import import (
    build_historical_training_import_manifest,
    build_training_episode_import_eligibility,
    validate_historical_training_import_manifest,
)
from verigym.schemas.evolution import HistoricalTrainingImportManifest


def _episode(
    index: int,
    *,
    outcome: str = "resolved_candidate",
    failed_check: str | None = None,
):
    checks = {
        "artifact_manifest": True,
        "candidate_and_task_identity": True,
        "evaluable_terminal": True,
        "model_runtime_tool_identity": True,
        "no_infrastructure_failure": True,
        "prompt_binding": True,
        "replay_zero_calls": True,
        "reward_recomputation": True,
        "security_scan": True,
        "trajectory_export_deterministic": True,
        "v0_agent_version": True,
    }
    if failed_check is not None:
        checks[failed_check] = False
    return build_training_episode_import_eligibility(
        run_id=f"historical-training-{index}",
        task_id=f"repo-rtl/task-{index}",
        outcome_kind=outcome,
        checks=checks,
        original_run_manifest_hash=f"{index + 1:x}" * 64,
        original_artifact_manifest_hash=f"{index + 4:x}" * 64,
        original_source_commit="9" * 40,
        exporter_source_commit="a" * 40,
        trajectory_hash=f"{index + 7:x}" * 64,
        reward_hash=f"{index + 10:x}" * 64,
    )


def test_three_eligible_historical_episodes_import_all() -> None:
    manifest = build_historical_training_import_manifest(
        import_id="historical-training-triplet",
        source_bundle_sha256sums_hash="b" * 64,
        exporter_source_commit="a" * 40,
        episodes=[_episode(0), _episode(1), _episode(2)],
    )

    assert manifest.import_all is True
    assert manifest.rerun_all is False
    assert validate_historical_training_import_manifest(manifest) == manifest


def test_one_invalid_episode_imports_none_and_schedules_all_reruns() -> None:
    manifest = build_historical_training_import_manifest(
        import_id="historical-training-triplet",
        source_bundle_sha256sums_hash="b" * 64,
        exporter_source_commit="a" * 40,
        episodes=[
            _episode(0),
            _episode(1, failed_check="artifact_manifest"),
            _episode(2),
        ],
    )

    assert manifest.import_all is False
    assert manifest.rerun_all is True
    assert [episode.eligible for episode in manifest.episodes].count(False) == 1


def test_contained_policy_failure_is_eligible_but_infrastructure_failure_is_not() -> None:
    policy = _episode(0, outcome="contained_workspace_policy_failure")
    infrastructure = _episode(
        1,
        outcome="infrastructure_invalid",
        failed_check="no_infrastructure_failure",
    )

    assert policy.eligible is True
    assert infrastructure.eligible is False


def test_mixed_imported_and_rerun_provenance_is_rejected() -> None:
    manifest = build_historical_training_import_manifest(
        import_id="historical-training-triplet",
        source_bundle_sha256sums_hash="b" * 64,
        exporter_source_commit="a" * 40,
        episodes=[_episode(0), _episode(1), _episode(2)],
    )
    payload = manifest.model_dump(mode="json")
    payload["mixed_sources"] = True

    with pytest.raises(ValidationError):
        HistoricalTrainingImportManifest.model_validate(payload)
