from __future__ import annotations

from pathlib import Path

from verigym.agents.base import AgentAdapter, AgentContext
from verigym.api import ReportService, RunConfig, VeriGym, build_registries
from verigym.core.replay import replay_run
from verigym.core.trace import read_trace
from verigym.models.static import StaticModelClient
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentAction,
    AgentDescriptor,
    ApplyPatchAction,
    EpisodeResult,
    FinalSubmissionAction,
    InteractionMode,
    Observation,
    SuiteSourceConfig,
    ToolCallAction,
)

from verigym_rtl_repo import RtlRepoScoreTool, RtlRepoSuite
from verigym_rtl_repo.dataset import AGENT_EVAL_VARIANT, VARIANT


class _RtlRepoAgentEvalFixtureAgent(AgentAdapter):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="rtl-repo-agent-eval-fixture",
        version="1.0.0",
        api_version=PLUGIN_API_VERSION,
        provider="tests",
        capabilities=["deterministic", "agent_eval_fixture"],
    )

    def __init__(self) -> None:
        self._actions: list[AgentAction] = []

    def start(self, context: AgentContext) -> None:
        assert context.agent_feedback_contract is not None
        assert context.agent_feedback_contract.compile_test_id is None
        self._actions = [
            ApplyPatchAction(
                patch="""--- a/repository/completion.txt
+++ b/repository/completion.txt
@@ -0,0 +1 @@
+assign y = a & b;
"""
            ),
            ToolCallAction(tool="file.diff", arguments={}),
            FinalSubmissionAction(message="fixture complete"),
        ]

    def act(self, observation: Observation) -> AgentAction:
        del observation
        return self._actions.pop(0)

    def finish(self, result: EpisodeResult) -> None:
        del result


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


def test_instructional_line_completion_is_explicit_and_keeps_raw_user_prompt(
    synthetic_source: Path,
    tmp_path: Path,
) -> None:
    registries = build_registries(discover_external=False)
    registries.suites.register(RtlRepoSuite())
    registries.tools.register(RtlRepoScoreTool())
    registries.models.register(
        StaticModelClient(
            name="rtl-repo-static-instructional",
            responses=["assign y = a & b;"],
        )
    )
    result = VeriGym(registries).run(
        RunConfig(
            task_id=f"rtl-repo/{VARIANT}/test-000000",
            mode=InteractionMode.CHAT,
            agent="single-turn",
            agent_options={"line_completion_prompt": "instructional-v1"},
            model="rtl-repo-static-instructional",
            suite_source=SuiteSourceConfig(source_root=synthetic_source, variant=VARIANT),
            runtime="local",
            output=tmp_path / "instructional-run",
        )
    )
    trace = read_trace(result.run_dir / "trace.jsonl", expected_run_id=result.manifest.run_id)
    request_event = next(event for event in trace if event.event_type == "model_request")
    messages = request_event.payload["request"]["messages"]

    assert result.scorecard.resolved
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "Return exactly the single source-code line" in messages[0]["content"]
    assert messages[1]["content"].startswith("// Repo Name: verigym/synthetic-rtl\n")


def test_agent_eval_projection_multiturn_hidden_score_and_replay(
    synthetic_source: Path,
    tmp_path: Path,
) -> None:
    registries = build_registries(discover_external=False)
    registries.suites.register(RtlRepoSuite())
    registries.tools.register(RtlRepoScoreTool())
    registries.agents.register(_RtlRepoAgentEvalFixtureAgent())
    service = VeriGym(registries)
    result = service.run(
        RunConfig(
            task_id=f"rtl-repo/{AGENT_EVAL_VARIANT}/test-000000",
            mode=InteractionMode.AGENT,
            agent="rtl-repo-agent-eval-fixture",
            suite_source=SuiteSourceConfig(
                source_root=synthetic_source,
                variant=AGENT_EVAL_VARIANT,
            ),
            runtime="local",
            output=tmp_path / "agent-eval",
        )
    )

    assert result.scorecard.resolved
    assert result.manifest.agent_feedback_contract is not None
    assert result.manifest.agent_feedback_contract.public_test_ids == []
    assert result.manifest.agent_feedback_evaluations == []
    replay = replay_run(result.run_dir, verify=True, service=service)
    assert replay.reverified_resolved is True
