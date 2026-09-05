from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain_build_diagnostic import (
    V182_IDENTITY,
    load_v182_build_diagnostic_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v182_bounded_open_build_diagnostic_v1.json"
)


def test_v182_manifest_is_task_free_and_keeps_all_lifecycle_gates_closed() -> None:
    manifest = load_v182_build_diagnostic_manifest(_MANIFEST)

    assert manifest.identity == V182_IDENTITY
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


def test_v182_manifest_rejects_category_or_content_hash_drift(tmp_path: Path) -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["diagnostic_categories"] = list(reversed(value["diagnostic_categories"]))
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v182_build_diagnostic_manifest(changed)


def test_v182_manifest_rejects_symlink(tmp_path: Path) -> None:
    link = tmp_path / "manifest.json"
    link.symlink_to(_MANIFEST)

    with pytest.raises(ConfigurationError, match="unsafe"):
        load_v182_build_diagnostic_manifest(link)
