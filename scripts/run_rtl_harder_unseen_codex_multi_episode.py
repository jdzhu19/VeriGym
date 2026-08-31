#!/usr/bin/env python3
"""Run one frozen 12-episode harder-unseen Codex RTL diagnostic cell."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke
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

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.workspace import copy_tree_safely
from verigym.experiments.identity import normalized_runtime_descriptor
from verigym.experiments.state import atomic_dump_json
from verigym.registry.base import PluginOrigin
from verigym.schemas.common import InteractionMode, RuntimeDescriptor
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus

_VARIANT = "v2-spec-to-rtl-agent-eval-functional-v5"
_NATIVE_TASKS = (
    "Prob140_fsm_hdlc",
    "Prob144_conwaylife",
    "Prob153_gshare",
    "Prob155_lemmings4",
)
_PREFLIGHT_EXCLUSIONS = {
    "Prob156_review2015_fancytimer": (
        "official reference emitted the native timeout marker after 200000 samples "
        "with zero mismatches"
    )
}
_EPISODES_PER_TASK = 3
_PROCESS_COUNT = len(_NATIVE_TASKS) * _EPISODES_PER_TASK
_OPT_IN = "VERIGYM_RUN_RTL_HARDER_UNSEEN_MULTI_EPISODE"
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
        "suite_qualification",
        "freeze",
        "qualified_plan",
        "execution",
        "finalization",
    }
)
_PROGRESS_STATUSES = frozenset({"started", "running", "completed", "failed"})


@dataclass(frozen=True)
class Cell:
    key: str
    model_id: str
    reasoning_effort: str
    agent_name: str
    agent_version_id: str
    agent_version_hash: str
    adapter_class: type[Any]
    comparison_groups: tuple[str, ...]

    @property
    def campaign_id(self) -> str:
        return f"rtl-harder-unseen-codex-{self.key}-12episode-diagnostic-v4"


def _cell(
    key: str,
    identity: Any,
    adapter_class: type[Any],
    *groups: str,
) -> Cell:
    return Cell(
        key=key,
        model_id=identity.model_id,
        reasoning_effort=identity.reasoning_effort,
        agent_name=identity.agent_name,
        agent_version_id=identity.agent_version_id,
        agent_version_hash=identity.agent_version_hash,
        adapter_class=adapter_class,
        comparison_groups=groups,
    )


_CELLS = {
    "mini-low": _cell(
        "mini-low",
        FUNCTIONAL_V3_LOW_IDENTITY,
        CodexCliFunctionalV3LowAgentEvalAdapter,
        "overall_strength_low",
        "same_model_reasoning_low",
    ),
    "mini-medium": _cell(
        "mini-medium",
        FUNCTIONAL_V3_MINI_MEDIUM_IDENTITY,
        CodexCliFunctionalV3MiniMediumAgentEvalAdapter,
        "same_model_reasoning_medium",
    ),
    "mini-high": _cell(
        "mini-high",
        FUNCTIONAL_V3_MEDIUM_IDENTITY,
        CodexCliFunctionalV3MediumAgentEvalAdapter,
        "overall_strength_medium",
        "same_model_reasoning_high",
    ),
    "full-xhigh": _cell(
        "full-xhigh",
        FUNCTIONAL_V3_HIGH_IDENTITY,
        CodexCliFunctionalV3HighAgentEvalAdapter,
        "overall_strength_high",
    ),
}


@dataclass(frozen=True)
class RunSpec:
    ordinal: int
    native_id: str
    episode_index: int

    @property
    def task_id(self) -> str:
        return f"verilog-eval/{_VARIANT}/{self.native_id}"

    @property
    def run_id(self) -> str:
        return f"{self.ordinal:02d}-{self.native_id.lower()}-e{self.episode_index}"


def _run_specs() -> tuple[RunSpec, ...]:
    records: list[RunSpec] = []
    ordinal = 1
    for native_id in _NATIVE_TASKS:
        for episode_index in range(_EPISODES_PER_TASK):
            records.append(RunSpec(ordinal, native_id, episode_index))
            ordinal += 1
    return tuple(records)


_RUN_SPECS = _run_specs()
_RUN_IDS = tuple(spec.run_id for spec in _RUN_SPECS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--resume-existing", action="store_true")
    mode.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--cell", choices=tuple(_CELLS), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--verilog-eval-source", type=Path, required=True)
    parser.add_argument("--image", default=smoke._IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    cell = _CELLS[arguments.cell]
    if arguments.output is None:
        arguments.output = Path(f"/data/jzhu484/Agent/experiments/{cell.campaign_id}")
    if arguments.finalize_existing:
        return _finalize_existing(arguments, cell)
    if arguments.resume_existing:
        return _resume_existing(arguments, cell)

    site_work = smoke._new_path(arguments.site_work, "site-profile work directory")
    progress_path = _campaign_progress_path(site_work)
    _record_progress(progress_path, cell, phase="input_qualification", status="started")
    output = smoke._new_path(arguments.output, "diagnostic output")
    broker_root = smoke._new_path(arguments.broker_root, "Codex broker root")
    source_root = smoke._directory(arguments.verilog_eval_source)
    _record_progress(progress_path, cell, phase="input_qualification", status="completed")

    _record_progress(progress_path, cell, phase="codex_preflight", status="started")
    capability_path, capability, auth = smoke._codex_preflight(
        arguments.codex_binary,
        site_work,
    )
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    _record_progress(progress_path, cell, phase="codex_preflight", status="completed")

    _record_progress(progress_path, cell, phase="docker_preflight", status="started")
    image_id = smoke._docker_image_id(arguments.image)
    docker_config = smoke._docker_config(arguments.image, image_id)
    _record_progress(progress_path, cell, phase="docker_preflight", status="completed")

    registries = _registries(cell)
    service = VeriGym(registries)
    source_config = SuiteSourceConfig(source_root=source_root, variant=_VARIANT)
    _record_progress(progress_path, cell, phase="suite_qualification", status="started")
    runtime_descriptor, qualification = _qualify_suite(
        service,
        source_config=source_config,
        docker_config=docker_config,
        scratch=site_work / "qualification",
    )
    _record_progress(progress_path, cell, phase="suite_qualification", status="completed")

    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(smoke._broker_root(broker_root))
    _record_progress(progress_path, cell, phase="freeze", status="started")
    configs = _frozen_run_configs(
        service,
        cell=cell,
        source_config=source_config,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        agent_options=_agent_options(cell, capability, auth),
        output=output / "runs",
    )
    plan = _build_plan(
        cell=cell,
        capability=capability,
        auth=auth,
        runtime_descriptor=runtime_descriptor,
        qualification=qualification,
        configs=configs,
    )
    _record_progress(progress_path, cell, phase="freeze", status="completed")
    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        _record_progress(progress_path, cell, phase="qualified_plan", status="completed")
        print(
            json.dumps(
                {
                    "status": "qualified_plan_only",
                    "cell": cell.key,
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
        cell,
        phase="execution",
        status="started",
        mirror=progress_mirror,
    )
    results = _execute_exactly_twelve(
        service,
        configs,
        output,
        cell=cell,
        progress_path=progress_path,
        progress_mirror=progress_mirror,
    )
    _record_progress(
        progress_path,
        cell,
        phase="execution",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    _record_progress(
        progress_path,
        cell,
        phase="finalization",
        status="started",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    summary = _finalize_results(
        results,
        cell=cell,
        output=output,
        service=service,
        source_config=source_config,
        source_root=source_root,
        site_paths=(site_work, broker_root, output),
    )
    _record_progress(
        progress_path,
        cell,
        phase="finalization",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        resolved_processes=summary["resolved_count"],
        mirror=progress_mirror,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["diagnostic_complete"] else 2


def _registries(cell: Cell) -> Any:
    registries = smoke._registries()
    if cell.agent_name not in registries.agents.names():
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


def _unique_specs() -> tuple[RunSpec, ...]:
    return tuple(spec for spec in _RUN_SPECS if spec.episode_index == 0)


def _qualify_suite(
    service: VeriGym,
    *,
    source_config: SuiteSourceConfig,
    docker_config: Any,
    scratch: Path,
) -> tuple[Any, dict[str, Any]]:
    suite = service.registries.suites.get("verilog-eval").with_source(source_config)
    report = suite.validate_source()
    if not report.valid:
        raise ConfigurationError("harder-unseen VerilogEval source qualification failed")
    scratch.mkdir()
    runtime = service.registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("rtl-harder-unseen-preflight")
    try:
        descriptor = runtime.descriptor
        image = descriptor.image
        if image is None or image.iverilog_version is None or "12." not in image.iverilog_version:
            raise ConfigurationError("qualified Docker runtime does not expose Icarus 12")
        records: list[dict[str, Any]] = []
        for spec in _unique_specs():
            loaded_suite, task, assets = service.load_task(spec.task_id, source_config)
            if task.metadata.get("public_feedback_semantics") != (
                "compile_and_independent_functional_smoke_v5"
            ):
                raise ConfigurationError("harder-unseen public feedback revision drifted")
            visible = Path(assets.visible_root)
            visible_paths = {
                path.relative_to(visible).as_posix()
                for path in visible.rglob("*")
                if path.is_file()
            }
            if any(
                path.startswith("verifier/") or path.startswith("hidden/") for path in visible_paths
            ):
                raise ConfigurationError("harder-unseen projection exposes a protected asset")
            reference = loaded_suite.reference_solution(task)
            top = task.metadata.get("candidate_top")
            editable = task.workspace.editable_globs
            if reference is None or not isinstance(top, str) or len(editable) != 1:
                raise ConfigurationError("harder-unseen qualification inputs are incomplete")
            if not _execute_public_candidate(runtime, task, assets, reference.files):
                raise ConfigurationError(
                    f"harder-unseen reference failed public feedback for {spec.task_id}"
                )
            if not _execute_public_candidate(
                runtime,
                task,
                assets,
                {editable[0]: f"module {top}; endmodule\n"},
                expect_pass=False,
            ):
                raise ConfigurationError(
                    f"harder-unseen known-bad passed public feedback for {spec.task_id}"
                )
            candidate = scratch / spec.run_id
            copy_tree_safely(visible, candidate)
            for relative, content in sorted(reference.files.items()):
                destination = candidate / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            verifier_results = service._verify_candidate(
                suite=loaded_suite,
                task=task,
                assets=assets,
                runtime=runtime,
                candidate_dir=candidate,
                artifact_root=scratch / "artifacts" / spec.run_id,
            )
            if not verifier_results or not all(
                result.status == VerifierStatus.PASSED for result in verifier_results
            ):
                raise ConfigurationError("harder-unseen reference hidden qualification failed")
            records.append(
                {
                    "task_id": spec.task_id,
                    "public_reference_passed": True,
                    "public_known_bad_rejected": True,
                    "hidden_reference_resolved": True,
                    "hidden_assets_not_visible": True,
                    "public_test_contract_hash": task.metadata["agent_eval"][
                        "public_test_contract_hash"
                    ],
                }
            )
        return descriptor, {"passed": True, "model_calls": 0, "records": records}
    finally:
        runtime.close()


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
        if completed.failure_origin == "control_plane" or completed.error is not None:
            raise ConfigurationError("harder-unseen public feedback infrastructure failed")
        return (completed.exit_code == 0) is expect_pass
    finally:
        session.close()


def _agent_options(cell: Cell, capability: Any, auth: Any) -> dict[str, Any]:
    return {
        "model_id": cell.model_id,
        "reasoning_effort": cell.reasoning_effort,
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
        "scoring_agent_version_id": cell.agent_version_id,
        "scoring_agent_version_hash": cell.agent_version_hash,
    }


def _frozen_run_configs(
    service: VeriGym,
    *,
    cell: Cell,
    source_config: SuiteSourceConfig,
    docker_config: Any,
    runtime_descriptor: Any,
    agent_options: dict[str, Any],
    output: Path,
) -> list[RunConfig]:
    configs: list[RunConfig] = []
    for spec in _RUN_SPECS:
        base = RunConfig(
            task_id=spec.task_id,
            mode=InteractionMode.AGENT,
            agent=cell.agent_name,
            agent_options=agent_options,
            suite_source=source_config,
            runtime="docker",
            docker_config=docker_config,
            agent_ppa_feedback=False,
            seed=spec.episode_index,
            sample_index=spec.episode_index,
            output=output,
            run_id=spec.run_id,
        )
        configs.append(
            smoke._freeze_run_config(
                service,
                base,
                runtime_descriptor=runtime_descriptor,
                expected_profile=None,
            )
        )
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("harder-unseen cell must freeze exactly twelve runs")
    return configs


def _build_plan(
    *,
    cell: Cell,
    capability: Any,
    auth: Any,
    runtime_descriptor: Any,
    qualification: dict[str, Any],
    configs: list[RunConfig],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "campaign_id": cell.campaign_id,
        "harness_revision": "functional-v3-recoverable-workspace-request",
        "campaign_orchestration_revision": "contained_model_policy_failure_v1",
        "cell": cell.key,
        "comparison_groups": list(cell.comparison_groups),
        "model": cell.model_id,
        "reasoning_effort": cell.reasoning_effort,
        "variant": _VARIANT,
        "native_tasks": list(_NATIVE_TASKS),
        "preflight_exclusions": dict(_PREFLIGHT_EXCLUSIONS),
        "episodes_per_task": _EPISODES_PER_TASK,
        "planned_codex_processes": _PROCESS_COUNT,
        "run_specs": [
            {
                "ordinal": spec.ordinal,
                "run_id": spec.run_id,
                "task_id": spec.task_id,
                "episode_index": spec.episode_index,
                "child_seed": spec.episode_index,
            }
            for spec in _RUN_SPECS
        ],
        "sampling": {
            "independent_episodes": True,
            "provider_seed_supported": False,
            "provider_seed_forwarded": False,
            "child_seed_is_model_seed": False,
        },
        "automatic_retries": 0,
        "automatic_retries_authorized": False,
        "codex": {
            "version": capability.version_output,
            "executable_sha256": capability.executable_sha256,
            "capability_fingerprint": capability.capability_fingerprint,
            "agent_version_id": cell.agent_version_id,
            "agent_version_hash": cell.agent_version_hash,
            "prompt_hash": FUNCTIONAL_V3_PROMPT_HASH,
            "tool_policy_fingerprint": FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT,
            "auth": auth.safe_dict(),
        },
        "runtime": runtime_descriptor.model_dump(mode="json"),
        "qualification": qualification,
        "run_config_hashes": [content_hash(item.identity_payload()) for item in configs],
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
    }


CampaignInfrastructureError = smoke.CampaignInfrastructureError


def _execute_exactly_twelve(
    service: VeriGym,
    configs: list[RunConfig],
    output: Path,
    *,
    cell: Cell,
    progress_path: Path | None = None,
    progress_mirror: Path | None = None,
    initial_results: list[RunResult] | None = None,
    initial_ledger: list[dict[str, Any]] | None = None,
) -> list[RunResult]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("harder-unseen launcher requires exactly twelve runs")
    ledger = list(initial_ledger or [])
    results = list(initial_results or [])
    if len(results) > _PROCESS_COUNT or len(ledger) not in {len(results), len(results) + 1}:
        raise ConfigurationError("harder-unseen resume prefix is not contiguous")
    for ordinal, config in enumerate(configs, start=1):
        if ordinal <= len(results):
            continue
        if ordinal <= len(ledger):
            record = ledger[ordinal - 1]
            expected_pending = {
                "ordinal": ordinal,
                "run_id": config.run_id,
                "task_id": config.task_id,
                "sample_index": config.sample_index,
                "authorization_granted": True,
                "process_started": False,
                "identity_observation_count": 0,
                "provider_observation_recorded": False,
                "retry_count": 0,
                "status": "authorized",
            }
            if any(record.get(key) != value for key, value in expected_pending.items()):
                raise ConfigurationError("harder-unseen pending authorization is not resumable")
        else:
            record = {
                "ordinal": ordinal,
                "run_id": config.run_id,
                "task_id": config.task_id,
                "sample_index": config.sample_index,
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
                cell,
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
                    cell,
                    phase="execution",
                    status="failed",
                    completed_processes=ordinal - 1,
                    active_process_ordinal=ordinal,
                    mirror=progress_mirror,
                )
            raise
        smoke._update_process_ledger_record(record, run_dir=run.run_dir, run=run)
        record["identity_observation_count"] = len(run.manifest.external_agent_observations)
        record["provider_observation_recorded"] = _identity_observation_valid(run, cell)
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        if not record["provider_observation_recorded"]:
            record["status"] = "identity_infrastructure_failure"
            _write_ledger(output, ledger)
            raise CampaignInfrastructureError(
                "harder-unseen diagnostic stopped after invalid identity evidence"
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
        if ordinal < len(configs) and infrastructure:
            raise CampaignInfrastructureError(
                "harder-unseen diagnostic stopped after infrastructure failure"
            )
    if len(results) != _PROCESS_COUNT:
        raise ConfigurationError("harder-unseen diagnostic stopped before twelve results")
    return results


def _identity_observation_valid(result: RunResult, cell: Cell) -> bool:
    observations = result.manifest.external_agent_observations
    identity_path = result.run_dir / "artifacts" / "codex_cli" / "identity.json"
    if len(observations) != 1 or not identity_path.is_file():
        return False
    observation = observations[0]
    return bool(
        observation.invocation_count == 1
        and observation.requested_model_id == cell.model_id
        and observation.observed_model_id in {None, cell.model_id}
        and observation.effective_reasoning_effort == cell.reasoning_effort
        and observation.harness_id == cell.agent_version_id
        and observation.agent_version_hash == cell.agent_version_hash
        and observation.prompt_contract_hash == FUNCTIONAL_V3_PROMPT_HASH
        and observation.tool_policy_fingerprint == FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT
    )


def _write_ledger(output: Path, records: list[dict[str, Any]]) -> None:
    atomic_dump_json(output / "evidence" / "process-authorizations.json", {"records": records})


def _finalize_results(
    results: list[RunResult],
    *,
    cell: Cell,
    output: Path,
    service: VeriGym,
    source_config: SuiteSourceConfig,
    source_root: Path,
    site_paths: tuple[Path, ...],
) -> dict[str, Any]:
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_config,
        source_root,
        site_paths=site_paths,
    )
    redaction = _redaction_audit(results)
    summary = _campaign_summary(results, cell, replay, scan, redaction)
    atomic_dump_json(output / "replay.json", replay)
    atomic_dump_json(output / "security-scan.json", scan)
    atomic_dump_json(output / "redaction-audit.json", redaction)
    atomic_dump_json(output / "summary.json", summary)
    return summary


def _scan_outputs(
    results: list[RunResult],
    service: VeriGym,
    source_config: SuiteSourceConfig,
    source_root: Path,
    *,
    site_paths: tuple[Path, ...],
) -> dict[str, Any]:
    sensitive: list[tuple[str, bytes]] = []
    for spec in _unique_specs():
        suite, task, assets = service.load_task(spec.task_id, source_config)
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
    path_markers = [str(source_root).encode("utf-8"), *(str(path).encode() for path in site_paths)]
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
            sanitized = payload.replace(b"scoring_event_mcp_server", b"").replace(
                b"mcp_server_category_counts", b"transport_category_counts"
            )
            if model_facing and smoke._COMMERCIAL_DIAGNOSTIC.search(sanitized):
                findings.add((result.manifest.run_id, "commercial_diagnostic"))
    records = [{"run_id": run_id, "category": category} for run_id, category in sorted(findings)]
    return {"schema_version": "1.0", "passed": not records, "findings": records}


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


def _campaign_summary(
    results: list[RunResult],
    cell: Cell,
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
        infrastructure = result.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        policy = failure is not None and failure.kind == "policy"
        compile_passed = any(
            evaluation.test_id == "compile"
            and evaluation.passed
            and evaluation.candidate_hash == result.manifest.candidate_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        verifier_ids = [item.node_id for item in result.scorecard.verifier_results]
        records.append(
            {
                "run_id": result.manifest.run_id,
                "task_id": result.manifest.task_id,
                "native_id": result.manifest.task_id.rsplit("/", 1)[-1],
                "episode_index": result.manifest.sample_index,
                "resolved": result.scorecard.resolved,
                "typed_finish": broker.get("finished") is True and broker.get("finish_calls") == 1,
                "identity_observation_count": len(result.manifest.external_agent_observations),
                "model_identity_valid": _identity_observation_valid(result, cell),
                "provider_usage_complete": usage.get("usage_complete") is True,
                "timed_out": process.get("timed_out") is True,
                "policy_failure": policy,
                "infrastructure_failure": infrastructure,
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
                "hidden_verifier_at_most_once": len(verifier_ids) == len(set(verifier_ids)),
            }
        )
    infrastructure_complete = bool(
        len(records) == _PROCESS_COUNT
        and replay.get("all_valid") is True
        and scan.get("passed") is True
        and redaction.get("passed") is True
        and all(record["model_identity_valid"] for record in records)
        and all(record["identity_observation_count"] == 1 for record in records)
        and all(record["hidden_verifier_at_most_once"] for record in records)
        and not any(record["infrastructure_failure"] for record in records)
    )
    evidence_complete = bool(
        infrastructure_complete
        and all(record["typed_finish"] for record in records)
        and all(record["provider_usage_complete"] for record in records)
        and all(record["public_validation_passed_for_final_candidate"] for record in records)
        and not any(record["timed_out"] for record in records)
    )
    task_records = []
    for native_id in _NATIVE_TASKS:
        selected = [record for record in records if record["native_id"] == native_id]
        resolved = sum(record["resolved"] for record in selected)
        task_records.append(
            {
                "native_id": native_id,
                "episodes": len(selected),
                "resolved_count": resolved,
                "resolved_rate": resolved / len(selected) if selected else None,
                "wilson_95": _wilson_interval(resolved, len(selected)),
                "functional_repair_count": sum(
                    record["functional_failed_then_passed"] for record in selected
                ),
            }
        )
    resolved_count = sum(record["resolved"] for record in records)
    return {
        "schema_version": "1.0",
        "campaign_id": cell.campaign_id,
        "cell": cell.key,
        "comparison_groups": list(cell.comparison_groups),
        "model": cell.model_id,
        "reasoning_effort": cell.reasoning_effort,
        "codex_processes_authorized": _PROCESS_COUNT,
        "codex_processes_started": len(records),
        "provider_observations_recorded": sum(record["model_identity_valid"] for record in records),
        "resolved_count": resolved_count,
        "resolved_rate": resolved_count / _PROCESS_COUNT,
        "wilson_95": _wilson_interval(resolved_count, _PROCESS_COUNT),
        "functional_repair_success_count": sum(
            record["functional_failed_then_passed"] for record in records
        ),
        "model_policy_failure_count": sum(record["policy_failure"] for record in records),
        "task_results": task_records,
        "runs": records,
        "automatic_retries": 0,
        "automatic_retries_authorized": False,
        "infrastructure_complete": infrastructure_complete,
        "evidence_complete": evidence_complete,
        "diagnostic_complete": infrastructure_complete and len(records) == _PROCESS_COUNT,
        "all_candidates_resolved": len(records) == _PROCESS_COUNT
        and all(record["resolved"] for record in records),
        "fully_successful": evidence_complete
        and len(records) == _PROCESS_COUNT
        and all(record["resolved"] for record in records),
        "provider_seed_supported": False,
        "provider_seed_forwarded": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
    }


def _wilson_interval(successes: int, total: int) -> dict[str, float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return {
        "lower": round(max(0.0, center - margin), 6),
        "upper": round(min(1.0, center + margin), 6),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("harder-unseen evidence JSON is unavailable") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("harder-unseen evidence JSON must be an object")
    return value


def _resume_existing(arguments: argparse.Namespace, cell: Cell) -> int:
    """Continue only a proven contiguous prefix without repeating an agent process."""

    if os.environ.get(_OPT_IN) != "1":
        raise ConfigurationError(f"execution requires {_OPT_IN}=1")
    output = smoke._directory(arguments.output)
    original_site_work = smoke._directory(arguments.site_work)
    broker_root = smoke._directory(arguments.broker_root)
    source_root = smoke._directory(arguments.verilog_eval_source)
    plan = _read_json(smoke._regular_file(output / "plan.json", "diagnostic plan"))
    _validate_existing_plan(plan, cell)

    resume_parent = Path(
        tempfile.mkdtemp(prefix="rtl-harder-unseen-resume-", dir=original_site_work.parent)
    ).resolve()
    resume_site_work = resume_parent / "site-work"
    progress_path = _campaign_progress_path(original_site_work)
    progress_mirror = output / "evidence" / "campaign-progress.json"

    capability_path, capability, auth = smoke._codex_preflight(
        arguments.codex_binary,
        resume_site_work,
    )
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    image_id = smoke._docker_image_id(arguments.image)
    docker_config = smoke._docker_config(arguments.image, image_id)
    service = VeriGym(_registries(cell))
    source_config = SuiteSourceConfig(source_root=source_root, variant=_VARIANT)
    runtime_descriptor, qualification = _qualify_suite(
        service,
        source_config=source_config,
        docker_config=docker_config,
        scratch=resume_site_work / "qualification",
    )
    frozen_runtime = RuntimeDescriptor.model_validate(plan.get("runtime"))
    if normalized_runtime_descriptor(runtime_descriptor) != normalized_runtime_descriptor(
        frozen_runtime
    ) or qualification != plan.get("qualification"):
        raise ConfigurationError("resume preflight differs from the frozen campaign plan")

    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(smoke._broker_root(broker_root))
    configs = _frozen_run_configs(
        service,
        cell=cell,
        source_config=source_config,
        docker_config=docker_config,
        runtime_descriptor=frozen_runtime,
        agent_options=_agent_options(cell, capability, auth),
        output=output / "runs",
    )
    hashes = [content_hash(item.identity_payload()) for item in configs]
    if hashes != plan.get("run_config_hashes"):
        raise ConfigurationError("resume run configurations differ from the frozen plan")

    results, ledger, pending = _load_resume_prefix(output, cell)
    if len(results) == _PROCESS_COUNT:
        raise ConfigurationError(
            "completed diagnostic requires independent finalization, not resume"
        )
    if pending is not None:
        _archive_unstarted_run(output, pending, completed_processes=len(results))
    _record_progress(
        progress_path,
        cell,
        phase="execution",
        status="running",
        completed_processes=len(results),
        active_process_ordinal=len(results) + 1,
        mirror=progress_mirror,
    )
    results = _execute_exactly_twelve(
        service,
        configs,
        output,
        cell=cell,
        progress_path=progress_path,
        progress_mirror=progress_mirror,
        initial_results=results,
        initial_ledger=ledger,
    )
    _record_progress(
        progress_path,
        cell,
        phase="execution",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    _record_progress(
        progress_path,
        cell,
        phase="finalization",
        status="started",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    summary = _finalize_results(
        results,
        cell=cell,
        output=output,
        service=service,
        source_config=source_config,
        source_root=source_root,
        site_paths=(original_site_work, resume_site_work, broker_root, output),
    )
    _record_progress(
        progress_path,
        cell,
        phase="finalization",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        resolved_processes=summary["resolved_count"],
        mirror=progress_mirror,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["diagnostic_complete"] else 2


def _load_resume_prefix(
    output: Path,
    cell: Cell,
) -> tuple[list[RunResult], list[dict[str, Any]], RunSpec | None]:
    ledger_payload = _read_json(
        smoke._regular_file(
            output / "evidence" / "process-authorizations.json",
            "process authorization ledger",
        )
    )
    records = ledger_payload.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= _PROCESS_COUNT:
        raise ConfigurationError("resume ledger must contain a non-empty bounded prefix")

    results: list[RunResult] = []
    pending: RunSpec | None = None
    for index, record in enumerate(records):
        spec = _RUN_SPECS[index]
        base = {
            "ordinal": spec.ordinal,
            "run_id": spec.run_id,
            "task_id": spec.task_id,
            "sample_index": spec.episode_index,
            "authorization_granted": True,
            "retry_count": 0,
        }
        if not isinstance(record, dict) or any(
            record.get(key) != value for key, value in base.items()
        ):
            raise ConfigurationError("resume ledger is not a frozen contiguous prefix")
        if record.get("status") == "authorized":
            expected_pending = {
                "process_started": False,
                "identity_observation_count": 0,
                "provider_observation_recorded": False,
                "resolved": None,
            }
            if index != len(records) - 1 or any(
                record.get(key) != value
                for key, value in expected_pending.items()
                if key in record or key != "resolved"
            ):
                raise ConfigurationError("only the next unstarted authorization may be resumed")
            pending = spec
            continue

        result = _load_run_result(output, spec)
        expected_completed = {
            "process_started": True,
            "identity_observation_count": 1,
            "provider_observation_recorded": True,
            "resolved": result.scorecard.resolved,
            "status": _expected_ledger_status(result),
        }
        if any(record.get(key) != value for key, value in expected_completed.items()):
            raise ConfigurationError("resume ledger differs from completed run evidence")
        if not _identity_observation_valid(result, cell):
            raise ConfigurationError("resume prefix contains invalid model identity evidence")
        if expected_completed["status"] == "infrastructure_failure":
            raise ConfigurationError("infrastructure-invalid campaigns cannot be resumed")
        results.append(result)

    if len(results) + (pending is not None) != len(records):
        raise ConfigurationError("resume ledger contains a gap after an authorization")
    expected_entries = {spec.run_id for spec in _RUN_SPECS[: len(records)]}
    runs_root = output / "runs"
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ConfigurationError("resume campaign has no real runs directory")
    actual_entries = {entry.name for entry in runs_root.iterdir()}
    if actual_entries != expected_entries:
        raise ConfigurationError("resume runs are not the exact ledger prefix")
    return results, records, pending


def _load_run_result(output: Path, spec: RunSpec) -> RunResult:
    run_dir = output / "runs" / spec.run_id
    manifest = load_model(run_dir / "run_manifest.json", RunManifest)
    scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
    if (
        run_dir.is_symlink()
        or manifest.run_id != spec.run_id
        or manifest.task_id != spec.task_id
        or manifest.sample_index != spec.episode_index
        or scorecard.run_id != spec.run_id
        or scorecard.task_id != spec.task_id
    ):
        raise ConfigurationError("resume run differs from its frozen slot")
    return RunResult(run_dir=run_dir, manifest=manifest, scorecard=scorecard)


def _expected_ledger_status(result: RunResult) -> str:
    failure = result.scorecard.failure
    infrastructure = result.scorecard.correctness.infrastructure_error or (
        failure is not None and failure.infrastructure
    )
    if infrastructure:
        return "infrastructure_failure"
    if failure is not None and failure.kind == "policy":
        return "policy_failure"
    if failure is not None:
        return "contained_model_failure"
    if not result.scorecard.resolved:
        return "verifier_rejection"
    return "completed"


def _archive_unstarted_run(output: Path, spec: RunSpec, *, completed_processes: int) -> None:
    run_dir = output / "runs" / spec.run_id
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ConfigurationError("authorized resume slot has no inspectable staging directory")
    if any(path.is_symlink() for path in run_dir.rglob("*")):
        raise ConfigurationError("authorized resume staging directory contains a symlink")
    manifest = load_model(run_dir / "run_manifest.json", RunManifest)
    codex_root = run_dir / "artifacts" / "codex_cli"
    agent_log = run_dir / "logs" / "agent.log"
    verifier_log = run_dir / "logs" / "verifier.log"
    trace_path = run_dir / "trace.jsonl"
    try:
        trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("authorized resume staging trace is unavailable") from exc
    event_types = [item.get("event_type") for item in trace if isinstance(item, dict)]
    proven_unstarted = bool(
        manifest.run_id == spec.run_id
        and manifest.task_id == spec.task_id
        and manifest.sample_index == spec.episode_index
        and not manifest.external_agent_observations
        and manifest.candidate_hash is None
        and not manifest.agent_feedback_evaluations
        and codex_root.is_dir()
        and not any(codex_root.iterdir())
        and agent_log.is_file()
        and agent_log.stat().st_size == 0
        and verifier_log.is_file()
        and verifier_log.stat().st_size == 0
        and not (run_dir / "scorecard.json").exists()
        and event_types == ["episode_started", "observation_emitted"]
    )
    if not proven_unstarted:
        raise ConfigurationError(
            "interrupted slot may have started an agent process; resume refused"
        )

    archive_root = output / "evidence" / "interrupted-before-agent-process"
    archive_root.mkdir()
    archived = archive_root / spec.run_id
    if archived.exists() or archived.is_symlink():
        raise ConfigurationError("interrupted staging archive already exists")
    run_dir.rename(archived)
    atomic_dump_json(
        output / "evidence" / "resume-audit.json",
        {
            "schema_version": "1.0",
            "classification": "external_interruption_before_agent_process",
            "run_id": spec.run_id,
            "ordinal": spec.ordinal,
            "completed_processes_preserved": completed_processes,
            "agent_process_started": False,
            "model_retry_performed": False,
            "staging_artifacts_archived": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
        },
    )


def _finalize_existing(arguments: argparse.Namespace, cell: Cell) -> int:
    output = smoke._directory(arguments.output)
    site_work = smoke._directory(arguments.site_work)
    broker_root = smoke._directory(arguments.broker_root)
    source_root = smoke._directory(arguments.verilog_eval_source)
    progress_path = _campaign_progress_path(site_work)
    progress_mirror = output / "evidence" / "campaign-progress.json"
    _record_progress(
        progress_path,
        cell,
        phase="finalization",
        status="started",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    plan = _read_json(smoke._regular_file(output / "plan.json", "diagnostic plan"))
    _validate_existing_plan(plan, cell)
    service = VeriGym(_registries(cell))
    source_config = SuiteSourceConfig(source_root=source_root, variant=_VARIANT)
    results = _load_existing_results(output)
    if plan["run_config_hashes"] != [result.manifest.run_config_hash for result in results]:
        raise ConfigurationError("run configuration hashes differ from the frozen plan")
    _validate_existing_ledger(output, results, cell)
    summary = _finalize_results(
        results,
        cell=cell,
        output=output,
        service=service,
        source_config=source_config,
        source_root=source_root,
        site_paths=(site_work, broker_root, output),
    )
    _record_progress(
        progress_path,
        cell,
        phase="finalization",
        status="completed",
        completed_processes=_PROCESS_COUNT,
        resolved_processes=summary["resolved_count"],
        mirror=progress_mirror,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["diagnostic_complete"] else 2


def _validate_existing_plan(plan: Any, cell: Cell) -> None:
    expected = {
        "campaign_id": cell.campaign_id,
        "harness_revision": "functional-v3-recoverable-workspace-request",
        "campaign_orchestration_revision": "contained_model_policy_failure_v1",
        "cell": cell.key,
        "comparison_groups": list(cell.comparison_groups),
        "model": cell.model_id,
        "reasoning_effort": cell.reasoning_effort,
        "variant": _VARIANT,
        "native_tasks": list(_NATIVE_TASKS),
        "episodes_per_task": _EPISODES_PER_TASK,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "automatic_retries_authorized": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
    }
    if not isinstance(plan, dict) or any(plan.get(key) != value for key, value in expected.items()):
        raise ConfigurationError("existing plan differs from the harder-unseen diagnostic")
    codex = plan.get("codex")
    hashes = plan.get("run_config_hashes")
    run_specs = plan.get("run_specs")
    if (
        not isinstance(codex, dict)
        or codex.get("agent_version_id") != cell.agent_version_id
        or codex.get("agent_version_hash") != cell.agent_version_hash
        or codex.get("prompt_hash") != FUNCTIONAL_V3_PROMPT_HASH
        or codex.get("tool_policy_fingerprint") != FUNCTIONAL_V3_TOOL_POLICY_FINGERPRINT
        or not isinstance(hashes, list)
        or len(hashes) != _PROCESS_COUNT
        or not all(isinstance(item, str) and smoke._SHA256.fullmatch(item) for item in hashes)
        or not isinstance(run_specs, list)
        or [item.get("run_id") for item in run_specs if isinstance(item, dict)] != list(_RUN_IDS)
    ):
        raise ConfigurationError("existing harder-unseen plan has invalid frozen identities")


def _load_existing_results(output: Path) -> list[RunResult]:
    runs_root = output / "runs"
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ConfigurationError("existing harder-unseen diagnostic has no real runs directory")
    if sorted(entry.name for entry in runs_root.iterdir()) != sorted(_RUN_IDS):
        raise ConfigurationError("existing harder-unseen diagnostic does not contain twelve runs")
    results: list[RunResult] = []
    for spec in _RUN_SPECS:
        results.append(_load_run_result(output, spec))
    return results


def _validate_existing_ledger(output: Path, results: list[RunResult], cell: Cell) -> None:
    ledger = _read_json(
        smoke._regular_file(
            output / "evidence" / "process-authorizations.json",
            "process authorization ledger",
        )
    )
    records = ledger.get("records")
    if not isinstance(records, list) or len(records) != _PROCESS_COUNT:
        raise ConfigurationError("authorization ledger must contain exactly twelve records")
    for ordinal, (record, result) in enumerate(zip(records, results, strict=True), start=1):
        expected = {
            "ordinal": ordinal,
            "run_id": result.manifest.run_id,
            "task_id": result.manifest.task_id,
            "sample_index": result.manifest.sample_index,
            "authorization_granted": True,
            "process_started": (
                result.run_dir / "artifacts" / "codex_cli" / "process.json"
            ).is_file(),
            "identity_observation_count": len(result.manifest.external_agent_observations),
            "provider_observation_recorded": _identity_observation_valid(result, cell),
            "retry_count": 0,
        }
        if not isinstance(record, dict) or any(
            record.get(key) != value for key, value in expected.items()
        ):
            raise ConfigurationError("authorization ledger differs from harder-unseen evidence")


def _record_progress(
    path: Path,
    cell: Cell,
    *,
    phase: str,
    status: str,
    completed_processes: int = 0,
    active_process_ordinal: int | None = None,
    resolved_processes: int | None = None,
    mirror: Path | None = None,
) -> None:
    if phase not in _PROGRESS_PHASES or status not in _PROGRESS_STATUSES:
        raise ConfigurationError("harder-unseen progress phase or status is not allowlisted")
    if not 0 <= completed_processes <= _PROCESS_COUNT:
        raise ConfigurationError("harder-unseen completed count is out of range")
    if active_process_ordinal is not None and not 1 <= active_process_ordinal <= _PROCESS_COUNT:
        raise ConfigurationError("harder-unseen active ordinal is out of range")
    if resolved_processes is not None and not 0 <= resolved_processes <= completed_processes:
        raise ConfigurationError("harder-unseen resolved count is out of range")
    payload = {
        "schema_version": "1.0",
        "campaign_id": cell.campaign_id,
        "cell": cell.key,
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
    return site_work.parent / f".{site_work.name}.campaign-progress.json"


if __name__ == "__main__":
    raise SystemExit(main())
