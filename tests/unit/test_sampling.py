from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from verigym.core.sampling import build_pass_at_k_report, compute_pass_at_k
from verigym.schemas.sampling import SampleOutcome, SampleRunRef, SampleSetManifest


@pytest.mark.parametrize(
    ("n", "c", "k", "expected"),
    [
        (1, 0, 1, 0.0),
        (1, 1, 1, 1.0),
        (4, 2, 1, 0.5),
        (4, 2, 2, 5 / 6),
        (4, 2, 3, 1.0),
        (4, 0, 4, 0.0),
        (4, 4, 1, 1.0),
        (4, 4, 4, 1.0),
        (2, 1, 3, None),
    ],
)
def test_unbiased_pass_at_k_exact_edge_cases(
    n: int,
    c: int,
    k: int,
    expected: float | None,
) -> None:
    value = compute_pass_at_k(n, c, k)
    if expected is None:
        assert value is None
    else:
        assert value == pytest.approx(expected)


@pytest.mark.parametrize(
    ("n", "c", "k"),
    [(-1, 0, 1), (1, -1, 1), (1, 2, 1), (1, 1, 0)],
)
def test_pass_at_k_rejects_invalid_arguments(n: int, c: int, k: int) -> None:
    with pytest.raises(ValueError):
        compute_pass_at_k(n, c, k)


def child(
    index: int,
    outcome: SampleOutcome,
    *,
    fingerprint: str = "same",
    task_id: str = "verilog-eval/v2-spec-to-rtl/Prob900_fixture_and",
) -> SampleRunRef:
    resolved = outcome == SampleOutcome.RESOLVED
    verdict = outcome in {
        SampleOutcome.RESOLVED,
        SampleOutcome.CANDIDATE_FAILURE,
        SampleOutcome.MODEL_OUTPUT_FAILURE,
    }
    return SampleRunRef(
        sample_index=index,
        seed=100 + index,
        run_id=f"run-{index}",
        task_id=task_id,
        relative_path=f"samples/{index:04d}/run-{index}",
        outcome=outcome,
        resolved=resolved,
        candidate_verdict=verdict,
        task_hash="task-hash",
        source_hash="source-hash",
        candidate_hash=hashlib.sha256(f"candidate-{index}".encode()).hexdigest(),
        configuration_fingerprint=fingerprint,
    )


def manifest(
    children: list[SampleRunRef],
    *,
    count: int | None = None,
    requested_k: list[int] | None = None,
    frozen_fingerprint: str | None = "same",
) -> SampleSetManifest:
    return SampleSetManifest(
        sample_set_id="sample-set",
        created_at_utc=datetime.now(UTC),
        task_id="verilog-eval/v2-spec-to-rtl/Prob900_fixture_and",
        requested_sample_count=count if count is not None else len(children),
        requested_k=requested_k or [1],
        base_seed=100,
        homogeneous_configuration_hash=frozen_fingerprint,
        child_runs=children,
    )


def test_report_counts_model_output_as_incorrect_candidate_verdict() -> None:
    report = build_pass_at_k_report(
        manifest(
            [
                child(0, SampleOutcome.RESOLVED),
                child(1, SampleOutcome.CANDIDATE_FAILURE),
                child(2, SampleOutcome.RESOLVED),
                child(3, SampleOutcome.MODEL_OUTPUT_FAILURE),
            ],
            requested_k=[1, 2, 3],
        )
    )
    assert report.canonical_valid
    assert report.valid_candidate_verdict_count == 4
    assert report.resolved_count == 2
    assert report.candidate_failure_count == 1
    assert report.model_output_failure_count == 1
    assert report.empirical_resolved_fraction == 0.5
    assert report.distinct_candidate_count == 4
    assert report.candidate_diversity_index == pytest.approx(0.75)
    assert report.candidate_diversity_valid
    assert [entry.value for entry in report.entries] == pytest.approx([0.5, 5 / 6, 1.0])


def test_infrastructure_error_invalidates_canonical_entries() -> None:
    report = build_pass_at_k_report(
        manifest(
            [
                child(0, SampleOutcome.RESOLVED),
                child(1, SampleOutcome.INFRASTRUCTURE_ERROR),
            ]
        )
    )
    assert not report.canonical_valid
    assert report.infrastructure_error_count == 1
    assert report.valid_candidate_verdict_count == 1
    assert report.empirical_resolved_fraction is None
    assert report.entries[0].value is None
    assert report.entries[0].invalid_reason == "infrastructure_error"


def test_mixed_configuration_task_or_frozen_fingerprint_is_rejected() -> None:
    mixed = build_pass_at_k_report(
        manifest(
            [
                child(0, SampleOutcome.RESOLVED, fingerprint="first"),
                child(1, SampleOutcome.RESOLVED, fingerprint="second"),
            ],
            frozen_fingerprint=None,
        )
    )
    assert not mixed.homogeneous
    assert mixed.entries[0].invalid_reason == "mixed_configuration"

    wrong_task = build_pass_at_k_report(
        manifest(
            [
                child(
                    0,
                    SampleOutcome.RESOLVED,
                    task_id="verilog-eval/v2-spec-to-rtl/Other",
                )
            ]
        )
    )
    assert not wrong_task.homogeneous
    assert wrong_task.entries[0].invalid_reason == "mixed_configuration"

    replaced = build_pass_at_k_report(
        manifest(
            [child(0, SampleOutcome.RESOLVED, fingerprint="replacement")],
            frozen_fingerprint="original",
        )
    )
    assert not replaced.homogeneous


def test_missing_cancelled_and_k_greater_than_n_are_unavailable() -> None:
    missing = build_pass_at_k_report(manifest([child(0, SampleOutcome.RESOLVED)], count=2))
    assert missing.missing_child_count == 1
    assert missing.entries[0].invalid_reason == "missing_child_results"

    cancelled = build_pass_at_k_report(manifest([child(0, SampleOutcome.CANCELLED_TRUNCATED)]))
    assert cancelled.entries[0].invalid_reason == "cancelled_or_truncated"

    too_large = build_pass_at_k_report(
        manifest([child(0, SampleOutcome.RESOLVED)], requested_k=[2])
    )
    assert too_large.entries[0].invalid_reason == "k_exceeds_n"
    assert too_large.entries[0].value is None


def test_candidate_diversity_uses_candidate_content_identity() -> None:
    repeated = child(1, SampleOutcome.CANDIDATE_FAILURE)
    first = child(0, SampleOutcome.RESOLVED)
    repeated = repeated.model_copy(update={"candidate_hash": first.candidate_hash})
    report = build_pass_at_k_report(manifest([first, repeated]))
    assert report.distinct_candidate_count == 1
    assert report.candidate_diversity_index == 0.0

    unavailable = first.model_copy(update={"candidate_hash": None})
    report = build_pass_at_k_report(manifest([unavailable]))
    assert not report.candidate_diversity_valid
    assert report.candidate_diversity_invalid_reason == "candidate_hash_unavailable"
