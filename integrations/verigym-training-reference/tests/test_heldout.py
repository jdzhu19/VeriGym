from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.schemas.evolution import TaskSplitEntry

from verigym_training_reference.heldout import summarize_heldout_results

HASHES = [f"{index:x}" * 64 for index in range(1, 8)]


def _split(path: Path) -> None:
    base = {
        "schema_version": "1.0",
        "split_id": "heldout-fixture",
        "training": [
            {
                "task_id": "suite/train/task",
                "source_hash": HASHES[0],
                "task_hash": HASHES[1],
                "license": "MIT",
                "attribution": "fixture",
            }
        ],
        "validation": [],
        "heldout": [
            {
                "task_id": "suite/variant/heldout",
                "source_hash": HASHES[2],
                "task_hash": HASHES[3],
                "license": "MIT",
                "attribution": "fixture",
            }
        ],
        "heldout_assets_loaded_after_version_hash": HASHES[4],
    }
    path.write_text(json.dumps({**base, "manifest_hash": content_hash(base)}), encoding="utf-8")


def _scorecard(path: Path, *, resolved: bool, infrastructure: bool = False) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "task_id": "suite/variant/heldout",
                "status": "error" if infrastructure else "completed",
                "resolved": resolved,
                "correctness": {
                    "compile_status": "passed" if resolved else "failed",
                    "infrastructure_error": infrastructure,
                },
                "efficiency": {"wall_time_s": 2.0},
            }
        ),
        encoding="utf-8",
    )


def test_task_split_entry_accepts_nested_canonical_task_ids() -> None:
    entry = TaskSplitEntry(
        task_id="verilog-eval-code-complete/v2-code-complete-iccad2023/Prob014_andgate",
        source_hash=HASHES[0],
        task_hash=HASHES[1],
        license="MIT",
        attribution="fixture",
    )
    assert entry.task_id.endswith("Prob014_andgate")


def test_summarize_heldout_preserves_infrastructure_invalid_samples(tmp_path: Path) -> None:
    split = tmp_path / "split.json"
    _split(split)
    policy = tmp_path / "policy"
    _scorecard(policy / "task" / "runs" / "run-0" / "scorecard.json", resolved=True)
    _scorecard(
        policy / "task" / "runs" / "run-1" / "scorecard.json",
        resolved=False,
        infrastructure=True,
    )
    report = summarize_heldout_results(
        split=split,
        policy_roots={"v1": policy},
        output=tmp_path / "report.json",
    )
    summary = report["policies"][0]
    assert summary["valid_sample_count"] == 1
    assert summary["infrastructure_invalid_count"] == 1
    assert summary["resolved_rate"] == 1.0


def test_summarize_heldout_rejects_incomplete_task_coverage(tmp_path: Path) -> None:
    split = tmp_path / "split.json"
    _split(split)
    policy = tmp_path / "policy"
    policy.mkdir()
    with pytest.raises(ConfigurationError, match="no scorecards"):
        summarize_heldout_results(
            split=split,
            policy_roots={"v1": policy},
            output=tmp_path / "report.json",
        )
