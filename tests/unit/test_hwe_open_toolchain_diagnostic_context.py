from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.open_toolchain_diagnostic_context import (
    V186_IDENTITY,
    load_v186_diagnostic_context_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v186_diagnostic_context_refinement_v1.json"
)


def test_v186_manifest_is_task_free_and_keeps_all_lifecycle_gates_closed() -> None:
    manifest = load_v186_diagnostic_context_manifest(_MANIFEST)

    assert manifest.identity == V186_IDENTITY
    assert manifest.task_metadata_loaded is False
    assert manifest.hwe_image_inspected is False
    assert manifest.hwe_image_imported is False
    assert manifest.task_source_prepared is False
    assert manifest.verifier_run is False
    assert manifest.model_process_count == 0
    assert manifest.provider_calls == 0
    assert manifest.qualification_authorized is False
    assert manifest.canary_authorized is False
    assert manifest.repair_authorized is False
    assert manifest.arbitrary_token_hash_allowed is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False
    assert manifest.control_root_min_available_bytes == 9 * 1024**3
    assert manifest.data2_min_available_bytes == 50 * 1024**3
    assert len(manifest.command_dictionary) == 119
    assert set(manifest.builder_prerequisite_commands).isdisjoint(manifest.generated_commands)
    assert set(manifest.dockerfile_injected_commands).isdisjoint(
        manifest.builder_prerequisite_commands
    )


def test_v186_manifest_rejects_dictionary_or_content_hash_drift(tmp_path: Path) -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["command_dictionary"].append("unreviewed")
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid"):
        load_v186_diagnostic_context_manifest(changed)


def test_v186_manifest_rejects_symlink(tmp_path: Path) -> None:
    link = tmp_path / "manifest.json"
    link.symlink_to(_MANIFEST)

    with pytest.raises(ConfigurationError, match="unsafe"):
        load_v186_diagnostic_context_manifest(link)
