"""Scoring-only Codex CLI adapter for bounded RTL AgentEval episodes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from verigym.core.repository_tool_broker import (
    RepositoryToolBroker,
    RepositoryToolBrokerLimits,
    RepositoryToolBrokerStats,
)
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
from verigym.schemas.action_protocol import RepositoryActionProtocolSpec

from .agenteval_config import (
    AGENTEVAL_PROMPT_INSTRUCTIONS,
    CodexAgentEvalSettings,
    agenteval_settings,
)
from .agenteval_invocation import (
    build_agenteval_arguments,
    sanitized_agenteval_invocation,
)
from .artifacts import update_summary
from .capabilities import CapabilityReport, runtime_capabilities
from .events import (
    EventParseError,
    ParsedEventStream,
    parse_event_stream,
    parse_partial_event_stream,
    validate_scoring_mcp_stream,
)
from .process import (
    CodexCliProcessRunner,
    CodexProcessError,
    CodexProcessResult,
    ExecutableIdentity,
)
from .util import atomic_json, redact_text

_POLICY_FAILURE_SUBCATEGORIES = frozenset(
    {
        "workspace_access_policy",
        "workspace_patch_policy",
        "workspace_path_policy",
        "workspace_sandbox_policy",
    }
)
_INFRASTRUCTURE_FAILURE_SUBCATEGORIES = frozenset(
    {
        "broker_dispatch_internal_error",
        "agent_feedback_dispatch_internal",
        "agent_feedback_infrastructure",
        "agent_worker_configuration",
        "agent_worker_execution",
        "agent_worker_identity",
        "agent_worker_infrastructure",
        "agent_worker_response",
        "agent_worker_scheduler",
        "agent_worker_start",
        "agent_worker_timeout",
        "mcp_service_rejected",
        "public_test_control_plane",
        "training_capture_limit",
        "training_observation_internal_error",
        "workspace_tool_internal_error",
    }
)
_ALLOWLISTED_TOOL_NAMES = frozenset(
    {
        "list_files",
        "read_file",
        "apply_patch",
        "run_public_test",
        "inspect_diff",
        "finish",
    }
)
_PATH_VIOLATION_CATEGORIES = frozenset(
    {
        "absolute",
        "traversal",
        "outside_editable",
        "readonly",
        "symlink",
        "hardlink",
        "hidden_or_protected",
        "unspecified",
    }
)


class CodexCliAgentEvalAdapter(AgentAdapter):
    """Run one gpt-5.4/xhigh MCP-only scoring episode without transcript capture."""

    requires_model = False
    action_protocol_spec = RepositoryActionProtocolSpec(
        prompt_contract_id="repository_action_v2_prompt_v4",
        state_machine_id="repository_action_state_machine_v3",
    )
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="repository_action_v2_prompt_v4",
        prompt_contract_version="4.0.0",
        task_context_policy="revision_bound_agent_feedback_v1",
        base_instruction_policy="generated_repository_action_registry_v4",
        content_visibility_policy="visible_assets_and_revision_bound_feedback_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="codex-cli-agenteval-agent",
        version="5.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "agent_eval",
            "external_coding_agent",
            "machine_readable_events",
            "runtime_mcp_tools",
            "repository_action.v2",
            "scoring_only",
            "single_external_episode",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._executable: ExecutableIdentity | None = None
        self._capabilities: CapabilityReport | None = None
        self._settings: CodexAgentEvalSettings | None = None
        self._prompt: str | None = None
        self._launched = False
        self._artifact_root: Path | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None or bridge.isolation_level != "docker_standard":
            raise ValueError("Codex AgentEval requires the Docker runtime bridge")
        if context.agent_feedback_contract is None:
            raise ValueError("Codex AgentEval requires a resolved feedback contract")
        if (
            context.action_protocol is None
            or context.action_protocol.protocol_id != "repository_action.v2"
            or context.action_protocol.state_machine_id != "repository_action_state_machine_v3"
        ):
            raise ValueError("Codex AgentEval requires the frozen repository action protocol")
        if (
            context.prompt_policy is None
            or context.prompt_policy.id != "repository_action_v2_prompt_v4"
        ):
            raise ValueError("Codex AgentEval prompt contract is not frozen")
        executable, capabilities = runtime_capabilities()
        settings = agenteval_settings(
            context.agent_options,
            capabilities,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        prompt = validate_prompt_text(
            _agenteval_prompt(context, bridge, settings),
            context.prompt_policy,
        )
        self._context = context
        self._bridge = bridge
        self._executable = executable
        self._capabilities = capabilities
        self._settings = settings
        self._prompt = prompt
        self._launched = False
        self._artifact_root = bridge.artifact_root

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._launched:
            raise _termination("multiple_external_episodes", "AgentEval launched more than once")
        self._launched = True
        context, bridge, executable, capabilities, settings, prompt = self._configured()
        feedback_contract = context.agent_feedback_contract
        if feedback_contract is None:
            raise RuntimeError("Codex AgentEval feedback contract disappeared after start")
        broker_root = _configured_broker_root()
        try:
            with tempfile.TemporaryDirectory(prefix="codex-agenteval-", dir=broker_root) as raw:
                control = Path(raw)
                cwd = control / "cwd"
                cwd.mkdir(mode=0o700)
                broker = RepositoryToolBroker(
                    bridge=bridge,
                    socket_path=control / "b" / "mcp.sock",
                    public_test_ids=tuple(feedback_contract.public_test_ids),
                    agent_feedback_contract=feedback_contract,
                    limits=RepositoryToolBrokerLimits(
                        max_tool_calls=settings.max_tool_calls,
                        max_patch_calls=settings.max_patch_calls,
                        max_consecutive_rejected_calls=(settings.max_consecutive_rejected_calls),
                    ),
                    wall_time_s=settings.execution.effective_process_timeout_s,
                )
                arguments = build_agenteval_arguments(
                    capabilities,
                    settings,
                    socket_path=broker.socket_path,
                )
                invocation = sanitized_agenteval_invocation(arguments, settings, capabilities)
                runner = CodexCliProcessRunner(
                    executable,
                    auth_mode=settings.execution.resolved_auth_mode,
                    credential_env=settings.execution.credential_env,
                    max_output_bytes=settings.execution.max_output_bytes,
                    allow_proxy_environment=settings.execution.allow_proxy_environment,
                )
                broker.start()
                try:
                    process = runner.run(
                        arguments,
                        cwd=cwd,
                        timeout_s=settings.execution.effective_process_timeout_s,
                        stdin_bytes=prompt.encode("utf-8"),
                        cancellation_event=broker.cancellation_event,
                    )
                finally:
                    broker.stop()
                broker_stats = broker.stats()
        except CodexProcessError as exc:
            raise _termination(
                "codex_process_boundary", redact_text(str(exc)), infrastructure=True
            ) from exc

        parsed, parse_error = _parse_returned_event_stream(process.stdout)
        process_failure = _preparse_process_failure(process, broker_stats)
        scoring_failure: AgentTerminationError | None = process_failure
        if scoring_failure is None:
            scoring_failure = _postparse_scoring_failure(
                process,
                broker_stats,
                parsed,
                parse_error=parse_error,
                expected_model_id=settings.execution.model_id,
            )

        identity = _identity(settings, capabilities, parsed, broker_stats)
        accounting = _accounting(process, broker_stats, parsed)
        bridge.emit_event("codex_cli_identity_observed", identity.model_dump(mode="json"))
        bridge.record_accounting(accounting)
        _write_scoring_evidence(
            bridge.artifact_root,
            capabilities=capabilities,
            invocation=invocation,
            process=process,
            broker=broker_stats,
            identity=identity,
            accounting=accounting,
            parsed=parsed,
            failure_category=(
                scoring_failure.failure.category if scoring_failure is not None else None
            ),
        )
        if scoring_failure is not None:
            raise scoring_failure
        return FinalSubmissionAction(
            message="Codex AgentEval finished; submit the broker-owned candidate to VeriGym."
        )

    def finish(self, result: EpisodeResult) -> None:
        if self._artifact_root is not None and (self._artifact_root / "summary.json").is_file():
            update_summary(
                self._artifact_root,
                {
                    "verigym_run_id": result.run_id,
                    "ordinary_verifier_resolved": result.resolved,
                    "ordinary_termination_reason": result.termination_reason,
                },
            )

    def _configured(
        self,
    ) -> tuple[
        AgentContext,
        ExternalAgentBridge,
        ExecutableIdentity,
        CapabilityReport,
        CodexAgentEvalSettings,
        str,
    ]:
        values = (
            self._context,
            self._bridge,
            self._executable,
            self._capabilities,
            self._settings,
            self._prompt,
        )
        if any(value is None for value in values):
            raise RuntimeError("Codex AgentEval has not been started")
        return values  # type: ignore[return-value]


def _agenteval_prompt(
    context: AgentContext,
    bridge: ExternalAgentBridge,
    settings: CodexAgentEvalSettings,
) -> str:
    contract = context.agent_feedback_contract
    assert contract is not None
    instructions = list(AGENTEVAL_PROMPT_INSTRUCTIONS)
    instructions.append(
        "apply_patch requires --- a/path and +++ b/path headers plus numbered @@ hunks; never "
        "use *** Update File syntax."
    )
    instructions.append("Every successful patch invalidates prior compile, PPA, and diff evidence.")
    instructions.append(
        "Use each repository-relative editable_globs value exactly as written; do not add or "
        "remove a repository/ prefix."
    )
    if contract.compile_test_id is not None:
        instructions.append(
            "Run compile for the current revision and require it to pass before finish."
        )
    if contract.ppa_enabled:
        instructions.append(
            "After compile passes for the current revision, call ppa at least once before finish."
        )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "agent_version_id": settings_version_id(),
        "task": {
            "id": context.task.id,
            "title": context.task.title,
            "description": context.task.description,
            "entrypoints": sorted(context.task.workspace.entrypoints),
        },
        "workspace_policy": {
            "editable_globs": sorted(bridge.editable_globs),
            "readonly_globs": sorted(bridge.readonly_globs),
            "path_format": "relative_only",
            "editable_paths_must_be_copied_verbatim": True,
        },
        "budgets": {
            "task_wall_time_s": int(settings.execution.task_wall_time_s),
            "process_wall_time_s": int(settings.execution.effective_process_timeout_s),
            "max_tool_calls": settings.max_tool_calls,
            "max_patch_calls": settings.max_patch_calls,
            "max_consecutive_rejected_calls": settings.max_consecutive_rejected_calls,
            "finalization_reserve_s": 60,
        },
        "agent_feedback_contract": contract.model_dump(mode="json"),
        "instructions": instructions,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def settings_version_id() -> str:
    from .agenteval_config import AGENTEVAL_AGENT_VERSION_ID

    return AGENTEVAL_AGENT_VERSION_ID


def _parse_returned_event_stream(
    stdout: str,
) -> tuple[ParsedEventStream, str | None]:
    """Parse a returned process before classifying broker or process failures."""

    try:
        return parse_event_stream(stdout), None
    except EventParseError:
        return parse_partial_event_stream(stdout), "event_stream_malformed_or_incomplete"


def _postparse_scoring_failure(
    process: CodexProcessResult,
    broker: RepositoryToolBrokerStats,
    parsed: ParsedEventStream,
    *,
    parse_error: str | None,
    expected_model_id: str,
) -> AgentTerminationError | None:
    if parsed.observed_model_id is not None and parsed.observed_model_id != expected_model_id:
        return _termination(
            "model_identity_drift",
            "Codex AgentEval observed a different model identity",
            infrastructure=True,
            kind="runtime",
            reason=TerminationReason.RUNTIME_ERROR,
        )
    if parse_error is not None or not parsed.canonical_stream_complete:
        return _termination(
            "scoring_event_ineligible",
            "Codex AgentEval returned an incomplete machine-event stream",
        )
    try:
        completed_tools = validate_scoring_mcp_stream(process.stdout)
    except (EventParseError, ValueError):
        return _termination(
            "scoring_event_ineligible",
            "Codex AgentEval returned a non-canonical MCP event stream",
        )
    canonical_finish = bool(completed_tools) and completed_tools[-1] == "finish"
    if (
        process.exit_code != 0
        or not parsed.terminal_event_seen
        or parsed.error_messages
        or len(completed_tools) != broker.tool_calls
        or not broker.finished
        or broker.finish_calls != 1
        or not canonical_finish
    ):
        return _termination(
            "scoring_event_ineligible",
            "Codex AgentEval did not finish through canonical MCP",
        )
    if parsed.input_tokens is None or parsed.output_tokens is None:
        return _termination(
            "provider_usage_incomplete",
            "Codex AgentEval terminal event omitted complete provider usage",
        )
    return None


def _identity(
    settings: CodexAgentEvalSettings,
    capabilities: CapabilityReport,
    parsed: ParsedEventStream | None,
    broker: RepositoryToolBrokerStats,
) -> ExternalAgentCallIdentity:
    calls = broker.tool_calls
    complete_terminal = bool(
        parsed is not None and parsed.canonical_stream_complete and parsed.terminal_event_seen
    )
    observed_model_id = (
        parsed.observed_model_id if complete_terminal and parsed is not None else None
    )
    return ExternalAgentCallIdentity(
        adapter_name="codex-cli-agenteval-agent",
        adapter_version="5.0.0",
        harness_name="verigym-codex-agenteval-scoring",
        requested_model_id="gpt-5.4",
        observed_model_id=observed_model_id,
        requested_reasoning_effort="xhigh",
        effective_reasoning_effort="xhigh",
        reasoning_effort_source="verigym_explicit_cli_override",
        inherited_reasoning_effort_allowed=False,
        executable_name=capabilities.executable_name,
        executable_sha256=capabilities.executable_sha256,
        executable_version=capabilities.version_output,
        capability_fingerprint=capabilities.capability_fingerprint,
        configuration_fingerprint=settings.execution.configuration_fingerprint,
        invocation_count=1,
        integration_track="codex_cli_agenteval_scoring",
        execution_surface="codex_cli",
        interaction_class="cli_agent_mcp_repository_scoring",
        harness_id=settings.agent_version_id,
        agent_version_hash=settings.agent_version_hash,
        prompt_contract_hash=settings.prompt_hash,
        tool_policy_fingerprint=settings.tool_policy_fingerprint,
        model_client_kind="cli_agent_mediated",
        agent_harness_kind="codex_cli",
        tool_availability_policy="verigym_required_allowlisted_mcp_only_v2",
        tool_use_policy="repository_action_state_machine_v3",
        tool_event_count=calls,
        side_effecting_tool_event_count=0,
        read_only_tool_event_count=0,
        external_network_tool_event_count=0,
        mcp_tool_event_count=calls,
        workspace_write_count=broker.patches,
        chat_eval_compatible=False,
        pure_api_model_eval=False,
        direct_api_benchmark=False,
        auth_mode_label=settings.execution.requested_auth_mode,
        requested_auth_mode=settings.execution.requested_auth_mode,
        resolved_auth_mode=settings.execution.resolved_auth_mode,
        auth_semantic_id=settings.execution.auth_semantic_id,
        auth_alias_used=settings.execution.auth_alias_used,
        sandbox_policy="read-only_mcp-only",
        approval_policy="never",
        identity_confidence=("observed" if observed_model_id is not None else "requested_only"),
        reproducibility_scope="mutable_remote_observation",
    )


def _accounting(
    process: CodexProcessResult,
    broker: RepositoryToolBrokerStats,
    parsed: ParsedEventStream | None,
) -> ExternalAgentAccounting:
    usage_complete = bool(
        parsed is not None
        and parsed.canonical_stream_complete
        and parsed.terminal_event_seen
        and parsed.input_tokens is not None
        and parsed.output_tokens is not None
    )
    return ExternalAgentAccounting(
        process_wall_time_s=process.duration_s,
        cli_event_count=len(parsed.events) if parsed is not None else 0,
        model_call_count=parsed.model_call_count if parsed is not None else None,
        external_tool_call_count=broker.tool_calls,
        external_command_count=0,
        public_test_invocation_count=broker.public_test_calls,
        external_file_read_count=broker.file_reads,
        external_file_write_count=0,
        external_patch_count=broker.patches,
        input_tokens=parsed.input_tokens if usage_complete and parsed is not None else None,
        output_tokens=parsed.output_tokens if usage_complete and parsed is not None else None,
        total_tokens=parsed.total_tokens if usage_complete and parsed is not None else None,
        usage_complete=usage_complete,
    )


def _write_scoring_evidence(
    root: Path,
    *,
    capabilities: CapabilityReport,
    invocation: dict[str, object],
    process: CodexProcessResult,
    broker: RepositoryToolBrokerStats,
    identity: ExternalAgentCallIdentity | None,
    accounting: ExternalAgentAccounting,
    parsed: ParsedEventStream | None,
    failure_category: str | None = None,
) -> None:
    atomic_json(root / "capabilities.json", capabilities.safe_dict())
    atomic_json(root / "invocation.json", invocation)
    atomic_json(
        root / "process.json",
        {
            "exit_code": process.exit_code,
            "duration_s": process.duration_s,
            "timed_out": process.timed_out,
            "broker_cancelled": process.broker_cancelled,
            "stdout_truncated": process.stdout_truncated,
            "stderr_truncated": process.stderr_truncated,
            "process_group_cleaned": process.process_group_cleaned,
            "stdout_sha256": hashlib.sha256(process.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(process.stderr.encode()).hexdigest(),
            "raw_output_persisted": False,
            "message_content_persisted": False,
            "reasoning_content_persisted": False,
        },
    )
    atomic_json(root / "broker.json", _safe_broker_stats(broker))
    atomic_json(root / "accounting.json", accounting.model_dump(mode="json"))
    atomic_json(
        root / "provider-usage.json",
        {
            "schema_version": "1.0",
            "usage_complete": accounting.usage_complete is True,
            "input_tokens": accounting.input_tokens,
            "output_tokens": accounting.output_tokens,
            "total_tokens": accounting.total_tokens,
            "cached_input_tokens": (
                parsed.cached_input_tokens
                if accounting.usage_complete is True and parsed is not None
                else None
            ),
            "cost_usd": None,
            "currency": None,
        },
    )
    if identity is not None:
        atomic_json(root / "identity.json", identity.model_dump(mode="json"))
    atomic_json(
        root / "summary.json",
        {
            "schema_version": "1.0",
            "integration_track": "codex_cli_agenteval_scoring",
            "agent_version_id": settings_version_id(),
            "training_mode": False,
            "training_transcript_captured": False,
            "raw_event_stream_persisted": False,
            "private_reasoning_persisted": False,
            "provider_observation_recorded": identity is not None,
            "failure_category": failure_category,
            "failure_subcategory": (
                _bounded_policy_failure_subcategory(broker)
                if broker.policy_failure is not None
                else _bounded_infrastructure_failure_subcategory(broker)
            ),
        },
    )


def _safe_broker_stats(stats: RepositoryToolBrokerStats) -> dict[str, object]:
    return {
        "tool_calls": stats.tool_calls,
        "public_test_calls": stats.public_test_calls,
        "file_reads": stats.file_reads,
        "patches": stats.patches,
        "diff_inspections": stats.diff_inspections,
        "finish_calls": stats.finish_calls,
        "rejected_calls": stats.rejected_calls,
        "finished": stats.finished,
        "policy_failure": stats.policy_failure is not None,
        "infrastructure_failure": stats.infrastructure_failure is not None,
        "policy_failure_subcategory": _bounded_policy_failure_subcategory(stats),
        "infrastructure_failure_subcategory": _bounded_infrastructure_failure_subcategory(stats),
        "limit_failure": stats.limit_failure,
        "maximum_consecutive_rejected_calls": stats.maximum_consecutive_rejected_calls,
        "max_tool_calls": stats.max_tool_calls,
        "max_patch_calls": stats.max_patch_calls,
        "max_consecutive_rejected_calls": stats.max_consecutive_rejected_calls,
        "wall_time_s": stats.wall_time_s,
        "elapsed_wall_time_s": stats.elapsed_wall_time_s,
        "remaining_wall_time_s": stats.remaining_wall_time_s,
        "terminal_tool_name": _bounded_terminal_tool_name(stats),
        "terminal_path_category": _bounded_terminal_path_category(stats),
    }


def _configured_broker_root() -> Path:
    raw = os.environ.get("VERIGYM_CODEX_BROKER_ROOT")
    if not raw:
        raise CodexProcessError("VERIGYM_CODEX_BROKER_ROOT is required")
    path = Path(raw)
    if path.is_symlink():
        raise CodexProcessError("Codex broker root cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or len(os.fsencode(resolved)) > 72:
        raise CodexProcessError("Codex broker root must be a short real directory")
    return resolved


def _preparse_process_failure(
    process: CodexProcessResult,
    broker: RepositoryToolBrokerStats,
) -> AgentTerminationError | None:
    if broker.limit_failure is not None:
        return _termination("broker_resource_limit", broker.limit_failure, kind="agent")
    if broker.policy_failure is not None:
        return _termination(
            "workspace_policy",
            "repository broker reported a terminal workspace policy failure",
            kind="policy",
            reason=TerminationReason.POLICY_VIOLATION,
            protocol_error_subcategory=_bounded_policy_failure_subcategory(broker),
        )
    if broker.infrastructure_failure is not None:
        return _termination(
            "runtime_tool_infrastructure",
            "repository broker reported a terminal tool infrastructure failure",
            infrastructure=True,
            kind="runtime",
            reason=TerminationReason.RUNTIME_ERROR,
            protocol_error_subcategory=_bounded_infrastructure_failure_subcategory(broker),
        )
    if process.timed_out:
        return _termination("agent_timeout", "Codex AgentEval exhausted its episode deadline")
    if process.stdout_truncated or process.stderr_truncated:
        return _termination(
            "output_limit",
            "Codex AgentEval evidence stream exceeded the process byte bound",
            infrastructure=True,
            kind="runtime",
            reason=TerminationReason.RUNTIME_ERROR,
        )
    return None


def _bounded_policy_failure_subcategory(broker: RepositoryToolBrokerStats) -> str | None:
    if broker.policy_failure is None:
        return None
    if broker.policy_failure_subcategory in _POLICY_FAILURE_SUBCATEGORIES:
        return broker.policy_failure_subcategory
    return "workspace_policy_unspecified"


def _bounded_infrastructure_failure_subcategory(
    broker: RepositoryToolBrokerStats,
) -> str | None:
    if broker.infrastructure_failure is None:
        return None
    if broker.infrastructure_failure_subcategory in _INFRASTRUCTURE_FAILURE_SUBCATEGORIES:
        return broker.infrastructure_failure_subcategory
    return "tool_infrastructure_unspecified"


def _bounded_terminal_tool_name(broker: RepositoryToolBrokerStats) -> str | None:
    if broker.terminal_tool_name in _ALLOWLISTED_TOOL_NAMES:
        return broker.terminal_tool_name
    return None


def _bounded_terminal_path_category(broker: RepositoryToolBrokerStats) -> str | None:
    if broker.terminal_path_category in _PATH_VIOLATION_CATEGORIES:
        return broker.terminal_path_category
    return None


def _termination(
    category: str,
    message: str,
    *,
    infrastructure: bool = False,
    kind: Literal["agent", "model", "policy", "runtime"] = "model",
    reason: TerminationReason = TerminationReason.MODEL_ERROR,
    protocol_error_subcategory: str | None = None,
) -> AgentTerminationError:
    return AgentTerminationError(
        reason,
        EpisodeFailure(
            kind=kind,
            category=category,
            message=redact_text(message)[:2000],
            infrastructure=infrastructure,
            protocol_error_subcategory=protocol_error_subcategory,
        ),
    )


__all__ = ["CodexCliAgentEvalAdapter"]
