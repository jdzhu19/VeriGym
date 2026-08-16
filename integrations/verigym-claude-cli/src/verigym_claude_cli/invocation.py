"""Exact Claude CLI invocation with built-ins disabled and MCP allowlisted."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .config import ClaudeSettings
from .mcp_tools import CLAUDE_TOOL_NAMES

CLAUDE_BUILTIN_TOOL_NAMES = (
    "Agent",
    "AskUserQuestion",
    "Bash",
    "Edit",
    "EnterPlanMode",
    "ExitPlanMode",
    "Glob",
    "Grep",
    "KillShell",
    "ListMcpResourcesTool",
    "NotebookEdit",
    "NotebookRead",
    "Read",
    "ReadMcpResourceTool",
    "SendUserMessage",
    "Skill",
    "Task",
    "TaskOutput",
    "TodoRead",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
)


def build_arguments(
    settings: ClaudeSettings,
    *,
    socket_path: Path,
    run_id: str,
    provider_system_prompt: str,
    mcp_pythonpath: str | None = None,
) -> list[str]:
    session_name = "verigym-" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    mcp_arguments = [
        "-u",
        "ANTHROPIC_API_KEY",
        "-u",
        "ANTHROPIC_AUTH_TOKEN",
        "-u",
        "ANTHROPIC_BASE_URL",
        "-u",
        "HTTP_PROXY",
        "-u",
        "HTTPS_PROXY",
        "-u",
        "NO_PROXY",
        "-u",
        "CLAUDE_CODE_EFFORT_LEVEL",
    ]
    if mcp_pythonpath is not None:
        if (
            not mcp_pythonpath
            or "\x00" in mcp_pythonpath
            or any(ord(character) < 32 or ord(character) == 127 for character in mcp_pythonpath)
            or len(mcp_pythonpath.encode("utf-8")) > 16 * 1024
            or any(
                not value or not value.startswith("/") for value in mcp_pythonpath.split(os.pathsep)
            )
        ):
            raise ValueError("Claude MCP PYTHONPATH is malformed")
        mcp_arguments.append("PYTHONPATH=" + mcp_pythonpath)
    mcp_arguments.extend(
        [
            sys.executable,
            "-m",
            "verigym_claude_cli.mcp_stdio",
            "--socket",
            str(socket_path),
        ]
    )
    mcp_config = {
        "mcpServers": {
            "verigym": {
                "type": "stdio",
                "command": "/usr/bin/env",
                "args": mcp_arguments,
            }
        }
    }
    arguments = [
        "--bare",
        "--print",
        "--no-session-persistence",
        "--name",
        session_name,
        "--model",
        settings.model_id,
        "--effort",
        settings.effective_reasoning_effort,
        "--max-budget-usd",
        format(settings.max_budget_usd, ".12g"),
        "--disable-slash-commands",
        "--no-chrome",
        "--prompt-suggestions",
        "false",
        "--append-system-prompt",
        provider_system_prompt,
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps(mcp_config, separators=(",", ":"), ensure_ascii=False),
        "--tools",
        "",
        "--disallowedTools",
        ",".join(CLAUDE_BUILTIN_TOOL_NAMES),
        "--allowedTools",
        ",".join(CLAUDE_TOOL_NAMES),
        "--permission-mode",
        "dontAsk",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    _validate_invocation(
        arguments,
        settings,
        provider_system_prompt=provider_system_prompt,
        mcp_pythonpath=mcp_pythonpath,
    )
    return arguments


def sanitized_invocation(arguments: list[str], settings: ClaudeSettings) -> dict[str, Any]:
    sanitized = list(arguments)
    config_index = sanitized.index("--mcp-config") + 1
    sanitized[config_index] = "<private-verigym-mcp-config>"
    system_prompt_index = sanitized.index("--append-system-prompt") + 1
    provider_system_prompt = sanitized[system_prompt_index]
    system_prompt_sha256 = hashlib.sha256(provider_system_prompt.encode("utf-8")).hexdigest()
    sanitized[system_prompt_index] = "<frozen-provider-system-prompt>"
    return {
        "schema_version": "1.0",
        "argv": sanitized,
        "stdin_transport": "pipe",
        "prompt_persisted_in_argv": False,
        "provider_system_prompt_transport": "sanitized_cli_argument",
        "provider_system_prompt_persisted_in_argv": True,
        "provider_system_prompt_contains_task_context": False,
        "provider_system_prompt_sha256": system_prompt_sha256,
        "control_working_directory": "private_ephemeral_non_workspace",
        "model_provider_transport_location": "trusted_host_claude_cli",
        "workspace_tool_transport": "strict_private_mcp",
        "builtin_tools_available": False,
        "slash_commands_available": False,
        "session_persistence": False,
        "permission_mode": "dontAsk",
        "requested_model_id": settings.model_id,
        "requested_reasoning_effort": settings.effective_reasoning_effort,
        "process_wall_timeout_s": settings.effective_process_timeout_s,
        "process_evidence_byte_bound": settings.max_output_bytes,
        "internal_turn_limit": None,
        "model_call_limit": None,
        "model_token_limit": settings.max_provider_tokens,
        "model_token_limit_scope": "cache_inclusive_stream_observed",
        "budget_limit": settings.max_budget_usd,
        "budget_limit_currency": "USD",
        "broker_max_tool_calls": settings.max_tool_calls,
        "broker_max_patch_calls": settings.max_patch_calls,
        "broker_max_consecutive_rejected_calls": (settings.max_consecutive_rejected_calls),
        "retry_count": 0,
        "best_of_k": 1,
    }


def _validate_invocation(
    arguments: list[str],
    settings: ClaudeSettings,
    *,
    provider_system_prompt: str,
    mcp_pythonpath: str | None = None,
) -> None:
    forbidden = {
        "--add-dir",
        "--allow-dangerously-skip-permissions",
        "--continue",
        "--dangerously-skip-permissions",
        "--fallback-model",
        "--file",
        "--plugin-dir",
        "--plugin-url",
        "--resume",
        "--worktree",
    }
    if forbidden & set(arguments):
        raise ValueError("Claude invocation contains a forbidden capability")
    if (
        arguments.count("--append-system-prompt") != 1
        or arguments[arguments.index("--append-system-prompt") + 1] != provider_system_prompt
        or not provider_system_prompt.strip()
    ):
        raise ValueError("Claude invocation omits the frozen provider system prompt")
    if "--tools" not in arguments or arguments[arguments.index("--tools") + 1] != "":
        raise ValueError("Claude built-in tools must be disabled")
    if "--allowedTools" not in arguments:
        raise ValueError("Claude invocation omits the MCP tool allowlist")
    if (
        "--disallowedTools" not in arguments
        or tuple(arguments[arguments.index("--disallowedTools") + 1].split(","))
        != CLAUDE_BUILTIN_TOOL_NAMES
    ):
        raise ValueError("Claude invocation omits the frozen built-in tool denylist")
    raw_mcp = arguments[arguments.index("--mcp-config") + 1]
    mcp = json.loads(raw_mcp)
    server = mcp.get("mcpServers", {}).get("verigym") if isinstance(mcp, dict) else None
    if not isinstance(server, dict) or server.get("command") != "/usr/bin/env":
        raise ValueError("Claude MCP server does not use the credential-scrubbing launcher")
    server_arguments = server.get("args")
    if not isinstance(server_arguments, list) or not all(
        isinstance(value, str) for value in server_arguments
    ):
        raise ValueError("Claude MCP server arguments are malformed")
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ):
        if not any(
            server_arguments[index : index + 2] == ["-u", name]
            for index in range(len(server_arguments) - 1)
        ):
            raise ValueError("Claude MCP child credential scrubbing changed")
    if mcp_pythonpath is not None and f"PYTHONPATH={mcp_pythonpath}" not in server_arguments:
        raise ValueError("Claude MCP child import path changed")
    allowed = arguments[arguments.index("--allowedTools") + 1].split(",")
    if tuple(allowed) != CLAUDE_TOOL_NAMES:
        raise ValueError("Claude MCP tool allowlist changed")
    if (
        arguments.count("--model") != 1
        or arguments[arguments.index("--model") + 1] != settings.model_id
    ):
        raise ValueError("Claude model override is not exact")
    if arguments.count("--effort") != 1 or arguments[arguments.index("--effort") + 1] != "max":
        raise ValueError("Claude effort override is not exact")
    if arguments.count("--max-budget-usd") != 1:
        raise ValueError("Claude invocation omits its provider budget")
    try:
        observed_budget = float(arguments[arguments.index("--max-budget-usd") + 1])
    except (IndexError, ValueError) as exc:
        raise ValueError("Claude provider budget argument is malformed") from exc
    if observed_budget != settings.max_budget_usd:
        raise ValueError("Claude provider budget override is not exact")
    if any(
        re.search(r"(?:max.turn|max.output.token|max.token)", value, re.I) for value in arguments
    ):
        raise ValueError("Claude invocation unexpectedly contains an unsupported agent limit")


__all__ = ["CLAUDE_BUILTIN_TOOL_NAMES", "build_arguments", "sanitized_invocation"]
