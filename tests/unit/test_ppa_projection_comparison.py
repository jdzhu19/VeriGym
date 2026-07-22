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
from verigym.profiles.comparison import compare_area
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
        eligible=eligible,
        ineligible_reasons=[] if eligible else ["test_ineligible"],
        area=area if eligible else None,
        area_unit=profile.area_unit,
        reference_area=100.0 if eligible else None,
        area_ratio=100.0 / area if eligible else None,
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
