"""Reusable end-to-end run orchestration behind both API and CLI."""

from __future__ import annotations

import platform
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.core.artifact_policy import bound_value
from verigym.core.artifacts import RunLayout
from verigym.core.environment import VeriGymEnv
from verigym.core.episode import EpisodeState, TerminationReason
from verigym.core.errors import ConfigurationError, PathPolicyError
from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.integrity import write_run_artifact_manifest
from verigym.core.loaders import dump_json
from verigym.core.logging import append_json_log
from verigym.core.model_gateway import ModelGateway
from verigym.core.repository_candidate import repository_plan_identity
from verigym.core.repository_observation import (
    RawObservationAuditWriter,
    RepositoryObservationPolicy,
    resolve_repository_observation_policy,
)
from verigym.core.scoring import build_scorecard
from verigym.core.synthesis import SynthesisEvaluation, execute_synthesis_quality
from verigym.core.trace import TraceWriter
from verigym.core.verifier_dag import VerifierExecutor, has_infrastructure_error
from verigym.core.workspace import copy_tree_safely, merge_tree_safely, normalize_relative_path
from verigym.models.base import ModelClient
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.prompts.builder import PromptBuilder
from verigym.prompts.policy import (
    agent_configuration_hash,
    resolve_prompt_policy,
    validate_prompt_policy_binding,
)
from verigym.protocols.repository_action import (
    resolve_repository_action_protocol,
    validate_repository_action_protocol_binding,
)
from verigym.provenance import get_build_provenance
from verigym.registry.collections import Registries, build_registries
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.schemas.agent import EpisodeResult
from verigym.schemas.common import (
    ErrorCategory,
    InteractionMode,
    RuntimeRequirement,
    ToolchainProfile,
    ToolchainProfileRef,
    ToolRequirement,
)
from verigym.schemas.model import GenerationParameters
from verigym.schemas.prompt import ToolPolicySnapshot
from verigym.schemas.repository import RepositoryPublicTestOutcome
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.runtime import SessionSpec, WorkspaceDiff
from verigym.schemas.sampling import SampleSetResult
from verigym.schemas.score import EpisodeFailure
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.task import ResolvedTaskAssets, VeriTask
from verigym.schemas.verifier import VerifierResult, VerifierStatus
from verigym.suites.base import SuiteAdapter
from verigym.tools.base import SynthesisBackendPlugin, ToolContext
from verigym.version import __version__


def _external_agent_artifact_namespace(agent_name: str) -> str:
    if agent_name.startswith("codex-cli-"):
        return "codex_cli"
    if agent_name.startswith("claude-cli-"):
        return "claude_cli"
    if agent_name.startswith("openhands-"):
        return "openhands_sdk"
    if agent_name.startswith("deepseek-harness-"):
        return "deepseek_harness"
    return "external_agent"


def _external_agent_isolation_label(agent_name: str, execution_backend: str) -> str:
    if agent_name.startswith("claude-cli-"):
        return "host_claude_control_plane_runtime_mcp_delegated"
    if agent_name.startswith("openhands-"):
        return "host_openhands_sdk_control_plane_runtime_mcp_delegated"
    if agent_name.startswith("deepseek-harness-"):
        return "host_deepseek_harness_control_plane_runtime_tools_delegated"
    if execution_backend == "docker_outer_runtime_delegated":
        return "docker_outer_runtime_delegated"
    return "codex_cli_sandbox_on_trusted_host"


def _configured_observation_policy(
    options: dict[str, Any],
    *,
    external_agent_selected: bool = False,
    bounded_action_protocol: bool = False,
) -> RepositoryObservationPolicy | None:
    raw = options.get("observation_policy_id", options.get("observation_policy"))
    if raw is None and (
        external_agent_selected
        or bounded_action_protocol
        or options.get("action_protocol") == "repository_action.v2"
    ):
        raw = "repository_observation_v1"
    return resolve_repository_observation_policy(raw)


class VeriGym:
    """High-level service for deterministic task execution."""

    def __init__(self, registries: Registries | None = None) -> None:
        self.registries = registries or build_registries()

    @classmethod
    def from_config(cls, path: str | Path = "verigym.yaml") -> VeriGym:
        """Create a service; project configuration expansion begins after Milestone 4."""

        config_path = Path(path)
        if config_path.exists() and not config_path.is_file():
            raise ConfigurationError(f"configuration path is not a file: {config_path}")
        return cls()

    def load_task(
        self,
        task_id: str,
        suite_source: SuiteSourceConfig | None = None,
    ) -> tuple[Any, VeriTask, ResolvedTaskAssets]:
        if "/" not in task_id:
            raise ConfigurationError("task_id must be '<suite>/<task>'")
        suite_id, native_id = task_id.split("/", 1)
        suite = self.registries.suites.get(suite_id)
        if suite_source is not None:
            suite = suite.with_source(suite_source)
        reference = next(
            (ref for ref in suite.discover() if ref.id == task_id or ref.native_id == native_id),
            None,
        )
        if reference is None:
            raise ConfigurationError(f"task {task_id!r} was not found in suite {suite_id!r}")
        task = suite.load_task(reference)
        assets = suite.resolve_assets(task)
        return suite, task, assets

    def run(self, config: RunConfig) -> RunResult:
        if config.suite_source is None:
            suite, task, assets = self.load_task(config.task_id)
        else:
            suite, task, assets = self.load_task(config.task_id, config.suite_source)
        task_hash = content_hash(task)
        source_hash = task.source.content_hash or hash_directory(Path(assets.visible_root))
        source_snapshot = suite.source_snapshot()
        if config.expected_task_hash is not None and task_hash != config.expected_task_hash:
            raise ConfigurationError("task identity changed after experiment planning")
        if config.expected_source_hash is not None and source_hash != config.expected_source_hash:
            raise ConfigurationError("task source changed after experiment planning")
        if (
            config.expected_suite_source_snapshot is not None
            and source_snapshot != config.expected_suite_source_snapshot
        ):
            raise ConfigurationError("suite source identity changed after experiment planning")
        if config.mode not in task.interaction.supported_modes:
            raise ConfigurationError(
                f"task {task.id} does not support interaction mode {config.mode.value}"
            )
        runtime_plugin: Runtime = self.registries.runtimes.get(config.runtime)
        run_id = config.run_id or self._new_run_id(task.id)
        # Experiment children carry both the immutable planned descriptor and
        # the role-specific Docker configuration. Reconstructing Docker from
        # the verifier-only descriptor would silently discard the external
        # agent image and its credential-isolation controls.
        runtime = (
            runtime_plugin.configure(config.docker_config)
            if config.expected_runtime is not None and config.docker_config is not None
            else runtime_plugin.configure_for_replay(config.expected_runtime)
            if config.expected_runtime is not None
            else runtime_plugin.configure(config.docker_config)
        )
        synthesis_profile: ToolchainProfile | None = None
        resolved_profile: ResolvedToolchainProfile | None = None
        synthesis_backend: SynthesisBackendPlugin | None = None
        try:
            runtime.prepare(run_id)
            if config.toolchain_profile is not None:
                synthesis_profile = self.registries.profiles.get(config.toolchain_profile)
                if synthesis_profile.flow is None:
                    raise ConfigurationError(
                        f"profile {synthesis_profile.id!r} has no synthesis flow"
                    )
                candidate_backend = self.registries.tools.get(synthesis_profile.flow.backend_plugin)
                if not isinstance(candidate_backend, SynthesisBackendPlugin):
                    raise ConfigurationError(
                        f"tool {synthesis_profile.flow.backend_plugin!r} is not a synthesis backend"
                    )
                synthesis_backend = candidate_backend
                reference = suite.reference_solution(task)
                reference_hash = content_hash(reference) if reference is not None else None
                resolved_profile = resolve_toolchain_profile(
                    synthesis_profile,
                    runtime,
                    source_paths=list(task.workspace.entrypoints),
                    top_module=synthesis_profile.flow.top_module,
                    reference_candidate_hash=reference_hash,
                    expected=config.expected_resolved_profile,
                    backend=synthesis_backend,
                )
            # Agent and model registries are intentionally consulted only after profile
            # resolution, so a bad image/tool/asset can never trigger a model lookup.
            agent: AgentAdapter = self.registries.agents.get(config.agent)
            if config.mode not in agent.supported_modes:
                supported = ", ".join(sorted(mode.value for mode in agent.supported_modes))
                raise ConfigurationError(
                    f"agent {config.agent!r} does not support mode {config.mode.value!r}; "
                    f"supported: {supported}"
                )
            model_client: ModelClient | None = None
            prompt_builder: PromptBuilder | None = None
            if agent.requires_model:
                if config.model is None:
                    raise ConfigurationError(
                        f"model-backed agent {config.agent!r} requires --model"
                    )
                configured_model: ModelClient = self.registries.models.get(config.model)
                model_options = config.model_options.model_copy(
                    update={"sample_index": config.sample_index}
                )
                model_client = configured_model.clone_for_run(model_options)
                if agent.prompt_policy_spec is None:
                    prompt_builder = PromptBuilder(config.mode)
            elif config.model is not None:
                raise ConfigurationError(
                    f"agent {config.agent!r} does not use a model; omit --model"
                )
            actual_agent_configuration_hash = agent_configuration_hash(
                agent.descriptor,
                config.agent_options,
            )
            try:
                resolved_prompt_policy = resolve_prompt_policy(
                    interaction_mode=config.mode,
                    agent=agent,
                    agent_options=config.agent_options,
                    task=task,
                )
                resolved_prompt_policy_hash = (
                    resolved_prompt_policy.configuration_fingerprint
                    if resolved_prompt_policy is not None
                    else None
                )
                resolved_action_protocol = resolve_repository_action_protocol(
                    agent_descriptor=agent.descriptor,
                    protocol_spec=agent.action_protocol_spec,
                    agent_options=config.agent_options,
                    task=task,
                )
                if config.expected_agent_configuration_hash is not None:
                    if actual_agent_configuration_hash != config.expected_agent_configuration_hash:
                        raise ValueError("agent execution configuration differs from frozen plan")
                    if config.resolved_agent_configuration_hash != actual_agent_configuration_hash:
                        raise ValueError("batch pre-launch agent resolution was not preserved")
                    validate_prompt_policy_binding(
                        expected=config.expected_prompt_policy,
                        expected_hash=config.expected_prompt_policy_hash,
                        resolved=resolved_prompt_policy,
                        resolved_hash=resolved_prompt_policy_hash,
                    )
                    validate_repository_action_protocol_binding(
                        expected=config.expected_action_protocol,
                        resolved=resolved_action_protocol,
                    )
                    validate_repository_action_protocol_binding(
                        expected=config.resolved_action_protocol,
                        resolved=resolved_action_protocol,
                    )
                    validate_prompt_policy_binding(
                        expected=config.resolved_prompt_policy,
                        expected_hash=config.resolved_prompt_policy_hash,
                        resolved=resolved_prompt_policy,
                        resolved_hash=resolved_prompt_policy_hash,
                    )
                elif any(
                    value is not None
                    for value in (
                        config.expected_prompt_policy,
                        config.expected_prompt_policy_hash,
                        config.resolved_prompt_policy,
                        config.resolved_prompt_policy_hash,
                        config.resolved_agent_configuration_hash,
                        config.expected_action_protocol,
                        config.resolved_action_protocol,
                    )
                ):
                    raise ValueError("run prompt binding is incomplete")
                if (
                    prompt_builder is not None
                    and prompt_builder.descriptor != resolved_prompt_policy
                ):
                    raise ValueError(
                        "model-agent prompt builder differs from resolved prompt policy"
                    )
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc
        except BaseException:
            runtime.close()
            raise
        allowed_tools = (
            []
            if config.mode == InteractionMode.CHAT
            else sorted(
                tool
                for tool in task.interaction.allowed_tools
                if tool not in task.interaction.denied_tools
            )
        )
        denied_tools = sorted(
            set(task.interaction.denied_tools)
            | (
                set(task.interaction.allowed_tools)
                if config.mode == InteractionMode.CHAT
                else set()
            )
        )
        external_agent_selected = "external_coding_agent" in agent.descriptor.capabilities
        if (
            repository_plan_identity(task) is not None
            and (agent.requires_model or external_agent_selected)
            and runtime.descriptor.isolation_level != "docker_standard"
        ):
            runtime.close()
            raise ConfigurationError(
                "model-bearing repository repair requires the Docker security boundary"
            )
        tool_policy = ToolPolicySnapshot(
            allowed_tools=allowed_tools,
            denied_tools=denied_tools,
            allow_general_shell=(
                False
                if config.mode == InteractionMode.CHAT
                else task.interaction.allow_general_shell
            ),
            network_policy=task.interaction.network_policy,
        )
        layout = RunLayout.create(config.output.expanduser().resolve() / run_id)
        trace = TraceWriter(layout.trace, run_id)
        verifier_hash = content_hash(task.verifier)
        run_config_hash = content_hash(config.identity_payload())
        profile = synthesis_profile or suite.toolchain_profile(runtime, self.registries.tools)
        if profile is None:
            profile = self._toolchain_profile(runtime)
        profile_ref = ToolchainProfileRef(
            id=profile.id,
            version=profile.version,
            content_hash=content_hash(profile),
        )
        build_provenance = get_build_provenance()
        runtime_environment = runtime.environment_summary()
        external_process_backend = str(
            runtime_environment.get(
                "external_agent_execution_backend",
                "host_local_trusted",
            )
        )
        manifest = RunManifest(
            run_id=run_id,
            created_at_utc=datetime.now(UTC),
            verigym_version=__version__,
            verigym_commit=build_provenance.source_commit,
            build_provenance=build_provenance,
            task_id=task.id,
            task_hash=task_hash,
            source_hash=source_hash,
            repository_task_identity=repository_plan_identity(task),
            verifier_hash=verifier_hash,
            run_config_hash=run_config_hash,
            suite=task.suite,
            suite_version=task.suite_version,
            interaction_mode=config.mode.value,
            seed=config.seed,
            sample_index=config.sample_index,
            model=model_client.descriptor if model_client is not None else None,
            agent=agent.descriptor,
            agent_harness=agent.descriptor,
            prompt_policy=resolved_prompt_policy,
            action_protocol=resolved_action_protocol,
            tool_policy=tool_policy,
            generation=(
                GenerationParameters(
                    temperature=config.model_options.temperature,
                    top_p=config.model_options.top_p,
                    max_output_tokens=task.budget.max_output_tokens,
                )
                if model_client is not None
                else None
            ),
            agent_configuration_fingerprint=(
                content_hash(
                    {
                        "descriptor": agent.descriptor,
                        "options": config.agent_options,
                    }
                )
                if external_agent_selected
                else None
            ),
            agent_configuration_hash=actual_agent_configuration_hash,
            suite_source=source_snapshot,
            runtime=runtime.descriptor,
            toolchain_profiles=[profile_ref],
            requested_toolchain_profile_id=(
                resolved_profile.profile_id if resolved_profile is not None else None
            ),
            requested_toolchain_profile_version=(
                resolved_profile.profile_version if resolved_profile is not None else None
            ),
            declared_profile_hash=(
                resolved_profile.declared_profile_hash if resolved_profile is not None else None
            ),
            resolved_profile_hash=(
                resolved_profile.resolved_profile_hash if resolved_profile is not None else None
            ),
            resolved_toolchain_profile=resolved_profile,
            synthesis_flow_script_hash=(
                resolved_profile.generated_script_hash if resolved_profile is not None else None
            ),
            reference_strategy=(
                resolved_profile.reference_strategy if resolved_profile is not None else None
            ),
            reference_candidate_hash=(
                resolved_profile.reference_candidate_hash if resolved_profile is not None else None
            ),
            budget=task.budget,
            prompt_policy_hash=resolved_prompt_policy_hash,
            experiment_id=config.experiment_id,
            plan_item_id=config.plan_item_id,
            system_id=config.system_id,
            base_seed=config.base_seed,
            environment_summary={
                "python": platform.python_version(),
                "platform": platform.platform(),
                "python_implementation": platform.python_implementation(),
                "network_policy": task.interaction.network_policy,
                "unsafe_local_runtime": runtime.descriptor.isolation_level == "local_trusted",
                "verifier_isolation": "separate_runtime_session",
                **(
                    {
                        "agent_execution_backend": "docker_outer_runtime_delegated",
                        "credential_bearing_http_location": "trusted_controller",
                        "agent_workspace_credentials": False,
                    }
                    if "api_backed_repository_agent" in agent.descriptor.capabilities
                    and runtime.descriptor.isolation_level == "docker_standard"
                    else {}
                ),
                **(
                    {
                        "external_agent_isolation": _external_agent_isolation_label(
                            agent.descriptor.name,
                            external_process_backend,
                        ),
                        "external_agent_process_backend": external_process_backend,
                        "verigym_runtime_isolation": runtime.descriptor.isolation_level,
                    }
                    if external_agent_selected
                    else {}
                ),
                **runtime_environment,
            },
        )
        dump_json(layout.manifest, manifest)
        dump_json(layout.task_snapshot, task)
        dump_json(layout.artifacts / "toolchain_profile.json", profile)
        if resolved_profile is not None:
            dump_json(layout.artifacts / "resolved_toolchain_profile.json", resolved_profile)
        append_json_log(
            layout.logs / "runtime.log",
            event="runtime_created",
            run_id=run_id,
            task_id=task.id,
            level="warning" if runtime.descriptor.isolation_level == "local_trusted" else "info",
            runtime=runtime.descriptor.name,
            isolation_level=runtime.descriptor.isolation_level,
            warning=(
                "LocalRuntime is for trusted toy tasks only."
                if runtime.descriptor.isolation_level == "local_trusted"
                else None
            ),
        )

        observation_policy = _configured_observation_policy(
            config.agent_options,
            external_agent_selected=external_agent_selected,
            bounded_action_protocol=(
                resolved_action_protocol is not None
                and resolved_action_protocol.state_machine_id
                == "repository_action_state_machine_v2"
            ),
        )
        raw_observation_audit: RawObservationAuditWriter | None = None
        if (
            observation_policy is not None
            and config.agent_options.get("campaign_role") == "training"
            and config.agent_options.get("capture_training_transcript") is True
        ):
            raw_observation_audit = RawObservationAuditWriter(
                layout.root / "private-audit" / "raw-observations.ndjson"
            )
        env = VeriGymEnv(
            task=task,
            assets=assets,
            runtime=runtime,
            tools=self.registries.tools,
            mode=config.mode,
            observation_policy=observation_policy,
            audit_callback=raw_observation_audit,
        )
        verifier_results: list[VerifierResult] = []
        synthesis_evaluation: SynthesisEvaluation | None = None
        episode_failure: EpisodeFailure | None = None
        model_gateway: ModelGateway | None = None
        external_bridge: RuntimeExternalAgentBridge | None = None
        external_workspace_rejected = False
        try:
            observation, _ = env.reset(run_id=run_id, trace=trace)
            assert env.tracker is not None
            assert env.session is not None
            if external_agent_selected:
                external_bridge = RuntimeExternalAgentBridge(
                    session=env.session,
                    artifact_root=layout.artifacts
                    / _external_agent_artifact_namespace(agent.descriptor.name),
                    isolation_level=runtime.descriptor.isolation_level,
                    policy=env.policy,
                    trace=trace,
                    observation_policy=observation_policy,
                    audit_callback=raw_observation_audit,
                )
            model_gateway = (
                ModelGateway(
                    run_id=run_id,
                    client=model_client,
                    trace=trace,
                    tracker=env.tracker,
                    max_visible_bytes=max(
                        task.budget.max_output_bytes_per_tool,
                        resolved_action_protocol.max_response_bytes
                        if resolved_action_protocol is not None
                        else 0,
                    ),
                    temperature=config.model_options.temperature,
                    top_p=config.model_options.top_p,
                    prompt_policy_hash=resolved_prompt_policy_hash,
                    agent_configuration_hash=actual_agent_configuration_hash,
                    action_protocol_hash=(
                        resolved_action_protocol.configuration_fingerprint
                        if resolved_action_protocol is not None
                        else None
                    ),
                )
                if model_client is not None
                else None
            )
            agent.start(
                AgentContext(
                    run_id=run_id,
                    task=task,
                    seed=config.seed,
                    model_gateway=model_gateway,
                    prompt_builder=prompt_builder,
                    max_invalid_actions=config.max_invalid_actions,
                    agent_options=config.agent_options,
                    external_bridge=external_bridge,
                    prompt_policy=resolved_prompt_policy,
                    action_protocol=resolved_action_protocol,
                )
            )
            agent_log = layout.logs / "agent.log"
            while env.state == EpisodeState.RUNNING:
                assert env.tracker is not None
                exhausted = env.tracker.exhausted_before_turn()
                if exhausted is not None:
                    observation, _, _, _, _ = env._truncate(exhausted)
                    break
                started = time.monotonic()
                try:
                    action = agent.act(observation)
                except AgentTerminationError as exc:
                    env.tracker.agent_time_s += time.monotonic() - started
                    episode_failure = exc.failure
                    external_workspace_rejected = (
                        external_bridge is not None and exc.failure.kind == "policy"
                    )
                    try:
                        observation = env.terminate(exc.reason, exc.failure.message)
                    except PathPolicyError as workspace_error:
                        # A rejected external episode can leave a symlink or
                        # another object that makes even diff observation
                        # unsafe. terminate() has already moved the state to
                        # VERIFYING; retain the policy failure without reading
                        # or following the object.
                        external_workspace_rejected = True
                        trace.emit(
                            "codex_cli_unsafe_workspace_observation_rejected",
                            {"message": str(workspace_error)},
                        )
                    trace.emit(
                        "agent_terminated",
                        {
                            "termination_reason": exc.reason.value,
                            "failure": exc.failure.model_dump(mode="json"),
                        },
                    )
                    append_json_log(
                        agent_log,
                        event="agent_terminated",
                        run_id=run_id,
                        task_id=task.id,
                        termination_reason=exc.reason.value,
                        failure=exc.failure.model_dump(mode="json"),
                    )
                    break
                env.tracker.agent_time_s += time.monotonic() - started
                logged_action, action_truncated = bound_value(
                    action.model_dump(mode="json"),
                    task.budget.max_output_bytes_per_tool,
                )
                append_json_log(
                    agent_log,
                    event="agent_action",
                    run_id=run_id,
                    task_id=task.id,
                    action=logged_action,
                    content_truncated=action_truncated,
                )
                observation, _, terminated, truncated, _ = env.step(action)
                if terminated or truncated:
                    break
            if external_bridge is not None:
                try:
                    external_bridge.validate_workspace()
                except PathPolicyError as exc:
                    external_workspace_rejected = True
                    if episode_failure is None:
                        episode_failure = EpisodeFailure(
                            kind="policy",
                            category="external_workspace_policy",
                            message=str(exc),
                        )
                    env.termination_reason = TerminationReason.POLICY_VIOLATION
                    if env.state == EpisodeState.RUNNING:
                        try:
                            observation = env.terminate(
                                TerminationReason.POLICY_VIOLATION,
                                str(exc),
                            )
                        except PathPolicyError as workspace_error:
                            trace.emit(
                                "codex_cli_unsafe_workspace_observation_rejected",
                                {"message": str(workspace_error)},
                            )
                    trace.emit(
                        "codex_cli_policy_violation",
                        {"category": "external_workspace_policy", "message": str(exc)},
                    )
            if model_client is not None:
                model_client.export_run_artifacts(layout.artifacts / "codex_cli")
            if not external_workspace_rejected:
                manifest.repository_public_tests = self._run_repository_public_tests(
                    task=task,
                    session=env.session,
                    trace=trace,
                    max_output_bytes=task.budget.max_output_bytes_per_tool,
                )
                public_infrastructure = next(
                    (
                        outcome
                        for outcome in manifest.repository_public_tests
                        if outcome.category
                        in {
                            ErrorCategory.INTERNAL_ERROR.value,
                            ErrorCategory.LICENSE_UNAVAILABLE.value,
                            ErrorCategory.PARSER_ERROR.value,
                            ErrorCategory.SANDBOX_ERROR.value,
                            ErrorCategory.TOOL_NOT_FOUND.value,
                            ErrorCategory.UNSUPPORTED_VERSION.value,
                        }
                    ),
                    None,
                )
                if public_infrastructure is not None and episode_failure is None:
                    episode_failure = EpisodeFailure(
                        kind="runtime",
                        category=f"repository_public_test_{public_infrastructure.category}",
                        message=(
                            "trusted repository public-test infrastructure failed for "
                            f"{public_infrastructure.test_id}"
                        ),
                        infrastructure=True,
                    )
            if env.termination_reason is None:
                env.termination_reason = TerminationReason.RUNTIME_ERROR
            assert env.session is not None and env.tracker is not None
            env.session.freeze()
            if external_workspace_rejected:
                # Never copy or follow a workspace tree rejected by policy.
                # An empty quarantine snapshot keeps the run terminal and
                # auditable while the structured policy failure remains the
                # authoritative outcome.
                diff = WorkspaceDiff()
                layout.workspace_diff.write_text(
                    "# candidate quarantined: external workspace policy violation\n",
                    encoding="utf-8",
                )
                layout.candidate.mkdir()
            else:
                diff = env.session.snapshot_diff()
                layout.workspace_diff.write_text(diff.patch, encoding="utf-8")
                layout.export_candidate(
                    env.session.root,
                    reference_root=Path(assets.visible_root),
                )
                repository_candidate = suite.freeze_repository_candidate(
                    task=task,
                    candidate_dir=layout.candidate,
                    run_root=layout.root,
                    artifact_root=layout.artifacts,
                )
                if repository_candidate is not None:
                    manifest.repository_candidate = repository_candidate
                    trace.emit(
                        "repository_candidate_frozen",
                        {
                            "base_repository_hash": (
                                repository_candidate.patch.base_repository_hash
                            ),
                            "candidate_repository_hash": (
                                repository_candidate.patch.candidate_repository_hash
                            ),
                            "patch_hash": repository_candidate.patch.patch_hash,
                            "changed_files": repository_candidate.patch.changed_files,
                            "reapply_exact": repository_candidate.patch.reapply_exact,
                        },
                    )
            candidate_hash = hash_directory(layout.candidate)
            manifest.candidate_hash = candidate_hash
            dump_json(layout.manifest, manifest)
            trace.emit(
                "artifact_created",
                {"kind": "candidate", "path": "candidate", "content_hash": candidate_hash},
            )
            trace.emit("verifier_started", {"graph_hash": verifier_hash})
            verifier_started = time.monotonic()
            if external_workspace_rejected:
                verifier_results = [
                    VerifierResult(
                        node_id=node.id,
                        plugin=node.plugin,
                        status=VerifierStatus.SKIPPED,
                        error_category=ErrorCategory.SUCCESS,
                        message="candidate quarantined after external workspace policy violation",
                        request=node.request,
                    )
                    for node in task.verifier.nodes
                ]
            else:
                verifier_results = self._verify_candidate(
                    suite=suite,
                    task=task,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=layout.candidate,
                    artifact_root=layout.artifacts,
                    agent_session=env.session,
                )
            if (
                not external_workspace_rejected
                and synthesis_profile is not None
                and resolved_profile is not None
                and synthesis_backend is not None
            ):
                by_id = {result.node_id: result for result in verifier_results}
                correctness_passed = all(
                    by_id.get(node_id) is not None
                    and by_id[node_id].status == VerifierStatus.PASSED
                    for node_id in task.scoring.correctness_required_nodes
                ) and not has_infrastructure_error(verifier_results)
                synthesis_evaluation = execute_synthesis_quality(
                    suite=suite,
                    task=task,
                    candidate_dir=layout.candidate,
                    runtime=runtime,
                    profile=synthesis_profile,
                    resolved=resolved_profile,
                    artifact_root=layout.artifacts,
                    plugin=synthesis_backend,
                    correctness_passed=correctness_passed,
                )
                verifier_results.extend(synthesis_evaluation.results)
                reference_summary = (
                    layout.artifacts
                    / synthesis_backend.artifact_namespace
                    / "reference_summary.json"
                )
                if reference_summary.is_file():
                    manifest.reference_summary_hash = hash_bytes(reference_summary.read_bytes())
            env.tracker.verifier_time_s = time.monotonic() - verifier_started
            for result in verifier_results:
                trace.emit(
                    "verifier_node_result",
                    {
                        "node_id": result.node_id,
                        "plugin": result.plugin,
                        "status": result.status.value,
                        "error_category": result.error_category.value,
                        "message": result.message,
                        "duration_s": result.duration_s,
                        "artifacts": result.artifacts,
                    },
                )
            for result in verifier_results:
                append_json_log(
                    layout.logs / "verifier.log",
                    event="verifier_node_result",
                    run_id=run_id,
                    task_id=task.id,
                    node_id=result.node_id,
                    status=result.status.value,
                    error_category=result.error_category.value,
                    message=result.message,
                )
            runtime_public_test_invocation_count = env.session.public_test_invocation_count
            env.close()
            runtime.close()
            manifest.runtime = runtime.descriptor
            manifest.model_observations = (
                [item.model_copy(deep=True) for item in model_gateway.observations]
                if model_gateway is not None
                else []
            )
            manifest.action_protocol_records = agent.action_protocol_records()
            manifest.external_agent_observations = (
                external_bridge.observations if external_bridge is not None else []
            )
            external_accounting = (
                external_bridge.accounting if external_bridge is not None else None
            )
            if manifest.repository_task_identity is not None:
                manifest.repository_public_tool_invocation_count = (
                    runtime_public_test_invocation_count
                    + (
                        external_accounting.public_test_invocation_count
                        if external_accounting is not None
                        and external_accounting.public_test_invocation_count is not None
                        else 0
                    )
                )
            if (
                external_bridge is not None
                and external_bridge.configuration_fingerprint is not None
            ):
                manifest.agent_configuration_fingerprint = external_bridge.configuration_fingerprint
            manifest.environment_summary.update(runtime.environment_summary())
            dump_json(layout.manifest, manifest)
            trace.emit(
                "runtime_cleanup_result",
                {
                    "runtime": manifest.runtime.name,
                    "isolation_level": manifest.runtime.isolation_level,
                    "complete": (
                        manifest.runtime.cleanup.complete
                        if manifest.runtime.cleanup is not None
                        else True
                    ),
                    "warnings": (
                        len(manifest.runtime.cleanup.warnings)
                        if manifest.runtime.cleanup is not None
                        else 0
                    ),
                },
            )
            scorecard = build_scorecard(
                run_id=run_id,
                task=task,
                results=verifier_results,
                diff=diff,
                tracker=env.tracker,
                termination_reason=env.termination_reason,
                task_hash=task_hash,
                candidate_hash=candidate_hash,
                run_config_hash=run_config_hash,
                profile_refs=[profile_ref],
                isolation_level=runtime.descriptor.isolation_level,
                episode_failure=episode_failure,
                resolved_profile=resolved_profile,
                candidate_synthesis=(
                    synthesis_evaluation.candidate if synthesis_evaluation is not None else None
                ),
                reference_synthesis=(
                    synthesis_evaluation.reference if synthesis_evaluation is not None else None
                ),
                external_accounting=(
                    external_bridge.accounting if external_bridge is not None else None
                ),
            )
            dump_json(layout.scorecard, scorecard)
            trace.emit(
                "artifact_created",
                {"kind": "scorecard", "path": "scorecard.json"},
            )
            final_state = (
                EpisodeState.COMPLETED if scorecard.status == "completed" else EpisodeState.FAILED
            )
            env.state = final_state
            trace.emit(
                "episode_terminated",
                {
                    "state": final_state.value,
                    "termination_reason": env.termination_reason.value,
                    "resolved": scorecard.resolved,
                    "scorecard_status": scorecard.status,
                },
            )
            agent.finish(
                EpisodeResult(
                    run_id=run_id,
                    resolved=scorecard.resolved,
                    termination_reason=env.termination_reason.value,
                )
            )
            write_run_artifact_manifest(layout.root, run_id)
            return RunResult(run_dir=layout.root, manifest=manifest, scorecard=scorecard)
        finally:
            if raw_observation_audit is not None:
                raw_observation_audit.finalize()
            env.close()
            runtime.close()

    def run_samples(
        self,
        config: RunConfig,
        *,
        samples: int,
        pass_k: list[int] | tuple[int, ...] = (1,),
    ) -> SampleSetResult:
        """Run independent ChatEval children and emit a canonical pass@k report."""

        from verigym.core.sampling import run_sample_set

        return run_sample_set(self, config, samples=samples, pass_k=pass_k)

    def _verify_candidate(
        self,
        *,
        suite: SuiteAdapter | None = None,
        task: VeriTask,
        assets: ResolvedTaskAssets,
        runtime: Runtime,
        candidate_dir: Path,
        artifact_root: Path,
        agent_session: RuntimeSession | None = None,
    ) -> list[VerifierResult]:
        if suite is not None:
            managed = suite.verify_candidate(
                task=task,
                candidate_dir=candidate_dir,
                artifact_root=artifact_root,
            )
            if managed is not None:
                expected = {node.id: node for node in task.verifier.nodes}
                if len(managed) != len(expected) or {result.node_id for result in managed} != set(
                    expected
                ):
                    raise ConfigurationError(
                        "suite-managed verifier results do not match the frozen verifier graph"
                    )
                for result in managed:
                    node = expected[result.node_id]
                    if result.plugin != node.plugin or result.request != node.request:
                        raise ConfigurationError(
                            "suite-managed verifier result identity differs from its frozen node"
                        )
                return managed
        verifier_session: RuntimeSession | None = None
        protected_hashes: dict[str, str] = {}
        with tempfile.TemporaryDirectory(prefix="verigym-verifier-staging-") as temporary:
            staging = Path(temporary)
            copy_tree_safely(candidate_dir, staging)
            for index, hidden_root in enumerate(assets.hidden_roots):
                asset = (
                    task.workspace.hidden_assets[index]
                    if index < len(task.workspace.hidden_assets)
                    else None
                )
                mount_path = asset.mount_path if asset and asset.mount_path else "hidden"
                merge_tree_safely(Path(hidden_root), staging, mount_path=mount_path)
                protected_root = staging / normalize_relative_path(mount_path, allow_root=True)
                for protected in sorted(protected_root.rglob("*")):
                    if protected.is_file():
                        relative = protected.relative_to(staging).as_posix()
                        protected_hashes[relative] = hash_bytes(protected.read_bytes())
            for asset in assets.hidden_assets:
                if asset.kind != "inline" or asset.content is None or asset.mount_path is None:
                    raise ConfigurationError(
                        "resolved inline hidden assets require content and a mount path"
                    )
                mount_path = normalize_relative_path(asset.mount_path)
                payload = asset.content.encode("utf-8")
                if asset.content_hash is not None and hash_bytes(payload) != asset.content_hash:
                    raise ConfigurationError(
                        f"resolved hidden asset hash mismatch at {mount_path!r}"
                    )
                destination = staging / mount_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                protected_hashes[mount_path] = hash_bytes(payload)
            verifier_session = runtime.create_session(
                SessionSpec(
                    source_dir=str(staging),
                    label="verifier",
                    max_output_bytes=task.budget.max_output_bytes_per_tool,
                )
            )
        try:
            if agent_session is not None and verifier_session.root == agent_session.root:
                raise RuntimeError("agent and verifier sessions must be physically distinct")
            executor = VerifierExecutor(self.registries.tools)
            results = executor.execute(
                task.verifier,
                verifier_session,
                artifact_root,
                max_output_bytes=task.budget.max_output_bytes_per_tool,
            )
            integrity_ok = all(
                (verifier_session.root / relative).is_file()
                and hash_bytes((verifier_session.root / relative).read_bytes()) == expected
                for relative, expected in protected_hashes.items()
            )
            if not integrity_ok:
                results.append(
                    VerifierResult(
                        node_id="runtime_hidden_integrity",
                        plugin="runtime",
                        status=VerifierStatus.ERROR,
                        error_category=ErrorCategory.SANDBOX_ERROR,
                        message="verifier hidden-input integrity check failed",
                    )
                )
            return results
        finally:
            verifier_session.close()

    def _toolchain_profile(self, runtime: Runtime) -> ToolchainProfile:
        runtime_image = runtime.descriptor.image
        if runtime_image is None:
            compiler_version = self.registries.tools.get("iverilog.compile").health_check().version
            runner_version = self.registries.tools.get("iverilog.run").health_check().version
        else:
            compiler_version = runtime_image.iverilog_version
            runner_version = runtime_image.vvp_version
        return ToolchainProfile(
            id="toy-iverilog-v1",
            version="1.0.0",
            description="Public deterministic Icarus profile for the toy RTL counter.",
            tools=[
                ToolRequirement(name="iverilog", version=compiler_version),
                ToolRequirement(name="vvp", version=runner_version),
            ],
            runtime=RuntimeRequirement(runtime=runtime.descriptor.name),
            container_image=(
                runtime_image.requested_reference if runtime_image is not None else None
            ),
            container_digest=(
                runtime_image.resolved_image_id if runtime_image is not None else None
            ),
            deterministic=True,
            reproducibility_scope="public",
        )

    def _run_repository_public_tests(
        self,
        *,
        task: VeriTask,
        session: RuntimeSession,
        trace: TraceWriter,
        max_output_bytes: int,
    ) -> list[RepositoryPublicTestOutcome]:
        repository = task.metadata.get("repository_repair")
        if repository is None:
            return []
        if not isinstance(repository, dict):
            raise ConfigurationError("repository task metadata is malformed")
        identifiers = repository.get("public_test_ids")
        if not isinstance(identifiers, list) or not all(
            isinstance(value, str) for value in identifiers
        ):
            raise ConfigurationError("repository public-test identity is malformed")
        plugin = self.registries.tools.get("repository.public_test")
        outcomes: list[RepositoryPublicTestOutcome] = []
        for test_id in sorted(identifiers):
            request = plugin.validate_request({"test_id": test_id})
            completed = session.execute_public_test(test_id)
            result = plugin.parse_result(
                request,
                completed,
                ToolContext(
                    session=session,
                    max_output_bytes=max_output_bytes,
                ),
            )
            network_policy = result.metadata.get("network_policy")
            if network_policy not in {"none", "host_local_trusted"}:
                raise ConfigurationError(
                    "repository public-test result omitted its runtime network identity"
                )
            outcome = RepositoryPublicTestOutcome(
                test_id=test_id,
                passed=result.success,
                category=result.category.value,
                exit_code=result.exit_code,
                duration_s=result.duration_s,
                output_truncated=result.output_truncated,
                stdout_sha256=hash_bytes(completed.stdout.encode("utf-8")),
                stderr_sha256=hash_bytes(completed.stderr.encode("utf-8")),
                launcher_protocol="verigym_public_test_v1",
                public_assets_read_only=bool(result.metadata.get("public_assets_read_only")),
                network_policy=cast(
                    Literal["none", "host_local_trusted"],
                    network_policy,
                ),
            )
            outcomes.append(outcome)
            trace.emit(
                "repository_public_test_result",
                outcome.model_dump(mode="json"),
            )
        return outcomes

    @staticmethod
    def _new_run_id(task_id: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        slug = task_id.replace("/", "-")
        return f"{timestamp}-{slug}-{uuid.uuid4().hex[:8]}"
