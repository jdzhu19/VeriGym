"""MCP-only Codex CLI teacher for verified training trajectories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from verigym.core.repository_tool_broker import (
    RepositoryToolBroker,
    RepositoryToolBrokerLimits,
    RepositoryToolBrokerStats,
)
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
from .artifacts import update_summary
from .capabilities import CapabilityReport, runtime_capabilities
from .events import (
    EventParseError,
    ParsedEventStream,
    normalize_training_messages,
    parse_event_stream,
)
from .process import (
    CodexCliProcessRunner,
    CodexProcessError,
    CodexProcessResult,
    ExecutableIdentity,
)
from .teacher_config import CodexTeacherSettings, teacher_settings
from .teacher_invocation import build_teacher_arguments, sanitized_teacher_invocation
from .util import atomic_json, redact_text

_ACTIVE_TIMEOUT_MIN_TOOL_CALLS = 8


class CodexCliMcpTeacherAdapter(AgentAdapter):
    """Collect one strict gpt-5.4/xhigh repository demonstration."""

    requires_model = False
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="codex_cli_mcp_repository_task_context_v1",
        prompt_contract_version="1.0.0",
        task_context_policy="repository_visible_task_context_v1",
        base_instruction_policy="codex_cli_verigym_mcp_repository_teacher_v1",
        content_visibility_policy="public_task_context_and_mcp_workspace_only_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="codex-cli-mcp-teacher",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "external_coding_agent",
            "machine_readable_events",
            "runtime_mcp_tools",
            "training_transcript_capture",
            "single_external_episode",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._executable: ExecutableIdentity | None = None
        self._capabilities: CapabilityReport | None = None
        self._settings: CodexTeacherSettings | None = None
        self._prompt: str | None = None
        self._launched = False
        self._artifact_root: Path | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None or bridge.isolation_level != "docker_standard":
            raise ValueError("Codex MCP teacher requires the Docker runtime bridge")
        executable, capabilities = runtime_capabilities()
        settings = teacher_settings(
            context.agent_options,
            capabilities,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        if context.prompt_policy is None or context.prompt_policy.id != (
            self.prompt_policy_spec.prompt_contract_id
        ):
            raise ValueError("Codex MCP teacher prompt contract is not frozen")
        prompt = validate_prompt_text(_teacher_prompt(context, bridge), context.prompt_policy)
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
            raise _termination("multiple_external_episodes", "teacher launched more than once")
        self._launched = True
        context, bridge, executable, capabilities, settings, prompt = self._configured()
        broker_root = _configured_broker_root()
        process: CodexProcessResult
        try:
            with tempfile.TemporaryDirectory(prefix="codex-mcp-", dir=broker_root) as raw:
                control = Path(raw)
                cwd = control / "cwd"
                cwd.mkdir(mode=0o700)
                broker = RepositoryToolBroker(
                    bridge=bridge,
                    socket_path=control / "b" / "mcp.sock",
                    public_test_ids=_public_test_ids(context),
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
                arguments = build_teacher_arguments(
                    capabilities,
                    settings,
                    socket_path=broker.socket_path,
                )
                invocation = sanitized_teacher_invocation(arguments, settings, capabilities)
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
        process_failure = _preparse_process_failure(process, broker_stats)
        if process_failure is not None:
            raise process_failure
        try:
            parsed = parse_event_stream(process.stdout)
        except (EventParseError, ValueError) as exc:
            raise _termination("training_transcript_ineligible", str(exc)) from exc
        usage_failure = _provider_usage_failure(parsed)
        if usage_failure is not None:
            raise usage_failure
        try:
            messages = normalize_training_messages(
                process.stdout,
                system_prompt=_training_system_prompt(),
                user_prompt=prompt,
            )
            normalized_tool_calls = sum(
                len(message.tool_calls or []) for message in messages if message.role == "assistant"
            )
            if (
                process.exit_code != 0
                or process.timed_out
                or not parsed.terminal_event_seen
                or parsed.error_messages
                or normalized_tool_calls != broker_stats.tool_calls
                or not broker_stats.finished
            ):
                raise EventParseError("Codex teacher episode did not finish through canonical MCP")
            transcript = build_teacher_transcript(
                campaign_role="training",
                task_id=context.task.id,
                provider="openai",
                model_id="gpt-5.4",
                reasoning_effort="xhigh",
                client_kind="cli",
                client_name="codex-cli",
                client_version=capabilities.version_output.strip(),
                harness_identity={
                    "harness": "verigym-codex-required-mcp-teacher-v1",
                    "configuration_fingerprint": settings.execution.configuration_fingerprint,
                    "tools": repository_tool_definitions(dialect="openai"),
                },
                messages=messages,
            )
        except (EventParseError, ValueError) as exc:
            raise _termination("training_transcript_ineligible", str(exc)) from exc
        identity = _identity(settings, capabilities, parsed, broker_stats)
        accounting = ExternalAgentAccounting(
            process_wall_time_s=process.duration_s,
            cli_event_count=len(parsed.events),
            external_tool_call_count=broker_stats.tool_calls,
            external_command_count=0,
            public_test_invocation_count=broker_stats.public_test_calls,
            external_file_read_count=broker_stats.file_reads,
            external_file_write_count=0,
            external_patch_count=broker_stats.patches,
            input_tokens=parsed.input_tokens,
            output_tokens=parsed.output_tokens,
            total_tokens=parsed.total_tokens,
        )
        bridge.emit_event("codex_cli_identity_observed", identity.model_dump(mode="json"))
        bridge.record_accounting(accounting)
        _write_content_free_evidence(
            bridge.artifact_root,
            capabilities=capabilities,
            invocation=invocation,
            process=process,
            event_summaries=[event.safe_dict() for event in parsed.events],
            broker=broker_stats.__dict__,
            identity=identity.model_dump(mode="json"),
            accounting=accounting.model_dump(mode="json"),
            provider_usage={
                "schema_version": "1.0",
                "usage_complete": True,
                "usage_missing": False,
                "input_tokens": parsed.input_tokens,
                "output_tokens": parsed.output_tokens,
                "total_tokens": parsed.total_tokens,
                "cached_input_tokens": parsed.cached_input_tokens,
                "cache_usage_reported": parsed.cached_input_tokens is not None,
                "cost_usd": None,
                "currency": None,
                "provider_report_scope": "codex_cli_terminal_event",
            },
            transcript=transcript,
        )
        return FinalSubmissionAction(
            message="Codex MCP teacher finished; submit the broker-owned candidate to VeriGym."
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
        CodexTeacherSettings,
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
            raise RuntimeError("Codex MCP teacher has not been started")
        return values  # type: ignore[return-value]


def _identity(
    settings: CodexTeacherSettings,
    capabilities: CapabilityReport,
    parsed: ParsedEventStream,
    broker: RepositoryToolBrokerStats,
) -> ExternalAgentCallIdentity:
    observed = parsed.observed_model_id
    calls = broker.tool_calls
    return ExternalAgentCallIdentity(
        adapter_name="codex-cli-mcp-teacher",
        adapter_version=__version__,
        harness_name="verigym-codex-required-mcp-teacher",
        requested_model_id="gpt-5.4",
        observed_model_id=observed,
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
        integration_track="codex_cli_external_agent",
        execution_surface="codex_cli",
        interaction_class="cli_agent_workspace_writing",
        harness_id="verigym-codex-required-mcp-teacher-v1",
        model_client_kind="cli_agent_mediated",
        agent_harness_kind="codex_cli",
        tool_availability_policy="verigym_required_allowlisted_mcp_only_v1",
        tool_use_policy="repository_action_state_machine_v2",
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
        identity_confidence="observed" if observed else "requested_only",
        reproducibility_scope="mutable_remote_observation",
    )


def _teacher_prompt(context: AgentContext, bridge: ExternalAgentBridge) -> str:
    payload = {
        "schema_version": "1.0",
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
        },
        "public_test_ids": list(_public_test_ids(context)),
        "instructions": [
            "Use only the VeriGym MCP repository tools.",
            "Use exactly one MCP tool per turn and no built-in tools.",
            (
                "Read visible files before editing. apply_patch requires --- a/path and "
                "+++ b/path file headers plus numbered @@ -old,count +new,count @@ hunk "
                "headers; never use *** Update File syntax."
            ),
            "Run a declared public test when available.",
            "Inspect the diff, then call finish exactly once.",
            "Do not access shell, network, host files, hidden assets, or golden repair artifacts.",
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _training_system_prompt() -> str:
    return (
        "You are a bounded repository repair agent. Use exactly one supplied repository "
        "function per turn and do not mix prose with a tool call. Read visible files before "
        "editing. apply_patch requires ---/+++ file headers and numbered @@ hunk headers; "
        "*** Update File syntax is invalid. Use only declared public tests, inspect the "
        "candidate diff, then call finish. "
        "Shell, network, hidden assets, and golden repair artifacts are unavailable."
    )


def _public_test_ids(context: AgentContext) -> tuple[str, ...]:
    repository = context.task.metadata.get("repository_repair")
    values = repository.get("public_test_ids") if isinstance(repository, dict) else []
    if not isinstance(values, list) or not all(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
        for value in values
    ):
        raise ValueError("repository public-test identity is malformed")
    return tuple(sorted(set(values)))


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


def _write_content_free_evidence(
    root: Path,
    *,
    capabilities: CapabilityReport,
    invocation: dict[str, object],
    process: CodexProcessResult,
    event_summaries: list[dict[str, object]],
    broker: dict[str, object],
    identity: dict[str, object],
    accounting: dict[str, object],
    provider_usage: dict[str, object],
    transcript: dict[str, object],
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
            "stdout_sha256": hashlib.sha256(process.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(process.stderr.encode()).hexdigest(),
            "raw_output_persisted": False,
            "message_content_persisted": False,
            "reasoning_content_persisted": False,
        },
    )
    atomic_json(root / "events.json", {"events": event_summaries})
    atomic_json(root / "broker.json", broker)
    atomic_json(root / "identity.json", identity)
    atomic_json(root / "accounting.json", accounting)
    atomic_json(root / "provider-usage.json", provider_usage)
    atomic_json(root / "training-transcript.json", transcript)
    atomic_json(
        root / "summary.json",
        {
            "schema_version": "1.0",
            "integration_track": "codex_cli_mcp_teacher",
            "training_transcript_captured": True,
            "ordinary_hidden_verifier_pending": True,
            "private_reasoning_persisted": False,
        },
    )


def _termination(
    category: str,
    message: str,
    *,
    infrastructure: bool = False,
    kind: Literal["agent", "model", "policy", "runtime"] = "model",
    reason: TerminationReason = TerminationReason.MODEL_ERROR,
) -> AgentTerminationError:
    return AgentTerminationError(
        reason,
        EpisodeFailure(
            kind=kind,
            category=category,
            message=redact_text(message)[:2000],
            infrastructure=infrastructure,
        ),
    )


def _preparse_process_failure(
    process: CodexProcessResult,
    broker: RepositoryToolBrokerStats,
) -> AgentTerminationError | None:
    if broker.limit_failure is not None:
        return _termination(
            "broker_resource_limit",
            broker.limit_failure,
            kind="agent",
        )
    if broker.policy_failure is not None:
        return _termination(
            "workspace_policy",
            broker.policy_failure,
            kind="policy",
            reason=TerminationReason.POLICY_VIOLATION,
        )
    if broker.infrastructure_failure is not None:
        return _termination(
            "runtime_tool_infrastructure",
            broker.infrastructure_failure,
            infrastructure=True,
            kind="runtime",
            reason=TerminationReason.RUNTIME_ERROR,
        )
    if process.timed_out:
        active_agent_timeout = broker.tool_calls >= _ACTIVE_TIMEOUT_MIN_TOOL_CALLS
        return _termination(
            "agent_timeout" if active_agent_timeout else "timeout",
            (
                "Codex agent exhausted its episode deadline after sustained broker activity"
                if active_agent_timeout
                else "Codex CLI MCP teacher process timed out"
            ),
            infrastructure=not active_agent_timeout,
            kind="model" if active_agent_timeout else "runtime",
        )
    if process.stdout_truncated or process.stderr_truncated:
        return _termination(
            "output_limit",
            "Codex CLI MCP teacher evidence stream exceeded the process byte bound",
            infrastructure=True,
            kind="runtime",
        )
    return None


def _provider_usage_failure(parsed: ParsedEventStream) -> AgentTerminationError | None:
    if parsed.input_tokens is not None and parsed.output_tokens is not None:
        return None
    return _termination(
        "provider_usage_missing",
        "Codex successful terminal stream omitted provider token usage",
        infrastructure=True,
        kind="runtime",
        reason=TerminationReason.RUNTIME_ERROR,
    )


__all__ = ["CodexCliMcpTeacherAdapter"]
