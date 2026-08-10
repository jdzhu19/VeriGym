"""Zero-model diagnostic agent for end-to-end HWE-Bench smoke runs."""

from __future__ import annotations

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentAction,
    AgentAdapter,
    AgentContext,
    AgentDescriptor,
    EpisodeResult,
    FinalSubmissionAction,
    InteractionMode,
    Observation,
    ToolCallAction,
)


class HweBenchProbeAgent(AgentAdapter):
    """Inspect a real repository without using a model or golden repair."""

    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="hwe-bench-probe",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym-hwe-bench",
        capabilities=["zero_model", "diagnostic_only", "repository_observation"],
    )
    supported_modes = frozenset({InteractionMode.AGENT})

    def __init__(self) -> None:
        self._actions: list[AgentAction] = []
        self._index = 0

    def start(self, context: AgentContext) -> None:
        del context
        self._actions = [
            ToolCallAction(tool="file.read", arguments={"path": "TASK.md"}),
            ToolCallAction(
                tool="file.list", arguments={"path": "repository/rtl", "recursive": False}
            ),
            ToolCallAction(tool="file.read", arguments={"path": "repository/README.md"}),
            ToolCallAction(tool="file.diff", arguments={}),
            FinalSubmissionAction(message="Diagnostic no-op candidate frozen."),
        ]
        self._index = 0

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._index >= len(self._actions):
            return FinalSubmissionAction(message="Diagnostic action sequence exhausted.")
        action = self._actions[self._index]
        self._index += 1
        return action

    def finish(self, result: EpisodeResult) -> None:
        del result


__all__ = ["HweBenchProbeAgent"]
