"""Track B: external Codex CLI coding-agent adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentAction,
    AgentAdapter,
    AgentContext,
    AgentDescriptor,
    AgentTerminationError,
    EpisodeFailure,
    EpisodeResult,
    ExternalAgentAccounting,
    ExternalAgentBridge,
    ExternalAgentCallIdentity,
    FinalSubmissionAction,
    InteractionMode,
    Observation,
    TerminationReason,
)

from ._version import __version__
from .artifacts import CodexRunEvidence, update_summary
from .capabilities import CapabilityReport, runtime_capabilities
from .config import CodexSettings, agent_settings
from .events import (
    EventParseError,
    ParsedEventStream,
    parse_event_stream,
    parse_partial_event_stream,
)
from .invocation import build_exec_arguments, sanitized_invocation
from .process import (
    CodexCliProcessRunner,
    CodexProcessError,
    CodexProcessResult,
    ExecutableIdentity,
)
from .security import (
    CodexPolicyError,
    WorkspaceSnapshot,
    assert_instruction_isolation,
    assert_safe_workspace_tree,
    compare_workspace_snapshots,
    sandbox_backend_failure,
    snapshot_visible_workspace,
    validate_external_events,
)
from .util import redact_text


class CodexCliAgentAdapter(AgentAdapter):
    """Run exactly one external coding-agent episode in the visible workspace."""

    requires_model = False
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="codex-cli-agent",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "external_coding_agent",
            "workspace_editing",
            "machine_readable_events",
            "single_external_episode",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._executable: ExecutableIdentity | None = None
        self._capabilities: CapabilityReport | None = None
        self._settings: CodexSettings | None = None
        self._prompt: str | None = None
        self._launched = False
        self._artifact_root: Path | None = None
        self._workspace_before: WorkspaceSnapshot | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None:
            raise ValueError("codex-cli-agent requires ExternalAgentBridge")
        if bridge.isolation_level != "local_trusted":
            raise ValueError(
                "codex-cli-agent pilot supports only host-visible LocalRuntime workspaces"
            )
        workspace = bridge.workspace_root.resolve(strict=True)
        assert_instruction_isolation(workspace)
        assert_safe_workspace_tree(workspace)
        workspace_before = snapshot_visible_workspace(workspace)
        executable, capabilities = runtime_capabilities()
        settings = agent_settings(
            context.agent_options,
            capabilities,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        self._context = context
        self._bridge = bridge
        self._executable = executable
        self._capabilities = capabilities
        self._settings = settings
        self._prompt = _agent_prompt(context, bridge)
        self._launched = False
        self._artifact_root = bridge.artifact_root
        self._workspace_before = workspace_before
        bridge.emit_event(
            "codex_cli_capabilities_resolved",
            {
                "capability_fingerprint": capabilities.capability_fingerprint,
                "executable_sha256": capabilities.executable_sha256,
                "model_call_count": 0,
            },
        )

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._launched:
            raise AgentTerminationError(
                TerminationReason.POLICY_VIOLATION,
                EpisodeFailure(
                    kind="policy",
                    category="multiple_external_episodes",
                    message="codex-cli-agent attempted more than one external episode",
                ),
            )
        self._launched = True
        context, bridge, executable, capabilities, settings, prompt = self._configured()
        workspace = bridge.workspace_root.resolve(strict=True)
        arguments = build_exec_arguments(capabilities, settings)
        invocation = sanitized_invocation(
            arguments,
            settings,
            capabilities,
            working_directory_policy="visible_task_workspace",
        )
        bridge.emit_event(
            "codex_cli_process_started",
            {
                "integration_track": settings.integration_track,
                "sandbox_policy": settings.sandbox_policy,
                "sandbox_backend": settings.sandbox_backend,
                "sandbox_backend_source": settings.sandbox_backend_source,
                "approval_policy": settings.approval_policy,
                "effective_reasoning_effort": settings.effective_reasoning_effort,
                "reasoning_effort_source": settings.reasoning_effort_source,
            },
        )
        runner = CodexCliProcessRunner(
            executable,
            auth_mode=settings.resolved_auth_mode,
            credential_env=settings.credential_env,
            max_output_bytes=settings.max_output_bytes,
            allow_proxy_environment=settings.allow_proxy_environment,
        )
        parsed: ParsedEventStream | None = None
        failure: AgentTerminationError | None = None
        event_policy: dict[str, Any] = {
            "schema_version": "1.0",
            "policy_id": settings.tool_use_policy,
            "policy_passed": False,
            "evaluation_complete": False,
        }
        workspace_policy: dict[str, Any]
        workspace_after: WorkspaceSnapshot | None = None
        workspace_before = self._workspace_before
        if workspace_before is None:
            raise RuntimeError("codex-cli-agent workspace identity was not captured")
        try:
            process = runner.run(
                arguments,
                cwd=workspace,
                timeout_s=settings.max_process_time_s,
                stdin_bytes=prompt.encode("utf-8"),
            )
        except CodexProcessError as exc:
            process = _failed_process(str(exc))
            failure = _agent_failure(
                TerminationReason.MODEL_ERROR,
                "process_boundary",
                str(exc),
                infrastructure=True,
            )
        if failure is None:
            if process.timed_out or process.stdout_truncated or process.stderr_truncated:
                parsed = parse_partial_event_stream(process.stdout, roots=(workspace,))
                failure = _process_failure(process, parsed)
            else:
                try:
                    parsed = _parse_agent_process(process, workspace)
                    validate_external_events(parsed, workspace)
                    event_policy = {
                        "schema_version": "1.0",
                        "policy_id": settings.tool_use_policy,
                        "policy_passed": True,
                        "evaluation_complete": True,
                    }
                except CodexPolicyError as exc:
                    failure = _agent_failure(
                        TerminationReason.POLICY_VIOLATION,
                        "workspace_policy",
                        str(exc),
                        infrastructure=False,
                    )
                    bridge.emit_event(
                        "codex_cli_policy_violation",
                        {"category": "workspace_policy", "message": str(exc)},
                    )
                    event_policy = {
                        "schema_version": "1.0",
                        "policy_id": settings.tool_use_policy,
                        "policy_passed": False,
                        "evaluation_complete": True,
                        "failure_category": "workspace_policy",
                        "failure_message": str(exc),
                    }
                except EventParseError as exc:
                    backend_category = sandbox_backend_failure(process.stdout, process.stderr)
                    failure = _agent_failure(
                        TerminationReason.MODEL_ERROR,
                        backend_category or "parser_error",
                        (
                            "Codex CLI workspace sandbox backend was unavailable"
                            if backend_category is not None
                            else str(exc)
                        ),
                        infrastructure=True,
                    )
        try:
            workspace_after = snapshot_visible_workspace(workspace)
            workspace_policy = compare_workspace_snapshots(
                workspace_before,
                workspace_after,
                editable_globs=bridge.editable_globs,
                readonly_globs=bridge.readonly_globs,
            )
        except CodexPolicyError as exc:
            workspace_policy = {
                "schema_version": "1.0",
                "policy_id": settings.tool_use_policy,
                "before": workspace_before.safe_dict(),
                "after": workspace_after.safe_dict() if workspace_after is not None else None,
                "policy_passed": False,
                "failure_category": "workspace_policy",
                "failure_message": str(exc),
                "content_values_persisted": False,
            }
            failure = _agent_failure(
                TerminationReason.POLICY_VIOLATION,
                "workspace_policy",
                str(exc),
                infrastructure=False,
            )
            bridge.emit_event(
                "codex_cli_policy_violation",
                {"category": "workspace_policy", "message": str(exc)},
            )
        if parsed is not None:
            for event in parsed.events:
                bridge.emit_event(
                    "codex_cli_event_observed",
                    {
                        "sequence": event.sequence,
                        "category": event.category,
                        "upstream_type": event.upstream_type,
                        "diagnostic_only": parsed.diagnostic_only,
                    },
                )
        if failure is None:
            failure = _process_failure(process, parsed)
        workspace_write_count = int(workspace_policy.get("changed_file_count") or 0)
        identity = _external_identity(
            settings,
            capabilities,
            parsed,
            workspace_write_count=workspace_write_count,
        )
        accounting = _external_accounting(process, parsed)
        bridge.emit_event(
            "codex_cli_process_completed",
            {
                "exit_code": process.exit_code,
                "timed_out": process.timed_out,
                "event_count": len(parsed.events) if parsed is not None else 0,
            },
        )
        bridge.emit_event(
            "codex_cli_identity_observed",
            identity.model_dump(mode="json"),
        )
        bridge.record_accounting(accounting)
        evidence = CodexRunEvidence(
            capabilities=capabilities,
            invocation=invocation,
            process=process,
            parsed=parsed,
            identity=identity,
            accounting=accounting,
            summary={
                "integration_track": settings.integration_track,
                "sandbox_backend": settings.sandbox_backend,
                "sandbox_backend_source": settings.sandbox_backend_source,
                "structurally_successful_external_episode": failure is None,
                "candidate_correctness_inferred_from_cli": False,
                "failure_category": (failure.failure.category if failure is not None else None),
                "failure_message": (failure.failure.message if failure is not None else None),
            },
            event_policy=event_policy,
            workspace_policy=workspace_policy,
            roots_to_redact=(workspace,),
        )
        evidence.write(bridge.artifact_root, create=False)
        if failure is not None:
            raise failure
        return FinalSubmissionAction(
            message=(
                "External Codex CLI episode ended; candidate submitted to the ordinary "
                "VeriGym freeze and hidden-verifier flow."
            )
        )

    def finish(self, result: EpisodeResult) -> None:
        if self._artifact_root is not None and (self._artifact_root / "summary.json").is_file():
            update_summary(
                self._artifact_root,
                {
                    "verigym_run_id": result.run_id,
                    "ordinary_verifier_resolved": result.resolved,
                    "ordinary_termination_reason": result.termination_reason,
                    "model_called_during_finish": False,
                    "candidate_modified_during_finish": False,
                },
            )

    def _configured(
        self,
    ) -> tuple[
        AgentContext,
        ExternalAgentBridge,
        ExecutableIdentity,
        CapabilityReport,
        CodexSettings,
        str,
    ]:
        if (
            self._context is None
            or self._bridge is None
            or self._executable is None
            or self._capabilities is None
            or self._settings is None
            or self._prompt is None
        ):
            raise RuntimeError("codex-cli-agent has not been started")
        return (
            self._context,
            self._bridge,
            self._executable,
            self._capabilities,
            self._settings,
            self._prompt,
        )


def _agent_prompt(context: AgentContext, bridge: ExternalAgentBridge) -> str:
    workspace = bridge.workspace_root.resolve(strict=True)
    visible_files = [
        path.relative_to(workspace).as_posix()
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and ".verigym_internal" not in path.parts
    ]
    visible_tools = sorted(
        tool
        for tool in context.task.interaction.allowed_tools
        if tool not in context.task.interaction.denied_tools
    )
    payload = {
        "schema_version": "1.0",
        "task": {
            "title": context.task.title,
            "description": context.task.description,
            "entrypoints": sorted(context.task.workspace.entrypoints),
        },
        "visible_file_tree": visible_files,
        "workspace_policy": {
            "editable_globs": sorted(bridge.editable_globs),
            "readonly_globs": sorted(bridge.readonly_globs),
            "network": "disabled",
            "outside_workspace_access": "forbidden",
        },
        "visible_verification_interfaces": visible_tools,
        "budget": {
            "max_wall_time_s": context.task.budget.max_wall_time_s,
            "max_changed_files": context.task.workspace.max_changed_files,
            "max_patch_lines": context.task.workspace.max_patch_lines,
        },
        "instructions": [
            "Work only inside the current visible task workspace.",
            "Do not access parent, home, repository, credential, or hidden-verifier paths.",
            "Read the visible files, implement the RTL task, and use only visible checks.",
            "Do not use network, MCP, plugins, external repositories, or web search.",
            "Do not ask the user questions.",
            "Finish after one candidate; hidden verification happens only after submission.",
        ],
    }
    return (
        '<verigym_external_agent_task schema_version="1.0">\n'
        + json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n</verigym_external_agent_task>\n"
    )


def _parse_agent_process(
    process: CodexProcessResult,
    workspace: Path,
) -> ParsedEventStream:
    parsed = parse_event_stream(process.stdout, roots=(workspace,))
    if process.exit_code == 0 and not parsed.terminal_event_seen:
        raise EventParseError("Codex CLI external-agent stream has no terminal event")
    if process.exit_code == 0 and not parsed.final_messages:
        raise EventParseError("Codex CLI external-agent stream has no final message")
    return parsed


def _process_failure(
    process: CodexProcessResult,
    parsed: ParsedEventStream | None,
) -> AgentTerminationError | None:
    if process.timed_out:
        return _agent_failure(
            TerminationReason.MODEL_ERROR,
            "timeout",
            "Codex CLI external-agent process timed out",
            infrastructure=True,
        )
    if process.stdout_truncated or process.stderr_truncated:
        return _agent_failure(
            TerminationReason.MODEL_ERROR,
            "output_limit",
            "Codex CLI external-agent output exceeded the configured bound",
            infrastructure=True,
        )
    sandbox_failure = sandbox_backend_failure(process.stdout, process.stderr)
    if sandbox_failure is not None:
        return _agent_failure(
            TerminationReason.MODEL_ERROR,
            sandbox_failure,
            "Codex CLI workspace sandbox backend was unavailable",
            infrastructure=True,
        )
    if process.exit_code == 0 and parsed is not None and not parsed.error_messages:
        return None
    text = " ".join(
        [
            process.stderr,
            *(parsed.error_messages if parsed is not None else ()),
        ]
    ).lower()
    if any(marker in text for marker in ("unauthorized", "authentication", "login", "401")):
        category = "authentication"
    elif any(marker in text for marker in ("rate limit", "too many requests", "429")):
        category = "rate_limit"
    elif any(
        marker in text
        for marker in ("connection", "transport", "network", "unavailable", "502", "503")
    ):
        category = "transport"
    else:
        category = "remote_process_error"
    message = (
        parsed.error_messages[0]
        if parsed is not None and parsed.error_messages
        else redact_text(process.stderr).strip() or "Codex CLI external-agent process failed"
    )
    return _agent_failure(
        TerminationReason.MODEL_ERROR,
        category,
        message,
        infrastructure=True,
    )


def _external_identity(
    settings: CodexSettings,
    capabilities: CapabilityReport,
    parsed: ParsedEventStream | None,
    *,
    workspace_write_count: int,
) -> ExternalAgentCallIdentity:
    observed = parsed.observed_model_id if parsed is not None else None
    tool_event_count = len(parsed.tool_use_events) if parsed is not None else 0
    file_writes = parsed.file_write_count if parsed is not None else 0
    patches = parsed.patch_count if parsed is not None else 0
    file_reads = parsed.file_read_count if parsed is not None else 0
    network_events = (
        sum(
            event.category == "tool_call"
            and "web_search" in str(event.payload.get("tool") or "").lower()
            for event in parsed.events
        )
        if parsed is not None
        else 0
    )
    mcp_events = (
        sum(
            event.category == "tool_call" and "mcp" in str(event.payload.get("tool") or "").lower()
            for event in parsed.events
        )
        if parsed is not None
        else 0
    )
    return ExternalAgentCallIdentity(
        adapter_name="codex-cli-agent",
        adapter_version=__version__,
        harness_name="verigym-external-agent-bridge",
        requested_model_id=settings.model_id,
        observed_model_id=observed,
        requested_reasoning_effort=settings.requested_reasoning_effort,
        effective_reasoning_effort=settings.effective_reasoning_effort,
        reasoning_effort_source=settings.reasoning_effort_source,
        inherited_reasoning_effort_allowed=settings.inherited_reasoning_effort_allowed,
        executable_name=capabilities.executable_name,
        executable_sha256=capabilities.executable_sha256,
        executable_version=capabilities.version_output,
        capability_fingerprint=capabilities.capability_fingerprint,
        configuration_fingerprint=settings.configuration_fingerprint,
        invocation_count=1,
        identity_confidence="observed" if observed else "requested_only",
        reproducibility_scope="mutable_remote_observation",
        integration_track="codex_cli_external_agent",
        execution_surface="codex_cli",
        interaction_class="cli_agent_workspace_writing",
        harness_id="-".join(capabilities.version_output.strip().lower().split())[:128],
        model_client_kind="cli_agent_mediated",
        agent_harness_kind="codex_cli",
        tool_availability_policy=settings.tool_availability_policy,
        tool_use_policy=settings.tool_use_policy,
        tool_event_count=tool_event_count,
        side_effecting_tool_event_count=file_writes + patches,
        read_only_tool_event_count=file_reads,
        external_network_tool_event_count=network_events,
        mcp_tool_event_count=mcp_events,
        workspace_write_count=max(file_writes + patches, workspace_write_count),
        chat_eval_compatible=False,
        pure_api_model_eval=False,
        direct_api_benchmark=False,
        auth_mode_label=settings.auth_mode_label,
        requested_auth_mode=settings.requested_auth_mode,
        resolved_auth_mode=settings.resolved_auth_mode,
        auth_semantic_id=settings.auth_semantic_id,
        auth_alias_used=settings.auth_alias_used,
        sandbox_policy=settings.sandbox_policy,
        approval_policy=settings.approval_policy,
    )


def _external_accounting(
    process: CodexProcessResult,
    parsed: ParsedEventStream | None,
) -> ExternalAgentAccounting:
    canonical = parsed if parsed is not None and parsed.canonical_stream_complete else None
    return ExternalAgentAccounting(
        process_wall_time_s=process.duration_s,
        cli_event_count=len(parsed.events) if parsed is not None else 0,
        external_tool_call_count=(canonical.external_tool_count if canonical is not None else None),
        external_command_count=canonical.command_count if canonical is not None else None,
        external_file_read_count=(canonical.file_read_count if canonical is not None else None),
        external_file_write_count=(canonical.file_write_count if canonical is not None else None),
        external_patch_count=canonical.patch_count if canonical is not None else None,
        input_tokens=canonical.input_tokens if canonical is not None else None,
        output_tokens=canonical.output_tokens if canonical is not None else None,
        total_tokens=canonical.total_tokens if canonical is not None else None,
        cost=None,
        currency=None,
    )


def _agent_failure(
    reason: TerminationReason,
    category: str,
    message: str,
    *,
    infrastructure: bool,
) -> AgentTerminationError:
    return AgentTerminationError(
        reason,
        EpisodeFailure(
            kind=(
                "policy"
                if reason == TerminationReason.POLICY_VIOLATION
                else "model"
                if reason == TerminationReason.MODEL_ERROR
                else "agent"
            ),
            category=category,
            message=redact_text(message)[:4096],
            infrastructure=infrastructure,
        ),
    )


def _failed_process(message: str) -> CodexProcessResult:
    return CodexProcessResult(
        arguments=(),
        exit_code=None,
        stdout="",
        stderr=redact_text(message),
        duration_s=0.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )


__all__ = ["CodexCliAgentAdapter"]
