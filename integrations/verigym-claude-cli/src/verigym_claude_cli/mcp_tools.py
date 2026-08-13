"""Canonical MCP tools exposed to Claude."""

from verigym.protocols.repository_action import repository_tool_definitions

TOOL_DEFINITIONS = tuple(repository_tool_definitions(dialect="mcp"))
TOOL_NAMES = tuple(item["name"] for item in TOOL_DEFINITIONS)
CLAUDE_TOOL_NAMES = tuple(f"mcp__verigym__{name}" for name in TOOL_NAMES)

__all__ = ["CLAUDE_TOOL_NAMES", "TOOL_DEFINITIONS", "TOOL_NAMES"]
