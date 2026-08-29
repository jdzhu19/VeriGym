#!/usr/bin/env python3
"""Qualify and execute the frozen fourteen-process RTL AgentEval Codex pilot."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.experiments.state import atomic_dump_json
from verigym.profiles.identity import resolved_profile_component_hashes
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig

_CAMPAIGN_ID = "rtl-agenteval-codex-gpt54-xhigh-pilot-v1"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_PREDECESSOR_SUMMARY = Path(
    "/data/jzhu484/Agent/experiments/rtl-agenteval-codex-gpt54-xhigh-smoke-v7/summary.json"
)
_PROCESS_COUNT = 14
AGENTEVAL_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v4"
AGENTEVAL_AGENT_VERSION_HASH = "3013e36846e016c6b57b9d28c811317718902e89b40fd522e4f49de3c93dd040"
AGENTEVAL_PROMPT_HASH = "607e0c73bd6fdead39fb63916cfb24eb5929c17a9e801309d1d8c100da1a6141"
AGENTEVAL_TOOL_POLICY_FINGERPRINT = (
    "115a39244d7f64c63fe8b5b2628cb829aafc1429e6d1d5acb22abdbe0ce7c052"
)


@dataclass(frozen=True)
class PilotRunSpec:
    run_id: str
    task_id: str
    source_key: str
    profile_name: str | None = None
    ppa: bool = False


_RUN_SPECS = (
    PilotRunSpec(
        "01-counter-open",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_open",
        True,
    ),
    PilotRunSpec(
        "02-counter-dc",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_dc",
        True,
    ),
    PilotRunSpec(
        "03-up-down-open",
        "rtllm/up_down_counter_agent_eval_v1",
        "up_down",
        "up_down_open",
        True,
    ),
    PilotRunSpec(
        "04-up-down-dc",
        "rtllm/up_down_counter_agent_eval_v1",
        "up_down",
        "up_down_dc",
        True,
    ),
    PilotRunSpec(
        "05-verilog-eval-prob014-andgate",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob014_andgate",
        "verilog_eval",
    ),
    PilotRunSpec(
        "06-verilog-eval-prob024-hadd",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob024_hadd",
        "verilog_eval",
    ),
    PilotRunSpec(
        "07-verilog-eval-prob035-count1to10",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob035_count1to10",
        "verilog_eval",
    ),
    PilotRunSpec(
        "08-verilog-eval-prob085-shift4",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob085_shift4",
        "verilog_eval",
    ),
    PilotRunSpec(
        "09-verilog-eval-prob107-fsm1s",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob107_fsm1s",
        "verilog_eval",
    ),
    PilotRunSpec(
        "10-rtl-repo-test-000001",
        "rtl-repo/official-parquet-v1-agent-eval-v1/test-000001",
        "rtl_repo",
    ),
    PilotRunSpec(
        "11-rtl-repo-test-000002",
        "rtl-repo/official-parquet-v1-agent-eval-v1/test-000002",
        "rtl_repo",
    ),
    PilotRunSpec(
        "12-rtl-repo-test-000003",
        "rtl-repo/official-parquet-v1-agent-eval-v1/test-000003",
        "rtl_repo",
    ),
    PilotRunSpec(
        "13-rtl-repo-test-000004",
        "rtl-repo/official-parquet-v1-agent-eval-v1/test-000004",
        "rtl_repo",
    ),
    PilotRunSpec(
        "14-rtl-repo-test-000005",
        "rtl-repo/official-parquet-v1-agent-eval-v1/test-000005",
        "rtl_repo",
    ),
)
_RUN_IDS = tuple(spec.run_id for spec in _RUN_SPECS)
_TASKS = tuple(spec.task_id for spec in _RUN_SPECS)
_PPA_RUN_IDS = frozenset(spec.run_id for spec in _RUN_SPECS if spec.ppa)

CampaignInfrastructureError = smoke.CampaignInfrastructureError
PreparedProfile = smoke.PreparedProfile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    parser.add_argument("--predecessor-summary", type=Path, default=_PREDECESSOR_SUMMARY)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument(
        "--broker-root",
        type=Path,
        default=Path("/data/jzhu484/Agent/.verigym-tmp/cb-aep1"),
    )
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--verilog-eval-source", type=Path, required=True)
    parser.add_argument("--rtl-repo-source", type=Path, required=True)
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
    if arguments.finalize_existing:
        return _finalize_existing(arguments)
    if arguments.execute:
        raise ConfigurationError(
            "completed pilot-v1 is read-only; use the separately versioned diagnostic launcher"
        )

    site_work = smoke._new_path(arguments.site_work, "site-profile work directory")
    inputs = _inputs(arguments)
    profile_paths = _profile_paths(arguments)
    predecessor_path = smoke._regular_file(arguments.predecessor_summary, "smoke-v7 summary")
    predecessor = _validate_predecessor(predecessor_path)
    capability_path, capability, auth = smoke._codex_preflight(arguments.codex_binary, site_work)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    image_id = smoke._docker_image_id(arguments.image)
    docker_config = smoke._docker_config(arguments.image, image_id)

    registries = smoke._registries()
    service = VeriGym(registries)
    source_configs = smoke._source_configs(inputs)
    _validate_sources(service, source_configs)
    broker_regression = smoke._repository_broker_regression_qualification(service, source_configs)
    prepared = smoke._prepare_profiles(
        registries,
        site_work=site_work,
        image=arguments.image,
        image_id=image_id,
        pdk_root=inputs["pdk"],
        dc_paths=profile_paths,
    )
    runtime_descriptor, qualifications = smoke._no_model_qualification(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        prepared=prepared,
        vcs_paths=profile_paths,
        scratch=site_work / "qualification",
    )
    qualifications["repository_broker_regression"] = broker_regression
    qualifications["predecessor_smoke"] = predecessor

    output = smoke._new_path(arguments.output, "experiment output")
    broker_root = smoke._new_path(arguments.broker_root, "Codex broker root")
    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(smoke._broker_root(broker_root))
    run_configs = _frozen_run_configs(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        agent_options=smoke._agent_options(capability, auth),
        output=output / "runs",
    )
    plan = _build_plan(
        capability=capability,
        auth=auth,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        qualifications=qualifications,
        configs=run_configs,
        predecessor_path=predecessor_path,
    )

    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        print(
            json.dumps(
                {
                    "status": "qualified_plan_only",
                    "model_calls": 0,
                    "planned_codex_processes": _PROCESS_COUNT,
                },
                sort_keys=True,
            )
        )
        return 0
    if os.environ.get("VERIGYM_RUN_RTL_AGENT_EVAL_PILOT") != "1":
        raise ConfigurationError("execution requires VERIGYM_RUN_RTL_AGENT_EVAL_PILOT=1")

    output.mkdir(parents=True)
    (output / "runs").mkdir()
    (output / "evidence").mkdir()
    atomic_dump_json(output / "plan.json", plan)
    results = _execute_exactly_fourteen(service, run_configs, output)
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        site_paths=(site_work, broker_root, output, predecessor_path),
    )
    summary = _campaign_summary(results, replay, scan)
    _persist_final_evidence(output, replay, scan, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fully_successful"] else 2


def _inputs(arguments: argparse.Namespace) -> dict[str, Path]:
    return {
        "rtllm": smoke._directory(arguments.rtllm_source),
        "verilog_eval": smoke._directory(arguments.verilog_eval_source),
        "rtl_repo": smoke._directory(arguments.rtl_repo_source),
        "pdk": smoke._directory(arguments.pdk_root),
    }


def _profile_paths(arguments: argparse.Namespace) -> dict[str, Path]:
    return {
        "dc_counter": smoke._regular_file(arguments.dc_counter_profile),
        "dc_up_down": smoke._regular_file(arguments.dc_up_down_profile),
        "vcs_counter": smoke._regular_file(arguments.vcs_counter_profile),
        "vcs_up_down": smoke._regular_file(arguments.vcs_up_down_profile),
    }


def _validate_predecessor(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    try:
        summary = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("smoke-v7 summary is not valid JSON") from exc
    expected = {
        "campaign_id": smoke._CAMPAIGN_ID,
        "fully_successful": True,
        "pilot_authorized": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 4,
        "provider_observations_recorded": 4,
        "automatic_retries": 0,
    }
    if not isinstance(summary, dict) or any(
        summary.get(key) != value for key, value in expected.items()
    ):
        raise ConfigurationError("pilot requires the fully successful frozen smoke-v7 summary")
    runs = summary.get("runs")
    if (
        not isinstance(runs, list)
        or len(runs) != 4
        or not all(
            isinstance(run, dict)
            and run.get("model_identity_valid") is True
            and run.get("process_started") is True
            and run.get("provider_observation_recorded") is True
            and run.get("typed_finish") is True
            and run.get("resolved") is True
            and run.get("policy_failure") is False
            and run.get("infrastructure_failure") is False
            for run in runs
        )
    ):
        raise ConfigurationError("smoke-v7 summary lacks complete per-run acceptance evidence")
    return {
        "campaign_id": smoke._CAMPAIGN_ID,
        "summary_hash": hash_bytes(payload),
        "fully_successful": True,
        "pilot_authorized": True,
    }


def _validate_sources(
    service: VeriGym,
    source_configs: dict[str, SuiteSourceConfig],
) -> None:
    for spec in _RUN_SPECS:
        config = source_configs[spec.source_key]
        suite, task, assets = service.load_task(spec.task_id, config)
        report = suite.validate_source()
        if not report.valid or not Path(assets.visible_root).is_dir() or task.id != spec.task_id:
            raise ConfigurationError(f"source qualification failed for {spec.task_id}")


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
            agent="codex-cli-agenteval-agent",
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
    return configs


def _build_plan(
    *,
    capability: Any,
    auth: Any,
    runtime_descriptor: Any,
    prepared: dict[str, PreparedProfile],
    qualifications: dict[str, Any],
    configs: list[RunConfig],
    predecessor_path: Path,
) -> dict[str, Any]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("pilot plan must contain exactly fourteen frozen runs")
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "run_specs": [
            {
                "run_id": spec.run_id,
                "task_id": spec.task_id,
                "source_key": spec.source_key,
                "profile_name": spec.profile_name,
                "agent_ppa_feedback": spec.ppa,
            }
            for spec in _RUN_SPECS
        ],
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "codex": {
            "version": capability.version_output,
            "executable_sha256": capability.executable_sha256,
            "capability_fingerprint": capability.capability_fingerprint,
            "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
            "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
            "prompt_hash": AGENTEVAL_PROMPT_HASH,
            "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
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
        },
        "qualifications": qualifications,
        "run_config_hashes": [content_hash(item.identity_payload()) for item in configs],
        "predecessor_summary_hash": hash_bytes(predecessor_path.read_bytes()),
        "pilot_is_benchmark_score": False,
        "benchmark_score_claimed": False,
    }


def _execute_exactly_fourteen(
    service: VeriGym,
    configs: list[RunConfig],
    output: Path,
) -> list[RunResult]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("pilot launcher must contain exactly fourteen frozen runs")
    ledger: list[dict[str, Any]] = []
    results: list[RunResult] = []
    for ordinal, config in enumerate(configs, start=1):
        record = {
            "ordinal": ordinal,
            "run_id": config.run_id,
            "task_id": config.task_id,
            "authorization_granted": True,
            "process_started": False,
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
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        failure = run.scorecard.failure
        infrastructure = run.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        if infrastructure:
            record["status"] = "infrastructure_failure"
        elif failure is not None and failure.kind == "policy":
            record["status"] = "policy_failure"
        elif failure is not None:
            record["status"] = "contained_model_failure"
        elif not run.scorecard.resolved:
            record["status"] = "verifier_rejection"
        else:
            record["status"] = "completed"
        _write_ledger(output, ledger)
        if infrastructure and ordinal < len(configs):
            raise CampaignInfrastructureError(
                "pilot campaign stopped after an infrastructure-invalid run"
            )
    if len(results) != _PROCESS_COUNT:
        raise ConfigurationError("fourteen-process pilot stopped before all runs completed")
    return results


def _write_ledger(output: Path, records: list[dict[str, Any]]) -> None:
    atomic_dump_json(output / "evidence" / "process-authorizations.json", {"records": records})


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
    seen_tasks: set[str] = set()
    for spec in _RUN_SPECS:
        if spec.task_id in seen_tasks:
            continue
        seen_tasks.add(spec.task_id)
        suite, task, assets = service.load_task(spec.task_id, configs[spec.source_key])
        sensitive.extend(
            ("hidden_rtl", asset.content.encode())
            for asset in assets.hidden_assets
            if asset.content
        )
        reference = suite.reference_solution(task)
        if reference is not None:
            sensitive.extend(
                ("reference_rtl", value.encode()) for value in reference.files.values()
            )
    path_markers = [
        *(str(path).encode() for path in profile_paths.values()),
        *(str(path).encode() for path in inputs.values()),
        *(str(path).encode() for path in site_paths),
    ]
    findings: list[dict[str, str]] = []
    for result in results:
        for file in sorted(result.run_dir.rglob("*")):
            if file.is_symlink():
                findings.append({"run_id": result.manifest.run_id, "category": "symlink"})
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
                        findings.append({"run_id": result.manifest.run_id, "category": category})
            for marker in path_markers:
                if model_facing and marker and marker in payload:
                    findings.append({"run_id": result.manifest.run_id, "category": "site_path"})
            if model_facing and smoke._COMMERCIAL_DIAGNOSTIC.search(payload):
                findings.append(
                    {
                        "run_id": result.manifest.run_id,
                        "category": "commercial_diagnostic",
                    }
                )
    unique = [dict(item) for item in {tuple(sorted(item.items())) for item in findings}]
    return {"schema_version": "1.0", "passed": not unique, "findings": unique}


def _campaign_summary(
    results: list[RunResult],
    replay: dict[str, Any],
    scan: dict[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    infrastructure_complete = (
        len(results) == _PROCESS_COUNT and replay["all_valid"] and scan["passed"]
    )
    process_started_count = 0
    provider_observation_count = 0
    policy_failure_count = 0
    for result in results:
        observations = result.manifest.external_agent_observations
        evidence_root = result.run_dir / "artifacts" / "codex_cli"
        broker_path = evidence_root / "broker.json"
        broker = (
            json.loads(broker_path.read_text(encoding="utf-8")) if broker_path.is_file() else {}
        )
        identity_ok = (
            len(observations) == 1
            and observations[0].invocation_count == 1
            and observations[0].requested_model_id == "gpt-5.4"
            and observations[0].observed_model_id in {None, "gpt-5.4"}
            and observations[0].effective_reasoning_effort == "xhigh"
            and observations[0].harness_id == AGENTEVAL_AGENT_VERSION_ID
            and observations[0].agent_version_hash == AGENTEVAL_AGENT_VERSION_HASH
            and observations[0].prompt_contract_hash == AGENTEVAL_PROMPT_HASH
            and observations[0].tool_policy_fingerprint == AGENTEVAL_TOOL_POLICY_FINGERPRINT
        )
        finish_ok = broker.get("finished") is True and broker.get("finish_calls") == 1
        process_started = (evidence_root / "process.json").is_file()
        provider_recorded = identity_ok and (evidence_root / "identity.json").is_file()
        process_started_count += int(process_started)
        provider_observation_count += int(provider_recorded)
        failure = result.scorecard.failure
        policy_failure = failure is not None and failure.kind == "policy"
        infrastructure_failure = result.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        legal_candidate_ppa = any(
            evaluation.passed
            and evaluation.metrics is not None
            and evaluation.candidate_hash == result.manifest.candidate_hash
            and evaluation.profile_hash == result.manifest.resolved_profile_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        ppa = result.scorecard.quality.ppa
        final_ppa_eligible = ppa is not None and ppa.eligible
        policy_failure_count += int(policy_failure)
        infrastructure_complete = (
            infrastructure_complete
            and process_started
            and provider_recorded
            and not infrastructure_failure
        )
        records.append(
            {
                "run_id": result.manifest.run_id,
                "task_id": result.manifest.task_id,
                "resolved": result.scorecard.resolved,
                "model_identity_valid": identity_ok,
                "process_started": process_started,
                "provider_observation_recorded": provider_recorded,
                "typed_finish": finish_ok,
                "policy_failure": policy_failure,
                "infrastructure_failure": infrastructure_failure,
                "failure_subcategory": (
                    broker.get("policy_failure_subcategory")
                    or broker.get("infrastructure_failure_subcategory")
                ),
                "ppa_feedback_count": len(result.manifest.agent_feedback_evaluations),
                "legal_candidate_ppa": legal_candidate_ppa,
                "final_ppa_eligible": final_ppa_eligible,
            }
        )
    all_candidates_resolved = len(records) == _PROCESS_COUNT and all(
        record["resolved"] for record in records
    )
    ppa_records = [record for record in records if record["run_id"] in _PPA_RUN_IDS]
    pilot_complete = (
        infrastructure_complete
        and process_started_count == _PROCESS_COUNT
        and provider_observation_count == _PROCESS_COUNT
    )
    fully_successful = (
        pilot_complete
        and policy_failure_count == 0
        and all_candidates_resolved
        and all(record["typed_finish"] for record in records)
        and len(ppa_records) == len(_PPA_RUN_IDS)
        and all(record["legal_candidate_ppa"] for record in ppa_records)
        and all(record["final_ppa_eligible"] for record in ppa_records)
    )
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "codex_processes_authorized": _PROCESS_COUNT,
        "codex_processes_started": process_started_count,
        "provider_observations_recorded": provider_observation_count,
        "automatic_retries": 0,
        "runs": records,
        "all_candidates_resolved": all_candidates_resolved,
        "infrastructure_complete": infrastructure_complete,
        "pilot_complete": pilot_complete,
        "fully_successful": fully_successful,
        "pilot_is_benchmark_score": False,
        "benchmark_score_claimed": False,
    }


def _persist_final_evidence(
    output: Path,
    replay: dict[str, Any],
    scan: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    atomic_dump_json(output / "replay.json", replay)
    atomic_dump_json(output / "security-scan.json", scan)
    atomic_dump_json(output / "summary.json", summary)


def _finalize_existing(arguments: argparse.Namespace) -> int:
    output = smoke._directory(arguments.output)
    site_work = smoke._directory(arguments.site_work)
    broker_root = smoke._directory(arguments.broker_root)
    inputs = _inputs(arguments)
    profile_paths = _profile_paths(arguments)
    predecessor_path = smoke._regular_file(arguments.predecessor_summary, "smoke-v7 summary")
    predecessor = _validate_predecessor(predecessor_path)
    plan_path = smoke._regular_file(output / "plan.json", "formal pilot plan")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError("formal pilot plan is not valid JSON") from exc
    _validate_existing_plan(plan)
    if plan["predecessor_summary_hash"] != predecessor["summary_hash"]:
        raise ConfigurationError("pilot predecessor summary differs from the frozen plan")

    service = VeriGym(smoke._registries())
    source_configs = smoke._source_configs(inputs)
    _validate_sources(service, source_configs)
    results = _load_existing_results(output)
    _validate_existing_results_against_plan(plan, results)
    _validate_existing_ledger(output, results)
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        site_paths=(site_work, broker_root, output, predecessor_path),
    )
    summary = _campaign_summary(results, replay, scan)
    _persist_final_evidence(output, replay, scan, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fully_successful"] else 2


def _validate_existing_plan(plan: Any) -> None:
    expected = {
        "campaign_id": _CAMPAIGN_ID,
        "run_specs": [
            {
                "run_id": spec.run_id,
                "task_id": spec.task_id,
                "source_key": spec.source_key,
                "profile_name": spec.profile_name,
                "agent_ppa_feedback": spec.ppa,
            }
            for spec in _RUN_SPECS
        ],
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": _PROCESS_COUNT,
        "automatic_retries": 0,
        "pilot_is_benchmark_score": False,
        "benchmark_score_claimed": False,
    }
    if not isinstance(plan, dict) or any(plan.get(key) != value for key, value in expected.items()):
        raise ConfigurationError("existing campaign plan differs from the frozen pilot-v1 plan")
    codex = plan.get("codex")
    expected_codex = {
        "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
        "prompt_hash": AGENTEVAL_PROMPT_HASH,
        "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    }
    if not isinstance(codex, dict) or any(
        codex.get(key) != value for key, value in expected_codex.items()
    ):
        raise ConfigurationError("existing campaign plan has a different Codex agent identity")
    hashes = plan.get("run_config_hashes")
    predecessor_hash = plan.get("predecessor_summary_hash")
    if (
        not isinstance(hashes, list)
        or len(hashes) != _PROCESS_COUNT
        or not all(isinstance(item, str) and smoke._SHA256.fullmatch(item) for item in hashes)
        or not isinstance(predecessor_hash, str)
        or smoke._SHA256.fullmatch(predecessor_hash) is None
    ):
        raise ConfigurationError("existing pilot plan has invalid frozen hashes")


def _load_existing_results(output: Path) -> list[RunResult]:
    runs_root = output / "runs"
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ConfigurationError("existing pilot has no real runs directory")
    entries = sorted(entry.name for entry in runs_root.iterdir())
    if entries != sorted(_RUN_IDS):
        raise ConfigurationError("existing pilot does not contain fourteen frozen runs")
    results: list[RunResult] = []
    for spec in _RUN_SPECS:
        run_dir = runs_root / spec.run_id
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise ConfigurationError("existing pilot run directory is invalid")
        manifest = load_model(run_dir / "run_manifest.json", RunManifest)
        scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
        if (
            manifest.run_id != spec.run_id
            or manifest.task_id != spec.task_id
            or scorecard.run_id != spec.run_id
            or scorecard.task_id != spec.task_id
        ):
            raise ConfigurationError("existing pilot run identity differs from its frozen slot")
        results.append(RunResult(run_dir=run_dir, manifest=manifest, scorecard=scorecard))
    return results


def _validate_existing_results_against_plan(
    plan: dict[str, Any],
    results: list[RunResult],
) -> None:
    observed_hashes = [result.manifest.run_config_hash for result in results]
    if plan["run_config_hashes"] != observed_hashes:
        raise ConfigurationError("existing run configuration hashes differ from the frozen plan")


def _validate_existing_ledger(output: Path, results: list[RunResult]) -> None:
    ledger_path = smoke._regular_file(
        output / "evidence" / "process-authorizations.json",
        "process authorization ledger",
    )
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError("process authorization ledger is not valid JSON") from exc
    records = ledger.get("records") if isinstance(ledger, dict) else None
    if (
        not isinstance(records, list)
        or len(records) != _PROCESS_COUNT
        or len(results) != _PROCESS_COUNT
    ):
        raise ConfigurationError(
            "process authorization ledger must contain exactly fourteen records"
        )
    for ordinal, (record, result) in enumerate(zip(records, results, strict=True), start=1):
        evidence_root = result.run_dir / "artifacts" / "codex_cli"
        process_started = (evidence_root / "process.json").is_file()
        provider_recorded = (
            len(result.manifest.external_agent_observations) == 1
            and (evidence_root / "identity.json").is_file()
        )
        expected = {
            "ordinal": ordinal,
            "run_id": result.manifest.run_id,
            "task_id": result.manifest.task_id,
            "authorization_granted": True,
            "process_started": process_started,
            "provider_observation_recorded": provider_recorded,
            "retry_count": 0,
        }
        if not isinstance(record, dict) or any(
            record.get(key) != value for key, value in expected.items()
        ):
            raise ConfigurationError("process authorization ledger differs from run evidence")


if __name__ == "__main__":
    raise SystemExit(main())
