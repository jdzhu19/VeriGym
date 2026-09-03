from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV97RebuildIdentityScaffoldManifest,
    load_v92_official_matrix_manifest,
    load_v97_rebuild_identity_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v97_rebuild_identity_scaffold as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v97_rebuild_identity_scaffold_v1.json"
)


def test_v97_manifest_freezes_fresh_data2_runtime_complete_scaffold() -> None:
    manifest = load_v97_rebuild_identity_scaffold_manifest(_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV97RebuildIdentityScaffoldManifest)
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v97-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.workspace_runtime_image_id == HWE_WORKSPACE_RUNTIME_IMAGE_ID
    assert manifest.required_inner_image_count == 12
    assert manifest.runtime_prepare_task_count == 5
    assert manifest.historical_derived_image_identity_required is False
    assert manifest.historical_task_semantics_required is True
    assert manifest.v94_data_volume_reused is False
    assert manifest.provider_credentials_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v97_static_bindings_accept_only_the_audited_v94_stop() -> None:
    manifest = load_v97_rebuild_identity_scaffold_manifest(_MANIFEST)
    v92_manifest = load_v92_official_matrix_manifest(runner.V92_MANIFEST)
    report = runner.v94._load_json(runner.V92_REPORT)  # noqa: SLF001
    runner._validate_static_bindings(  # noqa: SLF001
        manifest,
        v92_manifest,
        report,
        v92_manifest_path=runner.V92_MANIFEST,
        v92_report_path=runner.V92_REPORT,
    )


def test_v97_rejects_a_relabelled_v94_provider_crossing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = load_v97_rebuild_identity_scaffold_manifest(_MANIFEST)
    v92_manifest = load_v92_official_matrix_manifest(runner.V92_MANIFEST)
    v92_report = runner.v94._load_json(runner.V92_REPORT)  # noqa: SLF001
    changed = copy.deepcopy(runner.v94._load_json(runner.V94_REPORT))  # noqa: SLF001
    changed["provider_calls"] = 1
    base = {key: value for key, value in changed.items() if key != "report_hash"}
    changed["report_hash"] = content_hash(base)
    changed_path = tmp_path / "v94-report.json"
    changed_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")
    manifest_value = manifest.model_dump(mode="json")
    manifest_value.update(
        {
            "v94_report_sha256": runner.v69._hash_file(changed_path),  # noqa: SLF001
            "v94_report_hash": changed["report_hash"],
        }
    )
    manifest_base = {key: value for key, value in manifest_value.items() if key != "manifest_hash"}
    manifest_value["manifest_hash"] = content_hash(manifest_base)
    changed_manifest = DeepSeekHarnessV97RebuildIdentityScaffoldManifest.model_validate(
        manifest_value
    )
    monkeypatch.setattr(runner, "V94_REPORT", changed_path)
    with pytest.raises(ConfigurationError, match="exact audited v94"):
        runner._validate_static_bindings(  # noqa: SLF001
            changed_manifest,
            v92_manifest,
            v92_report,
            v92_manifest_path=runner.V92_MANIFEST,
            v92_report_path=runner.V92_REPORT,
        )


def test_v97_base_configuration_is_scoped_and_restored() -> None:
    original_identity = runner.v94.IDENTITY
    original_output = runner.v94.OUTPUT_ROOT
    original_writer = runner.v94._write_progress  # noqa: SLF001
    with runner._v97_base_configuration():  # noqa: SLF001
        assert runner.v94.IDENTITY == runner.IDENTITY
        assert runner.v94.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert runner.v94._write_progress is runner._write_progress  # noqa: SLF001
    assert runner.v94.IDENTITY == original_identity
    assert runner.v94.OUTPUT_ROOT == original_output
    assert runner.v94._write_progress is original_writer  # noqa: SLF001


def test_v97_lock_projection_ignores_only_derived_identity_fields() -> None:
    old = {
        "task_id": "task",
        "scan_passed": True,
        "derived_command_image_id": "sha256:" + "1" * 64,
        "security_scan_id": "2" * 64,
        "lock_hash": "3" * 64,
    }
    new = {
        **old,
        "derived_command_image_id": "sha256:" + "4" * 64,
        "security_scan_id": "5" * 64,
        "lock_hash": "6" * 64,
    }
    ignored = ("derived_command_image_id", "security_scan_id", "lock_hash")
    assert runner._without(old, *ignored) == runner._without(new, *ignored)  # noqa: SLF001
    new["scan_passed"] = False
    assert runner._without(old, *ignored) != runner._without(new, *ignored)  # noqa: SLF001


def test_v97_contract_accepts_new_ids_only_after_all_semantic_gates() -> None:
    manifest = load_v97_rebuild_identity_scaffold_manifest(_MANIFEST)
    schedule = [item.task_id for item in manifest.schedule]
    task_receipts = [
        {
            "task_id": task_id,
            "historical_derived_image_identity_required": False,
            "historical_derived_command_image": "sha256:" + "1" * 64,
            "fresh_derived_command_image": "sha256:" + "2" * 64,
            "cross_build_derived_image_identity_equal": False,
            "command_image_lock_semantics_match": True,
            "security_scan_semantics_match": True,
        }
        for task_id in schedule
    ]
    common = {
        "source_commit": "1" * 40,
        "post_merge_main_run_id": 1,
        "runtime_receipt": {"receipt_hash": "2" * 64},
        "transfer": {
            "receipt_hash": "3" * 64,
            "controller_receipt_hash": "4" * 64,
            "workspace_runtime_receipt_hash": "5" * 64,
        },
        "task_materialization": {
            "receipt_hash": "a" * 64,
            "completed_task_ids": schedule,
            "task_count": 5,
            "all_base_failed_reference_passed": True,
            "all_command_images_v2_scanned": True,
            "all_historical_task_semantics_matched": True,
            "historical_derived_image_identity_required": False,
            "task_receipts": task_receipts,
        },
        "inventory": {
            "inventory_hash": "6" * 64,
            "required_image_count": 12,
            "workspace_runtime_image_present": True,
        },
        "runtime_preflight": {
            "receipt_hash": "7" * 64,
            "completed_task_ids": schedule,
            "task_count": 5,
        },
        "harness_preflight": {
            "receipt_hash": "8" * 64,
            "provider_request_started": False,
            "provider_call_count": 0,
            "provider_values_persisted_or_hashed": False,
        },
        "cleanup": {"receipt_hash": "9" * 64},
    }
    contract = runner._scaffold_contract(manifest, **common)  # noqa: SLF001
    assert contract["historical_derived_image_identity_required"] is False
    assert contract["all_historical_task_semantics_matched"] is True
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v98_audit"] is True

    task_receipts[0]["security_scan_semantics_match"] = False
    with pytest.raises(ConfigurationError, match="partial or provider-crossing"):
        runner._scaffold_contract(manifest, **common)  # noqa: SLF001


def test_v97_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001
