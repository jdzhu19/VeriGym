"""Codex exec invocation for scoring-only AgentEval with one required MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from verigym.protocols.repository_action import repository_tool_definitions

from .agenteval_config import CodexAgentEvalSettings
from .capabilities import CapabilityReport


def build_agenteval_arguments(
    capabilities: CapabilityReport,
    settings: CodexAgentEvalSettings,
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
        "features.apps=false",
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
        'mcp_servers.verigym.omit_tools_from=["deferred"]',
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
    _validate_arguments(arguments, capabilities, tool_names)
    return arguments


def sanitized_agenteval_invocation(
    arguments: list[str],
    settings: CodexAgentEvalSettings,
    capabilities: CapabilityReport,
) -> dict[str, object]:
    sanitized = [
        "mcp_servers.verigym.args=<private-broker-launch>"
        if value.startswith("mcp_servers.verigym.args=")
        else value
        for value in arguments
    ]
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
        "apps_enabled": False,
        "mcp_servers_enabled": True,
        "required_mcp_servers": ["verigym"],
        "mcp_tool_names": tool_names(),
        "mcp_tool_exposure": "direct_only_deferred_omitted",
        "broker_max_tool_calls": settings.max_tool_calls,
        "broker_max_patch_calls": settings.max_patch_calls,
        "broker_max_consecutive_rejected_calls": settings.max_consecutive_rejected_calls,
        "broker_max_exploratory_calls": settings.max_exploratory_calls,
        "broker_finalization_reserve_s": settings.finalization_reserve_s,
        "agent_version_id": settings.agent_version_id,
        "agent_version_hash": settings.agent_version_hash,
        "prompt_hash": settings.prompt_hash,
        "tool_policy_fingerprint": settings.tool_policy_fingerprint,
        "capability_fingerprint": settings.capability_fingerprint,
        "training_mode": False,
    }


def tool_names() -> list[str]:
    return [definition["name"] for definition in repository_tool_definitions(dialect="mcp")]


def _validate_arguments(
    arguments: list[str], capabilities: CapabilityReport, expected_tools: list[str]
) -> None:
    required = {
        "features.shell_tool=false",
        "features.apps=false",
        'web_search="disabled"',
        "mcp_servers.verigym.required=true",
        "mcp_servers.verigym.enabled=true",
        'mcp_servers.verigym.omit_tools_from=["deferred"]',
    }
    if not required.issubset(arguments):
        raise ValueError("Codex AgentEval invocation omits a required isolation override")
    enabled = "mcp_servers.verigym.enabled_tools=" + json.dumps(
        expected_tools, separators=(",", ":")
    )
    joined = "\n".join(arguments)
    if (
        "mcp_servers={}" in arguments
        or "orchestrator.mcp.enabled=false" in arguments
        or enabled not in arguments
        or arguments.count(capabilities.model_flag) != 1
        or "repository_mcp_stdio" not in joined
        or "-i" not in joined
    ):
        raise ValueError("Codex AgentEval model or MCP allowlist is not exact")


__all__ = ["build_agenteval_arguments", "sanitized_agenteval_invocation"]
