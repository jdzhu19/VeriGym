from __future__ import annotations

import copy
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    V69_PRIMARY_TASK_IDS,
    HweOfflineTaskLock,
    load_v69_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import materialize_hwe_deepseek_harness_v69 as runner  # noqa: E402

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)


def _receipt(task: HweOfflineTaskLock) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "agent_toolchain_id": task.agent_toolchain_id,
        "official_verifier_image": task.official_verifier_image,
        "base_failed": True,
        "base_infrastructure_error": False,
        "reference_passed": True,
        "verifier_network": "none",
        "provider_calls": 0,
    }


def test_checked_in_v69_manifest_is_hash_bound_and_collection_closed() -> None:
    manifest = load_v69_manifest(_MANIFEST)
    assert tuple(task.task_id for task in manifest.primary_tasks) == V69_PRIMARY_TASK_IDS
    assert manifest.provider_clients_available is False
    assert manifest.atomic_provider_contract is True
    assert manifest.formal_collection_allowed is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


def test_provider_contract_is_atomic_and_keeps_execution_unauthorized() -> None:
    manifest = load_v69_manifest(_MANIFEST)
    receipts = [_receipt(task) for task in manifest.primary_tasks]
    contract = runner._provider_contract(  # noqa: SLF001
        manifest,
        receipts,
        source_commit="3" * 40,
        post_merge_main_run_id=123,
    )
    assert contract["schedule"] == list(V69_PRIMARY_TASK_IDS)
    assert contract["all_tasks_materialized"] is True
    assert contract["partial_authorization_published"] is False
    assert contract["provider_execution_authorized"] is False
    assert contract["formal_collection_allowed"] is False

    with pytest.raises(ConfigurationError, match="partial provider contract"):
        runner._provider_contract(  # noqa: SLF001
            manifest,
            receipts[:-1],
            source_commit="3" * 40,
            post_merge_main_run_id=123,
        )


def test_provider_contract_rejects_task_or_verifier_drift() -> None:
    manifest = load_v69_manifest(_MANIFEST)
    receipts = [_receipt(task) for task in manifest.primary_tasks]
    changed = copy.deepcopy(receipts)
    changed[0]["official_verifier_image"] = "sha256:" + "f" * 64
    with pytest.raises(ConfigurationError, match="not eligible"):
        runner._provider_contract(  # noqa: SLF001
            manifest,
            changed,
            source_commit="3" * 40,
            post_merge_main_run_id=123,
        )


def test_v69_runner_has_no_provider_surface_or_registry_command() -> None:
    source = (_REPOSITORY_ROOT / "scripts/materialize_hwe_deepseek_harness_v69.py").read_text(
        encoding="utf-8"
    )
    assert "provider_clients_available" not in source
    assert '["docker", "pull"' not in source
    assert "registry_access_allowed" not in source
    assert "DEEPSEEK_API_KEY" in source
    assert "VERIGYM_DEEPSEEK_API_KEY" in source
    assert "VERIGYM_DEEPSEEK_API_BASE_URL" in source
    assert "refuses a provider configuration environment" in source
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert all(
        not task["archive_relpath"].endswith(".partial") for task in manifest["primary_tasks"]
    )


def test_v69_checks_patch_compatibility_before_headroom_and_images() -> None:
    source = (_REPOSITORY_ROOT / "scripts/materialize_hwe_deepseek_harness_v69.py").read_text(
        encoding="utf-8"
    )
    patch_index = source.index("instances = _patch_preflight")
    headroom_index = source.index("headroom = require_materialization_headroom")
    image_index = source.index("for task_lock in manifest.primary_tasks")
    assert patch_index < headroom_index < image_index
    assert 'control_root=Path("/")' in source
    assert 'SCRATCH_ROOT = Path("/data2/jiadongzhu/Agent/.verigym-tmp")' in source


def test_cva6_command_image_uses_the_campaign_scratch_root() -> None:
    source = (_REPOSITORY_ROOT / "scripts/build_cva6_hwe_command_image.sh").read_text(
        encoding="utf-8"
    )
    assert "scratch_parent=/data2/jiadongzhu/Agent/.verigym-tmp" in source
    assert "scratch_parent=/data/jzhu484/Agent/.verigym-tmp" not in source

    runner_source = (
        _REPOSITORY_ROOT / "scripts/materialize_hwe_deepseek_harness_v69.py"
    ).read_text(encoding="utf-8")
    assert "runtime_scratch_parent=scan_scratch_parent" in runner_source


@pytest.mark.parametrize(
    "name",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "VERIGYM_DEEPSEEK_API_KEY",
        "VERIGYM_DEEPSEEK_API_BASE_URL",
    ],
)
def test_v69_execution_boundary_rejects_every_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    for provider_name in runner._PROVIDER_ENV_NAMES:  # noqa: SLF001
        monkeypatch.delenv(provider_name, raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(name, "present-but-never-read")
    monkeypatch.setattr(runner.os, "getuid", lambda: 1000)
    monkeypatch.setattr(runner.os, "getgid", lambda: 1000)
    with pytest.raises(ConfigurationError, match="provider configuration"):
        runner._require_execution_boundary(Namespace(post_merge_main_run_id=1))  # noqa: SLF001
