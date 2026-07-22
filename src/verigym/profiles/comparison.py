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


__all__ = ["AreaComparison", "compare_area"]
