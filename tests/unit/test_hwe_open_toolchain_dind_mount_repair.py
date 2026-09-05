from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.open_toolchain_dind_mount_repair import (
    load_v180_dind_mount_repair_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / ("configs/training/qwen35_hwe_deepseek_harness_v180_dind_mount_repair_v1.json")


def test_checked_in_v180_manifest_is_closed_and_narrow() -> None:
    manifest = load_v180_dind_mount_repair_manifest(_MANIFEST)

    assert manifest.predecessor_stop_category == "invalid_mount_write_flag"
    assert manifest.rejected_write_mount_syntax.endswith(",rw")
    assert manifest.repaired_write_mount_syntax.endswith(">")
    assert manifest.writable_bind_mount_count == 2
    assert manifest.readonly_bind_mount_count == 1
    assert manifest.readonly_mount_syntax_unchanged is True
    assert manifest.builder_tag == "verigym/open-rtl-tools:v180-builder"
    assert "v180" in manifest.final_dockerfile
    assert "v180" in manifest.output_root
    assert manifest.provider_clients_available is False
    assert manifest.provider_calls == 0
    assert manifest.registry_access_allowed is False
    assert manifest.download_allowed is False
    assert manifest.local_runtime_allowed is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False
    assert manifest.requires_independent_v181_audit is True
    assert manifest.v182_canary_authorized is False


def test_v180_manifest_binds_complete_v178_stop_inventory() -> None:
    manifest = load_v180_dind_mount_repair_manifest(_MANIFEST)

    assert set(manifest.predecessor_result_file_sha256) == {
        "archive-receipt.json",
        "headroom.json",
        "local-builder-archive.json",
        "materialization-progress.json",
        "reference-patch-compatibility.json",
        "zero-provider-report.json",
    }
    assert (
        manifest.predecessor_result_file_sha256["materialization-progress.json"]
        == (manifest.predecessor_result_file_sha256["zero-provider-report.json"])
    )
    assert manifest.predecessor_audit_post_merge_all_eight_classes_passed is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("writable_bind_mount_count", 3),
        ("readonly_bind_mount_count", 0),
        ("readonly_mount_syntax_unchanged", False),
        ("repaired_write_mount_syntax", "type=bind,src=<path>,dst=<path>,rw=true"),
    ],
)
def test_v180_manifest_rejects_broader_mount_repair(
    tmp_path: Path, field: str, value: object
) -> None:
    document = json.loads(_MANIFEST.read_bytes())
    document[field] = value
    document["manifest_hash"] = content_hash(
        {key: item for key, item in document.items() if key != "manifest_hash"}
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v180_dind_mount_repair_manifest(path)


def test_v180_manifest_rejects_partial_predecessor_inventory(tmp_path: Path) -> None:
    document = json.loads(_MANIFEST.read_bytes())
    document["predecessor_result_file_sha256"].pop("headroom.json")
    document["manifest_hash"] = content_hash(
        {key: item for key, item in document.items() if key != "manifest_hash"}
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v180_dind_mount_repair_manifest(path)


def test_v180_manifest_loader_rejects_symlink(tmp_path: Path) -> None:
    linked = tmp_path / "manifest.json"
    linked.symlink_to(_MANIFEST)

    with pytest.raises(ConfigurationError, match="unsafe"):
        load_v180_dind_mount_repair_manifest(linked)
