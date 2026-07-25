"""Independent one-task sampling and canonical unbiased pass@k reporting."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.loaders import dump_json, load_model
from verigym.core.replay import replay_run
from verigym.provenance import get_build_provenance
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunManifest
from verigym.schemas.sampling import (
    PassAtKEntry,
    PassAtKReport,
    SampleOutcome,
    SampleRunRef,
    SampleSetManifest,
    SampleSetResult,
)
from verigym.schemas.score import ScoreCard

if TYPE_CHECKING:
    from verigym.core.orchestrator import VeriGym

_CANCELLED_REASONS = {
    "turn_budget_exhausted",
    "tool_budget_exhausted",
    "model_budget_exhausted",
    "token_budget_exhausted",
    "wall_time_exhausted",
    "agent_abort",
    "runtime_error",
    "policy_violation",
    "cancelled",
}
_MODEL_OUTPUT_REASONS = {"model_output_invalid", "invalid_action_limit"}


def compute_pass_at_k(n: int, c: int, k: int) -> float | None:
    """Return the exact-combination unbiased estimator, or ``None`` when k > n."""

    if n < 0 or c < 0 or c > n:
        raise ValueError("pass@k requires 0 <= c <= n")
    if k < 1:
        raise ValueError("pass@k requires k >= 1")
    if k > n:
        return None
    numerator = 0 if k > n - c else math.comb(n - c, k)
    value = Fraction(1, 1) - Fraction(numerator, math.comb(n, k))
    return float(value)


def run_sample_set(
    service: VeriGym,
    config: RunConfig,
    *,
    samples: int,
    pass_k: list[int] | tuple[int, ...] = (1,),
) -> SampleSetResult:
    """Run N sequential, independent ChatEval children under one configuration."""

    requested_k, task_id = _validate_request(service, config, samples=samples, pass_k=pass_k)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    slug = task_id.replace("/", "-")
    sample_set_id = f"{timestamp}-sample-set-{slug}-{uuid.uuid4().hex[:8]}"
    group_dir = config.output.expanduser().resolve() / sample_set_id
    (group_dir / "samples").mkdir(parents=True)
    manifest = SampleSetManifest(
        sample_set_id=sample_set_id,
        created_at_utc=datetime.now(UTC),
        task_id=task_id,
        requested_sample_count=samples,
        requested_k=requested_k,
        base_seed=config.seed,
        build_provenance=get_build_provenance(),
    )
    dump_json(group_dir / "sample_set_manifest.json", manifest)

    children: list[SampleRunRef] = []
    errors: list[str] = []
    for sample_index in range(samples):
        sample_seed = config.seed + sample_index
        child_output = group_dir / "samples" / f"{sample_index:04d}"
        child_options = config.model_options.model_copy(update={"sample_index": sample_index})
        child_config = config.model_copy(
            deep=True,
            update={
                "sample_index": sample_index,
                "seed": sample_seed,
                "output": child_output,
                "model_options": child_options,
            },
        )
        try:
            result = service.run(child_config)
        except Exception as exc:
            errors.append(f"sample {sample_index}: {type(exc).__name__}: {exc}")
            continue
        fingerprint = manifest_configuration_fingerprint(result.manifest)
        children.append(
            _sample_ref(
                manifest=result.manifest,
                scorecard=result.scorecard,
                relative_path=result.run_dir.relative_to(group_dir).as_posix(),
                configuration_fingerprint=fingerprint,
            )
        )
        manifest = manifest.model_copy(update={"child_runs": children, "errors": errors})
        dump_json(group_dir / "sample_set_manifest.json", manifest)

    fingerprints = {child.configuration_fingerprint for child in children}
    manifest = manifest.model_copy(
        update={
            "child_runs": children,
            "errors": errors,
            "homogeneous_configuration_hash": (
                next(iter(fingerprints)) if len(fingerprints) == 1 else None
            ),
        }
    )
    report = build_pass_at_k_report(manifest)
    dump_json(group_dir / "sample_set_manifest.json", manifest)
    dump_json(group_dir / "pass_at_k.json", report)
    return SampleSetResult(group_dir=group_dir, manifest=manifest, report=report)


def regenerate_sample_report(group_dir: Path) -> SampleSetResult:
    """Rebuild an aggregate from frozen child artifacts without model or verifier calls."""

    group_dir = group_dir.expanduser().resolve()
    manifest = load_model(group_dir / "sample_set_manifest.json", SampleSetManifest)
    children: list[SampleRunRef] = []
    errors = list(manifest.errors)
    for frozen_child in manifest.child_runs:
        child_dir = (group_dir / frozen_child.relative_path).resolve(strict=False)
        if not child_dir.is_relative_to(group_dir):
            raise ConfigurationError("sample child path escapes the sample-set directory")
        try:
            replay = replay_run(child_dir, verify=False)
        except Exception as exc:
            errors.append(f"sample {frozen_child.sample_index}: {type(exc).__name__}: {exc}")
            continue
        children.append(
            _sample_ref(
                manifest=replay.manifest,
                scorecard=replay.scorecard,
                relative_path=frozen_child.relative_path,
                configuration_fingerprint=manifest_configuration_fingerprint(replay.manifest),
            )
        )
    regenerated = manifest.model_copy(
        update={
            "child_runs": children,
            "errors": errors,
        }
    )
    report = build_pass_at_k_report(regenerated)
    dump_json(group_dir / "sample_set_manifest.json", regenerated)
    dump_json(group_dir / "pass_at_k.json", report)
    return SampleSetResult(group_dir=group_dir, manifest=regenerated, report=report)


def manifest_configuration_fingerprint(manifest: RunManifest) -> str:
    """Hash every score-relevant homogeneous field, excluding sample seed/index."""

    runtime = manifest.runtime.model_dump(mode="json")
    runtime.pop("sessions", None)
    runtime.pop("cleanup", None)
    payload: dict[str, Any] = {
        "task_id": manifest.task_id,
        "task_hash": manifest.task_hash,
        "source_hash": manifest.source_hash,
        "verifier_hash": manifest.verifier_hash,
        "suite": manifest.suite,
        "suite_version": manifest.suite_version,
        "interaction_mode": manifest.interaction_mode,
        "model": manifest.model,
        "agent_harness": manifest.agent_harness or manifest.agent,
        "prompt_policy": manifest.prompt_policy,
        "tool_policy": manifest.tool_policy,
        "generation": manifest.generation,
        "suite_source": manifest.suite_source,
        "runtime": runtime,
        "toolchain_profiles": manifest.toolchain_profiles,
        "budget": manifest.budget,
        "isolation_level": manifest.environment_summary.get("unsafe_local_runtime"),
        "verifier_isolation": manifest.environment_summary.get("verifier_isolation"),
    }
    if manifest.agent_configuration_fingerprint is not None:
        payload["agent_configuration_fingerprint"] = manifest.agent_configuration_fingerprint
    if manifest.external_agent_observations:
        payload["external_agent_identity"] = [
            {
                "integration_track": observation.integration_track,
                "requested_model_id": observation.requested_model_id,
                "observed_model_id": observation.observed_model_id,
                "executable_sha256": observation.executable_sha256,
                "executable_version": observation.executable_version,
                "capability_fingerprint": observation.capability_fingerprint,
                "identity_confidence": observation.identity_confidence,
            }
            for observation in manifest.external_agent_observations
        ]
    return content_hash(payload)


def build_pass_at_k_report(manifest: SampleSetManifest) -> PassAtKReport:
    children = manifest.child_runs
    outcomes = [child.outcome for child in children]
    resolved_count = outcomes.count(SampleOutcome.RESOLVED)
    candidate_failure_count = outcomes.count(SampleOutcome.CANDIDATE_FAILURE)
    model_output_failure_count = outcomes.count(SampleOutcome.MODEL_OUTPUT_FAILURE)
    infrastructure_error_count = outcomes.count(SampleOutcome.INFRASTRUCTURE_ERROR)
    cancelled_count = outcomes.count(SampleOutcome.CANCELLED_TRUNCATED)
    valid_verdicts = resolved_count + candidate_failure_count + model_output_failure_count
    missing_count = manifest.requested_sample_count - len(children)
    fingerprints = {child.configuration_fingerprint for child in children}
    task_ids_match = all(child.task_id == manifest.task_id for child in children)
    frozen_fingerprint_matches = (
        manifest.homogeneous_configuration_hash is None
        or not fingerprints
        or fingerprints == {manifest.homogeneous_configuration_hash}
    )
    homogeneous = len(fingerprints) <= 1 and task_ids_match and frozen_fingerprint_matches
    homogeneity_error = None if homogeneous else "child runs have mixed score configurations"

    base_invalid_reason: str | None = None
    if not homogeneous:
        base_invalid_reason = "mixed_configuration"
    elif missing_count:
        base_invalid_reason = "missing_child_results"
    elif infrastructure_error_count:
        base_invalid_reason = "infrastructure_error"
    elif cancelled_count:
        base_invalid_reason = "cancelled_or_truncated"
    elif valid_verdicts != manifest.requested_sample_count:
        base_invalid_reason = "incomplete_candidate_verdicts"

    entries: list[PassAtKEntry] = []
    for k in manifest.requested_k:
        reason = base_invalid_reason
        if reason is None and k > manifest.requested_sample_count:
            reason = "k_exceeds_n"
        value = (
            compute_pass_at_k(manifest.requested_sample_count, resolved_count, k)
            if reason is None
            else None
        )
        entries.append(
            PassAtKEntry(
                k=k,
                n=manifest.requested_sample_count,
                c=resolved_count,
                value=value,
                valid=reason is None,
                invalid_reason=reason,
            )
        )

    complete_candidate_set = base_invalid_reason is None
    return PassAtKReport(
        sample_set_id=manifest.sample_set_id,
        task_id=manifest.task_id,
        requested_sample_count=manifest.requested_sample_count,
        valid_candidate_verdict_count=valid_verdicts,
        resolved_count=resolved_count,
        candidate_failure_count=candidate_failure_count,
        model_output_failure_count=model_output_failure_count,
        infrastructure_error_count=infrastructure_error_count,
        cancelled_truncated_count=cancelled_count,
        missing_child_count=missing_count,
        empirical_resolved_fraction=(
            resolved_count / manifest.requested_sample_count if complete_candidate_set else None
        ),
        any_resolved=resolved_count > 0,
        homogeneous=homogeneous,
        homogeneity_error=homogeneity_error,
        canonical_valid=complete_candidate_set and all(entry.valid for entry in entries),
        entries=entries,
        child_runs=children,
    )


def _validate_request(
    service: VeriGym,
    config: RunConfig,
    *,
    samples: int,
    pass_k: list[int] | tuple[int, ...],
) -> tuple[list[int], str]:
    if samples < 1:
        raise ConfigurationError("sample count must be at least one")
    requested_k = list(pass_k)
    if not requested_k:
        requested_k = [1]
    if any(k < 1 for k in requested_k):
        raise ConfigurationError("pass@k values must be positive integers")
    if len(requested_k) != len(set(requested_k)):
        raise ConfigurationError("pass@k values must not be repeated")
    if config.mode != InteractionMode.CHAT:
        raise ConfigurationError("Milestone 6 multi-sample execution supports ChatEval only")
    if config.sample_index is not None:
        raise ConfigurationError("sample_index is assigned by the sample-set runner")
    if config.model is None:
        raise ConfigurationError("multi-sample ChatEval requires a model client")
    if config.suite_source is None:
        _suite, task, _assets = service.load_task(config.task_id)
    else:
        _suite, task, _assets = service.load_task(config.task_id, config.suite_source)
    agent = service.registries.agents.get(config.agent)
    if config.mode not in agent.supported_modes or not agent.requires_model:
        raise ConfigurationError(f"agent {config.agent!r} is not a model-backed ChatEval harness")
    configured_model = service.registries.models.get(config.model)
    service.registries.runtimes.get(config.runtime)
    for sample_index in range(samples):
        options = config.model_options.model_copy(update={"sample_index": sample_index})
        configured_model.clone_for_run(options)
    return requested_k, task.id


def _sample_ref(
    *,
    manifest: RunManifest,
    scorecard: ScoreCard,
    relative_path: str,
    configuration_fingerprint: str,
) -> SampleRunRef:
    outcome, verdict = classify_sample_outcome(scorecard)
    if manifest.sample_index is None:
        raise ConfigurationError("sample child manifest has no sample index")
    return SampleRunRef(
        sample_index=manifest.sample_index,
        seed=manifest.seed,
        run_id=manifest.run_id,
        task_id=manifest.task_id,
        relative_path=relative_path,
        outcome=outcome,
        resolved=scorecard.resolved,
        candidate_verdict=verdict,
        task_hash=manifest.task_hash,
        source_hash=manifest.source_hash,
        configuration_fingerprint=configuration_fingerprint,
    )


def classify_sample_outcome(scorecard: ScoreCard) -> tuple[SampleOutcome, bool]:
    """Classify one scorecard using the canonical Milestone 6 sample semantics."""

    if (
        scorecard.status == "error"
        or scorecard.correctness.infrastructure_error
        or bool(scorecard.failure and scorecard.failure.infrastructure)
    ):
        return SampleOutcome.INFRASTRUCTURE_ERROR, False
    if scorecard.termination_reason in _MODEL_OUTPUT_REASONS:
        return SampleOutcome.MODEL_OUTPUT_FAILURE, True
    if scorecard.termination_reason in _CANCELLED_REASONS or scorecard.status == "cancelled":
        return SampleOutcome.CANCELLED_TRUNCATED, False
    if scorecard.resolved:
        return SampleOutcome.RESOLVED, True
    return SampleOutcome.CANDIDATE_FAILURE, True


__all__ = [
    "build_pass_at_k_report",
    "classify_sample_outcome",
    "compute_pass_at_k",
    "manifest_configuration_fingerprint",
    "regenerate_sample_report",
    "run_sample_set",
]
