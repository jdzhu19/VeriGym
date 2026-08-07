from __future__ import annotations

from pathlib import Path

from verigym.api import ReportService, RunConfig, VeriGym, build_registries
from verigym.core.trace import read_trace
from verigym.models.static import StaticModelClient
from verigym.plugin_api import InteractionMode, SuiteSourceConfig

from verigym_rtl_repo import RtlRepoScoreTool, RtlRepoSuite
from verigym_rtl_repo.dataset import VARIANT


def test_one_synthetic_task_runs_and_reports_native_metrics(
    synthetic_source: Path,
    tmp_path: Path,
) -> None:
    registries = build_registries(discover_external=False)
    registries.suites.register(RtlRepoSuite())
    registries.tools.register(RtlRepoScoreTool())
    registries.models.register(
        StaticModelClient(
            name="rtl-repo-static-exact",
            responses=["// explanation\nassign y = a & b;\nignored"],
        )
    )
    output = tmp_path / "run"
    result = VeriGym(registries).run(
        RunConfig(
            task_id=f"rtl-repo/{VARIANT}/test-000000",
            mode=InteractionMode.CHAT,
            agent="single-turn",
            model="rtl-repo-static-exact",
            suite_source=SuiteSourceConfig(source_root=synthetic_source, variant=VARIANT),
            runtime="local",
            output=output,
        )
    )
    reports = ReportService().generate_all(output)
    partitions = reports.aggregate.metadata["benchmark_metric_partitions"]
    trace = read_trace(result.run_dir / "trace.jsonl", expected_run_id=result.manifest.run_id)
    request_event = next(event for event in trace if event.event_type == "model_request")
    messages = request_event.payload["request"]["messages"]

    assert result.scorecard.resolved
    assert result.scorecard.patch.edit_similarity == 100.0
    assert result.scorecard.efficiency.model_calls == 1
    assert messages == [
        {
            "role": "user",
            "content": (
                "// Repo Name: verigym/synthetic-rtl\n"
                "// Path: rtl/helper.v\n"
                "module helper;\n"
                "endmodule\n\n\n"
                "// Path: rtl/test_10.v\n"
                "module demo(input a, input b, output y);\n\n"
            ),
        }
    ]
    assert len(partitions) == 1
    dimensions = partitions[0]["dimensions"]
    assert dimensions["suite"] == "rtl-repo"
    assert dimensions["suite_version"] == "rtl-repo-official-full-context-compat-1"
    assert dimensions["profile_id"] == "rtl_repo_official_v1"
    assert dimensions["split"] == "test"
    assert dimensions["dataset_content_hash"]
    assert dimensions["metric_units"] == {
        "edit_similarity": "percent",
        "exact_match": "percent",
    }
    assert partitions[0]["metrics"]["exact_match"]["mean"] == 100.0
    assert "Benchmark-native metric partitions" in reports.markdown_path.read_text(encoding="utf-8")
    assert "edit_similarity" in reports.csv_path.read_text(encoding="utf-8").splitlines()[0]
