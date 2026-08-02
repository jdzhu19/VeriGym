from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import verigym.public_test_launcher as public_launcher
from verigym.core.integrity import verify_artifact_manifest
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.schemas.run import RunConfig

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_iverilog,
    pytest.mark.skipif(
        shutil.which("iverilog") is None or shutil.which("vvp") is None,
        reason="Icarus Verilog is not installed",
    ),
]

TASKS = [
    "repo-api-protocol/protocol-dual-fix",
    "repo-api-protocol/protocol-pipeline-flush",
    "repo-api-protocol/protocol-valid-hold",
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


@pytest.mark.conformance
@pytest.mark.parametrize("task_id", TASKS)
def test_protocol_tasks_scripted_good_bad_and_policy_bad(task_id: str, tmp_path: Path) -> None:
    service = VeriGym()
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
    assert verify_artifact_manifest(good.run_dir, expected_scope="run").status == "verified"
    assert replay_run(good.run_dir, verify=True, service=VeriGym()).reverified_resolved is True

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
    replay_run(bad.run_dir, service=VeriGym())

    policy = service.run(
        RunConfig(
            task_id=task_id,
            agent="repo-scripted-policy-bad",
            runtime="local",
            output=tmp_path / "policy",
        )
    )
    assert not policy.scorecard.resolved
    assert policy.scorecard.failure is not None
    assert policy.scorecard.failure.kind == "policy"
    assert not policy.scorecard.correctness.infrastructure_error
    replay_run(policy.run_dir, service=VeriGym())
