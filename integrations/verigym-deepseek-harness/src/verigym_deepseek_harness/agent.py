"""DeepSeek Harness adapter for the frozen HWE native-shell v2 pilot."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness import (
    DEEPSEEK_HARNESS_MODEL,
    build_deepseek_harness_transcript,
    build_deepseek_harness_transcript_v3,
    set_deepseek_harness_verifier_result,
    set_deepseek_harness_verifier_result_v3,
)
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_OBSERVATION_POLICY_V2_ID,
    HWE_TOOL_CONTRACT_V2_ID,
)
from verigym.hwe.trajectory import HweNormalizedEvent
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

from ._version import __version__
from .broker import DeepSeekHarnessBrokerStats, DeepSeekHarnessHweBroker, broker_stats_dict
from .config import (
    DEEPSEEK_HARNESS_VERSION,
    MAX_PROVIDER_CALLS,
    MAX_PROVIDER_TOKENS,
    DeepSeekHarnessSettings,
    require_provider_environment,
    resolve_settings,
)
from .process import (
    DeepSeekHarnessProcessError,
    DeepSeekHarnessProcessResult,
    provider_request_started,
    run_harness_helper,
)

PROMPT_CONTRACT_ID = "deepseek_harness_hwe_native_shell_context_v1"
PROMPT_CONTRACT_VERSION = "1.0.0"
BASE_INSTRUCTION_POLICY = "deepseek_harness_hwe_six_tool_base_v1"
PROMPT_CONTRACT_ID_V3 = "deepseek_harness_hwe_native_shell_context_v3"
PROMPT_CONTRACT_VERSION_V3 = "3.0.0"
BASE_INSTRUCTION_POLICY_V3 = "deepseek_harness_hwe_deepswe_compatible_v3"
PROMPT_CONTRACT_ID_V4 = "deepseek_harness_hwe_native_shell_context_v4"
PROMPT_CONTRACT_VERSION_V4 = "4.0.0"
BASE_INSTRUCTION_POLICY_V4 = "deepseek_harness_hwe_bounded_recovery_v4"
_CONTROL_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness")


class DeepSeekHarnessHweAgentAdapter(AgentAdapter):
    """Run one DeepSeek V4 Flash trajectory through the six typed HWE tools."""

    requires_model = False
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id=PROMPT_CONTRACT_ID,
        prompt_contract_version=PROMPT_CONTRACT_VERSION,
        task_context_policy="hwe_bounded_repository_context_v2",
        base_instruction_policy=BASE_INSTRUCTION_POLICY,
        content_visibility_policy="public_task_workspace_no_hidden_reference_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="deepseek-harness-hwe-agent",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="deepseek-official",
        capabilities=[
            "external_coding_agent",
            "workspace_editing",
            "machine_readable_events",
            "single_external_episode",
            "hwe_native_shell_collection",
            "training_transcript_capture",
        ],
    )
    integration_track = "deepseek_harness_hwe_native_shell"
    harness_contract_version = "v2"
    format_repair_budget = 0
    accepts_public_assistant_text = False
    bounded_progress_controls = False
    enforce_provider_budget = False

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._settings: DeepSeekHarnessSettings | None = None
        self._system_prompt: str | None = None
        self._task_prompt: str | None = None
        self._launched = False
        self._pending_transcript: dict[str, Any] | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        self._validate_execution_surface(bridge)
        assert bridge is not None
        if bridge.isolation_level != "docker_standard":
            raise ValueError("DeepSeek Harness HWE requires Docker standard isolation")
        if (
            context.prompt_policy is None
            or context.prompt_policy.id != self.prompt_policy_spec.prompt_contract_id
            or context.prompt_policy.version != self.prompt_policy_spec.prompt_contract_version
        ):
            raise ValueError("DeepSeek Harness HWE prompt contract is not frozen")
        require_provider_environment()
        settings = resolve_settings(
            context.agent_options,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        system_prompt = self._select_system_prompt()
        task_prompt = validate_prompt_text(_task_prompt(context, bridge), context.prompt_policy)
        self._context = context
        self._bridge = bridge
        self._settings = settings
        self._system_prompt = system_prompt
        self._task_prompt = task_prompt
        self._launched = False
        self._pending_transcript = None
        bridge.emit_event(
            "deepseek_harness_prompt_policy_bound",
            {
                "prompt_policy_hash": context.prompt_policy.configuration_fingerprint,
                "configuration_fingerprint": settings.configuration_fingerprint,
                "model_call_count": 0,
            },
        )

    def _validate_execution_surface(self, bridge: ExternalAgentBridge | None) -> None:
        """Fail closed unless the frozen contract owns the expected execution surfaces."""

        if bridge is None:
            raise ValueError("DeepSeek Harness HWE requires an external-agent bridge")
        if self.harness_contract_version == "v4":
            if (
                bridge.execution_backend != "runtime_external_process_unavailable"
                or bridge.command_execution_backend != "episode_container_exec_v1"
            ):
                raise ValueError(
                    "DeepSeek Harness HWE v4 requires the host Harness control plane "
                    "and episode command-image backend"
                )
            return
        if bridge.execution_backend != "docker_outer_runtime_delegated":
            raise ValueError("DeepSeek Harness HWE requires the Docker outer runtime")

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._launched:
            raise _termination(
                "multiple_external_episodes",
                "DeepSeek Harness HWE attempted more than one trajectory",
                infrastructure=False,
            )
        self._launched = True
        context, bridge, settings, system_prompt, task_prompt = self._configured()
        _CONTROL_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(_CONTROL_ROOT, 0o700)
        private_root = bridge.artifact_root.parent.parent / "private-audit"
        private_root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(private_root, 0o700)
        session_root = private_root / "deepseek-harness-sessions"
        session_root.mkdir(mode=0o700, exist_ok=False)
        session_id = f"dsh-{content_hash({'run_id': context.run_id})[:24]}"
        process: DeepSeekHarnessProcessResult | None = None
        process_error: DeepSeekHarnessProcessError | None = None
        provider_started = False
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="run-", dir=_CONTROL_ROOT) as raw_control:
            control = Path(raw_control)
            broker = DeepSeekHarnessHweBroker(
                bridge=bridge,
                socket_path=control / "b" / "broker.sock",
                private_audit_root=bridge.artifact_root.parent.parent,
                openhands_v23_controls=self.bounded_progress_controls,
            )
            broker.start()
            bridge.emit_event(
                "deepseek_harness_process_started",
                {
                    "integration_track": self.integration_track,
                    "requested_model_id": DEEPSEEK_HARNESS_MODEL,
                    "effective_reasoning_effort": "off",
                    "thinking": "disabled",
                    "temperature": 0,
                    "max_output_tokens": 2048,
                    "max_parallel_tool_calls": 1,
                    "provider_request_retries": 0,
                    "whole_episode_retries": 0,
                    "same_episode_format_repair_budget": self.format_repair_budget,
                    "controller_network": "verigym-hwe-net",
                    "agent_tool_network": "none",
                },
            )
            try:
                process = run_harness_helper(
                    settings,
                    mode="run",
                    prompt=task_prompt,
                    system_prompt=system_prompt,
                    session_id=session_id,
                    session_root=session_root,
                    broker_root=broker.socket_path.parent,
                    max_format_repairs=self.format_repair_budget,
                )
            except DeepSeekHarnessProcessError as exc:
                process_error = exc
            finally:
                broker.stop()
            try:
                provider_started = provider_request_started(session_root)
            except DeepSeekHarnessProcessError as exc:
                process_error = exc
            stats = broker.stats()
            events = broker.events()
            call_ids = broker.call_ids()
            progress_receipt = (
                broker.openhands_v23_progress_receipt() if self.bounded_progress_controls else None
            )

        duration_s = time.monotonic() - started
        if provider_started:
            bridge.emit_event(
                "deepseek_harness_provider_request_started",
                {
                    "provider_request_started": True,
                    "provider_request_count_lower_bound": 1,
                    "credential_values_persisted": False,
                },
            )
        self._record_identity_and_accounting(
            process=process,
            stats=stats,
            broker_events=events,
            duration_s=duration_s,
        )
        _write_collection_evidence(
            bridge.artifact_root,
            settings=settings,
            process=process,
            stats=stats,
            session_id=session_id,
            integration_track=self.integration_track,
            format_repair_budget=self.format_repair_budget,
            accepts_public_assistant_text=self.accepts_public_assistant_text,
            progress_receipt=progress_receipt,
            provider_request_started=provider_started,
        )
        if process_error is not None:
            raise _termination(
                "controller_process_boundary",
                str(process_error),
                infrastructure=True,
            ) from process_error
        assert process is not None
        model_calls = sum(event.get("type") == "assistant/message" for event in process.events)
        input_tokens, output_tokens = _usage(process.events)
        if self.enforce_provider_budget and (
            model_calls > MAX_PROVIDER_CALLS or input_tokens + output_tokens > MAX_PROVIDER_TOKENS
        ):
            raise _termination(
                "provider_budget_exhausted",
                "DeepSeek Harness exceeded its frozen provider budget",
                infrastructure=False,
            )
        if stats.infrastructure_failure is not None:
            raise _termination(
                "tool_broker_infrastructure",
                "DeepSeek Harness tool broker failed closed",
                infrastructure=True,
            )
        recoverable_v3_rejections = (
            self.accepts_public_assistant_text
            and stats.rejected_calls > 0
            and set(stats.rejection_codes) <= {"invalid_arguments"}
        )
        if (stats.policy_failure is not None or stats.rejected_calls) and not (
            recoverable_v3_rejections
        ):
            raise _termination(
                "hwe_action_policy",
                "DeepSeek Harness emitted an action outside the HWE v2 contract",
                infrastructure=False,
            )
        if process.finish_reason != "completed" or not stats.finished:
            raise _termination(
                "incomplete_harness_trajectory",
                "DeepSeek Harness did not complete with an explicit finish action",
                infrastructure=False,
            )
        if process.final_response and not self.accepts_public_assistant_text:
            raise _termination(
                "assistant_prose_outside_action",
                "DeepSeek Harness emitted final prose outside the typed finish action",
                infrastructure=False,
            )
        try:
            builder = (
                build_deepseek_harness_transcript_v3
                if self.accepts_public_assistant_text
                else build_deepseek_harness_transcript
            )
            build_options: dict[str, Any] = {}
            if self.accepts_public_assistant_text:
                build_options["format_repair_prompts"] = process.format_repairs
            self._pending_transcript = builder(
                task_id=context.task.id,
                system_prompt=system_prompt,
                task_prompt=task_prompt,
                session_events=process.events,
                broker_events=events,
                broker_call_ids=call_ids,
                harness_identity=settings.harness_identity(),
                **build_options,
            )
        except (TypeError, ValueError) as exc:
            raise _termination(
                "trajectory_causal_validation",
                "DeepSeek Harness trajectory failed causal normalization",
                infrastructure=False,
            ) from exc
        return FinalSubmissionAction(
            message=(
                "DeepSeek Harness submitted one typed-tool candidate to the ordinary "
                "VeriGym verifier flow."
            )
        )

    def _select_system_prompt(self) -> str:
        if self.harness_contract_version == "v4":
            return _system_prompt_v4()
        return _system_prompt_v3() if self.accepts_public_assistant_text else _system_prompt()

    def finish(self, result: EpisodeResult) -> None:
        if self._bridge is None:
            return
        updates: dict[str, Any] = {
            "ordinary_verifier_resolved": result.resolved,
            "ordinary_termination_reason": result.termination_reason,
            "model_called_during_finish": False,
            "candidate_modified_during_finish": False,
            "training_started": False,
            "hpc_jobs_submitted": False,
            "gpu_hours": 0,
        }
        if self._pending_transcript is not None:
            setter = (
                set_deepseek_harness_verifier_result_v3
                if self.accepts_public_assistant_text
                else set_deepseek_harness_verifier_result
            )
            transcript = setter(
                self._pending_transcript,
                verifier_resolved=result.resolved,
            )
            atomic_dump_json(
                self._bridge.artifact_root
                / (
                    "deepseek_harness_teacher_transcript_v3.json"
                    if self.accepts_public_assistant_text
                    else "deepseek_harness_teacher_transcript.json"
                ),
                transcript,
            )
            updates.update(
                {
                    "deepseek_harness_transcript_format": transcript["format_id"],
                    "deepseek_harness_transcript_hash": transcript["transcript_hash"],
                    "deepseek_harness_action_count": len(transcript["normalized_events"]),
                    "deepseek_harness_supervised_decision_count": transcript.get(
                        "supervised_decision_count", len(transcript["normalized_events"])
                    ),
                    "deepseek_harness_masked_policy_error_decision_count": transcript.get(
                        "masked_policy_error_decision_count", 0
                    ),
                    "deepseek_harness_masked_format_error_decision_count": transcript.get(
                        "masked_format_error_decision_count", 0
                    ),
                    "deepseek_harness_sft_eligible": result.resolved,
                }
            )
        _update_summary(self._bridge.artifact_root, updates)

    def _record_identity_and_accounting(
        self,
        *,
        process: DeepSeekHarnessProcessResult | None,
        stats: DeepSeekHarnessBrokerStats,
        broker_events: tuple[HweNormalizedEvent, ...],
        duration_s: float,
    ) -> None:
        _context, bridge, settings, _system, _task = self._configured()
        events = process.events if process is not None else ()
        model_calls = sum(event.get("type") == "assistant/message" for event in events)
        input_tokens, output_tokens = _usage(events)
        mutations = sum(
            event.action == "apply_patch" or (event.action == "shell" and bool(event.changed_paths))
            for event in broker_events
        )
        identity = ExternalAgentCallIdentity(
            adapter_name=self.descriptor.name,
            adapter_version=self.descriptor.version,
            harness_name="deepseek-harness-python-sdk-source-controller",
            requested_model_id=DEEPSEEK_HARNESS_MODEL,
            observed_model_id=DEEPSEEK_HARNESS_MODEL if model_calls else None,
            requested_reasoning_effort="off",
            effective_reasoning_effort="off",
            reasoning_effort_source="verigym_explicit_harness_override",
            inherited_reasoning_effort_allowed=False,
            executable_name="dsh-jsonrpc-agent-source",
            executable_sha256=settings.runtime_entry_hash,
            executable_version=DEEPSEEK_HARNESS_VERSION,
            capability_fingerprint=content_hash(settings.harness_identity()),
            configuration_fingerprint=settings.configuration_fingerprint,
            invocation_count=1,
            integration_track=self.integration_track,  # type: ignore[arg-type]
            execution_surface="deepseek_harness_sdk",
            interaction_class="sdk_agent_broker_tools",
            harness_id=(
                f"deepseek-harness-{DEEPSEEK_HARNESS_VERSION}-hwe-{self.harness_contract_version}"
            ),
            model_client_kind="sdk_agent_mediated",
            agent_harness_kind="deepseek_harness",
            tool_availability_policy="hwe_exact_six_typed_tools_v2",
            tool_use_policy=(
                "hwe_serial_execution_recoverable_invalid_arguments_v3"
                if self.accepts_public_assistant_text
                else "hwe_serial_action_state_machine_v2"
            ),
            tool_event_count=stats.tool_calls,
            side_effecting_tool_event_count=mutations,
            read_only_tool_event_count=stats.tool_calls - mutations,
            external_network_tool_event_count=0,
            mcp_tool_event_count=0,
            workspace_write_count=mutations,
            chat_eval_compatible=False,
            pure_api_model_eval=False,
            direct_api_benchmark=False,
            sandbox_policy="controller_without_workspace_brokered_hwe_tools",
            approval_policy="automatic_frozen_broker_policy",
            identity_confidence="observed" if model_calls else "requested_only",
            reproducibility_scope="mutable_remote_observation",
        )
        bridge.emit_event(
            "deepseek_harness_identity_observed",
            identity.model_dump(mode="json"),
        )
        bridge.record_accounting(
            ExternalAgentAccounting(
                process_wall_time_s=duration_s,
                cli_event_count=len(events),
                model_call_count=model_calls,
                external_tool_call_count=stats.tool_calls,
                external_command_count=stats.command_calls,
                public_test_invocation_count=0,
                external_file_read_count=stats.file_reads,
                external_file_write_count=mutations,
                external_patch_count=stats.patches,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
        )

    def _configured(
        self,
    ) -> tuple[AgentContext, ExternalAgentBridge, DeepSeekHarnessSettings, str, str]:
        if (
            self._context is None
            or self._bridge is None
            or self._settings is None
            or self._system_prompt is None
            or self._task_prompt is None
        ):
            raise RuntimeError("DeepSeek Harness HWE agent has not been started")
        return (
            self._context,
            self._bridge,
            self._settings,
            self._system_prompt,
            self._task_prompt,
        )


class DeepSeekHarnessHweAgentV3Adapter(DeepSeekHarnessHweAgentAdapter):
    """Native Harness v3 route with public rationale and bounded in-session recovery."""

    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id=PROMPT_CONTRACT_ID_V3,
        prompt_contract_version=PROMPT_CONTRACT_VERSION_V3,
        task_context_policy="hwe_bounded_repository_context_v2",
        base_instruction_policy=BASE_INSTRUCTION_POLICY_V3,
        content_visibility_policy="public_task_workspace_no_hidden_reference_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="deepseek-harness-hwe-agent-v3",
        version="0.2.0",
        api_version=PLUGIN_API_VERSION,
        provider="deepseek-official",
        capabilities=[
            "external_coding_agent",
            "workspace_editing",
            "machine_readable_events",
            "single_external_episode",
            "same_episode_format_recovery",
            "recoverable_tool_policy_errors",
            "public_text_and_typed_tool_decisions",
            "hwe_native_shell_collection",
            "training_transcript_capture",
        ],
    )
    integration_track = "deepseek_harness_hwe_native_shell_v3"
    harness_contract_version = "v3"
    format_repair_budget = 1
    accepts_public_assistant_text = True


class DeepSeekHarnessHweAgentV4Adapter(DeepSeekHarnessHweAgentV3Adapter):
    """Fresh-task Harness route with v23 progress and provider-budget gates."""

    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id=PROMPT_CONTRACT_ID_V4,
        prompt_contract_version=PROMPT_CONTRACT_VERSION_V4,
        task_context_policy="hwe_bounded_repository_context_v2",
        base_instruction_policy=BASE_INSTRUCTION_POLICY_V4,
        content_visibility_policy="public_task_workspace_no_hidden_reference_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="deepseek-harness-hwe-agent-v4",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="deepseek-official",
        capabilities=[
            *DeepSeekHarnessHweAgentV3Adapter.descriptor.capabilities,
            "pre_edit_progress_gate",
            "provider_call_budget",
            "provider_token_budget",
        ],
    )
    integration_track = "deepseek_harness_hwe_native_shell_v4"
    harness_contract_version = "v4"
    bounded_progress_controls = True
    enforce_provider_budget = True


def _system_prompt() -> str:
    return (
        "You are a hardware repository repair agent operating under the frozen HWE native-shell "
        "v2 contract. Every assistant step must contain exactly one tool call and no prose or "
        "reasoning block. Use only these six tools, one at a time: "
        "list_files, read_file, apply_patch, shell, inspect_diff, finish. Start by inspecting "
        "the task and repository, make only necessary workspace-relative changes, run focused "
        "local compile or simulation diagnostics, inspect the final diff, and call finish "
        "exactly once. Never use network access, hidden verifier assets, reference solutions, "
        "credentials, parent host paths, other agents, or undeclared tools."
    )


def _system_prompt_v3() -> str:
    return (
        "You are a hardware repository repair agent using the frozen HWE native-shell v3 "
        "contract. You may include concise public analysis text before one or more typed tool "
        "calls. Use only these six tools: list_files, read_file, apply_patch, shell, "
        "inspect_diff, finish. Tool calls in one assistant decision are executed serially in "
        "their emitted order. If a tool returns an error, read that public error, correct the "
        "arguments, and continue in the same episode. Start by inspecting TASK.md and relevant "
        "source, make only necessary workspace-relative changes, run focused local compile or "
        "simulation diagnostics, inspect the final diff, and call finish exactly once. Never "
        "use network access, hidden verifier assets, reference solutions, credentials, parent "
        "host paths, other agents, private reasoning blocks, or undeclared tools. Do not finish "
        "with a text-only response."
    )


def _system_prompt_v4() -> str:
    return (
        "You are a hardware repository repair agent using the frozen HWE native-shell v4 "
        "contract. Briefly state the current public hypothesis, next action, and validation "
        "conclusion when useful; do not expose or invent private chain-of-thought. You may emit "
        "one or more typed tool calls in a decision. Use only list_files, read_file, apply_patch, "
        "shell, inspect_diff, and finish. Sibling calls execute serially in emitted order. "
        "Inspect TASK.md and relevant repository source, make a focused edit, "
        "run bounded local diagnostics, inspect the final diff, and call finish exactly once. "
        "Never use network access, hidden verifier assets, reference solutions, credentials, "
        "parent host paths, other agents, private reasoning blocks, or undeclared tools. Do not "
        "finish with a text-only response."
    )


def _task_prompt(context: AgentContext, bridge: ExternalAgentBridge) -> str:
    workspace = bridge.workspace_root.resolve(strict=True)
    payload = {
        "schema_version": "1.0",
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "observation_policy_id": HWE_OBSERVATION_POLICY_V2_ID,
        "tool_contract_id": HWE_TOOL_CONTRACT_V2_ID,
        "task": {
            "id": context.task.id,
            "title": context.task.title,
            "description": context.task.description,
            "entrypoints": sorted(context.task.workspace.entrypoints),
        },
        "visible_file_tree": _bounded_tree(workspace),
        "workspace_policy": {
            "editable_globs": sorted(bridge.editable_globs),
            "readonly_globs": sorted(bridge.readonly_globs),
            "path_format": "workspace-relative only",
            "network": "disabled for every task tool",
            "max_changed_files": context.task.workspace.max_changed_files,
            "max_patch_lines": context.task.workspace.max_patch_lines,
        },
        "diagnostics": {
            "public_test_launcher": "unavailable to the model",
            "local_tools": ["rg", "make", "verilator"],
            "ordinary_timeout_s": 60,
            "compile_timeout_s": 600,
            "simulation_timeout_s": 900,
        },
        "instructions": [
            "Read TASK.md and relevant repository source before editing.",
            "Use list_files and bounded read_file calls to locate relevant code.",
            "Use apply_patch for concise persistent edits.",
            "Use shell only for bounded searches and local diagnostics; cwd is relative.",
            "Treat omission markers as evidence that unseen content still exists.",
            "Inspect the final candidate diff before calling finish exactly once.",
            "Do not ask questions and do not attempt whole-episode retries.",
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _bounded_tree(workspace: Path) -> list[str]:
    excluded = {".git", ".verigym_internal", "build", "generated", "third_party", "vendor"}
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


def _usage(events: tuple[dict[str, Any], ...]) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    for event in events:
        if event.get("type") != "assistant/message":
            continue
        data = event.get("data")
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            continue
        raw_input = usage.get("inputTokens")
        raw_output = usage.get("outputTokens")
        input_tokens += raw_input if isinstance(raw_input, int) else 0
        output_tokens += raw_output if isinstance(raw_output, int) else 0
    return input_tokens, output_tokens


def _write_collection_evidence(
    root: Path,
    *,
    settings: DeepSeekHarnessSettings,
    process: DeepSeekHarnessProcessResult | None,
    stats: DeepSeekHarnessBrokerStats,
    session_id: str,
    integration_track: str,
    format_repair_budget: int,
    accepts_public_assistant_text: bool,
    progress_receipt: dict[str, Any] | None,
    provider_request_started: bool,
) -> None:
    input_tokens, output_tokens = _usage(process.events if process is not None else ())
    model_calls = (
        sum(event.get("type") == "assistant/message" for event in process.events)
        if process is not None
        else 0
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_deepseek_harness_collection_evidence_v1",
        "session_id_hash": content_hash({"session_id": session_id}),
        "harness_identity": settings.harness_identity(),
        "provider": "deepseek-official",
        "model": DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "max_parallel_tool_calls": 1,
        "provider_request_retries": 0,
        "whole_episode_retries": 0,
        "max_provider_calls": MAX_PROVIDER_CALLS,
        "max_provider_tokens": MAX_PROVIDER_TOKENS,
        "observed_provider_calls": model_calls,
        "observed_provider_input_tokens": input_tokens,
        "observed_provider_output_tokens": output_tokens,
        "observed_provider_total_tokens": input_tokens + output_tokens,
        "provider_request_started": provider_request_started,
        "provider_request_count_lower_bound": 1 if provider_request_started else 0,
        "provider_budget_valid": (
            model_calls <= MAX_PROVIDER_CALLS
            and input_tokens + output_tokens <= MAX_PROVIDER_TOKENS
        ),
        "same_episode_format_repair_budget": format_repair_budget,
        "same_episode_format_repair_count": (
            len(process.format_repairs) if process is not None else 0
        ),
        "run_interval_count": process.run_interval_count if process is not None else 0,
        "assistant_output_contract": (
            "public_text_plus_one_or_more_typed_tool_calls"
            if accepts_public_assistant_text
            else "exactly_one_typed_tool_call_without_text"
        ),
        "broker": broker_stats_dict(stats),
        "progress_receipt": progress_receipt,
        "helper_exit_code": process.helper_exit_code if process is not None else None,
        "finish_reason": process.finish_reason if process is not None else None,
        "session_event_count": len(process.events) if process is not None else 0,
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "credential_values_exported": False,
        "training_started": False,
        "hpc_jobs_submitted": False,
        "gpu_hours": 0,
    }
    atomic_dump_json(
        root / "collection_evidence.json",
        {**base, "evidence_hash": content_hash(base)},
    )
    _update_summary(
        root,
        {
            "integration_track": integration_track,
            "model_id": DEEPSEEK_HARNESS_MODEL,
            "structurally_successful_external_episode": (
                process is not None
                and process.finish_reason == "completed"
                and stats.finished
                and stats.infrastructure_failure is None
                and (
                    stats.policy_failure is None
                    or (
                        accepts_public_assistant_text
                        and set(stats.rejection_codes) <= {"invalid_arguments"}
                    )
                )
            ),
            "tool_calls": stats.tool_calls,
            "model_call_count": (
                sum(event.get("type") == "assistant/message" for event in process.events)
                if process is not None
                else 0
            ),
            "training_started": False,
            "hpc_jobs_submitted": False,
            "gpu_hours": 0,
        },
    )


def _update_summary(root: Path, updates: dict[str, Any]) -> None:
    path = root / "summary.json"
    current: dict[str, Any] = {}
    if path.is_file() and not path.is_symlink():
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            current = value
    current.update(updates)
    atomic_dump_json(path, current)


def _termination(
    category: str,
    message: str,
    *,
    infrastructure: bool,
) -> AgentTerminationError:
    return AgentTerminationError(
        TerminationReason.RUNTIME_ERROR if infrastructure else TerminationReason.POLICY_VIOLATION,
        EpisodeFailure(
            kind="runtime" if infrastructure else "policy",
            category=category,
            message=message,
            infrastructure=infrastructure,
        ),
    )


__all__ = [
    "BASE_INSTRUCTION_POLICY",
    "BASE_INSTRUCTION_POLICY_V3",
    "DeepSeekHarnessHweAgentAdapter",
    "DeepSeekHarnessHweAgentV3Adapter",
    "DeepSeekHarnessHweAgentV4Adapter",
    "PROMPT_CONTRACT_ID",
    "PROMPT_CONTRACT_VERSION",
    "PROMPT_CONTRACT_ID_V3",
    "PROMPT_CONTRACT_VERSION_V3",
    "PROMPT_CONTRACT_ID_V4",
    "PROMPT_CONTRACT_VERSION_V4",
]
