#!/usr/bin/env python3
"""Qualify and run the frozen 4-task x 2-backend x 4-identity RTLLM diagnostic."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke
import run_rtl_functional_multiturn_codex_14 as functional
import yaml
from prepare_nangate45_ppa_profile import main as prepare_nangate45_profile
from verigym_codex_cli import (
    CodexCliFunctionalV3HighAgentEvalAdapter,
    CodexCliFunctionalV3LowAgentEvalAdapter,
    CodexCliFunctionalV3MediumAgentEvalAdapter,
    CodexCliFunctionalV3MiniMediumAgentEvalAdapter,
)
from verigym_codex_cli.functional_v3_agenteval_config import (
    FUNCTIONAL_V3_HIGH_IDENTITY,
    FUNCTIONAL_V3_LOW_IDENTITY,
    FUNCTIONAL_V3_MEDIUM_IDENTITY,
    FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY,
    FUNCTIONAL_V3_PROMPT_HASH,
    FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
)
from verigym_rtllm.adapter import HARDER_VARIANT
from verigym_rtllm.manifest import HARDER_TASK_NAMES, TASK_MANIFESTS
from verigym_synopsys.export_mcp_profile import bind_mcp_client_profile_to_docker

from verigym.core.agent_feedback import (
    AgentFeedbackController,
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_directory
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.synthesis_projection import resolve_synthesis_source_projection
from verigym.core.verifier_profiles import (
    resolve_verifier_profile,
    task_with_verifier_profile,
)
from verigym.core.workspace import copy_tree_safely
from verigym.experiments.state import atomic_dump_json, atomic_write_text
from verigym.profiles.identity import resolved_profile_component_hashes
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.profiles.verifier_registry import load_verifier_profile
from verigym.prompts.policy import agent_configuration_hash, resolve_prompt_policy
from verigym.protocols.repository_action import resolve_repository_action_protocol
from verigym.registry.base import PluginOrigin
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus
from verigym.tools.base import SynthesisBackendPlugin

_CAMPAIGN_ID = "rtl-rtllm-harder-multiturn-codex-32run-diagnostic-v1"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_OPT_IN = "VERIGYM_RUN_RTLLM_HARDER_32"
_PROCESS_COUNT = 32
_SOURCE_CONFIG_KEY = "rtllm_harder"


@dataclass(frozen=True)
class AgentCell:
    key: str
    adapter_class: type[Any]
    identity: Any


@dataclass(frozen=True)
class RunSpec:
    ordinal: int
    run_id: str
    task_name: str
    task_id: str
    backend: str
    profile_name: str
    agent_key: str


_AGENT_CELLS = {
    "mini-low": AgentCell(
        "mini-low", CodexCliFunctionalV3LowAgentEvalAdapter, FUNCTIONAL_V3_LOW_IDENTITY
    ),
    "mini-medium": AgentCell(
        "mini-medium",
        CodexCliFunctionalV3MiniMediumAgentEvalAdapter,
        FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY,
    ),
    "mini-high": AgentCell(
        "mini-high",
        CodexCliFunctionalV3MediumAgentEvalAdapter,
        FUNCTIONAL_V3_MEDIUM_IDENTITY,
    ),
    "full-xhigh": AgentCell(
        "full-xhigh", CodexCliFunctionalV3HighAgentEvalAdapter, FUNCTIONAL_V3_HIGH_IDENTITY
    ),
}


def _run_specs() -> tuple[RunSpec, ...]:
    specs: list[RunSpec] = []
    ordinal = 0
    for agent_key in _AGENT_CELLS:
        for task_name in HARDER_TASK_NAMES:
            for backend in ("open", "commercial"):
                ordinal += 1
                slug = task_name.lower().replace("_", "-")
                run_id = f"{ordinal:02d}-{agent_key}-{slug}-{backend}"
                specs.append(
                    RunSpec(
                        ordinal=ordinal,
                        run_id=run_id,
                        task_name=task_name,
                        task_id=f"rtllm/{HARDER_VARIANT}/{task_name}",
                        backend=backend,
                        profile_name=f"{task_name}_{'open' if backend == 'open' else 'dc'}",
                        agent_key=agent_key,
                    )
                )
    return tuple(specs)


_RUN_SPECS = _run_specs()
_RUN_IDS = tuple(spec.run_id for spec in _RUN_SPECS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument(
        "--broker-root",
        type=Path,
        default=Path("/data/jzhu484/Agent/.verigym-tmp/cb-fmt1"),
    )
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--pdk-root", type=Path, required=True)
    parser.add_argument(
        "--dc-profile",
        action="append",
        default=[],
        metavar="TASK=PATH",
        help="repeat once per harder task",
    )
    parser.add_argument(
        "--vcs-profile",
        action="append",
        default=[],
        metavar="TASK=PATH",
        help="repeat once per harder task",
    )
    parser.add_argument("--image", default=smoke._IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def _named_paths(values: list[str], label: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or name not in HARDER_TASK_NAMES or name in parsed:
            raise ConfigurationError(f"{label} entries require one unique TASK=PATH per task")
        parsed[name] = smoke._regular_file(Path(raw_path), f"{label} profile")
    if set(parsed) != set(HARDER_TASK_NAMES):
        raise ConfigurationError(f"{label} profiles must cover exactly the four harder tasks")
    return parsed


def _registries() -> Any:
    registries = smoke._registries()
    for cell in _AGENT_CELLS.values():
        if cell.identity.agent_name not in registries.agents.names():
            registries.agents.register(
                cell.adapter_class(),
                origin=PluginOrigin(
                    package="verigym-codex-cli",
                    version="0.1.0",
                    entry_point=None,
                    registration="runtime",
                ),
            )
    return registries


def _agent_options(cell: AgentCell, capability: Any, auth: Any) -> dict[str, Any]:
    identity = cell.identity
    return {
        "model_id": identity.model_id,
        "reasoning_effort": identity.reasoning_effort,
        "max_process_time_s": 900,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        ),
        "expected_cli_version": smoke._EXPECTED_CLI_VERSION,
        "expected_cli_executable_sha256": smoke._EXPECTED_CODEX_SHA256,
        "expected_capability_fingerprint": capability.capability_fingerprint,
        "expected_prompt_hash": FUNCTIONAL_V3_PROMPT_HASH,
        "expected_tool_policy_fingerprint": FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": auth.requested_auth_mode,
        "expected_resolved_auth_mode": auth.resolved_auth_mode,
        "expected_auth_semantic_id": auth.auth_semantic_id,
        "prompt_contract_id": "repository_action_v2_prompt_v8",
        "scoring_agent_version_id": identity.agent_version_id,
        "scoring_agent_version_hash": identity.agent_version_hash,
    }


def _sdc(task_name: str) -> str:
    manifest = TASK_MANIFESTS[task_name]
    lines = [
        f"create_clock -name {clock.name} -period {clock.period_ns:g} [get_ports {clock.name}]"
        for clock in manifest.clocks
    ]
    if len(manifest.clocks) > 1:
        groups = " ".join(f"-group [get_clocks {clock.name}]" for clock in manifest.clocks)
        lines.append(f"set_clock_groups -asynchronous {groups}")
    return "\n".join(lines) + "\n"


def _prepare_profiles(
    registries: Any,
    *,
    site_work: Path,
    image: str,
    image_id: str,
    pdk_root: Path,
    dc_paths: dict[str, Path],
) -> dict[str, smoke.PreparedProfile]:
    profiles_root = site_work / "profiles"
    profiles_root.mkdir()
    prepared: dict[str, smoke.PreparedProfile] = {}
    for task_name in HARDER_TASK_NAMES:
        manifest = TASK_MANIFESTS[task_name]
        profile_name = f"{task_name}_open"
        sdc = profiles_root / f"{profile_name}.sdc"
        atomic_write_text(sdc, _sdc(task_name))
        profile_path = profiles_root / f"{profile_name}.yaml"
        result = prepare_nangate45_profile(
            [
                "--pdk-root",
                str(pdk_root),
                "--sdc",
                str(sdc),
                "--runtime",
                "docker",
                "--opensta",
                "sta",
                "--docker-image",
                image,
                "--output-manifest",
                str(profiles_root / f"{profile_name}-pdk-manifest.json"),
                "--output-profile",
                str(profile_path),
                "--source",
                f"rtl/{task_name}.v",
                "--top",
                manifest.synthesis_top,
                "--clock-name",
                manifest.power_base_clock,
                "--clock-period",
                str(
                    next(
                        c.period_ns for c in manifest.clocks if c.name == manifest.power_base_clock
                    )
                ),
                "--profile-id",
                f"rtllm-harder-{task_name}-opensta-v1",
                "--profile-version",
                "1.0.0",
            ]
        )
        if result != 0:
            raise ConfigurationError("RTLLM harder OpenSTA profile preparation failed")
        profile = ToolchainProfileRegistry().load_file(profile_path)
        profile = profile.model_copy(
            update={
                "metadata": {
                    **profile.metadata,
                    "clock_constraints": [
                        {"name": clock.name, "period_ns": clock.period_ns}
                        for clock in manifest.clocks
                    ],
                    "power_base_clock": manifest.power_base_clock,
                    "asynchronous_clock_groups": len(manifest.clocks) > 1,
                }
            },
            deep=True,
        )
        registries.profiles.register(profile)
        prepared[profile_name] = smoke.PreparedProfile(profile, None)

    loader = ToolchainProfileRegistry()
    for task_name in HARDER_TASK_NAMES:
        client = loader.load_file(dc_paths[task_name])
        smoke._require_commercial_worker_release(client)
        manifest = TASK_MANIFESTS[task_name]
        if (
            client.flow is None
            or client.flow.top_module != manifest.synthesis_top
            or client.flow.default_sources != [f"rtl/{task_name}.v"]
            or client.metadata.get("power_base_clock") != manifest.power_base_clock
        ):
            raise ConfigurationError(f"DC profile is not task-bound for {task_name}")
        client = client.model_copy(
            update={
                "metadata": {
                    **client.metadata,
                    "clock_constraints": [
                        {"name": clock.name, "period_ns": clock.period_ns}
                        for clock in manifest.clocks
                    ],
                    "power_base_clock": manifest.power_base_clock,
                    "asynchronous_clock_groups": len(manifest.clocks) > 1,
                }
            },
            deep=True,
        )
        bound = bind_mcp_client_profile_to_docker(
            client,
            image=image,
            prepared_image_id=image_id,
            profile_id=f"rtllm-harder-{task_name}-dc-docker-v1",
            profile_version="1.0.0",
        )
        registries.profiles.register(bound)
        prepared[f"{task_name}_dc"] = smoke.PreparedProfile(bound, None)
        atomic_write_text(
            profiles_root / f"{task_name}_dc.yaml",
            yaml.safe_dump(bound.model_dump(mode="json", exclude_none=True), sort_keys=False),
        )
    return prepared


def _source_config(rtllm_source: Path) -> SuiteSourceConfig:
    return SuiteSourceConfig(source_root=rtllm_source, variant=HARDER_VARIANT)


def _load_tasks(
    service: VeriGym, source_config: SuiteSourceConfig
) -> dict[str, tuple[Any, Any, Any]]:
    loaded: dict[str, tuple[Any, Any, Any]] = {}
    for task_name in HARDER_TASK_NAMES:
        task_id = f"rtllm/{HARDER_VARIANT}/{task_name}"
        suite, task, assets = service.load_task(task_id, source_config)
        if (
            task.id != task_id
            or task.metadata.get("diagnostic_only") is not True
            or task.metadata.get("benchmark_score_claimed") is not False
            or task.metadata.get("public_feedback_semantics")
            != "compile_and_independent_functional_smoke_harder_v1"
            or len(assets.read_only_mounts) != 1
        ):
            raise ConfigurationError(f"RTLLM harder source qualification failed for {task_id}")
        loaded[task_name] = (suite, task, assets)
    return loaded


def _task_cases(suite: Any, task_name: str) -> list[Any]:
    cases = [case for case in suite.conformance_cases() if case.name.startswith(f"{task_name}-")]
    if len(cases) != 5 or [case.expected_resolved for case in cases] != [
        True,
        False,
        False,
        False,
        False,
    ]:
        raise ConfigurationError(f"RTLLM harder conformance matrix drifted for {task_name}")
    return cases


def _candidate_tree(root: Path, assets: Any, case: Any) -> Path:
    copy_tree_safely(Path(assets.visible_root), root)
    for relative, content in sorted(case.candidate.files.items()):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return root


def _qualify_public(loaded: dict[str, tuple[Any, Any, Any]], runtime: Any) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for task_name, (suite, task, assets) in loaded.items():
        cases = list(suite.public_conformance_cases(task))
        if len(cases) != 5:
            raise ConfigurationError("RTLLM public conformance matrix must contain five cases")
        visible = Path(assets.visible_root)
        visible_paths = {
            path.relative_to(visible).as_posix() for path in visible.rglob("*") if path.is_file()
        }
        if any(
            path.startswith("verifier/")
            or path in TASK_MANIFESTS[task_name].auxiliary_files
            or "public-smoke" in path
            for path in visible_paths
        ):
            raise ConfigurationError("RTLLM public projection exposes a protected asset")
        for case in cases:
            matched = functional._execute_public_candidate(
                runtime,
                task,
                assets,
                case.candidate.files,
                expect_pass=case.expected_resolved,
            )
            if not matched:
                raise ConfigurationError(f"public qualification failed for {case.name}")
            records.append(
                {
                    "task_id": task.id,
                    "case": case.name,
                    "resolved": case.expected_resolved,
                }
            )
    return {"passed": True, "model_calls": 0, "records": records}


def _qualify_open_hidden(
    service: VeriGym,
    loaded: dict[str, tuple[Any, Any, Any]],
    runtime: Any,
    scratch: Path,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for task_name, (suite, task, assets) in loaded.items():
        for case in _task_cases(suite, task_name):
            candidate = _candidate_tree(scratch / task_name / case.name, assets, case)
            results = service._verify_candidate(
                suite=suite,
                task=task,
                assets=assets,
                runtime=runtime,
                candidate_dir=candidate,
                artifact_root=scratch / "artifacts" / task_name / case.name,
            )
            observed = bool(results) and all(
                result.status == VerifierStatus.PASSED for result in results
            )
            if observed is not case.expected_resolved:
                raise ConfigurationError(f"Icarus qualification failed for {case.name}")
            records.append({"task_id": task.id, "case": case.name, "resolved": observed})
    return {"passed": True, "model_calls": 0, "records": records}


def _resolve_verifiers(
    service: VeriGym,
    loaded: dict[str, tuple[Any, Any, Any]],
    paths: dict[str, Path],
) -> dict[str, tuple[Any, Any]]:
    resolved: dict[str, tuple[Any, Any]] = {}
    for task_name, (_suite, task, _assets) in loaded.items():
        profile = load_verifier_profile(paths[task_name])
        if (
            profile.task_id != task.id
            or profile.source_plugin != "iverilog.simulate"
            or profile.target_plugin != "synopsys.vcs.mcp"
        ):
            raise ConfigurationError(f"VCS profile is not task-bound for {task_name}")
        identity = resolve_verifier_profile(
            task=task,
            profile=profile,
            tools=service.registries.tools,
        )
        if (
            resolve_verifier_profile(
                task=task,
                profile=profile,
                tools=service.registries.tools,
                expected=identity,
            )
            != identity
        ):
            raise ConfigurationError("VCS profile resolution is not stable")
        resolved[task_name] = (profile, identity)
    return resolved


def _qualify_vcs_hidden(
    service: VeriGym,
    loaded: dict[str, tuple[Any, Any, Any]],
    verifiers: dict[str, tuple[Any, Any]],
    scratch: Path,
) -> dict[str, Any]:
    runtime = service.registries.runtimes.get("local").configure(None)
    runtime.prepare("rtllm-harder-vcs-preflight")
    records: list[dict[str, Any]] = []
    try:
        for task_name, (suite, task, assets) in loaded.items():
            profile, resolved = verifiers[task_name]
            effective = task_with_verifier_profile(task, profile)
            for case in _task_cases(suite, task_name):
                candidate = _candidate_tree(scratch / task_name / case.name, assets, case)
                results = service._verify_candidate(
                    suite=suite,
                    task=effective,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=scratch / "artifacts" / task_name / case.name,
                    verifier_profile=profile,
                    resolved_verifier_profile=resolved,
                )
                observed = bool(results) and all(
                    result.status == VerifierStatus.PASSED for result in results
                )
                if observed is not case.expected_resolved:
                    raise ConfigurationError(f"VCS qualification failed for {case.name}")
                records.append({"task_id": task.id, "case": case.name, "resolved": observed})
    finally:
        runtime.close()
    return {"passed": True, "model_calls": 0, "records": records}


def _qualify_synthesis_feedback(
    service: VeriGym,
    loaded: dict[str, tuple[Any, Any, Any]],
    runtime: Any,
    prepared: dict[str, smoke.PreparedProfile],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for task_name, (suite, task, assets) in loaded.items():
        reference = suite.reference_solution(task)
        if reference is None:
            raise ConfigurationError("RTLLM synthesis qualification lacks a reference")
        projection = resolve_synthesis_source_projection(task)
        for suffix in ("open", "dc"):
            profile_name = f"{task_name}_{suffix}"
            item = prepared[profile_name]
            if item.profile.flow is None:
                raise ConfigurationError("RTLLM synthesis profile lacks a flow")
            backend = service.registries.tools.get(item.profile.flow.backend_plugin)
            if not isinstance(backend, SynthesisBackendPlugin):
                raise ConfigurationError("RTLLM synthesis backend is unavailable")
            first = resolve_toolchain_profile(
                item.profile,
                runtime,
                source_paths=projection.profile_sources,
                top_module=item.profile.flow.top_module,
                reference_candidate_hash=content_hash(reference),
                backend=backend,
                synthesis_source_projection_hash=projection.projection_hash,
            )
            resolved = resolve_toolchain_profile(
                item.profile,
                runtime,
                source_paths=projection.profile_sources,
                top_module=item.profile.flow.top_module,
                reference_candidate_hash=content_hash(reference),
                expected=first,
                backend=backend,
                synthesis_source_projection_hash=projection.projection_hash,
            )
            contract = resolve_agent_feedback_contract(
                task=task,
                ppa_enabled=True,
                ppa_max_executions=3,
                resolved_profile=resolved,
                profile_backend=item.profile.flow.backend_plugin,
            )
            if contract is None:
                raise ConfigurationError("RTLLM synthesis feedback contract is unavailable")
            controller = AgentFeedbackController(
                contract=contract,
                task=task_with_agent_feedback_contract(task, contract),
                runtime=runtime,
                profile=item.profile,
                resolved_profile=resolved,
                backend=backend,
            )
            session = runtime.create_session(
                SessionSpec(
                    source_dir=assets.visible_root,
                    label="agent",
                    max_output_bytes=task.budget.max_output_bytes_per_tool,
                    read_only_mounts=assets.read_only_mounts,
                )
            )
            try:
                for relative, content in sorted(reference.files.items()):
                    session.write_file(relative, content.encode("utf-8"))
                compile_result = controller.execute("compile", session)
                ppa_result = controller.execute("ppa", session)
            finally:
                session.close()
            if (
                compile_result.exit_code != 0
                or ppa_result.exit_code != 0
                or [evaluation.test_id for evaluation in controller.evaluations]
                != ["compile", "ppa"]
                or not all(evaluation.passed for evaluation in controller.evaluations)
                or controller.evaluations[1].metrics is None
            ):
                raise ConfigurationError(f"PPA qualification failed for {profile_name}")
            prepared[profile_name] = smoke.PreparedProfile(item.profile, resolved)
            records.append(
                {
                    "task_id": task.id,
                    "profile_name": profile_name,
                    "resolved_profile_hash": resolved.resolved_profile_hash,
                    "compile_passed": True,
                    "ppa_passed": True,
                }
            )
    return {"passed": True, "model_calls": 0, "records": records}


def _no_model_qualification(
    service: VeriGym,
    *,
    source_config: SuiteSourceConfig,
    docker_config: Any,
    prepared: dict[str, smoke.PreparedProfile],
    vcs_paths: dict[str, Path],
    scratch: Path,
) -> tuple[Any, dict[str, Any], dict[str, tuple[Any, Any]]]:
    scratch.mkdir()
    loaded = _load_tasks(service, source_config)
    verifiers = _resolve_verifiers(service, loaded, vcs_paths)
    runtime = service.registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("rtllm-harder-32-preflight")
    try:
        image = runtime.descriptor.image
        if image is None or image.iverilog_version is None or "12." not in image.iverilog_version:
            raise ConfigurationError("qualified Docker runtime does not expose Icarus 12")
        records = {
            "public_functional": _qualify_public(loaded, runtime),
            "icarus_hidden": _qualify_open_hidden(service, loaded, runtime, scratch / "icarus"),
            "synthesis_feedback": _qualify_synthesis_feedback(service, loaded, runtime, prepared),
        }
        descriptor = runtime.descriptor
    finally:
        runtime.close()
    records["vcs_hidden"] = _qualify_vcs_hidden(service, loaded, verifiers, scratch / "vcs")
    return descriptor, records, verifiers


def _freeze_run_config(
    service: VeriGym,
    *,
    spec: RunSpec,
    source_config: SuiteSourceConfig,
    docker_config: Any,
    runtime_descriptor: Any,
    prepared: dict[str, smoke.PreparedProfile],
    verifiers: dict[str, tuple[Any, Any]],
    agent_options: dict[str, Any],
    output: Path,
) -> RunConfig:
    suite, task, assets = service.load_task(spec.task_id, source_config)
    verifier_profile = None
    resolved_verifier = None
    if spec.backend == "commercial":
        verifier_profile, resolved_verifier = verifiers[spec.task_name]
        task = task_with_verifier_profile(task, verifier_profile)
    item = prepared[spec.profile_name]
    if item.resolved is None or item.profile.flow is None:
        raise ConfigurationError("RTLLM harder profile was not qualified before freeze")
    feedback = resolve_agent_feedback_contract(
        task=task,
        ppa_enabled=True,
        ppa_max_executions=3,
        resolved_profile=item.resolved,
        profile_backend=item.profile.flow.backend_plugin,
    )
    execution_task = task_with_agent_feedback_contract(task, feedback)
    cell = _AGENT_CELLS[spec.agent_key]
    agent = service.registries.agents.get(cell.identity.agent_name)
    prompt = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=agent_options,
        task=execution_task,
    )
    action = resolve_repository_action_protocol(
        agent_descriptor=agent.descriptor,
        protocol_spec=agent.action_protocol_spec,
        agent_options=agent_options,
        task=execution_task,
    )
    configuration_hash = agent_configuration_hash(agent.descriptor, agent_options)
    source_hash = task.source.content_hash or hash_directory(Path(assets.visible_root))
    return RunConfig(
        task_id=spec.task_id,
        mode=InteractionMode.AGENT,
        agent=cell.identity.agent_name,
        agent_options=agent_options,
        suite_source=source_config,
        runtime="docker",
        docker_config=docker_config,
        toolchain_profile=item.profile.id,
        verifier_profile_id=verifier_profile.id if verifier_profile is not None else None,
        verifier_profile=verifier_profile,
        expected_resolved_verifier_profile=resolved_verifier,
        agent_ppa_feedback=True,
        agent_ppa_max_calls=3,
        seed=0,
        sample_index=0,
        output=output,
        run_id=spec.run_id,
        expected_task_hash=content_hash(task),
        expected_source_hash=source_hash,
        expected_suite_source_snapshot=suite.source_snapshot(),
        expected_runtime=runtime_descriptor,
        expected_resolved_profile=item.resolved,
        expected_prompt_policy=prompt,
        expected_prompt_policy_hash=(
            prompt.configuration_fingerprint if prompt is not None else None
        ),
        resolved_prompt_policy=prompt,
        resolved_prompt_policy_hash=(
            prompt.configuration_fingerprint if prompt is not None else None
        ),
        expected_agent_configuration_hash=configuration_hash,
        resolved_agent_configuration_hash=configuration_hash,
        expected_action_protocol=action,
        resolved_action_protocol=action,
        expected_agent_feedback_contract=feedback,
        resolved_agent_feedback_contract=feedback,
    )


def _frozen_run_configs(
    service: VeriGym,
    *,
    source_config: SuiteSourceConfig,
    docker_config: Any,
    runtime_descriptor: Any,
    prepared: dict[str, smoke.PreparedProfile],
    verifiers: dict[str, tuple[Any, Any]],
    capability: Any,
    auth: Any,
    output: Path,
) -> list[RunConfig]:
    options = {key: _agent_options(cell, capability, auth) for key, cell in _AGENT_CELLS.items()}
    configs = [
        _freeze_run_config(
            service,
            spec=spec,
            source_config=source_config,
            docker_config=docker_config,
            runtime_descriptor=runtime_descriptor,
            prepared=prepared,
            verifiers=verifiers,
            agent_options=options[spec.agent_key],
            output=output,
        )
        for spec in _RUN_SPECS
    ]
    if (
        len(configs) != _PROCESS_COUNT
        or len({config.run_id for config in configs}) != _PROCESS_COUNT
    ):
        raise ConfigurationError("RTLLM harder launcher must freeze exactly 32 unique runs")
    return configs


def _spec_payload(spec: RunSpec) -> dict[str, Any]:
    return {
        "ordinal": spec.ordinal,
        "run_id": spec.run_id,
        "task_id": spec.task_id,
        "task_name": spec.task_name,
        "backend": spec.backend,
        "ppa_profile_name": spec.profile_name,
        "agent_identity": spec.agent_key,
    }


def _build_plan(
    *,
    capability: Any,
    auth: Any,
    runtime_descriptor: Any,
    prepared: dict[str, smoke.PreparedProfile],
    verifiers: dict[str, tuple[Any, Any]],
    qualifications: dict[str, Any],
    configs: list[RunConfig],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "variant": HARDER_VARIANT,
        "run_specs": [_spec_payload(spec) for spec in _RUN_SPECS],
        "seed": 0,
        "samples_per_task_backend_identity": 1,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "serial_execution": True,
        "agents": {
            key: {
                "agent_name": cell.identity.agent_name,
                "agent_version_id": cell.identity.agent_version_id,
                "agent_version_hash": cell.identity.agent_version_hash,
                "model": cell.identity.model_id,
                "reasoning_effort": cell.identity.reasoning_effort,
                "prompt_hash": FUNCTIONAL_V3_PROMPT_HASH,
                "tool_policy_fingerprint": FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
            }
            for key, cell in _AGENT_CELLS.items()
        },
        "codex": {
            "version": capability.version_output,
            "executable_sha256": capability.executable_sha256,
            "capability_fingerprint": capability.capability_fingerprint,
            "auth": auth.safe_dict(),
        },
        "runtime": runtime_descriptor.model_dump(mode="json"),
        "ppa_profiles": {
            name: {
                "declared_hash": content_hash(item.profile),
                "resolved_hash": item.resolved.resolved_profile_hash,
                "component_hashes": resolved_profile_component_hashes(item.resolved),
            }
            for name, item in prepared.items()
            if item.resolved is not None
        },
        "verifier_profiles": {
            name: {
                "declared_hash": content_hash(profile),
                "resolved_hash": resolved.resolved_profile_hash,
            }
            for name, (profile, resolved) in verifiers.items()
        },
        "qualifications": qualifications,
        "run_config_hashes": [content_hash(config.identity_payload()) for config in configs],
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
    }


def _identity_valid(result: RunResult, spec: RunSpec) -> bool:
    observations = result.manifest.external_agent_observations
    identity_path = result.run_dir / "artifacts" / "codex_cli" / "identity.json"
    if len(observations) != 1 or not identity_path.is_file():
        return False
    observation = observations[0]
    identity = _AGENT_CELLS[spec.agent_key].identity
    return bool(
        observation.invocation_count == 1
        and observation.requested_model_id == identity.model_id
        and observation.observed_model_id in {None, identity.model_id}
        and observation.effective_reasoning_effort == identity.reasoning_effort
        and observation.harness_id == identity.agent_version_id
        and observation.agent_version_hash == identity.agent_version_hash
        and observation.prompt_contract_hash == FUNCTIONAL_V3_PROMPT_HASH
        and observation.tool_policy_fingerprint == FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT
    )


def _write_ledger(output: Path, records: list[dict[str, Any]]) -> None:
    atomic_dump_json(output / "evidence" / "process-authorizations.json", {"records": records})


def _execute_exactly_32(
    service: VeriGym, configs: list[RunConfig], output: Path
) -> list[RunResult]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("RTLLM harder launcher requires exactly 32 frozen runs")
    results: list[RunResult] = []
    ledger: list[dict[str, Any]] = []
    for spec, config in zip(_RUN_SPECS, configs, strict=True):
        record: dict[str, Any] = {
            "ordinal": spec.ordinal,
            "run_id": spec.run_id,
            "task_id": spec.task_id,
            "agent_identity": spec.agent_key,
            "backend": spec.backend,
            "authorization_granted": True,
            "process_started": False,
            "identity_observation_count": 0,
            "provider_observation_recorded": False,
            "retry_count": 0,
            "status": "authorized",
        }
        ledger.append(record)
        _write_ledger(output, ledger)
        try:
            run = service.run(config)
        except Exception:
            run_dir = config.output.expanduser().resolve() / str(config.run_id)
            smoke._update_process_ledger_record(record, run_dir=run_dir)
            record["status"] = "infrastructure_failure"
            _write_ledger(output, ledger)
            raise
        smoke._update_process_ledger_record(record, run_dir=run.run_dir, run=run)
        identity_ok = _identity_valid(run, spec)
        record["identity_observation_count"] = len(run.manifest.external_agent_observations)
        record["provider_observation_recorded"] = identity_ok
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        if not identity_ok:
            record["status"] = "identity_infrastructure_failure"
            _write_ledger(output, ledger)
            raise functional.CampaignInfrastructureError(
                "RTLLM harder campaign stopped after invalid identity evidence"
            )
        failure = run.scorecard.failure
        infrastructure = run.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        policy = failure is not None and failure.kind == "policy"
        record["status"] = (
            "infrastructure_failure"
            if infrastructure
            else "policy_failure"
            if policy
            else "contained_model_failure"
            if failure is not None
            else "verifier_rejection"
            if not run.scorecard.resolved
            else "completed"
        )
        _write_ledger(output, ledger)
        if spec.ordinal < _PROCESS_COUNT and (infrastructure or policy):
            raise functional.CampaignInfrastructureError(
                "RTLLM harder campaign stopped after infrastructure or safety failure"
            )
    if len(results) != _PROCESS_COUNT:
        raise ConfigurationError("RTLLM harder campaign stopped before all slots completed")
    return results


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("RTLLM harder evidence JSON is unavailable") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("RTLLM harder evidence JSON must be an object")
    return value


def _hidden_verifier_execution(
    verifier_results: list[Any],
    *,
    typed_finish: bool,
    expected_plugin: str,
) -> tuple[bool, int, int]:
    functional = [result for result in verifier_results if result.node_id == "functional_hidden"]
    executed = [result for result in functional if result.status != VerifierStatus.SKIPPED]
    valid = (typed_finish and len(executed) == 1 and executed[0].plugin == expected_plugin) or (
        not typed_finish and not executed
    )
    return valid, len(executed), len(functional) - len(executed)


def _provider_usage_valid(
    *,
    usage_complete: bool,
    typed_finish: bool,
    contained_model_failure: bool,
) -> bool:
    return usage_complete or (not typed_finish and contained_model_failure)


def _audit_outputs(
    results: list[RunResult],
    service: VeriGym,
    source_config: SuiteSourceConfig,
    profile_paths: dict[str, Path],
    inputs: dict[str, Path],
    site_paths: tuple[Path, ...],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    original_specs = functional._RUN_SPECS
    original_count = functional._PROCESS_COUNT
    try:
        functional._RUN_SPECS = tuple(
            functional.RunSpec(
                spec.run_id,
                spec.task_id,
                _SOURCE_CONFIG_KEY,
                spec.profile_name,
                True,
            )
            for spec in _RUN_SPECS
        )
        functional._PROCESS_COUNT = _PROCESS_COUNT
        replay = smoke._offline_replay(results)
        scan = functional._scan_outputs(
            results,
            service,
            {_SOURCE_CONFIG_KEY: source_config},
            profile_paths,
            inputs,
            site_paths=site_paths,
        )
        redaction = functional._redaction_audit(results)
    finally:
        functional._RUN_SPECS = original_specs
        functional._PROCESS_COUNT = original_count
    return replay, scan, redaction


def _campaign_summary(
    results: list[RunResult],
    replay: dict[str, Any],
    scan: dict[str, Any],
    redaction: dict[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for spec, result in zip(_RUN_SPECS, results, strict=True):
        root = result.run_dir / "artifacts" / "codex_cli"
        broker = _read_json(root / "broker.json")
        process = _read_json(root / "process.json")
        usage = _read_json(root / "provider-usage.json")
        failure = result.scorecard.failure
        infrastructure = result.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        policy = failure is not None and failure.kind == "policy"
        typed_finish = broker.get("finished") is True and broker.get("finish_calls") == 1
        public_passed = any(
            evaluation.test_id == "compile"
            and evaluation.passed
            and evaluation.candidate_hash == result.manifest.candidate_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        legal_ppa = any(
            evaluation.test_id == "ppa"
            and evaluation.passed
            and evaluation.metrics is not None
            and evaluation.candidate_hash == result.manifest.candidate_hash
            and evaluation.profile_hash == result.manifest.resolved_profile_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        verifier_results = result.scorecard.verifier_results
        expected_plugin = (
            "synopsys.vcs.mcp" if spec.backend == "commercial" else "iverilog.simulate"
        )
        hidden_execution_valid, hidden_execution_count, hidden_placeholder_count = (
            _hidden_verifier_execution(
                verifier_results,
                typed_finish=typed_finish,
                expected_plugin=expected_plugin,
            )
        )
        contained_model_failure = failure is not None and not infrastructure and not policy
        usage_complete = usage.get("usage_complete") is True
        usage_valid = _provider_usage_valid(
            usage_complete=usage_complete,
            typed_finish=typed_finish,
            contained_model_failure=contained_model_failure,
        )
        first_public = broker.get("first_public_validation_passed") is True
        repaired = broker.get("public_validation_failed_then_passed") is True
        failures = broker.get("public_validation_failures", 0)
        if not typed_finish:
            sequence = "unverified_finish"
        elif first_public:
            sequence = "first_pass"
        elif repaired:
            sequence = "fail_repair_pass"
        elif isinstance(failures, int) and failures > 0:
            sequence = "persistent_failure"
        else:
            sequence = "finish_without_public_pass"
        records.append(
            {
                "ordinal": spec.ordinal,
                "run_id": spec.run_id,
                "task_id": spec.task_id,
                "agent_identity": spec.agent_key,
                "backend": spec.backend,
                "resolved": result.scorecard.resolved,
                "typed_finish": typed_finish,
                "sequence": sequence,
                "first_public_validation_passed": first_public,
                "public_validation_failures": failures,
                "repair_patches_after_failure": broker.get(
                    "repair_patches_after_public_validation_failure", 0
                ),
                "public_validation_rechecks_after_repair": broker.get(
                    "public_validation_rechecks_after_repair_patch", 0
                ),
                "public_validation_passed_for_final_candidate": public_passed,
                "legal_candidate_ppa": legal_ppa,
                "final_ppa_eligible": bool(
                    result.scorecard.quality.ppa is not None
                    and result.scorecard.quality.ppa.eligible
                ),
                "hidden_verifier_node_count": hidden_execution_count,
                "hidden_verifier_placeholder_count": hidden_placeholder_count,
                "verifier_dag_node_count": len(verifier_results),
                "hidden_verifier_execution_valid": hidden_execution_valid,
                "model_identity_valid": _identity_valid(result, spec),
                "identity_observation_count": len(result.manifest.external_agent_observations),
                "process_started": (root / "process.json").is_file(),
                "provider_usage_complete": usage_complete,
                "provider_usage_valid": usage_valid,
                "contained_model_failure": contained_model_failure,
                "timed_out": process.get("timed_out") is True,
                "policy_failure": policy,
                "infrastructure_failure": infrastructure,
                "failure_subcategory": broker.get("policy_failure_subcategory")
                or broker.get("infrastructure_failure_subcategory"),
            }
        )
    infrastructure_complete = bool(
        len(records) == _PROCESS_COUNT
        and len({record["run_id"] for record in records}) == _PROCESS_COUNT
        and replay.get("all_valid") is True
        and scan.get("passed") is True
        and redaction.get("passed") is True
        and all(record["process_started"] for record in records)
        and all(record["model_identity_valid"] for record in records)
        and all(record["identity_observation_count"] == 1 for record in records)
        and all(record["hidden_verifier_execution_valid"] for record in records)
        and all(record["provider_usage_valid"] for record in records)
        and not any(record["infrastructure_failure"] for record in records)
        and not any(record["policy_failure"] for record in records)
    )
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "codex_processes_authorized": _PROCESS_COUNT,
        "codex_processes_started": sum(record["process_started"] for record in records),
        "provider_observations_recorded": sum(record["model_identity_valid"] for record in records),
        "automatic_retries": 0,
        "runs": records,
        "resolved_count": sum(record["resolved"] for record in records),
        "first_pass_count": sum(record["sequence"] == "first_pass" for record in records),
        "fail_repair_pass_count": sum(
            record["sequence"] == "fail_repair_pass" for record in records
        ),
        "persistent_failure_count": sum(
            record["sequence"] == "persistent_failure" for record in records
        ),
        "unverified_finish_count": sum(
            record["sequence"] == "unverified_finish" for record in records
        ),
        "all_candidates_resolved": len(records) == _PROCESS_COUNT
        and all(record["resolved"] for record in records),
        "infrastructure_complete": infrastructure_complete,
        "diagnostic_complete": infrastructure_complete,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
    }


def _persist_evidence(
    output: Path,
    replay: dict[str, Any],
    scan: dict[str, Any],
    redaction: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    atomic_dump_json(output / "replay.json", replay)
    atomic_dump_json(output / "security-scan.json", scan)
    atomic_dump_json(output / "redaction-audit.json", redaction)
    atomic_dump_json(output / "summary.json", summary)


def _load_existing_results(output: Path) -> list[RunResult]:
    runs = output / "runs"
    if runs.is_symlink() or not runs.is_dir():
        raise ConfigurationError("existing RTLLM harder campaign has no runs directory")
    if sorted(path.name for path in runs.iterdir()) != sorted(_RUN_IDS):
        raise ConfigurationError("existing RTLLM harder campaign does not contain 32 slots")
    results: list[RunResult] = []
    for spec in _RUN_SPECS:
        run_dir = runs / spec.run_id
        manifest = load_model(run_dir / "run_manifest.json", RunManifest)
        scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
        if (
            manifest.run_id != spec.run_id
            or manifest.task_id != spec.task_id
            or scorecard.run_id != spec.run_id
            or scorecard.task_id != spec.task_id
        ):
            raise ConfigurationError("existing RTLLM harder slot differs from its frozen identity")
        results.append(RunResult(run_dir=run_dir, manifest=manifest, scorecard=scorecard))
    return results


def _validate_authorization_ledger(records: Any) -> None:
    if not isinstance(records, list) or len(records) != _PROCESS_COUNT:
        raise ConfigurationError("existing authorization ledger must contain 32 records")
    terminal_statuses = {
        "completed",
        "contained_model_failure",
        "verifier_rejection",
    }
    for spec, record in zip(_RUN_SPECS, records, strict=True):
        if not isinstance(record, dict):
            raise ConfigurationError("authorization ledger records must be objects")
        expected = {
            "ordinal": spec.ordinal,
            "run_id": spec.run_id,
            "task_id": spec.task_id,
            "agent_identity": spec.agent_key,
            "backend": spec.backend,
        }
        if any(record.get(key) != value for key, value in expected.items()):
            raise ConfigurationError("authorization ledger differs from its frozen slot identity")
        if (
            record.get("authorization_granted") is not True
            or record.get("process_started") is not True
            or record.get("identity_observation_count") != 1
            or record.get("provider_observation_recorded") is not True
            or record.get("retry_count") != 0
            or record.get("status") not in terminal_statuses
        ):
            raise ConfigurationError("authorization ledger contains a non-terminal frozen slot")


def _finalize_existing(
    arguments: argparse.Namespace,
    dc_paths: dict[str, Path],
    vcs_paths: dict[str, Path],
) -> int:
    output = smoke._directory(arguments.output)
    site_work = smoke._directory(arguments.site_work)
    broker_root = smoke._directory(arguments.broker_root)
    rtllm = smoke._directory(arguments.rtllm_source)
    pdk = smoke._directory(arguments.pdk_root)
    plan = _read_json(smoke._regular_file(output / "plan.json", "RTLLM harder plan"))
    if (
        plan.get("campaign_id") != _CAMPAIGN_ID
        or plan.get("run_specs") != [_spec_payload(spec) for spec in _RUN_SPECS]
        or plan.get("planned_codex_processes") != _PROCESS_COUNT
        or plan.get("automatic_retries") != 0
    ):
        raise ConfigurationError("existing plan differs from the frozen RTLLM harder campaign")
    results = _load_existing_results(output)
    hashes = [result.manifest.run_config_hash for result in results]
    if plan.get("run_config_hashes") != hashes:
        raise ConfigurationError("existing run configuration hashes differ from the plan")
    ledger = _read_json(
        smoke._regular_file(
            output / "evidence" / "process-authorizations.json", "authorization ledger"
        )
    )
    records = ledger.get("records")
    _validate_authorization_ledger(records)
    service = VeriGym(_registries())
    source_config = _source_config(rtllm)
    _load_tasks(service, source_config)
    profile_paths = {
        **{f"dc_{name}": path for name, path in dc_paths.items()},
        **{f"vcs_{name}": path for name, path in vcs_paths.items()},
    }
    replay, scan, redaction = _audit_outputs(
        results,
        service,
        source_config,
        profile_paths,
        {"rtllm": rtllm, "pdk": pdk},
        (site_work, broker_root, output),
    )
    summary = _campaign_summary(results, replay, scan, redaction)
    _persist_evidence(output, replay, scan, redaction, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["diagnostic_complete"] else 2


def main() -> int:
    arguments = _parser().parse_args()
    dc_paths = _named_paths(arguments.dc_profile, "DC")
    vcs_paths = _named_paths(arguments.vcs_profile, "VCS")
    if arguments.finalize_existing:
        return _finalize_existing(arguments, dc_paths, vcs_paths)

    site_work = smoke._new_path(arguments.site_work, "site-profile work directory")
    output = smoke._new_path(arguments.output, "diagnostic output")
    broker_root = smoke._broker_root(smoke._new_path(arguments.broker_root, "Codex broker root"))
    rtllm = smoke._directory(arguments.rtllm_source)
    pdk = smoke._directory(arguments.pdk_root)
    capability_path, capability, auth = smoke._codex_preflight(arguments.codex_binary, site_work)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    image_id = smoke._docker_image_id(arguments.image)
    docker_config = smoke._docker_config(arguments.image, image_id)
    registries = _registries()
    service = VeriGym(registries)
    source_config = _source_config(rtllm)
    _load_tasks(service, source_config)
    prepared = _prepare_profiles(
        registries,
        site_work=site_work,
        image=arguments.image,
        image_id=image_id,
        pdk_root=pdk,
        dc_paths=dc_paths,
    )
    runtime_descriptor, qualifications, verifiers = _no_model_qualification(
        service,
        source_config=source_config,
        docker_config=docker_config,
        prepared=prepared,
        vcs_paths=vcs_paths,
        scratch=site_work / "qualification",
    )
    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(broker_root)
    configs = _frozen_run_configs(
        service,
        source_config=source_config,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        verifiers=verifiers,
        capability=capability,
        auth=auth,
        output=output / "runs",
    )
    plan = _build_plan(
        capability=capability,
        auth=auth,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        verifiers=verifiers,
        qualifications=qualifications,
        configs=configs,
    )
    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        print(
            json.dumps(
                {
                    "status": "qualified_plan_only",
                    "model_calls": 0,
                    "planned_codex_processes": _PROCESS_COUNT,
                    "diagnostic_only": True,
                    "benchmark_score_claimed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if os.environ.get(_OPT_IN) != "1":
        raise ConfigurationError(f"execution requires {_OPT_IN}=1")
    output.mkdir(parents=True)
    (output / "runs").mkdir()
    (output / "evidence").mkdir()
    atomic_dump_json(output / "plan.json", plan)
    results = _execute_exactly_32(service, configs, output)
    profile_paths = {
        **{f"dc_{name}": path for name, path in dc_paths.items()},
        **{f"vcs_{name}": path for name, path in vcs_paths.items()},
    }
    replay, scan, redaction = _audit_outputs(
        results,
        service,
        source_config,
        profile_paths,
        {"rtllm": rtllm, "pdk": pdk},
        (site_work, broker_root, output),
    )
    summary = _campaign_summary(results, replay, scan, redaction)
    _persist_evidence(output, replay, scan, redaction, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["diagnostic_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
