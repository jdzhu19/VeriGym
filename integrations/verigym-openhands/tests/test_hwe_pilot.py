from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from verigym.core.hashing import content_hash
from verigym.evolution.memory import validate_agent_version

from verigym_openhands import hwe_pilot
from verigym_openhands.hwe_pilot import (
    OPENHANDS_HWE_NEW_TASKS,
    OPENHANDS_HWE_PILOT_TASKS,
    OPENHANDS_HWE_PREDECESSOR_TASK,
    build_pilot_agent_version,
    load_predecessor_qualification,
    seal_campaign_report,
    validate_pilot_split,
)


def _split(*, move_to_heldout: str | None = None) -> Any:
    training = [
        SimpleNamespace(task_id=task_id)
        for task_id in OPENHANDS_HWE_PILOT_TASKS
        if task_id != move_to_heldout
    ]
    heldout = [SimpleNamespace(task_id=move_to_heldout)] if move_to_heldout else []
    return SimpleNamespace(training=training, validation=[], heldout=heldout)


def _locks() -> dict[str, Any]:
    return {
        task_id: SimpleNamespace(
            task_id=task_id,
            lock_hash=f"{index + 1:064x}",
            derived_agent_image_id=f"sha256:{index + 11:064x}",
            verifier_base_image_id=f"sha256:{index + 21:064x}",
        )
        for index, task_id in enumerate(OPENHANDS_HWE_NEW_TASKS)
    }


def test_five_task_selection_is_training_only_and_nonrepeating() -> None:
    assert len(OPENHANDS_HWE_PILOT_TASKS) == 5
    assert len(set(OPENHANDS_HWE_PILOT_TASKS)) == 5
    assert len(OPENHANDS_HWE_NEW_TASKS) == 4
    assert OPENHANDS_HWE_PREDECESSOR_TASK not in OPENHANDS_HWE_NEW_TASKS
    validate_pilot_split(_split())

    with pytest.raises(ValueError, match="absent from the frozen training split"):
        validate_pilot_split(_split(move_to_heldout=OPENHANDS_HWE_PILOT_TASKS[0]))


def test_pilot_agent_version_binds_all_four_task_images() -> None:
    version = build_pilot_agent_version(source_commit="a" * 40, image_locks=_locks())

    assert validate_agent_version(version) == version
    assert version.model_id == "openai/deepseek-v4-flash"
    assert version.reasoning_effort == "thinking-disabled"
    assert len(version.image_hashes) == 8
    assert version.training_dataset_hash is None
    assert version.model_weights_modified is False

    changed = _locks()
    changed.pop(OPENHANDS_HWE_NEW_TASKS[-1])
    with pytest.raises(ValueError, match="exactly four image locks"):
        build_pilot_agent_version(source_commit="a" * 40, image_locks=changed)


def test_predecessor_qualification_is_hash_and_eligibility_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "openhands-deepseek-v4-flash-training-pr2944-s484-attempt16-local"
    trajectory_path = (
        tmp_path / "runs" / run_id / "artifacts" / "openhands_sdk" / "training-trajectory.json"
    )
    trajectory_path.parent.mkdir(parents=True)
    trajectory_path.write_text("{}", encoding="utf-8")
    base = {
        "format_id": "verigym_openhands_hwe_single_trajectory_qualification_v1",
        "status": "passed",
        "source_commit": "3e0cc0a22f7005ba8b4573b80b08b1f46971ed3f",
        "task_id": OPENHANDS_HWE_PREDECESSOR_TASK,
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "candidate_hash": "3" * 64,
        "verifier_hash": "4" * 64,
        "model_transport_id": "openai/deepseek-v4-flash",
        "model_identity": "deepseek-v4-flash",
        "openhands_sdk_version": "1.42.1",
        "seed": 484,
        "max_context_tokens": 65_536,
        "max_output_tokens": 2_048,
        "truncation": "error",
        "truncation_applied": False,
        "infrastructure_valid": True,
        "ordinary_verifier_resolved": True,
        "trajectory_sft_eligible": True,
        "trajectory_file_sha256": (
            "ccc8bbf307b5cd674a39161475f428201c9bbc77ac85f5e78e948ccc25d56771"
        ),
        "trajectory_hash": ("7ed148bf5e206d214d7abfdd5612275283e1e2e0643c8b8df3d5dcd5107c7416"),
        "run_id": run_id,
    }
    report = {**base, "report_hash": content_hash(base)}
    (tmp_path / "qualification-report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        hwe_pilot,
        "hash_bytes",
        lambda _payload: base["trajectory_file_sha256"],
    )
    monkeypatch.setattr(
        hwe_pilot,
        "validate_openhands_training_trajectory",
        lambda _value: {
            "task_id": OPENHANDS_HWE_PREDECESSOR_TASK,
            "transcript_hash": base["trajectory_hash"],
            "verifier_resolved": True,
            "sft_eligible": True,
        },
    )

    predecessor = load_predecessor_qualification(tmp_path)

    assert predecessor.report_hash == report["report_hash"]
    assert predecessor.trajectory_path == trajectory_path
    report["ordinary_verifier_resolved"] = False
    (tmp_path / "qualification-report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="report identity changed"):
        load_predecessor_qualification(tmp_path)


def test_campaign_report_seal_detects_drift() -> None:
    report = seal_campaign_report(
        {
            "format_id": "verigym_openhands_hwe_five_task_campaign_report_v1",
            "status": "pilot_running",
            "optimizer_steps": 0,
        }
    )
    expected = report.pop("report_hash")
    assert content_hash(report) == expected


def test_pilot_cli_statically_forbids_retry_training_and_gpu() -> None:
    source = (
        Path(__file__).parents[3] / "scripts" / "collect_cva6_hwe_openhands_pilot.py"
    ).read_text(encoding="utf-8")

    assert '"whole_episode_retries": 0' in source
    assert '"provider_request_retries": 0' in source
    assert '"optimizer_steps": 0' in source
    assert '"hpc_jobs_submitted": False' in source
    assert '"gpu_seconds": 0' in source
    assert "dry_run_decision_record_v4" in source
    assert "dry_run_decision_record," not in source
    assert 'return "model_rejected", str(failure.category)' in source
    assert '"accounting_available": accounting_available' in source
    assert "optimizer.step" not in source
    assert "bsub" not in source
