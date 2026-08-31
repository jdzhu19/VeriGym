#!/usr/bin/env python3
"""Qualify and execute a frozen 14-process RTLLM/VerilogEval multi-turn diagnostic."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke
from verigym_codex_cli import (
    CodexCliFunctionalAgentEvalAdapter,
    CodexCliFunctionalV2HighAgentEvalAdapter,
    CodexCliFunctionalV2LowAgentEvalAdapter,
    CodexCliFunctionalV2MediumAgentEvalAdapter,
)
from verigym_codex_cli.functional_agenteval_config import (
    FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH,
    FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
    FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
    FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
)
from verigym_codex_cli.functional_v2_agenteval_config import (
    FUNCTIONAL_V2_HIGH_IDENTITY,
    FUNCTIONAL_V2_LOW_IDENTITY,
    FUNCTIONAL_V2_MEDIUM_IDENTITY,
    FUNCTIONAL_V2_PROMPT_HASH,
    FUNCTIONAL_V2_TOOL_POLICY_FINGERPRINT,
)

from verigym.core.agent_feedback import (
    AgentFeedbackController,
    resolve_agent_feedback_contract,
    task_with_agent_feedback_contract,
)
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.synthesis_projection import resolve_synthesis_source_projection
from verigym.core.workspace import copy_tree_safely
from verigym.experiments.state import atomic_dump_json
from verigym.profiles.identity import resolved_profile_component_hashes
from verigym.registry.base import PluginOrigin
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus
from verigym.tools.base import SynthesisBackendPlugin

_PROCESS_COUNT = 14
_OPT_IN = "VERIGYM_RUN_RTL_FUNCTIONAL_MULTITURN_14"
_PATH_CATEGORIES = frozenset(
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
_TOOL_NAMES = frozenset(
    {"list_files", "read_file", "apply_patch", "run_public_test", "inspect_diff", "finish"}
)
_PROGRESS_PHASES = frozenset(
    {
        "input_qualification",
        "codex_preflight",
        "docker_preflight",
        "source_qualification",
        "toolchain_qualification",
        "freeze",
        "qualified_plan",
        "execution",
        "finalization",
    }
)
_PROGRESS_STATUSES = frozenset({"started", "running", "completed", "failed"})


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    task_id: str
    source_key: str
    profile_name: str | None = None
    ppa: bool = False


@dataclass(frozen=True)
class CampaignProfile:
    tier: str
    campaign_id: str
    agent_name: str
    adapter_class: type[Any]
    model_id: str
    reasoning_effort: str
    prompt_contract_id: str
    agent_version_id: str
    agent_version_hash: str
    prompt_hash: str
    tool_policy_fingerprint: str
    ve_variant: str
    counter_variant: str
    up_down_variant: str
    rtllm_public_feedback_semantics: str
    verilog_eval_public_feedback_semantics: str


_VE_TASKS = (
    "Prob038_count15",
    "Prob067_countslow",
    "Prob096_review2015_fsmseq",
    "Prob100_fsm3comb",
    "Prob107_fsm1s",
    "Prob118_history_shift",
    "Prob124_rule110",
    "Prob128_fsm_ps2",
    "Prob137_fsm_serial",
    "Prob150_review2015_fsmonehot",
)

_LEGACY_PROFILE = CampaignProfile(
    tier="legacy",
    campaign_id="rtl-functional-multiturn-codex-gpt54mini-medium-14run-diagnostic-v1",
    agent_name="codex-cli-functional-agenteval-agent",
    adapter_class=CodexCliFunctionalAgentEvalAdapter,
    model_id="gpt-5.4-mini",
    reasoning_effort="medium",
    prompt_contract_id="repository_action_v2_prompt_v7",
    agent_version_id=FUNCTIONAL_AGENTEVAL_AGENT_VERSION_ID,
    agent_version_hash=FUNCTIONAL_AGENTEVAL_AGENT_VERSION_HASH,
    prompt_hash=FUNCTIONAL_AGENTEVAL_PROMPT_HASH,
    tool_policy_fingerprint=FUNCTIONAL_AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    ve_variant="v2-spec-to-rtl-agent-eval-functional-v1",
    counter_variant="counter_12_agent_eval_functional_v1",
    up_down_variant="up_down_counter_agent_eval_functional_v1",
    rtllm_public_feedback_semantics="compile_and_independent_functional_smoke_v1",
    verilog_eval_public_feedback_semantics="compile_and_independent_functional_smoke_v1",
)


def _v2_profile(tier: str, adapter_class: type[Any], identity: Any) -> CampaignProfile:
    return CampaignProfile(
        tier=tier,
        campaign_id=f"rtl-functional-multiturn-codex-{tier}-14run-diagnostic-v2",
        agent_name=identity.agent_name,
        adapter_class=adapter_class,
        model_id=identity.model_id,
        reasoning_effort=identity.reasoning_effort,
        prompt_contract_id="repository_action_v2_prompt_v8",
        agent_version_id=identity.agent_version_id,
        agent_version_hash=identity.agent_version_hash,
        prompt_hash=FUNCTIONAL_V2_PROMPT_HASH,
        tool_policy_fingerprint=FUNCTIONAL_V2_TOOL_POLICY_FINGERPRINT,
        ve_variant="v2-spec-to-rtl-agent-eval-functional-v2",
        counter_variant="counter_12_agent_eval_functional_v2",
        up_down_variant="up_down_counter_agent_eval_functional_v2",
        rtllm_public_feedback_semantics="compile_and_independent_functional_smoke_v2",
        verilog_eval_public_feedback_semantics="compile_and_independent_functional_smoke_v2",
    )


def _v3_profile(base: CampaignProfile) -> CampaignProfile:
    return CampaignProfile(
        tier=base.tier,
        campaign_id=f"rtl-functional-multiturn-codex-{base.tier}-14run-diagnostic-v3",
        agent_name=base.agent_name,
        adapter_class=base.adapter_class,
        model_id=base.model_id,
        reasoning_effort=base.reasoning_effort,
        prompt_contract_id=base.prompt_contract_id,
        agent_version_id=base.agent_version_id,
        agent_version_hash=base.agent_version_hash,
        prompt_hash=base.prompt_hash,
        tool_policy_fingerprint=base.tool_policy_fingerprint,
        ve_variant="v2-spec-to-rtl-agent-eval-functional-v3",
        counter_variant=base.counter_variant,
        up_down_variant=base.up_down_variant,
        rtllm_public_feedback_semantics=base.rtllm_public_feedback_semantics,
        verilog_eval_public_feedback_semantics=("compile_and_independent_functional_smoke_v3"),
    )


_CAMPAIGN_PROFILES = {
    "legacy": _LEGACY_PROFILE,
    "low": _v2_profile("low", CodexCliFunctionalV2LowAgentEvalAdapter, FUNCTIONAL_V2_LOW_IDENTITY),
    "medium": _v2_profile(
        "medium", CodexCliFunctionalV2MediumAgentEvalAdapter, FUNCTIONAL_V2_MEDIUM_IDENTITY
    ),
    "high": _v2_profile(
        "high", CodexCliFunctionalV2HighAgentEvalAdapter, FUNCTIONAL_V2_HIGH_IDENTITY
    ),
}
_CAMPAIGN_PROFILES.update(
    {f"{tier}-v3": _v3_profile(_CAMPAIGN_PROFILES[tier]) for tier in ("low", "medium", "high")}
)
_PROFILE = _LEGACY_PROFILE
_CAMPAIGN_ID = _PROFILE.campaign_id
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_VE_VARIANT = _PROFILE.ve_variant
_COUNTER_VARIANT = _PROFILE.counter_variant
_UP_DOWN_VARIANT = _PROFILE.up_down_variant


def _run_specs() -> tuple[RunSpec, ...]:
    return (
        RunSpec("01-counter-open", f"rtllm/{_COUNTER_VARIANT}", "counter", "counter_open", True),
        RunSpec("02-counter-dc", f"rtllm/{_COUNTER_VARIANT}", "counter", "counter_dc", True),
        RunSpec(
            "03-up-down-open",
            f"rtllm/{_UP_DOWN_VARIANT}",
            "up_down",
            "up_down_open",
            True,
        ),
        RunSpec(
            "04-up-down-dc",
            f"rtllm/{_UP_DOWN_VARIANT}",
            "up_down",
            "up_down_dc",
            True,
        ),
        *(
            RunSpec(
                f"{ordinal:02d}-ve-{native_id.lower()}",
                f"verilog-eval/{_VE_VARIANT}/{native_id}",
                "verilog_eval",
            )
            for ordinal, native_id in enumerate(_VE_TASKS, start=5)
        ),
    )


_RUN_SPECS = _run_specs()
_RUN_IDS = tuple(spec.run_id for spec in _RUN_SPECS)
_PPA_RUN_IDS = frozenset(spec.run_id for spec in _RUN_SPECS if spec.ppa)


def _activate_profile(tier: str) -> None:
    global _CAMPAIGN_ID, _COUNTER_VARIANT, _OUTPUT, _PPA_RUN_IDS, _PROFILE
    global _RUN_IDS, _RUN_SPECS, _UP_DOWN_VARIANT, _VE_VARIANT
    _PROFILE = _CAMPAIGN_PROFILES[tier]
    _CAMPAIGN_ID = _PROFILE.campaign_id
    _OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
    _VE_VARIANT = _PROFILE.ve_variant
    _COUNTER_VARIANT = _PROFILE.counter_variant
    _UP_DOWN_VARIANT = _PROFILE.up_down_variant
    _RUN_SPECS = _run_specs()
    _RUN_IDS = tuple(spec.run_id for spec in _RUN_SPECS)
    _PPA_RUN_IDS = frozenset(spec.run_id for spec in _RUN_SPECS if spec.ppa)


CampaignInfrastructureError = smoke.CampaignInfrastructureError
PreparedProfile = smoke.PreparedProfile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--tier", choices=tuple(_CAMPAIGN_PROFILES), default="legacy")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument(
        "--broker-root",
        type=Path,
        default=Path("/data/jzhu484/Agent/.verigym-tmp/cb-fmt1"),
    )
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--verilog-eval-source", type=Path, required=True)
    parser.add_argument("--pdk-root", type=Path, required=True)
    parser.add_argument("--dc-counter-profile", type=Path, required=True)
    parser.add_argument("--dc-up-down-profile", type=Path, required=True)
    parser.add_argument("--vcs-counter-profile", type=Path, required=True)
    parser.add_argument("--vcs-up-down-profile", type=Path, required=True)
    parser.add_argument("--image", default=smoke._IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    _activate_profile(arguments.tier)
    if arguments.output is None:
        arguments.output = _OUTPUT
    if arguments.finalize_existing:
        return _finalize_existing(arguments)

    site_work = smoke._new_path(arguments.site_work, "site-profile work directory")
    progress_path = _campaign_progress_path(site_work)
    _record_progress(progress_path, phase="input_qualification", status="started")
    output = smoke._new_path(arguments.output, "diagnostic output")
    broker_root = smoke._new_path(arguments.broker_root, "Codex broker root")
    inputs = _inputs(arguments)
    profile_paths = _profile_paths(arguments)
    _record_progress(progress_path, phase="input_qualification", status="completed")
    _record_progress(progress_path, phase="codex_preflight", status="started")
    capability_path, capability, auth = smoke._codex_preflight(
        arguments.codex_binary,
        site_work,
    )
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    _record_progress(progress_path, phase="codex_preflight", status="completed")
    _record_progress(progress_path, phase="docker_preflight", status="started")
    image_id = smoke._docker_image_id(arguments.image)
    docker_config = smoke._docker_config(arguments.image, image_id)
    _record_progress(progress_path, phase="docker_preflight", status="completed")
    registries = _registries()
    service = VeriGym(registries)
    source_configs = _source_configs(inputs)
    _record_progress(progress_path, phase="source_qualification", status="started")
    _validate_sources(service, source_configs)
    _record_progress(progress_path, phase="source_qualification", status="completed")
    _record_progress(progress_path, phase="toolchain_qualification", status="started")
    prepared = smoke._prepare_profiles(
        registries,
        site_work=site_work,
        image=arguments.image,
        image_id=image_id,
        pdk_root=inputs["pdk"],
        dc_paths=profile_paths,
    )
    runtime_descriptor, qualifications = _no_model_qualification(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        prepared=prepared,
        vcs_paths=profile_paths,
        scratch=site_work / "qualification",
    )
    _record_progress(progress_path, phase="toolchain_qualification", status="completed")
    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(smoke._broker_root(broker_root))
    _record_progress(progress_path, phase="freeze", status="started")
    configs = _frozen_run_configs(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        agent_options=_agent_options(capability, auth),
        output=output / "runs",
    )
    plan = _build_plan(
        capability=capability,
        auth=auth,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        qualifications=qualifications,
        configs=configs,
    )
    _record_progress(progress_path, phase="freeze", status="completed")
    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        _record_progress(progress_path, phase="qualified_plan", status="completed")
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
    progress_mirror = output / "evidence" / "campaign-progress.json"
    _record_progress(
        progress_path,
        phase="execution",
        status="started",
        mirror=progress_mirror,
    )
    results = _execute_exactly_fourteen(
        service,
        configs,
        output,
        progress_path=progress_path,
        progress_mirror=progress_mirror,
    )
    _record_progress(
        progress_path,
        phase="execution",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    _record_progress(
        progress_path,
        phase="finalization",
        status="started",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        site_paths=(site_work, broker_root, output),
    )
    redaction = _redaction_audit(results)
    summary = _campaign_summary(results, replay, scan, redaction)
    _persist_final_evidence(output, replay, scan, redaction, summary)
    _record_progress(
        progress_path,
        phase="finalization",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        resolved_processes=summary["resolved_count"],
        mirror=progress_mirror,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fully_successful"] else 2


def _inputs(arguments: argparse.Namespace) -> dict[str, Path]:
    return {
        "rtllm": smoke._directory(arguments.rtllm_source),
        "verilog_eval": smoke._directory(arguments.verilog_eval_source),
        "pdk": smoke._directory(arguments.pdk_root),
    }


def _profile_paths(arguments: argparse.Namespace) -> dict[str, Path]:
    return {
        "dc_counter": smoke._regular_file(arguments.dc_counter_profile),
        "dc_up_down": smoke._regular_file(arguments.dc_up_down_profile),
        "vcs_counter": smoke._regular_file(arguments.vcs_counter_profile),
        "vcs_up_down": smoke._regular_file(arguments.vcs_up_down_profile),
    }


def _source_configs(inputs: dict[str, Path]) -> dict[str, SuiteSourceConfig]:
    return {
        "counter": SuiteSourceConfig(source_root=inputs["rtllm"], variant=_COUNTER_VARIANT),
        "up_down": SuiteSourceConfig(source_root=inputs["rtllm"], variant=_UP_DOWN_VARIANT),
        "verilog_eval": SuiteSourceConfig(source_root=inputs["verilog_eval"], variant=_VE_VARIANT),
    }


def _registries() -> Any:
    registries = smoke._registries()
    if _PROFILE.agent_name not in registries.agents.names():
        registries.agents.register(
            _PROFILE.adapter_class(),
            origin=PluginOrigin(
                package="verigym-codex-cli",
                version="0.1.0",
                entry_point=None,
                registration="runtime",
            ),
        )
    return registries


def _validate_sources(service: VeriGym, configs: dict[str, SuiteSourceConfig]) -> None:
    for spec in _RUN_SPECS:
        suite, task, assets = service.load_task(spec.task_id, configs[spec.source_key])
        report = suite.validate_source()
        if (
            not report.valid
            or task.id != spec.task_id
            or not Path(assets.visible_root).is_dir()
            or len(assets.read_only_mounts) != 1
            or task.metadata.get("public_feedback_semantics")
            != (
                _PROFILE.verilog_eval_public_feedback_semantics
                if spec.source_key == "verilog_eval"
                else _PROFILE.rtllm_public_feedback_semantics
            )
        ):
            raise ConfigurationError(f"functional source qualification failed for {spec.task_id}")


def _no_model_qualification(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    docker_config: Any,
    prepared: dict[str, PreparedProfile],
    vcs_paths: dict[str, Path],
    scratch: Path,
) -> tuple[Any, dict[str, Any]]:
    scratch.mkdir()
    runtime = service.registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("rtl-functional-multiturn-preflight")
    try:
        descriptor = runtime.descriptor
        image = descriptor.image
        if image is None or image.iverilog_version is None or "12." not in image.iverilog_version:
            raise ConfigurationError("qualified Docker runtime does not expose Icarus 12")
        records: dict[str, Any] = {
            "public_functional_feedback": _qualify_public_feedback(
                service, source_configs, runtime
            ),
            "rtllm_hidden_reference_and_bad": {
                key: smoke._qualify_functional(
                    service,
                    source_configs[key],
                    runtime,
                    scratch / f"hidden-{key}",
                )
                for key in ("counter", "up_down")
            },
            "verilog_eval_hidden_references": _qualify_verilog_eval_hidden(
                service,
                source_configs["verilog_eval"],
                runtime,
                scratch / "hidden-verilog-eval",
            ),
        }
        resolved_items: dict[str, PreparedProfile] = {}
        for name, key in (
            ("counter_open", "counter"),
            ("up_down_open", "up_down"),
            ("counter_dc", "counter"),
            ("up_down_dc", "up_down"),
        ):
            item = prepared[name]
            resolved, record = smoke._qualify_synthesis(
                service,
                source_configs[key],
                runtime,
                item.profile,
                scratch / f"synthesis-{name}",
            )
            resolved_items[name] = PreparedProfile(item.profile, resolved)
            records[f"synthesis_{name}"] = record
        prepared.update(resolved_items)
        records["agent_feedback_exact_path"] = _qualify_agent_feedback(
            service,
            source_configs=source_configs,
            runtime=runtime,
            prepared=prepared,
        )
        records["vcs_mcp_preflight"] = smoke._qualify_vcs(
            service,
            rtllm_source=source_configs["counter"].source_root,
            profile_paths=(vcs_paths["vcs_counter"], vcs_paths["vcs_up_down"]),
            scratch=scratch / "vcs",
        )
        return descriptor, records
    finally:
        runtime.close()


def _unique_task_specs() -> list[RunSpec]:
    seen: set[str] = set()
    unique: list[RunSpec] = []
    for spec in _RUN_SPECS:
        if spec.task_id not in seen:
            seen.add(spec.task_id)
            unique.append(spec)
    return unique


def _qualify_public_feedback(
    service: VeriGym,
    source_configs: dict[str, SuiteSourceConfig],
    runtime: Any,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for spec in _unique_task_specs():
        suite, task, assets = service.load_task(spec.task_id, source_configs[spec.source_key])
        reference = suite.reference_solution(task)
        if reference is None:
            raise ConfigurationError("public feedback qualification lacks a reference")
        visible = Path(assets.visible_root)
        visible_paths = {
            path.relative_to(visible).as_posix() for path in visible.rglob("*") if path.is_file()
        }
        if any(
            path.startswith("verifier/") or path.startswith("hidden/") or "public-smoke" in path
            for path in visible_paths
        ):
            raise ConfigurationError("public feedback projection exposes a protected asset")
        passed = _execute_public_candidate(runtime, task, assets, reference.files)
        top = task.metadata.get("candidate_top")
        editable = task.workspace.editable_globs
        if not isinstance(top, str) or len(editable) != 1:
            raise ConfigurationError("public feedback task has no exact candidate interface")
        rejected = _execute_public_candidate(
            runtime,
            task,
            assets,
            {editable[0]: f"module {top}; endmodule\n"},
            expect_pass=False,
        )
        if not passed or not rejected:
            raise ConfigurationError("public feedback reference/bad qualification failed")
        records.append(
            {
                "task_id": spec.task_id,
                "reference_passed": True,
                "known_bad_rejected": True,
                "hidden_assets_not_visible": True,
                "public_test_contract_hash": task.metadata["agent_eval"][
                    "public_test_contract_hash"
                ],
            }
        )
    return {"passed": True, "model_calls": 0, "records": records}


def _execute_public_candidate(
    runtime: Any,
    task: Any,
    assets: Any,
    files: dict[str, str],
    *,
    expect_pass: bool = True,
) -> bool:
    session = runtime.create_session(
        SessionSpec(
            source_dir=assets.visible_root,
            label="agent",
            max_output_bytes=task.budget.max_output_bytes_per_tool,
            read_only_mounts=assets.read_only_mounts,
        )
    )
    try:
        for relative, content in sorted(files.items()):
            session.write_file(relative, content.encode("utf-8"))
        completed = session.execute_public_test("compile")
        infrastructure = completed.failure_origin == "control_plane" or completed.error is not None
        if infrastructure:
            raise ConfigurationError("public feedback qualification infrastructure failed")
        observed = completed.exit_code == 0
        return observed is expect_pass
    finally:
        session.close()


def _qualify_verilog_eval_hidden(
    service: VeriGym,
    source_config: SuiteSourceConfig,
    runtime: Any,
    scratch: Path,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for spec in (item for item in _RUN_SPECS if item.source_key == "verilog_eval"):
        suite, task, assets = service.load_task(spec.task_id, source_config)
        reference = suite.reference_solution(task)
        if reference is None:
            raise ConfigurationError("VerilogEval qualification lacks a reference")
        candidate = scratch / spec.run_id
        copy_tree_safely(Path(assets.visible_root), candidate)
        for relative, content in sorted(reference.files.items()):
            destination = candidate / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        results = service._verify_candidate(
            suite=suite,
            task=task,
            assets=assets,
            runtime=runtime,
            candidate_dir=candidate,
            artifact_root=scratch / "artifacts" / spec.run_id,
        )
        if not results or not all(result.status == VerifierStatus.PASSED for result in results):
            if results and _completed_reference_misclassified_as_timeout(results):
                raise CampaignInfrastructureError(
                    "VerilogEval reference produced a complete zero-mismatch result after the "
                    "Docker attach deadline; qualification is invalid due control-plane timing"
                )
            raise ConfigurationError("VerilogEval reference hidden qualification failed")
        records.append({"task_id": spec.task_id, "reference_resolved": True})
    return {"passed": True, "model_calls": 0, "records": records}


def _completed_reference_misclassified_as_timeout(results: list[Any]) -> bool:
    failed = [result for result in results if result.status != VerifierStatus.PASSED]
    if len(failed) != 1:
        return False
    result = failed[0]
    metadata = result.metadata
    return bool(
        result.exit_code == 0
        and isinstance(metadata, dict)
        and metadata.get("process_timed_out") is True
        and metadata.get("native_result_marker_found") is True
        and metadata.get("native_timeout") is False
        and metadata.get("mismatches") == 0
        and isinstance(metadata.get("samples_checked"), int)
        and metadata["samples_checked"] > 0
    )


def _qualify_agent_feedback(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    runtime: Any,
    prepared: dict[str, PreparedProfile],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for source_key, task_id, profile_name in (
        ("counter", f"rtllm/{_COUNTER_VARIANT}", "counter_open"),
        ("up_down", f"rtllm/{_UP_DOWN_VARIANT}", "up_down_dc"),
    ):
        suite, task, assets = service.load_task(task_id, source_configs[source_key])
        reference = suite.reference_solution(task)
        item = prepared[profile_name]
        if reference is None or item.resolved is None or item.profile.flow is None:
            raise ConfigurationError("agent feedback qualification inputs are incomplete")
        projection = resolve_synthesis_source_projection(task)
        if not projection.profile_sources:
            raise ConfigurationError("agent feedback synthesis projection is empty")
        backend = service.registries.tools.get(item.profile.flow.backend_plugin)
        if not isinstance(backend, SynthesisBackendPlugin):
            raise ConfigurationError("agent feedback backend is unavailable")
        contract = resolve_agent_feedback_contract(
            task=task,
            ppa_enabled=True,
            ppa_max_executions=3,
            resolved_profile=item.resolved,
            profile_backend=item.profile.flow.backend_plugin,
        )
        if contract is None:
            raise ConfigurationError("agent feedback contract was not resolved")
        effective_task = task_with_agent_feedback_contract(task, contract)
        controller = AgentFeedbackController(
            contract=contract,
            task=effective_task,
            runtime=runtime,
            profile=item.profile,
            resolved_profile=item.resolved,
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
        evaluations = controller.evaluations
        if (
            compile_result.exit_code != 0
            or ppa_result.exit_code != 0
            or [item.test_id for item in evaluations] != ["compile", "ppa"]
            or not all(item.passed for item in evaluations)
            or evaluations[1].metrics is None
        ):
            raise ConfigurationError("exact agent feedback qualification failed")
        records.append(
            {
                "task_id": task_id,
                "profile_name": profile_name,
                "public_functional_validation_passed": True,
                "candidate_ppa_passed": True,
            }
        )
    return {"passed": True, "model_calls": 0, "records": records}


def _agent_options(capability: Any, auth: Any) -> dict[str, Any]:
    return {
        "model_id": _PROFILE.model_id,
        "reasoning_effort": _PROFILE.reasoning_effort,
        "max_process_time_s": 900,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        ),
        "expected_cli_version": smoke._EXPECTED_CLI_VERSION,
        "expected_cli_executable_sha256": smoke._EXPECTED_CODEX_SHA256,
        "expected_capability_fingerprint": capability.capability_fingerprint,
        "expected_prompt_hash": _PROFILE.prompt_hash,
        "expected_tool_policy_fingerprint": _PROFILE.tool_policy_fingerprint,
        "expected_requested_auth_mode": auth.requested_auth_mode,
        "expected_resolved_auth_mode": auth.resolved_auth_mode,
        "expected_auth_semantic_id": auth.auth_semantic_id,
        "prompt_contract_id": _PROFILE.prompt_contract_id,
        "scoring_agent_version_id": _PROFILE.agent_version_id,
        "scoring_agent_version_hash": _PROFILE.agent_version_hash,
    }


def _frozen_run_configs(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    docker_config: Any,
    runtime_descriptor: Any,
    prepared: dict[str, PreparedProfile],
    agent_options: dict[str, Any],
    output: Path,
) -> list[RunConfig]:
    configs: list[RunConfig] = []
    for spec in _RUN_SPECS:
        profile_id = (
            prepared[spec.profile_name].profile.id if spec.profile_name is not None else None
        )
        base = RunConfig(
            task_id=spec.task_id,
            mode=InteractionMode.AGENT,
            agent=_PROFILE.agent_name,
            agent_options=agent_options,
            suite_source=source_configs[spec.source_key],
            runtime="docker",
            docker_config=docker_config,
            toolchain_profile=profile_id,
            agent_ppa_feedback=spec.ppa,
            agent_ppa_max_calls=3,
            seed=0,
            sample_index=0,
            output=output,
            run_id=spec.run_id,
        )
        configs.append(
            smoke._freeze_run_config(
                service,
                base,
                runtime_descriptor=runtime_descriptor,
                expected_profile=(
                    prepared[spec.profile_name].resolved if spec.profile_name is not None else None
                ),
            )
        )
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("functional diagnostic must freeze exactly fourteen runs")
    return configs


def _build_plan(
    *,
    capability: Any,
    auth: Any,
    runtime_descriptor: Any,
    prepared: dict[str, PreparedProfile],
    qualifications: dict[str, Any],
    configs: list[RunConfig],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "run_specs": [_run_spec_payload(spec) for spec in _RUN_SPECS],
        **({"comparison_tier": _PROFILE.tier} if _PROFILE.tier != "legacy" else {}),
        "model": _PROFILE.model_id,
        "reasoning_effort": _PROFILE.reasoning_effort,
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "benchmark_suites": ["rtllm", "verilog-eval"],
        "multiturn_definition": (
            "read_first_candidate_public_compile_and_functional_smoke_repair_revalidate_"
            "optional_ppa_typed_finish_hidden_once_v1"
        ),
        "codex": {
            "version": capability.version_output,
            "executable_sha256": capability.executable_sha256,
            "capability_fingerprint": capability.capability_fingerprint,
            "agent_version_id": _PROFILE.agent_version_id,
            "agent_version_hash": _PROFILE.agent_version_hash,
            "prompt_hash": _PROFILE.prompt_hash,
            "tool_policy_fingerprint": _PROFILE.tool_policy_fingerprint,
            "auth": auth.safe_dict(),
        },
        "runtime": runtime_descriptor.model_dump(mode="json"),
        "profiles": {
            name: {
                "declared_hash": content_hash(item.profile),
                "resolved_hash": item.resolved.resolved_profile_hash,
                "component_hashes": resolved_profile_component_hashes(item.resolved),
            }
            for name, item in prepared.items()
            if item.resolved is not None
        },
        "qualifications": qualifications,
        "run_config_hashes": [content_hash(item.identity_payload()) for item in configs],
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
    }


def _run_spec_payload(spec: RunSpec) -> dict[str, Any]:
    return {
        "run_id": spec.run_id,
        "task_id": spec.task_id,
        "source_key": spec.source_key,
        "profile_name": spec.profile_name,
        "agent_ppa_feedback": spec.ppa,
    }


def _execute_exactly_fourteen(
    service: VeriGym,
    configs: list[RunConfig],
    output: Path,
    *,
    progress_path: Path | None = None,
    progress_mirror: Path | None = None,
) -> list[RunResult]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("launcher must contain exactly fourteen frozen runs")
    ledger: list[dict[str, Any]] = []
    results: list[RunResult] = []
    for ordinal, config in enumerate(configs, start=1):
        record: dict[str, Any] = {
            "ordinal": ordinal,
            "run_id": config.run_id,
            "task_id": config.task_id,
            "authorization_granted": True,
            "process_started": False,
            "identity_observation_count": 0,
            "provider_observation_recorded": False,
            "retry_count": 0,
            "status": "authorized",
        }
        ledger.append(record)
        _write_ledger(output, ledger)
        if progress_path is not None:
            _record_progress(
                progress_path,
                phase="execution",
                status="running",
                completed_processes=ordinal - 1,
                active_process_ordinal=ordinal,
                mirror=progress_mirror,
            )
        try:
            run = service.run(config)
        except Exception:
            run_dir = config.output.expanduser().resolve() / str(config.run_id)
            smoke._update_process_ledger_record(record, run_dir=run_dir)
            record["status"] = "infrastructure_failure"
            _write_ledger(output, ledger)
            if progress_path is not None:
                _record_progress(
                    progress_path,
                    phase="execution",
                    status="failed",
                    completed_processes=ordinal - 1,
                    active_process_ordinal=ordinal,
                    mirror=progress_mirror,
                )
            raise
        smoke._update_process_ledger_record(record, run_dir=run.run_dir, run=run)
        record["identity_observation_count"] = len(run.manifest.external_agent_observations)
        record["provider_observation_recorded"] = _identity_observation_valid(run)
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        if not record["provider_observation_recorded"]:
            record["status"] = "identity_infrastructure_failure"
            _write_ledger(output, ledger)
            if progress_path is not None:
                _record_progress(
                    progress_path,
                    phase="execution",
                    status="failed",
                    completed_processes=ordinal,
                    mirror=progress_mirror,
                )
            raise CampaignInfrastructureError(
                "functional diagnostic stopped after invalid identity evidence"
            )
        failure = run.scorecard.failure
        infrastructure = run.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        policy = failure is not None and failure.kind == "policy"
        if infrastructure:
            record["status"] = "infrastructure_failure"
        elif policy:
            record["status"] = "policy_failure"
        elif failure is not None:
            record["status"] = "contained_model_failure"
        elif not run.scorecard.resolved:
            record["status"] = "verifier_rejection"
        else:
            record["status"] = "completed"
        _write_ledger(output, ledger)
        if ordinal < len(configs) and (infrastructure or policy):
            if progress_path is not None:
                _record_progress(
                    progress_path,
                    phase="execution",
                    status="failed",
                    completed_processes=ordinal,
                    mirror=progress_mirror,
                )
            raise CampaignInfrastructureError(
                "functional diagnostic stopped after infrastructure or safety failure"
            )
    if len(results) != _PROCESS_COUNT:
        raise ConfigurationError("fourteen-process diagnostic stopped before completion")
    return results


def _identity_observation_valid(result: RunResult) -> bool:
    observations = result.manifest.external_agent_observations
    identity_path = result.run_dir / "artifacts" / "codex_cli" / "identity.json"
    if len(observations) != 1 or not identity_path.is_file():
        return False
    observation = observations[0]
    return bool(
        observation.invocation_count == 1
        and observation.requested_model_id == _PROFILE.model_id
        and observation.observed_model_id in {None, _PROFILE.model_id}
        and observation.effective_reasoning_effort == _PROFILE.reasoning_effort
        and observation.harness_id == _PROFILE.agent_version_id
        and observation.agent_version_hash == _PROFILE.agent_version_hash
        and observation.prompt_contract_hash == _PROFILE.prompt_hash
        and observation.tool_policy_fingerprint == _PROFILE.tool_policy_fingerprint
    )


def _write_ledger(output: Path, records: list[dict[str, Any]]) -> None:
    atomic_dump_json(output / "evidence" / "process-authorizations.json", {"records": records})


def _record_progress(
    path: Path,
    *,
    phase: str,
    status: str,
    completed_processes: int = 0,
    active_process_ordinal: int | None = None,
    resolved_processes: int | None = None,
    mirror: Path | None = None,
) -> None:
    """Persist and print bounded, content-free campaign progress."""

    if phase not in _PROGRESS_PHASES or status not in _PROGRESS_STATUSES:
        raise ConfigurationError("campaign progress phase or status is not allowlisted")
    if not 0 <= completed_processes <= _PROCESS_COUNT:
        raise ConfigurationError("campaign progress completed count is out of range")
    if active_process_ordinal is not None and not 1 <= active_process_ordinal <= _PROCESS_COUNT:
        raise ConfigurationError("campaign progress active ordinal is out of range")
    if resolved_processes is not None and not 0 <= resolved_processes <= completed_processes:
        raise ConfigurationError("campaign progress resolved count is out of range")
    payload = {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "comparison_tier": _PROFILE.tier,
        "phase": phase,
        "status": status,
        "planned_processes": _PROCESS_COUNT,
        "completed_processes": completed_processes,
        "active_process_ordinal": active_process_ordinal,
        "resolved_processes": resolved_processes,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
    }
    atomic_dump_json(path, payload)
    if mirror is not None:
        atomic_dump_json(mirror, payload)
    print(json.dumps({"event": "campaign_progress", **payload}, sort_keys=True), flush=True)


def _campaign_progress_path(site_work: Path) -> Path:
    """Keep preflight progress outside the not-yet-created site-work directory."""

    return site_work.parent / f".{site_work.name}.campaign-progress.json"


def _scan_outputs(
    results: list[RunResult],
    service: VeriGym,
    configs: dict[str, SuiteSourceConfig],
    profile_paths: dict[str, Path],
    inputs: dict[str, Path],
    *,
    site_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    sensitive: list[tuple[str, bytes]] = []
    for spec in _unique_task_specs():
        suite, task, assets = service.load_task(spec.task_id, configs[spec.source_key])
        sensitive.extend(
            ("hidden_rtl", asset.content.encode("utf-8"))
            for asset in assets.hidden_assets
            if asset.content
        )
        reference = suite.reference_solution(task)
        if reference is not None:
            sensitive.extend(
                ("reference_rtl", value.encode("utf-8")) for value in reference.files.values()
            )
    path_markers = [
        *(str(path).encode("utf-8") for path in profile_paths.values()),
        *(str(path).encode("utf-8") for path in inputs.values()),
        *(str(path).encode("utf-8") for path in site_paths),
    ]
    proxy_markers = [
        value.encode("utf-8")
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
        if (value := os.environ.get(name))
    ]
    findings: set[tuple[str, str]] = set()
    for result in results:
        for file in sorted(result.run_dir.rglob("*")):
            if file.is_symlink():
                findings.add((result.manifest.run_id, "symlink"))
                continue
            if not file.is_file() or file.stat().st_size > 16 * 1024 * 1024:
                continue
            relative = file.relative_to(result.run_dir).as_posix()
            payload = file.read_bytes()
            model_facing = relative.startswith("artifacts/codex_cli/")
            if not relative.startswith("candidate/"):
                for category, marker in sensitive:
                    scan_reference = category != "reference_rtl" or model_facing
                    if scan_reference and len(marker) >= 32 and marker in payload:
                        findings.add((result.manifest.run_id, category))
            if model_facing and any(marker and marker in payload for marker in path_markers):
                findings.add((result.manifest.run_id, "site_path"))
            if model_facing and any(marker and marker in payload for marker in proxy_markers):
                findings.add((result.manifest.run_id, "proxy_value"))
            commercial_scan_payload = _without_safe_event_categories(payload)
            if model_facing and smoke._COMMERCIAL_DIAGNOSTIC.search(commercial_scan_payload):
                findings.add((result.manifest.run_id, "commercial_diagnostic"))
    records = [{"run_id": run_id, "category": category} for run_id, category in sorted(findings)]
    return {"schema_version": "1.0", "passed": not records, "findings": records}


def _without_safe_event_categories(payload: bytes) -> bytes:
    """Remove frozen content-free enum keys before commercial diagnostic scanning."""

    replacements = {
        b"scoring_event_mcp_server": b"",
        b"mcp_server_category_counts": b"transport_category_counts",
    }
    for marker, replacement in replacements.items():
        payload = payload.replace(marker, replacement)
    return payload


def _redaction_audit(results: list[RunResult]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for result in results:
        root = result.run_dir / "artifacts" / "codex_cli"
        process = _read_json(root / "process.json")
        summary = _read_json(root / "summary.json")
        broker = _read_json(root / "broker.json")
        forbidden = [
            name
            for name in ("raw_stdout.jsonl", "raw_stderr.txt", "training-transcript.json")
            if (root / name).exists() or (root / name).is_symlink()
        ]
        terminal_tool = broker.get("terminal_tool_name")
        terminal_path = broker.get("terminal_path_category")
        passed = bool(
            not forbidden
            and process.get("raw_output_persisted") is False
            and process.get("message_content_persisted") is False
            and process.get("reasoning_content_persisted") is False
            and summary.get("training_transcript_captured") is False
            and summary.get("raw_event_stream_persisted") is False
            and (terminal_tool is None or terminal_tool in _TOOL_NAMES)
            and (terminal_path is None or terminal_path in _PATH_CATEGORIES)
        )
        records.append(
            {
                "run_id": result.manifest.run_id,
                "passed": passed,
                "forbidden_artifact_count": len(forbidden),
                "terminal_tool_sanitized": terminal_tool is None or terminal_tool in _TOOL_NAMES,
                "terminal_path_category_bounded": terminal_path is None
                or terminal_path in _PATH_CATEGORIES,
            }
        )
    return {
        "schema_version": "1.0",
        "passed": len(records) == _PROCESS_COUNT and all(record["passed"] for record in records),
        "records": records,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("functional diagnostic evidence JSON is unavailable") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("functional diagnostic evidence JSON must be an object")
    return value


def _campaign_summary(
    results: list[RunResult],
    replay: dict[str, Any],
    scan: dict[str, Any],
    redaction: dict[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for result in results:
        evidence_root = result.run_dir / "artifacts" / "codex_cli"
        broker = _read_json(evidence_root / "broker.json")
        process = _read_json(evidence_root / "process.json")
        usage = _read_json(evidence_root / "provider-usage.json")
        failure = result.scorecard.failure
        infrastructure_failure = result.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        policy_failure = failure is not None and failure.kind == "policy"
        compile_passed = any(
            evaluation.test_id == "compile"
            and evaluation.passed
            and evaluation.candidate_hash == result.manifest.candidate_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        legal_candidate_ppa = any(
            evaluation.test_id == "ppa"
            and evaluation.passed
            and evaluation.metrics is not None
            and evaluation.candidate_hash == result.manifest.candidate_hash
            and evaluation.profile_hash == result.manifest.resolved_profile_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        verifier_ids = [item.node_id for item in result.scorecard.verifier_results]
        hidden_verifier_at_most_once = len(verifier_ids) == len(set(verifier_ids))
        ppa = result.scorecard.quality.ppa
        records.append(
            {
                "run_id": result.manifest.run_id,
                "task_id": result.manifest.task_id,
                "resolved": result.scorecard.resolved,
                "typed_finish": broker.get("finished") is True and broker.get("finish_calls") == 1,
                "identity_observation_count": len(result.manifest.external_agent_observations),
                "model_identity_valid": _identity_observation_valid(result),
                "process_started": (evidence_root / "process.json").is_file(),
                "timed_out": process.get("timed_out") is True,
                "provider_usage_complete": usage.get("usage_complete") is True,
                "policy_failure": policy_failure,
                "infrastructure_failure": infrastructure_failure,
                "failure_subcategory": broker.get("policy_failure_subcategory")
                or broker.get("infrastructure_failure_subcategory"),
                "public_validation_passed_for_final_candidate": compile_passed,
                "first_public_validation_passed": broker.get("first_public_validation_passed"),
                "public_validation_failures": broker.get("public_validation_failures", 0),
                "repair_patches_after_public_validation_failure": broker.get(
                    "repair_patches_after_public_validation_failure", 0
                ),
                "public_validation_rechecks_after_repair_patch": broker.get(
                    "public_validation_rechecks_after_repair_patch", 0
                ),
                "functional_failed_then_passed": broker.get("public_validation_failed_then_passed")
                is True,
                "hidden_verifier_node_count": len(verifier_ids),
                "hidden_verifier_at_most_once": hidden_verifier_at_most_once,
                "legal_candidate_ppa": legal_candidate_ppa,
                "final_ppa_eligible": ppa is not None and ppa.eligible,
            }
        )
    ppa_records = [record for record in records if record["run_id"] in _PPA_RUN_IDS]
    infrastructure_complete = bool(
        len(records) == _PROCESS_COUNT
        and replay.get("all_valid") is True
        and scan.get("passed") is True
        and redaction.get("passed") is True
        and all(record["process_started"] for record in records)
        and all(record["model_identity_valid"] for record in records)
        and all(record["identity_observation_count"] == 1 for record in records)
        and all(record["hidden_verifier_at_most_once"] for record in records)
        and not any(record["infrastructure_failure"] for record in records)
    )
    repair_records = [record for record in records if record["functional_failed_then_passed"]]
    fully_successful = bool(
        infrastructure_complete
        and all(record["resolved"] for record in records)
        and all(record["typed_finish"] for record in records)
        and all(record["provider_usage_complete"] for record in records)
        and all(record["public_validation_passed_for_final_candidate"] for record in records)
        and not any(record["timed_out"] for record in records)
        and not any(record["policy_failure"] for record in records)
        and len(ppa_records) == len(_PPA_RUN_IDS)
        and all(record["legal_candidate_ppa"] for record in ppa_records)
        and all(record["final_ppa_eligible"] for record in ppa_records)
        and bool(repair_records)
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
        "functional_repair_success_count": len(repair_records),
        "functional_multiturn_effect_demonstrated": bool(repair_records),
        "all_candidates_resolved": len(records) == _PROCESS_COUNT
        and all(record["resolved"] for record in records),
        "infrastructure_complete": infrastructure_complete,
        "diagnostic_complete": infrastructure_complete and len(records) == _PROCESS_COUNT,
        "fully_successful": fully_successful,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
    }


def _persist_final_evidence(
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


def _finalize_existing(arguments: argparse.Namespace) -> int:
    output = smoke._directory(arguments.output)
    site_work = smoke._directory(arguments.site_work)
    broker_root = smoke._directory(arguments.broker_root)
    progress_path = _campaign_progress_path(site_work)
    progress_mirror = output / "evidence" / "campaign-progress.json"
    _record_progress(
        progress_path,
        phase="finalization",
        status="started",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    inputs = _inputs(arguments)
    profile_paths = _profile_paths(arguments)
    plan = _read_json(smoke._regular_file(output / "plan.json", "diagnostic plan"))
    _validate_existing_plan(plan)
    service = VeriGym(_registries())
    source_configs = _source_configs(inputs)
    _validate_sources(service, source_configs)
    results = _load_existing_results(output)
    if plan["run_config_hashes"] != [result.manifest.run_config_hash for result in results]:
        raise ConfigurationError("run configuration hashes differ from the frozen plan")
    _validate_existing_ledger(output, results)
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        site_paths=(site_work, broker_root, output),
    )
    redaction = _redaction_audit(results)
    summary = _campaign_summary(results, replay, scan, redaction)
    _persist_final_evidence(output, replay, scan, redaction, summary)
    _record_progress(
        progress_path,
        phase="finalization",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        resolved_processes=summary["resolved_count"],
        mirror=progress_mirror,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fully_successful"] else 2


def _validate_existing_plan(plan: Any) -> None:
    expected = {
        "campaign_id": _CAMPAIGN_ID,
        "run_specs": [_run_spec_payload(spec) for spec in _RUN_SPECS],
        **({"comparison_tier": _PROFILE.tier} if _PROFILE.tier != "legacy" else {}),
        "model": _PROFILE.model_id,
        "reasoning_effort": _PROFILE.reasoning_effort,
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "benchmark_suites": ["rtllm", "verilog-eval"],
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
    }
    if not isinstance(plan, dict) or any(plan.get(key) != value for key, value in expected.items()):
        raise ConfigurationError("existing plan differs from the frozen functional diagnostic")
    codex = plan.get("codex")
    expected_codex = {
        "agent_version_id": _PROFILE.agent_version_id,
        "agent_version_hash": _PROFILE.agent_version_hash,
        "prompt_hash": _PROFILE.prompt_hash,
        "tool_policy_fingerprint": _PROFILE.tool_policy_fingerprint,
    }
    hashes = plan.get("run_config_hashes")
    if (
        not isinstance(codex, dict)
        or any(codex.get(key) != value for key, value in expected_codex.items())
        or not isinstance(hashes, list)
        or len(hashes) != _PROCESS_COUNT
        or not all(isinstance(item, str) and smoke._SHA256.fullmatch(item) for item in hashes)
    ):
        raise ConfigurationError("existing plan has invalid frozen identities")


def _load_existing_results(output: Path) -> list[RunResult]:
    runs_root = output / "runs"
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ConfigurationError("existing diagnostic has no real runs directory")
    if sorted(entry.name for entry in runs_root.iterdir()) != sorted(_RUN_IDS):
        raise ConfigurationError("existing diagnostic does not contain exactly fourteen runs")
    results: list[RunResult] = []
    for spec in _RUN_SPECS:
        run_dir = runs_root / spec.run_id
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise ConfigurationError("existing diagnostic run directory is invalid")
        manifest = load_model(run_dir / "run_manifest.json", RunManifest)
        scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
        if (
            manifest.run_id != spec.run_id
            or manifest.task_id != spec.task_id
            or scorecard.run_id != spec.run_id
            or scorecard.task_id != spec.task_id
        ):
            raise ConfigurationError("existing diagnostic run differs from its frozen slot")
        results.append(RunResult(run_dir=run_dir, manifest=manifest, scorecard=scorecard))
    return results


def _validate_existing_ledger(output: Path, results: list[RunResult]) -> None:
    ledger = _read_json(
        smoke._regular_file(
            output / "evidence" / "process-authorizations.json",
            "process authorization ledger",
        )
    )
    records = ledger.get("records")
    if not isinstance(records, list) or len(records) != _PROCESS_COUNT:
        raise ConfigurationError("authorization ledger must contain exactly fourteen records")
    for ordinal, (record, result) in enumerate(zip(records, results, strict=True), start=1):
        expected = {
            "ordinal": ordinal,
            "run_id": result.manifest.run_id,
            "task_id": result.manifest.task_id,
            "authorization_granted": True,
            "process_started": (
                result.run_dir / "artifacts" / "codex_cli" / "process.json"
            ).is_file(),
            "identity_observation_count": len(result.manifest.external_agent_observations),
            "provider_observation_recorded": _identity_observation_valid(result),
            "retry_count": 0,
        }
        if not isinstance(record, dict) or any(
            record.get(key) != value for key, value in expected.items()
        ):
            raise ConfigurationError("authorization ledger differs from run evidence")


if __name__ == "__main__":
    raise SystemExit(main())
