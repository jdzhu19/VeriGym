from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.milestone9_helpers import experiment_config, offline_service
from verigym.campaign.config import load_campaign_config
from verigym.campaign.render import CAMPAIGN_CSV_COLUMNS
from verigym.campaign.schemas import CampaignInputConfig, CampaignQualityPartition
from verigym.campaign.service import (
    CampaignService,
    _license_count,
    validate_evolving_plan_contract,
    validate_quality_comparison_partitions,
)
from verigym.campaign.service import (
    _quality_row as project_quality_row,
)
from verigym.cli.app import app
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig, PlanItem
from verigym.experiments.state import atomic_dump_json, load_jsonl_models
from verigym.models.static import AND_GATE_GOOD_SOURCE, StaticModelClient
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.schemas import QualityPartition, QualityRunValue
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import (
    EvolvingEvaluationReport,
    PairedVersionDifference,
    TaskVersionMetric,
    VersionMetricSummary,
)
from verigym.schemas.prompt import PromptPolicyDescriptor


def _chat_service() -> VeriGym:
    return offline_service(
        StaticModelClient(
            name="campaign-static-good",
            responses=[AND_GATE_GOOD_SOURCE],
        )
    )


def _run(config: ExperimentConfig, *, chat: bool = False) -> Path:
    if chat:
        planner = ExperimentPlanner(_chat_service())
        runner = BatchRunner(
            planner=planner,
            service_factory=_chat_service,
        )
    else:
        planner = ExperimentPlanner(offline_service())
        runner = BatchRunner(planner=planner, service_factory=offline_service)
    result = runner.run(planner.build(config))
    assert result.exit_code == 0
    return result.experiment_dir


def _version_metric(version_id: str) -> VersionMetricSummary:
    return VersionMetricSummary(
        agent_version_id=version_id,
        planned=1,
        launched=1,
        terminal=1,
        evaluable=1,
        resolved=1,
        candidate_failures=0,
        contained_policy_failures=0,
        infrastructure_failures=0,
        public_test_reached=1,
        hidden_verifier_reached=1,
        patch_reproducible=1,
        macro_pass_at_1=1.0,
        mean_public_tool_calls=5.0,
        mean_tokens=0.0,
        mean_wall_time_s=0.0,
        missing_usage_count=0,
    )


def _write_evolving_report(experiment: Path, output: Path) -> EvolvingEvaluationReport:
    manifest = json.loads((experiment / "experiment_manifest.json").read_text(encoding="utf-8"))
    version_ids = ("toy-v0", "toy-v1")
    metrics = [_version_metric(version_id) for version_id in version_ids]
    task_metrics = [
        TaskVersionMetric(
            task_id="toy-rtl/and-gate-basic",
            agent_version_id=version_id,
            planned=1,
            terminal=1,
            evaluable=1,
            resolved=1,
            contained_policy_failures=0,
            infrastructure_failures=0,
            pass_at_1=1.0,
        )
        for version_id in version_ids
    ]
    paired = PairedVersionDifference(
        baseline_version_id=version_ids[0],
        evolved_version_id=version_ids[1],
        macro_pass_at_1_delta=0.0,
    )
    base = {
        "schema_version": "1.0",
        "report_id": "campaign-evolving-test",
        "split_manifest_hash": "a" * 64,
        "heldout_plan_hash": manifest["plan_hash"],
        "version_metrics": [item.model_dump(mode="json") for item in metrics],
        "task_version_metrics": [item.model_dump(mode="json") for item in task_metrics],
        "paired_difference": paired.model_dump(mode="json"),
        "heldout_task_count": 1,
        "samples_per_task_version": 1,
        "no_weight_update": True,
        "establishes_general_improvement": False,
        "required_interpretation": (
            "The before/after result is a bounded first-party Evolve-Context pilot and "
            "does not establish general performance improvement."
        ),
    }
    report = EvolvingEvaluationReport.model_validate({**base, "report_hash": content_hash(base)})
    atomic_dump_json(output, report)
    return report


def _campaign_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    chat_root = _run(
        experiment_config(
            tmp_path / "chat",
            tasks=["and-gate-basic"],
            systems=[
                {
                    "id": "chat",
                    "agent": {"id": "single-turn"},
                    "model": {"id": "campaign-static-good"},
                }
            ],
            seeds=[0],
            mode="chat",
        ),
        chat=True,
    )
    agent_root = _run(
        experiment_config(
            tmp_path / "agent",
            tasks=["and-gate-basic"],
            systems=[{"id": "agent", "agent": {"id": "scripted"}}],
            seeds=[0],
            mode="agent",
        )
    )
    evolving_root = _run(
        experiment_config(
            tmp_path / "evolving",
            tasks=["and-gate-basic"],
            systems=[
                {
                    "id": "v0",
                    "agent": {
                        "id": "scripted",
                        "options": {
                            "agent_version_id": "toy-v0",
                            "agent_version_hash": "b" * 64,
                        },
                    },
                },
                {
                    "id": "v1",
                    "agent": {
                        "id": "scripted",
                        "options": {
                            "agent_version_id": "toy-v1",
                            "agent_version_hash": "c" * 64,
                            "memory_pack": {"content_hash": "d" * 64},
                        },
                    },
                },
            ],
            seeds=[0],
            mode="agent",
        )
    )
    evolution_path = tmp_path / "evolving-evaluation.json"
    _write_evolving_report(evolving_root, evolution_path)
    return chat_root, agent_root, evolving_root, evolution_path


def _write_campaign_config(
    path: Path,
    output: Path,
    chat_root: Path,
    agent_root: Path,
    evolving_root: Path,
    evolution_path: Path,
) -> None:
    payload = {
        "schema_version": "1.0",
        "name": "unit platform matrix",
        "inputs": [
            {
                "id": "chat-track",
                "kind": "experiment",
                "evaluation_mode": "chat",
                "experiment_root": str(chat_root),
            },
            {
                "id": "agent-track",
                "kind": "experiment",
                "evaluation_mode": "agent",
                "experiment_root": str(agent_root),
            },
            {
                "id": "evolving-track",
                "kind": "evolving_evaluation",
                "evaluation_mode": "evolving_agent",
                "experiment_root": str(evolving_root),
                "evolving_report": str(evolution_path),
            },
        ],
        "output": {"root": str(output)},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_campaign_generates_complete_path_free_platform_matrix(tmp_path: Path) -> None:
    chat, agent, evolving, evolution = _campaign_fixture(tmp_path)
    config_path = tmp_path / "campaign.json"
    output = tmp_path / "campaign-reports"
    _write_campaign_config(config_path, output, chat, agent, evolving, evolution)

    generated = CampaignService().generate_from_path(config_path)

    assert generated.report.mode_coverage.complete_platform_matrix
    assert len(generated.report.evaluations) == 4
    assert {item.evaluation_mode for item in generated.report.evaluations} == {
        "chat",
        "agent",
        "evolving_agent",
    }
    assert {item.agent_version_id for item in generated.report.evaluations} >= {
        "toy-v0",
        "toy-v1",
    }
    chat_summary = next(
        item for item in generated.report.evaluations if item.evaluation_mode == "chat"
    )
    assert chat_summary.model_client_id == "campaign-static-good"
    assert chat_summary.model_id == "campaign-static-good"
    assert generated.report.offline_only
    assert generated.report.model_calls_during_reporting == 0
    assert generated.report.tool_calls_during_reporting == 0
    serialized = generated.report.model_dump_json()
    assert str(tmp_path) not in serialized
    assert generated.json_path.name == "campaign_report.json"
    assert generated.csv_path.name == "campaign_report.csv"
    assert generated.markdown_path.name == "campaign_report.md"

    rows = list(csv.DictReader(StringIO(generated.csv_path.read_text(encoding="utf-8"))))
    assert list(rows[0]) == CAMPAIGN_CSV_COLUMNS
    assert [row["record_type"] for row in rows] == ["evaluation"] * 4
    markdown = generated.markdown_path.read_text(encoding="utf-8")
    assert "Complete chat/agent/evolving matrix: yes" in markdown
    assert "The campaign never ranks different partitions." in markdown

    repeated = CampaignService().generate_from_path(config_path)
    assert repeated.hashes == generated.hashes


def test_campaign_cli_validates_and_generates(tmp_path: Path) -> None:
    chat, agent, evolving, evolution = _campaign_fixture(tmp_path)
    config_path = tmp_path / "campaign.json"
    output = tmp_path / "campaign-reports"
    _write_campaign_config(config_path, output, chat, agent, evolving, evolution)
    runner = CliRunner()

    validated = runner.invoke(app, ["campaign", "validate", "--config", str(config_path)])
    assert validated.exit_code == 0, validated.output
    assert '"complete_platform_matrix": true' in validated.output

    generated = runner.invoke(app, ["campaign", "generate", "--config", str(config_path)])
    assert generated.exit_code == 0, generated.output
    assert "Campaign JSON:" in generated.output
    assert (output / "campaign_report.json").is_file()


def test_campaign_config_is_duplicate_safe_and_rejects_parent_paths(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text('schema_version: "1.0"\nname: first\nname: second\n', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate campaign configuration key"):
        load_campaign_config(duplicate)

    invalid = tmp_path / "parent.json"
    invalid.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "name": "invalid parent path",
                "inputs": [
                    {
                        "id": "chat",
                        "kind": "experiment",
                        "evaluation_mode": "chat",
                        "experiment_root": "../chat",
                    },
                    {
                        "id": "agent",
                        "kind": "experiment",
                        "evaluation_mode": "agent",
                        "experiment_root": "agent",
                    },
                ],
                "output": {"root": "reports"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="cannot contain '..'"):
        load_campaign_config(invalid)


def test_campaign_service_rejects_a_symlink_config(tmp_path: Path) -> None:
    target = tmp_path / "campaign.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "campaign-link.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="traverses a symlink"):
        CampaignService().build_from_path(link)


def test_evolving_contract_rejects_tool_or_verifier_drift(tmp_path: Path) -> None:
    _chat, _agent, evolving, evolution = _campaign_fixture(tmp_path)
    report = EvolvingEvaluationReport.model_validate_json(evolution.read_text(encoding="utf-8"))
    items = load_jsonl_models(evolving / "plan.jsonl", PlanItem)
    changed = [
        item.model_copy(update={"tool_policy_hash": "f" * 64})
        if item.system.agent_options.get("agent_version_id") == "toy-v1"
        else item
        for item in items
    ]

    with pytest.raises(ValueError, match="must keep task, model, runtime, tools, verifier"):
        validate_evolving_plan_contract(
            changed,
            {item.agent_version_id for item in report.version_metrics},
        )


def test_evolving_contract_accepts_hash_bound_versioned_prompt_context(tmp_path: Path) -> None:
    _chat, _agent, evolving, evolution = _campaign_fixture(tmp_path)
    report = EvolvingEvaluationReport.model_validate_json(evolution.read_text(encoding="utf-8"))
    items = load_jsonl_models(evolving / "plan.jsonl", PlanItem)
    updated: list[PlanItem] = []
    for item in items:
        version_id = item.system.agent_options["agent_version_id"]
        version_hash = item.system.agent_options["agent_version_hash"]
        assert isinstance(version_id, str) and isinstance(version_hash, str)
        memory_hash = "d" * 64 if version_id == "toy-v1" else None
        prompt = PromptPolicyDescriptor(
            id="versioned-context",
            version="1.0.0",
            interaction_mode=InteractionMode.AGENT,
            configuration_fingerprint=("e" if version_id == "toy-v0" else "f") * 64,
            resolver_id="agent_execution_prompt_policy_v1",
            task_context_policy="public-task-v1",
            task_context_hash="1" * 64,
            base_instruction_policy="strict-agent-v1",
            content_visibility_policy="public-only-v1",
            max_prompt_bytes=4096,
            max_task_context_bytes=2048,
            agent_descriptor_hash=content_hash(item.system.agent_descriptor),
            agent_version_id=version_id,
            agent_version_hash=version_hash,
            memory_pack_hash=memory_hash,
        )
        options = dict(item.system.agent_options)
        options["agent_version_manifest_json"] = json.dumps({"version": version_id})
        system = item.system.model_copy(update={"agent_options": options})
        updated.append(
            item.model_copy(
                update={
                    "system": system,
                    "prompt_policy": prompt,
                    "prompt_policy_hash": prompt.configuration_fingerprint,
                }
            )
        )

    by_version = validate_evolving_plan_contract(
        updated,
        {item.agent_version_id for item in report.version_metrics},
    )

    assert {key: len(value) for key, value in by_version.items()} == {
        "toy-v0": 1,
        "toy-v1": 1,
    }


def test_campaign_rejects_evolving_counts_that_differ_from_aggregate(tmp_path: Path) -> None:
    chat, agent, evolving, evolution = _campaign_fixture(tmp_path)
    report = EvolvingEvaluationReport.model_validate_json(evolution.read_text(encoding="utf-8"))
    payload = report.model_dump(mode="json")
    payload.pop("report_hash")
    payload["version_metrics"][0]["resolved"] = 0
    tampered = EvolvingEvaluationReport.model_validate(
        {**payload, "report_hash": content_hash(payload)}
    )
    atomic_dump_json(evolution, tampered)
    config_path = tmp_path / "campaign.json"
    _write_campaign_config(
        config_path,
        tmp_path / "reports",
        chat,
        agent,
        evolving,
        evolution,
    )

    with pytest.raises(ValueError, match="version metrics differ"):
        CampaignService().build_from_path(config_path)


def _quality_row(*, partition: str, profile: str) -> CampaignQualityPartition:
    return CampaignQualityPartition(
        input_id="quality",
        evaluation_mode="agent",
        comparison_partition_id=partition,
        suite_source_identity="1" * 64,
        task_id="toy-rtl/and-gate-basic",
        task_hash="2" * 64,
        correctness_definition_hash="3" * 64,
        declared_profile_id="profile",
        declared_profile_hash="4" * 64,
        resolved_profile_hash=profile,
        runtime_identity_hash="5" * 64,
        metric_scope="synthesis_area_timing",
        area_unit="um^2",
        timing_unit="ns",
        clock_period=10.0,
        reference_candidate_hash="6" * 64,
        eligible_run_count=1,
        ineligible_run_count=0,
    )


def test_campaign_never_reuses_a_ppa_partition_for_different_profiles() -> None:
    first = _quality_row(partition="a" * 64, profile="b" * 64)
    second = _quality_row(partition="a" * 64, profile="c" * 64)
    with pytest.raises(ValueError, match="different contracts"):
        validate_quality_comparison_partitions([first, second])

    separate = second.model_copy(update={"comparison_partition_id": "d" * 64})
    assert validate_quality_comparison_partitions([first, separate]) == [first, separate]


def test_campaign_quality_summary_preserves_raw_candidate_and_reference_metrics() -> None:
    identity = {
        "suite_source_identity": "1" * 64,
        "task_id": "toy-rtl/and-gate-basic",
        "task_hash": "2" * 64,
        "correctness_definition_hash": "3" * 64,
        "declared_profile_id": "profile",
        "declared_profile_hash": "4" * 64,
        "resolved_profile_hash": "5" * 64,
        "runtime_identity_hash": "6" * 64,
        "image_id": None,
        "area_unit": "um^2",
        "metric_scope": "synthesis_area_timing",
        "timing_unit": "ns",
        "clock_period": 10.0,
        "reference_candidate_hash": "7" * 64,
    }
    run = QualityRunValue(
        plan_index=0,
        run_id="run",
        task_id="toy-rtl/and-gate-basic",
        system_id="system",
        eligible=True,
        area=10.0,
        reference_area=12.0,
        area_ratio=1.2,
        delay=2.0,
        reference_delay=2.5,
        delay_ratio=1.25,
        worst_negative_slack=-0.5,
        reference_worst_negative_slack=-0.25,
        worst_negative_slack_delta=-0.25,
    )
    partition = QualityPartition(
        partition_id=content_hash(identity),
        **identity,
        eligible_run_count=1,
        ineligible_run_count=0,
        runs=[run],
    )
    row = project_quality_row(
        CampaignInputConfig(
            id="quality",
            kind="experiment",
            evaluation_mode="agent",
            experiment_root=Path("experiment"),
        ),
        partition,
        [run],
        version_id=None,
    )

    assert row.area_median == 10.0
    assert row.reference_area_median == 12.0
    assert row.delay_median == 2.0
    assert row.reference_delay_median == 2.5
    assert row.worst_negative_slack_median == -0.5
    assert row.reference_worst_negative_slack_median == -0.25


def test_license_unavailable_remains_verifier_infrastructure(tmp_path: Path) -> None:
    root = _run(
        experiment_config(
            tmp_path / "license",
            tasks=["and-gate-basic"],
            systems=[{"id": "agent", "agent": {"id": "scripted"}}],
            seeds=[0],
        )
    )
    aggregate = ReportBuilder().build(root)
    taxonomy = aggregate.failure_taxonomy.model_copy(
        update={"verifier_tool": {"license_unavailable": 2}, "model_infrastructure": {}}
    )
    aggregate = aggregate.model_copy(update={"failure_taxonomy": taxonomy})

    assert _license_count(aggregate) == 2
    assert aggregate.failure_taxonomy.model_infrastructure == {}
