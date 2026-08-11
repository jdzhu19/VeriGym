from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.memory import build_agent_version
from verigym.schemas.evolution import TaskSplitEntry
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite

from verigym_training_reference import heldout
from verigym_training_reference.heldout import (
    RepositoryHeldoutRequest,
    freeze_repository_heldout,
    load_repository_heldout_freeze,
    summarize_heldout_results,
)

HASHES = [f"{index:x}" * 64 for index in range(1, 8)]


def _agent_version(path: Path) -> None:
    version = build_agent_version(
        agent_version_id="codex-luna-max-hwe-heldout-v1",
        update_type="none",
        executable_in_m10b=True,
        base_agent_id="codex-cli-agent",
        agent_descriptor_hash="1" * 64,
        model_id="gpt-5.6-luna",
        reasoning_effort="max",
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        runtime_identity_hash="2" * 64,
        tool_policy_hash="3" * 64,
        prompt_contract_hash="4" * 64,
        source_commit="5" * 40,
        package_hashes={"verigym": "6" * 64},
        image_hashes={"agent": "7" * 64, "verifier": "8" * 64},
    )
    path.write_text(version.model_dump_json(indent=2), encoding="utf-8")


def _repository_tasks() -> dict[str, object]:
    suite = RepositoryRtlSuite()
    base = suite.load_task(next(iter(suite.discover())))
    return {
        task_id: base.model_copy(
            update={
                "id": task_id,
                "description": f"private description {index}",
                "source": base.source.model_copy(
                    update={
                        "kind": "repository",
                        "content_hash": f"{index:x}" * 64,
                        "license": "Apache-2.0",
                        "attribution": "fixture",
                    }
                ),
            },
            deep=True,
        )
        for index, task_id in enumerate(("fixture/repository-one", "fixture/repository-two"), 1)
    }


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


def test_freeze_repository_heldout_exports_only_hash_bound_manifests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tasks = _repository_tasks()

    class FakeService:
        def __init__(self, _registries: object) -> None:
            pass

        def load_task(self, task_id: str, _source: object) -> tuple[object, object, object]:
            return object(), tasks[task_id], object()

    monkeypatch.setattr(heldout, "build_registries", lambda: object())
    monkeypatch.setattr(heldout, "VeriGym", FakeService)
    sources = [tmp_path / "source-one", tmp_path / "source-two"]
    for source in sources:
        source.mkdir()
    agent = tmp_path / "agent-version.json"
    _agent_version(agent)
    output = tmp_path / "freeze"

    manifest = freeze_repository_heldout(
        split_id="hwe-repo-heldout-v1",
        requests=[
            RepositoryHeldoutRequest(source=source, task_id=task_id)
            for source, task_id in zip(sources, tasks, strict=True)
        ],
        variant="repo-repair-v1",
        agent_version_path=agent,
        output=output,
    )
    reloaded, split = load_repository_heldout_freeze(output)

    assert reloaded == manifest
    assert split.manifest_hash == manifest.split_manifest_hash
    assert not split.training
    assert [item.task_id for item in manifest.tasks] == sorted(tasks)
    assert {path.name for path in output.iterdir()} == {
        "repository-heldout-freeze.json",
        "task-split.json",
    }
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert "private description" not in serialized
    assert str(tmp_path) not in serialized


def test_repository_heldout_rejects_tampered_split(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tasks = _repository_tasks()

    class FakeService:
        def __init__(self, _registries: object) -> None:
            pass

        def load_task(self, task_id: str, _source: object) -> tuple[object, object, object]:
            return object(), tasks[task_id], object()

    monkeypatch.setattr(heldout, "build_registries", lambda: object())
    monkeypatch.setattr(heldout, "VeriGym", FakeService)
    source = tmp_path / "source"
    source.mkdir()
    agent = tmp_path / "agent-version.json"
    _agent_version(agent)
    output = tmp_path / "freeze"
    freeze_repository_heldout(
        split_id="hwe-repo-heldout-v1",
        requests=[RepositoryHeldoutRequest(source=source, task_id=next(iter(tasks)))],
        variant="repo-repair-v1",
        agent_version_path=agent,
        output=output,
    )
    split_path = output / "task-split.json"
    value = json.loads(split_path.read_text(encoding="utf-8"))
    value["heldout"][0]["source_hash"] = "f" * 64
    split_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid repository held-out freeze"):
        load_repository_heldout_freeze(output)
