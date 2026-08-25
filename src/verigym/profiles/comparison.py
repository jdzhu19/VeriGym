"""Strict, intentionally narrow ranked-area comparison safeguards."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from verigym.core.errors import ComparisonError
from verigym.core.hashing import content_hash
from verigym.core.loaders import load_model
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.schemas.base import StrictModel
from verigym.schemas.run import RunManifest
from verigym.schemas.score import ScoreCard


class AreaComparison(StrictModel):
    metric: Literal["area"] = "area"
    comparable: Literal[True] = True
    run_a: str
    run_b: str
    area_a: float
    area_b: float
    area_unit: str
    resolved_profile_hash: str
    winner_run_id: str | None
    relation: Literal["run_a_better", "run_b_better", "equal"]
    area_a_over_area_b: float


class TimingComparison(StrictModel):
    metric: Literal["delay", "worst_negative_slack"]
    comparable: Literal[True] = True
    run_a: str
    run_b: str
    value_a: float
    value_b: float
    unit: str
    resolved_profile_hash: str
    winner_run_id: str | None
    relation: Literal["run_a_better", "run_b_better", "equal"]
    value_a_over_value_b: float | None
    value_a_minus_value_b: float


class PowerComparison(StrictModel):
    metric: Literal["power"] = "power"
    comparable: Literal[True] = True
    run_a: str
    run_b: str
    power_a: float
    power_b: float
    power_unit: str
    resolved_profile_hash: str
    winner_run_id: str | None
    relation: Literal["run_a_better", "run_b_better", "equal"]
    power_a_over_power_b: float


def _load(run_dir: Path) -> tuple[RunManifest, ScoreCard, ResolvedToolchainProfile]:
    root = run_dir.expanduser().resolve()
    manifest_path = root / "run_manifest.json"
    scorecard_path = root / "scorecard.json"
    profile_path = root / "artifacts" / "resolved_toolchain_profile.json"
    if not manifest_path.is_file() or not scorecard_path.is_file() or not profile_path.is_file():
        raise ComparisonError(
            f"run {root} is missing manifest, scorecard, or resolved profile metadata"
        )
    manifest = load_model(manifest_path, RunManifest)
    scorecard = load_model(scorecard_path, ScoreCard)
    profile = load_model(profile_path, ResolvedToolchainProfile)
    if content_hash(profile.identity_payload()) != profile.resolved_profile_hash:
        raise ComparisonError(f"run {root} has a non-canonical resolved profile hash")
    if manifest.resolved_profile_hash != profile.resolved_profile_hash:
        raise ComparisonError(f"run {root} manifest and resolved profile hashes differ")
    if manifest.declared_profile_hash != profile.declared_profile_hash:
        raise ComparisonError(f"run {root} manifest and declared profile hashes differ")
    if (
        manifest.requested_toolchain_profile_id != profile.profile_id
        or manifest.requested_toolchain_profile_version != profile.profile_version
    ):
        raise ComparisonError(f"run {root} manifest and resolved profile IDs differ")
    if (
        manifest.resolved_toolchain_profile is not None
        and manifest.resolved_toolchain_profile != profile
    ):
        raise ComparisonError(f"run {root} inline and artifact profile identities differ")
    return manifest, scorecard, profile


def compare_area(run_a: Path, run_b: Path) -> AreaComparison:
    manifest_a, score_a, profile_a = _load(run_a)
    manifest_b, score_b, profile_b = _load(run_b)
    ppa_a = score_a.quality.ppa
    ppa_b = score_b.quality.ppa
    mismatches: list[str] = []
    if ppa_a is None or ppa_b is None:
        mismatches.append("missing profile/PPA metadata")
    else:
        if (
            ppa_a.profile_id != profile_a.profile_id
            or ppa_a.profile_version != profile_a.profile_version
            or ppa_a.resolved_profile_hash != profile_a.resolved_profile_hash
        ):
            mismatches.append("run A PPA and resolved profile identity differ")
        if (
            ppa_b.profile_id != profile_b.profile_id
            or ppa_b.profile_version != profile_b.profile_version
            or ppa_b.resolved_profile_hash != profile_b.resolved_profile_hash
        ):
            mismatches.append("run B PPA and resolved profile identity differ")
        if ppa_a.profile_id != ppa_b.profile_id:
            mismatches.append(f"profile_id differs ({ppa_a.profile_id!r} != {ppa_b.profile_id!r})")
        if ppa_a.profile_version != ppa_b.profile_version:
            mismatches.append("profile_version differs")
        if ppa_a.resolved_profile_hash != ppa_b.resolved_profile_hash:
            mismatches.append("resolved_profile_hash differs")
        if ppa_a.scope != ppa_b.scope:
            mismatches.append("metric scope differs")
        if ppa_a.area_unit != ppa_b.area_unit:
            mismatches.append("area unit differs")
        if not ppa_a.eligible:
            mismatches.append("run A is PPA-ineligible")
        if not ppa_b.eligible:
            mismatches.append("run B is PPA-ineligible")
    if manifest_a.task_id != manifest_b.task_id:
        mismatches.append("task_id differs")
    if manifest_a.task_hash != manifest_b.task_hash:
        mismatches.append("task content hash differs")
    if manifest_a.verifier_hash != manifest_b.verifier_hash:
        mismatches.append("correctness definition differs")
    if manifest_a.reference_strategy != manifest_b.reference_strategy:
        mismatches.append("reference strategy differs")
    if manifest_a.reference_candidate_hash != manifest_b.reference_candidate_hash:
        mismatches.append("reference candidate hash differs")
    if manifest_a.declared_profile_hash != manifest_b.declared_profile_hash:
        mismatches.append("declared_profile_hash differs")
    if profile_a.profile_id != profile_b.profile_id:
        mismatches.append("resolved profile IDs differ")
    if profile_a.resolved_profile_hash != profile_b.resolved_profile_hash:
        if content_hash(profile_a.runtime_identity) != content_hash(profile_b.runtime_identity):
            mismatches.append("runtime/image identity differs")
        if content_hash(profile_a.tool_identities) != content_hash(profile_b.tool_identities):
            mismatches.append("Yosys/ABC identity differs")
        if content_hash(profile_a.asset_identities) != content_hash(profile_b.asset_identities):
            mismatches.append("library/script identity differs")
    if mismatches:
        raise ComparisonError("invalid comparison: " + "; ".join(dict.fromkeys(mismatches)))
    assert ppa_a is not None and ppa_b is not None
    assert ppa_a.area is not None and ppa_b.area is not None and ppa_a.area_unit is not None
    if ppa_a.area < ppa_b.area:
        winner = score_a.run_id
        relation = "run_a_better"
    elif ppa_b.area < ppa_a.area:
        winner = score_b.run_id
        relation = "run_b_better"
    else:
        winner = None
        relation = "equal"
    return AreaComparison(
        run_a=score_a.run_id,
        run_b=score_b.run_id,
        area_a=ppa_a.area,
        area_b=ppa_b.area,
        area_unit=ppa_a.area_unit,
        resolved_profile_hash=ppa_a.resolved_profile_hash,
        winner_run_id=winner,
        relation=relation,  # type: ignore[arg-type]
        area_a_over_area_b=ppa_a.area / ppa_b.area,
    )


def compare_timing(
    run_a: Path,
    run_b: Path,
    *,
    metric: Literal["delay", "worst_negative_slack"],
) -> TimingComparison:
    """Compare one timing metric after the ordinary exact-profile safeguards."""

    compare_area(run_a, run_b)
    _manifest_a, score_a, profile_a = _load(run_a)
    _manifest_b, score_b, profile_b = _load(run_b)
    ppa_a = score_a.quality.ppa
    ppa_b = score_b.quality.ppa
    assert ppa_a is not None and ppa_b is not None
    mismatches: list[str] = []
    timing_scopes = {"synthesis_area_timing", "synthesis_area_timing_power"}
    if ppa_a.scope not in timing_scopes or ppa_b.scope not in timing_scopes:
        mismatches.append("timing comparison requires area/timing profiles")
    if ppa_a.timing_unit is None or ppa_a.timing_unit != ppa_b.timing_unit:
        mismatches.append("timing unit differs or is unavailable")
    if ppa_a.clock_period is None or ppa_a.clock_period != ppa_b.clock_period:
        mismatches.append("clock period differs or is unavailable")
    if profile_a.timing_unit != profile_b.timing_unit:
        mismatches.append("resolved timing units differ")
    if metric == "delay":
        value_a = ppa_a.delay
        value_b = ppa_b.delay
        smaller_is_better = True
    else:
        value_a = ppa_a.worst_negative_slack
        value_b = ppa_b.worst_negative_slack
        smaller_is_better = False
    if value_a is None or value_b is None:
        mismatches.append(f"{metric} is unavailable")
    if mismatches:
        raise ComparisonError("invalid comparison: " + "; ".join(mismatches))
    assert value_a is not None and value_b is not None and ppa_a.timing_unit is not None
    if value_a == value_b:
        winner = None
        relation = "equal"
    elif (value_a < value_b) == smaller_is_better:
        winner = score_a.run_id
        relation = "run_a_better"
    else:
        winner = score_b.run_id
        relation = "run_b_better"
    return TimingComparison(
        metric=metric,
        run_a=score_a.run_id,
        run_b=score_b.run_id,
        value_a=value_a,
        value_b=value_b,
        unit=ppa_a.timing_unit,
        resolved_profile_hash=ppa_a.resolved_profile_hash,
        winner_run_id=winner,
        relation=relation,  # type: ignore[arg-type]
        value_a_over_value_b=value_a / value_b if value_b != 0 else None,
        value_a_minus_value_b=value_a - value_b,
    )


def compare_power(run_a: Path, run_b: Path) -> PowerComparison:
    """Compare total synthesis-estimated power after exact-profile safeguards."""

    compare_area(run_a, run_b)
    _manifest_a, score_a, profile_a = _load(run_a)
    _manifest_b, score_b, profile_b = _load(run_b)
    ppa_a = score_a.quality.ppa
    ppa_b = score_b.quality.ppa
    assert ppa_a is not None and ppa_b is not None
    mismatches: list[str] = []
    if ppa_a.scope != "synthesis_area_timing_power" or ppa_b.scope != "synthesis_area_timing_power":
        mismatches.append("power comparison requires area/timing/power profiles")
    if ppa_a.power_unit is None or ppa_a.power_unit != ppa_b.power_unit:
        mismatches.append("power unit differs or is unavailable")
    if profile_a.power_unit != profile_b.power_unit:
        mismatches.append("resolved power units differ")
    if ppa_a.power is None or ppa_b.power is None:
        mismatches.append("power is unavailable")
    if mismatches:
        raise ComparisonError("invalid comparison: " + "; ".join(mismatches))
    assert ppa_a.power is not None and ppa_b.power is not None and ppa_a.power_unit is not None
    if ppa_a.power < ppa_b.power:
        winner = score_a.run_id
        relation = "run_a_better"
    elif ppa_b.power < ppa_a.power:
        winner = score_b.run_id
        relation = "run_b_better"
    else:
        winner = None
        relation = "equal"
    return PowerComparison(
        run_a=score_a.run_id,
        run_b=score_b.run_id,
        power_a=ppa_a.power,
        power_b=ppa_b.power,
        power_unit=ppa_a.power_unit,
        resolved_profile_hash=ppa_a.resolved_profile_hash,
        winner_run_id=winner,
        relation=relation,  # type: ignore[arg-type]
        power_a_over_power_b=ppa_a.power / ppa_b.power,
    )


__all__ = [
    "AreaComparison",
    "PowerComparison",
    "TimingComparison",
    "compare_area",
    "compare_power",
    "compare_timing",
]
