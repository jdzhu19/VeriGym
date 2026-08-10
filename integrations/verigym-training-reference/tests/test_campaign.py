from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError
from verigym.core.errors import ConfigurationError

from verigym_training_reference.campaign import (
    CampaignStageSpec,
    TrainingCampaignSpec,
    run_training_campaign,
)


def _stage(stage_id: str, output: str, depends_on: list[str] | None = None) -> CampaignStageSpec:
    script = (
        "from pathlib import Path; "
        f"p=Path({output!r}); p.parent.mkdir(parents=True,exist_ok=True); "
        f"p.write_text({stage_id!r},encoding='utf-8')"
    )
    return CampaignStageSpec(
        stage_id=stage_id,
        argv=[sys.executable, "-c", script],
        depends_on=depends_on or [],
        expected_outputs=[output],
        working_directory="workspace",
    )


def _spec() -> TrainingCampaignSpec:
    return TrainingCampaignSpec(
        format_id="verigym_external_training_campaign_v1",
        campaign_id="fixture",
        stages=[
            _stage("rollout", "rollout/data.json"),
            _stage("score", "score/data.json", ["rollout"]),
        ],
        max_parallel_stages=2,
        max_workspace_bytes=1024 * 1024,
    )


def test_campaign_executes_and_resumes_hash_bound_stages(tmp_path: Path) -> None:
    report = run_training_campaign(spec=_spec(), workspace=tmp_path, repository=tmp_path)
    assert report["status"] == "completed"
    receipt = tmp_path / ".campaign" / "receipts" / "rollout.json"
    before = receipt.read_bytes()
    resumed = run_training_campaign(spec=_spec(), workspace=tmp_path, repository=tmp_path)
    assert resumed["report_hash"] == report["report_hash"]
    assert receipt.read_bytes() == before
    state = json.loads((tmp_path / ".campaign" / "states" / "rollout.json").read_text())
    assert state["status"] == "completed"
    assert state["exit_code"] == 0


def test_campaign_rejects_mutated_completed_output(tmp_path: Path) -> None:
    run_training_campaign(spec=_spec(), workspace=tmp_path, repository=tmp_path)
    (tmp_path / "rollout" / "data.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="output changed"):
        run_training_campaign(spec=_spec(), workspace=tmp_path, repository=tmp_path)


def test_campaign_does_not_inherit_credentials(tmp_path: Path) -> None:
    stage = CampaignStageSpec(
        stage_id="env",
        argv=[
            sys.executable,
            "-c",
            "import json,os; from pathlib import Path; "
            "Path('env.json').write_text(json.dumps(dict(os.environ)))",
        ],
        expected_outputs=["env.json"],
        working_directory="workspace",
    )
    spec = TrainingCampaignSpec(
        format_id="verigym_external_training_campaign_v1",
        campaign_id="environment-fixture",
        stages=[stage],
    )
    run_training_campaign(
        spec=spec,
        workspace=tmp_path,
        repository=tmp_path,
        host_environment={"PATH": "/bin", "PROVIDER_API_KEY": "do-not-inherit"},
    )
    environment = json.loads((tmp_path / "env.json").read_text(encoding="utf-8"))
    assert "PROVIDER_API_KEY" not in environment


def test_campaign_rejects_cycles_and_credential_environment() -> None:
    with pytest.raises(ValidationError, match="credential-like"):
        CampaignStageSpec(
            stage_id="bad",
            argv=["python", "worker.py"],
            expected_outputs=["result.json"],
            environment={"API_TOKEN": "secret"},
        )
    with pytest.raises(ValidationError, match="cycle"):
        TrainingCampaignSpec(
            format_id="verigym_external_training_campaign_v1",
            campaign_id="cycle",
            stages=[
                _stage("a", "a.json", ["b"]),
                _stage("b", "b.json", ["a"]),
            ],
        )


def test_campaign_records_failed_stage_without_waiting_for_stage_timeout(tmp_path: Path) -> None:
    stage = CampaignStageSpec(
        stage_id="fail-fast",
        argv=[sys.executable, "-c", "raise SystemExit(7)"],
        expected_outputs=["never-created.json"],
        working_directory="workspace",
        timeout_s=60,
    )
    spec = TrainingCampaignSpec(
        format_id="verigym_external_training_campaign_v1",
        campaign_id="fail-fast-fixture",
        stages=[stage],
    )

    started = time.monotonic()
    with pytest.raises(ConfigurationError, match="stage command failed"):
        run_training_campaign(spec=spec, workspace=tmp_path, repository=tmp_path)
    assert time.monotonic() - started < 5
    state = json.loads((tmp_path / ".campaign" / "states" / "fail-fast.json").read_text())
    assert state["status"] == "failed"
    assert state["exit_code"] == 7


def test_campaign_terminates_stage_when_fatal_log_marker_appears(tmp_path: Path) -> None:
    marker = "fatal worker fixture"
    stage = CampaignStageSpec(
        stage_id="fatal-log",
        argv=[
            sys.executable,
            "-c",
            f"import time; print({marker!r}, flush=True); time.sleep(60)",
        ],
        expected_outputs=["never-created.json"],
        working_directory="workspace",
        timeout_s=60,
        fatal_log_markers=[marker],
    )
    spec = TrainingCampaignSpec(
        format_id="verigym_external_training_campaign_v1",
        campaign_id="fatal-log-fixture",
        stages=[stage],
    )

    started = time.monotonic()
    with pytest.raises(ConfigurationError, match="fatal log marker detected"):
        run_training_campaign(spec=spec, workspace=tmp_path, repository=tmp_path)
    assert time.monotonic() - started < 5
    state = json.loads((tmp_path / ".campaign" / "states" / "fatal-log.json").read_text())
    receipt = json.loads((tmp_path / ".campaign" / "receipts" / "fatal-log.json").read_text())
    assert state["status"] == "failed"
    assert state["failure_reason"] == "fatal_log_marker"
    assert state["fatal_log_marker"] == marker
    assert receipt["failure_reason"] == "fatal_log_marker"
    assert receipt["fatal_log_marker"] == marker
