"""The only tools exposed to Claude by the strict MCP server."""

from __future__ import annotations

from typing import Any

TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "list_files",
        "description": "List visible task-workspace files using relative paths.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "recursive": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read one visible UTF-8 workspace file by relative path.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_files",
        "description": "Search visible UTF-8 files for text or a regular expression.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "glob": {"type": "string", "default": "**/*"},
                "regex": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_patch",
        "description": "Apply a unified diff to paths permitted by the workspace policy.",
        "inputSchema": {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Write one UTF-8 file at an editable relative workspace path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run one argument-array command in the official task Docker runtime with network off. "
            "All executable, cwd, and file-path arguments must be workspace-relative; use '.' "
            "instead of '/workspace' and never send a leading slash."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "One shell-free relative command argument.",
                    },
                    "minItems": 1,
                    "maxItems": 128,
                },
                "cwd": {
                    "type": "string",
                    "default": ".",
                    "description": "Relative workspace directory without a leading slash.",
                },
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 1800},
                "stdin": {"type": ["string", "null"]},
            },
            "required": ["argv"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_public_test",
        "description": "Run one declared repository public test by its exact ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"test_id": {"type": "string"}},
            "required": ["test_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_diff",
        "description": "Inspect the current unified candidate diff.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
)

TOOL_NAMES = tuple(item["name"] for item in TOOL_DEFINITIONS)
CLAUDE_TOOL_NAMES = tuple(f"mcp__verigym__{name}" for name in TOOL_NAMES)

__all__ = ["CLAUDE_TOOL_NAMES", "TOOL_DEFINITIONS", "TOOL_NAMES"]
