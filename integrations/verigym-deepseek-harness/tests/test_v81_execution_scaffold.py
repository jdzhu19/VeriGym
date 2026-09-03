from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    load_v69_manifest,
    load_v79_dind_successor_manifest,
    load_v81_execution_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v81_execution_scaffold as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v81_provider_execution_scaffold_v1.json"
)
_UPSTREAM = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)
_V79_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v79_dind_zero_provider_successor_v1.json"
)


def test_checked_in_v81_scaffold_is_fresh_credential_free_and_purpose_bound() -> None:
    manifest = load_v81_execution_scaffold_manifest(_MANIFEST)
    assert manifest.identity == runner.IDENTITY
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_socket_backing == str(runner.DIND_SOCKET_BACKING)
    assert manifest.dind_data_volume != "verigym-deepseek-harness-v79-dind-data"
    assert manifest.scaffold_outer_network == "none"
    assert manifest.provider_outer_network == "verigym-hwe-net"
    assert manifest.controller_transfer == "content_free_read_only_outer_image_pipe_v1"
    assert manifest.provider_successor_reopen_budget == 1
    assert manifest.provider_clients_available is False
    assert manifest.registry_access_allowed is False
    assert manifest.partial_archive_allowed is False


def test_v81_scaffold_contract_is_atomic_and_does_not_authorize_provider() -> None:
    manifest = load_v81_execution_scaffold_manifest(_MANIFEST)
    upstream = load_v69_manifest(_UPSTREAM)
    receipts = [{"task_id": task.task_id} for task in upstream.primary_tasks]
    contract = runner._scaffold_contract(  # noqa: SLF001
        manifest,
        upstream,
        receipts,
        source_commit="1" * 40,
        post_merge_main_run_id=123,
        runtime_receipt={"receipt_hash": "2" * 64},
        controller_receipt={"receipt_hash": "3" * 64},
        inventory={"inventory_hash": "4" * 64},
        cleanup={"receipt_hash": "5" * 64},
    )
    without_hash = dict(contract)
    observed = without_hash.pop("contract_hash")
    assert observed == content_hash(without_hash)
    assert contract["schedule"] == [task.task_id for task in upstream.primary_tasks]
    assert contract["provider_execution_scaffold_published"] is True
    assert contract["provider_execution_authorized"] is False
    assert contract["provider_successor_reopen_count"] == 0
    assert contract["formal_collection_allowed"] is False

    with pytest.raises(ConfigurationError, match="partial execution scaffold"):
        runner._scaffold_contract(  # noqa: SLF001
            manifest,
            upstream,
            receipts[:-1],
            source_commit="1" * 40,
            post_merge_main_run_id=123,
            runtime_receipt={"receipt_hash": "2" * 64},
            controller_receipt={"receipt_hash": "3" * 64},
            inventory={"inventory_hash": "4" * 64},
            cleanup={"receipt_hash": "5" * 64},
        )


def test_v81_execution_boundary_rejects_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in runner.v69._PROVIDER_ENV_NAMES:  # noqa: SLF001
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    arguments = Namespace(post_merge_main_run_id=123)
    runner._require_execution_boundary(arguments)  # noqa: SLF001

    monkeypatch.setenv("VERIGYM_DEEPSEEK_API_KEY", "not-persisted")
    with pytest.raises(ConfigurationError, match="refuses a provider"):
        runner._require_execution_boundary(arguments)  # noqa: SLF001


def test_v81_content_free_diagnostic_does_not_persist_output(tmp_path: Path) -> None:
    receipt_path = tmp_path / "diagnostic.json"
    receipt = runner._content_free_bounded_command(  # noqa: SLF001
        [sys.executable, "-c", "print('private-build-output')"],
        timeout=30,
        receipt_path=receipt_path,
    )
    persisted = receipt_path.read_text(encoding="utf-8")
    assert receipt["diagnostic_passed"] is True
    assert receipt["stdout_bytes"] > 0
    assert "private-build-output" not in persisted
    assert receipt["raw_stdout_persisted"] is False


def test_v81_rebuild_locks_a_fresh_command_image_without_relabelling_v79() -> None:
    task = load_v69_manifest(_UPSTREAM).primary_tasks[0]
    v79_manifest = load_v79_dind_successor_manifest(_V79_MANIFEST)
    execution_image = "sha256:" + "a" * 64
    expected = {
        "task_id": task.task_id,
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "source_commit": task.source_commit,
        "dataset_base_commit": task.source_commit,
        "runtime_base_commit": task.source_commit,
        "runtime_base_commit_override_applied": False,
        "official_verifier_image": task.official_verifier_image,
        "agent_command_image": "sha256:" + "b" * 64,
        "agent_toolchain_id": task.agent_toolchain_id,
        "toolchain_profile_id": "ibex-verilator-system-container-native-v1",
    }
    base = {
        **expected,
        "agent_command_image": execution_image,
        "agent_command_image_lock_hash": "3" * 64,
        "agent_command_network": "none",
        "base_failed": True,
        "base_infrastructure_error": False,
        "reference_passed": True,
        "verifier_network": "none",
        "provider_calls": 0,
        "model_process_count": 0,
        "command_diagnostic_hash": "4" * 64,
        "runtime_baseline_policy": "exact-task-override-otherwise-dataset-base-v1",
    }
    receipt = {**base, "task_receipt_hash": content_hash(base)}
    runner._validate_execution_receipt(  # noqa: SLF001
        receipt,
        expected,
        task,
        v79_manifest,
    )
    assert receipt["agent_command_image"] != expected["agent_command_image"]


def test_v81_inventory_requires_all_provider_execution_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v81_execution_scaffold_manifest(_MANIFEST)
    verifier = "sha256:" + "1" * 64
    command = "sha256:" + "2" * 64
    output = "\n".join((manifest.controller_image_id, verifier, command)).encode()
    monkeypatch.setattr(
        runner.dind,
        "_inner",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, b""),
    )
    receipt = runner._inner_inventory(  # noqa: SLF001
        "sidecar",
        manifest,
        receipts=[
            {
                "official_verifier_image": verifier,
                "agent_command_image": command,
            }
        ],
    )
    assert receipt["required_images_present"] is True
    assert receipt["provider_inner_network_created"] is False

    monkeypatch.setattr(
        runner.dind,
        "_inner",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, (manifest.controller_image_id + "\n").encode(), b""
        ),
    )
    with pytest.raises(ConfigurationError, match="inventory"):
        runner._inner_inventory(  # noqa: SLF001
            "sidecar",
            manifest,
            receipts=[
                {
                    "official_verifier_image": verifier,
                    "agent_command_image": command,
                }
            ],
        )


def test_v81_manifest_json_does_not_contain_credentials() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True).lower()
    assert "api_key" not in encoded
    assert "credential_value" not in encoded
