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

_SCRIPT = Path(__file__).parents[2] / "scripts" / "run_api_repository_campaign.py"
_NAMESPACE = runpy.run_path(str(_SCRIPT))
_task_requests = cast(Any, _NAMESPACE["_task_requests"])
_summary = cast(Any, _NAMESPACE["_summary"])
_run = cast(Any, _NAMESPACE["_run"])
_heldout_binding = cast(Any, _NAMESPACE["_heldout_binding"])
_model_policy_hash = cast(Any, _NAMESPACE["_model_policy_hash"])
_parser = cast(Any, _NAMESPACE["_parser"])


def _arguments(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        campaign_role="heldout",
        samples=1,
        model_id="deepseek-v4-flash",
        provider_id="DeepSeek",
        thinking_mode="disabled",
        action_plan_protocol="strict_three_action_repository_repair_v1",
        max_output_tokens=4096,
        connect_timeout_s=10.0,
        read_timeout_s=120.0,
        request_timeout_s=120.0,
        max_response_bytes=1024 * 1024,
        base_url_env="VERIGYM_DEEPSEEK_API_BASE_URL",
        api_key_env="VERIGYM_DEEPSEEK_API_KEY",
        agent_image_id=f"sha256:{'a' * 64}",
        verifier_image_id=f"sha256:{'b' * 64}",
        heldout_freeze=None,
        agent_version=None,
        output=tmp_path / "campaign",
    )


def test_campaign_default_output_cap_is_16k() -> None:
    assert _parser().get_default("max_output_tokens") == 16_384


def _heldout_files(
    tmp_path: Path,
    arguments: SimpleNamespace,
    *,
    agent_descriptor_hash: str,
) -> tuple[Path, Path, list[dict[str, object]]]:
    heldout = pytest.importorskip("verigym_training_reference.heldout")
    task_id = "hwe-bench/repo-repair-v1/fixture"
    suite_image = "c" * 64
    version = build_agent_version(
        agent_version_id="deepseek-api-hwe-heldout-v1",
        update_type="none",
        executable_in_m10b=True,
        base_agent_id="api-repository-agent",
        agent_descriptor_hash=agent_descriptor_hash,
        model_id=arguments.model_id,
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash="2" * 64,
        tool_policy_hash="3" * 64,
        prompt_contract_hash="4" * 64,
        source_commit="5" * 40,
        package_hashes={
            "api-request-policy": _model_policy_hash(arguments),
            "verigym": "6" * 64,
        },
        image_hashes={
            "agent": "a" * 64,
            "verifier": "b" * 64,
            f"suite-verifier:{task_id}:run_hidden_regression": suite_image,
        },
    )
    agent_path = tmp_path / "agent-version.json"
    agent_path.write_text(version.model_dump_json(indent=2), encoding="utf-8")
    entry = TaskSplitEntry(
        task_id=task_id,
        source_hash="7" * 64,
        task_hash="8" * 64,
        license="Apache-2.0",
        attribution="fixture",
    )
    split = build_task_split(
        split_id="hwe-repo-heldout-deepseek-v1",
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
            "task_id": task_id,
            "task_hash": entry.task_hash,
            "source_hash": entry.source_hash,
            "suite_verifier_images": {"run_hidden_regression": suite_image},
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


def test_missing_credential_preflight_runs_before_output_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VERIGYM_RUN_API_REPOSITORY_CAMPAIGN", "1")
    monkeypatch.delenv("VERIGYM_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("VERIGYM_DEEPSEEK_API_BASE_URL", "https://example.invalid")
    arguments = _arguments(tmp_path)
    arguments.max_process_time_s = 1

    with pytest.raises(SystemExit, match="VERIGYM_DEEPSEEK_API_KEY"):
        _run(arguments)

    assert not arguments.output.exists()


def test_heldout_binding_validates_api_policy_and_exact_task_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    descriptor_hash = "1" * 64
    arguments = _arguments(tmp_path)
    freeze_root, agent_path, records = _heldout_files(
        tmp_path,
        arguments,
        agent_descriptor_hash=descriptor_hash,
    )
    arguments.heldout_freeze = freeze_root
    arguments.agent_version = agent_path
    monkeypatch.setitem(
        _heldout_binding.__globals__,
        "get_build_provenance",
        lambda: SimpleNamespace(dirty=False, source_commit="5" * 40),
    )

    binding = _heldout_binding(
        arguments,
        task_records=records,
        agent_descriptor_hash=descriptor_hash,
    )

    assert binding is not None
    assert binding.split_id == "hwe-repo-heldout-deepseek-v1"
    assert binding.agent_version.agent_version_id == "deepseek-api-hwe-heldout-v1"


def test_heldout_binding_rejects_changed_output_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    descriptor_hash = "1" * 64
    arguments = _arguments(tmp_path)
    freeze_root, agent_path, records = _heldout_files(
        tmp_path,
        arguments,
        agent_descriptor_hash=descriptor_hash,
    )
    arguments.heldout_freeze = freeze_root
    arguments.agent_version = agent_path
    arguments.max_output_tokens = 8192
    monkeypatch.setitem(
        _heldout_binding.__globals__,
        "get_build_provenance",
        lambda: SimpleNamespace(dirty=False, source_commit="5" * 40),
    )

    with pytest.raises(SystemExit, match="requested API policy"):
        _heldout_binding(
            arguments,
            task_records=records,
            agent_descriptor_hash=descriptor_hash,
        )


def test_summary_distinguishes_model_rejection_from_infrastructure() -> None:
    summary = _summary(
        plan={
            "provider_id": "DeepSeek",
            "model_id": "deepseek-v4-flash",
            "reasoning_effort": "thinking-disabled",
            "plan_hash": "1" * 64,
        },
        records=[
            {"resolved": False, "infrastructure_invalid": False},
            {"resolved": False, "infrastructure_invalid": True},
        ],
        planned=3,
        stopped_early=True,
    )

    assert summary["rejected"] == 1
    assert summary["infrastructure_invalid"] == 1
    assert summary["stopped_early"] is True
