#!/usr/bin/env python3
"""Qualify and execute the frozen six-process RTL AgentEval gym-fix diagnostic."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_smoke as smoke
from verigym_rtl_repo import AGENT_EVAL_V2_SUITE_VERSION
from verigym_rtl_repo.dataset import (
    AGENT_EVAL_V2_VARIANT,
    CONTEXT_CLASSIFICATION_RULE,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.core.repository_observation import (
    BOUNDED_REPOSITORY_OBSERVATION_POLICY,
    bounded_read_view,
)
from verigym.experiments.state import atomic_dump_json
from verigym.profiles.identity import resolved_profile_component_hashes
from verigym.protocols.repository_action import repository_tool_definitions
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig

_CAMPAIGN_ID = "rtl-agenteval-codex-gpt54-xhigh-gymfix-diagnostic-v1"
_OUTPUT = Path(f"/data/jzhu484/Agent/experiments/{_CAMPAIGN_ID}")
_PILOT_SUMMARY = Path(
    "/data/jzhu484/Agent/experiments/rtl-agenteval-codex-gpt54-xhigh-pilot-v1/summary.json"
)
_PROCESS_COUNT = 6
_OPT_IN = "VERIGYM_RUN_RTL_AGENT_EVAL_GYMFIX_DIAGNOSTIC"
AGENTEVAL_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v5"
AGENTEVAL_AGENT_VERSION_HASH = "18e69a46fb8ecca8c1000cfb7997d17c27b572be1940e94a2dd26ced796945e8"
AGENTEVAL_PROMPT_HASH = "bd96dbf5defd6203d4939873f92817817bd5593750cd6e292a4c0240135edc5c"
AGENTEVAL_TOOL_POLICY_FINGERPRINT = (
    "424e9d022ef0c9fb891260698f130d865e19dfcaa2a7bfe4ff818a410823340a"
)
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
    definition["name"] for definition in repository_tool_definitions(dialect="mcp")
)


@dataclass(frozen=True)
class DiagnosticRunSpec:
    run_id: str
    task_id: str
    source_key: str
    profile_name: str | None = None
    ppa: bool = False


_RUN_SPECS = (
    DiagnosticRunSpec(
        "01-counter-open",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_open",
        True,
    ),
    DiagnosticRunSpec(
        "02-counter-dc",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_dc",
        True,
    ),
    DiagnosticRunSpec(
        "03-rtl-repo-test-000002",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000002",
        "rtl_repo",
    ),
    DiagnosticRunSpec(
        "04-rtl-repo-test-000003",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000003",
        "rtl_repo",
    ),
    DiagnosticRunSpec(
        "05-rtl-repo-test-000005",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000005",
        "rtl_repo",
    ),
    DiagnosticRunSpec(
        "06-rtl-repo-test-000004-control",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000004",
        "rtl_repo",
    ),
)
_RUN_IDS = tuple(spec.run_id for spec in _RUN_SPECS)
_PPA_RUN_IDS = frozenset(spec.run_id for spec in _RUN_SPECS if spec.ppa)

CampaignInfrastructureError = smoke.CampaignInfrastructureError
PreparedProfile = smoke.PreparedProfile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    parser.add_argument("--pilot-summary", type=Path, default=_PILOT_SUMMARY)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument(
        "--broker-root",
        type=Path,
        default=Path("/data/jzhu484/Agent/.verigym-tmp/cb-aeg1"),
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

    site_work = smoke._new_path(arguments.site_work, "site-profile work directory")
    output = smoke._new_path(arguments.output, "diagnostic output")
    broker_root = smoke._new_path(arguments.broker_root, "Codex broker root")
    inputs = _inputs(arguments)
    profile_paths = _profile_paths(arguments)
    pilot_summary_path = smoke._regular_file(arguments.pilot_summary, "pilot-v1 summary")
    pilot_receipt = _validate_pilot_summary(pilot_summary_path)
    capability_path, capability, auth = smoke._codex_preflight(
        arguments.codex_binary,
        site_work,
    )
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    image_id = smoke._docker_image_id(arguments.image)
    docker_config = smoke._docker_config(arguments.image, image_id)

    registries = smoke._registries()
    service = VeriGym(registries)
    source_configs = _source_configs(inputs)
    _validate_sources(service, source_configs)
    projection = _rtl_repo_v2_qualification(service, source_configs["rtl_repo"])
    broker_regression = _repository_broker_regression_qualification(service, source_configs)
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
    qualifications["rtl_repo_projection_v2"] = projection
    qualifications["pilot_v1_readonly_receipt"] = pilot_receipt

    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(smoke._broker_root(broker_root))
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
        pilot_summary_path=pilot_summary_path,
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
    results = _execute_exactly_six(service, configs, output)
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        site_paths=(site_work, broker_root, output, pilot_summary_path),
    )
    redaction = _redaction_audit(results)
    summary = _campaign_summary(results, replay, scan, redaction)
    _persist_final_evidence(output, replay, scan, redaction, summary)
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


def _validate_pilot_summary(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    try:
        summary = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("pilot-v1 summary is not valid JSON") from exc
    expected = {
        "campaign_id": "rtl-agenteval-codex-gpt54-xhigh-pilot-v1",
        "pilot_complete": True,
        "infrastructure_complete": True,
        "benchmark_score_claimed": False,
        "codex_processes_started": 14,
        "provider_observations_recorded": 14,
        "automatic_retries": 0,
    }
    runs = summary.get("runs") if isinstance(summary, dict) else None
    if (
        not isinstance(summary, dict)
        or any(summary.get(key) != value for key, value in expected.items())
        or not isinstance(runs, list)
        or len(runs) != 14
        or not all(
            isinstance(run, dict)
            and run.get("process_started") is True
            and run.get("provider_observation_recorded") is True
            for run in runs
        )
    ):
        raise ConfigurationError("diagnostic requires the complete read-only pilot-v1 receipt")
    return {
        "campaign_id": expected["campaign_id"],
        "summary_hash": hash_bytes(payload),
        "pilot_complete": True,
        "fully_successful": summary.get("fully_successful") is True,
        "read_only": True,
    }


def _source_configs(inputs: dict[str, Path]) -> dict[str, SuiteSourceConfig]:
    return {
        "counter": SuiteSourceConfig(
            source_root=inputs["rtllm"],
            variant="counter_12_agent_eval_v1",
        ),
        "up_down": SuiteSourceConfig(
            source_root=inputs["rtllm"],
            variant="up_down_counter_agent_eval_v1",
        ),
        "verilog_eval": SuiteSourceConfig(
            source_root=inputs["verilog_eval"],
            variant="v2-spec-to-rtl-agent-eval-v1",
        ),
        "rtl_repo": SuiteSourceConfig(
            source_root=inputs["rtl_repo"],
            variant=AGENT_EVAL_V2_VARIANT,
        ),
    }


def _validation_tasks() -> tuple[tuple[str, str], ...]:
    return (
        (_RUN_SPECS[0].task_id, "counter"),
        (smoke._TASKS[1], "up_down"),
        (smoke._TASKS[2], "verilog_eval"),
        *((spec.task_id, spec.source_key) for spec in _RUN_SPECS[2:]),
    )


def _validate_sources(
    service: VeriGym,
    configs: dict[str, SuiteSourceConfig],
) -> None:
    for task_id, key in _validation_tasks():
        suite, task, assets = service.load_task(task_id, configs[key])
        report = suite.validate_source()
        if not report.valid or not Path(assets.visible_root).is_dir() or task.id != task_id:
            raise ConfigurationError(f"source qualification failed for {task_id}")


def _rtl_repo_v2_qualification(
    service: VeriGym,
    source_config: SuiteSourceConfig,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for spec in _RUN_SPECS[2:]:
        _suite, task, assets = service.load_task(spec.task_id, source_config)
        root = Path(assets.visible_root)
        index_path = root / "repository" / "context" / "index.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError("RTL-Repo v2 context index is unreadable") from exc
        items = index.get("items") if isinstance(index, dict) else None
        if (
            task.suite_version != AGENT_EVAL_V2_SUITE_VERSION
            or task.metadata.get("projection_version") != "v2"
            or task.metadata.get("context_classification_rule") != CONTEXT_CLASSIFICATION_RULE
            or not isinstance(items, list)
            or len(items) != task.metadata.get("context_count")
        ):
            raise ConfigurationError("RTL-Repo v2 task identity or index differs")
        totals = {"source": 0, "generated": 0}
        for ordinal, item in enumerate(items):
            if not isinstance(item, dict):
                raise ConfigurationError("RTL-Repo v2 context item is malformed")
            expected_file = f"{ordinal:04d}.txt"
            classification = item.get("classification")
            context_path = root / "repository" / "context" / expected_file
            payload = context_path.read_bytes()
            if (
                item.get("file") != expected_file
                or classification not in totals
                or item.get("read_priority") != (0 if classification == "source" else 1)
                or item.get("utf8_bytes") != len(payload)
            ):
                raise ConfigurationError("RTL-Repo v2 context ordering or byte count differs")
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ConfigurationError("RTL-Repo v2 context is not UTF-8") from exc
            totals[classification] += len(payload)
        if (
            index.get("source_utf8_bytes") != totals["source"]
            or index.get("generated_utf8_bytes") != totals["generated"]
            or index.get("read_priority_order") != ["source", "generated"]
        ):
            raise ConfigurationError("RTL-Repo v2 aggregate context bytes differ")
        visible_paths = {
            path.relative_to(root).as_posix() for path in sorted(root.rglob("*")) if path.is_file()
        }
        if (
            any(
                path == "hidden"
                or path.startswith("hidden/")
                or path == "verifier"
                or path.startswith("verifier/")
                for path in visible_paths
            )
            or "next_line" in index
            or "all_code" in index
            or any(hidden.mount_path in visible_paths for hidden in assets.hidden_assets)
        ):
            raise ConfigurationError("RTL-Repo v2 structurally exposes a verifier-only asset")
        records.append(
            {
                "task_id": spec.task_id,
                "context_count": len(items),
                "source_utf8_bytes": totals["source"],
                "generated_utf8_bytes": totals["generated"],
                "original_order_preserved": True,
                "verifier_only_target_not_materialized": True,
            }
        )
    return {
        "passed": True,
        "model_calls": 0,
        "variant": AGENT_EVAL_V2_VARIANT,
        "suite_version": AGENT_EVAL_V2_SUITE_VERSION,
        "context_classification_rule": CONTEXT_CLASSIFICATION_RULE,
        "records": records,
    }


def _repository_broker_regression_qualification(
    service: VeriGym,
    configs: dict[str, SuiteSourceConfig],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    total_empty_views = 0
    required_empty_tasks = {spec.task_id for spec in _RUN_SPECS[2:]}
    qualified_empty_tasks: set[str] = set()
    for task_id, key in _validation_tasks():
        _suite, _task, assets = service.load_task(task_id, configs[key])
        root = Path(assets.visible_root)
        empty_files = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.stat().st_size != 0:
                continue
            relative = path.relative_to(root).as_posix()
            for concise in (None, True):
                rendered, metadata = bounded_read_view(
                    "",
                    relative,
                    concise=concise,
                    policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
                )
                if (
                    rendered
                    or metadata.get("line_count") != 0
                    or metadata.get("line_range") != [0, 0]
                ):
                    raise ConfigurationError("empty repository read regression failed")
                total_empty_views += 1
            empty_files += 1
        if task_id in required_empty_tasks and empty_files > 0:
            qualified_empty_tasks.add(task_id)
        records.append({"task_id": task_id, "empty_files_checked": empty_files})
    if qualified_empty_tasks != required_empty_tasks or total_empty_views < 2:
        raise ConfigurationError("broker regression did not exercise every RTL-Repo candidate")
    return {
        "passed": True,
        "model_calls": 0,
        "empty_file_views_checked": total_empty_views,
        "records": records,
    }


def _agent_options(capability: Any, auth: Any) -> dict[str, Any]:
    return {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
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
        "prompt_contract_id": "repository_action_v2_prompt_v4",
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
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
    pilot_summary_path: Path,
) -> dict[str, Any]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("diagnostic plan must contain exactly six frozen runs")
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
        "pilot_v1_summary_hash": hash_bytes(pilot_summary_path.read_bytes()),
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_pilot_v2_authorized": False,
    }


def _execute_exactly_six(
    service: VeriGym,
    configs: list[RunConfig],
    output: Path,
) -> list[RunResult]:
    if len(configs) != _PROCESS_COUNT:
        raise ConfigurationError("diagnostic launcher must contain exactly six frozen runs")
    ledger: list[dict[str, Any]] = []
    results: list[RunResult] = []
    for ordinal, config in enumerate(configs, start=1):
        record = {
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
        try:
            run = service.run(config)
        except Exception:
            run_dir = config.output.expanduser().resolve() / str(config.run_id)
            smoke._update_process_ledger_record(record, run_dir=run_dir)
            record["status"] = "infrastructure_failure"
            _write_ledger(output, ledger)
            raise
        smoke._update_process_ledger_record(record, run_dir=run.run_dir, run=run)
        observation_count = len(run.manifest.external_agent_observations)
        record["identity_observation_count"] = observation_count
        record["provider_observation_recorded"] = _identity_observation_valid(run)
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        if not record["provider_observation_recorded"]:
            record["status"] = "identity_infrastructure_failure"
            _write_ledger(output, ledger)
            raise CampaignInfrastructureError(
                "diagnostic stopped after missing, duplicate, or drifted identity evidence"
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
            raise CampaignInfrastructureError(
                "diagnostic stopped after an infrastructure or safety-invalid run"
            )
    if len(results) != _PROCESS_COUNT:
        raise ConfigurationError("six-process diagnostic stopped before all runs completed")
    return results


def _identity_observation_valid(result: RunResult) -> bool:
    observations = result.manifest.external_agent_observations
    identity_path = result.run_dir / "artifacts" / "codex_cli" / "identity.json"
    if len(observations) != 1 or not identity_path.is_file():
        return False
    observation = observations[0]
    return bool(
        observation.invocation_count == 1
        and observation.requested_model_id == "gpt-5.4"
        and observation.observed_model_id in {None, "gpt-5.4"}
        and observation.effective_reasoning_effort == "xhigh"
        and observation.harness_id == AGENTEVAL_AGENT_VERSION_ID
        and observation.agent_version_hash == AGENTEVAL_AGENT_VERSION_HASH
        and observation.prompt_contract_hash == AGENTEVAL_PROMPT_HASH
        and observation.tool_policy_fingerprint == AGENTEVAL_TOOL_POLICY_FINGERPRINT
    )


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


def _redaction_audit(results: list[RunResult]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for result in results:
        root = result.run_dir / "artifacts" / "codex_cli"
        process = _read_json(root / "process.json")
        summary = _read_json(root / "summary.json")
        broker = _read_json(root / "broker.json")
        forbidden = [
            name
            for name in (
                "raw_stdout.jsonl",
                "raw_stderr.txt",
                "training-transcript.json",
            )
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
        raise ConfigurationError("diagnostic evidence JSON is unavailable") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("diagnostic evidence JSON must be an object")
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
                "compile_passed": compile_passed,
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
        and not any(record["infrastructure_failure"] for record in records)
    )
    fully_successful = bool(
        infrastructure_complete
        and all(record["resolved"] for record in records)
        and all(record["typed_finish"] for record in records)
        and all(record["provider_usage_complete"] for record in records)
        and not any(record["timed_out"] for record in records)
        and not any(record["policy_failure"] for record in records)
        and len(ppa_records) == len(_PPA_RUN_IDS)
        and all(record["compile_passed"] for record in ppa_records)
        and all(record["legal_candidate_ppa"] for record in ppa_records)
        and all(record["final_ppa_eligible"] for record in ppa_records)
    )
    return {
        "schema_version": "1.0",
        "campaign_id": _CAMPAIGN_ID,
        "codex_processes_authorized": _PROCESS_COUNT,
        "codex_processes_started": sum(record["process_started"] for record in records),
        "provider_observations_recorded": sum(record["model_identity_valid"] for record in records),
        "automatic_retries": 0,
        "runs": records,
        "all_candidates_resolved": len(records) == _PROCESS_COUNT
        and all(record["resolved"] for record in records),
        "infrastructure_complete": infrastructure_complete,
        "diagnostic_complete": infrastructure_complete and len(records) == _PROCESS_COUNT,
        "fully_successful": fully_successful,
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_pilot_v2_authorized": False,
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
    inputs = _inputs(arguments)
    profile_paths = _profile_paths(arguments)
    pilot_summary_path = smoke._regular_file(arguments.pilot_summary, "pilot-v1 summary")
    pilot_receipt = _validate_pilot_summary(pilot_summary_path)
    plan = _read_json(smoke._regular_file(output / "plan.json", "diagnostic plan"))
    _validate_existing_plan(plan)
    if plan.get("pilot_v1_summary_hash") != pilot_receipt["summary_hash"]:
        raise ConfigurationError("diagnostic pilot-v1 receipt differs from the frozen plan")

    service = VeriGym(smoke._registries())
    source_configs = _source_configs(inputs)
    _validate_sources(service, source_configs)
    _rtl_repo_v2_qualification(service, source_configs["rtl_repo"])
    results = _load_existing_results(output)
    if plan["run_config_hashes"] != [result.manifest.run_config_hash for result in results]:
        raise ConfigurationError("diagnostic run configuration hashes differ from the plan")
    _validate_existing_ledger(output, results)
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        site_paths=(site_work, broker_root, output, pilot_summary_path),
    )
    redaction = _redaction_audit(results)
    summary = _campaign_summary(results, replay, scan, redaction)
    _persist_final_evidence(output, replay, scan, redaction, summary)
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
        "diagnostic_only": True,
        "benchmark_score_claimed": False,
        "automatic_pilot_v2_authorized": False,
    }
    if not isinstance(plan, dict) or any(plan.get(key) != value for key, value in expected.items()):
        raise ConfigurationError("existing plan differs from the frozen gym-fix diagnostic")
    codex = plan.get("codex")
    expected_codex = {
        "agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
        "prompt_hash": AGENTEVAL_PROMPT_HASH,
        "tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    }
    hashes = plan.get("run_config_hashes")
    if (
        not isinstance(codex, dict)
        or any(codex.get(key) != value for key, value in expected_codex.items())
        or not isinstance(hashes, list)
        or len(hashes) != _PROCESS_COUNT
        or not all(isinstance(item, str) and smoke._SHA256.fullmatch(item) for item in hashes)
    ):
        raise ConfigurationError("existing diagnostic plan has invalid frozen identities")


def _load_existing_results(output: Path) -> list[RunResult]:
    runs_root = output / "runs"
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ConfigurationError("existing diagnostic has no real runs directory")
    if sorted(entry.name for entry in runs_root.iterdir()) != sorted(_RUN_IDS):
        raise ConfigurationError("existing diagnostic does not contain exactly six runs")
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
            "diagnostic process authorization ledger",
        )
    )
    records = ledger.get("records")
    if not isinstance(records, list) or len(records) != _PROCESS_COUNT:
        raise ConfigurationError("diagnostic ledger must contain exactly six records")
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
            raise ConfigurationError("diagnostic ledger differs from run evidence")


if __name__ == "__main__":
    raise SystemExit(main())
