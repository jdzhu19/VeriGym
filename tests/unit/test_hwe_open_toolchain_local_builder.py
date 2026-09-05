from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.open_toolchain_local_builder import load_v178_local_builder_manifest

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "configs/training/qwen35_hwe_deepseek_harness_v178_local_builder_v1.json"


def test_checked_in_v178_local_builder_manifest_is_closed_and_fresh() -> None:
    manifest = load_v178_local_builder_manifest(_MANIFEST)

    assert manifest.local_builder_acquisition == "completed-data2-docker-archive-v1"
    assert manifest.local_builder_origin == "opensta-build-dependency-stage-v1"
    assert manifest.local_builder_image_id.startswith("sha256:427a3c")
    assert len(manifest.local_builder_rootfs_layers) == 2
    assert manifest.local_builder_archive_path.startswith("/data2/")
    assert manifest.local_builder_archive_bytes == 519838720
    assert manifest.generic_builder_dockerfile_executed is False
    assert "v178" in manifest.builder_tag
    assert "v178" in manifest.final_dockerfile
    assert "v178" in manifest.output_root
    assert manifest.download_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.provider_clients_available is False
    assert manifest.provider_calls == 0
    assert manifest.local_runtime_allowed is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False
    assert manifest.requires_independent_v179_audit is True
    assert manifest.v180_canary_authorized is False


def test_v178_manifest_binds_complete_v176_failure_inventory() -> None:
    manifest = load_v178_local_builder_manifest(_MANIFEST)

    assert set(manifest.predecessor_result_file_sha256) == {
        "archive-receipt.json",
        "builder-diagnostic.json",
        "headroom.json",
        "materialization-progress.json",
        "reference-patch-compatibility.json",
        "zero-provider-report.json",
    }
    assert manifest.predecessor_builder_diagnostic_category == "offline_cache_miss"
    assert manifest.predecessor_audit_post_merge_all_eight_classes_passed is True


def test_v178_manifest_rejects_layer_mutation_even_with_recomputed_hash(tmp_path: Path) -> None:
    value = json.loads(_MANIFEST.read_bytes())
    value["local_builder_rootfs_layers"].reverse()
    value["manifest_hash"] = content_hash(
        {key: item for key, item in value.items() if key != "manifest_hash"}
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v178_local_builder_manifest(path)


def test_v178_manifest_rejects_partial_predecessor_inventory(tmp_path: Path) -> None:
    value = json.loads(_MANIFEST.read_bytes())
    value["predecessor_result_file_sha256"].pop("builder-diagnostic.json")
    value["manifest_hash"] = content_hash(
        {key: item for key, item in value.items() if key != "manifest_hash"}
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v178_local_builder_manifest(path)


def test_v178_manifest_loader_rejects_symlink(tmp_path: Path) -> None:
    linked = tmp_path / "manifest.json"
    linked.symlink_to(_MANIFEST)

    with pytest.raises(ConfigurationError, match="unsafe"):
        load_v178_local_builder_manifest(linked)
