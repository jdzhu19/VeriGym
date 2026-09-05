from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.open_toolchain import (
    V172_AGENT_TOOLCHAIN_ID,
    V172_TASK_ID,
    OpenToolchainImageLock,
    load_open_toolchain_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v172_open_toolchain_qualification_v1.json"
)


def _image_lock() -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v1",
        "identity": "deepseek-harness-hwe-v172-open-toolchain-qualification-v1",
        "agent_toolchain_id": V172_AGENT_TOOLCHAIN_ID,
        "image_id": "sha256:" + "1" * 64,
        "accepted_open_tools_image_id": "sha256:" + "2" * 64,
        "builder_image_id": "sha256:" + "3" * 64,
        "official_verifier_image": "sha256:" + "4" * 64,
        "binary_sha256": {
            name: f"{index}" * 64
            for index, name in enumerate(
                ["verilator", "verilator_bin", "iverilog", "vvp", "yosys", "rg", "make", "g++"],
                start=1,
            )
        },
        "binary_versions": {"verilator": "5.008"},
        "build_network": "none",
        "runtime_network": "none",
        "effective_user": "1004:100",
        "read_only_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "single_workspace_mount": True,
        "provider_credentials_present": False,
        "codex_present": False,
        "hwe_task_image_ancestor": False,
        "official_verifier_included": False,
        "security_scan_id": "v172-open-toolchain-scan-v1",
        "security_check_count": 38,
        "security_scan_passed": True,
    }
    return {**base, "lock_hash": content_hash(base)}


def test_checked_in_v172_manifest_separates_agent_and_official_roles() -> None:
    manifest = load_open_toolchain_manifest(_MANIFEST)
    assert manifest.task.task_id == V172_TASK_ID
    assert manifest.agent_toolchain_id == V172_AGENT_TOOLCHAIN_ID
    assert manifest.agent_toolchain_id != manifest.task.agent_toolchain_id
    assert manifest.accepted_open_tools_image_id != manifest.official_verifier_image
    assert manifest.build_network == "none"
    assert manifest.agent_command_network == "none"
    assert manifest.official_verifier_network == "none"
    assert manifest.provider_clients_available is False
    assert manifest.provider_calls == 0
    assert manifest.local_runtime_allowed is False
    assert manifest.formal_collection_allowed is False
    assert manifest.v174_canary_authorized is False


def test_manifest_rejects_role_confusion_even_with_recomputed_hash() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["agent_toolchain_id"] = value["task"]["agent_toolchain_id"]
    value.pop("manifest_hash")
    value["manifest_hash"] = content_hash(value)
    changed = _MANIFEST.parent / "not-written.json"
    with pytest.raises(ValueError, match="agent_toolchain_id"):
        type(load_open_toolchain_manifest(_MANIFEST)).model_validate(value)
    assert not changed.exists()


def test_open_toolchain_image_lock_requires_full_executable_inventory() -> None:
    value = _image_lock()
    OpenToolchainImageLock.model_validate(value)
    changed = copy.deepcopy(value)
    changed["binary_sha256"].pop("g++")  # type: ignore[union-attr]
    identity = dict(changed)
    identity.pop("lock_hash")
    changed["lock_hash"] = content_hash(identity)
    with pytest.raises(ValueError, match="executable inventory"):
        OpenToolchainImageLock.model_validate(changed)


def test_manifest_loader_rejects_symlink(tmp_path: Path) -> None:
    linked = tmp_path / "manifest.json"
    linked.symlink_to(_MANIFEST)
    with pytest.raises(ConfigurationError, match="unsafe"):
        load_open_toolchain_manifest(linked)
