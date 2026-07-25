"""Model-independent agent adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from verigym.agents.external import ExternalAgentBridge
from verigym.core.episode import TerminationReason
from verigym.schemas.agent import AgentAction, EpisodeResult, Observation
from verigym.schemas.common import AgentDescriptor, InteractionMode
from verigym.schemas.options import JsonValue
from verigym.schemas.score import EpisodeFailure
from verigym.schemas.task import VeriTask

if TYPE_CHECKING:
    from verigym.core.model_gateway import ModelGateway
    from verigym.prompts.builder import PromptBuilder


@dataclass(frozen=True)
class AgentContext:
    run_id: str
    task: VeriTask
    seed: int
    model_gateway: ModelGateway | None = None
    prompt_builder: PromptBuilder | None = None
    max_invalid_actions: int = 3
    agent_options: Mapping[str, JsonValue] = field(default_factory=dict)
    external_bridge: ExternalAgentBridge | None = None


class AgentTerminationError(Exception):
    """A harness-requested structured episode termination."""

    def __init__(
        self,
        reason: TerminationReason,
        failure: EpisodeFailure,
    ) -> None:
        super().__init__(failure.message)
        self.reason = reason
        self.failure = failure


class AgentAdapter(ABC):
    descriptor: AgentDescriptor
    requires_model: ClassVar[bool] = False
    supported_modes: ClassVar[frozenset[InteractionMode]] = frozenset({InteractionMode.AGENT})

    @abstractmethod
    def start(self, context: AgentContext) -> None:
        """Reset all per-episode policy state."""

    @abstractmethod
    def act(self, observation: Observation) -> AgentAction:
        """Choose one visible structured action."""

    @abstractmethod
    def finish(self, result: EpisodeResult) -> None:
        """Receive the final public episode result."""
