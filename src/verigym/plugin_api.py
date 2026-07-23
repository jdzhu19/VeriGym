"""Stable MVP plugin-author imports."""

from verigym.agents.base import AgentAdapter, AgentContext
from verigym.schemas.agent import AgentAction, EpisodeResult, FinalSubmissionAction, Observation
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
from verigym.schemas.common import (
    AgentDescriptor,
    ErrorCategory,
    SuiteDescriptor,
    ToolDescriptor,
    ToolVisibility,
)
from verigym.schemas.task import (
    ResolvedTaskAssets,
    TaskRef,
    ValidationReport,
    VeriTask,
)
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult, ToolResult
from verigym.suites.base import SuiteAdapter
from verigym.tools.base import ToolContext, ToolPlugin

__all__ = [
    "AgentAction",
    "AgentAdapter",
    "AgentContext",
    "AgentDescriptor",
    "CommandSpec",
    "CompletedCommand",
    "EpisodeResult",
    "ErrorCategory",
    "FinalSubmissionAction",
    "HealthCheckResult",
    "Observation",
    "PLUGIN_API_VERSION",
    "ResolvedTaskAssets",
    "SCHEMA_VERSION",
    "StrictModel",
    "SuiteAdapter",
    "SuiteDescriptor",
    "TaskRef",
    "ToolContext",
    "ToolDescriptor",
    "ToolPlugin",
    "ToolResult",
    "ToolVisibility",
    "ValidationReport",
    "VeriTask",
]
