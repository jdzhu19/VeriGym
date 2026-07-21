"""Correctness-first scorecard and raw metric dimensions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.verifier import VerifierResult


class CorrectnessMetrics(StrictModel):
    compile_status: str | None = None
    visible_regression_status: str | None = None
    hidden_regression_status: str | None = None
    formal_status: str | None = None
    equivalence_status: str | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    resolved: bool
    infrastructure_error: bool = False


class PPAMetrics(StrictModel):
    profile_id: str
    eligible: bool
    area: float | None = None
    delay: float | None = None
    frequency: float | None = None
    power: float | None = None
    worst_negative_slack: float | None = None
    total_negative_slack: float | None = None
    violations: dict[str, int] = Field(default_factory=dict)
    reference_area: float | None = None
    reference_delay: float | None = None
    reference_power: float | None = None
    area_ratio: float | None = None
    delay_ratio: float | None = None
    power_ratio: float | None = None


class QualityMetrics(StrictModel):
    ppa: PPAMetrics | None = None
    synthesis: dict[str, float | int | str] | None = None


class EfficiencyMetrics(StrictModel):
    wall_time_s: float = 0.0
    agent_time_s: float = 0.0
    tool_time_s: float = 0.0
    verifier_time_s: float = 0.0
    model_input_tokens: int | None = 0
    model_output_tokens: int | None = 0
    total_tokens: int | None = 0
    model_calls: int = 0
    model_api_cost: float | None = None
    turns: int = 0
    tool_calls: int = 0
    failed_tool_calls: int = 0
    peak_memory_bytes: int | None = None


class PatchMetrics(StrictModel):
    changed_files: list[str] = Field(default_factory=list)
    added_lines: int = 0
    deleted_lines: int = 0
    total_diff_lines: int = 0
    changes_outside_expected_files: list[str] = Field(default_factory=list)
    changed_file_precision: float | None = None
    edit_similarity: float | None = None


class ReproducibilityMetrics(StrictModel):
    task_hash: str
    candidate_hash: str
    verifier_hash: str
    run_config_hash: str
    toolchain_profile_ids: list[str] = Field(default_factory=list)
    deterministic: bool
    isolation_level: str


class EpisodeFailure(StrictModel):
    kind: Literal["agent", "model", "policy", "runtime"]
    category: str
    message: str
    infrastructure: bool = False


class ScoreCard(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    task_id: str
    status: Literal["completed", "failed", "error", "cancelled"]
    resolved: bool
    correctness: CorrectnessMetrics
    quality: QualityMetrics
    efficiency: EfficiencyMetrics
    patch: PatchMetrics
    reproducibility: ReproducibilityMetrics
    verifier_results: list[VerifierResult]
    termination_reason: str
    failure: EpisodeFailure | None = None
    warnings: list[str] = Field(default_factory=list)
