"""Plugin-to-core request construction for runtime-owned external execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from verigym.plugin_api import (
    ExternalAgentBridge,
    ExternalProcessRequest,
    ExternalProcessResult,
)

from .capabilities import CapabilityReport
from .config import CodexSettings
from .process import CodexProcessResult, ExecutableIdentity


@dataclass(frozen=True)
class RuntimeExecutionOutcome:
    process: CodexProcessResult
    runtime_result: ExternalProcessResult


def execute_runtime_process(
    *,
    bridge: ExternalAgentBridge,
    executable: ExecutableIdentity,
    capabilities: CapabilityReport,
    settings: CodexSettings,
    prompt: str,
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"],
) -> RuntimeExecutionOutcome:
    """Ask the selected runtime to own exactly one model-bearing process."""

    if settings.integration_track not in {
        "codex_cli_readonly_single_turn_agent",
        "codex_cli_external_agent",
    }:
        raise ValueError("runtime-owned execution requires a supported integration track")
    if settings.requested_reasoning_effort != "xhigh":
        raise ValueError("runtime-owned execution requires reasoning effort xhigh")
    if settings.resolved_auth_mode != "inherited_codex_login":
        raise ValueError("Docker runtime execution requires inherited Codex login")
    request = ExternalProcessRequest(
        protocol="codex_app_server_remote_environment_v1",
        runtime_role="agent",
        argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
        logical_cwd="/workspace",
        stdin_text=prompt,
        stdin_transport="runtime_protocol_adapter",
        network_policy="none",
        mount_policy="task_workspace_only",
        writable_destinations=["/workspace", "/tmp"],
        container_environment_names=[],
        integration_track=cast(
            Literal[
                "codex_cli_readonly_single_turn_agent",
                "codex_cli_external_agent",
            ],
            settings.integration_track,
        ),
        workspace_mode=workspace_mode,
        logical_workspace_root="/workspace",
        requested_model_id=settings.model_id,
        requested_reasoning_effort=cast(Literal["xhigh"], settings.requested_reasoning_effort),
        executable_path=executable.path,
        executable_name=executable.name,
        executable_sha256=executable.sha256,
        executable_version=capabilities.version_output,
        capability_fingerprint=capabilities.capability_fingerprint,
        requested_auth_mode=settings.requested_auth_mode,
        resolved_auth_mode=cast(
            Literal["inherited_codex_login"],
            settings.resolved_auth_mode,
        ),
        auth_semantic_id=settings.auth_semantic_id,
        allow_proxy_environment=settings.allow_proxy_environment,
        forwarded_proxy_environment_names=list(settings.forwarded_proxy_environment_names),
        timeout_s=settings.max_process_time_s,
        max_output_bytes=settings.max_output_bytes,
        editable_globs=list(bridge.editable_globs),
        readonly_globs=list(bridge.readonly_globs),
    )
    runtime_result = bridge.execute_process(request)
    process = CodexProcessResult(
        arguments=("<runtime-owned-codex-app-server>",),
        exit_code=runtime_result.exit_code,
        stdout=runtime_result.stdout,
        stderr=runtime_result.stderr,
        duration_s=runtime_result.duration_s,
        timed_out=runtime_result.timed_out,
        stdout_truncated=runtime_result.stdout_truncated,
        stderr_truncated=runtime_result.stderr_truncated,
        process_group_cleaned=runtime_result.process_group_cleaned,
    )
    return RuntimeExecutionOutcome(process=process, runtime_result=runtime_result)


__all__ = ["RuntimeExecutionOutcome", "execute_runtime_process"]
