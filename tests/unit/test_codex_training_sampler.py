from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from verigym.core.hashing import content_hash
from verigym.evolution.memory import build_agent_version
from verigym.evolution.splits import build_task_split
from verigym.schemas.evolution import TaskSplitEntry

_SCRIPT = Path(__file__).parents[2] / "scripts" / "run_codex_training_sampler.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT))
_task_requests = cast(Any, _NAMESPACE["_task_requests"])
_summary = cast(Any, _NAMESPACE["_summary"])
_run = cast(Any, _NAMESPACE["_run"])
_heldout_binding = cast(Any, _NAMESPACE["_heldout_binding"])
_suite_verifier_images = cast(Any, _NAMESPACE["_suite_verifier_images"])


def _heldout_files(
    tmp_path: Path,
    *,
    suite_verifier_image: str | None = None,
) -> tuple[Path, Path, list[dict[str, object]]]:
    heldout = pytest.importorskip("verigym_training_reference.heldout")
    agent_image = "a" * 64
    verifier_image = "b" * 64
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
        image_hashes={
            "agent": agent_image,
            "verifier": verifier_image,
            **(
                {
                    "suite-verifier:hwe-bench/repo-repair-v1/fixture:run_hidden_regression": (
                        suite_verifier_image
                    )
                }
                if suite_verifier_image is not None
                else {}
            ),
        },
    )
    agent_path = tmp_path / "agent-version.json"
    agent_path.write_text(version.model_dump_json(indent=2), encoding="utf-8")
    entry = TaskSplitEntry(
        task_id="hwe-bench/repo-repair-v1/fixture",
        source_hash="7" * 64,
        task_hash="8" * 64,
        license="Apache-2.0",
        attribution="fixture",
    )
    split = build_task_split(
        split_id="hwe-repo-heldout-v1",
        training=[],
        heldout=[entry],
        heldout_assets_loaded_after_version_hash=version.version_hash,
    )
    task = heldout.RepositoryHeldoutTaskIdentity(
        task_id=entry.task_id,
        task_hash=entry.task_hash,
        source_hash=entry.source_hash,
    )
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_repository_heldout_freeze_v1",
        "split_id": split.split_id,
        "tasks": [task.model_dump(mode="json")],
        "split_manifest_hash": split.manifest_hash,
        "agent_version_hash": version.version_hash,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "public_source_contents_exported": False,
        "sample_eligible_for_training": False,
    }
    freeze = heldout.RepositoryHeldoutFreezeManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )
    freeze_root = tmp_path / "freeze"
    freeze_root.mkdir()
    (freeze_root / "task-split.json").write_text(split.model_dump_json(indent=2), encoding="utf-8")
    (freeze_root / "repository-heldout-freeze.json").write_text(
        freeze.model_dump_json(indent=2), encoding="utf-8"
    )
    records: list[dict[str, object]] = [
        {
            "task_id": entry.task_id,
            "task_hash": entry.task_hash,
            "source_hash": entry.source_hash,
            "suite_verifier_images": (
                {"run_hidden_regression": suite_verifier_image}
                if suite_verifier_image is not None
                else {}
            ),
        }
    ]
    return freeze_root, agent_path, records


def test_multi_source_task_requests_are_ordered(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    arguments = SimpleNamespace(
        source=None,
        task=None,
        source_task=[f"{first}::suite/one", f"{second}::suite/two"],
    )

    requests = _task_requests(arguments)

    assert [(request.source, request.task_id) for request in requests] == [
        (first, "suite/one"),
        (second, "suite/two"),
    ]


def test_progress_summary_distinguishes_rejection_from_infrastructure() -> None:
    summary = _summary(
        plan={"model_id": "model", "reasoning_effort": "max", "plan_hash": "1" * 64},
        records=[
            {"resolved": True, "infrastructure_invalid": False},
            {"resolved": False, "infrastructure_invalid": False},
            {"resolved": False, "infrastructure_invalid": True},
        ],
        planned=4,
        stopped_early=True,
    )

    assert summary["completed"] == 3
    assert summary["resolved"] == 1
    assert summary["rejected"] == 1
    assert summary["infrastructure_invalid"] == 1
    assert summary["stopped_early"] is True


def test_auth_mode_preflight_runs_before_output_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VERIGYM_RUN_CODEX_TRAINING_SAMPLER", "1")
    monkeypatch.delenv("VERIGYM_CODEX_AUTH_MODE", raising=False)
    output = tmp_path / "campaign"
    arguments = SimpleNamespace(samples=1, max_process_time_s=1, output=output)

    with pytest.raises(SystemExit, match="VERIGYM_CODEX_AUTH_MODE"):
        _run(arguments)

    assert not output.exists()


def test_heldout_binding_validates_exact_split_and_agent_version(tmp_path: Path) -> None:
    freeze_root, agent_path, records = _heldout_files(tmp_path)
    arguments = SimpleNamespace(
        campaign_role="heldout",
        samples=1,
        heldout_freeze=freeze_root,
        agent_version=agent_path,
        model_id="gpt-5.6-luna",
        reasoning_effort="max",
        agent_image_id=f"sha256:{'a' * 64}",
        verifier_image_id=f"sha256:{'b' * 64}",
    )

    binding = _heldout_binding(
        arguments,
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        task_records=records,
    )

    assert binding is not None
    assert binding.split_id == "hwe-repo-heldout-v1"
    assert binding.agent_version.agent_version_id == "codex-luna-max-hwe-heldout-v1"


def test_heldout_binding_includes_suite_managed_verifier_image(tmp_path: Path) -> None:
    suite_image = "c" * 64
    freeze_root, agent_path, records = _heldout_files(tmp_path, suite_verifier_image=suite_image)
    arguments = SimpleNamespace(
        campaign_role="heldout",
        samples=1,
        heldout_freeze=freeze_root,
        agent_version=agent_path,
        model_id="gpt-5.6-luna",
        reasoning_effort="max",
        agent_image_id=f"sha256:{'a' * 64}",
        verifier_image_id=f"sha256:{'b' * 64}",
    )

    binding = _heldout_binding(
        arguments,
        auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
        task_records=records,
    )

    assert binding is not None
    assert suite_image in binding.agent_version.image_hashes.values()


def test_suite_verifier_images_rejects_non_digest_identity() -> None:
    task = SimpleNamespace(
        verifier=SimpleNamespace(
            nodes=[SimpleNamespace(id="verify", request={"image_id": "mutable:latest"})]
        )
    )

    with pytest.raises(SystemExit, match="lowercase SHA-256"):
        _suite_verifier_images(task)


def test_heldout_binding_rejects_incomplete_task_set(tmp_path: Path) -> None:
    freeze_root, agent_path, records = _heldout_files(tmp_path)
    arguments = SimpleNamespace(
        campaign_role="heldout",
        samples=1,
        heldout_freeze=freeze_root,
        agent_version=agent_path,
        model_id="gpt-5.6-luna",
        reasoning_effort="max",
        agent_image_id=f"sha256:{'a' * 64}",
        verifier_image_id=f"sha256:{'b' * 64}",
    )
    records[0]["task_hash"] = "f" * 64

    with pytest.raises(SystemExit, match="task set"):
        _heldout_binding(
            arguments,
            auth_semantic_id="codex.auth.inherited_chatgpt_session.v1",
            task_records=records,
        )
