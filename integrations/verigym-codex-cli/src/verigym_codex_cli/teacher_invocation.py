"""Codex exec invocation for the single required VeriGym MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from verigym.protocols.repository_action import repository_tool_definitions

from .capabilities import CapabilityReport
from .teacher_config import CodexTeacherSettings


def build_teacher_arguments(
    capabilities: CapabilityReport,
    settings: CodexTeacherSettings,
    *,
    socket_path: Path,
) -> list[str]:
    execution = settings.execution
    tool_names = [definition["name"] for definition in repository_tool_definitions(dialect="mcp")]
    child_args = [
        "-i",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "LANG=C.UTF-8",
        sys.executable,
        "-m",
        "verigym.protocols.repository_mcp_stdio",
        "--socket",
        str(socket_path),
    ]
    arguments = [
        capabilities.non_interactive_command,
        capabilities.machine_output_flag,
        capabilities.ephemeral_flag,
        capabilities.strict_config_flag,
        capabilities.ignore_user_config_flag,
        capabilities.ignore_rules_flag,
        capabilities.skip_git_flag,
        capabilities.sandbox_flag,
        "read-only",
        capabilities.model_flag,
        execution.model_id,
    ]
    if capabilities.approval_flag is not None and "never" in capabilities.supported_approval_modes:
        arguments.extend([capabilities.approval_flag, "never"])
    overrides = [
        "project_doc_max_bytes=0",
        'web_search="disabled"',
        "features.shell_tool=false",
        "features.plugins=false",
        "features.multi_agent=false",
        "features.hooks=false",
        "skills.include_instructions=false",
        "skills.bundled.enabled=false",
        "orchestrator.skills.enabled=false",
        "include_apps_instructions=false",
        "include_environment_context=false",
        'mcp_servers.verigym.command="/usr/bin/env"',
        f"mcp_servers.verigym.args={json.dumps(child_args, separators=(',', ':'))}",
        f"mcp_servers.verigym.enabled_tools={json.dumps(tool_names, separators=(',', ':'))}",
        "mcp_servers.verigym.enabled=true",
        "mcp_servers.verigym.required=true",
        'mcp_servers.verigym.default_tools_approval_mode="approve"',
        "mcp_servers.verigym.startup_timeout_sec=30",
        f"mcp_servers.verigym.tool_timeout_sec={int(execution.effective_process_timeout_s) + 10}",
        f'model_reasoning_effort="{execution.effective_reasoning_effort}"',
    ]
    for override in overrides:
        arguments.extend([capabilities.config_flag, override])
    arguments.append("-")
    _validate_teacher_arguments(arguments, capabilities, tool_names)
    return arguments


def sanitized_teacher_invocation(
    arguments: list[str],
    settings: CodexTeacherSettings,
    capabilities: CapabilityReport,
) -> dict[str, object]:
    sanitized: list[str] = []
    for value in arguments:
        if value.startswith("mcp_servers.verigym.args="):
            sanitized.append("mcp_servers.verigym.args=<private-broker-launch>")
        else:
            sanitized.append(value)
    return {
        "schema_version": "1.0",
        "argv": ["<codex>", *sanitized],
        "stdin_protocol": capabilities.selected_invocation_protocol,
        "machine_event_protocol": capabilities.selected_event_protocol,
        "working_directory_policy": "private_empty_non_repository",
        "requested_model_id": settings.execution.model_id,
        "reasoning_effort": settings.execution.effective_reasoning_effort,
        "sandbox_policy": "read-only",
        "approval_policy": "never",
        "features_shell_tool": False,
        "web_search_enabled": False,
        "user_config_loaded": False,
        "project_instructions_enabled": False,
        "skills_instructions_enabled": False,
        "plugins_enabled": False,
        "mcp_servers_enabled": True,
        "required_mcp_servers": ["verigym"],
        "mcp_tool_names": [
            definition["name"] for definition in repository_tool_definitions(dialect="mcp")
        ],
        "broker_max_tool_calls": settings.max_tool_calls,
        "broker_max_patch_calls": settings.max_patch_calls,
        "broker_max_consecutive_rejected_calls": (settings.max_consecutive_rejected_calls),
    }


def _validate_teacher_arguments(
    arguments: list[str],
    capabilities: CapabilityReport,
    tool_names: list[str],
) -> None:
    joined = "\n".join(arguments)
    required = {
        "features.shell_tool=false",
        'web_search="disabled"',
        "mcp_servers.verigym.required=true",
        "mcp_servers.verigym.enabled=true",
    }
    if not required.issubset(arguments):
        raise ValueError("Codex teacher invocation omits a required isolation override")
    if "mcp_servers={}" in arguments or "orchestrator.mcp.enabled=false" in arguments:
        raise ValueError("Codex teacher invocation disables its required MCP server")
    enabled = f"mcp_servers.verigym.enabled_tools={json.dumps(tool_names, separators=(',', ':'))}"
    if enabled not in arguments or arguments.count(capabilities.model_flag) != 1:
        raise ValueError("Codex teacher model or MCP allowlist is not exact")
    if "repository_mcp_stdio" not in joined or "-i" not in joined:
        raise ValueError("Codex MCP child is not launched through a scrubbed environment")


__all__ = ["build_teacher_arguments", "sanitized_teacher_invocation"]
