"""Episode states, termination reasons, and deterministic budget accounting."""

from __future__ import annotations

import time
from enum import StrEnum

from verigym.schemas.agent import BudgetRemaining
from verigym.schemas.model import NormalizedModelUsage
from verigym.schemas.task import BudgetSpec


class EpisodeState(StrEnum):
    CREATED = "created"
    MATERIALIZING = "materializing"
    READY = "ready"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TerminationReason(StrEnum):
    FINAL_SUBMISSION = "final_submission"
    SUCCESS_EARLY_STOP = "success_early_stop"
    TURN_BUDGET_EXHAUSTED = "turn_budget_exhausted"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    MODEL_BUDGET_EXHAUSTED = "model_budget_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    WALL_TIME_EXHAUSTED = "wall_time_exhausted"
    INVALID_ACTION_LIMIT = "invalid_action_limit"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    MODEL_ERROR = "model_error"
    AGENT_ABORT = "agent_abort"
    RUNTIME_ERROR = "runtime_error"
    POLICY_VIOLATION = "policy_violation"
    CANCELLED = "cancelled"


class BudgetTracker:
    """Track episode consumption without conflating budgets with verifier results."""

    def __init__(self, spec: BudgetSpec) -> None:
        self.spec = spec
        self.started = time.monotonic()
        self.turns = 0
        self.tool_calls = 0
        self.failed_tool_calls = 0
        self.model_calls = 0
        self.model_input_tokens: int | None = 0
        self.model_output_tokens: int | None = 0
        self.total_tokens: int | None = 0
        self.agent_time_s = 0.0
        self.tool_time_s = 0.0
        self.verifier_time_s = 0.0

    @property
    def wall_time_s(self) -> float:
        return time.monotonic() - self.started

    def exhausted_before_turn(self) -> TerminationReason | None:
        if self.wall_time_s >= self.spec.max_wall_time_s:
            return TerminationReason.WALL_TIME_EXHAUSTED
        if self.turns >= self.spec.max_turns:
            return TerminationReason.TURN_BUDGET_EXHAUSTED
        return None

    def exhausted_before_tool(self) -> TerminationReason | None:
        if self.wall_time_s >= self.spec.max_wall_time_s:
            return TerminationReason.WALL_TIME_EXHAUSTED
        if self.tool_calls >= self.spec.max_tool_calls:
            return TerminationReason.TOOL_BUDGET_EXHAUSTED
        return None

    def exhausted_before_model(self) -> TerminationReason | None:
        if self.wall_time_s >= self.spec.max_wall_time_s:
            return TerminationReason.WALL_TIME_EXHAUSTED
        if self.spec.max_model_calls is not None and self.model_calls >= self.spec.max_model_calls:
            return TerminationReason.MODEL_BUDGET_EXHAUSTED
        if self._token_limit_reached():
            return TerminationReason.TOKEN_BUDGET_EXHAUSTED
        return None

    def consume_turn(self) -> None:
        self.turns += 1

    def consume_tool(self) -> None:
        self.tool_calls += 1

    def consume_model_call(self) -> None:
        self.model_calls += 1

    def record_model_usage(self, usage: NormalizedModelUsage | None) -> None:
        self.model_input_tokens = self._accumulate(
            self.model_input_tokens, usage.input_tokens if usage else None
        )
        self.model_output_tokens = self._accumulate(
            self.model_output_tokens, usage.output_tokens if usage else None
        )
        self.total_tokens = self._accumulate(
            self.total_tokens, usage.total_tokens if usage else None
        )

    def exhausted_after_model(self) -> TerminationReason | None:
        if self.wall_time_s >= self.spec.max_wall_time_s:
            return TerminationReason.WALL_TIME_EXHAUSTED
        if self._token_limit_exceeded():
            return TerminationReason.TOKEN_BUDGET_EXHAUSTED
        return None

    def remaining(self) -> BudgetRemaining:
        return BudgetRemaining(
            turns=max(0, self.spec.max_turns - self.turns),
            tool_calls=max(0, self.spec.max_tool_calls - self.tool_calls),
            wall_time_s=max(0.0, self.spec.max_wall_time_s - self.wall_time_s),
            model_calls=(
                None
                if self.spec.max_model_calls is None
                else max(0, self.spec.max_model_calls - self.model_calls)
            ),
            input_tokens=self._remaining(self.spec.max_input_tokens, self.model_input_tokens),
            output_tokens=self._remaining(self.spec.max_output_tokens, self.model_output_tokens),
            total_tokens=self._remaining(self.spec.max_total_tokens, self.total_tokens),
        )

    @staticmethod
    def _accumulate(current: int | None, value: int | None) -> int | None:
        if current is None or value is None:
            return None
        return current + value

    @staticmethod
    def _remaining(limit: int | None, consumed: int | None) -> int | None:
        if limit is None or consumed is None:
            return None
        return max(0, limit - consumed)

    def _token_limit_reached(self) -> bool:
        pairs = (
            (self.spec.max_input_tokens, self.model_input_tokens),
            (self.spec.max_output_tokens, self.model_output_tokens),
            (self.spec.max_total_tokens, self.total_tokens),
        )
        return any(
            limit is not None and used is not None and used >= limit for limit, used in pairs
        )

    def _token_limit_exceeded(self) -> bool:
        pairs = (
            (self.spec.max_input_tokens, self.model_input_tokens),
            (self.spec.max_output_tokens, self.model_output_tokens),
            (self.spec.max_total_tokens, self.total_tokens),
        )
        return any(limit is not None and used is not None and used > limit for limit, used in pairs)
