"""Versioned public compile and candidate-only PPA feedback contracts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel

_HASH = re.compile(r"^[0-9a-f]{64}$")


class AgentFeedbackMetrics(StrictModel):
    """The complete and deliberately narrow model-visible PPA projection."""

    area: float | None = Field(default=None, gt=0)
    area_unit: str | None = None
    maximum_path_delay: float | None = Field(default=None, gt=0)
    worst_negative_slack: float | None = None
    timing_unit: str | None = None
    power: float | None = Field(default=None, gt=0)
    power_unit: str | None = None

    @model_validator(mode="after")
    def validate_units(self) -> AgentFeedbackMetrics:
        if (self.area is None) != (self.area_unit is None):
            raise ValueError("agent feedback area and unit must be supplied together")
        timing_values = (self.maximum_path_delay, self.worst_negative_slack)
        if any(value is not None for value in timing_values) != (self.timing_unit is not None):
            raise ValueError("agent feedback timing values require one timing unit")
        if (self.power is None) != (self.power_unit is None):
            raise ValueError("agent feedback power and unit must be supplied together")
        return self


class AgentFeedbackContract(StrictModel):
    """Run-time resolved feedback contract bound before a model is consulted."""

    schema_version: str = SCHEMA_VERSION
    contract_id: Literal["agent_feedback_contract.v1"] = "agent_feedback_contract.v1"
    resolver_id: Literal["agent_feedback_contract_resolver_v1"] = (
        "agent_feedback_contract_resolver_v1"
    )
    task_id: str
    benchmark_variant: str
    state_machine_id: Literal["repository_action_state_machine_v3"] = (
        "repository_action_state_machine_v3"
    )
    compile_test_id: str | None = None
    ppa_test_id: str | None = None
    public_test_ids: list[str] = Field(default_factory=list, max_length=2)
    compile_required_for_finish: bool
    ppa_requires_compile: Literal[True] = True
    patch_invalidates_compile: Literal[True] = True
    patch_invalidates_ppa: Literal[True] = True
    patch_invalidates_diff: Literal[True] = True
    ppa_supported: bool
    ppa_enabled: bool
    ppa_max_executions: int = Field(default=3, ge=1, le=8)
    resolved_profile_hash: str | None = None
    profile_backend: str | None = None
    public_test_contract_hash: str | None = None
    configuration_fingerprint: str

    @model_validator(mode="after")
    def validate_contract(self) -> AgentFeedbackContract:
        if not _HASH.fullmatch(self.configuration_fingerprint):
            raise ValueError("agent feedback contract requires a SHA-256 fingerprint")
        for value in (self.resolved_profile_hash, self.public_test_contract_hash):
            if value is not None and not _HASH.fullmatch(value):
                raise ValueError("agent feedback contract contains an invalid SHA-256")
        expected = [
            value for value in (self.compile_test_id, self.ppa_test_id) if value is not None
        ]
        if self.public_test_ids != expected:
            raise ValueError("agent feedback public-test IDs do not match the resolved interface")
        if self.compile_required_for_finish != (self.compile_test_id is not None):
            raise ValueError("compile finish gate differs from the compile interface")
        if self.ppa_enabled:
            if (
                not self.ppa_supported
                or self.ppa_test_id is None
                or self.compile_test_id is None
                or self.resolved_profile_hash is None
                or self.profile_backend is None
            ):
                raise ValueError("enabled PPA feedback lacks its compile/profile binding")
        elif self.ppa_test_id is not None or self.resolved_profile_hash is not None:
            raise ValueError("disabled PPA feedback must not expose a PPA test or profile")
        return self


AgentFeedbackCategory = Literal[
    "passed",
    "compile_failed",
    "compile_required",
    "ppa_disabled",
    "ppa_quota_exhausted",
    "synthesis_failed",
    "infrastructure_error",
]


class AgentFeedbackEvaluation(StrictModel):
    """One bounded feedback evaluation tied to an exact candidate revision."""

    schema_version: str = SCHEMA_VERSION
    sequence: int = Field(ge=0)
    test_id: str
    candidate_hash: str
    profile_hash: str | None = None
    cache_hit: bool
    synthesis_executed: bool
    duration_s: float = Field(ge=0)
    category: AgentFeedbackCategory
    passed: bool
    metrics: AgentFeedbackMetrics | None = None
    observation_hash: str

    @model_validator(mode="after")
    def validate_evaluation(self) -> AgentFeedbackEvaluation:
        for value in (self.candidate_hash, self.profile_hash, self.observation_hash):
            if value is not None and not _HASH.fullmatch(value):
                raise ValueError("agent feedback evaluation contains an invalid SHA-256")
        if self.cache_hit and self.synthesis_executed:
            raise ValueError("a cached feedback result cannot execute synthesis")
        if self.metrics is not None and self.profile_hash is None:
            raise ValueError("PPA metrics require a resolved profile hash")
        if self.passed != (self.category == "passed"):
            raise ValueError("agent feedback pass flag differs from its category")
        return self


__all__ = [
    "AgentFeedbackCategory",
    "AgentFeedbackContract",
    "AgentFeedbackEvaluation",
    "AgentFeedbackMetrics",
]
