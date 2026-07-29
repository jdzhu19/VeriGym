"""Track A: read-only, single-turn Codex CLI agent in a fresh empty workdir."""

from __future__ import annotations

import difflib
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path

from verigym.agents.parsing import ModelOutputParseError, parse_single_turn_rtl
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
    ExternalProcessResult,
    FinalSubmissionAction,
    InteractionMode,
    Observation,
    TerminationReason,
)
from verigym.schemas.agent import ApplyPatchAction

from ._version import __version__
from .artifacts import CodexRunEvidence, update_summary
from .capabilities import CapabilityReport, runtime_capabilities
from .config import (
    CodexSettings,
    readonly_agent_settings,
    settings_for_execution_backend,
)
from .event_policy import (
    EventPolicyContext,
    EventPolicyResult,
    ToolPolicyId,
    evaluate_event_policy,
)
from .events import (
    EventParseError,
    ParsedEventStream,
    parse_event_stream,
    parse_partial_event_stream,
)
from .invocation import (
    build_exec_arguments,
    sanitized_invocation,
    sanitized_runtime_invocation,
)
from .process import (
    CodexCliProcessRunner,
    CodexProcessError,
    CodexProcessResult,
    ExecutableIdentity,
)
from .runtime_execution import execute_runtime_process
from .security import assert_empty_directory, assert_instruction_isolation
from .util import redact_text

_WORKDIR_IDENTITY = "fresh_empty_temporary_directory"
_POLICY_ID: ToolPolicyId = "typed_readonly_empty_workdir_v1"


class CodexCliReadonlyAgentAdapter(AgentAdapter):
    """Submit one textual RTL candidate after typed read-only event validation."""

    requires_model = False
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="codex-cli-readonly-agent",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "external_coding_agent",
            "cli_agent_single_turn_readonly",
            "machine_readable_events",
            "ordinary_patch_submission",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._executable: ExecutableIdentity | None = None
        self._capabilities: CapabilityReport | None = None
        self._settings: CodexSettings | None = None
        self._launched = False
        self._awaiting_patch_result = False
        self._artifact_root: Path | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None:
            raise ValueError("codex-cli-readonly-agent requires ExternalAgentBridge")
        if bridge.execution_backend not in {
            "host_local_trusted",
            "docker_outer_runtime_delegated",
        }:
            raise ValueError(
                "codex-cli-readonly-agent requires a supported external execution backend"
            )
        executable, capabilities = runtime_capabilities()
        settings = readonly_agent_settings(
            context.agent_options,
            capabilities,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        settings = settings_for_execution_backend(settings, bridge.execution_backend)
        self._context = context
        self._bridge = bridge
        self._executable = executable
        self._capabilities = capabilities
        self._settings = settings
        self._launched = False
        self._awaiting_patch_result = False
        self._artifact_root = bridge.artifact_root
        bridge.emit_event(
            "codex_cli_capabilities_resolved",
            {
                "capability_fingerprint": capabilities.capability_fingerprint,
                "executable_sha256": capabilities.executable_sha256,
                "model_call_count": 0,
            },
        )

    def act(self, observation: Observation) -> AgentAction:
        if self._awaiting_patch_result:
            self._awaiting_patch_result = False
            tool_result = observation.previous_tool_result
            if (
                tool_result is None
                or tool_result.tool != "file.apply_patch"
                or not tool_result.success
            ):
                update_summary(
                    self._required_artifact_root(),
                    {
                        "candidate_materialization": "ordinary_file_apply_patch",
                        "candidate_materialization_succeeded": False,
                    },
                )
                raise _agent_failure(
                    TerminationReason.POLICY_VIOLATION,
                    "candidate_materialization",
                    "ordinary VeriGym candidate patch was rejected",
                    infrastructure=False,
                )
            update_summary(
                self._required_artifact_root(),
                {
                    "candidate_materialization": "ordinary_file_apply_patch",
                    "candidate_materialization_succeeded": True,
                },
            )
            return FinalSubmissionAction(
                message=(
                    "Read-only Codex CLI agent response passed the typed event policy; "
                    "the ordinary VeriGym patch path materialized the candidate for freeze "
                    "and hidden verification."
                )
            )
        if self._launched:
            raise _agent_failure(
                TerminationReason.POLICY_VIOLATION,
                "multiple_readonly_episodes",
                "codex-cli-readonly-agent attempted more than one CLI episode",
                infrastructure=False,
            )
        self._launched = True
        context, bridge, executable, capabilities, settings = self._configured()
        runtime_delegated = bridge.execution_backend == "docker_outer_runtime_delegated"
        arguments = [] if runtime_delegated else build_exec_arguments(capabilities, settings)
        invocation = (
            sanitized_runtime_invocation(
                settings,
                capabilities,
                working_directory_policy=_WORKDIR_IDENTITY,
            )
            if runtime_delegated
            else sanitized_invocation(
                arguments,
                settings,
                capabilities,
                working_directory_policy=_WORKDIR_IDENTITY,
            )
        )
        bridge.emit_event(
            "codex_cli_process_started",
            {
                "integration_track": settings.integration_track,
                "sandbox_policy": settings.sandbox_policy,
                "approval_policy": settings.approval_policy,
                "effective_reasoning_effort": settings.effective_reasoning_effort,
                "reasoning_effort_source": settings.reasoning_effort_source,
                "working_directory_policy": _WORKDIR_IDENTITY,
            },
        )
        prompt = _readonly_prompt(context, observation)
        parsed: ParsedEventStream | None = None
        policy: EventPolicyResult | None = None
        source: str | None = None
        failure: AgentTerminationError | None = None
        workspace_mutated = False
        runtime_result: ExternalProcessResult | None = None
        with ExitStack() as stack:
            if runtime_delegated:
                workspace = Path(bridge.logical_workspace_root)
            else:
                temporary = stack.enter_context(
                    tempfile.TemporaryDirectory(prefix="verigym-codex-readonly-agent-")
                )
                workspace = Path(temporary).resolve()
                try:
                    assert_instruction_isolation(workspace)
                    assert_empty_directory(workspace)
                except Exception as exc:
                    raise _agent_failure(
                        TerminationReason.POLICY_VIOLATION,
                        "empty_workdir_precondition",
                        str(exc),
                        infrastructure=False,
                    ) from exc
            try:
                if runtime_delegated:
                    outcome = execute_runtime_process(
                        bridge=bridge,
                        executable=executable,
                        capabilities=capabilities,
                        settings=settings,
                        prompt=prompt,
                        workspace_mode="fresh_empty",
                    )
                    process = outcome.process
                    runtime_result = outcome.runtime_result
                else:
                    runner = CodexCliProcessRunner(
                        executable,
                        auth_mode=settings.resolved_auth_mode,
                        credential_env=settings.credential_env,
                        max_output_bytes=settings.max_output_bytes,
                        allow_proxy_environment=settings.allow_proxy_environment,
                    )
                    process = runner.run(
                        arguments,
                        cwd=workspace,
                        timeout_s=settings.max_process_time_s,
                        stdin_bytes=prompt.encode("utf-8"),
                    )
            except (CodexProcessError, ValueError) as exc:
                process = _failed_process(str(exc))
                failure = _agent_failure(
                    TerminationReason.MODEL_ERROR,
                    "process_boundary",
                    str(exc),
                    infrastructure=True,
                )
            if runtime_result is not None and not _runtime_security_complete(runtime_result):
                failure = _agent_failure(
                    TerminationReason.MODEL_ERROR,
                    "runtime_security_controls",
                    "Docker external-agent effective controls or cleanup were incomplete",
                    infrastructure=True,
                )
            if failure is None:
                if process.timed_out or process.stdout_truncated or process.stderr_truncated:
                    parsed = parse_partial_event_stream(process.stdout, roots=(workspace,))
                    failure = _process_failure(process, parsed, runtime_result)
                else:
                    try:
                        parsed = parse_event_stream(process.stdout, roots=(workspace,))
                    except EventParseError as exc:
                        failure = _agent_failure(
                            TerminationReason.MODEL_ERROR,
                            "parser_error",
                            str(exc),
                            infrastructure=True,
                        )
            if parsed is not None:
                policy = evaluate_event_policy(
                    parsed,
                    EventPolicyContext(
                        working_directory=workspace,
                        working_directory_identity=_WORKDIR_IDENTITY,
                        sandbox_identity=settings.sandbox_policy,
                        network_policy="disabled",
                        mcp_policy="disabled",
                    ),
                    policy_id=_POLICY_ID,
                )
                _emit_events(bridge, parsed)
            if failure is None:
                failure = _process_failure(process, parsed, runtime_result)
            if failure is None and parsed is not None:
                if not parsed.terminal_event_seen:
                    failure = _agent_failure(
                        TerminationReason.MODEL_ERROR,
                        "parser_error",
                        "Codex CLI read-only agent stream has no terminal event",
                        infrastructure=True,
                    )
                elif not parsed.final_messages:
                    failure = _agent_failure(
                        TerminationReason.MODEL_OUTPUT_INVALID,
                        "missing_final_response",
                        "Codex CLI read-only agent stream has no final response",
                        infrastructure=False,
                    )
                elif policy is None or not policy.policy_passed:
                    failure = _agent_failure(
                        TerminationReason.POLICY_VIOLATION,
                        "readonly_event_policy",
                        _policy_message(policy),
                        infrastructure=False,
                    )
                    bridge.emit_event(
                        "codex_cli_policy_violation",
                        {
                            "category": "readonly_event_policy",
                            "message": _policy_message(policy),
                        },
                    )
                else:
                    try:
                        source = parse_single_turn_rtl(parsed.final_messages[-1])
                    except ModelOutputParseError as exc:
                        failure = _agent_failure(
                            TerminationReason.MODEL_OUTPUT_INVALID,
                            "invalid_single_turn_output",
                            str(exc),
                            infrastructure=False,
                        )
            workspace_mutated = (
                bool(runtime_result.security.workspace_changed_paths)
                if runtime_result is not None
                else any(workspace.iterdir())
            )
            if workspace_mutated and (failure is None or not failure.failure.infrastructure):
                failure = _agent_failure(
                    TerminationReason.POLICY_VIOLATION,
                    "empty_workdir_modified",
                    "read-only Codex CLI agent modified its fresh empty workdir",
                    infrastructure=False,
                )
            identity = _external_identity(
                settings,
                capabilities,
                parsed,
                policy,
                workspace_mutated=workspace_mutated,
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
                event_policy=policy.safe_dict() if policy is not None else None,
                runtime_process=runtime_result,
                summary={
                    "integration_track": settings.integration_track,
                    "structurally_successful_readonly_episode": failure is None,
                    "complete_final_response": bool(
                        parsed is not None and parsed.terminal_event_seen and parsed.final_messages
                    ),
                    "candidate_parsed": source is not None,
                    "tool_policy_passed": (policy.policy_passed if policy is not None else False),
                    "tool_event_count": (policy.tool_event_count if policy is not None else 0),
                    "side_effecting_tool_event_count": (
                        policy.side_effecting_tool_event_count if policy is not None else 0
                    ),
                    "read_only_tool_event_count": (
                        policy.read_only_tool_event_count if policy is not None else 0
                    ),
                    "external_network_tool_event_count": (
                        policy.external_network_tool_event_count if policy is not None else 0
                    ),
                    "mcp_tool_event_count": (
                        policy.mcp_tool_event_count if policy is not None else 0
                    ),
                    "workspace_write_count": max(
                        policy.workspace_write_count if policy is not None else 0,
                        int(workspace_mutated),
                    ),
                    "final_message_count": (
                        len(parsed.final_messages) if parsed is not None else 0
                    ),
                    "failure_category": (failure.failure.category if failure is not None else None),
                    "failure_message": (failure.failure.message if failure is not None else None),
                },
                roots_to_redact=(bridge.workspace_root,),
            )
            evidence.write(bridge.artifact_root, create=False)
        if failure is not None:
            raise failure
        assert source is not None
        entrypoints = context.task.workspace.entrypoints
        if len(entrypoints) != 1:
            raise _agent_failure(
                TerminationReason.MODEL_OUTPUT_INVALID,
                "unsupported_submission_policy",
                "read-only Codex CLI agent requires exactly one task entrypoint",
                infrastructure=False,
            )
        patch = _candidate_patch(
            bridge,
            entrypoints[0],
            source,
            max_source_bytes=context.task.budget.max_output_bytes_per_tool,
        )
        if not patch:
            update_summary(
                self._required_artifact_root(),
                {
                    "candidate_materialization": "candidate_already_identical",
                    "candidate_materialization_succeeded": True,
                },
            )
            return FinalSubmissionAction(
                message=(
                    "Read-only Codex CLI agent response passed the typed event policy; "
                    "the candidate already matched the visible entrypoint and was submitted "
                    "for ordinary freeze and hidden verification."
                )
            )
        self._awaiting_patch_result = True
        return ApplyPatchAction(patch=patch)

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
    ]:
        if (
            self._context is None
            or self._bridge is None
            or self._executable is None
            or self._capabilities is None
            or self._settings is None
        ):
            raise RuntimeError("codex-cli-readonly-agent has not been started")
        return (
            self._context,
            self._bridge,
            self._executable,
            self._capabilities,
            self._settings,
        )

    def _required_artifact_root(self) -> Path:
        if self._artifact_root is None:
            raise RuntimeError("codex-cli-readonly-agent has no artifact root")
        return self._artifact_root


def _candidate_patch(
    bridge: ExternalAgentBridge,
    entrypoint: str,
    source: str,
    *,
    max_source_bytes: int,
) -> str:
    relative = Path(entrypoint)
    if relative.is_absolute() or ".." in relative.parts or "\\" in entrypoint:
        raise _agent_failure(
            TerminationReason.POLICY_VIOLATION,
            "candidate_materialization",
            "task entrypoint is not a safe relative path",
            infrastructure=False,
        )
    root = bridge.workspace_root.resolve(strict=True)
    target = root / relative
    if target.is_symlink():
        raise _agent_failure(
            TerminationReason.POLICY_VIOLATION,
            "candidate_materialization",
            "task entrypoint cannot be a symlink",
            infrastructure=False,
        )
    try:
        resolved = target.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("entrypoint is not a contained regular file")
        if resolved.stat().st_size > max_source_bytes:
            raise ValueError("entrypoint exceeds the bounded source-read limit")
        current = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise _agent_failure(
            TerminationReason.POLICY_VIOLATION,
            "candidate_materialization",
            str(exc),
            infrastructure=False,
        ) from exc
    candidate = source if source.endswith("\n") else source + "\n"
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=f"a/{entrypoint}",
            tofile=f"b/{entrypoint}",
        )
    )


def _readonly_prompt(context: AgentContext, observation: Observation) -> str:
    payload = {
        "schema_version": "1.0",
        "execution_identity": {
            "surface": "codex_cli",
            "interaction_class": "cli_agent_single_turn_readonly",
            "direct_api_benchmark": False,
            "chat_eval_compatible": False,
        },
        "task": {
            "id": context.task.id,
            "title": context.task.title,
            "description": context.task.description,
            "entrypoints": sorted(context.task.workspace.entrypoints),
        },
        "visible_context": {
            "visible_files": sorted(observation.visible_files),
            "selected_files": {
                key: observation.selected_files[key] for key in sorted(observation.selected_files)
            },
        },
        "policy": {
            "working_directory": "fresh_empty_read_only",
            "network": "disabled",
            "mcp": "disabled",
            "writes": "forbidden",
            "outside_workdir_access": "forbidden",
        },
        "instructions": [
            "Return exactly one RTL candidate for the declared entrypoint.",
            "Use raw Verilog/SystemVerilog or one fenced verilog/systemverilog block.",
            "Do not use tools; all required visible task context is already in this prompt.",
            (
                "Do not access home, config, repository, parent, hidden-verifier, "
                "or network resources."
            ),
            "Do not write or patch files and do not ask the user questions.",
        ],
    }
    return (
        '<verigym_readonly_cli_agent_task schema_version="1.0">\n'
        + json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n</verigym_readonly_cli_agent_task>\n"
    )


def _emit_events(bridge: ExternalAgentBridge, parsed: ParsedEventStream) -> None:
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


def _process_failure(
    process: CodexProcessResult,
    parsed: ParsedEventStream | None,
    runtime_result: ExternalProcessResult | None = None,
) -> AgentTerminationError | None:
    if (
        runtime_result is not None
        and runtime_result.failure_reason == "control_plane_loopback_proxy"
        and runtime_result.failure_origin == "host_control_plane"
    ):
        return AgentTerminationError(
            TerminationReason.MODEL_ERROR,
            EpisodeFailure(
                kind="runtime",
                category="control_plane_loopback_proxy",
                message=(
                    "trusted host control plane attempted proxy transport for its loopback broker"
                ),
                infrastructure=True,
            ),
        )
    if process.timed_out:
        return _agent_failure(
            TerminationReason.MODEL_ERROR,
            "timeout",
            "Codex CLI read-only agent process timed out",
            infrastructure=True,
        )
    if process.stdout_truncated or process.stderr_truncated:
        return _agent_failure(
            TerminationReason.MODEL_ERROR,
            "output_limit",
            "Codex CLI read-only agent output exceeded the configured bound",
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
        else redact_text(process.stderr).strip() or "Codex CLI read-only agent process failed"
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
    policy: EventPolicyResult | None,
    *,
    workspace_mutated: bool,
) -> ExternalAgentCallIdentity:
    observed = parsed.observed_model_id if parsed is not None else None
    return ExternalAgentCallIdentity(
        adapter_name="codex-cli-readonly-agent",
        adapter_version=__version__,
        harness_name="verigym-readonly-single-turn-agent",
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
        integration_track="codex_cli_readonly_single_turn_agent",
        execution_surface="codex_cli",
        interaction_class="cli_agent_single_turn_readonly",
        harness_id=_harness_id(capabilities.version_output),
        model_client_kind="cli_agent_mediated",
        agent_harness_kind="codex_cli",
        tool_availability_policy=settings.tool_availability_policy,
        tool_use_policy=settings.tool_use_policy,
        tool_event_count=policy.tool_event_count if policy is not None else 0,
        side_effecting_tool_event_count=(
            policy.side_effecting_tool_event_count if policy is not None else 0
        ),
        read_only_tool_event_count=(policy.read_only_tool_event_count if policy is not None else 0),
        external_network_tool_event_count=(
            policy.external_network_tool_event_count if policy is not None else 0
        ),
        mcp_tool_event_count=policy.mcp_tool_event_count if policy is not None else 0,
        workspace_write_count=max(
            policy.workspace_write_count if policy is not None else 0,
            int(workspace_mutated),
        ),
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
        identity_confidence="observed" if observed else "requested_only",
        reproducibility_scope="mutable_remote_observation",
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
        public_test_invocation_count=(
            canonical.public_test_command_count if canonical is not None else None
        ),
        external_file_read_count=(canonical.file_read_count if canonical is not None else None),
        external_file_write_count=(canonical.file_write_count if canonical is not None else None),
        external_patch_count=canonical.patch_count if canonical is not None else None,
        input_tokens=canonical.input_tokens if canonical is not None else None,
        output_tokens=canonical.output_tokens if canonical is not None else None,
        total_tokens=canonical.total_tokens if canonical is not None else None,
        cost=None,
        currency=None,
    )


def _policy_message(policy: EventPolicyResult | None) -> str:
    if policy is None:
        return "read-only event policy evidence is unavailable"
    reasons = ", ".join(policy.reason_list) or "unspecified policy violation"
    return f"read-only event policy rejected {policy.forbidden_event_count} event(s): {reasons}"


def _harness_id(version_output: str) -> str:
    return "-".join(version_output.strip().lower().split())[:128]


def _runtime_security_complete(result: ExternalProcessResult) -> bool:
    security = result.security
    return (
        result.cleanup_complete
        and security.effective_controls_verified
        and security.container_exit_inspected
        and security.cleanup_verified
        and security.container_removed
        and security.broker_stopped
        and security.process_group_cleaned
        and security.user_config_metadata_unchanged
        and not security.api_key_environment_forwarded
        and not security.credential_contents_accessed_by_verigym
        and not security.user_config_contents_accessed_by_verigym
        and not security.credential_environment_names_in_container
        and not security.proxy_environment_names_in_container
        and security.control_plane_mandatory_loopback_bypass_present
        and (
            not security.control_plane_proxy_forwarding_enabled
            or security.control_plane_synthesized_environment_names == ["NO_PROXY", "no_proxy"]
        )
        and security.network_mode == "none"
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


__all__ = ["CodexCliReadonlyAgentAdapter"]
