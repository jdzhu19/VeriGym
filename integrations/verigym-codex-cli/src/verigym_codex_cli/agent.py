"""Track B: external Codex CLI coding-agent adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

from verigym.core.hashing import content_hash
from verigym.evolution.memory import validate_memory_pack
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.campaign import (
    HWE_CODEX_BASE_INSTRUCTION_POLICY,
    HWE_CODEX_PROMPT_CONTRACT_ID,
    HWE_CODEX_PROMPT_CONTRACT_VERSION,
)
from verigym.hwe.codex_normalization import (
    HweCausalValidationError,
    normalize_codex_hwe_events,
)
from verigym.hwe.observation import TiktokenO200kCounter
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_OBSERVATION_POLICY_V2_ID,
    HWE_TOOL_CONTRACT_V2_ID,
)
from verigym.hwe.trajectory import build_hwe_teacher_transcript
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
    ExternalProcessResult,
    FinalSubmissionAction,
    InteractionMode,
    Observation,
    TerminationReason,
    validate_prompt_text,
)
from verigym.schemas.evolution import MemoryPack

from ._version import __version__
from .artifacts import CodexRunEvidence, update_summary
from .capabilities import CapabilityReport, runtime_capabilities
from .config import CodexSettings, agent_settings, settings_for_execution_backend
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
from .prompt_policy import bind_prompt_policy
from .runtime_execution import execute_runtime_process
from .security import (
    CodexPolicyError,
    WorkspaceSnapshot,
    assert_instruction_isolation,
    assert_safe_workspace_tree,
    compare_workspace_snapshots,
    sandbox_backend_failure,
    snapshot_visible_workspace,
    validate_external_events,
    validate_runtime_isolated_external_events,
)
from .util import redact_text


class CodexCliAgentAdapter(AgentAdapter):
    """Run exactly one external coding-agent episode in the visible workspace."""

    requires_model = False
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="codex_cli_workspace_verilog_task_context_v1",
        prompt_contract_version="1.0.0",
        task_context_policy="repository_visible_task_context_v1",
        base_instruction_policy="codex_cli_repository_agent_instructions_v1",
        content_visibility_policy="public_task_workspace_no_hidden_reference_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=True,
    )
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
        self._hwe_counter: TiktokenO200kCounter | None = None
        self._hwe_runtime_result: ExternalProcessResult | None = None
        self._hwe_process_stdout: str | None = None
        self._hwe_api_input_tokens = 0
        self._hwe_api_output_tokens = 0

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None:
            raise ValueError("codex-cli-agent requires ExternalAgentBridge")
        if bridge.execution_backend not in {
            "host_local_trusted",
            "docker_outer_runtime_delegated",
        }:
            raise ValueError("codex-cli-agent requires a supported external execution backend")
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
        settings = settings_for_execution_backend(settings, bridge.execution_backend)
        prompt_policy = bind_prompt_policy(
            context,
            settings,
            versioned_context_allowed=True,
        )
        hwe_collection = settings.integration_track == "codex_cli_hwe_native_shell"
        if hwe_collection and bridge.execution_backend != "docker_outer_runtime_delegated":
            raise ValueError("HWE native-shell collection requires the Docker runtime backend")
        prompt = validate_prompt_text(
            _agent_prompt(context, bridge, hwe_collection=hwe_collection), prompt_policy
        )
        self._context = context
        self._bridge = bridge
        self._executable = executable
        self._capabilities = capabilities
        self._settings = settings
        self._prompt = prompt
        self._launched = False
        self._artifact_root = bridge.artifact_root
        self._workspace_before = workspace_before
        self._hwe_counter = TiktokenO200kCounter() if hwe_collection else None
        self._hwe_runtime_result = None
        self._hwe_process_stdout = None
        self._hwe_api_input_tokens = 0
        self._hwe_api_output_tokens = 0
        bridge.emit_event(
            "codex_cli_prompt_policy_bound",
            {
                "prompt_policy_hash": prompt_policy.configuration_fingerprint,
                "task_context_hash": prompt_policy.task_context_hash,
                "agent_version_id": prompt_policy.agent_version_id,
                "agent_version_hash": prompt_policy.agent_version_hash,
                "memory_pack_hash": prompt_policy.memory_pack_hash,
                "model_call_count": 0,
            },
        )
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
        runtime_delegated = bridge.execution_backend == "docker_outer_runtime_delegated"
        arguments = [] if runtime_delegated else build_exec_arguments(capabilities, settings)
        invocation = (
            sanitized_runtime_invocation(
                settings,
                capabilities,
                working_directory_policy="visible_task_workspace",
            )
            if runtime_delegated
            else sanitized_invocation(
                arguments,
                settings,
                capabilities,
                working_directory_policy="visible_task_workspace",
            )
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
        parsed: ParsedEventStream | None = None
        runtime_result: ExternalProcessResult | None = None
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
            if runtime_delegated:
                outcome = execute_runtime_process(
                    bridge=bridge,
                    executable=executable,
                    capabilities=capabilities,
                    settings=settings,
                    prompt=prompt,
                    prompt_policy=context.prompt_policy,
                    workspace_mode="visible_task_workspace",
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
            protocol_reason = runtime_result.failure_reason
            if isinstance(protocol_reason, str) and protocol_reason.startswith("hwe_protocol_"):
                failure = _agent_failure(
                    TerminationReason.MODEL_ERROR,
                    "protocol_error",
                    "HWE exec-server protocol failed closed during runtime cleanup",
                    infrastructure=True,
                    protocol_error_subcategory=protocol_reason,
                )
            else:
                failure = _agent_failure(
                    TerminationReason.MODEL_ERROR,
                    "runtime_security_controls",
                    "Docker external-agent effective controls or cleanup were incomplete",
                    infrastructure=True,
                )
        if failure is not None and process.stdout:
            parsed = parse_partial_event_stream(process.stdout, roots=(workspace,))
        if failure is None:
            backend_category = sandbox_backend_failure(process.stdout, process.stderr)
            if backend_category is not None:
                try:
                    parsed = _parse_agent_process(
                        process,
                        workspace,
                        require_final_message=(
                            settings.integration_track != "codex_cli_hwe_native_shell"
                        ),
                    )
                except EventParseError:
                    parsed = parse_partial_event_stream(process.stdout, roots=(workspace,))
                failure = _agent_failure(
                    TerminationReason.MODEL_ERROR,
                    backend_category,
                    "Codex CLI workspace sandbox backend was unavailable",
                    infrastructure=True,
                )
                event_policy = {
                    "schema_version": "1.0",
                    "policy_id": settings.tool_use_policy,
                    "policy_passed": False,
                    "evaluation_complete": False,
                    "failure_category": backend_category,
                    "failure_message": "Codex CLI workspace sandbox backend was unavailable",
                }
            elif process.timed_out or process.stdout_truncated or process.stderr_truncated:
                parsed = parse_partial_event_stream(process.stdout, roots=(workspace,))
                failure = _process_failure(process, parsed, runtime_result)
            else:
                try:
                    parsed = _parse_agent_process(
                        process,
                        workspace,
                        require_final_message=(
                            settings.integration_track != "codex_cli_hwe_native_shell"
                        ),
                    )
                    if runtime_delegated:
                        validate_runtime_isolated_external_events(
                            parsed,
                            Path(bridge.logical_workspace_root),
                        )
                    else:
                        validate_external_events(
                            parsed,
                            workspace,
                            editable_globs=bridge.editable_globs,
                        )
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
            failure = _process_failure(process, parsed, runtime_result)
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
            runtime_process=runtime_result,
            roots_to_redact=(workspace,),
        )
        evidence.write(bridge.artifact_root, create=False)
        if failure is not None:
            raise failure
        if settings.integration_track == "codex_cli_hwe_native_shell":
            if runtime_result is None or not runtime_result.hwe_protocol_records:
                raise _agent_failure(
                    TerminationReason.MODEL_ERROR,
                    "hwe_protocol_evidence_missing",
                    "HWE native-shell episode produced no correlated protocol evidence",
                    infrastructure=True,
                )
            self._hwe_runtime_result = runtime_result
            self._hwe_process_stdout = process.stdout
            self._hwe_api_input_tokens = int(parsed.input_tokens or 0) if parsed is not None else 0
            self._hwe_api_output_tokens = (
                int(parsed.output_tokens or 0) if parsed is not None else 0
            )
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
        if self._hwe_counter is not None and result.resolved:
            self._write_hwe_transcript(result)

    def _write_hwe_transcript(self, result: EpisodeResult) -> None:
        context, bridge, executable, capabilities, settings, prompt = self._configured()
        runtime_result = self._hwe_runtime_result
        stdout = self._hwe_process_stdout
        if runtime_result is None or stdout is None:
            raise RuntimeError("resolved HWE episode lacks its native-shell evidence")
        raw_manifest = runtime_result.hwe_private_audit_manifest
        if not isinstance(raw_manifest, dict) or not isinstance(raw_manifest.get("sha256"), str):
            raise RuntimeError("resolved HWE episode lacks its frozen private raw manifest")
        raw_layer_hash = cast(str, raw_manifest["sha256"])
        counter = self._hwe_counter
        if counter is None:
            raise RuntimeError("resolved HWE episode lacks its frozen tokenizer")
        try:
            events, turns = normalize_codex_hwe_events(
                protocol_records=runtime_result.hwe_protocol_records,
                app_server_jsonl=stdout,
                terminal_success=(
                    runtime_result.terminal_event_seen and runtime_result.exit_code == 0
                ),
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
        except HweCausalValidationError as exc:
            base = {
                "schema_version": "1.0",
                "format_id": "verigym_hwe_materialization_rejection_v1",
                "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "task_id": context.task.id,
                "reason": exc.reason,
                "ordinary_verifier_resolved": result.resolved,
                "terminal_event_seen": runtime_result.terminal_event_seen,
                "protocol_record_count": len(runtime_result.hwe_protocol_records),
                "raw_layer_hash": raw_layer_hash,
            }
            rejection = {**base, "rejection_hash": content_hash(base)}
            atomic_dump_json(bridge.artifact_root / "hwe_materialization_rejection.json", rejection)
            update_summary(
                bridge.artifact_root,
                {
                    "hwe_collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                    "hwe_materialization_rejected": True,
                    "hwe_materialization_rejection_reason": exc.reason,
                    "hwe_materialization_rejection_hash": rejection["rejection_hash"],
                    "ordinary_verifier_resolved": result.resolved,
                },
            )
            return
        messages = [
            {
                "role": "system",
                "content": (
                    "Operate only through the selected external Docker environment. Never "
                    "request permissions, network, MCP, apps, plugins, or other agents."
                ),
            },
            {"role": "user", "content": prompt},
            *turns,
        ]
        transcript = build_hwe_teacher_transcript(
            task_id=context.task.id,
            model_id=settings.model_id,
            client_version=capabilities.version_output.strip(),
            client_sha256=executable.sha256,
            agent_image_lock_hash=str(context.agent_options["agent_image_lock_hash"]),
            messages=messages,
            normalized_events=events,
            counter=counter,
            api_input_tokens=self._hwe_api_input_tokens,
            api_output_tokens=self._hwe_api_output_tokens,
            raw_layer_hash=raw_layer_hash,
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )
        atomic_dump_json(bridge.artifact_root / "hwe_teacher_transcript.json", transcript)
        update_summary(
            bridge.artifact_root,
            {
                "hwe_collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "hwe_transcript_format": transcript["format_id"],
                "hwe_transcript_hash": transcript["transcript_hash"],
                "hwe_sft_bucket": transcript["sft_bucket"],
                "hwe_primary_eligible": transcript["primary_eligible"],
                "ordinary_verifier_resolved": result.resolved,
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


class CodexCliHweAgentAdapter(CodexCliAgentAdapter):
    """Codex 0.147 production collector using the isolated HWE native-shell contract."""

    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id=HWE_CODEX_PROMPT_CONTRACT_ID,
        prompt_contract_version=HWE_CODEX_PROMPT_CONTRACT_VERSION,
        task_context_policy="hwe_bounded_repository_context_v2",
        base_instruction_policy=HWE_CODEX_BASE_INSTRUCTION_POLICY,
        content_visibility_policy="public_task_workspace_no_hidden_reference_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="codex-cli-hwe-agent",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="openai-codex-cli",
        capabilities=[
            "external_coding_agent",
            "workspace_editing",
            "machine_readable_events",
            "single_external_episode",
            "hwe_native_shell_collection",
        ],
    )

    def start(self, context: AgentContext) -> None:
        if context.agent_options.get("collection_profile_id") != HWE_COLLECTION_PROFILE_V2_ID:
            raise ValueError("codex-cli-hwe-agent requires collection_profile_id=hwe_standard_v2")
        super().start(context)


def _agent_prompt(
    context: AgentContext,
    bridge: ExternalAgentBridge,
    *,
    hwe_collection: bool = False,
) -> str:
    workspace = bridge.workspace_root.resolve(strict=True)
    visible_files = (
        _bounded_hwe_tree(workspace)
        if hwe_collection
        else [
            path.relative_to(workspace).as_posix()
            for path in sorted(workspace.rglob("*"))
            if path.is_file() and ".verigym_internal" not in path.parts
        ]
    )
    visible_tools = sorted(
        tool
        for tool in context.task.interaction.allowed_tools
        if tool not in context.task.interaction.denied_tools
    )
    payload = {
        "schema_version": "1.0",
        "prompt_policy": context.prompt_policy.model_dump(mode="json")
        if context.prompt_policy is not None
        else None,
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
            "outside_workspace_access": (
                "isolated_container_read_only_allowed" if hwe_collection else "forbidden"
            ),
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
    if hwe_collection:
        payload.update(
            {
                "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
                "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
                "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
                "initial_tree_contract": {
                    "depth": 2,
                    "entries": 200,
                    "excluded_from_initial_expansion": [
                        "build",
                        "generated",
                        "vendor",
                        "third_party",
                    ],
                    "scoped_search_and_read_allowed": True,
                },
                "native_shell_contract": {
                    "cwd": "workspace-relative only",
                    "container_read_scope": "isolated agent container",
                    "parent_paths": "allowed",
                    "absolute_container_paths": "allowed",
                    "candidate_write_scope": "/workspace/repository",
                    "ephemeral_write_scope": "/tmp",
                    "container_rootfs": "read-only",
                    "environment_injection": "forbidden",
                    "model_selected_timeout": "forbidden",
                    "timeouts_s": {"ordinary": 60, "compile": 600, "simulation": 900},
                },
            }
        )
        payload["instructions"] = [
            "Make candidate changes only in /workspace/repository.",
            "TASK.md is at the workspace root; CVA6 source paths begin with repository/.",
            "Start from the bounded shallow tree, then use scoped search/read commands.",
            "Treat every omission marker as evidence that content exists but is not shown.",
            "Container-native reads may use parent paths such as `find ..` and absolute paths; "
            "the isolated image contains no hidden verifier or provider credentials.",
            "The container root is read-only and /tmp is ephemeral; do not inject environment "
            "variables or timeouts.",
            "Do not probe environment variables or use $NAME expansions other than the frozen "
            "allowlist $PWD, $RISCV, and $VERILATOR_ROOT; prefer fixed tool paths.",
            "Never issue an empty or whitespace-only shell command; use `true` only when an "
            "explicit no-op is necessary.",
            "Do not assign shell or environment variables and do not use command substitution "
            "(`$()` or backticks); use fixed paths and direct commands.",
            "Do not write interactive stdin; a single interrupt of a stalled known process is "
            "recorded as completion of that shell action.",
            "Issue exactly one tool or process call at a time and wait for it to complete; never "
            "run shell commands or edits in parallel.",
            "Make persistent edits through concise shell commands so every mutation remains "
            "attached to its completed shell action; do not use direct filesystem-write or "
            "built-in patch operations.",
            "Do not embed full file contents or previous command output in an edit command; use "
            "a short targeted transformation (a single-quoted Python heredoc is allowed) and "
            "then inspect the diff; never use a heredoc to reproduce an entire source file.",
            "Run focused compile/simulation diagnostics and inspect the final diff.",
            "Do not use network, MCP, apps, plugins, other agents, or hidden verifier assets.",
            "Finish after one candidate; VeriGym owns verifier execution.",
        ]
    repository_contract = context.task.metadata.get("repository_repair")
    if isinstance(repository_contract, dict):
        public_test_ids = repository_contract.get("public_test_ids")
        if not isinstance(public_test_ids, list) or not all(
            isinstance(value, str) for value in public_test_ids
        ):
            raise ValueError("repository task public-test identity is malformed")
        if hwe_collection:
            payload["repository_repair"] = {
                "repository_root": "repository",
                "issue_file": "TASK.md",
                "public_test_launcher": {
                    "available": False,
                    "execution_owner": "verigym_after_submission",
                    "model_access": "unavailable",
                },
                "local_diagnostics": {
                    "available_commands": ["rg", "make", "verilator"],
                    "repository_scripts": "allowed within workspace policy",
                },
                "candidate_contract": {
                    "kind": "unified_repository_patch",
                    "freeze_owner": "verigym",
                    "candidate_repair": "forbidden",
                },
            }
            payload["instructions"] = [
                "Make candidate changes only in /workspace/repository.",
                "TASK.md is at the workspace root; CVA6 source paths begin with repository/.",
                "Read TASK.md and the visible repository before editing.",
                "Start from the bounded shallow tree, then use scoped search/read commands.",
                "Treat every omission marker as evidence that content exists but is not shown.",
                "Edit only paths allowed by workspace_policy.editable_globs.",
                "The `verigym-public-test` launcher and verifier assets are unavailable; "
                "do not invoke or inspect them.",
                "Use available `rg`, `make`, `verilator`, and repository scripts for focused "
                "local compile/simulation diagnostics.",
                "Container-native reads may use parent paths such as `find ..` and absolute "
                "container paths.",
                "The container root is read-only and /tmp is ephemeral; do not inject "
                "environment variables or timeouts.",
                "Do not probe environment variables or use $NAME expansions other than the "
                "frozen allowlist $PWD, $RISCV, and $VERILATOR_ROOT; prefer fixed tool paths.",
                "Never issue an empty or whitespace-only shell command; use `true` only when an "
                "explicit no-op is necessary.",
                "Do not assign shell or environment variables and do not use command "
                "substitution (`$()` or backticks); use fixed paths and direct commands.",
                "Do not write interactive stdin; a single interrupt of a stalled known process "
                "is recorded as completion of that shell action.",
                "Issue exactly one tool or process call at a time and wait for it to complete; "
                "never run shell commands or edits in parallel.",
                "Make persistent edits through concise shell commands so every mutation remains "
                "attached to its completed shell action; do not use direct filesystem-write or "
                "built-in patch operations.",
                "Do not embed full file contents or previous command output in an edit command; "
                "use a short targeted transformation (a single-quoted Python heredoc is allowed) "
                "and then inspect the diff; never use a heredoc to reproduce an entire source "
                "file.",
                "Inspect the final diff before finishing.",
                "Do not use network, MCP, apps, plugins, other agents, or hidden verifier assets.",
                "Do not ask the user questions.",
                "Finish after one repository candidate; VeriGym owns verifier execution.",
            ]
        else:
            payload["repository_repair"] = {
                "repository_root": "repository",
                "issue_file": "TASK.md",
                "public_test_launcher": {
                    "list": ["verigym-public-test", "list"],
                    "run": ["verigym-public-test", "run", "<test-id>"],
                    "test_ids": sorted(public_test_ids),
                    "assets": "trusted read-only mount; direct asset access is forbidden",
                },
                "candidate_contract": {
                    "kind": "unified_repository_patch",
                    "freeze_owner": "verigym",
                    "candidate_repair": "forbidden",
                },
            }
            payload["instructions"] = [
                "Work only inside the current visible task workspace.",
                "Read TASK.md and the visible repository before editing.",
                "Edit only paths allowed by workspace_policy.editable_globs.",
                "Use only `verigym-public-test list` and `verigym-public-test run <test-id>` "
                "for public verification; do not inspect /verigym-public directly.",
                "Do not access parent, home, source repository, credential, or "
                "hidden-verifier paths.",
                "Do not use network, MCP, plugins, external repositories, or web search.",
                "Do not ask the user questions.",
                "Finish after one repository candidate; VeriGym freezes the patch "
                "and runs hidden tests.",
            ]
    task_artifact = (
        '<verigym_external_agent_task schema_version="1.0">\n'
        + json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n</verigym_external_agent_task>\n"
    )
    raw_memory = context.agent_options.get("memory_pack")
    if raw_memory is None:
        return task_artifact
    memory = validate_memory_pack(MemoryPack.model_validate(raw_memory))
    memory_artifact = {
        "schema_version": "1.0",
        "label": "frozen_task_independent_read_only_agent_memory",
        "content_hash": memory.content_hash,
        "read_only": True,
        "must_not_write_to_candidate_repository": True,
        "sections": [
            {"section": section.section, "items": section.items} for section in memory.sections
        ],
    }
    return (
        task_artifact
        + '<verigym_agent_memory schema_version="1.0" '
        + f'content_hash="{memory.content_hash}">\n'
        + json.dumps(memory_artifact, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n</verigym_agent_memory>\n"
    )


def _bounded_hwe_tree(workspace: Path) -> list[str]:
    excluded = {"build", "generated", "vendor", "third_party", ".git", ".verigym_internal"}
    values: list[str] = []
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace)
        if len(relative.parts) > 2 or any(part in excluded for part in relative.parts):
            continue
        values.append(relative.as_posix() + ("/" if path.is_dir() else ""))
        if len(values) == 200:
            values.append("[verigym-hwe omission: initial tree exceeds 200 entries]")
            break
    return values


def _parse_agent_process(
    process: CodexProcessResult,
    workspace: Path,
    *,
    require_final_message: bool = True,
) -> ParsedEventStream:
    parsed = parse_event_stream(process.stdout, roots=(workspace,))
    if process.exit_code == 0 and not parsed.terminal_event_seen:
        raise EventParseError("Codex CLI external-agent stream has no terminal event")
    if process.exit_code == 0 and require_final_message and not parsed.final_messages:
        raise EventParseError("Codex CLI external-agent stream has no final message")
    return parsed


def _process_failure(
    process: CodexProcessResult,
    parsed: ParsedEventStream | None,
    runtime_result: ExternalProcessResult | None = None,
) -> AgentTerminationError | None:
    if (
        runtime_result is not None
        and isinstance(runtime_result.failure_reason, str)
        and runtime_result.failure_reason.startswith("hwe_protocol_")
    ):
        return _agent_failure(
            TerminationReason.MODEL_ERROR,
            "protocol_error",
            "HWE exec-server protocol failed closed",
            infrastructure=True,
            protocol_error_subcategory=runtime_result.failure_reason,
        )
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
        adapter_name=(
            "codex-cli-hwe-agent"
            if settings.integration_track == "codex_cli_hwe_native_shell"
            else "codex-cli-agent"
        ),
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
        integration_track=cast(
            Literal[
                "codex_cli_readonly_single_turn_agent",
                "codex_cli_external_agent",
                "codex_cli_hwe_native_shell",
                "claude_cli_external_agent",
                "openhands_sdk_agent",
            ],
            settings.integration_track,
        ),
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
        model_call_count=parsed.model_call_count if parsed is not None else None,
        external_tool_call_count=(canonical.external_tool_count if canonical is not None else None),
        external_command_count=canonical.command_count if canonical is not None else None,
        public_test_invocation_count=(
            canonical.public_test_command_count if canonical is not None else None
        ),
        external_file_read_count=(canonical.file_read_count if canonical is not None else None),
        external_file_write_count=(canonical.file_write_count if canonical is not None else None),
        external_patch_count=canonical.patch_count if canonical is not None else None,
        input_tokens=parsed.input_tokens if parsed is not None else None,
        output_tokens=parsed.output_tokens if parsed is not None else None,
        total_tokens=parsed.total_tokens if parsed is not None else None,
        cost=None,
        currency=None,
    )


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
    protocol_error_subcategory: str | None = None,
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
            protocol_error_subcategory=protocol_error_subcategory,
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
