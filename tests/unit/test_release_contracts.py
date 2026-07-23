"""Focused stabilization contracts added by the MVP release audit."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from tests.milestone9_helpers import experiment_config, offline_service
from verigym.core.episode import BudgetTracker
from verigym.core.errors import ArtifactIntegrityError, ConfigurationError
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.loaders import load_model
from verigym.core.model_gateway import ModelGateway
from verigym.core.trace import TraceWriter
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.schemas import (
    ExperimentConfig,
    ExperimentExecutionConfig,
    ExperimentManifest,
    PlanItem,
    RunIndexRecord,
)
from verigym.experiments.state import load_jsonl_models
from verigym.models.openai_compatible import OpenAICompatibleModelClient
from verigym.profiles.base import ResolvedToolchainProfile
from verigym.registry.base import PluginRegistry
from verigym.reporting.aggregate import ReportBuilder
from verigym.reporting.csv_report import CSV_COLUMNS
from verigym.reporting.loader import LoadedReportInputs, ValidatedRun
from verigym.reporting.schemas import AggregateReport
from verigym.schema_export import export_schemas
from verigym.schemas.common import PluginDescriptor
from verigym.schemas.model import ModelMessage
from verigym.schemas.run import RunConfig, RunManifest
from verigym.schemas.sampling import PassAtKReport, SampleSetManifest
from verigym.schemas.score import ScoreCard
from verigym.schemas.task import BudgetSpec

_GOLDEN = Path("tests/fixtures/golden/v1")


@pytest.mark.parametrize(
    ("relative", "model", "schema_name"),
    [
        ("resolved_local/run_manifest.json", RunManifest, "run-manifest"),
        ("resolved_local/scorecard.json", ScoreCard, "scorecard"),
        ("unresolved_normal/scorecard.json", ScoreCard, "scorecard"),
        ("model_error/scorecard.json", ScoreCard, "scorecard"),
        ("docker_replay/run_manifest.json", RunManifest, "run-manifest"),
        (
            "verilog_eval_sampling/sample_set_manifest.json",
            SampleSetManifest,
            "sample-set-manifest",
        ),
        ("verilog_eval_sampling/pass_at_k.json", PassAtKReport, "pass-at-k-report"),
        ("yosys_area/scorecard.json", ScoreCard, "scorecard"),
        (
            "yosys_area/resolved_toolchain_profile.json",
            ResolvedToolchainProfile,
            "resolved-toolchain-profile",
        ),
        (
            "experiment/experiment_manifest.json",
            ExperimentManifest,
            "experiment-manifest",
        ),
        ("experiment/experiment_config.json", ExperimentConfig, "experiment-config"),
        ("experiment/aggregate.json", AggregateReport, "aggregate-report"),
    ],
)
def test_golden_json_loads_and_validates_exported_schema(
    relative: str,
    model: type[Any],
    schema_name: str,
) -> None:
    path = _GOLDEN / relative
    value = load_model(path, model)
    assert value.schema_version == "1.0"
    schema = json.loads(
        (Path("docs/schemas") / f"{schema_name}.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(json.loads(path.read_text(encoding="utf-8")))


def test_golden_jsonl_and_text_reports_are_compatible_and_sanitized() -> None:
    assert len(load_jsonl_models(_GOLDEN / "experiment/plan.jsonl", PlanItem)) == 1
    assert len(load_jsonl_models(_GOLDEN / "experiment/run_index.jsonl", RunIndexRecord)) == 1
    with (_GOLDEN / "experiment/runs.csv").open(encoding="utf-8", newline="") as stream:
        assert next(csv.reader(stream)) == CSV_COLUMNS
    assert "# VeriGym experiment report" in (_GOLDEN / "experiment/report.md").read_text(
        encoding="utf-8"
    )
    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in sorted(_GOLDEN.rglob("*"))
        if path.is_file()
    )
    assert "/tmp/" not in serialized
    assert "/home/" not in serialized
    assert "/data/" not in serialized
    assert "Bearer " not in serialized


def test_schema_export_has_no_drift() -> None:
    assert export_schemas(Path("docs/schemas"), check=True) == []


def test_new_run_integrity_tamper_and_legacy_paths(tmp_path: Path) -> None:
    result = offline_service().run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            agent="scripted",
            output=tmp_path / "runs",
        )
    )
    verified = verify_artifact_manifest(result.run_dir, expected_scope="run")
    assert verified.status == "verified"
    assert verified.verified_entry_count > 5

    candidate = result.run_dir / "candidate" / "rtl" / "and_gate.v"
    candidate.write_text(candidate.read_text(encoding="utf-8") + "\n// tampered\n")
    with pytest.raises(ArtifactIntegrityError, match="candidate/rtl/and_gate.v"):
        verify_artifact_manifest(result.run_dir, expected_scope="run")

    (result.run_dir / "artifact_manifest.json").unlink()
    assert (
        verify_artifact_manifest(result.run_dir, expected_scope="run").status == "legacy_unverified"
    )


def test_costs_partition_without_conversion_or_unknown_unit_sum(tmp_path: Path) -> None:
    result = offline_service().run(
        RunConfig(
            task_id="toy-rtl/and-gate-basic",
            agent="scripted",
            output=tmp_path / "runs",
        )
    )
    dimensions = [
        (1.25, "USD", None),
        (2.5, "EUR", None),
        (3.0, None, None),
        (None, None, None),
    ]
    runs: list[ValidatedRun] = []
    for index, (cost, currency, unit) in enumerate(dimensions):
        run_id = f"cost-{index}"
        score = result.scorecard.model_copy(
            update={
                "run_id": run_id,
                "efficiency": result.scorecard.efficiency.model_copy(
                    update={
                        "model_api_cost": cost,
                        "model_api_cost_currency": currency,
                        "model_api_cost_unit": unit,
                    }
                ),
            }
        )
        runs.append(
            ValidatedRun(
                plan_index=index,
                attempt=1,
                relative_path=run_id,
                manifest=result.manifest.model_copy(update={"run_id": run_id}),
                scorecard=score,
            )
        )
    inputs = LoadedReportInputs(
        root=tmp_path,
        source_kind="runs_root",
        experiment_id="cost-partitions",
        config_hash=None,
        plan_hash=None,
        task_set_hash=None,
        planned_count=4,
        plan_items=[],
        index_records=[],
        valid_runs=runs,
        invalid_inputs=[],
        requested_k=[1],
        samples_per_task=1,
    )
    report = ReportBuilder().build_inputs(inputs)
    assert report.cost_accounting is not None
    assert report.cost_accounting.missing_value_count == 1
    assert report.cost_accounting.unknown_unit_count == 1
    assert report.cost_accounting.incompatible_unit_count == 2
    assert {(item.identifier, item.sum) for item in report.cost_accounting.partitions} == {
        ("EUR", 2.5),
        ("USD", 1.25),
    }
    assert report.cost_resolved.sum is None


class _Transport:
    def create_chat_completion(self, **kwargs: Any) -> Mapping[str, Any]:
        del kwargs
        return {
            "id": "response-1",
            "model": "provider-observed",
            "system_fingerprint": "provider-fingerprint",
            "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
            "usage": {},
        }


def test_remote_model_identity_is_observed_but_explicitly_mutable(tmp_path: Path) -> None:
    client = OpenAICompatibleModelClient(
        base_url="https://models.example.test/v1",
        model_id="requested-model",
        api_key="test-only",
        transport=_Transport(),
    )
    gateway = ModelGateway(
        run_id="identity",
        client=client,
        trace=TraceWriter(tmp_path / "trace.jsonl", "identity"),
        tracker=BudgetTracker(BudgetSpec(max_model_calls=1)),
        max_visible_bytes=1024,
    )
    request = gateway.create_request([ModelMessage(role="user", content="hello")])
    gateway.generate(request)
    identity = gateway.observations[0]
    assert identity.requested_model_id == "requested-model"
    assert identity.observed_provider_model_id == "provider-observed"
    assert identity.endpoint_origin == "https://models.example.test"
    assert identity.identity_confidence == "provider_observed"
    assert identity.reproducibility_scope == "mutable_remote_observation"
    assert identity.mutable_remote_service


def test_plan_bound_is_explicit_bounded_and_checked_before_output(tmp_path: Path) -> None:
    config = experiment_config(
        tmp_path / "must-not-exist",
        tasks=["and-gate-basic"],
        systems=[
            {"id": "first", "agent": {"id": "scripted"}},
            {"id": "second", "agent": {"id": "scripted"}},
        ],
        seeds=[0],
    )
    limited = config.model_copy(
        update={"execution": config.execution.model_copy(update={"max_plan_items": 1})}
    )
    with pytest.raises(ConfigurationError, match="max_plan_items=1"):
        ExperimentPlanner(offline_service()).build(limited)
    assert not config.output.root.exists()

    exact = config.model_copy(
        update={"execution": config.execution.model_copy(update={"max_plan_items": 2})}
    )
    assert len(ExperimentPlanner(offline_service()).build(exact).items) == 2
    with pytest.raises(ValidationError):
        ExperimentExecutionConfig.model_validate({"max_plan_items": 100_001})


class _DummyPlugin:
    def __init__(self, name: str) -> None:
        self.descriptor = PluginDescriptor(
            name=name,
            version="1.0.0",
            api_version="1.0",
            provider="fixture",
        )


class _Distribution:
    metadata = {"Name": "external-fixture"}
    version = "2.3.4"


class _EntryPoint:
    dist = _Distribution()

    def __init__(self, name: str, value: str, loaded: Any) -> None:
        self.name = name
        self.value = value
        self._loaded = loaded

    def load(self) -> Any:
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


class _EntryPoints(list[_EntryPoint]):
    def select(self, *, group: str) -> _EntryPoints:
        assert group == "tests.plugins"
        return self


def test_plugin_import_failures_are_isolated_and_origin_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_points = _EntryPoints(
        [
            _EntryPoint("broken", "broken.module:plugin", ImportError("unsafe detail")),
            _EntryPoint("working", "working.module:plugin", _DummyPlugin("external-good")),
        ]
    )
    monkeypatch.setattr("verigym.registry.base.metadata.entry_points", lambda: entry_points)
    registry: PluginRegistry[_DummyPlugin] = PluginRegistry("tests.plugins")
    registry.discover()
    assert registry.names() == ["external-good"]
    assert registry.origin("external-good").package == "external-fixture"
    diagnostics = registry.diagnostics()
    assert [item.status for item in diagnostics] == ["rejected", "loaded"]
    assert "unsafe detail" not in diagnostics[0].message
