"""Capability-derived Codex exec argument construction."""

from __future__ import annotations

from .capabilities import CapabilityReport
from .config import CodexSettings


def build_exec_arguments(
    capabilities: CapabilityReport,
    settings: CodexSettings,
) -> list[str]:
    arguments = [
        capabilities.non_interactive_command,
        capabilities.machine_output_flag,
        capabilities.ephemeral_flag,
        capabilities.skip_git_flag,
        capabilities.sandbox_flag,
        settings.sandbox_policy,
        capabilities.model_flag,
        settings.model_id,
    ]
    if capabilities.approval_flag is not None and "never" in capabilities.supported_approval_modes:
        arguments.extend([capabilities.approval_flag, "never"])
    arguments.extend(
        [
            capabilities.config_flag,
            "mcp_servers={}",
            capabilities.config_flag,
            "project_doc_max_bytes=0",
        ]
    )
    if settings.integration_track == "codex_cli_external_agent":
        arguments.extend(
            [
                capabilities.config_flag,
                "sandbox_workspace_write.network_access=false",
            ]
        )
    arguments.append("-")
    return arguments


def sanitized_invocation(
    arguments: list[str],
    settings: CodexSettings,
    capabilities: CapabilityReport,
    *,
    working_directory_policy: str,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "argv": ["<codex>", *arguments],
        "stdin_protocol": capabilities.selected_invocation_protocol,
        "machine_event_protocol": capabilities.selected_event_protocol,
        "working_directory_policy": working_directory_policy,
        "auth_mode_label": settings.auth_mode_label,
        "credential_values_persisted": False,
        "shell": False,
        "new_process_session": True,
        "timeout_s": settings.max_process_time_s,
        "max_output_bytes": settings.max_output_bytes,
    }


__all__ = ["build_exec_arguments", "sanitized_invocation"]
