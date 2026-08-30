from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.hwe.image_lock import HweAgentImageLock

from verigym_openhands.hwe_v19_campaign import (
    OPENHANDS_V19_CANARY_VALIDATION_BINDING,
    OPENHANDS_V19_CANARY_VALIDATION_TASK,
    OPENHANDS_V19_QUALIFICATION_CANDIDATES,
    build_v19_canary_contract,
)

_REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY))
sys.path.insert(0, str(_REPOSITORY / "integrations/verigym-hwe-bench/src"))

_materialize = importlib.import_module("scripts.materialize_cva6_openhands_v29_v19_canary")


def _authorization() -> dict[str, Any]:
    path = (
        _REPOSITORY / "configs/training/qwen35_hwe_openhands_v29_v19_canary_materialization_v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _binding(task_id: str, index: int) -> dict[str, str]:
    suffix = task_id.rsplit("-", 1)[-1]
    return {
        "task_hash": f"{index + 1:064x}",
        "source_hash": f"{index + 11:064x}",
        "source_image_lock_sha256": f"{index + 21:064x}",
        "verifier_image": f"sha256:{index + 31:064x}",
        "verifier_manifest_digest": f"sha256:{index + 41:064x}",
        "source": f"sources/pr-{suffix}",
        "smoke": f"smokes/pr-{suffix}",
        "transfer_receipt_hash": f"{index + 51:064x}",
    }


def _progress() -> dict[str, Any]:
    bindings = {
        task_id: _binding(task_id, index)
        for index, task_id in enumerate(_materialize._QUALIFIED_TASKS)
    }
    base = {
        "schema_version": "1.0",
        "format_id": _materialize._v28.OPENHANDS_V28_PROGRESS_FORMAT,
        "identity": _materialize._v28.OPENHANDS_V28_IDENTITY,
        "authorization_hash": _materialize._v28.OPENHANDS_V28_APPROVAL_HASH,
        "status": "qualified_pending_agent_images",
        "candidate_order": list(OPENHANDS_V19_QUALIFICATION_CANDIDATES),
        "qualified_task_ids": list(_materialize._QUALIFIED_TASKS),
        "training_reserve_task_ids": list(_materialize._TRAINING_RESERVES),
        "validation_reserve_task_ids": list(_materialize._VALIDATION_RESERVES),
        "historical_attempts_retried": False,
        "model_process_count": 0,
        "provider_calls": 0,
        "heldout_task_ids_loaded": [],
        "verifier_network": "none",
        "implicit_image_pulls_allowed": False,
        "raw_command_output_persisted": False,
        "temporary_containers_removed": True,
        "temporary_transfer_scratch_removed": True,
        "privileged_container_used": False,
        "docker_socket_mounted": False,
        "tcp_api_listener_present": False,
        "outcomes": [],
        "qualified_bindings": bindings,
    }
    return {**base, "progress_hash": content_hash(base)}


def _approved_for(progress: dict[str, Any]) -> dict[str, Any]:
    return {
        "qualification_evidence": {
            "progress_hash": progress["progress_hash"],
            "format_id": progress["format_id"],
            "identity": progress["identity"],
            "authorization_hash": progress["authorization_hash"],
            "status": progress["status"],
        }
    }


def _agent_lock(task_id: str, index: int) -> HweAgentImageLock:
    source = _binding(task_id, index)
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_agent_image_lock_v2",
        "task_id": task_id,
        "task_hash": source["task_hash"],
        "source_hash": source["source_hash"],
        "verifier_base_image_id": source["verifier_image"],
        "derived_agent_image_id": f"sha256:{index + 101:064x}",
        "codex_version": "codex-cli 0.147.0",
        "host_codex_sha256": "a" * 64,
        "agent_codex_sha256": _materialize._images._EXPECTED_AGENT_CODEX_SHA256,
        "agent_rg_sha256": _materialize._images._EXPECTED_AGENT_RG_SHA256,
        "collection_profile_id": "hwe_standard_v2",
        "tool_contract_id": "hwe_native_shell_v2",
        "toolchain_profile_id": "cva6-verilator-5.008-container-native-v2",
        "allowlisted_artifacts": [
            {
                "path": "/usr/bin/make",
                "sha256": "b" * 64,
                "role": "build_tool",
            },
            {
                "path": "/tools/verilator/bin/verilator_bin",
                "sha256": "c" * 64,
                "role": "simulator",
            },
        ],
        "source_whiteout_path": "/home/cva6",
        "visible_workspace_path": "/workspace/repository",
        "build_network": "none",
        "runtime_network": "none",
        "provider_credentials_present": False,
        "hidden_assets_present": False,
        "verifier_payload_present": False,
        "reference_patch_present": False,
        "security_scan_id": f"{index + 201:064x}",
        "security_scan_passed": True,
    }
    return HweAgentImageLock.model_validate({**base, "lock_hash": content_hash(base)})


def test_v29_authorization_is_hash_bound_and_authorizes_no_provider() -> None:
    approved = _materialize._validated_authorization(_authorization())

    assert approved["authorization_hash"] == _materialize.OPENHANDS_V29_APPROVAL_HASH
    assert approved["authorized_actions"]["build_reserve_agent_images"] is True
    assert approved["authorized_actions"]["materialize_v19_canary_contract"] is True
    assert approved["authorized_actions"]["invoke_provider"] is False
    assert approved["authorized_actions"]["execute_canary"] is False
    assert approved["authorized_actions"]["load_heldout_tasks"] is False
    assert approved["canary_contract"]["training_task_id"] == _materialize._TRAINING_RESERVES[0]


def test_v29_authorization_rejects_provider_or_contract_substitution() -> None:
    changed = _authorization()
    changed["authorized_actions"]["invoke_provider"] = True
    changed["canary_contract"]["training_task_id"] = _materialize._TRAINING_RESERVES[1]
    base = {key: value for key, value in changed.items() if key != "authorization_hash"}
    changed["authorization_hash"] = content_hash(base)

    with pytest.raises(ConfigurationError, match="authorization identity changed"):
        _materialize._validated_authorization(changed)


def test_v29_progress_preserves_five_reserves_and_zero_model_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress = _progress()
    monkeypatch.setattr(
        _materialize._v28,
        "_qualification_state",
        lambda _outcomes: {
            "qualified_task_ids": list(_materialize._QUALIFIED_TASKS),
            "satisfied": True,
        },
    )

    validated = _materialize._validated_qualification_progress(
        copy.deepcopy(progress), approved=_approved_for(progress)
    )

    assert validated["training_reserve_task_ids"] == list(_materialize._TRAINING_RESERVES)
    assert validated["validation_reserve_task_ids"] == list(_materialize._VALIDATION_RESERVES)
    assert validated["provider_calls"] == 0
    assert validated["heldout_task_ids_loaded"] == []

    changed = copy.deepcopy(progress)
    changed["qualified_bindings"].pop(_materialize._QUALIFIED_TASKS[-1])
    base = {key: value for key, value in changed.items() if key != "progress_hash"}
    changed["progress_hash"] = content_hash(base)
    with pytest.raises(ConfigurationError, match="qualification evidence changed"):
        _materialize._validated_qualification_progress(changed, approved=_approved_for(changed))


def test_v29_source_catalog_checks_all_three_read_only_origins(tmp_path: Path) -> None:
    progress = _progress()
    roots = {name: tmp_path / name for name in ("v26", "v27", "v28")}
    for root in roots.values():
        root.mkdir()
    for task_id in _materialize._QUALIFIED_TASKS:
        binding = progress["qualified_bindings"][task_id]
        source = roots[_materialize._SOURCE_ORIGINS[task_id]] / binding["source"]
        source.mkdir(parents=True)
        source_lock = {
            "format_id": "verigym_hwe_bench_source_v2",
            "entries": [
                {
                    "repository_hash": binding["source_hash"],
                    "image_id": binding["verifier_image"],
                    "manifest_digest": binding["verifier_manifest_digest"],
                }
            ],
        }
        lock_path = source / "image-lock.json"
        lock_path.write_text(json.dumps(source_lock), encoding="utf-8")
        binding["source_image_lock_sha256"] = hash_bytes(lock_path.read_bytes())

    catalog = _materialize._validated_source_catalog(progress, roots=roots)

    assert catalog["tasks"][_materialize._QUALIFIED_TASKS[0]]["origin"] == "v26"
    assert catalog["tasks"][_materialize._QUALIFIED_TASKS[2]]["origin"] == "v27"
    assert catalog["tasks"][_materialize._QUALIFIED_TASKS[-1]]["origin"] == "v28"
    assert all("/data/" not in item["source"] for item in catalog["tasks"].values())
    assert catalog["catalog_hash"] == content_hash(
        {key: value for key, value in catalog.items() if key != "catalog_hash"}
    )


def test_v29_receipt_keeps_v19_identity_and_selects_pr2330_then_pr3204() -> None:
    qualification = _progress()
    locks = {
        task_id: _agent_lock(task_id, index)
        for index, task_id in enumerate(_materialize._QUALIFIED_TASKS)
    }
    qualification["outcomes"] = [
        {
            "task_id": task_id,
            "infrastructure_valid": True,
            "verifier_network": "none",
            "verifier_image": locks[task_id].verifier_base_image_id,
            "model_process_count": 0,
            "base_failed": True,
            "reference_passed": True,
        }
        for task_id in _materialize._QUALIFIED_TASKS
    ]

    receipt = _materialize._qualification_receipt(qualification, locks=locks)
    contract = build_v19_canary_contract(
        receipt,
        validation_binding=OPENHANDS_V19_CANARY_VALIDATION_BINDING,
    )

    assert receipt["training_reserve_task_ids"] == list(_materialize._TRAINING_RESERVES)
    assert contract["schedule"][0]["task_id"] == _materialize._TRAINING_RESERVES[0]
    assert contract["schedule"][1]["task_id"] == OPENHANDS_V19_CANARY_VALIDATION_TASK
    assert contract["teacher"]["provider_request_retries"] == 0
    assert contract["teacher"]["whole_episode_retries"] == 0
    assert contract["gate"]["truncation_allowed"] is False
    assert contract["heldout_task_ids_loaded"] == []


def test_v29_source_child_cannot_escape_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not relative"):
        _materialize._safe_child(root.resolve(), "../outside")

    inside = root / "inside"
    inside.mkdir()
    (root / "link").symlink_to(inside, target_is_directory=True)
    with pytest.raises(ConfigurationError, match="contains a symlink"):
        _materialize._safe_child(root.resolve(), "link")
