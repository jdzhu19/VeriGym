from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.open_toolchain_git_builder_repair import (
    V188_IDENTITY,
    OpenToolchainV188ImageLock,
    load_v188_git_builder_repair_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / ("configs/training/qwen35_hwe_deepseek_harness_v188_git_builder_repair_v1.json")


def test_v188_manifest_authorizes_only_the_task_free_minimal_git_repair() -> None:
    manifest = load_v188_git_builder_repair_manifest(_MANIFEST)

    assert manifest.identity == V188_IDENTITY
    assert manifest.predecessor_missing_command == "git"
    assert manifest.git_version == "2.47.3"
    assert len(manifest.git_packages) == 6
    assert manifest.builder_build_network == "none"
    assert manifest.final_build_network == "none"
    assert manifest.probe_network == "none"
    assert manifest.pull is False
    assert manifest.minimal_git_repair_authorized is True
    assert manifest.task_metadata_loaded is False
    assert manifest.hwe_image_inspected is False
    assert manifest.hwe_image_imported is False
    assert manifest.task_source_prepared is False
    assert manifest.verifier_run is False
    assert manifest.model_process_count == 0
    assert manifest.provider_calls == 0
    assert manifest.qualification_authorized is False
    assert manifest.canary_authorized is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False
    assert manifest.control_root_min_available_bytes == 9 * 1024**3
    assert manifest.data2_min_available_bytes == 50 * 1024**3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("git_version", "2.48.0"),
        ("builder_build_network", "default"),
        ("hwe_image_imported", True),
        ("provider_calls", 1),
    ],
)
def test_v188_manifest_rejects_identity_or_lifecycle_drift(
    tmp_path: Path, field: str, value: object
) -> None:
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    data[field] = value
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v188_git_builder_repair_manifest(changed)


def test_v188_manifest_rejects_package_closure_drift(tmp_path: Path) -> None:
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    data["git_packages"][0]["sha256"] = "0" * 64
    identity = {key: value for key, value in data.items() if key != "manifest_hash"}
    data["manifest_hash"] = content_hash(identity)
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v188_git_builder_repair_manifest(changed)


def test_v188_manifest_rejects_symlink(tmp_path: Path) -> None:
    link = tmp_path / "manifest.json"
    link.symlink_to(_MANIFEST)

    with pytest.raises(ConfigurationError, match="unsafe"):
        load_v188_git_builder_repair_manifest(link)


def test_v188_image_lock_keeps_agent_and_official_images_distinct() -> None:
    manifest = load_v188_git_builder_repair_manifest(_MANIFEST)
    hashes = {
        name: "1" * 64
        for name in (
            "g++",
            "git",
            "iverilog",
            "make",
            "rg",
            "verilator",
            "verilator_bin",
            "vvp",
            "yosys",
        )
    }
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v2",
        "identity": V188_IDENTITY,
        "scanner_profile_id": manifest.scanner_profile_id,
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "image_id": "sha256:" + "2" * 64,
        "accepted_open_tools_image_id": "sha256:" + "3" * 64,
        "base_builder_image_id": "sha256:" + "4" * 64,
        "derived_builder_image_id": "sha256:" + "5" * 64,
        "official_verifier_image": "sha256:" + "6" * 64,
        "binary_sha256": hashes,
        "binary_versions": {name: "locked" for name in hashes},
        "build_network": "none",
        "runtime_network": "none",
        "effective_user": "1004:100",
        "read_only_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "mount_count": 0,
        "provider_credentials_present": False,
        "codex_present": False,
        "hwe_image_loaded": False,
        "official_verifier_included": False,
        "security_scan_passed": True,
    }
    lock = OpenToolchainV188ImageLock.model_validate({**base, "lock_hash": content_hash(base)})
    assert lock.agent_toolchain_id == "verigym-open-rtl-tools-v1"
    assert lock.image_id != lock.official_verifier_image


def test_v188_image_lock_rejects_official_image_alias() -> None:
    manifest = load_v188_git_builder_repair_manifest(_MANIFEST)
    hashes = {
        name: "1" * 64
        for name in (
            "g++",
            "git",
            "iverilog",
            "make",
            "rg",
            "verilator",
            "verilator_bin",
            "vvp",
            "yosys",
        )
    }
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_open_hwe_toolchain_image_lock_v2",
        "identity": V188_IDENTITY,
        "scanner_profile_id": manifest.scanner_profile_id,
        "agent_toolchain_id": manifest.agent_toolchain_id,
        "image_id": "sha256:" + "2" * 64,
        "accepted_open_tools_image_id": "sha256:" + "3" * 64,
        "base_builder_image_id": "sha256:" + "4" * 64,
        "derived_builder_image_id": "sha256:" + "5" * 64,
        "official_verifier_image": "sha256:" + "2" * 64,
        "binary_sha256": hashes,
        "binary_versions": {name: "locked" for name in hashes},
        "build_network": "none",
        "runtime_network": "none",
        "effective_user": "1004:100",
        "read_only_root": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "mount_count": 0,
        "provider_credentials_present": False,
        "codex_present": False,
        "hwe_image_loaded": False,
        "official_verifier_included": False,
        "security_scan_passed": True,
    }

    with pytest.raises(ValueError, match="role"):
        OpenToolchainV188ImageLock.model_validate({**base, "lock_hash": content_hash(base)})
