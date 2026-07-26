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
        capabilities.strict_config_flag,
        capabilities.ignore_user_config_flag,
        capabilities.ignore_rules_flag,
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
            capabilities.config_flag,
            'web_search="disabled"',
            capabilities.config_flag,
            "features.plugins=false",
            capabilities.config_flag,
            "features.multi_agent=false",
            capabilities.config_flag,
            "features.hooks=false",
            capabilities.config_flag,
            "skills.include_instructions=false",
            capabilities.config_flag,
            "skills.bundled.enabled=false",
            capabilities.config_flag,
            "orchestrator.skills.enabled=false",
            capabilities.config_flag,
            "orchestrator.mcp.enabled=false",
            capabilities.config_flag,
            "include_apps_instructions=false",
            capabilities.config_flag,
            "include_environment_context=false",
        ]
    )
    if settings.integration_track == "codex_cli_external_agent":
        arguments.extend(
            [
                capabilities.config_flag,
                "sandbox_workspace_write.network_access=false",
            ]
        )
    arguments.extend(
        [
            capabilities.config_flag,
            f'model_reasoning_effort="{settings.effective_reasoning_effort}"',
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
        "sandbox_backend": settings.sandbox_backend,
        "sandbox_backend_source": settings.sandbox_backend_source,
        "auth_mode_label": settings.auth_mode_label,
        "requested_auth_mode": settings.requested_auth_mode,
        "resolved_auth_mode": settings.resolved_auth_mode,
        "auth_semantic_id": settings.auth_semantic_id,
        "auth_alias_used": settings.auth_alias_used,
        "requested_reasoning_effort": settings.requested_reasoning_effort,
        "effective_reasoning_effort": settings.effective_reasoning_effort,
        "reasoning_effort_source": settings.reasoning_effort_source,
        "inherited_reasoning_effort_allowed": settings.inherited_reasoning_effort_allowed,
        "credential_values_persisted": False,
        "proxy_values_persisted": False,
        "allow_proxy_environment": settings.allow_proxy_environment,
        "proxy_environment_allowed": settings.allow_proxy_environment,
        "forwarded_proxy_environment_names": list(settings.forwarded_proxy_environment_names),
        "shell": False,
        "new_process_session": True,
        "requested_process_timeout_s": settings.requested_process_timeout_s,
        "task_wall_time_s": settings.task_wall_time_s,
        "effective_process_timeout_s": settings.effective_process_timeout_s,
        "timeout_clamped": settings.timeout_clamped,
        "timeout_s": settings.effective_process_timeout_s,
        "max_output_bytes": settings.max_output_bytes,
        "execution_surface": "codex_cli",
        "tool_availability_policy": settings.tool_availability_policy,
        "tool_use_policy": settings.tool_use_policy,
        "user_config_loaded": False,
        "exec_rules_loaded": False,
        "project_instructions_enabled": False,
        "skills_instructions_enabled": False,
        "plugins_enabled": False,
        "web_search_enabled": False,
        "mcp_servers_enabled": False,
    }


__all__ = ["build_exec_arguments", "sanitized_invocation"]
