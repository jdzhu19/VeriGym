"""Immutable deterministic experiment plan expansion."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from verigym.core.agent_feedback import (
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import ConfigurationError, MissingDependencyError
from verigym.core.hashing import content_hash, hash_directory
from verigym.core.orchestrator import VeriGym
from verigym.core.repository_candidate import repository_plan_identity
from verigym.core.verifier_profiles import (
    resolve_verifier_profile,
    task_with_verifier_profile,
)
from verigym.experiments.identity import (
    correctness_definition_hash,
    derive_child_seed,
    derive_experiment_id,
    evaluation_config_payload,
    normalized_runtime_descriptor,
    normalized_system_identity_payload,
    plan_item_identity_payload,
    plan_items_hash_payload,
    runtime_identity_hash,
)
from verigym.experiments.schemas import (
    ExperimentConfig,
    ExperimentPlan,
    PlanItem,
    PlannedSystemIdentity,
)
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.profiles.validation import validate_profile
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.prompts.policy import agent_configuration_hash, resolve_prompt_policy
from verigym.protocols.repository_action import resolve_repository_action_protocol
from verigym.provenance import get_build_provenance
from verigym.runtimes.base import Runtime
from verigym.schemas.common import ToolchainProfile, ToolchainProfileRef
from verigym.schemas.model import GenerationParameters, ModelRunConfig
from verigym.schemas.prompt import ToolPolicySnapshot
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.task import TaskRef, VeriTask
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile
from verigym.tools.base import SynthesisBackendPlugin
from verigym.version import __version__


class ExperimentPlanner:
    """Resolve a strict config into a timestamp-free ordered execution plan."""

    def __init__(self, service: VeriGym | None = None) -> None:
        self.service = service or VeriGym()

    def build(self, config: ExperimentConfig) -> ExperimentPlan:
        config = ExperimentConfig.model_validate(config.model_dump(mode="python"))
        self._validate_output_root(config.output.root)
        config_hash = content_hash(config.identity_payload())
        evaluation_payload = evaluation_config_payload(config)
        evaluation_config_hash = content_hash(evaluation_payload)
        suite, tasks, source_snapshot = self._resolve_tasks(config)
        verifier_profile, resolved_verifier_profiles, tasks = self._resolve_verifier_profiles(
            config,
            tasks,
        )
        task_records = [
            {
                "task_id": task.id,
                "task_hash": content_hash(task),
                "source_hash": self._task_source_hash(task, suite.resolve_assets(task)),
            }
            for task in tasks
        ]
        planned_count = (
            len(tasks) * len(config.systems) * len(config.runs.seeds) * config.runs.samples_per_task
        )
        if planned_count > config.execution.max_plan_items:
            raise ConfigurationError(
                f"experiment expansion has {planned_count:,} plan items, exceeding the "
                f"configured max_plan_items={config.execution.max_plan_items:,}"
            )
        task_set_hash = content_hash(task_records)
        source_identity_hash = content_hash(
            {
                "suite": suite.descriptor,
                "source_snapshot": source_snapshot,
                "tasks": task_records,
            }
        )

        runtime, frozen_docker = self._prepare_runtime(config, evaluation_config_hash)
        try:
            default_profiles = self._execution_profiles(suite, tasks, runtime)
            resolved_profiles = self._resolve_quality_profiles(config, suite, tasks, runtime)
            systems = self._resolve_systems(config)
            items = self._expand(
                config=config,
                tasks=tasks,
                source_snapshot=source_snapshot,
                source_identity_hash=source_identity_hash,
                evaluation_config_hash=evaluation_config_hash,
                systems=systems,
                runtime=runtime,
                frozen_docker=frozen_docker,
                default_profiles=default_profiles,
                resolved_profiles=resolved_profiles,
                verifier_profile=verifier_profile,
                resolved_verifier_profiles=resolved_verifier_profiles,
            )
            items = self._order_items(items, config.execution.plan_order_policy)
            child_seeds = [item.child_seed for item in items]
            if len(child_seeds) != len(set(child_seeds)):
                raise ConfigurationError(
                    "derived child-seed collision; change the experiment sampling identity"
                )
            self._verify_task_stability(
                config,
                task_records,
                resolved_verifier_profiles,
            )
        finally:
            runtime.close()

        plan_hash = content_hash(plan_items_hash_payload(items))
        experiment_id = derive_experiment_id(config.name, plan_hash)
        build_provenance = get_build_provenance()
        return ExperimentPlan(
            experiment_id=experiment_id,
            config_hash=config_hash,
            evaluation_config_hash=evaluation_config_hash,
            task_set_hash=task_set_hash,
            source_identity_hash=source_identity_hash,
            plan_hash=plan_hash,
            verigym_version=__version__,
            verigym_commit=build_provenance.source_commit,
            build_provenance=build_provenance,
            config=config,
            items=items,
        )

    def verify_frozen_inputs(self, plan: ExperimentPlan) -> None:
        """Check filesystem/profile identities without model or runtime execution."""

        self.verify_plan_integrity(plan)
        config = plan.config
        suite, tasks, source_snapshot = self._resolve_tasks(config, check_tools=False)
        verifier_profile, current_verifier_profiles, tasks = self._resolve_verifier_profiles(
            config,
            tasks,
        )
        del verifier_profile
        planned_verifier_profiles: dict[str, ResolvedVerifierToolProfile] = {}
        for item in plan.items:
            if item.resolved_verifier_profile is not None:
                previous = planned_verifier_profiles.setdefault(
                    item.task_id,
                    item.resolved_verifier_profile,
                )
                if previous != item.resolved_verifier_profile:
                    raise ConfigurationError(
                        "planned verifier profile identity differs across repeated task items"
                    )
        if current_verifier_profiles != planned_verifier_profiles:
            raise ConfigurationError("resolved verifier profile changed after planning")
        task_records = [
            {
                "task_id": task.id,
                "task_hash": content_hash(task),
                "source_hash": self._task_source_hash(task, suite.resolve_assets(task)),
            }
            for task in tasks
        ]
        if content_hash(task_records) != plan.task_set_hash:
            raise ConfigurationError("task/source identity changed after the experiment was frozen")
        current_source_hash = content_hash(
            {
                "suite": suite.descriptor,
                "source_snapshot": source_snapshot,
                "tasks": task_records,
            }
        )
        if current_source_hash != plan.source_identity_hash:
            raise ConfigurationError("suite source identity changed after plan construction")
        if config.profile is not None:
            profile = self.service.registries.profiles.get(config.profile)
            if profile.flow is None:
                raise ConfigurationError(f"profile {profile.id!r} has no synthesis flow")
            backend = self.service.registries.tools.get(profile.flow.backend_plugin)
            if not isinstance(backend, SynthesisBackendPlugin):
                raise ConfigurationError("planned profile backend is not a synthesis backend")
            validation = validate_profile(profile, backend)
            if not validation.valid:
                raise ConfigurationError("; ".join(validation.errors))
            declared_hash = content_hash(profile)
            expected = {item.declared_profile_hash for item in plan.items}
            if expected != {declared_hash}:
                raise ConfigurationError("declared profile identity changed after planning")

    def verify_plan_integrity(self, plan: ExperimentPlan) -> None:
        """Validate all stored hashes without consulting plugins or external state."""

        ExperimentConfig.model_validate(plan.config.model_dump(mode="python"))
        if content_hash(plan.config.identity_payload()) != plan.config_hash:
            raise ConfigurationError("experiment configuration hash does not match its payload")
        evaluation_hash = content_hash(evaluation_config_payload(plan.config))
        if evaluation_hash != plan.evaluation_config_hash:
            raise ConfigurationError("evaluation configuration hash does not match its payload")
        serialized = plan_items_hash_payload(plan.items)
        if content_hash(serialized) != plan.plan_hash:
            raise ConfigurationError("ordered plan hash does not match its plan items")
        if derive_experiment_id(plan.config.name, plan.plan_hash) != plan.experiment_id:
            raise ConfigurationError("experiment ID does not match its immutable plan identity")
        for item, raw in zip(plan.items, serialized, strict=True):
            if content_hash(plan_item_identity_payload(raw)) != item.plan_item_id:
                raise ConfigurationError(
                    f"plan item {item.plan_index} identity does not match its payload"
                )

    def _resolve_tasks(
        self,
        config: ExperimentConfig,
        *,
        check_tools: bool = True,
    ) -> tuple[Any, list[VeriTask], Any]:
        try:
            suite = self.service.registries.suites.get(config.suite.id)
        except Exception as exc:
            raise ConfigurationError(str(exc)) from exc
        if config.suite.source is not None:
            suite = suite.with_source(
                SuiteSourceConfig(
                    source_root=config.suite.source,
                    variant=config.suite.variant,
                    strict_compatibility=config.suite.strict_compatibility,
                )
            )
        report = suite.validate_source()
        if not report.valid:
            raise ConfigurationError("suite source validation failed: " + "; ".join(report.errors))
        references = sorted(suite.discover(), key=lambda ref: ref.id)
        selected = self._select_references(config, references)
        tasks = [suite.load_task(reference) for reference in selected]
        configured_verifier = (
            load_verifier_profile(config.verifier_profile_file)
            if config.verifier_profile_file is not None
            else None
        )
        for task in tasks:
            if task.id != task.id.strip() or not task.id.startswith(f"{config.suite.id}/"):
                raise ConfigurationError(f"suite returned an invalid task identity: {task.id!r}")
            if config.runs.mode not in task.interaction.supported_modes:
                raise ConfigurationError(
                    f"task {task.id!r} does not support mode {config.runs.mode.value!r}"
                )
            if check_tools and config.runtime.id == "local":
                for plugin_name in sorted({node.plugin for node in task.verifier.nodes}):
                    if (
                        configured_verifier is not None
                        and plugin_name == configured_verifier.source_plugin
                    ):
                        continue
                    health = self.service.registries.tools.get(plugin_name).health_check()
                    if not health.healthy:
                        raise MissingDependencyError(
                            f"required verifier tool {plugin_name!r} is unavailable: "
                            f"{health.message}"
                        )
        return suite, tasks, suite.source_snapshot()

    def _resolve_verifier_profiles(
        self,
        config: ExperimentConfig,
        tasks: list[VeriTask],
    ) -> tuple[
        VerifierToolProfile | None,
        dict[str, ResolvedVerifierToolProfile],
        list[VeriTask],
    ]:
        if config.verifier_profile_file is None:
            return None, {}, tasks
        if config.runtime.id != "local":
            raise ConfigurationError("verifier MCP profiles require runtime.id='local'")
        profile = load_verifier_profile(config.verifier_profile_file)
        if profile.id != config.verifier_profile:
            raise ConfigurationError("experiment verifier profile ID differs from its file")
        resolved: dict[str, ResolvedVerifierToolProfile] = {}
        transformed: list[VeriTask] = []
        for task in tasks:
            item = resolve_verifier_profile(
                task=task,
                profile=profile,
                tools=self.service.registries.tools,
            )
            resolved[task.id] = item
            transformed.append(task_with_verifier_profile(task, profile))
        return profile, resolved, transformed

    @staticmethod
    def _select_references(
        config: ExperimentConfig,
        references: list[TaskRef],
    ) -> list[TaskRef]:
        by_full = {reference.id: reference for reference in references}
        by_native = {reference.native_id: reference for reference in references}
        selected: list[TaskRef] = []
        seen: set[str] = set()
        for pattern in config.suite.tasks.include:
            is_glob = any(character in pattern for character in "*?[")
            if is_glob:
                matches = [
                    reference
                    for reference in references
                    if fnmatch.fnmatchcase(reference.id, pattern)
                    or fnmatch.fnmatchcase(reference.native_id, pattern)
                ]
            else:
                reference = by_full.get(pattern) or by_native.get(pattern)
                if reference is None:
                    raise ConfigurationError(f"unknown explicit task ID: {pattern!r}")
                matches = [reference]
            for reference in matches:
                if reference.id in seen:
                    raise ConfigurationError(f"task {reference.id!r} was selected more than once")
                seen.add(reference.id)
                selected.append(reference)
        excluded: set[str] = set()
        for pattern in config.suite.tasks.exclude:
            is_glob = any(character in pattern for character in "*?[")
            if not is_glob and pattern not in by_full and pattern not in by_native:
                raise ConfigurationError(f"unknown explicit task ID: {pattern!r}")
            excluded.update(
                reference.id
                for reference in references
                if fnmatch.fnmatchcase(reference.id, pattern)
                or fnmatch.fnmatchcase(reference.native_id, pattern)
            )
        result = sorted(
            (reference for reference in selected if reference.id not in excluded),
            key=lambda reference: reference.id,
        )
        if not result:
            raise ConfigurationError("experiment task selection is empty")
        return result

    def _prepare_runtime(
        self,
        config: ExperimentConfig,
        evaluation_config_hash: str,
    ) -> tuple[Runtime, DockerRuntimeConfig | None]:
        try:
            plugin = self.service.registries.runtimes.get(config.runtime.id)
            runtime = plugin.configure(config.runtime.docker)
        except Exception as exc:
            raise ConfigurationError(str(exc)) from exc
        try:
            health = runtime.health_check()
            if not health.healthy:
                raise MissingDependencyError(
                    f"runtime {config.runtime.id!r} is unavailable: {health.message}"
                )
            frozen_docker = config.runtime.docker
            if config.runtime.id == "docker":
                runtime.prepare(f"experiment-plan-{evaluation_config_hash[:16]}")
                image = runtime.descriptor.image
                if image is None:
                    raise MissingDependencyError(
                        "Docker planning produced no immutable image identity"
                    )
                assert frozen_docker is not None
                frozen_docker = frozen_docker.model_copy(
                    update={"image": image.resolved_image_id, "pull_policy": "never"}
                )
            return runtime, frozen_docker
        except BaseException:
            runtime.close()
            raise

    def _execution_profiles(
        self,
        suite: Any,
        tasks: Iterable[VeriTask],
        runtime: Runtime,
    ) -> dict[str, ToolchainProfile]:
        profiles: dict[str, ToolchainProfile] = {}
        for task in tasks:
            profile = suite.toolchain_profile(runtime, self.service.registries.tools)
            if profile is None:
                profile = self.service._toolchain_profile(runtime)
            image = runtime.descriptor.image
            if image is not None and profile.container_digest == image.resolved_image_id:
                # Batch children are constrained to the immutable image ID.
                # Freeze the default profile using the same reference spelling
                # that configure_for_replay will use for each child.
                profile = profile.model_copy(update={"container_image": image.resolved_image_id})
            profiles[task.id] = profile
        return profiles

    def _resolve_quality_profiles(
        self,
        config: ExperimentConfig,
        suite: Any,
        tasks: Iterable[VeriTask],
        runtime: Runtime,
    ) -> dict[str, ResolvedToolchainProfile]:
        if config.profile is None:
            return {}
        profile = self.service.registries.profiles.get(config.profile)
        if profile.flow is None:
            raise ConfigurationError(f"profile {profile.id!r} has no synthesis flow")
        candidate_backend = self.service.registries.tools.get(profile.flow.backend_plugin)
        if not isinstance(candidate_backend, SynthesisBackendPlugin):
            raise ConfigurationError(
                f"tool {profile.flow.backend_plugin!r} is not a synthesis backend"
            )
        validation = validate_profile(profile, candidate_backend)
        if not validation.valid:
            raise ConfigurationError("; ".join(validation.errors))
        resolved: dict[str, ResolvedToolchainProfile] = {}
        for task in tasks:
            reference = suite.reference_solution(task)
            resolved[task.id] = resolve_toolchain_profile(
                profile,
                runtime,
                source_paths=list(task.workspace.entrypoints),
                top_module=profile.flow.top_module,
                reference_candidate_hash=(
                    content_hash(reference) if reference is not None else None
                ),
                backend=candidate_backend,
            )
        return resolved

    def _resolve_systems(self, config: ExperimentConfig) -> list[PlannedSystemIdentity]:
        systems: list[PlannedSystemIdentity] = []
        for selected in sorted(config.systems, key=lambda item: item.id):
            try:
                agent = self.service.registries.agents.get(selected.agent.id)
            except Exception as exc:
                raise ConfigurationError(str(exc)) from exc
            if config.runs.mode not in agent.supported_modes:
                raise ConfigurationError(
                    f"agent {selected.agent.id!r} does not support mode {config.runs.mode.value!r}"
                )
            if agent.requires_model and selected.model is None:
                raise ConfigurationError(
                    f"model-backed agent {selected.agent.id!r} requires a model"
                )
            if not agent.requires_model and selected.model is not None:
                raise ConfigurationError(
                    f"model-free agent {selected.agent.id!r} must not specify a model"
                )
            model_descriptor = None
            model_hash = None
            model_options = selected.model.options if selected.model else None
            if selected.model is not None:
                try:
                    model = self.service.registries.models.get(selected.model.id)
                except Exception as exc:
                    raise ConfigurationError(str(exc)) from exc
                for sample_index in range(config.runs.samples_per_task):
                    try:
                        clone = model.clone_for_run(
                            selected.model.options.model_copy(update={"sample_index": sample_index})
                        )
                    except Exception as exc:
                        raise ConfigurationError(
                            f"model {selected.model.id!r} cannot produce independent sample "
                            f"{sample_index}: {exc}"
                        ) from exc
                    if sample_index == 0:
                        model_descriptor = clone.descriptor
                model_hash = content_hash(
                    {"descriptor": model_descriptor, "options": selected.model.options}
                )
            systems.append(
                PlannedSystemIdentity(
                    system_id=selected.id,
                    agent_id=selected.agent.id,
                    agent_descriptor=agent.descriptor,
                    agent_configuration_hash=agent_configuration_hash(
                        agent.descriptor,
                        selected.agent.options,
                    ),
                    agent_options=selected.agent.options,
                    agent_requires_model=agent.requires_model,
                    model_id=selected.model.id if selected.model is not None else None,
                    model_descriptor=model_descriptor,
                    model_configuration_hash=model_hash,
                    model_options=model_options or ModelRunConfig(),
                )
            )
        return systems

    def _expand(
        self,
        *,
        config: ExperimentConfig,
        tasks: list[VeriTask],
        source_snapshot: Any,
        source_identity_hash: str,
        evaluation_config_hash: str,
        systems: list[PlannedSystemIdentity],
        runtime: Runtime,
        frozen_docker: DockerRuntimeConfig | None,
        default_profiles: dict[str, ToolchainProfile],
        resolved_profiles: dict[str, ResolvedToolchainProfile],
        verifier_profile: VerifierToolProfile | None,
        resolved_verifier_profiles: dict[str, ResolvedVerifierToolProfile],
    ) -> list[PlanItem]:
        runtime_descriptor = normalized_runtime_descriptor(runtime.descriptor)
        runtime_hash = runtime_identity_hash(runtime_descriptor)
        profile = (
            self.service.registries.profiles.get(config.profile)
            if config.profile is not None
            else None
        )
        suite_source = (
            SuiteSourceConfig(
                source_root=config.suite.source,
                variant=config.suite.variant,
                strict_compatibility=config.suite.strict_compatibility,
            )
            if config.suite.source is not None
            else None
        )
        items: list[PlanItem] = []
        for task in sorted(tasks, key=lambda item: item.id):
            task_hash = content_hash(task)
            assets = self.service.registries.suites.get(config.suite.id)
            if suite_source is not None:
                assets = assets.with_source(suite_source)
            source_hash = self._task_source_hash(task, assets.resolve_assets(task))
            task_source_identity = content_hash(
                {
                    "experiment_source_identity": source_identity_hash,
                    "task": task.id,
                    "task_source": task.source,
                    "source_hash": source_hash,
                }
            )
            verifier_hash = content_hash(task.verifier)
            correctness_hash = correctness_definition_hash(task)
            repository_identity = repository_plan_identity(task)
            tool_policy = self._tool_policy(task, config.runs.mode)
            resolved = resolved_profiles.get(task.id)
            resolved_verifier = resolved_verifier_profiles.get(task.id)
            feedback_contract = resolve_agent_feedback_contract(
                task=task,
                ppa_enabled=config.runs.agent_ppa_feedback,
                ppa_max_executions=config.runs.agent_ppa_max_calls,
                resolved_profile=resolved,
                profile_backend=(
                    profile.flow.backend_plugin
                    if profile is not None and profile.flow is not None
                    else None
                ),
            )
            execution_task = task_with_agent_feedback_contract(task, feedback_contract)
            for system in systems:
                agent = self.service.registries.agents.get(system.agent_id)
                try:
                    prompt = resolve_prompt_policy(
                        interaction_mode=config.runs.mode,
                        agent=agent,
                        agent_options=system.agent_options,
                        task=execution_task,
                    )
                    action_protocol = resolve_repository_action_protocol(
                        agent_descriptor=agent.descriptor,
                        protocol_spec=agent.action_protocol_spec,
                        agent_options=system.agent_options,
                        task=execution_task,
                    )
                except ValueError as exc:
                    raise ConfigurationError(
                        f"cannot resolve prompt policy for system {system.system_id!r}: {exc}"
                    ) from exc
                system_identity = normalized_system_identity_payload(system)
                system_hash = content_hash(system_identity)
                for base_seed in config.runs.seeds:
                    for sample_index in range(config.runs.samples_per_task):
                        child_seed = derive_child_seed(
                            evaluation_config_hash=evaluation_config_hash,
                            task_hash=task_hash,
                            system_identity_hash=system_hash,
                            base_seed=base_seed,
                            sample_index=sample_index,
                        )
                        execution_profile = profile or default_profiles[task.id]
                        profile_ref = ToolchainProfileRef(
                            id=execution_profile.id,
                            version=execution_profile.version,
                            content_hash=content_hash(execution_profile),
                        )
                        generation = (
                            GenerationParameters(
                                temperature=system.model_options.temperature,
                                top_p=system.model_options.top_p,
                                max_output_tokens=task.budget.max_output_tokens,
                            )
                            if system.model_descriptor is not None
                            else None
                        )
                        raw: dict[str, Any] = {
                            "schema_version": "1.0",
                            "plan_index": len(items),
                            "plan_item_id": "0" * 64,
                            "task_id": task.id,
                            "task_hash": task_hash,
                            "source_hash": source_hash,
                            "source_identity_hash": task_source_identity,
                            "suite": task.suite,
                            "suite_version": task.suite_version,
                            "release_id": None,
                            "suite_source": suite_source,
                            "suite_source_snapshot": source_snapshot,
                            "category": self._metadata_text(task, "category"),
                            "difficulty": self._metadata_text(task, "difficulty"),
                            "interaction_mode": config.runs.mode,
                            "system": system,
                            "prompt_policy": prompt,
                            "prompt_policy_hash": (
                                prompt.configuration_fingerprint if prompt is not None else None
                            ),
                            "agent_feedback_contract": feedback_contract,
                            "tool_policy": tool_policy,
                            "tool_policy_hash": content_hash(tool_policy),
                            "base_seed": base_seed,
                            "sample_index": sample_index,
                            "child_seed": child_seed,
                            "runtime_id": config.runtime.id,
                            "runtime_descriptor": runtime_descriptor,
                            "runtime_identity_hash": runtime_hash,
                            "docker_config": frozen_docker,
                            "verifier_hash": verifier_hash,
                            "correctness_definition_hash": correctness_hash,
                            "budget": task.budget,
                            "generation": generation,
                            "max_invalid_actions": next(
                                selected.max_invalid_actions
                                for selected in config.systems
                                if selected.id == system.system_id
                            ),
                            "toolchain_profiles": [profile_ref],
                            "requested_profile_id": config.profile,
                            "declared_profile_hash": (
                                resolved.declared_profile_hash if resolved is not None else None
                            ),
                            "resolved_profile_hash": (
                                resolved.resolved_profile_hash if resolved is not None else None
                            ),
                            "resolved_profile": resolved,
                            "verifier_profile": verifier_profile,
                            "resolved_verifier_profile": resolved_verifier,
                            "reference_candidate_hash": (
                                resolved.reference_candidate_hash if resolved is not None else None
                            ),
                            "repository_task_identity": repository_identity,
                            "evaluation_contract_hash": "0" * 64,
                        }
                        contract_payload: dict[str, Any] = {
                            "task_hash": task_hash,
                            "source_identity_hash": task_source_identity,
                            "system": system_identity,
                            "prompt_policy": prompt,
                            "tool_policy": tool_policy,
                            "base_seed": base_seed,
                            "sample_index": sample_index,
                            "child_seed": child_seed,
                            "runtime_identity_hash": runtime_hash,
                            "verifier_hash": verifier_hash,
                            "correctness_definition_hash": correctness_hash,
                            "budget": task.budget,
                            "generation": generation,
                            "toolchain_profiles": [profile_ref],
                            "declared_profile_hash": raw["declared_profile_hash"],
                            "resolved_profile_hash": raw["resolved_profile_hash"],
                            "verifier_profile": verifier_profile,
                            "resolved_verifier_profile": resolved_verifier,
                            "agent_feedback_contract": feedback_contract,
                        }
                        if action_protocol is not None:
                            raw["action_protocol"] = action_protocol
                            contract_payload["action_protocol"] = action_protocol
                        if repository_identity is not None:
                            contract_payload["repository_task_identity"] = repository_identity
                        contract = content_hash(contract_payload)
                        raw["evaluation_contract_hash"] = contract
                        raw["plan_item_id"] = content_hash(plan_item_identity_payload(raw))
                        items.append(PlanItem.model_validate(raw))
        return items

    @staticmethod
    def _order_items(items: list[PlanItem], policy: str) -> list[PlanItem]:
        if policy == "canonical":
            return items
        if policy != "counterbalanced_systems_v1":
            raise ConfigurationError(f"unsupported experiment plan-order policy: {policy}")
        system_order = {
            system_id: index
            for index, system_id in enumerate(sorted({item.system.system_id for item in items}))
        }

        def key(item: PlanItem) -> tuple[str, int, int, int]:
            system_index = system_order[item.system.system_id]
            if item.sample_index % 2:
                system_index = len(system_order) - 1 - system_index
            return item.task_id, item.base_seed, item.sample_index, system_index

        ordered = sorted(items, key=key)
        return [item.model_copy(update={"plan_index": index}) for index, item in enumerate(ordered)]

    @staticmethod
    def _tool_policy(task: VeriTask, mode: Any) -> ToolPolicySnapshot:
        allowed = (
            []
            if mode.value == "chat"
            else sorted(
                tool
                for tool in task.interaction.allowed_tools
                if tool not in task.interaction.denied_tools
            )
        )
        denied = sorted(
            set(task.interaction.denied_tools)
            | (set(task.interaction.allowed_tools) if mode.value == "chat" else set())
        )
        return ToolPolicySnapshot(
            allowed_tools=allowed,
            denied_tools=denied,
            allow_general_shell=(
                False if mode.value == "chat" else task.interaction.allow_general_shell
            ),
            network_policy=task.interaction.network_policy,
        )

    @staticmethod
    def _task_source_hash(task: VeriTask, assets: Any) -> str:
        return task.source.content_hash or hash_directory(Path(assets.visible_root))

    def _verify_task_stability(
        self,
        config: ExperimentConfig,
        expected: list[dict[str, str]],
        expected_verifier_profiles: dict[str, ResolvedVerifierToolProfile],
    ) -> None:
        suite, tasks, _snapshot = self._resolve_tasks(config, check_tools=False)
        _profile, resolved, tasks = self._resolve_verifier_profiles(config, tasks)
        if resolved != expected_verifier_profiles:
            raise ConfigurationError("verifier profile changed during plan construction")
        actual = [
            {
                "task_id": task.id,
                "task_hash": content_hash(task),
                "source_hash": self._task_source_hash(task, suite.resolve_assets(task)),
            }
            for task in tasks
        ]
        if actual != expected:
            raise ConfigurationError("task source changed during plan construction")

    @staticmethod
    def _metadata_text(task: VeriTask, key: str) -> str | None:
        value = task.metadata.get(key)
        return str(value) if isinstance(value, (str, int, float, bool)) else None

    @staticmethod
    def _validate_output_root(path: Path) -> None:
        expanded = path.expanduser()
        current = Path(expanded.anchor) if expanded.is_absolute() else Path.cwd()
        parts = expanded.parts[1:] if expanded.is_absolute() else expanded.parts
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ConfigurationError(f"experiment output traverses a symlink: {current}")
            if current.exists() and not current.is_dir():
                raise ConfigurationError(f"experiment output traverses a non-directory: {current}")
        if expanded.exists() and any(expanded.iterdir()):
            raise ConfigurationError(
                f"experiment output already exists and is not empty: {expanded}; use --resume"
            )


__all__ = ["ExperimentPlanner"]
