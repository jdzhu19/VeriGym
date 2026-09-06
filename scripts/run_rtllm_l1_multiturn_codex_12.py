#!/usr/bin/env python3
"""Qualify and run a frozen twelve-task RTLLM L1 Codex diagnostic."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke
import run_rtl_functional_multiturn_codex_14 as functional
from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_AGENT_VERSION_HASH,
    AGENTEVAL_AGENT_VERSION_ID,
    AGENTEVAL_PROMPT_HASH,
    AGENTEVAL_TOOL_POLICY_FINGERPRINT,
)
from verigym_rtllm.adapter import ALL_AGENT_EVAL_VARIANT
from verigym_rtllm.manifest import HARDER_TASK_NAMES, TASK_MANIFESTS

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.workspace import copy_tree_safely
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.verifier import VerifierStatus

_CAMPAIGN_ID = "rtllm-full-l1-codex-gpt54-xhigh-12task-pilot-v1"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_OPT_IN = "VERIGYM_RUN_RTLLM_FULL_L1_12"
_PROCESS_COUNT = 12
_SOURCE_KEY = "rtllm_all"
_EXPECTED_RUNTIME_IMAGE_ID = (
    "sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1"
)
_MODEL_ID = "gpt-5.4"
_REASONING_EFFORT = "xhigh"
_AGENT_NAME = "codex-cli-agenteval-agent"
_PROMPT_CONTRACT_ID = "repository_action_v2_prompt_v6"
_TASK_NAMES = (
    "adder_32bit",
    "fixed_point_substractor",
    "div_16bit",
    "multi_booth_8bit",
    "adder_pipe_64bit",
    "JC_counter",
    "sequence_detector",
    "LFSR",
    "synchronizer",
    "RAM",
    "freq_divbyodd",
    "serial2parallel",
)
_PRIOR_CAMPAIGN_TASK_NAMES = frozenset({"counter_12", "up_down_counter", *HARDER_TASK_NAMES})
_PROGRESS_PHASES = frozenset(
    {
        "input_qualification",
        "codex_preflight",
        "docker_preflight",
        "source_qualification",
        "freeze",
        "qualified_plan",
        "execution",
        "finalization",
    }
)
_PROGRESS_STATUSES = frozenset({"started", "running", "completed", "failed"})
_TERMINAL_LEDGER_STATUSES = frozenset(
    {"completed", "verifier_rejection", "contained_model_failure"}
)


@dataclass(frozen=True)
class RunSpec:
    ordinal: int
    run_id: str
    task_name: str
    task_id: str


def _run_specs() -> tuple[RunSpec, ...]:
    if set(_TASK_NAMES).intersection(_PRIOR_CAMPAIGN_TASK_NAMES):
        raise ConfigurationError("RTLLM L1 pilot must not reuse prior campaign tasks")
    return tuple(
        RunSpec(
            ordinal=ordinal,
            run_id=f"{ordinal:02d}-{name.lower().replace('_', '-')}",
            task_name=name,
            task_id=f"rtllm/{ALL_AGENT_EVAL_VARIANT}/{name}",
        )
        for ordinal, name in enumerate(_TASK_NAMES, start=1)
    )


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
        default=Path("/data/jzhu484/Agent/.verigym-tmp/rl1p1b"),
    )
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--image", default=smoke._IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.finalize_existing:
        return _finalize_existing(arguments)

    site_work = smoke._new_path(arguments.site_work, "pilot site-work directory")
    output = smoke._new_path(arguments.output, "pilot output")
    broker_path = smoke._new_path(arguments.broker_root, "Codex broker root")
    source = smoke._directory(arguments.rtllm_source)
    progress_path = _progress_path(site_work)
    _record_progress(progress_path, phase="input_qualification", status="completed")

    _record_progress(progress_path, phase="codex_preflight", status="started")
    capability_path, capability, auth = smoke._codex_preflight(arguments.codex_binary, site_work)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    _record_progress(progress_path, phase="codex_preflight", status="completed")

    _record_progress(progress_path, phase="docker_preflight", status="started")
    image_id = smoke._docker_image_id(arguments.image)
    if image_id != _EXPECTED_RUNTIME_IMAGE_ID:
        raise ConfigurationError("RTLLM L1 pilot image differs from its frozen identity")
    docker_config = smoke._docker_config(arguments.image, image_id)
    _record_progress(progress_path, phase="docker_preflight", status="completed")

    registries = smoke._registries()
    service = VeriGym(registries)
    source_config = SuiteSourceConfig(source_root=source, variant=ALL_AGENT_EVAL_VARIANT)
    _record_progress(progress_path, phase="source_qualification", status="started")
    runtime_descriptor, qualification = _no_model_qualification(
        service,
        source_config=source_config,
        docker_config=docker_config,
        scratch=site_work / "qualification",
    )
    _record_progress(progress_path, phase="source_qualification", status="completed")

    broker_root = smoke._broker_root(broker_path)
    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(broker_root)
    _record_progress(progress_path, phase="freeze", status="started")
    options = _agent_options(capability, auth)
    configs = _frozen_run_configs(
        service,
        source_config=source_config,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        agent_options=options,
        output=output / "runs",
    )
    plan = _build_plan(
        capability=capability,
        auth=auth,
        runtime_descriptor=runtime_descriptor,
        qualification=qualification,
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
    results = _execute_exactly_twelve(
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
    replay, scan, redaction = _audit_outputs(
        results,
        service=service,
        source_config=source_config,
        source=source,
        site_paths=(site_work, broker_root, output),
    )
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
    return 0 if summary["diagnostic_complete"] else 2


def _agent_options(capability: Any, auth: Any) -> dict[str, Any]:
    return {
        "model_id": _MODEL_ID,
        "reasoning_effort": _REASONING_EFFORT,
        "max_process_time_s": 900,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        ),
        "expected_cli_version": smoke._EXPECTED_CLI_VERSION,
        "expected_cli_executable_sha256": smoke._EXPECTED_CODEX_SHA256,
        "expected_capability_fingerprint": capability.capability_fingerprint,
        "expected_prompt_hash": AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": auth.requested_auth_mode,
        "expected_resolved_auth_mode": auth.resolved_auth_mode,
        "expected_auth_semantic_id": auth.auth_semantic_id,
        "prompt_contract_id": _PROMPT_CONTRACT_ID,
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
    }


def _no_model_qualification(
    service: VeriGym,
    *,
    source_config: SuiteSourceConfig,
    docker_config: Any,
    scratch: Path,
) -> tuple[Any, dict[str, Any]]:
    scratch.mkdir()
    suite = service.registries.suites.get("rtllm").with_source(source_config)
    report = suite.validate_source()
    if not report.valid:
        raise ConfigurationError("RTLLM full-corpus source qualification failed")
    refs = {ref.native_id: ref for ref in suite.discover()}
    if not set(_TASK_NAMES).issubset(refs):
        raise ConfigurationError("RTLLM L1 pilot task set is unavailable")

    runtime = service.registries.runtimes.get("docker").configure(docker_config)
    runtime.prepare("rtllm-full-l1-12-preflight")
    records: list[dict[str, Any]] = []
    try:
        image = runtime.descriptor.image
        if image is None or image.iverilog_version is None or "12." not in image.iverilog_version:
            raise ConfigurationError("RTLLM L1 pilot requires the frozen Icarus 12 image")
        for spec in _RUN_SPECS:
            suite_item, task, assets = service.load_task(spec.task_id, source_config)
            if (
                task.metadata.get("gym_qualification_level") != "L1_compile_only"
                or task.metadata.get("diagnostic_only") is not True
                or task.metadata.get("benchmark_score_claimed") is not False
                or task.metadata.get("verification_requires_final_submission") is not True
                or task.metadata.get("agent_eval", {}).get("ppa_supported") is not False
                or task.scoring.ppa_enabled
                or len(assets.read_only_mounts) != 1
            ):
                raise ConfigurationError(f"RTLLM L1 contract drifted for {task.id}")
            manifest = TASK_MANIFESTS[spec.task_name]
            visible = Path(assets.visible_root)
            visible_files = {
                path.relative_to(visible).as_posix()
                for path in visible.rglob("*")
                if path.is_file()
            }
            if any(
                path.startswith("verifier/") or path in manifest.auxiliary_files
                for path in visible_files
            ):
                raise ConfigurationError("RTLLM L1 workspace exposes a verifier-only asset")
            reference = suite_item.reference_solution(task)
            if reference is None:
                raise ConfigurationError("RTLLM L1 reference qualification is unavailable")
            missing = {f"repository/rtl/{spec.task_name}.v": suite_item._candidate_stub(manifest)}
            if not functional._execute_public_candidate(
                runtime,
                task,
                assets,
                reference.files,
                expect_pass=True,
            ) or not functional._execute_public_candidate(
                runtime,
                task,
                assets,
                missing,
                expect_pass=False,
            ):
                raise ConfigurationError(f"RTLLM public compile qualification failed for {task.id}")
            for label, files, expected in (
                ("reference", reference.files, True),
                ("missing-module", missing, False),
            ):
                candidate = _candidate_tree(scratch / spec.task_name / label, assets, files)
                hidden = service._verify_candidate(
                    suite=suite_item,
                    task=task,
                    assets=assets,
                    runtime=runtime,
                    candidate_dir=candidate,
                    artifact_root=scratch / "artifacts" / spec.task_name / label,
                )
                resolved = bool(hidden) and all(
                    result.status == VerifierStatus.PASSED for result in hidden
                )
                if resolved is not expected:
                    raise ConfigurationError(
                        f"RTLLM hidden qualification failed for {task.id}/{label}"
                    )
            records.append(
                {
                    "task_id": task.id,
                    "public_reference_passed": True,
                    "public_missing_module_rejected": True,
                    "hidden_reference_passed": True,
                    "hidden_missing_module_rejected": True,
                    "ppa_supported": False,
                }
            )
        return runtime.descriptor, {
            "passed": True,
            "model_calls": 0,
            "task_count": len(records),
            "records": records,
        }
    finally:
        runtime.close()


def _candidate_tree(root: Path, assets: Any, files: dict[str, str]) -> Path:
    copy_tree_safely(Path(assets.visible_root), root)
    for relative, content in sorted(files.items()):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return root


def _frozen_run_configs(
    service: VeriGym,
    *,
    source_config: SuiteSourceConfig,
    docker_config: Any,
    runtime_descriptor: Any,
    agent_options: dict[str, Any],
    output: Path,
) -> list[RunConfig]:
    configs = [
        smoke._freeze_run_config(
            service,
            RunConfig(
                task_id=spec.task_id,
                mode=InteractionMode.AGENT,
                agent=_AGENT_NAME,
                agent_options=agent_options,
                suite_source=source_config,
                runtime="docker",
                docker_config=docker_config,
                toolchain_profile=None,
                agent_ppa_feedback=False,
                agent_ppa_max_calls=3,
                seed=0,
                sample_index=0,
                output=output,
                run_id=spec.run_id,
            ),
            runtime_descriptor=runtime_descriptor,
            expected_profile=None,
        )
        for spec in _RUN_SPECS
    ]
    if (
        len(configs) != _PROCESS_COUNT
        or len({config.run_id for config in configs}) != _PROCESS_COUNT
        or any(config.toolchain_profile is not None for config in configs)
        or any(config.agent_ppa_feedback for config in configs)
    ):
        raise ConfigurationError("RTLLM L1 pilot must freeze twelve unique no-PPA runs")
    return configs


def _build_plan(
    *,
    capability: Any,
    auth: Any,
    runtime_descriptor: Any,
    qualification: dict[str, Any],
    configs: list[RunConfig],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "launcher_sha256": _launcher_hash(),
        "variant": ALL_AGENT_EVAL_VARIANT,
        "run_specs": [_spec_payload(spec) for spec in _RUN_SPECS],
        "model": _MODEL_ID,
        "reasoning_effort": _REASONING_EFFORT,
        "seed": 0,
        "samples_per_task": 1,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "serial_execution": True,
        "public_feedback_level": "L1_candidate_only_compile",
        "ppa_enabled": False,
        "codex": {
            "version": capability.version_output,
            "executable_sha256": capability.executable_sha256,
            "capability_fingerprint": capability.capability_fingerprint,
            "agent_name": _AGENT_NAME,
            "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
            "auth": auth.safe_dict(),
        },
        "runtime": runtime_descriptor.model_dump(mode="json"),
        "qualification": qualification,
        "run_config_hashes": [content_hash(config.identity_payload()) for config in configs],
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
    }


def _spec_payload(spec: RunSpec) -> dict[str, Any]:
    return {
        "ordinal": spec.ordinal,
        "run_id": spec.run_id,
        "task_name": spec.task_name,
        "task_id": spec.task_id,
        "agent_ppa_feedback": False,
    }


def _launcher_hash() -> str:
    return hash_bytes(Path(__file__).resolve(strict=True).read_bytes())


def _execute_exactly_twelve(
    service: VeriGym,
    configs: list[RunConfig],
    output: Path,
    *,
    progress_path: Path | None = None,
    progress_mirror: Path | None = None,
) -> list[RunResult]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("RTLLM L1 launcher requires exactly twelve frozen runs")
    results: list[RunResult] = []
    ledger: list[dict[str, Any]] = []
    for spec, config in zip(_RUN_SPECS, configs, strict=True):
        record: dict[str, Any] = {
            "ordinal": spec.ordinal,
            "run_id": spec.run_id,
            "task_id": spec.task_id,
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
                completed_processes=spec.ordinal - 1,
                active_process_ordinal=spec.ordinal,
                mirror=progress_mirror,
            )
        try:
            run = service.run(config)
        except Exception:
            run_dir = config.output.expanduser().resolve() / str(config.run_id)
            smoke._update_process_ledger_record(record, run_dir=run_dir)
            record["status"] = "infrastructure_failure"
            _write_ledger(output, ledger)
            raise
        smoke._update_process_ledger_record(record, run_dir=run.run_dir, run=run)
        identity_valid = _identity_observation_valid(run)
        record["identity_observation_count"] = len(run.manifest.external_agent_observations)
        record["provider_observation_recorded"] = identity_valid
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        if not identity_valid:
            record["status"] = "identity_infrastructure_failure"
            _write_ledger(output, ledger)
            raise functional.CampaignInfrastructureError(
                "RTLLM L1 pilot stopped after invalid identity evidence"
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
        if infrastructure or policy:
            raise functional.CampaignInfrastructureError(
                "RTLLM L1 pilot stopped after infrastructure or safety failure"
            )
    if len(results) != _PROCESS_COUNT:
        raise ConfigurationError("RTLLM L1 pilot stopped before every frozen slot completed")
    _validate_authorization_ledger(ledger)
    return results


def _identity_observation_valid(result: RunResult) -> bool:
    observations = result.manifest.external_agent_observations
    identity_path = result.run_dir / "artifacts" / "codex_cli" / "identity.json"
    if len(observations) != 1 or not identity_path.is_file():
        return False
    observation = observations[0]
    return bool(
        observation.invocation_count == 1
        and observation.requested_model_id == _MODEL_ID
        and observation.observed_model_id in {None, _MODEL_ID}
        and observation.effective_reasoning_effort == _REASONING_EFFORT
        and observation.harness_id == AGENTEVAL_AGENT_VERSION_ID
        and observation.agent_version_hash == AGENTEVAL_AGENT_VERSION_HASH
        and observation.prompt_contract_hash == AGENTEVAL_PROMPT_HASH
        and observation.tool_policy_fingerprint == AGENTEVAL_TOOL_POLICY_FINGERPRINT
    )


def _write_ledger(output: Path, records: list[dict[str, Any]]) -> None:
    atomic_dump_json(output / "evidence" / "process-authorizations.json", {"records": records})


def _validate_authorization_ledger(records: list[dict[str, Any]]) -> None:
    if (
        len(records) != _PROCESS_COUNT
        or [record.get("ordinal") for record in records] != list(range(1, _PROCESS_COUNT + 1))
        or [record.get("run_id") for record in records] != list(_RUN_IDS)
        or any(record.get("authorization_granted") is not True for record in records)
        or any(record.get("process_started") is not True for record in records)
        or any(record.get("identity_observation_count") != 1 for record in records)
        or any(record.get("provider_observation_recorded") is not True for record in records)
        or any(record.get("retry_count") != 0 for record in records)
        or any(record.get("status") not in _TERMINAL_LEDGER_STATUSES for record in records)
    ):
        raise ConfigurationError("RTLLM L1 authorization ledger has a non-terminal frozen slot")


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
    if phase not in _PROGRESS_PHASES or status not in _PROGRESS_STATUSES:
        raise ConfigurationError("RTLLM L1 progress state is not allowlisted")
    if not 0 <= completed_processes <= _PROCESS_COUNT:
        raise ConfigurationError("RTLLM L1 completed-process count is invalid")
    if active_process_ordinal is not None and not 1 <= active_process_ordinal <= _PROCESS_COUNT:
        raise ConfigurationError("RTLLM L1 active process ordinal is invalid")
    if resolved_processes is not None and not 0 <= resolved_processes <= completed_processes:
        raise ConfigurationError("RTLLM L1 resolved-process count is invalid")
    payload = {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
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


def _progress_path(site_work: Path) -> Path:
    return site_work.with_name(site_work.name + "-progress.json")


def _audit_outputs(
    results: list[RunResult],
    *,
    service: VeriGym,
    source_config: SuiteSourceConfig,
    source: Path,
    site_paths: tuple[Path, ...],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    original_specs = functional._RUN_SPECS
    original_count = functional._PROCESS_COUNT
    original_ppa_ids = functional._PPA_RUN_IDS
    try:
        functional._RUN_SPECS = tuple(
            functional.RunSpec(spec.run_id, spec.task_id, _SOURCE_KEY) for spec in _RUN_SPECS
        )
        functional._PROCESS_COUNT = _PROCESS_COUNT
        functional._PPA_RUN_IDS = frozenset()
        replay = smoke._offline_replay(results)
        scan = functional._scan_outputs(
            results,
            service,
            {_SOURCE_KEY: source_config},
            {},
            {"rtllm": source},
            site_paths=site_paths,
        )
        redaction = functional._redaction_audit(results)
    finally:
        functional._RUN_SPECS = original_specs
        functional._PROCESS_COUNT = original_count
        functional._PPA_RUN_IDS = original_ppa_ids
    return replay, scan, redaction


def _hidden_execution_valid(
    verifier_results: list[Any], *, typed_finish: bool
) -> tuple[bool, int, int]:
    functional_nodes = [
        result for result in verifier_results if result.node_id == "functional_hidden"
    ]
    executed = [result for result in functional_nodes if result.status != VerifierStatus.SKIPPED]
    valid = (typed_finish and len(executed) == 1 and executed[0].plugin == "iverilog.simulate") or (
        not typed_finish and not executed
    )
    return valid, len(executed), len(functional_nodes) - len(executed)


def _provider_usage_valid(
    *, usage_complete: bool, typed_finish: bool, contained_model_failure: bool
) -> bool:
    return usage_complete or (not typed_finish and contained_model_failure)


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
        contained_model_failure = failure is not None and not infrastructure and not policy
        typed_finish = broker.get("finished") is True and broker.get("finish_calls") == 1
        compile_passed = any(
            evaluation.test_id == "compile"
            and evaluation.passed
            and evaluation.candidate_hash == result.manifest.candidate_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        ppa_evaluations = [
            evaluation
            for evaluation in result.manifest.agent_feedback_evaluations
            if evaluation.test_id == "ppa"
        ]
        hidden_valid, hidden_count, placeholder_count = _hidden_execution_valid(
            result.scorecard.verifier_results,
            typed_finish=typed_finish,
        )
        usage_complete = usage.get("usage_complete") is True
        first_public = broker.get("first_public_validation_passed") is True
        repaired = broker.get("public_validation_failed_then_passed") is True
        failures = broker.get("public_validation_failures", 0)
        sequence = (
            "unverified_finish"
            if not typed_finish
            else "first_pass"
            if first_public
            else "fail_repair_pass"
            if repaired
            else "persistent_failure"
            if isinstance(failures, int) and failures > 0
            else "finish_without_public_pass"
        )
        records.append(
            {
                "ordinal": spec.ordinal,
                "run_id": spec.run_id,
                "task_id": spec.task_id,
                "resolved": result.scorecard.resolved,
                "typed_finish": typed_finish,
                "sequence": sequence,
                "process_started": (root / "process.json").is_file(),
                "timed_out": process.get("timed_out") is True,
                "model_identity_valid": _identity_observation_valid(result),
                "identity_observation_count": len(result.manifest.external_agent_observations),
                "provider_usage_complete": usage_complete,
                "provider_usage_valid": _provider_usage_valid(
                    usage_complete=usage_complete,
                    typed_finish=typed_finish,
                    contained_model_failure=contained_model_failure,
                ),
                "policy_failure": policy,
                "infrastructure_failure": infrastructure,
                "public_validation_passed_for_final_candidate": compile_passed,
                "first_public_validation_passed": first_public,
                "public_validation_failures": failures,
                "repair_patches_after_public_validation_failure": broker.get(
                    "repair_patches_after_public_validation_failure", 0
                ),
                "public_validation_rechecks_after_repair": broker.get(
                    "public_validation_rechecks_after_repair_patch", 0
                ),
                "hidden_verifier_execution_count": hidden_count,
                "hidden_verifier_placeholder_count": placeholder_count,
                "hidden_verifier_execution_valid": hidden_valid,
                "ppa_evaluation_count": len(ppa_evaluations),
                "final_ppa_present": result.scorecard.quality.ppa is not None,
            }
        )
    infrastructure_complete = bool(
        len(records) == _PROCESS_COUNT
        and replay.get("all_valid") is True
        and scan.get("passed") is True
        and redaction.get("passed") is True
        and all(record["process_started"] for record in records)
        and all(record["model_identity_valid"] for record in records)
        and all(record["identity_observation_count"] == 1 for record in records)
        and all(record["hidden_verifier_execution_valid"] for record in records)
        and all(record["provider_usage_valid"] for record in records)
        and all(record["ppa_evaluation_count"] == 0 for record in records)
        and not any(record["final_ppa_present"] for record in records)
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
        "typed_finish_count": sum(record["typed_finish"] for record in records),
        "first_public_pass_count": sum(record["sequence"] == "first_pass" for record in records),
        "fail_repair_pass_count": sum(
            record["sequence"] == "fail_repair_pass" for record in records
        ),
        "infrastructure_complete": infrastructure_complete,
        "diagnostic_complete": infrastructure_complete,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "ppa_enabled": False,
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
    source = smoke._directory(arguments.rtllm_source)
    source_config = SuiteSourceConfig(source_root=source, variant=ALL_AGENT_EVAL_VARIANT)
    plan = _read_json(smoke._regular_file(output / "plan.json", "RTLLM L1 pilot plan"))
    _validate_existing_plan(plan)
    service = VeriGym(smoke._registries())
    suite = service.registries.suites.get("rtllm").with_source(source_config)
    if not suite.validate_source().valid:
        raise ConfigurationError("RTLLM L1 source differs during finalization")
    results = _load_existing_results(output)
    if plan["run_config_hashes"] != [result.manifest.run_config_hash for result in results]:
        raise ConfigurationError("RTLLM L1 run identities differ from the frozen plan")
    _validate_existing_ledger(output, results)
    progress_path = _progress_path(site_work)
    progress_mirror = output / "evidence" / "campaign-progress.json"
    _record_progress(
        progress_path,
        phase="finalization",
        status="started",
        completed_processes=_PROCESS_COUNT,
        mirror=progress_mirror,
    )
    replay, scan, redaction = _audit_outputs(
        results,
        service=service,
        source_config=source_config,
        source=source,
        site_paths=(site_work, broker_root, output),
    )
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
    return 0 if summary["diagnostic_complete"] else 2


def _validate_existing_plan(plan: Any) -> None:
    expected = {
        "campaign_id": _CAMPAIGN_ID,
        "launcher_sha256": _launcher_hash(),
        "variant": ALL_AGENT_EVAL_VARIANT,
        "run_specs": [_spec_payload(spec) for spec in _RUN_SPECS],
        "model": _MODEL_ID,
        "reasoning_effort": _REASONING_EFFORT,
        "seed": 0,
        "samples_per_task": 1,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "serial_execution": True,
        "public_feedback_level": "L1_candidate_only_compile",
        "ppa_enabled": False,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_retries_authorized": False,
    }
    if not isinstance(plan, dict) or any(plan.get(key) != value for key, value in expected.items()):
        raise ConfigurationError("existing RTLLM L1 plan differs from the frozen campaign")
    codex = plan.get("codex")
    hashes = plan.get("run_config_hashes")
    qualification = plan.get("qualification")
    qualification_records = (
        qualification.get("records") if isinstance(qualification, dict) else None
    )
    runtime = plan.get("runtime")
    runtime_image = runtime.get("image") if isinstance(runtime, dict) else None
    expected_codex = {
        "version": smoke._EXPECTED_CLI_VERSION,
        "executable_sha256": smoke._EXPECTED_CODEX_SHA256,
        "agent_name": _AGENT_NAME,
        "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
        "prompt_hash": AGENTEVAL_PROMPT_HASH,
        "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    }
    if (
        not isinstance(codex, dict)
        or any(codex.get(key) != value for key, value in expected_codex.items())
        or not isinstance(hashes, list)
        or len(hashes) != _PROCESS_COUNT
        or len(set(hashes)) != _PROCESS_COUNT
        or not all(isinstance(item, str) and smoke._SHA256.fullmatch(item) for item in hashes)
        or not isinstance(runtime_image, dict)
        or runtime_image.get("resolved_image_id") != _EXPECTED_RUNTIME_IMAGE_ID
        or not isinstance(qualification, dict)
        or qualification.get("passed") is not True
        or qualification.get("model_calls") != 0
        or qualification.get("task_count") != _PROCESS_COUNT
        or not isinstance(qualification_records, list)
        or len(qualification_records) != _PROCESS_COUNT
        or any(not isinstance(record, dict) for record in qualification_records)
        or [record.get("task_id") for record in qualification_records]
        != [spec.task_id for spec in _RUN_SPECS]
        or any(
            record.get("public_reference_passed") is not True
            or record.get("public_missing_module_rejected") is not True
            or record.get("hidden_reference_passed") is not True
            or record.get("hidden_missing_module_rejected") is not True
            or record.get("ppa_supported") is not False
            for record in qualification_records
        )
    ):
        raise ConfigurationError("existing RTLLM L1 plan has invalid frozen identities")


def _load_existing_results(output: Path) -> list[RunResult]:
    runs_root = output / "runs"
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ConfigurationError("RTLLM L1 pilot has no valid runs directory")
    if sorted(entry.name for entry in runs_root.iterdir()) != sorted(_RUN_IDS):
        raise ConfigurationError("RTLLM L1 pilot does not contain every frozen run")
    results: list[RunResult] = []
    for spec in _RUN_SPECS:
        run_dir = runs_root / spec.run_id
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise ConfigurationError("RTLLM L1 run directory is invalid")
        manifest = load_model(run_dir / "run_manifest.json", RunManifest)
        scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
        if (
            manifest.run_id != spec.run_id
            or manifest.task_id != spec.task_id
            or scorecard.run_id != spec.run_id
            or scorecard.task_id != spec.task_id
        ):
            raise ConfigurationError("RTLLM L1 run differs from its frozen slot")
        results.append(RunResult(run_dir=run_dir, manifest=manifest, scorecard=scorecard))
    return results


def _validate_existing_ledger(output: Path, results: list[RunResult]) -> None:
    ledger = _read_json(
        smoke._regular_file(
            output / "evidence" / "process-authorizations.json",
            "RTLLM L1 authorization ledger",
        )
    )
    records = ledger.get("records")
    if not isinstance(records, list):
        raise ConfigurationError("RTLLM L1 authorization ledger is malformed")
    _validate_authorization_ledger(records)
    for record, result in zip(records, results, strict=True):
        expected = {
            "run_id": result.manifest.run_id,
            "task_id": result.manifest.task_id,
            "process_started": (
                result.run_dir / "artifacts" / "codex_cli" / "process.json"
            ).is_file(),
            "identity_observation_count": len(result.manifest.external_agent_observations),
            "provider_observation_recorded": _identity_observation_valid(result),
            "retry_count": 0,
        }
        if any(record.get(key) != value for key, value in expected.items()):
            raise ConfigurationError("RTLLM L1 authorization ledger differs from run evidence")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("RTLLM L1 evidence JSON is unavailable") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("RTLLM L1 evidence JSON must be an object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
