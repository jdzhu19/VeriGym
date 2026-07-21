"""Built-in agent adapters."""

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.agents.react import ReferenceReActAgent
from verigym.agents.scripted import ScriptedAgent, ScriptedBadAgent
from verigym.agents.single_turn import SingleTurnAgent

__all__ = [
    "AgentAdapter",
    "AgentContext",
    "AgentTerminationError",
    "ReferenceReActAgent",
    "ScriptedAgent",
    "ScriptedBadAgent",
    "SingleTurnAgent",
]
