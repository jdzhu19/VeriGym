"""In-process verifier for RTL-Repo's official native metrics."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    CommandSpec,
    CompletedCommand,
    ErrorCategory,
    HealthCheckResult,
    StrictModel,
    ToolContext,
    ToolDescriptor,
    ToolPlugin,
    ToolResult,
    ToolVisibility,
)

METRIC_PROFILE = "rtl_repo_official_v1"
POSTPROCESS_PROFILE = "first_nonempty_noncomment_line_v1"
MAX_CANDIDATE_BYTES = 256 * 1024
MAX_TARGET_BYTES = 64 * 1024


class RtlRepoScoreRequest(StrictModel):
    candidate: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
    target: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
    metric_profile: Literal["rtl_repo_official_v1"]
    split: Literal["train", "test"]
    timeout_s: int | None = Field(default=None, ge=1, le=300)


class RtlRepoScoreTool(ToolPlugin):
    """Score one hidden next-line target without exposing either text in artifacts."""

    descriptor = ToolDescriptor(
        schema_version=SCHEMA_VERSION,
        name="rtl_repo.score",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-rtl-repo",
        capabilities=[
            "in_process",
            "exact_match",
            "edit_similarity",
            "hidden_target",
            POSTPROCESS_PROFILE,
        ],
        visibility=ToolVisibility.VERIFIER_ONLY,
    )

    def health_check(self, context: ToolContext | None = None) -> HealthCheckResult:
        del context
        return HealthCheckResult(
            healthy=True,
            message="built-in official RTL-Repo indel-ratio metric is available",
            version="indel-ratio-v1",
        )

    def validate_request(self, request: dict[str, Any]) -> RtlRepoScoreRequest:
        return RtlRepoScoreRequest.model_validate(request)

    def build_command(self, request: BaseModel, context: ToolContext) -> CommandSpec:
        del request, context
        raise RuntimeError("RTL-Repo scoring is in-process and has no external command")

    def parse_result(
        self,
        request: BaseModel,
        completed: CompletedCommand,
        context: ToolContext,
    ) -> ToolResult:
        del request, completed, context
        raise RuntimeError("RTL-Repo scoring is in-process and has no command result")

    def execute(self, raw_request: dict[str, Any], context: ToolContext) -> ToolResult:
        request = self.validate_request(raw_request)
        if context.session is None:
            return _infrastructure_failure("RTL-Repo scoring requires a runtime session")
        try:
            candidate_data = context.session.read_file(request.candidate)
            target_data = context.session.read_file(request.target)
            if len(candidate_data) > MAX_CANDIDATE_BYTES:
                raise ValueError("candidate completion exceeds the verifier byte bound")
            if len(target_data) > MAX_TARGET_BYTES:
                raise ValueError("hidden target exceeds the verifier byte bound")
            candidate = candidate_data.decode("utf-8")
            target = target_data.decode("utf-8")
            prediction = official_postprocess(candidate)
            exact_match = prediction.split() == target.split()
            similarity = official_edit_similarity(prediction, target)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return _infrastructure_failure(str(exc))
        metrics = {
            "exact_match": 100.0 if exact_match else 0.0,
            "edit_similarity": float(similarity),
        }
        return ToolResult(
            tool=self.descriptor.name,
            success=exact_match,
            category=ErrorCategory.SUCCESS if exact_match else ErrorCategory.TEST_FAILED,
            message=(
                "RTL-Repo completion exactly matched the hidden target"
                if exact_match
                else "RTL-Repo completion did not exactly match the hidden target"
            ),
            metadata={
                "candidate_failure": not exact_match,
                "tests_passed": int(exact_match),
                "tests_total": 1,
                "exact_match": exact_match,
                "edit_similarity": float(similarity),
                "benchmark_metric_profile": METRIC_PROFILE,
                "benchmark_split": request.split,
                "benchmark_metrics": metrics,
                "benchmark_metric_units": {
                    "exact_match": "percent",
                    "edit_similarity": "percent",
                },
                "postprocess_profile": POSTPROCESS_PROFILE,
            },
        )


def official_postprocess(text: str) -> str:
    """Match RTL-Repo's `post_process` selection exactly."""

    prediction = ""
    for line in text.split("\n"):
        if not line.strip():
            continue
        prediction = line
        if not line.strip().startswith("//"):
            break
    return prediction


def official_edit_similarity(prediction: str, target: str) -> int:
    """Match `fuzzywuzzy.fuzz.ratio` with the official Levenshtein backend."""

    total_length = len(prediction) + len(target)
    if total_length == 0:
        return 100
    common = _lcs_length(prediction, target)
    return int(round(200 * common / total_length))


def _lcs_length(left: str, right: str) -> int:
    """Compute LCS length with bit vectors for the normalized indel ratio."""

    if len(left) < len(right):
        left, right = right, left
    masks: dict[str, int] = {}
    for index, character in enumerate(right):
        masks[character] = masks.get(character, 0) | (1 << index)
    state = 0
    for character in left:
        matches = masks.get(character, 0)
        combined = state | matches
        state = combined & ~(combined - ((state << 1) | 1))
    return state.bit_count()


def _infrastructure_failure(message: str) -> ToolResult:
    return ToolResult(
        tool=RtlRepoScoreTool.descriptor.name,
        success=False,
        category=ErrorCategory.PARSER_ERROR,
        message=message,
        metadata={"candidate_failure": False},
    )


__all__ = [
    "METRIC_PROFILE",
    "POSTPROCESS_PROFILE",
    "RtlRepoScoreRequest",
    "RtlRepoScoreTool",
    "official_edit_similarity",
    "official_postprocess",
]
