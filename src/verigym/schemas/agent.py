"""Agent actions, observations, and episode-facing descriptors."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import AgentDescriptor
from verigym.schemas.tool import ToolResult


class BudgetRemaining(StrictModel):
    turns: int
    tool_calls: int
    wall_time_s: float
    model_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class Observation(StrictModel):
    schema_version: str = SCHEMA_VERSION
    task_id: str
    task_description: str | None = None
    visible_files: list[str] = Field(default_factory=list)
    selected_files: dict[str, str] = Field(default_factory=dict)
    previous_tool_result: ToolResult | None = None
    remaining_budget: BudgetRemaining
    diff_summary: dict[str, Any] = Field(default_factory=dict)
    policy_reminders: list[str] = Field(default_factory=list)
    episode_status: str
    message: str | None = None


class MessageAction(StrictModel):
    schema_version: str = SCHEMA_VERSION
    type: Literal["message"] = "message"
    message: str


class ToolCallAction(StrictModel):
    schema_version: str = SCHEMA_VERSION
    type: Literal["tool_call"] = "tool_call"
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ApplyPatchAction(StrictModel):
    schema_version: str = SCHEMA_VERSION
    type: Literal["apply_patch"] = "apply_patch"
    patch: str


class FinalSubmissionAction(StrictModel):
    schema_version: str = SCHEMA_VERSION
    type: Literal["final"] = "final"
    message: str = "Implementation complete."
    files: dict[str, str] | None = None


class AbortAction(StrictModel):
    schema_version: str = SCHEMA_VERSION
    type: Literal["abort"] = "abort"
    reason: str


AgentAction: TypeAlias = Annotated[
    MessageAction | ToolCallAction | ApplyPatchAction | FinalSubmissionAction | AbortAction,
    Field(discriminator="type"),
]


class EpisodeResult(StrictModel):
    run_id: str
    resolved: bool
    termination_reason: str


__all__ = [
    "AbortAction",
    "AgentAction",
    "AgentDescriptor",
    "ApplyPatchAction",
    "EpisodeResult",
    "FinalSubmissionAction",
    "MessageAction",
    "Observation",
    "ToolCallAction",
]
