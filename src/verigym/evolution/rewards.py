"""Deterministic offline repository-repair reward derivation."""

from __future__ import annotations

from verigym.core.hashing import content_hash
from verigym.schemas.evolution import (
    EpisodeOutcomeKind,
    RewardDerivationRecord,
    RewardProfile,
    RewardVector,
)
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard

_PROFILE_VALUES: dict[EpisodeOutcomeKind, float | None] = {
    "resolved_candidate": 1.0,
    "incorrect_policy_compliant_candidate": 0.0,
    "contained_workspace_policy_failure": -0.25,
    "strict_output_failure": -0.25,
    "infrastructure_invalid": None,
    "cancelled_or_interrupted": None,
}
_PROFILE_PAYLOAD = {
    "schema_version": "1.0",
    "profile_id": "repo_rtl_sparse_v1",
    "profile_version": "1.0",
    "outcome_values": _PROFILE_VALUES,
    "universal_benchmark_score": False,
}
REPO_RTL_SPARSE_V1 = RewardProfile.model_validate(
    {
        **_PROFILE_PAYLOAD,
        "profile_hash": content_hash(_PROFILE_PAYLOAD),
    }
)


def classify_outcome(scorecard: ScoreCard) -> EpisodeOutcomeKind:
    """Preserve correctness, contained policy, and infrastructure distinctions."""

    failure = scorecard.failure
    if scorecard.correctness.infrastructure_error or (
        failure is not None and failure.infrastructure
    ):
        return "infrastructure_invalid"
    if scorecard.status == "cancelled" or scorecard.termination_reason in {
        "cancelled",
        "interrupted",
    }:
        return "cancelled_or_interrupted"
    if failure is not None and failure.kind == "policy":
        return "contained_workspace_policy_failure"
    if failure is not None and any(
        marker in failure.category
        for marker in ("strict_output", "parser_error", "output_format", "output_limit")
    ):
        return "strict_output_failure"
    if scorecard.resolved:
        return "resolved_candidate"
    return "incorrect_policy_compliant_candidate"


def _stage_passed(scorecard: ScoreCard, *, contains: str) -> int | None:
    matches = [
        result for result in scorecard.verifier_results if contains in result.node_id.lower()
    ]
    if not matches:
        return None
    if all(result.status.value == "skipped" for result in matches):
        return None
    return int(all(result.status.value == "passed" for result in matches))


def reward_vector(manifest: RunManifest, scorecard: ScoreCard) -> RewardVector:
    """Derive the authoritative vector without executing any external component."""

    outcome = classify_outcome(scorecard)
    infrastructure_valid = int(outcome != "infrastructure_invalid")
    if not infrastructure_valid:
        correctness: dict[str, int | None] = {
            "policy_compliance": None,
            "public_test_reached": None,
            "public_test_passed": None,
            "patch_reproducible": None,
            "candidate_compile_passed": None,
            "hidden_regression_passed": None,
            "task_resolved": None,
        }
    else:
        public_reached = bool(manifest.repository_public_tests)
        candidate = manifest.repository_candidate
        correctness = {
            "policy_compliance": int(outcome != "contained_workspace_policy_failure"),
            "public_test_reached": int(public_reached),
            "public_test_passed": (
                int(all(item.passed for item in manifest.repository_public_tests))
                if public_reached
                else None
            ),
            "patch_reproducible": (
                int(candidate.patch.reapply_exact) if candidate is not None else None
            ),
            "candidate_compile_passed": _stage_passed(
                scorecard,
                contains="compile",
            ),
            "hidden_regression_passed": _stage_passed(
                scorecard,
                contains="run_hidden",
            ),
            "task_resolved": int(scorecard.resolved),
        }
    candidate = manifest.repository_candidate
    patch = candidate.patch if candidate is not None else None
    efficiency = scorecard.efficiency
    input_tokens = (
        efficiency.external_input_tokens
        if efficiency.external_input_tokens is not None
        else efficiency.model_input_tokens
    )
    output_tokens = (
        efficiency.external_output_tokens
        if efficiency.external_output_tokens is not None
        else efficiency.model_output_tokens
    )
    return RewardVector.model_validate(
        {
            "outcome_kind": outcome,
            "infrastructure_valid": infrastructure_valid,
            **correctness,
            "changed_file_count": len(patch.changed_files) if patch is not None else None,
            "added_lines": patch.added_lines if patch is not None else None,
            "deleted_lines": patch.deleted_lines if patch is not None else None,
            "public_tool_calls": manifest.repository_public_tool_invocation_count,
            "wall_time_s": efficiency.wall_time_s,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    )


def derive_reward(
    manifest: RunManifest,
    scorecard: ScoreCard,
    *,
    manifest_sha256: str,
    scorecard_sha256: str,
    artifact_manifest_sha256: str,
    profile: RewardProfile | None = REPO_RTL_SPARSE_V1,
) -> RewardDerivationRecord:
    """Create a hash-bound, recomputable derivation record."""

    reward = reward_vector(manifest, scorecard)
    scalar = profile.outcome_values[reward.outcome_kind] if profile is not None else None
    return RewardDerivationRecord(
        run_id=manifest.run_id,
        source_artifact_hashes={
            "artifact_manifest.json": artifact_manifest_sha256,
            "run_manifest.json": manifest_sha256,
            "scorecard.json": scorecard_sha256,
        },
        reward=reward,
        reward_hash=content_hash(reward),
        scalar_profile_id=profile.profile_id if profile is not None else None,
        scalar_profile_hash=profile.profile_hash if profile is not None else None,
        scalar_reward=scalar,
    )


def recompute_reward(
    record: RewardDerivationRecord,
    manifest: RunManifest,
    scorecard: ScoreCard,
) -> RewardDerivationRecord:
    """Reject any reward-vector or profile mutation during offline replay."""

    recomputed = derive_reward(
        manifest,
        scorecard,
        manifest_sha256=record.source_artifact_hashes["run_manifest.json"],
        scorecard_sha256=record.source_artifact_hashes["scorecard.json"],
        artifact_manifest_sha256=record.source_artifact_hashes["artifact_manifest.json"],
        profile=(
            REPO_RTL_SPARSE_V1
            if record.scalar_profile_id == REPO_RTL_SPARSE_V1.profile_id
            else None
        ),
    )
    if recomputed != record:
        raise ValueError("reward derivation differs from frozen source artifacts")
    return recomputed


__all__ = [
    "REPO_RTL_SPARSE_V1",
    "classify_outcome",
    "derive_reward",
    "recompute_reward",
    "reward_vector",
]
