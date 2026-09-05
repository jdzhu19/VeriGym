from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from verigym.cli.app import app
from verigym.core.episode import BudgetTracker, TerminationReason
from verigym.core.errors import ComparisonError
from verigym.core.hashing import content_hash
from verigym.core.loaders import dump_json
from verigym.core.orchestrator import VeriGym
from verigym.core.scoring import build_scorecard
from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.profiles.comparison import compare_area, compare_power, compare_timing
from verigym.schemas.common import ToolchainProfileRef
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import WorkspaceDiff
from verigym.schemas.score import PPAMetrics, QualityMetrics, ScoreCard
from verigym.schemas.synthesis import SynthesisMetrics
from verigym.schemas.verifier import VerifierResult, VerifierStatus
from verigym.suites.toy_rtl.adapter import ToyRtlSuite


def _resolved(profile_id: str = "profile", asset_hash: str = "a" * 64) -> ResolvedToolchainProfile:
    value = ResolvedToolchainProfile(
        profile_id=profile_id,
        profile_version="1.0.0",
        declared_profile_hash="b" * 64,
        resolved_profile_hash="",
        reproducibility_scope="public",
        deterministic=True,
        runtime_identity=ResolvedRuntimeIdentity(
            runtime_slug="docker",
            isolation_level="docker_standard",
            deterministic=True,
            os="linux",
            architecture="amd64",
            resolved_image_id="sha256:" + "c" * 64,
            network_policy="none",
            resource_controls=True,
        ),
        tool_identities=[
            ResolvedToolIdentity(
                logical_name="yosys",
                executable="yosys",
                version="0.67",
                version_output="Yosys 0.67",
                identity_kind="immutable_image_observation",
            )
        ],
        asset_identities=[
            ResolvedArtifactIdentity(
                logical_id="cells",
                media_type="application/x-liberty",
                source_kind="package_resource",
                content_hash=asset_hash,
                redistributable=True,
                unit="toy_area_unit",
                copy_permitted=True,
            )
        ],
        flow_hash="1" * 64,
        metric_contract_hash="2" * 64,
        reference_contract_hash="3" * 64,
        flow_template_id="verigym-yosys-area-v1",
        generated_script_hash="4" * 64,
        top_module="counter",
        source_paths=["rtl/counter.v"],
        metric_scope="synthesis_area_only",
        area_unit="toy_area_unit",
        reference_strategy="suite_reference_solution",
        reference_candidate_hash="5" * 64,
    )
    return value.model_copy(
        update={"resolved_profile_hash": content_hash(value.identity_payload())}
    )


def _metrics(role: str, area: float, profile_hash: str, *, ok: bool = True) -> SynthesisMetrics:
    return SynthesisMetrics(
        status="passed" if ok else "failed",
        synthesis_ok=ok,
        role=role,  # type: ignore[arg-type]
        top="counter",
        num_wires=3,
        num_wire_bits=10,
        num_memories=0,
        num_memory_bits=0,
        num_processes=0,
        num_cells=10,
        cells_by_type={"VG_DFF": 8, "VG_XOR2": 2},
        mapped_area_raw=area,
        mapped_area_unit="toy_area_unit",
        mapped_area_source_hash="a" * 64,
        resolved_profile_hash=profile_hash,
        generated_script_hash="4" * 64,
    )


def _resolved_timing() -> ResolvedToolchainProfile:
    value = _resolved().model_copy(
        update={
            "resolved_profile_hash": "",
            "metric_scope": "synthesis_area_timing",
            "timing_unit": "ns",
            "metadata": {"clock_period": 10.0},
        }
    )
    return value.model_copy(
        update={"resolved_profile_hash": content_hash(value.identity_payload())}
    )


def _timing_metrics(
    role: str,
    area: float,
    delay: float,
    slack: float,
    profile_hash: str,
) -> SynthesisMetrics:
    return _metrics(role, area, profile_hash).model_copy(
        update={
            "critical_path_delay_raw": delay,
            "worst_negative_slack_raw": slack,
            "timing_unit": "ns",
            "clock_period": 10.0,
            "timing_constraints_hash": "9" * 64,
        }
    )


def _resolved_power() -> ResolvedToolchainProfile:
    value = _resolved_timing().model_copy(
        update={
            "resolved_profile_hash": "",
            "metric_scope": "synthesis_area_timing_power",
            "power_unit": "uW",
            "metadata": {"clock_period": 10.0, "power_activity_mode": "vectorless_default"},
        }
    )
    return value.model_copy(
        update={"resolved_profile_hash": content_hash(value.identity_payload())}
    )


def test_optional_power_unit_preserves_legacy_resolved_identity_shape() -> None:
    assert "power_unit" not in _resolved().identity_payload()
    assert _resolved_power().identity_payload()["power_unit"] == "uW"


def _power_metrics(
    role: str,
    area: float,
    delay: float,
    slack: float,
    power: float,
    profile_hash: str,
) -> SynthesisMetrics:
    return _timing_metrics(role, area, delay, slack, profile_hash).model_copy(
        update={
            "total_power_raw": power,
            "power_unit": "uW",
            "power_activity_mode": "vectorless_default",
        }
    )


def _score(
    *,
    correctness: bool,
    candidate_area: float,
    reference_area: float,
) -> tuple[ScoreCard, ResolvedToolchainProfile]:
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    resolved = _resolved()
    status = VerifierStatus.PASSED if correctness else VerifierStatus.FAILED
    results = [
        VerifierResult(
            node_id="compile_hidden",
            plugin="iverilog.compile",
            status=VerifierStatus.PASSED,
        ),
        VerifierResult(node_id="run_hidden", plugin="iverilog.run", status=status),
    ]
    candidate = _metrics("candidate", candidate_area, resolved.resolved_profile_hash)
    reference = _metrics("reference", reference_area, resolved.resolved_profile_hash)
    card = build_scorecard(
        run_id="run",
        task=task,
        results=results,
        diff=WorkspaceDiff(),
        tracker=BudgetTracker(task.budget),
        termination_reason=TerminationReason.FINAL_SUBMISSION,
        task_hash=content_hash(task),
        candidate_hash="6" * 64,
        run_config_hash="7" * 64,
        profile_refs=[ToolchainProfileRef(id="profile", version="1.0.0", content_hash="8" * 64)],
        isolation_level="docker_standard",
        resolved_profile=resolved,
        candidate_synthesis=candidate,
        reference_synthesis=reference,
    )
    return card, resolved


@pytest.mark.parametrize(("candidate", "expected"), [(100.0, 1.0), (80.0, 1.25), (125.0, 0.8)])
def test_correctness_gated_area_ratio(candidate: float, expected: float) -> None:
    card, _resolved_profile = _score(
        correctness=True, candidate_area=candidate, reference_area=100.0
    )
    ppa = card.quality.ppa
    assert ppa is not None and ppa.eligible
    assert ppa.area == candidate
    assert ppa.reference_area == 100.0
    assert ppa.area_ratio == expected
    assert ppa.delay is None
    assert ppa.frequency is None
    assert ppa.power is None
    assert ppa.worst_negative_slack is None
    assert ppa.total_negative_slack is None


def test_incorrect_candidate_keeps_raw_area_but_has_no_ranked_values() -> None:
    card, _resolved_profile = _score(correctness=False, candidate_area=1.0, reference_area=100.0)
    assert not card.resolved
    assert card.quality.synthesis is not None
    assert card.quality.synthesis.mapped_area_raw == 1.0
    ppa = card.quality.ppa
    assert ppa is not None and not ppa.eligible
    assert "correctness_gate_failed" in ppa.ineligible_reasons
    assert ppa.area is None
    assert ppa.reference_area is None
    assert ppa.area_ratio is None


def test_area_timing_projection_keeps_metrics_separate() -> None:
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    resolved = _resolved_timing()
    results = [
        VerifierResult(
            node_id="compile_hidden",
            plugin="iverilog.compile",
            status=VerifierStatus.PASSED,
        ),
        VerifierResult(
            node_id="run_hidden",
            plugin="iverilog.run",
            status=VerifierStatus.PASSED,
        ),
    ]
    card = build_scorecard(
        run_id="timing-run",
        task=task,
        results=results,
        diff=WorkspaceDiff(),
        tracker=BudgetTracker(task.budget),
        termination_reason=TerminationReason.FINAL_SUBMISSION,
        task_hash=content_hash(task),
        candidate_hash="6" * 64,
        run_config_hash="7" * 64,
        profile_refs=[ToolchainProfileRef(id="profile", version="1.0.0", content_hash="8" * 64)],
        isolation_level="local_trusted",
        resolved_profile=resolved,
        candidate_synthesis=_timing_metrics(
            "candidate", 80.0, 4.0, -0.5, resolved.resolved_profile_hash
        ),
        reference_synthesis=_timing_metrics(
            "reference", 100.0, 5.0, -1.0, resolved.resolved_profile_hash
        ),
    )
    ppa = card.quality.ppa
    assert ppa is not None and ppa.eligible
    assert ppa.area_ratio == 1.25
    assert ppa.delay_ratio == 1.25
    assert ppa.worst_negative_slack_delta == 0.5
    assert ppa.power is None


def test_area_timing_power_projection_reports_reference_ratio() -> None:
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    resolved = _resolved_power()
    results = [
        VerifierResult(
            node_id="compile_hidden",
            plugin="iverilog.compile",
            status=VerifierStatus.PASSED,
        ),
        VerifierResult(
            node_id="run_hidden",
            plugin="iverilog.run",
            status=VerifierStatus.PASSED,
        ),
    ]
    card = build_scorecard(
        run_id="power-run",
        task=task,
        results=results,
        diff=WorkspaceDiff(),
        tracker=BudgetTracker(task.budget),
        termination_reason=TerminationReason.FINAL_SUBMISSION,
        task_hash=content_hash(task),
        candidate_hash="6" * 64,
        run_config_hash="7" * 64,
        profile_refs=[ToolchainProfileRef(id="profile", version="1.0.0", content_hash="8" * 64)],
        isolation_level="local_trusted",
        resolved_profile=resolved,
        candidate_synthesis=_power_metrics(
            "candidate", 80.0, 4.0, -0.5, 8.0, resolved.resolved_profile_hash
        ),
        reference_synthesis=_power_metrics(
            "reference", 100.0, 5.0, -1.0, 10.0, resolved.resolved_profile_hash
        ),
    )
    ppa = card.quality.ppa
    assert ppa is not None and ppa.eligible
    assert ppa.power == 8.0
    assert ppa.reference_power == 10.0
    assert ppa.power_ratio == 1.25
    assert ppa.power_unit == "uW"


def test_opensta_power_projection_compares_the_complete_activity_identity() -> None:
    suite = ToyRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    unresolved = _resolved_power().model_copy(
        update={
            "resolved_profile_hash": "",
            "flow_template_id": "verigym-yosys-opensta-atp-v2",
            "metadata": {
                "clock_period": 10.0,
                "power_activity_mode": "global_clock_relative",
                "power_activity": 0.1,
                "power_duty": 0.5,
            },
        }
    )
    resolved = unresolved.model_copy(
        update={"resolved_profile_hash": content_hash(unresolved.identity_payload())}
    )
    results = [
        VerifierResult(
            node_id="compile_hidden",
            plugin="iverilog.compile",
            status=VerifierStatus.PASSED,
        ),
        VerifierResult(
            node_id="run_hidden",
            plugin="iverilog.run",
            status=VerifierStatus.PASSED,
        ),
    ]
    activity_identity = "opensta_global_clock_relative:activity=0.1:duty=0.5"
    candidate = _power_metrics(
        "candidate", 80.0, 4.0, -0.5, 8.0, resolved.resolved_profile_hash
    ).model_copy(update={"power_activity_mode": activity_identity})
    reference = _power_metrics(
        "reference", 100.0, 5.0, -1.0, 10.0, resolved.resolved_profile_hash
    ).model_copy(update={"power_activity_mode": activity_identity})

    card = build_scorecard(
        run_id="opensta-power-run",
        task=task,
        results=results,
        diff=WorkspaceDiff(),
        tracker=BudgetTracker(task.budget),
        termination_reason=TerminationReason.FINAL_SUBMISSION,
        task_hash=content_hash(task),
        candidate_hash="6" * 64,
        run_config_hash="7" * 64,
        profile_refs=[ToolchainProfileRef(id="profile", version="1.0.0", content_hash="8" * 64)],
        isolation_level="docker_standard",
        resolved_profile=resolved,
        candidate_synthesis=candidate,
        reference_synthesis=reference,
    )

    ppa = card.quality.ppa
    assert ppa is not None and ppa.eligible
    assert ppa.power == 8.0
    assert ppa.reference_power == 10.0

    mismatched = build_scorecard(
        run_id="opensta-power-mismatch",
        task=task,
        results=results,
        diff=WorkspaceDiff(),
        tracker=BudgetTracker(task.budget),
        termination_reason=TerminationReason.FINAL_SUBMISSION,
        task_hash=content_hash(task),
        candidate_hash="6" * 64,
        run_config_hash="7" * 64,
        profile_refs=[ToolchainProfileRef(id="profile", version="1.0.0", content_hash="8" * 64)],
        isolation_level="docker_standard",
        resolved_profile=resolved,
        candidate_synthesis=candidate.model_copy(
            update={"power_activity_mode": "opensta_global_clock_relative:activity=0.2:duty=0.5"}
        ),
        reference_synthesis=reference,
    )
    mismatch_ppa = mismatched.quality.ppa
    assert mismatch_ppa is not None and not mismatch_ppa.eligible
    assert mismatch_ppa.ineligible_reasons == ["candidate_power_activity_mismatch"]


@pytest.mark.parametrize("area", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_synthesis_and_ranked_schemas_reject_invalid_area(area: float) -> None:
    with pytest.raises(ValidationError, match="finite and positive"):
        SynthesisMetrics(
            status="passed",
            synthesis_ok=True,
            role="candidate",
            top="counter",
            mapped_area_raw=area,
        )
    with pytest.raises(ValidationError):
        PPAMetrics(
            profile_id="p",
            eligible=True,
            area=area,
            reference_area=1.0,
            area_ratio=1.0,
            area_unit="unit",
        )


def _write_ranked_run(
    root: Path,
    *,
    profile: ResolvedToolchainProfile,
    area: float,
    eligible: bool = True,
    delay: float | None = None,
    worst_negative_slack: float | None = None,
    power: float | None = None,
) -> Path:
    result = VeriGym().run(
        RunConfig(
            task_id="toy-rtl/counter-basic",
            agent="scripted",
            output=root,
        )
    )
    manifest = result.manifest.model_copy(
        update={
            "requested_toolchain_profile_id": profile.profile_id,
            "requested_toolchain_profile_version": profile.profile_version,
            "declared_profile_hash": profile.declared_profile_hash,
            "resolved_profile_hash": profile.resolved_profile_hash,
            "reference_strategy": profile.reference_strategy,
            "reference_candidate_hash": profile.reference_candidate_hash,
        }
    )
    ppa = PPAMetrics(
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        resolved_profile_hash=profile.resolved_profile_hash,
        scope=profile.metric_scope,
        eligible=eligible,
        ineligible_reasons=[] if eligible else ["test_ineligible"],
        area=area if eligible else None,
        area_unit=profile.area_unit,
        reference_area=100.0 if eligible else None,
        area_ratio=100.0 / area if eligible else None,
        delay=delay if eligible else None,
        timing_unit=(profile.timing_unit if eligible and delay is not None else None),
        clock_period=(10.0 if eligible and delay is not None else None),
        reference_delay=(5.0 if eligible and delay is not None else None),
        delay_ratio=(5.0 / delay if eligible and delay is not None else None),
        worst_negative_slack=(worst_negative_slack if eligible else None),
        reference_worst_negative_slack=(
            -1.0 if eligible and worst_negative_slack is not None else None
        ),
        worst_negative_slack_delta=(
            worst_negative_slack - -1.0 if eligible and worst_negative_slack is not None else None
        ),
        power=power if eligible else None,
        power_unit=(profile.power_unit if eligible and power is not None else None),
        reference_power=(10.0 if eligible and power is not None else None),
        power_ratio=(10.0 / power if eligible and power is not None else None),
    )
    scorecard = result.scorecard.model_copy(update={"quality": QualityMetrics(ppa=ppa)})
    dump_json(result.run_dir / "run_manifest.json", manifest)
    dump_json(result.run_dir / "scorecard.json", scorecard)
    dump_json(result.run_dir / "artifacts/resolved_toolchain_profile.json", profile)
    return result.run_dir


def test_comparison_allows_only_exact_eligible_profile_identity(tmp_path: Path) -> None:
    exact = _resolved()
    run_a = _write_ranked_run(tmp_path / "a", profile=exact, area=80.0)
    run_b = _write_ranked_run(tmp_path / "b", profile=exact, area=100.0)
    allowed = compare_area(run_a, run_b)
    assert allowed.relation == "run_a_better"
    assert allowed.winner_run_id is not None

    different_id = _resolved(profile_id="other")
    run_c = _write_ranked_run(tmp_path / "c", profile=different_id, area=70.0)
    with pytest.raises(ComparisonError, match="profile_id differs"):
        compare_area(run_a, run_c)

    changed_asset = _resolved(asset_hash="9" * 64)
    run_d = _write_ranked_run(tmp_path / "d", profile=changed_asset, area=70.0)
    with pytest.raises(ComparisonError, match="resolved_profile_hash differs"):
        compare_area(run_a, run_d)

    run_e = _write_ranked_run(tmp_path / "e", profile=exact, area=70.0, eligible=False)
    with pytest.raises(ComparisonError, match="PPA-ineligible"):
        compare_area(run_a, run_e)

    refused = CliRunner().invoke(
        app, ["report", "compare", str(run_a), str(run_c), "--metric", "area"]
    )
    assert refused.exit_code == 2
    assert "invalid comparison" in refused.output
    assert "winner_run_id" not in refused.output


def test_timing_comparison_uses_metric_direction(tmp_path: Path) -> None:
    profile = _resolved_timing()
    run_a = _write_ranked_run(
        tmp_path / "a",
        profile=profile,
        area=80.0,
        delay=4.0,
        worst_negative_slack=-0.5,
    )
    run_b = _write_ranked_run(
        tmp_path / "b",
        profile=profile,
        area=100.0,
        delay=5.0,
        worst_negative_slack=-1.0,
    )
    delay = compare_timing(run_a, run_b, metric="delay")
    slack = compare_timing(run_a, run_b, metric="worst_negative_slack")
    assert delay.relation == "run_a_better"
    assert slack.relation == "run_a_better"


def test_power_comparison_and_cli_use_smaller_is_better(tmp_path: Path) -> None:
    profile = _resolved_power()
    run_a = _write_ranked_run(
        tmp_path / "a",
        profile=profile,
        area=80.0,
        delay=4.0,
        worst_negative_slack=-0.5,
        power=8.0,
    )
    run_b = _write_ranked_run(
        tmp_path / "b",
        profile=profile,
        area=100.0,
        delay=5.0,
        worst_negative_slack=-1.0,
        power=10.0,
    )
    compared = compare_power(run_a, run_b)
    assert compared.relation == "run_a_better"
    assert compared.power_a_over_power_b == pytest.approx(0.8)

    invoked = CliRunner().invoke(
        app, ["report", "compare", str(run_a), str(run_b), "--metric", "power"]
    )
    assert invoked.exit_code == 0
    assert '"metric": "power"' in invoked.output
