from __future__ import annotations

import csv
import json
import shutil
from io import StringIO
from pathlib import Path

import pytest

import verigym.public_test_launcher as public_launcher
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.reporting.service import ReportService
from verigym.runtimes.local import LocalRuntimeSession
from verigym.schemas.run import RunConfig
from verigym.schemas.tool import CompletedCommand

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_iverilog,
    pytest.mark.skipif(
        shutil.which("iverilog") is None or shutil.which("vvp") is None,
        reason="Icarus Verilog is not installed",
    ),
]

TASKS = [
    "repo-rtl/arbiter-reset-recovery",
    "repo-rtl/counter-wrap",
    "repo-rtl/pipeline-stall-backpressure",
]


@pytest.fixture(autouse=True)
def _local_icarus_path(monkeypatch: pytest.MonkeyPatch) -> None:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    assert iverilog is not None and vvp is not None
    paths = sorted({str(Path(iverilog).parent), str(Path(vvp).parent)})
    monkeypatch.setattr(
        public_launcher,
        "TOOLCHAIN_PATH",
        ":".join([*paths, "/usr/local/bin", "/usr/bin", "/bin"]),
    )


def _service() -> VeriGym:
    return VeriGym()


def _config(output: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "schema_version": "1.0",
            "name": "Milestone 10A zero-model repository matrix",
            "suite": {
                "id": "repo-rtl",
                "tasks": {"include": TASKS, "exclude": []},
            },
            "runs": {
                "mode": "agent",
                "seeds": [0],
                "samples_per_task": 1,
                "pass_k": [1],
            },
            "systems": [
                {"id": "scripted-good", "agent": {"id": "repo-scripted-good"}},
                {"id": "scripted-bad", "agent": {"id": "repo-scripted-bad"}},
                {
                    "id": "scripted-policy-bad",
                    "agent": {"id": "repo-scripted-policy-bad"},
                },
            ],
            "runtime": {"id": "local"},
            "execution": {
                "max_workers": 1,
                "continue_on_infrastructure_error": True,
            },
            "output": {"root": output},
        }
    )


@pytest.mark.conformance
def test_scripted_good_bad_and_policy_bad_matrix(tmp_path: Path) -> None:
    service = _service()
    for task_id in TASKS:
        good = service.run(
            RunConfig(
                task_id=task_id,
                agent="repo-scripted-good",
                runtime="local",
                output=tmp_path / "good",
            )
        )
        assert good.scorecard.resolved
        assert good.manifest.repository_candidate is not None
        assert good.manifest.repository_candidate.patch.reapply_exact
        assert all(outcome.passed for outcome in good.manifest.repository_public_tests)
        assert all(
            outcome.network_policy == "host_local_trusted" and not outcome.public_assets_read_only
            for outcome in good.manifest.repository_public_tests
        )
        assert good.manifest.repository_public_tool_invocation_count == 2
        assert verify_artifact_manifest(good.run_dir, expected_scope="run").status == "verified"
        replay = replay_run(good.run_dir, verify=True, service=_service())
        assert replay.reverified_resolved is True

        bad = service.run(
            RunConfig(
                task_id=task_id,
                agent="repo-scripted-bad",
                runtime="local",
                output=tmp_path / "bad",
            )
        )
        assert not bad.scorecard.resolved
        assert not bad.scorecard.correctness.infrastructure_error
        assert bad.manifest.repository_candidate is not None
        replay_run(bad.run_dir, service=_service())

        policy = service.run(
            RunConfig(
                task_id=task_id,
                agent="repo-scripted-policy-bad",
                runtime="local",
                output=tmp_path / "policy",
            )
        )
        assert not policy.scorecard.resolved
        assert not policy.scorecard.correctness.infrastructure_error
        assert policy.scorecard.failure is not None
        assert policy.scorecard.failure.kind == "policy"
        assert policy.manifest.repository_candidate is not None
        assert policy.manifest.repository_candidate.patch.changed_files == []
        replay_run(policy.run_dir, service=_service())


def test_generic_plan_batch_report_resume_and_replay(tmp_path: Path) -> None:
    output = tmp_path / "experiment"
    planner = ExperimentPlanner()
    plan = planner.build(_config(output))
    assert len(plan.items) == 9
    assert all(item.repository_task_identity is not None for item in plan.items)
    assert all(
        item.repository_task_identity.task_bundle_hash
        for item in plan.items
        if item.repository_task_identity
    )
    result = BatchRunner(planner=planner).run(plan)
    assert result.state.planned_count == 9
    assert result.state.valid_terminal_count == 9
    assert result.state.infrastructure_error_count == 0

    reports = ReportService().generate_all(
        output,
        output_dir=output / "repository-reports",
        group_by=("task", "agent"),
    )
    aggregate = json.loads(reports.aggregate_path.read_text(encoding="utf-8"))
    repository = aggregate["metadata"]["repository_repair"]
    assert repository["denominators"]["planned"] == 9
    assert repository["denominators"]["terminal"] == 9
    assert repository["denominators"]["evaluable"] == 9
    assert repository["denominators"]["infrastructure_failure"] == 0
    rows = list(csv.DictReader(StringIO(reports.csv_path.read_text(encoding="utf-8"))))
    assert len(rows) == 9
    assert "repository_patch_hash" in rows[0]
    assert "public_tests_passed" in rows[0]
    assert {row["public_tool_invocation_count"] for row in rows} == {"1", "2"}

    before = (output / "run_index.jsonl").read_bytes()
    resumed = BatchRunner(planner=planner).resume(output)
    assert resumed.state.valid_terminal_count == 9
    assert (output / "run_index.jsonl").read_bytes() == before
    for row in rows:
        replay_run(output / row["relative_run_path"], service=_service())


def test_public_launcher_platform_failure_is_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_public_test(
        session: LocalRuntimeSession,
        test_id: str,
    ) -> CompletedCommand:
        session._public_test_invocation_count += 1  # noqa: SLF001 - failure fixture
        return CompletedCommand(
            argv=["verigym-public-test", "run", test_id],
            cwd=".",
            exit_code=None,
            error="synthetic trusted-launcher failure",
            failure_reason="public_test_contract",
            failure_origin="control_plane",
            runtime_role="agent",
            metadata={
                "public_test_protocol": "verigym_public_test_v1",
                "network_policy": "host_local_trusted",
                "public_assets_read_only": False,
            },
        )

    monkeypatch.setattr(LocalRuntimeSession, "execute_public_test", fail_public_test)
    result = _service().run(
        RunConfig(
            task_id="repo-rtl/counter-wrap",
            agent="repo-scripted-good",
            runtime="local",
            output=tmp_path / "platform-failure",
        )
    )
    assert result.scorecard.status == "error"
    assert result.scorecard.correctness.infrastructure_error
    assert result.scorecard.failure is not None
    assert result.scorecard.failure.category == "repository_public_test_sandbox_error"
