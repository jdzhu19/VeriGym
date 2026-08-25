"""OpenHands SDK Agent/Conversation adapter with only broker-owned tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from verigym.core.hashing import hash_bytes
from verigym.core.repository_tool_broker import (
    RepositoryToolBroker,
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
from verigym.protocols.repository_action import repository_tool_definitions

from ._version import __version__
from .config import OpenHandsSettings, openhands_settings
from .trajectory import (
    OpenHandsTrajectoryError,
    OpenHandsTrajectoryInfrastructureError,
    build_openhands_training_trajectory,
    repository_broker_receipts,
    set_openhands_verifier_result,
    snapshot_openhands_events,
    snapshot_openhands_tools,
)


class OpenHandsRepositoryAgentAdapter(AgentAdapter):
    """Run Qwen through OpenHands without granting OpenHands the task workspace."""

    requires_model = False
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id="openhands_repository_broker_task_context_v1",
        prompt_contract_version="1.0.0",
        task_context_policy="repository_visible_task_context_v1",
        base_instruction_policy="openhands_repository_action_agent_v1",
        content_visibility_policy="public_task_context_and_mcp_workspace_only_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=True,
    )
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="openhands-repository-agent",
        version=__version__,
        api_version=PLUGIN_API_VERSION,
        provider="openhands-sdk",
        capabilities=[
            "external_coding_agent",
            "sdk_agent",
            "provider_native_tool_calls",
            "runtime_mcp_tools",
            "repository_action.v2",
            "single_external_episode",
            "verifier_gated_training_trajectory",
            "exact_tool_schema_capture",
        ],
    )

    def __init__(self) -> None:
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._settings: OpenHandsSettings | None = None
        self._prompt: str | None = None
        self._launched = False
        self._artifact_root: Path | None = None
        self._pending_training_trajectory: dict[str, Any] | None = None

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None or bridge.isolation_level != "docker_standard":
            raise ValueError("OpenHands repository agent requires the Docker runtime bridge")
        settings = openhands_settings(
            context.agent_options,
            task_wall_time_s=context.task.budget.max_wall_time_s,
        )
        policy = context.prompt_policy
        if policy is None or policy.id != self.prompt_policy_spec.prompt_contract_id:
            raise ValueError("OpenHands repository prompt contract is not frozen")
        if (
            policy.agent_version_id != settings.agent_version_id
            or policy.agent_version_hash != settings.agent_version_hash
            or policy.memory_pack_hash is not None
        ):
            raise ValueError("OpenHands policy version differs from its resolved prompt")
        prompt = validate_prompt_text(_agent_prompt(context, bridge), policy)
        self._context = context
        self._bridge = bridge
        self._settings = settings
        self._prompt = prompt
        self._launched = False
        self._artifact_root = bridge.artifact_root
        self._pending_training_trajectory = None

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._launched:
            raise _termination("multiple_sdk_episodes", "OpenHands launched more than once")
        self._launched = True
        context, bridge, settings, prompt = self._configured()
        try:
            import openhands.sdk as openhands  # type: ignore[import-not-found]
            from openhands.sdk.conversation import (  # type: ignore[import-not-found]
                get_agent_final_response,
            )
            from openhands.sdk.mcp import MCPServer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise _termination("sdk_unavailable", "OpenHands SDK 1.42.1 is unavailable") from exc
        if openhands.__version__ != "1.42.1":
            raise _termination("sdk_version", "OpenHands SDK differs from frozen version 1.42.1")
        broker_root = _configured_broker_root()
        started = time.monotonic()
        event_count = 0
        final_response = ""
        training_trajectory: dict[str, Any] | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="openhands-", dir=broker_root) as raw:
                control = Path(raw)
                workspace = control / "empty-workspace"
                persistence = control / "state"
                workspace.mkdir(mode=0o700)
                persistence.mkdir(mode=0o700)
                broker = RepositoryToolBroker(
                    bridge=bridge,
                    socket_path=control / "b" / "mcp.sock",
                    public_test_ids=_public_test_ids(context),
                    capture_training_transcript=settings.capture_training_transcript,
                    campaign_role=settings.campaign_role,
                )
                llm = openhands.LLM(
                    model=settings.model_id,
                    base_url=os.environ[settings.base_url_env],
                    api_key=os.environ[settings.api_key_env],
                    usage_id=f"verigym-{hashlib.sha256(context.run_id.encode()).hexdigest()[:12]}",
                )
                allowed = [
                    definition["name"] for definition in repository_tool_definitions(dialect="mcp")
                ]
                server = MCPServer(
                    command="/usr/bin/env",
                    args=[
                        "-i",
                        "PATH=/usr/local/bin:/usr/bin:/bin",
                        "LANG=C.UTF-8",
                        sys.executable,
                        "-m",
                        "verigym_openhands.repository_mcp_stdio",
                        "--socket",
                        str(broker.socket_path),
                    ],
                    timeout=1810.0,
                )
                agent = openhands.Agent(
                    llm=llm,
                    tools=[],
                    include_default_tools=[],
                    mcp_config={"verigym": server},
                    filter_tools_regex="^(?:" + "|".join(map(re.escape, allowed)) + ")$",
                    system_prompt=_system_prompt(),
                )
                conversation = openhands.Conversation(
                    agent=agent,
                    workspace=workspace,
                    persistence_dir=persistence,
                    plugins=[],
                    callbacks=[],
                    client_tools=[],
                    max_iteration_per_run=settings.max_iterations,
                    stuck_detection=False,
                    visualizer=None,
                    delete_on_close=True,
                )
                broker.start()
                try:
                    conversation.send_message(prompt)
                    if sorted(agent.tools_map) != sorted(allowed):
                        raise RuntimeError(
                            "OpenHands exposed tools outside the repository registry"
                        )
                    asyncio.run(
                        asyncio.wait_for(conversation.arun(), timeout=settings.process_timeout_s)
                    )
                    event_count = len(conversation.state.events)
                    final_response = get_agent_final_response(conversation.state.events)
                    event_snapshots = (
                        snapshot_openhands_events(conversation.state.events)
                        if settings.capture_training_transcript
                        else []
                    )
                    effective_tools = (
                        snapshot_openhands_tools(list(agent.tools_map.values()))
                        if settings.capture_training_transcript
                        else []
                    )
                finally:
                    try:
                        conversation.close()
                    finally:
                        broker.stop()
                broker_stats = broker.stats()
                if not broker_stats.finished:
                    raise RuntimeError("OpenHands did not terminate through the broker finish tool")
                if settings.capture_training_transcript:
                    try:
                        training_trajectory = build_openhands_training_trajectory(
                            task_id=context.task.id,
                            provider="openai-compatible",
                            model_id=settings.model_id,
                            configuration_fingerprint=settings.configuration_fingerprint,
                            event_snapshots=event_snapshots,
                            tools=effective_tools,
                            broker_turns=repository_broker_receipts(broker.training_turns()),
                            tool_contract="repository_action.v2",
                        )
                    except OpenHandsTrajectoryInfrastructureError as exc:
                        raise _termination(
                            "training_trajectory_causal_mismatch",
                            str(exc),
                            infrastructure=True,
                        ) from exc
                    except OpenHandsTrajectoryError as exc:
                        raise _termination(
                            "training_trajectory_ineligible",
                            str(exc),
                            infrastructure=False,
                        ) from exc
        except AgentTerminationError:
            raise
        except Exception as exc:
            raise _termination(
                "sdk_episode", f"OpenHands episode failed: {type(exc).__name__}"
            ) from exc
        duration = time.monotonic() - started
        self._pending_training_trajectory = training_trajectory
        identity = _identity(settings, broker_stats)
        accounting = ExternalAgentAccounting(
            process_wall_time_s=duration,
            cli_event_count=event_count,
            external_tool_call_count=broker_stats.tool_calls,
            external_command_count=0,
            public_test_invocation_count=broker_stats.public_test_calls,
            external_file_read_count=broker_stats.file_reads,
            external_file_write_count=0,
            external_patch_count=broker_stats.patches,
        )
        bridge.emit_event("openhands_sdk_identity_observed", identity.model_dump(mode="json"))
        bridge.record_accounting(accounting)
        _write_evidence(
            bridge.artifact_root,
            settings=settings,
            broker=broker_stats,
            identity=identity,
            accounting=accounting,
            duration_s=duration,
            event_count=event_count,
            final_response=final_response,
            training_trajectory_captured=training_trajectory is not None,
        )
        return FinalSubmissionAction(
            message="OpenHands broker episode finished; submit the candidate to VeriGym."
        )

    def finish(self, result: EpisodeResult) -> None:
        if self._artifact_root is None:
            return
        path = self._artifact_root / "summary.json"
        if not path.is_file() or path.is_symlink():
            return
        current = json.loads(path.read_text(encoding="utf-8"))
        current.update(
            {
                "verigym_run_id": result.run_id,
                "ordinary_verifier_resolved": result.resolved,
                "ordinary_termination_reason": result.termination_reason,
                "development_pilot": self._settings is not None
                and self._settings.campaign_role == "development",
                "benchmark_score_claimed": False,
                "training_trajectory_captured": self._pending_training_trajectory is not None,
                "training_trajectory_exported": False,
            }
        )
        if self._pending_training_trajectory is not None and result.resolved:
            trajectory = set_openhands_verifier_result(
                self._pending_training_trajectory,
                verifier_resolved=True,
            )
            _atomic_json(self._artifact_root / "training-trajectory.json", trajectory)
            current.update(
                {
                    "training_trajectory_exported": True,
                    "training_trajectory_hash": trajectory["transcript_hash"],
                    "message_content_persisted": True,
                    "private_reasoning_persisted": False,
                }
            )
        _atomic_json(path, current)

    def _configured(self) -> tuple[AgentContext, ExternalAgentBridge, OpenHandsSettings, str]:
        values = (self._context, self._bridge, self._settings, self._prompt)
        if any(value is None for value in values):
            raise RuntimeError("OpenHands repository agent has not been started")
        return values  # type: ignore[return-value]


def _identity(
    settings: OpenHandsSettings,
    broker: RepositoryToolBrokerStats,
) -> ExternalAgentCallIdentity:
    return ExternalAgentCallIdentity(
        adapter_name="openhands-repository-agent",
        adapter_version=__version__,
        harness_name="verigym-openhands-broker-agent",
        requested_model_id=settings.model_id,
        observed_model_id=settings.model_id,
        executable_name="python",
        executable_sha256=hash_bytes(Path(sys.executable).read_bytes()),
        executable_version=f"python-{sys.version_info.major}.{sys.version_info.minor}",
        capability_fingerprint=hashlib.sha256(b"openhands-sdk-1.42.1").hexdigest(),
        configuration_fingerprint=settings.configuration_fingerprint,
        invocation_count=1,
        integration_track="openhands_sdk_agent",
        execution_surface="openhands_sdk",
        interaction_class="sdk_agent_broker_tools",
        harness_id="openhands-sdk-1.42.1-repository-action-v2",
        model_client_kind="sdk_agent_mediated",
        agent_harness_kind="openhands_sdk",
        tool_availability_policy="verigym_mcp_only_no_default_tools_v1",
        tool_use_policy="repository_action_state_machine_v2",
        tool_event_count=broker.tool_calls,
        side_effecting_tool_event_count=0,
        read_only_tool_event_count=0,
        external_network_tool_event_count=0,
        mcp_tool_event_count=broker.tool_calls,
        workspace_write_count=broker.patches,
        chat_eval_compatible=False,
        pure_api_model_eval=False,
        direct_api_benchmark=False,
        sandbox_policy="empty_local_workspace_mcp_only",
        approval_policy="automatic_broker_policy",
        identity_confidence="observed",
        reproducibility_scope="site_specific_cli",
    )


def _agent_prompt(context: AgentContext, bridge: ExternalAgentBridge) -> str:
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
        "observation_policy": "repository_observation_v1",
        "public_test_ids": list(_public_test_ids(context)),
        "instructions": [
            "Use exactly one supplied repository function per turn.",
            "Start with a shallow list_files view; use a bounded line range or concise read_file "
            "view for large files. Omitted content is explicitly marked.",
            "Read visible files before editing and use apply_patch for changes.",
            "Run a declared public test when available.",
            "Inspect the diff, then call finish exactly once.",
            "Shell, network, host files, hidden assets, and reference solutions are unavailable.",
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _system_prompt() -> str:
    return (
        "You are a bounded repository repair agent. Only the supplied repository functions are "
        "available. Use one function per turn, inspect the diff, and call finish when complete."
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
    raw = os.environ.get("VERIGYM_OPENHANDS_BROKER_ROOT")
    if not raw:
        raise ValueError("VERIGYM_OPENHANDS_BROKER_ROOT is required")
    path = Path(raw)
    if path.is_symlink():
        raise ValueError("OpenHands broker root cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or len(os.fsencode(resolved)) > 72:
        raise ValueError("OpenHands broker root must be a short real directory")
    return resolved


def _write_evidence(
    root: Path,
    *,
    settings: OpenHandsSettings,
    broker: RepositoryToolBrokerStats,
    identity: ExternalAgentCallIdentity,
    accounting: ExternalAgentAccounting,
    duration_s: float,
    event_count: int,
    final_response: str,
    training_trajectory_captured: bool,
) -> None:
    _atomic_json(root / "configuration.json", settings.safe_dict())
    _atomic_json(root / "broker.json", broker.__dict__)
    _atomic_json(root / "identity.json", identity.model_dump(mode="json"))
    _atomic_json(root / "accounting.json", accounting.model_dump(mode="json"))
    _atomic_json(
        root / "summary.json",
        {
            "schema_version": "1.0",
            "integration_track": "openhands_sdk_agent",
            "sdk_version": "1.42.1",
            "duration_s": duration_s,
            "event_count": event_count,
            "final_response_sha256": hashlib.sha256(final_response.encode()).hexdigest(),
            "message_content_persisted": False,
            "private_reasoning_persisted": False,
            "local_repository_exposed": False,
            "docker_socket_exposed": False,
            "default_tools_exposed": False,
            "plugins_loaded": False,
            "ordinary_hidden_verifier_pending": True,
            "benchmark_score_claimed": False,
            "training_trajectory_captured": training_trajectory_captured,
            "training_trajectory_exported": False,
        },
    )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    from verigym.experiments.state import atomic_dump_json

    atomic_dump_json(path, value)


def _termination(
    category: str, message: str, *, infrastructure: bool = True
) -> AgentTerminationError:
    return AgentTerminationError(
        TerminationReason.MODEL_ERROR if infrastructure else TerminationReason.POLICY_VIOLATION,
        EpisodeFailure(
            kind="model",
            category=category,
            message=message[:2000],
            infrastructure=infrastructure,
        ),
    )


__all__ = ["OpenHandsRepositoryAgentAdapter"]
