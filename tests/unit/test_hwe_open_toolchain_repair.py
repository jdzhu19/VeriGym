from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.open_toolchain_repair import (
    V176_IDENTITY,
    OpenToolchainV176RepairManifest,
    load_v176_repair_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v176_open_toolchain_repair_v1.json"
)


def test_checked_in_v176_repair_is_closed_and_fresh() -> None:
    manifest = load_v176_repair_manifest(_MANIFEST)
    assert manifest.identity == V176_IDENTITY
    assert manifest.predecessor_identity.endswith("v174-open-toolchain-qualification-repair-v1")
    assert "v176" in manifest.builder_source_dockerfile
    assert "v176" in manifest.builder_tag
    assert "v176" in manifest.final_dockerfile
    assert "v176" in manifest.output_root
    assert "v176" in manifest.scratch_root
    assert "v176" in manifest.dind_data_volume
    assert "v176" in manifest.dind_socket_volume
    assert manifest.builder_external_frontend_allowed is False
    assert manifest.builder_diagnostic_max_bytes == 1024 * 1024
    assert manifest.provider_clients_available is False
    assert manifest.provider_calls == 0
    assert manifest.registry_access_allowed is False
    assert manifest.local_runtime_allowed is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False
    assert manifest.requires_independent_v177_audit is True
    assert manifest.v178_canary_authorized is False


def test_v176_manifest_binds_exact_predecessor_inventory() -> None:
    manifest = load_v176_repair_manifest(_MANIFEST)
    assert set(manifest.predecessor_result_file_sha256) == {
        "archive-receipt.json",
        "headroom.json",
        "materialization-progress.json",
        "reference-patch-compatibility.json",
        "zero-provider-report.json",
    }
    assert manifest.predecessor_audit_post_merge_main_run_id == 33983817261
    assert manifest.predecessor_audit_post_merge_all_eight_classes_passed is True


def test_v176_manifest_rejects_mutation_with_recomputed_hash() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["builder_tag"] = "verigym/open-rtl-tools:wrong"
    value.pop("manifest_hash")
    value["manifest_hash"] = content_hash(value)
    with pytest.raises(ValueError, match="builder_tag"):
        OpenToolchainV176RepairManifest.model_validate(value)


def test_v176_manifest_rejects_partial_predecessor_inventory() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["predecessor_result_file_sha256"].pop("archive-receipt.json")
    value.pop("manifest_hash")
    value["manifest_hash"] = content_hash(value)
    with pytest.raises(ValueError, match="inventory"):
        OpenToolchainV176RepairManifest.model_validate(value)


def test_v176_manifest_loader_rejects_symlink(tmp_path: Path) -> None:
    linked = tmp_path / "manifest.json"
    linked.symlink_to(_MANIFEST)
    with pytest.raises(ConfigurationError, match="unsafe"):
        load_v176_repair_manifest(linked)
