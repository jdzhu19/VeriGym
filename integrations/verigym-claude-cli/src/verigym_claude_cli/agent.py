"""Claude CLI external coding-agent adapter with runtime-owned MCP tools."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from verigym.core.repository_tool_broker import RepositoryToolBrokerLimits
from verigym.evolution.training_transcript import build_teacher_transcript
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentAction,
    AgentAdapter,
    AgentContext,
    AgentDescriptor,
    AgentPromptPolicySpec,
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
    validate_prompt_text,
)
from verigym.protocols.repository_action import repository_tool_definitions

from ._version import __version__
from .artifacts import update_summary, write_evidence
from .broker import BrokerStats, BrokerTurn, ClaudeToolBroker
from .capabilities import CapabilityReport, runtime_capabilities
from .config import ClaudeSettings, agent_settings
from .events import (
    EventParseError,
    ParsedEventStream,
    TranscriptNormalizationInfrastructureError,
    normalize_training_messages,
    parse_event_stream,
)
from .invocation import build_arguments, sanitized_invocation
from .process import (
    ClaudeCliProcessRunner,
    ClaudeProcessError,
    ClaudeProcessResult,
    ExecutableIdentity,
    configured_broker_root,
    provider_environment,
    trusted_mcp_pythonpath,
)
from .util import atomic_json, redact_text


class ClaudeCliAgentAdapter(AgentAdapter):
    """Run one bounded outer episode while Claude performs its internal agent loop."""

    requires_model = False
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="claude_cli_workspace_repository_task_context_v5",
        prompt_contract_version="5.0.0",
        task_context_policy="repository_visible_task_context_v1",
        base_instruction_policy="claude_cli_verigym_mcp_repository_agent_v4",
        content_visibility_policy="public_task_context_and_mcp_workspace_only_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=True,
    )
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="claude-cli-agent",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="anthropic-claude-cli",
        capabilities=[
            "external_coding_agent",
            "workspace_editing",
            "machine_readable_events",
            "runtime_mcp_tools",
            "single_external_episode",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._executable: ExecutableIdentity | None = None
        self._capabilities: CapabilityReport | None = None
        self._settings: ClaudeSettings | None = None
        self._prompt: str | None = None
        self._launched = False
        self._artifact_root: Path | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None:
            raise ValueError("claude-cli-agent requires ExternalAgentBridge")
        if bridge.isolation_level != "docker_standard":
            raise ValueError("claude-cli-agent requires the Docker runtime security boundary")
        executable, capabilities = runtime_capabilities()
        settings = agent_settings(
            context.agent_options,
            capabilities,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        _bind_prompt_policy(context, settings)
        prompt = validate_prompt_text(_agent_prompt(context, bridge), context.prompt_policy)
        self._context = context
        self._bridge = bridge
        self._executable = executable
        self._capabilities = capabilities
        self._settings = settings
        self._prompt = prompt
        self._launched = False
        self._artifact_root = bridge.artifact_root
        bridge.emit_event(
            "claude_cli_prompt_policy_bound",
            {
                "prompt_policy_hash": context.prompt_policy.configuration_fingerprint
                if context.prompt_policy is not None
                else None,
                "agent_version_id": settings.agent_version_id,
                "agent_version_hash": settings.agent_version_hash,
                "model_call_count": 0,
            },
        )
        bridge.emit_event(
            "claude_cli_capabilities_resolved",
            {
                "capability_fingerprint": capabilities.capability_fingerprint,
                "executable_sha256": capabilities.executable_sha256,
                "diagnostic_process_count": capabilities.diagnostic_process_count,
                "model_call_count": capabilities.model_call_count,
            },
        )

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._launched:
            raise _termination(
                TerminationReason.POLICY_VIOLATION,
                kind="policy",
                category="multiple_external_episodes",
                message="claude-cli-agent attempted more than one external episode",
                infrastructure=False,
            )
        self._launched = True
        context, bridge, executable, capabilities, settings, prompt = self._configured()
        public_test_ids = _public_test_ids(context)
        process: ClaudeProcessResult
        broker_stats: BrokerStats
        broker_turns: tuple[BrokerTurn, ...] = ()
        invocation: dict[str, object]
        try:
            root = configured_broker_root()
            with tempfile.TemporaryDirectory(prefix="run-", dir=root) as raw_control:
                control = Path(raw_control)
                cwd = control / "cwd"
                cwd.mkdir(mode=0o700)
                socket_path = control / "b" / "mcp.sock"
                broker = ClaudeToolBroker(
                    bridge=bridge,
                    socket_path=socket_path,
                    public_test_ids=public_test_ids,
                    capture_training_transcript=settings.capture_training_transcript,
                    campaign_role=settings.campaign_role,
                    limits=(
                        RepositoryToolBrokerLimits(
                            max_tool_calls=settings.max_tool_calls,
                            max_patch_calls=settings.max_patch_calls,
                            max_consecutive_rejected_calls=(
                                settings.max_consecutive_rejected_calls
                            ),
                        )
                        if settings.max_tool_calls is not None
                        and settings.max_patch_calls is not None
                        and settings.max_consecutive_rejected_calls is not None
                        else None
                    ),
                )
                arguments = build_arguments(
                    settings,
                    socket_path=socket_path,
                    run_id=context.run_id,
                    provider_system_prompt=_training_system_prompt(),
                    mcp_pythonpath=trusted_mcp_pythonpath(),
                )
                invocation = sanitized_invocation(arguments, settings)
                environment = provider_environment(
                    control,
                    allow_proxy_environment=settings.allow_proxy_environment,
                    include_auth=True,
                )
                runner = ClaudeCliProcessRunner(
                    executable,
                    max_output_bytes=settings.max_output_bytes,
                )
                bridge.emit_event(
                    "claude_cli_process_started",
                    {
                        "integration_track": settings.integration_track,
                        "requested_model_id": settings.model_id,
                        "effective_reasoning_effort": settings.effective_reasoning_effort,
                        "builtin_tools_available": False,
                        "internal_turn_limit": None,
                        "model_token_limit": settings.max_provider_tokens,
                        "model_token_limit_scope": "cache_inclusive_stream_observed",
                        "budget_limit": settings.max_budget_usd,
                        "budget_limit_currency": "USD",
                        "broker_max_tool_calls": settings.max_tool_calls,
                        "broker_max_patch_calls": settings.max_patch_calls,
                        "broker_max_consecutive_rejected_calls": (
                            settings.max_consecutive_rejected_calls
                        ),
                    },
                )
                broker.start()
                try:
                    process = runner.run(
                        arguments,
                        cwd=cwd,
                        timeout_s=settings.effective_process_timeout_s,
                        stdin_bytes=prompt.encode("utf-8"),
                        environment=environment,
                        cancellation_event=broker.cancellation_event,
                        max_provider_tokens=settings.max_provider_tokens,
                    )
                finally:
                    broker.stop()
                broker_stats = broker.stats()
                if settings.capture_training_transcript:
                    broker_turns = broker.training_turns()
        except ClaudeProcessError as exc:
            raise _termination(
                TerminationReason.MODEL_ERROR,
                kind="runtime",
                category="claude_process_boundary",
                message=redact_text(str(exc)),
                infrastructure=True,
            ) from exc
        parsed: ParsedEventStream | None = None
        parse_failure: str | None = None
        if not process.stdout_truncated:
            try:
                parsed = parse_event_stream(
                    process.stdout,
                    requested_model_id=settings.model_id,
                    expected_context_window_tokens=settings.expected_context_window_tokens,
                )
            except EventParseError as exc:
                parse_failure = str(exc)
        failure = _process_failure(
            process,
            parsed,
            parse_failure,
            broker_stats,
            max_budget_usd=settings.max_budget_usd,
        )
        if (
            failure is None
            and parsed is not None
            and len(parsed.tool_names) != broker_stats.tool_calls
        ):
            failure = _termination(
                TerminationReason.RUNTIME_ERROR,
                kind="runtime",
                category="mcp_tool_evidence_mismatch",
                message="Claude tool events differ from private broker accounting",
                infrastructure=True,
            )
        training_transcript: dict[str, object] | None = None
        if failure is None and parsed is not None and settings.capture_training_transcript:
            try:
                messages = normalize_training_messages(
                    process.stdout,
                    system_prompt=_training_system_prompt(),
                    user_prompt=prompt,
                    broker_turns=broker_turns,
                )
                training_transcript = build_teacher_transcript(
                    campaign_role="training",
                    task_id=context.task.id,
                    provider="anthropic-compatible",
                    model_id=settings.model_id,
                    reasoning_effort="max",
                    client_kind="cli",
                    client_name="claude-code",
                    client_version=capabilities.version_output.strip(),
                    harness_identity={
                        "harness": "verigym-claude-mcp-external-agent-bridge-v2",
                        "configuration_fingerprint": settings.configuration_fingerprint,
                        "tools": repository_tool_definitions(dialect="openai"),
                    },
                    messages=messages,
                )
            except TranscriptNormalizationInfrastructureError as exc:
                failure = _termination(
                    TerminationReason.RUNTIME_ERROR,
                    kind="runtime",
                    category="training_transcript_normalization_invalid",
                    message=str(exc),
                    infrastructure=True,
                )
            except (EventParseError, ValueError) as exc:
                failure = _termination(
                    TerminationReason.MODEL_ERROR,
                    kind="model",
                    category="training_transcript_ineligible",
                    message=str(exc),
                    infrastructure=False,
                )
        identity = _identity(settings, capabilities, parsed, broker_stats)
        accounting = _accounting(process, parsed, broker_stats)
        if parsed is not None:
            for event in parsed.events:
                bridge.emit_event(
                    "claude_cli_event_observed",
                    {
                        "sequence": event.sequence,
                        "upstream_type": event.upstream_type,
                        "subtype": event.subtype,
                        "model_id": event.model_id,
                        "tool_names": list(event.tool_names),
                        "thinking_block_present": event.thinking_block_present,
                        "reasoning_content_persisted": False,
                    },
                )
        bridge.emit_event(
            "claude_cli_process_completed",
            {
                "exit_code": process.exit_code,
                "timed_out": process.timed_out,
                "event_count": len(parsed.events) if parsed is not None else 0,
                "tool_call_count": broker_stats.tool_calls,
                "provider_cancelled": process.provider_cancelled,
                "provider_limit_failure": process.provider_limit_failure,
                "observed_provider_billed_tokens": process.observed_provider_billed_tokens,
            },
        )
        bridge.emit_event("claude_cli_identity_observed", identity.model_dump(mode="json"))
        bridge.record_accounting(accounting)
        write_evidence(
            bridge.artifact_root,
            capabilities=capabilities,
            invocation=invocation,
            process=process,
            parsed=parsed,
            broker=broker_stats,
            identity=identity,
            accounting=accounting,
            summary={
                "schema_version": "1.0",
                "integration_track": settings.integration_track,
                "structurally_successful_external_episode": failure is None,
                "candidate_correctness_inferred_from_cli": False,
                "ordinary_hidden_verifier_pending": failure is None,
                "failure_category": failure.failure.category if failure is not None else None,
                "failure_message": failure.failure.message if failure is not None else None,
                "context_window_tokens": (
                    parsed.context_window_tokens if parsed is not None else None
                ),
                "per_response_max_output_tokens": (
                    parsed.per_response_max_output_tokens if parsed is not None else None
                ),
                "internal_turn_limit_configured": False,
                "model_call_limit_configured": False,
                "model_token_limit_configured": True,
                "model_token_limit": settings.max_provider_tokens,
                "model_token_limit_scope": "cache_inclusive_stream_observed",
                "budget_limit_configured": True,
                "budget_limit_usd": settings.max_budget_usd,
                "broker_resource_limits_configured": settings.max_tool_calls is not None,
                "broker_max_tool_calls": settings.max_tool_calls,
                "broker_max_patch_calls": settings.max_patch_calls,
                "broker_max_consecutive_rejected_calls": (settings.max_consecutive_rejected_calls),
                "training_transcript_captured": training_transcript is not None,
            },
            roots_to_redact=(bridge.workspace_root,),
        )
        if training_transcript is not None:
            atomic_json(bridge.artifact_root / "training-transcript.json", training_transcript)
        if failure is not None:
            raise failure
        return FinalSubmissionAction(
            message=(
                "External Claude CLI episode ended; candidate submitted to the ordinary "
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
                    "ordinary_hidden_verifier_pending": False,
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
        ClaudeSettings,
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
            raise RuntimeError("claude-cli-agent has not been started")
        return (
            self._context,
            self._bridge,
            self._executable,
            self._capabilities,
            self._settings,
            self._prompt,
        )


def _bind_prompt_policy(context: AgentContext, settings: ClaudeSettings) -> None:
    policy = context.prompt_policy
    if policy is None or policy.resolver_id != "agent_execution_prompt_policy_v1":
        raise ValueError("Claude CLI harness requires a resolved agent prompt policy")
    if policy.id != settings.prompt_contract_id:
        raise ValueError("Claude CLI prompt contract differs from the resolved policy")
    if (
        policy.agent_version_id != settings.agent_version_id
        or policy.agent_version_hash != settings.agent_version_hash
        or policy.memory_pack_hash is not None
    ):
        raise ValueError("Claude CLI frozen version identity differs from the resolved policy")


def _agent_prompt(context: AgentContext, bridge: ExternalAgentBridge) -> str:
    editable_globs = sorted(bridge.editable_globs)
    repository_prefix_required = bool(editable_globs) and all(
        pattern == "repository" or pattern.startswith("repository/") for pattern in editable_globs
    )
    path_instruction = (
        "This task requires the repository/ prefix: use paths such as "
        "repository/core/decoder.sv, never core/decoder.sv."
        if repository_prefix_required
        else "Retain every directory prefix shown in editable_globs when constructing paths."
    )
    payload = {
        "schema_version": "1.0",
        "task": {
            "title": context.task.title,
            "description": context.task.description,
            "entrypoints": sorted(context.task.workspace.entrypoints),
        },
        "workspace_policy": {
            "editable_globs": editable_globs,
            "readonly_globs": sorted(bridge.readonly_globs),
            "logical_root": "/workspace",
            "tool_path_format": "workspace_relative_with_declared_prefixes",
            "repository_prefix_required": repository_prefix_required,
            "network": "disabled_for_all_workspace_commands",
        },
        "public_test_ids": list(_public_test_ids(context)),
        "instructions": [
            "Solve the task by using only the mcp__verigym__* tools supplied in this session.",
            "Begin by listing and reading visible files; paths are relative to /workspace.",
            path_instruction,
            (
                "Use apply_patch only for paths permitted by editable_globs. Its patch must "
                "use --- a/path and +++ b/path file headers plus numbered "
                "@@ -old,count +new,count @@ hunk headers; never use *** Update File syntax."
            ),
            "Use only relative MCP paths; never send /workspace or another absolute path.",
            "Use run_public_test only with an ID listed in public_test_ids.",
            "Inspect the final diff, then call finish exactly once.",
            (
                "Every non-final response must contain exactly one MCP tool call and no text. "
                "Never emit a standalone plan, progress update, explanation, or narration "
                "between tool calls. Emit final assistant text only after the finish tool result."
            ),
            (
                "Never call apply_patch on any path in readonly_globs. TASK.md and "
                "PUBLIC_TESTS.md are read-only context and must never be edited, even when "
                "the task description mentions them."
            ),
            "Do not access the host cwd, home, credentials, settings, hidden tests, or network.",
            "Do not ask questions; finish after producing one candidate.",
            "VeriGym, not this CLI, freezes and verifies the final candidate.",
        ],
    }
    return (
        '<verigym_external_agent_task schema_version="1.0">\n'
        + json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n</verigym_external_agent_task>\n"
    )


def _training_system_prompt() -> str:
    return (
        "You are a bounded repository repair agent. Every non-final response must contain "
        "exactly one supplied repository function call and no text. Never emit a standalone "
        "plan, progress update, explanation, or narration between tool calls. Emit final "
        "assistant text only after the finish tool result. Never call apply_patch on TASK.md or "
        "PUBLIC_TESTS.md; they are read-only context. Read visible files before editing. "
        "Preserve every workspace path prefix declared by the task. apply_patch requires "
        "---/+++ file headers and numbered @@ hunk headers; *** Update File syntax is invalid. "
        "Use only declared public tests, inspect the candidate diff, then call finish. "
        "Shell, network, hidden assets, and golden repair artifacts are unavailable."
    )


def _public_test_ids(context: AgentContext) -> tuple[str, ...]:
    repository = context.task.metadata.get("repository_repair")
    if repository is None:
        return ()
    if not isinstance(repository, dict):
        raise ValueError("repository task metadata is malformed")
    values = repository.get("public_test_ids")
    if not isinstance(values, list) or not all(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
        for value in values
    ):
        raise ValueError("repository public-test identity is malformed")
    if len(values) != len(set(values)):
        raise ValueError("repository public-test IDs must be unique")
    return tuple(sorted(values))


def _process_failure(
    process: ClaudeProcessResult,
    parsed: ParsedEventStream | None,
    parse_failure: str | None,
    broker: BrokerStats,
    *,
    max_budget_usd: float | None = None,
) -> AgentTerminationError | None:
    if broker.limit_failure is not None:
        return _termination(
            TerminationReason.MODEL_ERROR,
            kind="agent",
            category="broker_resource_limit",
            message=broker.limit_failure,
            infrastructure=False,
        )
    if process.provider_limit_failure is not None:
        return _termination(
            TerminationReason.MODEL_ERROR,
            kind="agent",
            category="provider_resource_limit",
            message=process.provider_limit_failure,
            infrastructure=False,
        )
    if process.stream_monitor_failed:
        return _termination(
            TerminationReason.RUNTIME_ERROR,
            kind="runtime",
            category="provider_usage_monitor",
            message="Claude provider usage monitor failed",
            infrastructure=True,
        )
    if (
        max_budget_usd is not None
        and parsed is not None
        and parsed.cost_usd is not None
        and parsed.cost_usd >= max_budget_usd
    ):
        return _termination(
            TerminationReason.MODEL_ERROR,
            kind="agent",
            category="provider_resource_limit",
            message="claude_provider_budget_limit",
            infrastructure=False,
        )
    if broker.policy_failure is not None:
        return _termination(
            TerminationReason.POLICY_VIOLATION,
            kind="policy",
            category="workspace_policy",
            message=broker.policy_failure,
            infrastructure=False,
        )
    if broker.infrastructure_failure is not None:
        return _termination(
            TerminationReason.RUNTIME_ERROR,
            kind="runtime",
            category="runtime_tool_infrastructure",
            message=broker.infrastructure_failure,
            infrastructure=True,
        )
    if process.timed_out:
        return _termination(
            TerminationReason.MODEL_ERROR,
            kind="model",
            category="agent_timeout",
            message=(
                "Claude agent exhausted its episode deadline after broker activity"
                if broker.tool_calls
                else "Claude agent exhausted its episode deadline before using a broker tool"
            ),
            infrastructure=False,
        )
    if process.stdout_truncated or process.stderr_truncated:
        return _termination(
            TerminationReason.MODEL_ERROR,
            kind="runtime",
            category="output_limit",
            message="Claude CLI evidence stream exceeded the process byte bound",
            infrastructure=True,
        )
    if parse_failure is not None:
        return _termination(
            TerminationReason.MODEL_ERROR,
            kind="runtime",
            category="event_protocol",
            message=parse_failure,
            infrastructure=True,
        )
    if process.exit_code == 0 and parsed is not None and parsed.successful:
        if parsed.input_tokens is None or parsed.output_tokens is None:
            return _termination(
                TerminationReason.RUNTIME_ERROR,
                kind="runtime",
                category="provider_usage_missing",
                message="Claude successful terminal result omitted provider token usage",
                infrastructure=True,
            )
        return None
    text = (process.stderr + " " + (parsed.failure_message or "" if parsed else "")).lower()
    if any(marker in text for marker in ("max budget", "budget exceeded", "budget limit")):
        return _termination(
            TerminationReason.MODEL_ERROR,
            kind="agent",
            category="provider_resource_limit",
            message="claude_provider_budget_limit",
            infrastructure=False,
        )
    if any(marker in text for marker in ("unauthorized", "authentication", "api key", "401")):
        category = "authentication"
    elif any(marker in text for marker in ("rate limit", "too many requests", "429")):
        category = "rate_limit"
    elif any(marker in text for marker in ("overloaded", "529")):
        category = "server_overloaded"
    elif any(marker in text for marker in ("connection", "transport", "network", "502", "503")):
        category = "transport"
    else:
        category = "remote_process_error"
    message = (
        parsed.failure_message
        if parsed is not None and parsed.failure_message
        else redact_text(process.stderr).strip() or "Claude CLI external-agent process failed"
    )
    return _termination(
        TerminationReason.MODEL_ERROR,
        kind="model",
        category=category,
        message=message,
        infrastructure=True,
    )


def _identity(
    settings: ClaudeSettings,
    capabilities: CapabilityReport,
    parsed: ParsedEventStream | None,
    broker: BrokerStats,
) -> ExternalAgentCallIdentity:
    return ExternalAgentCallIdentity(
        adapter_name="claude-cli-agent",
        adapter_version=__version__,
        harness_name="verigym-claude-mcp-external-agent-bridge",
        requested_model_id=settings.model_id,
        observed_model_id=parsed.observed_model_id if parsed is not None else None,
        requested_reasoning_effort=settings.requested_reasoning_effort,
        effective_reasoning_effort=settings.effective_reasoning_effort,
        reasoning_effort_source="verigym_explicit_cli_override",
        inherited_reasoning_effort_allowed=False,
        executable_name=capabilities.executable_name,
        executable_sha256=capabilities.executable_sha256,
        executable_version=capabilities.version_output,
        capability_fingerprint=capabilities.capability_fingerprint,
        configuration_fingerprint=settings.configuration_fingerprint,
        invocation_count=1,
        integration_track="claude_cli_external_agent",
        execution_surface="claude_cli",
        interaction_class="cli_agent_workspace_writing",
        harness_id=("-".join(capabilities.version_output.strip().lower().split()))[:128],
        model_client_kind="cli_agent_mediated",
        agent_harness_kind="claude_cli",
        tool_availability_policy="verigym_mcp_only_no_builtin_tools_v1",
        tool_use_policy="docker_runtime_workspace_tools_v1",
        tool_event_count=broker.tool_calls,
        # The identity schema uses mutually exclusive transport/tool classifications. Every
        # Claude workspace action traverses MCP; broker.json retains the read/write breakdown.
        side_effecting_tool_event_count=0,
        read_only_tool_event_count=0,
        external_network_tool_event_count=0,
        mcp_tool_event_count=broker.tool_calls,
        workspace_write_count=broker.file_writes + broker.patches,
        chat_eval_compatible=False,
        pure_api_model_eval=False,
        direct_api_benchmark=False,
        auth_mode_label=settings.requested_auth_mode,
        requested_auth_mode=settings.requested_auth_mode,
        resolved_auth_mode=settings.resolved_auth_mode,
        auth_semantic_id=settings.auth_semantic_id,
        auth_alias_used=settings.auth_alias_used,
        sandbox_policy="host_control_plane_mcp_only_runtime_tools",
        approval_policy="dontAsk",
        identity_confidence=(
            "observed" if parsed is not None and parsed.observed_model_id else "requested_only"
        ),
        reproducibility_scope="mutable_remote_observation",
    )


def _accounting(
    process: ClaudeProcessResult,
    parsed: ParsedEventStream | None,
    broker: BrokerStats,
) -> ExternalAgentAccounting:
    parsed_input = parsed.input_tokens if parsed is not None else None
    parsed_output = parsed.output_tokens if parsed is not None else None
    input_tokens = _maximum_observed_count(parsed_input, process.observed_provider_input_tokens)
    output_tokens = _maximum_observed_count(parsed_output, process.observed_provider_output_tokens)
    return ExternalAgentAccounting(
        process_wall_time_s=process.duration_s,
        cli_event_count=len(parsed.events) if parsed is not None else 0,
        external_tool_call_count=broker.tool_calls,
        external_command_count=broker.command_calls,
        public_test_invocation_count=broker.public_test_calls,
        external_file_read_count=broker.file_reads,
        external_file_write_count=broker.file_writes,
        external_patch_count=broker.patches,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=(
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
        cost=parsed.cost_usd if parsed is not None else None,
        currency=("USD" if parsed is not None and parsed.cost_usd is not None else None),
    )


def _maximum_observed_count(terminal: int | None, observed: int | None) -> int | None:
    if terminal is None:
        return observed
    if observed is None:
        return terminal
    return max(terminal, observed)


def _termination(
    reason: TerminationReason,
    *,
    kind: str,
    category: str,
    message: str,
    infrastructure: bool,
) -> AgentTerminationError:
    valid_kind = kind if kind in {"agent", "model", "policy", "runtime"} else "agent"
    return AgentTerminationError(
        reason,
        EpisodeFailure(
            kind=valid_kind,  # type: ignore[arg-type]
            category=category,
            message=redact_text(message)[:2000],
            infrastructure=infrastructure,
        ),
    )


__all__ = ["ClaudeCliAgentAdapter"]
