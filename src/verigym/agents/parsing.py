"""Strict model-output parsing without repair heuristics."""

from __future__ import annotations

import json
import re

from pydantic import TypeAdapter, ValidationError

from verigym.schemas.agent import (
    AbortAction,
    AgentAction,
    ApplyPatchAction,
    FinalSubmissionAction,
    MessageAction,
    ToolCallAction,
)


class ModelOutputParseError(ValueError):
    pass


_ACTION_ADAPTER: TypeAdapter[AgentAction] = TypeAdapter(AgentAction)
_FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", flags=re.DOTALL)
_RTL_LANGUAGES = {"verilog", "systemverilog", "sv"}


def parse_single_turn_rtl(text: str) -> str:
    """Accept raw RTL or exactly one explicitly tagged RTL fence."""

    candidate = text.strip()
    if not candidate:
        raise ModelOutputParseError("model output is empty")
    if "```" in candidate:
        matches = list(_FENCE_RE.finditer(candidate))
        if len(matches) != 1:
            raise ModelOutputParseError("model output must contain exactly one RTL code block")
        match = matches[0]
        language = match.group(1).strip().lower()
        if language not in _RTL_LANGUAGES:
            raise ModelOutputParseError("fenced candidate must be tagged verilog or systemverilog")
        outside = candidate[: match.start()] + candidate[match.end() :]
        if outside.strip():
            raise ModelOutputParseError("text outside the candidate RTL block is not allowed")
        candidate = match.group(2).strip()
    if not candidate:
        raise ModelOutputParseError("candidate RTL source is empty")
    if not re.search(r"\bmodule\s+[A-Za-z_][A-Za-z0-9_$]*", candidate):
        raise ModelOutputParseError("candidate does not declare a Verilog module")
    if not re.search(r"\bendmodule\b", candidate):
        raise ModelOutputParseError("candidate has no endmodule")
    return candidate + "\n"


def parse_react_action(text: str) -> AgentAction:
    """Parse one exact JSON action; never recover or rewrite malformed input."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelOutputParseError("response is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ModelOutputParseError("response JSON must be one object")
    try:
        action = _ACTION_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        raise ModelOutputParseError("response does not match the strict action schema") from exc
    if isinstance(action, MessageAction):
        raise ModelOutputParseError("message is not a model-executable ReAct action")
    if isinstance(action, FinalSubmissionAction) and action.files is not None:
        raise ModelOutputParseError("ReAct final actions cannot directly submit files")
    if not isinstance(
        action,
        (ToolCallAction, ApplyPatchAction, FinalSubmissionAction, AbortAction),
    ):
        raise ModelOutputParseError("unsupported ReAct action")
    return action


__all__ = ["ModelOutputParseError", "parse_react_action", "parse_single_turn_rtl"]
