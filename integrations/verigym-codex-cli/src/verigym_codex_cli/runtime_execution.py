"""Plugin-to-core request construction for runtime-owned external execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from verigym.core.hashing import content_hash
from verigym.plugin_api import (
    ExternalAgentBridge,
    ExternalProcessInvocationSpec,
    ExternalProcessPayloadBinding,
    ExternalProcessRequest,
    ExternalProcessResult,
    PromptPolicyDescriptor,
    bind_external_process_payload,
    build_external_process_request,
    resolve_external_process_invocation_spec,
)

from .capabilities import CapabilityReport
from .config import CodexSettings
from .process import CodexProcessResult, ExecutableIdentity


@dataclass(frozen=True)
class RuntimeExecutionOutcome:
    process: CodexProcessResult
    runtime_result: ExternalProcessResult


def resolve_runtime_process_invocation_spec(
    *,
    bridge: ExternalAgentBridge,
    executable: ExecutableIdentity,
    capabilities: CapabilityReport,
    settings: CodexSettings,
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"],
    prompt_policy: PromptPolicyDescriptor | None = None,
    prompt_contract_id: str | None = None,
    expected_output_schema_hash: str | None = None,
) -> ExternalProcessInvocationSpec:
    """Resolve the launch-invariant Codex process identity without a prompt."""

    if settings.integration_track not in {
        "codex_cli_readonly_single_turn_agent",
        "codex_cli_external_agent",
    }:
        raise ValueError("runtime-owned execution requires a supported integration track")
    allowed_efforts = (
        {"xhigh", "max"} if settings.integration_track == "codex_cli_external_agent" else {"xhigh"}
    )
    if settings.requested_reasoning_effort not in allowed_efforts:
        raise ValueError("runtime-owned execution received an unsupported reasoning effort")
    if settings.resolved_auth_mode != "inherited_codex_login":
        raise ValueError("Docker runtime execution requires inherited Codex login")
    read_only_mounts = list(getattr(bridge, "read_only_mounts", []))
    contract = prompt_contract_id or settings.prompt_contract_id
    output_schema = expected_output_schema_hash or content_hash(
        {
            "schema_version": "1.0",
            "protocol": "codex_app_server_remote_environment_v1",
            "terminal_output": "codex_jsonl_event_stream",
        }
    )
    return resolve_external_process_invocation_spec(
        protocol="codex_app_server_remote_environment_v1",
        runtime_role="agent",
        argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
        logical_cwd="/workspace",
        stdin_transport="runtime_protocol_adapter",
        network_policy="none",
        mount_policy=(
            "task_workspace_and_public_tests" if read_only_mounts else "task_workspace_only"
        ),
        writable_destinations=["/workspace", "/tmp"],
        read_only_mounts=read_only_mounts,
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
        requested_reasoning_effort=settings.requested_reasoning_effort,
        executable_path_identity="verified_host_codex_cli",
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
        forwarded_proxy_environment_names=list(settings.runtime_forwarded_proxy_environment_names),
        timeout_s=settings.max_process_time_s,
        max_output_bytes=settings.max_output_bytes,
        editable_globs=list(bridge.editable_globs),
        readonly_globs=list(bridge.readonly_globs),
        prompt_policy=prompt_policy,
        prompt_policy_hash=(
            prompt_policy.configuration_fingerprint if prompt_policy is not None else None
        ),
        prompt_contract_id=contract,
        expected_output_schema_hash=output_schema,
    )


def build_runtime_process_request(
    *,
    bridge: ExternalAgentBridge,
    executable: ExecutableIdentity,
    capabilities: CapabilityReport,
    settings: CodexSettings,
    prompt: str,
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"],
    prompt_policy: PromptPolicyDescriptor | None = None,
    invocation_spec: ExternalProcessInvocationSpec | None = None,
    payload_binding: ExternalProcessPayloadBinding | None = None,
    template_hash: str | None = None,
    input_dataset_hash: str | None = None,
    expected_output_schema_hash: str | None = None,
) -> ExternalProcessRequest:
    """Build the complete immutable runtime-owned process request."""

    spec = invocation_spec or resolve_runtime_process_invocation_spec(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        workspace_mode=workspace_mode,
        prompt_policy=prompt_policy,
        expected_output_schema_hash=expected_output_schema_hash,
    )
    binding = payload_binding or bind_external_process_payload(
        spec,
        prompt,
        template_hash=template_hash
        or content_hash(
            {
                "schema_version": "1.0",
                "renderer": "codex_cli_runtime_prompt_v1",
                "prompt_contract_id": spec.prompt_contract_id,
            }
        ),
        input_dataset_hash=input_dataset_hash
        or content_hash(
            {
                "schema_version": "1.0",
                "prompt_policy_hash": spec.prompt_policy_hash,
                "workspace_mode": spec.workspace_mode,
            }
        ),
    )
    return build_external_process_request(
        spec,
        binding,
        prompt,
        executable_path=executable.path,
    )


def execute_runtime_process(
    *,
    bridge: ExternalAgentBridge,
    executable: ExecutableIdentity,
    capabilities: CapabilityReport,
    settings: CodexSettings,
    prompt: str,
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"],
    prompt_policy: PromptPolicyDescriptor | None = None,
    invocation_spec: ExternalProcessInvocationSpec | None = None,
    payload_binding: ExternalProcessPayloadBinding | None = None,
    template_hash: str | None = None,
    input_dataset_hash: str | None = None,
    expected_output_schema_hash: str | None = None,
) -> RuntimeExecutionOutcome:
    """Ask the selected runtime to own exactly one model-bearing process."""

    request = build_runtime_process_request(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        prompt=prompt,
        prompt_policy=prompt_policy,
        workspace_mode=workspace_mode,
        invocation_spec=invocation_spec,
        payload_binding=payload_binding,
        template_hash=template_hash,
        input_dataset_hash=input_dataset_hash,
        expected_output_schema_hash=expected_output_schema_hash,
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


__all__ = [
    "RuntimeExecutionOutcome",
    "build_runtime_process_request",
    "execute_runtime_process",
    "resolve_runtime_process_invocation_spec",
]
