"""OpenHands SDK backend for verifier-gated HWE native-shell trajectory collection."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from verigym.core.hashing import hash_bytes
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
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

from ._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
    OPENHANDS_SDK_STOP_CONTINUATION_BUDGET,
    OPENHANDS_SDK_STOP_CONTINUATION_MESSAGE,
    OPENHANDS_SDK_STOP_CONTINUATION_POLICY,
)
from ._version import __version__
from .hwe_config import OpenHandsHweSettings, resolve_hwe_settings
from .hwe_stop_hook import read_recovery_count
from .trajectory import (
    OpenHandsTrajectoryError,
    OpenHandsTrajectoryInfrastructureError,
    build_openhands_training_trajectory,
    hwe_broker_receipts,
    set_openhands_verifier_result,
    snapshot_openhands_events,
    snapshot_openhands_tools,
)

PROMPT_CONTRACT_ID = "openhands_hwe_native_shell_training_v2"
PROMPT_CONTRACT_VERSION = "2.0.0"
BASE_INSTRUCTION_POLICY = "openhands_hwe_exact_one_tool_bounded_recovery_v2"
_TOOL_NAMES = sorted(item["function"]["name"] for item in deepseek_harness_tool_definitions())


class OpenHandsHweAgentAdapter(AgentAdapter):
    """Run one exact, no-retry OpenHands HWE episode through six brokered tools."""

    requires_model = False
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id=PROMPT_CONTRACT_ID,
        prompt_contract_version=PROMPT_CONTRACT_VERSION,
        task_context_policy="hwe_bounded_repository_context_v2",
        base_instruction_policy=BASE_INSTRUCTION_POLICY,
        content_visibility_policy="public_task_workspace_no_hidden_reference_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=True,
    )
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="openhands-hwe-agent",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="openhands-sdk",
        capabilities=[
            "external_coding_agent",
            "openhands_sdk_agent_loop",
            "hwe_native_shell_collection",
            "exact_tool_schema_capture",
            "verifier_gated_training_trajectory",
            "decision_sft_64k_export",
            "single_external_episode",
            "exact_provider_call_budget",
            "same_session_format_recovery",
            "broker_authoritative_typed_finish",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._settings: OpenHandsHweSettings | None = None
        self._system_prompt: str | None = None
        self._task_prompt: str | None = None
        self._launched = False
        self._pending_training_trajectory: dict[str, Any] | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None or bridge.execution_backend != "docker_outer_runtime_delegated":
            raise ValueError("OpenHands HWE requires the Docker outer runtime")
        if bridge.isolation_level != "docker_standard":
            raise ValueError("OpenHands HWE requires Docker standard isolation")
        policy = context.prompt_policy
        if (
            policy is None
            or policy.id != PROMPT_CONTRACT_ID
            or policy.version != PROMPT_CONTRACT_VERSION
        ):
            raise ValueError("OpenHands HWE prompt contract is not frozen")
        settings = resolve_hwe_settings(
            context.agent_options,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        if (
            policy.agent_version_id != settings.agent_version_id
            or policy.agent_version_hash != settings.agent_version_hash
            or policy.memory_pack_hash is not None
        ):
            raise ValueError("OpenHands HWE version differs from its prompt binding")
        workspace_relative = settings.tool_choice_policy in {
            "validated_responses_recovery_state_required_tool_v14",
            "validated_responses_recovery_state_required_tool_v15",
            "validated_responses_recovery_state_required_tool_v16",
        }
        system_prompt = _system_prompt(workspace_relative=workspace_relative)
        task_prompt = validate_prompt_text(
            _task_prompt(context, bridge, workspace_relative=workspace_relative),
            policy,
        )
        self._context = context
        self._bridge = bridge
        self._settings = settings
        self._system_prompt = system_prompt
        self._task_prompt = task_prompt
        self._launched = False
        self._pending_training_trajectory = None
        bridge.emit_event(
            "openhands_sdk_hwe_prompt_policy_bound",
            {
                "prompt_policy_hash": policy.configuration_fingerprint,
                "configuration_fingerprint": settings.configuration_fingerprint,
                "model_call_count": 0,
            },
        )

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._launched:
            raise _termination(
                "multiple_openhands_hwe_episodes",
                "OpenHands HWE attempted more than one episode",
                infrastructure=False,
            )
        self._launched = True
        context, bridge, settings, system_prompt, task_prompt = self._configured()
        try:
            import openhands.sdk as openhands
            from openhands.sdk.conversation import (
                get_agent_final_response,
            )
            from openhands.sdk.hooks import (
                HookConfig,
                HookDefinition,
                HookMatcher,
            )
            from openhands.sdk.mcp import MCPServer
        except ImportError as exc:
            raise _termination(
                "openhands_sdk_unavailable",
                "OpenHands SDK 1.42.1 is unavailable",
                infrastructure=True,
            ) from exc
        try:
            from verigym_deepseek_harness.broker import (
                DeepSeekHarnessHweBroker,
                broker_stats_dict,
            )
        except ImportError as exc:
            raise _termination(
                "hwe_broker_unavailable",
                "verigym-deepseek-harness is required for OpenHands HWE",
                infrastructure=True,
            ) from exc
        if openhands.__version__ != "1.42.1":
            raise _termination(
                "openhands_sdk_version",
                "OpenHands SDK differs from frozen version 1.42.1",
                infrastructure=True,
            )
        control_root = _configured_control_root()
        mcp_pythonpath = _configured_mcp_pythonpath()
        private_root = bridge.artifact_root.parent.parent / "private-audit"
        private_root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(private_root, 0o700)
        started = time.monotonic()
        event_snapshots: list[dict[str, Any]] = []
        effective_tools: list[dict[str, Any]] = []
        event_types: dict[str, int] = {}
        final_response = ""
        format_recovery_count = 0
        recovery_forced_request_count = 0
        recovery_validated_finish_count = 0
        recovery_validated_tool_count = 0
        recovery_coalesced_output_count = 0
        recovery_response_shape: dict[str, Any] = {}
        sdk_stop_continuation_count = 0
        broker: Any = None
        llm: Any = None
        recovery_violation_type: type[Exception] | None = None
        provider_tool_policy_type: type[Exception] | None = None
        recovery_protocol_failure = False
        provider_budget_failure = False
        provider_tool_policy_failure = False
        failure_stage = "temporary_directory"
        failure_receipt_emitted = False
        try:
            with tempfile.TemporaryDirectory(prefix="oh-hwe-", dir=control_root) as raw:
                control = Path(raw)
                workspace = control / "empty-workspace"
                persistence = control / "state"
                recovery_state = control / "format-recovery.json"
                workspace.mkdir(mode=0o700)
                persistence.mkdir(mode=0o700)
                failure_stage = "broker_initialization"
                broker = DeepSeekHarnessHweBroker(
                    bridge=bridge,
                    socket_path=control / "b" / "broker.sock",
                    private_audit_root=private_root,
                )
                failure_stage = "llm_initialization"
                from .hwe_tool_choice import (
                    BoundedProviderCallLLM,
                    ProviderCallBudgetExceeded,
                )

                llm_type: Any = BoundedProviderCallLLM
                if settings.tool_choice_policy == "required":
                    from .hwe_tool_choice import RequiredToolChoiceLLM

                    llm_type = RequiredToolChoiceLLM
                elif settings.tool_choice_policy in {
                    "recovery_forced_finish",
                    "recovery_forced_finish_v5",
                }:
                    from .hwe_tool_choice import RecoveryForcedFinishLLM

                    llm_type = RecoveryForcedFinishLLM
                elif settings.tool_choice_policy == "recovery_state_forced_finish_v6":
                    from .hwe_tool_choice import RecoveryStateForcedFinishLLM

                    llm_type = RecoveryStateForcedFinishLLM
                elif settings.tool_choice_policy in {
                    "validated_recovery_state_forced_finish_v7",
                    "validated_recovery_state_forced_finish_v8",
                }:
                    from .hwe_tool_choice import (
                        RecoveryToolChoiceViolation,
                        ValidatedRecoveryStateForcedFinishLLM,
                    )

                    llm_type = ValidatedRecoveryStateForcedFinishLLM
                    recovery_violation_type = RecoveryToolChoiceViolation
                elif (
                    settings.tool_choice_policy
                    == "validated_responses_recovery_state_forced_finish_v9"
                ):
                    from .hwe_tool_choice import (
                        RecoveryToolChoiceViolation,
                        ValidatedResponsesRecoveryStateForcedFinishLLM,
                    )

                    llm_type = ValidatedResponsesRecoveryStateForcedFinishLLM
                    recovery_violation_type = RecoveryToolChoiceViolation
                elif settings.tool_choice_policy in {
                    "validated_responses_recovery_state_required_tool_v11",
                    "validated_responses_recovery_state_required_tool_v12",
                    "validated_responses_recovery_state_required_tool_v13",
                    "validated_responses_recovery_state_required_tool_v14",
                    "validated_responses_recovery_state_required_tool_v15",
                    "validated_responses_recovery_state_required_tool_v16",
                }:
                    from .hwe_tool_choice import RecoveryToolChoiceViolation

                    if settings.tool_choice_policy in {
                        "validated_responses_recovery_state_required_tool_v13",
                        "validated_responses_recovery_state_required_tool_v14",
                        "validated_responses_recovery_state_required_tool_v15",
                        "validated_responses_recovery_state_required_tool_v16",
                    }:
                        from .hwe_tool_choice import (
                            MetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM,
                            ProviderToolArgumentsPolicyError,
                        )

                        llm_type = MetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM
                        if settings.tool_choice_policy in {
                            "validated_responses_recovery_state_required_tool_v14",
                            "validated_responses_recovery_state_required_tool_v15",
                            "validated_responses_recovery_state_required_tool_v16",
                        }:
                            from .hwe_tool_choice import WorkspaceRelativeRequiredToolLLM

                            llm_type = WorkspaceRelativeRequiredToolLLM
                        provider_tool_policy_type = ProviderToolArgumentsPolicyError
                    else:
                        from .hwe_tool_choice import (
                            ValidatedResponsesRecoveryStateRequiredToolLLM,
                        )

                        llm_type = ValidatedResponsesRecoveryStateRequiredToolLLM
                        provider_tool_policy_type = None
                    recovery_violation_type = RecoveryToolChoiceViolation
                llm_options: dict[str, Any] = {}
                if settings.tool_choice_policy in {
                    "recovery_state_forced_finish_v6",
                    "validated_recovery_state_forced_finish_v7",
                    "validated_recovery_state_forced_finish_v8",
                    "validated_responses_recovery_state_forced_finish_v9",
                    "validated_responses_recovery_state_required_tool_v11",
                    "validated_responses_recovery_state_required_tool_v12",
                    "validated_responses_recovery_state_required_tool_v13",
                    "validated_responses_recovery_state_required_tool_v14",
                    "validated_responses_recovery_state_required_tool_v15",
                    "validated_responses_recovery_state_required_tool_v16",
                }:
                    llm_options["recovery_state_path"] = recovery_state
                llm = llm_type(
                    model=settings.model_id,
                    base_url=os.environ[settings.base_url_env],
                    api_key=os.environ[settings.api_key_env],
                    usage_id=f"verigym-hwe-{hashlib.sha256(context.run_id.encode()).hexdigest()[:12]}",
                    temperature=0.0,
                    top_p=1.0,
                    max_input_tokens=settings.max_context_tokens,
                    max_output_tokens=settings.max_output_tokens,
                    seed=settings.seed,
                    num_retries=0,
                    timeout=300,
                    api_mode="chat",
                    stream=False,
                    native_tool_calling=True,
                    disable_vision=True,
                    reasoning_effort="none",
                    litellm_extra_body={"thinking": {"type": "disabled"}},
                    capability_overrides={
                        "supports_reasoning_effort": False,
                        "supports_sampling_params": True,
                        "supports_responses_api": False,
                        "supports_vision": False,
                        "thinking_mode": "none",
                    },
                    max_provider_calls=settings.max_iterations,
                    **llm_options,
                )
                failure_stage = "mcp_configuration"
                server = MCPServer(
                    command="/usr/bin/env",
                    args=[
                        "-i",
                        "PATH=/usr/local/bin:/usr/bin:/bin",
                        "LANG=C.UTF-8",
                        f"PYTHONPATH={mcp_pythonpath}",
                        sys.executable,
                        "-m",
                        "verigym_openhands.hwe_mcp_stdio",
                        "--socket",
                        str(broker.socket_path),
                    ],
                    timeout=1810.0,
                )
                failure_stage = "agent_initialization"
                agent = openhands.Agent(
                    llm=llm,
                    tools=[],
                    include_default_tools=[],
                    mcp_config={"verigym_hwe": server},
                    filter_tools_regex="^(?:" + "|".join(map(re.escape, _TOOL_NAMES)) + ")$",
                    system_prompt=system_prompt,
                    condenser=None,
                    tool_concurrency_limit=1,
                )
                hook_command = " ".join(
                    shlex.quote(value)
                    for value in (
                        sys.executable,
                        str(_stop_hook_script()),
                        "--socket",
                        str(broker.socket_path),
                        "--state",
                        str(recovery_state),
                    )
                )
                hook_config = HookConfig(
                    stop=[
                        HookMatcher(
                            matcher="*",
                            hooks=[HookDefinition(command=hook_command, timeout=5)],
                        )
                    ]
                )
                failure_stage = "conversation_initialization"
                conversation: Any = openhands.Conversation(
                    agent=agent,
                    workspace=workspace,
                    persistence_dir=persistence,
                    plugins=[],
                    callbacks=[],
                    client_tools=[],
                    max_iteration_per_run=settings.max_iterations,
                    stuck_detection=False,
                    hook_config=hook_config,
                    visualizer=None,
                    delete_on_close=True,
                )
                failure_stage = "broker_start"
                broker.start()
                try:
                    failure_stage = "send_message"
                    conversation.send_message(task_prompt)
                    try:
                        failure_stage = "agent_loop"
                        with _frozen_hook_locale():
                            asyncio.run(
                                asyncio.wait_for(
                                    conversation.arun(),
                                    timeout=settings.process_timeout_s,
                                )
                            )
                    except Exception as exc:
                        receipt = _sdk_failure_receipt(exc, conversation.state.events)
                        receipt.update(_recovery_choice_counts(llm))
                        receipt["recovery_response_shape"] = _recovery_response_shape(llm)
                        receipt["failure_stage"] = failure_stage
                        bridge.emit_event(
                            "openhands_sdk_hwe_episode_failed",
                            receipt,
                        )
                        failure_receipt_emitted = True
                        if recovery_violation_type is not None and _exception_chain_contains(
                            exc, recovery_violation_type
                        ):
                            recovery_protocol_failure = True
                        elif _exception_chain_contains(exc, ProviderCallBudgetExceeded):
                            provider_budget_failure = True
                        elif provider_tool_policy_type is not None and _exception_chain_contains(
                            exc, provider_tool_policy_type
                        ):
                            provider_tool_policy_failure = True
                        else:
                            raise
                    initial_recovery_count = read_recovery_count(recovery_state)
                    initial_choice_counts = _recovery_choice_counts(llm)
                    initial_stats = broker.stats()
                    if (
                        _requires_sdk_stop_continuation(
                            tool_choice_policy=settings.tool_choice_policy,
                            recovery_count=initial_recovery_count,
                            choice_counts=initial_choice_counts,
                        )
                        and not provider_budget_failure
                        and not recovery_protocol_failure
                        and not initial_stats.finished
                        and initial_stats.policy_failure is None
                        and initial_stats.infrastructure_failure is None
                    ):
                        remaining_s = settings.process_timeout_s - (time.monotonic() - started)
                        if remaining_s <= 0:
                            raise TimeoutError("OpenHands HWE continuation exhausted wall time")
                        failure_stage = "sdk_stop_continuation"
                        conversation.send_message(
                            OPENHANDS_SDK_STOP_CONTINUATION_MESSAGE,
                            sender="verigym_adapter",
                        )
                        sdk_stop_continuation_count = 1
                        try:
                            with _frozen_hook_locale():
                                asyncio.run(
                                    asyncio.wait_for(
                                        conversation.arun(),
                                        timeout=remaining_s,
                                    )
                                )
                        except Exception as exc:
                            receipt = _sdk_failure_receipt(exc, conversation.state.events)
                            receipt.update(_recovery_choice_counts(llm))
                            receipt["recovery_response_shape"] = _recovery_response_shape(llm)
                            receipt["failure_stage"] = failure_stage
                            bridge.emit_event(
                                "openhands_sdk_hwe_episode_failed",
                                receipt,
                            )
                            failure_receipt_emitted = True
                            if recovery_violation_type is not None and _exception_chain_contains(
                                exc, recovery_violation_type
                            ):
                                recovery_protocol_failure = True
                            elif _exception_chain_contains(exc, ProviderCallBudgetExceeded):
                                provider_budget_failure = True
                            elif (
                                provider_tool_policy_type is not None
                                and _exception_chain_contains(exc, provider_tool_policy_type)
                            ):
                                provider_tool_policy_failure = True
                            else:
                                raise
                    choice_counts = _recovery_choice_counts(llm)
                    recovery_forced_request_count = choice_counts["recovery_forced_request_count"]
                    recovery_validated_finish_count = choice_counts[
                        "recovery_validated_finish_count"
                    ]
                    recovery_validated_tool_count = choice_counts["recovery_validated_tool_count"]
                    recovery_coalesced_output_count = choice_counts[
                        "recovery_coalesced_output_count"
                    ]
                    recovery_response_shape = _recovery_response_shape(llm)
                    format_recovery_count = read_recovery_count(recovery_state)
                    if format_recovery_count:
                        bridge.emit_event(
                            "openhands_sdk_hwe_format_recovery_observed",
                            {
                                "policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                                "recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
                                "recovery_count": format_recovery_count,
                                "same_session": True,
                                "whole_episode_retries": 0,
                                "model_visible_content_persisted": False,
                            },
                        )
                    post_stage = "tool_contract"
                    try:
                        if sorted(conversation.agent.tools_map) != _TOOL_NAMES:
                            raise OpenHandsTrajectoryInfrastructureError(
                                "OpenHands exposed tools outside the exact HWE contract"
                            )
                        post_stage = "event_inventory"
                        for event in conversation.state.events:
                            event_type = type(event).__name__
                            event_types[event_type] = event_types.get(event_type, 0) + 1
                        post_stage = "final_response"
                        final_response = get_agent_final_response(conversation.state.events)
                        if settings.capture_training_transcript:
                            post_stage = "event_snapshot"
                            event_snapshots = snapshot_openhands_events(conversation.state.events)
                            post_stage = "tool_snapshot"
                            effective_tools = snapshot_openhands_tools(
                                list(conversation.agent.tools_map.values()),
                                without_sdk_metadata=(
                                    settings.tool_choice_policy
                                    in {
                                        "validated_responses_recovery_state_required_tool_v13",
                                        "validated_responses_recovery_state_required_tool_v14",
                                        "validated_responses_recovery_state_required_tool_v15",
                                        "validated_responses_recovery_state_required_tool_v16",
                                    }
                                ),
                                workspace_relative_constraints=(
                                    settings.tool_choice_policy
                                    in {
                                        "validated_responses_recovery_state_required_tool_v14",
                                        "validated_responses_recovery_state_required_tool_v15",
                                        "validated_responses_recovery_state_required_tool_v16",
                                    }
                                ),
                            )
                    except Exception as exc:
                        receipt = _sdk_failure_receipt(exc, conversation.state.events)
                        receipt["post_episode_stage"] = post_stage
                        bridge.emit_event(
                            "openhands_sdk_hwe_post_episode_failed",
                            receipt,
                        )
                        failure_receipt_emitted = True
                        raise
                finally:
                    try:
                        conversation.close()
                    finally:
                        broker.stop()
                stats = broker.stats()
                broker_events = broker.events()
                broker_call_ids = broker.call_ids()
                broker = None
        except AgentTerminationError:
            raise
        except OpenHandsTrajectoryInfrastructureError as exc:
            raise _termination(
                "openhands_hwe_causal_boundary",
                str(exc),
                infrastructure=True,
            ) from exc
        except Exception as exc:
            if not failure_receipt_emitted:
                receipt = _sdk_failure_receipt(exc, [])
                receipt["failure_stage"] = failure_stage
                bridge.emit_event("openhands_sdk_hwe_episode_failed", receipt)
            raise _termination(
                "openhands_hwe_sdk_episode",
                f"OpenHands HWE episode failed: {type(exc).__name__}",
                infrastructure=True,
            ) from exc
        finally:
            if broker is not None:
                broker.stop()
        stats_value = broker_stats_dict(stats)
        duration_s = time.monotonic() - started
        try:
            provider = _provider_accounting_receipt(
                llm,
                max_provider_calls=settings.max_iterations,
            )
        except OpenHandsTrajectoryInfrastructureError as exc:
            raise _termination(
                "openhands_hwe_provider_accounting",
                str(exc),
                infrastructure=True,
            ) from exc
        accounting = ExternalAgentAccounting(
            process_wall_time_s=duration_s,
            cli_event_count=sum(event_types.values()),
            model_call_count=provider["provider_call_count"],
            external_tool_call_count=stats.tool_calls,
            external_command_count=stats.command_calls,
            public_test_invocation_count=0,
            external_file_read_count=stats.file_reads,
            external_file_write_count=stats.patches,
            external_patch_count=stats.patches,
            input_tokens=provider["input_tokens"],
            output_tokens=provider["output_tokens"],
        )
        identity = _identity(settings, stats.tool_calls, stats.patches)

        def persist_evidence(
            *, trajectory_captured: bool, ordinary_hidden_verifier_pending: bool
        ) -> None:
            bridge.record_accounting(accounting)
            bridge.emit_event("openhands_sdk_identity_observed", identity.model_dump(mode="json"))
            _write_evidence(
                bridge.artifact_root,
                settings=settings,
                stats=stats_value,
                identity=identity,
                accounting=accounting,
                event_types=event_types,
                final_response=final_response,
                duration_s=duration_s,
                provider=provider,
                format_recovery_count=format_recovery_count,
                recovery_forced_request_count=recovery_forced_request_count,
                recovery_validated_finish_count=recovery_validated_finish_count,
                recovery_validated_tool_count=recovery_validated_tool_count,
                recovery_coalesced_output_count=recovery_coalesced_output_count,
                recovery_response_shape=recovery_response_shape,
                sdk_stop_continuation_count=sdk_stop_continuation_count,
                trajectory_captured=trajectory_captured,
                ordinary_hidden_verifier_pending=ordinary_hidden_verifier_pending,
            )

        if stats.infrastructure_failure is not None:
            persist_evidence(
                trajectory_captured=False,
                ordinary_hidden_verifier_pending=False,
            )
            raise _termination(
                "openhands_hwe_broker_infrastructure",
                "OpenHands HWE broker reported an infrastructure failure",
                infrastructure=True,
            )
        if provider_budget_failure:
            persist_evidence(
                trajectory_captured=False,
                ordinary_hidden_verifier_pending=False,
            )
            raise _termination(
                "openhands_hwe_provider_call_budget",
                "OpenHands HWE exhausted its exact provider-request budget",
                infrastructure=False,
            )
        if provider_tool_policy_failure:
            persist_evidence(
                trajectory_captured=False,
                ordinary_hidden_verifier_pending=False,
            )
            raise _termination(
                "openhands_hwe_provider_tool_arguments_policy",
                "OpenHands HWE provider emitted arguments outside the metadata-free policy",
                infrastructure=False,
            )
        recoverable_invalid_arguments = (
            stats.finished
            and stats.rejected_calls > 0
            and set(stats.rejection_codes) <= {"invalid_arguments"}
        )
        if (stats.policy_failure is not None or stats.rejected_calls) and not (
            recoverable_invalid_arguments
        ):
            persist_evidence(
                trajectory_captured=False,
                ordinary_hidden_verifier_pending=False,
            )
            raise _termination(
                "openhands_hwe_action_policy",
                "OpenHands emitted an action outside the HWE contract",
                infrastructure=False,
            )
        if recovery_protocol_failure:
            persist_evidence(
                trajectory_captured=False,
                ordinary_hidden_verifier_pending=False,
            )
            raise _termination(
                "openhands_hwe_recovery_tool_choice_violation",
                "OpenHands HWE provider violated the validated recovery tool contract",
                infrastructure=False,
            )
        if not stats.finished:
            persist_evidence(
                trajectory_captured=False,
                ordinary_hidden_verifier_pending=False,
            )
            raise _termination(
                "openhands_hwe_missing_finish",
                "OpenHands HWE did not complete through typed finish",
                infrastructure=False,
            )
        if settings.capture_training_transcript:
            try:
                self._pending_training_trajectory = build_openhands_training_trajectory(
                    task_id=context.task.id,
                    provider="openai-compatible",
                    model_id=settings.model_id,
                    configuration_fingerprint=settings.configuration_fingerprint,
                    event_snapshots=event_snapshots,
                    tools=effective_tools,
                    broker_turns=hwe_broker_receipts(broker_events, broker_call_ids),
                    tool_contract="hwe_native_shell_v2",
                    recovery_policy_id=OPENHANDS_FORMAT_RECOVERY_POLICY,
                    retain_recoverable_invalid_arguments=recoverable_invalid_arguments,
                    sdk_stop_continuation_count=sdk_stop_continuation_count,
                )
            except OpenHandsTrajectoryInfrastructureError as exc:
                persist_evidence(
                    trajectory_captured=False,
                    ordinary_hidden_verifier_pending=False,
                )
                raise _termination(
                    "openhands_hwe_training_causal_mismatch",
                    str(exc),
                    infrastructure=True,
                ) from exc
            except OpenHandsTrajectoryError as exc:
                persist_evidence(
                    trajectory_captured=False,
                    ordinary_hidden_verifier_pending=False,
                )
                raise _termination(
                    "openhands_hwe_training_ineligible",
                    str(exc),
                    infrastructure=False,
                ) from exc
        persist_evidence(
            trajectory_captured=self._pending_training_trajectory is not None,
            ordinary_hidden_verifier_pending=True,
        )
        return FinalSubmissionAction(
            message="OpenHands completed one typed HWE episode; submit to the verifier."
        )

    def finish(self, result: EpisodeResult) -> None:
        if self._bridge is None:
            return
        summary_path = self._bridge.artifact_root / "summary.json"
        if not summary_path.is_file() or summary_path.is_symlink():
            return
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.update(
            {
                "verigym_run_id": result.run_id,
                "ordinary_verifier_resolved": result.resolved,
                "ordinary_termination_reason": result.termination_reason,
                "training_trajectory_exported": False,
                "model_called_during_finish": False,
                "candidate_modified_during_finish": False,
                "benchmark_score_claimed": False,
            }
        )
        if self._pending_training_trajectory is not None and result.resolved:
            trajectory = set_openhands_verifier_result(
                self._pending_training_trajectory,
                verifier_resolved=True,
            )
            atomic_dump_json(
                self._bridge.artifact_root / "training-trajectory.json",
                trajectory,
            )
            summary.update(
                {
                    "training_trajectory_exported": True,
                    "training_trajectory_hash": trajectory["transcript_hash"],
                    "message_content_persisted": True,
                    "private_reasoning_persisted": False,
                }
            )
        elif self._pending_training_trajectory is not None:
            private_root = self._bridge.artifact_root.parent.parent / "private-audit"
            private_root.mkdir(mode=0o700, exist_ok=True)
            os.chmod(private_root, 0o700)
            candidate_path = private_root / "openhands-training-trajectory-candidate.json"
            atomic_dump_json(candidate_path, self._pending_training_trajectory)
            os.chmod(candidate_path, 0o600)
            summary.update(
                {
                    "training_trajectory_candidate_persisted": True,
                    "training_trajectory_candidate_hash": self._pending_training_trajectory[
                        "transcript_hash"
                    ],
                    "training_trajectory_candidate_private": True,
                }
            )
        atomic_dump_json(summary_path, summary)

    def _configured(
        self,
    ) -> tuple[
        AgentContext,
        ExternalAgentBridge,
        OpenHandsHweSettings,
        str,
        str,
    ]:
        values = (
            self._context,
            self._bridge,
            self._settings,
            self._system_prompt,
            self._task_prompt,
        )
        if any(value is None for value in values):
            raise RuntimeError("OpenHands HWE agent has not been started")
        return values  # type: ignore[return-value]


def _system_prompt(*, workspace_relative: bool = False) -> str:
    prompt = (
        "You are a hardware repository repair agent using the frozen OpenHands HWE native-shell "
        "v2 contract. Every assistant decision must contain exactly one typed tool call. One "
        "same-session format recovery may be supplied if a response omits its tool call. Use only "
        "list_files, read_file, apply_patch, shell, inspect_diff, and finish. Read TASK.md and "
        "relevant source before editing, make only necessary workspace-relative changes, run "
        "focused local diagnostics, inspect the final diff, and call finish exactly once. Never "
        "use network access, hidden verifier assets, reference solutions, credentials, private "
        "reasoning blocks, host paths, other agents, or undeclared tools."
    )
    if not workspace_relative:
        return prompt
    return (
        prompt
        + " Every path and cwd argument must be '.' or a workspace-relative POSIX path with no "
        "leading slash or drive prefix. In command, patch, and summary arguments, refer to "
        "repository files only by workspace-relative path and never copy a controller or host "
        "filesystem path."
    )


def _task_prompt(
    context: AgentContext,
    bridge: ExternalAgentBridge,
    *,
    workspace_relative: bool = False,
) -> str:
    workspace = bridge.workspace_root.resolve(strict=True)
    instructions = [
        "Read TASK.md and relevant source before editing.",
        "Use bounded reads and shell diagnostics.",
        "Use apply_patch for persistent edits.",
        "Inspect the final candidate diff before calling finish exactly once.",
        "Do not ask questions or attempt whole-episode retries.",
    ]
    if workspace_relative:
        instructions.append(
            "Use '.' or paths like 'core/id_stage.sv' for path and cwd arguments; never use a "
            "leading slash or drive-letter prefix, and never copy a host path into any tool "
            "argument."
        )
    payload = {
        "schema_version": "1.0",
        "collection_profile_id": "hwe_production_native_shell_v2",
        "observation_policy_id": "hwe_public_observation_v2",
        "tool_contract_id": "hwe_native_shell_v2",
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
        "instructions": instructions,
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
        if len(values) >= 4000:
            values.append("<tree omitted after 4000 entries>")
            break
    return values


def _configured_control_root() -> Path:
    raw = os.environ.get("VERIGYM_OPENHANDS_BROKER_ROOT")
    if not raw:
        raise ValueError("VERIGYM_OPENHANDS_BROKER_ROOT is required")
    path = Path(raw)
    if path.is_symlink():
        raise ValueError("OpenHands HWE control root cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or len(os.fsencode(resolved)) > 72:
        raise ValueError("OpenHands HWE control root must be a short real directory")
    return resolved


@contextlib.contextmanager
def _frozen_hook_locale() -> Iterator[None]:
    """Give OpenHands hook subprocesses a portable, warning-free POSIX locale."""

    names = ("LANG", "LC_ALL", "LC_CTYPE")
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ[name] = "C"
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _configured_mcp_pythonpath() -> str:
    raw = os.environ.get("VERIGYM_OPENHANDS_MCP_PYTHONPATH")
    if not raw or len(os.fsencode(raw)) > 4096:
        raise ValueError("VERIGYM_OPENHANDS_MCP_PYTHONPATH is required and bounded")
    entries = raw.split(os.pathsep)
    if not 1 <= len(entries) <= 16:
        raise ValueError("OpenHands MCP Python path entry count is invalid")
    resolved: list[str] = []
    for entry in entries:
        path = Path(entry)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("OpenHands MCP Python paths must be absolute non-symlinks")
        target = path.resolve(strict=True)
        if not target.is_dir():
            raise ValueError("OpenHands MCP Python paths must be directories")
        resolved.append(str(target))
    if len(resolved) != len(set(resolved)):
        raise ValueError("OpenHands MCP Python paths must be unique")
    return os.pathsep.join(resolved)


def _stop_hook_script() -> Path:
    path = Path(__file__).with_name("hwe_stop_hook.py")
    if path.is_symlink() or not path.is_file():
        raise ValueError("OpenHands HWE Stop hook must be a regular package file")
    return path.resolve(strict=True)


def _sdk_failure_receipt(exc: BaseException, events: list[Any]) -> dict[str, Any]:
    chain: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    event_types: dict[str, int] = {}
    error_codes: list[str] = []
    for event in events:
        event_type = type(event).__name__
        event_types[event_type] = event_types.get(event_type, 0) + 1
        code = getattr(event, "code", None)
        if isinstance(code, str) and code and len(code) <= 160:
            error_codes.append(code)
    root = exc
    visited: set[int] = set()
    while root.__cause__ is not None and id(root) not in visited:
        visited.add(id(root))
        root = root.__cause__
    receipt: dict[str, Any] = {
        "exception_chain": chain,
        "root_exception_type": type(root).__name__,
        "root_message_sha256": hashlib.sha256(str(root).encode()).hexdigest(),
        "event_type_counts": event_types,
        "last_event_type": type(events[-1]).__name__ if events else None,
        "error_codes": error_codes[-4:],
        "raw_exception_message_persisted": False,
        "raw_model_content_persisted": False,
    }
    violation_tool = getattr(root, "tool_name", None)
    violation_field = getattr(root, "argument_field", None)
    violation_kind = getattr(root, "violation_kind", None)
    if (
        violation_tool in _TOOL_NAMES
        and violation_field
        in {
            "command",
            "cwd",
            "patch",
            "path",
            "security_risk",
            "summary",
            "unparsed",
        }
        and violation_kind in {"forbidden_sdk_metadata", "raw_host_path"}
    ):
        receipt["provider_tool_arguments_violation"] = {
            "tool_name": violation_tool,
            "argument_field": violation_field,
            "violation_kind": violation_kind,
        }
    return receipt


def _identity(
    settings: OpenHandsHweSettings, tool_calls: int, patches: int
) -> ExternalAgentCallIdentity:
    policy_versions = {
        "auto": "v2",
        "required": "v3",
        "recovery_forced_finish": "v4",
        "recovery_forced_finish_v5": "v5",
        "recovery_state_forced_finish_v6": "v6",
        "validated_recovery_state_forced_finish_v7": "v7",
        "validated_recovery_state_forced_finish_v8": "v8",
        "validated_responses_recovery_state_forced_finish_v9": "v10",
        "validated_responses_recovery_state_required_tool_v11": "v11",
        "validated_responses_recovery_state_required_tool_v12": "v12",
        "validated_responses_recovery_state_required_tool_v13": "v13",
        "validated_responses_recovery_state_required_tool_v14": "v14",
        "validated_responses_recovery_state_required_tool_v15": "v15",
        "validated_responses_recovery_state_required_tool_v16": "v16",
    }
    policy_version = policy_versions[settings.tool_choice_policy]
    return ExternalAgentCallIdentity(
        adapter_name="openhands-hwe-agent",
        adapter_version=__version__,
        harness_name="verigym-openhands-hwe-broker-agent",
        requested_model_id=settings.model_id,
        observed_model_id=settings.model_id,
        executable_name="python",
        executable_sha256=hash_bytes(Path(sys.executable).read_bytes()),
        executable_version=f"python-{sys.version_info.major}.{sys.version_info.minor}",
        capability_fingerprint=hashlib.sha256(
            f"openhands-sdk-1.42.1-hwe-{policy_version}".encode()
        ).hexdigest(),
        configuration_fingerprint=settings.configuration_fingerprint,
        invocation_count=1,
        integration_track="openhands_sdk_agent",
        execution_surface="openhands_sdk",
        interaction_class="sdk_agent_broker_tools",
        harness_id=f"openhands-sdk-1.42.1-hwe-native-shell-{policy_version}",
        model_client_kind="sdk_agent_mediated",
        agent_harness_kind="openhands_sdk",
        tool_availability_policy="hwe_exact_six_typed_tools_v2",
        tool_use_policy=(
            "repository_action_state_machine_v2"
            if settings.tool_choice_policy == "auto"
            else "repository_action_state_machine_required_tool_v3"
            if settings.tool_choice_policy == "required"
            else "repository_action_state_machine_recovery_forced_finish_v4"
            if settings.tool_choice_policy == "recovery_forced_finish"
            else "repository_action_state_machine_recovery_forced_finish_merged_v5"
            if settings.tool_choice_policy == "recovery_forced_finish_v5"
            else "repository_action_state_machine_recovery_state_forced_finish_v6"
            if settings.tool_choice_policy == "recovery_state_forced_finish_v6"
            else "repository_action_state_machine_validated_recovery_finish_v7"
            if settings.tool_choice_policy == "validated_recovery_state_forced_finish_v7"
            else "repository_action_state_machine_validated_recovery_finish_v8"
            if settings.tool_choice_policy == "validated_recovery_state_forced_finish_v8"
            else "repository_action_state_machine_metadata_free_sdk_continuation_v13"
            if settings.tool_choice_policy == "validated_responses_recovery_state_required_tool_v13"
            else "repository_action_state_machine_workspace_relative_sdk_continuation_v14"
            if settings.tool_choice_policy == "validated_responses_recovery_state_required_tool_v14"
            else "repository_action_state_machine_nonterminal_recovery_continuation_v15"
            if settings.tool_choice_policy == "validated_responses_recovery_state_required_tool_v15"
            else "repository_action_state_machine_all_string_path_contract_v16"
            if settings.tool_choice_policy == "validated_responses_recovery_state_required_tool_v16"
            else "repository_action_state_machine_validated_responses_sdk_continuation_v12"
            if settings.tool_choice_policy == "validated_responses_recovery_state_required_tool_v12"
            else "repository_action_state_machine_validated_responses_recovery_required_tool_v11"
            if settings.tool_choice_policy == "validated_responses_recovery_state_required_tool_v11"
            else (
                "repository_action_state_machine_validated_responses_recovery_"
                "masked_invalid_arguments_v10"
            )
        ),
        tool_event_count=tool_calls,
        side_effecting_tool_event_count=0,
        read_only_tool_event_count=0,
        external_network_tool_event_count=0,
        mcp_tool_event_count=tool_calls,
        workspace_write_count=patches,
        chat_eval_compatible=False,
        pure_api_model_eval=False,
        direct_api_benchmark=False,
        sandbox_policy="empty_openhands_workspace_brokered_hwe_tools",
        approval_policy="automatic_broker_policy",
        identity_confidence="observed",
        reproducibility_scope="site_specific_cli",
    )


def _write_evidence(
    root: Path,
    *,
    settings: OpenHandsHweSettings,
    stats: dict[str, Any],
    identity: ExternalAgentCallIdentity,
    accounting: ExternalAgentAccounting,
    event_types: dict[str, int],
    final_response: str,
    duration_s: float,
    provider: dict[str, int],
    format_recovery_count: int,
    recovery_forced_request_count: int,
    recovery_validated_finish_count: int,
    recovery_validated_tool_count: int,
    recovery_coalesced_output_count: int,
    recovery_response_shape: dict[str, Any],
    sdk_stop_continuation_count: int,
    trajectory_captured: bool,
    ordinary_hidden_verifier_pending: bool,
) -> None:
    atomic_dump_json(root / "configuration.json", settings.safe_dict())
    atomic_dump_json(root / "broker.json", stats)
    atomic_dump_json(root / "identity.json", identity.model_dump(mode="json"))
    atomic_dump_json(root / "accounting.json", accounting.model_dump(mode="json"))
    atomic_dump_json(
        root / "summary.json",
        {
            "schema_version": "1.0",
            "integration_track": "openhands_sdk_hwe_native_shell",
            "sdk_version": "1.42.1",
            "duration_s": duration_s,
            "provider_call_budget": settings.max_iterations,
            "provider_call_count": provider["provider_call_count"],
            "successful_provider_response_count": provider["successful_provider_response_count"],
            "provider_usage_record_count": provider["provider_usage_record_count"],
            "provider_input_tokens": provider["input_tokens"],
            "provider_output_tokens": provider["output_tokens"],
            "broker_decision_steps": stats.get("decision_steps"),
            "hook_subprocess_locale": "C",
            "event_type_counts": event_types,
            "final_response_sha256": hashlib.sha256(final_response.encode()).hexdigest(),
            "training_trajectory_captured": trajectory_captured,
            "training_trajectory_exported": False,
            "message_content_persisted": False,
            "private_reasoning_persisted": False,
            "local_repository_exposed_to_openhands": False,
            "docker_socket_exposed_to_openhands": False,
            "default_tools_exposed": False,
            "plugins_loaded": False,
            "condenser_enabled": False,
            "tool_choice_policy": settings.tool_choice_policy,
            "whole_episode_retries": 0,
            "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
            "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
            "format_recovery_count": format_recovery_count,
            "recovery_forced_request_count": recovery_forced_request_count,
            "recovery_validated_finish_count": recovery_validated_finish_count,
            "recovery_validated_tool_count": recovery_validated_tool_count,
            "recovery_coalesced_output_count": recovery_coalesced_output_count,
            "recovery_response_shape": recovery_response_shape,
            "recoverable_invalid_arguments": (
                stats.get("finished") is True
                and isinstance(stats.get("rejected_calls"), int)
                and stats.get("rejected_calls", 0) > 0
                and set(stats.get("rejection_codes", [])) <= {"invalid_arguments"}
            ),
            "failed_decisions_retained_as_context": trajectory_captured
            and stats.get("rejected_calls", 0) > 0,
            "failed_decisions_supervised": False,
            "same_session_recovery": True,
            "sdk_stop_continuation_policy_id": OPENHANDS_SDK_STOP_CONTINUATION_POLICY,
            "sdk_stop_continuation_budget": OPENHANDS_SDK_STOP_CONTINUATION_BUDGET,
            "sdk_stop_continuation_count": sdk_stop_continuation_count,
            "sdk_upstream_source_modified": False,
            "termination_authority": "broker_typed_finish",
            "ordinary_hidden_verifier_pending": ordinary_hidden_verifier_pending,
            "benchmark_score_claimed": False,
        },
    )


def _recovery_choice_counts(llm: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for name in (
        "recovery_forced_request_count",
        "recovery_validated_finish_count",
        "recovery_validated_tool_count",
        "recovery_coalesced_output_count",
    ):
        value = getattr(llm, name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OpenHandsTrajectoryInfrastructureError(
                "OpenHands recovery tool-choice counter is invalid"
            )
        result[name] = value
    return result


def _requires_sdk_stop_continuation(
    *,
    tool_choice_policy: str,
    recovery_count: int,
    choice_counts: dict[str, int],
) -> bool:
    """Continue only the frozen SDK stop states that cannot finish in one run."""

    if recovery_count != 1:
        return False
    forced = choice_counts.get("recovery_forced_request_count")
    validated_finish = choice_counts.get("recovery_validated_finish_count")
    validated_tool = choice_counts.get("recovery_validated_tool_count")
    if tool_choice_policy == "validated_responses_recovery_state_required_tool_v12":
        return forced == 0
    if tool_choice_policy in {
        "validated_responses_recovery_state_required_tool_v15",
        "validated_responses_recovery_state_required_tool_v16",
    }:
        return forced == 1 and validated_finish == 0 and validated_tool == 1
    return False


def _provider_accounting_receipt(
    llm: Any,
    *,
    max_provider_calls: int,
) -> dict[str, int]:
    """Bind provider requests and aggregate token usage without retaining content."""

    call_count = getattr(llm, "provider_call_count", None)
    if (
        isinstance(call_count, bool)
        or not isinstance(call_count, int)
        or not 0 <= call_count <= max_provider_calls
    ):
        raise OpenHandsTrajectoryInfrastructureError(
            "OpenHands provider request counter is invalid"
        )
    metrics = getattr(llm, "metrics", None)
    response_latencies = getattr(metrics, "response_latencies", None)
    token_usages = getattr(metrics, "token_usages", None)
    accumulated = getattr(metrics, "accumulated_token_usage", None)
    if not isinstance(response_latencies, list) or not isinstance(token_usages, list):
        raise OpenHandsTrajectoryInfrastructureError("OpenHands provider metrics are unavailable")
    successful_responses = len(response_latencies)
    usage_records = len(token_usages)
    if successful_responses > call_count or usage_records > call_count:
        raise OpenHandsTrajectoryInfrastructureError(
            "OpenHands provider metrics exceed attempted requests"
        )
    input_tokens = getattr(accumulated, "prompt_tokens", None)
    output_tokens = getattr(accumulated, "completion_tokens", None)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (input_tokens, output_tokens)
    ):
        raise OpenHandsTrajectoryInfrastructureError("OpenHands provider token totals are invalid")
    assert isinstance(input_tokens, int)
    assert isinstance(output_tokens, int)
    return {
        "provider_call_count": call_count,
        "successful_provider_response_count": successful_responses,
        "provider_usage_record_count": usage_records,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _recovery_response_shape(llm: Any) -> dict[str, Any]:
    value = getattr(llm, "recovery_response_shape", {})
    if not isinstance(value, dict):
        raise OpenHandsTrajectoryInfrastructureError(
            "OpenHands recovery response shape receipt is invalid"
        )
    allowed_keys = {
        "raw_output_count",
        "raw_output_types",
        "raw_function_names",
        "converted_tool_call_count",
        "converted_tool_names",
        "converted_text_part_count",
    }
    if set(value) - allowed_keys:
        raise OpenHandsTrajectoryInfrastructureError(
            "OpenHands recovery response shape receipt has unknown fields"
        )
    return dict(value)


def _exception_chain_contains(exc: BaseException, expected: type[BaseException]) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    for _index in range(8):
        if current is None or id(current) in seen:
            return False
        if isinstance(current, expected):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _termination(category: str, message: str, *, infrastructure: bool) -> AgentTerminationError:
    return AgentTerminationError(
        TerminationReason.MODEL_ERROR if infrastructure else TerminationReason.POLICY_VIOLATION,
        EpisodeFailure(
            kind="runtime" if infrastructure else "model",
            category=category,
            message=message[:2000],
            infrastructure=infrastructure,
        ),
    )


__all__ = ["OpenHandsHweAgentAdapter"]
