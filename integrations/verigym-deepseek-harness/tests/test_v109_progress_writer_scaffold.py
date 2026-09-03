from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV109ProgressWriterScaffoldManifest,
    load_v92_official_matrix_manifest,
    load_v109_progress_writer_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v109_progress_writer_scaffold as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v109_progress_writer_scaffold_v1.json"
)


def _manifest() -> DeepSeekHarnessV109ProgressWriterScaffoldManifest:
    return load_v109_progress_writer_scaffold_manifest(_MANIFEST)


def _fresh_images() -> dict[str, str]:
    return {
        item.task_id: "sha256:" + f"{index:x}" * 64
        for index, item in enumerate(_manifest().schedule, start=10)
    }


def _contract_inputs(
    manifest: DeepSeekHarnessV109ProgressWriterScaffoldManifest,
) -> dict[str, Any]:
    schedule = [item.task_id for item in manifest.schedule]
    fresh_images = _fresh_images()
    task_receipts = [
        {
            "format_id": "verigym_deepseek_harness_hwe_v109_task_materialization_receipt_v1",
            "identity": runner.IDENTITY,
            "task_id": task_id,
            "historical_derived_image_identity_required": False,
            "historical_derived_command_image": manifest.schedule[index].command_image,
            "fresh_derived_command_image": fresh_images[task_id],
            "cross_build_derived_image_identity_equal": False,
            "command_image_lock_semantics_match": True,
            "security_scan_semantics_match": True,
            "final_inventory_command_image_source": "fresh-materialization-lock",
            "final_inventory_command_image": fresh_images[task_id],
            "progress_writer_source": manifest.progress_writer_source,
        }
        for index, task_id in enumerate(schedule)
    ]
    return {
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
            "final_inventory_command_image_source": "fresh-materialization-locks",
            "final_inventory_fresh_command_images": fresh_images,
            "final_inventory_fresh_command_image_lock_hashes": {
                task_id: "b" * 64 for task_id in schedule
            },
            "final_inventory_fresh_command_image_count": 5,
        },
        "inventory": {
            "inventory_hash": "6" * 64,
            "required_image_count": 12,
            "required_image_ids": [
                manifest.controller_image_id,
                manifest.workspace_runtime_image_id,
                *(item.official_verifier_image for item in manifest.schedule),
                *fresh_images.values(),
            ],
            "workspace_runtime_image_present": True,
            "final_inventory_command_image_source": "fresh-materialization-locks",
            "fresh_command_images_by_task": fresh_images,
            "fresh_command_image_count": 5,
            "historical_command_images_required": False,
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


def test_v109_manifest_freezes_fresh_data2_progress_writer_scaffold() -> None:
    manifest = _manifest()
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v109-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.progress_writer_source == "v97-captured-v94-base-writer"
    assert manifest.final_inventory_command_image_source == "fresh-materialization-locks"
    assert manifest.final_inventory_fresh_command_image_count == 5
    assert manifest.v106_data_volume_reused is False
    assert manifest.v108_identity_retired is True
    assert manifest.provider_credentials_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v109_progress_writer_calls_the_real_frozen_base_writer(tmp_path: Path) -> None:
    progress = {
        "schema_version": "1.0",
        "format_id": "predecessor",
        "identity": runner.IDENTITY,
        "status": "completed_pending_independent_v107_audit",
        "provider_calls": 0,
    }
    runner._write_progress(tmp_path, progress)  # noqa: SLF001
    written = runner.v106.v103.v100.v97.v94._load_json(  # noqa: SLF001
        tmp_path / "execution-scaffold-progress.json"
    )
    assert written["format_id"] == "verigym_deepseek_harness_hwe_v109_scaffold_progress_v1"
    assert written["status"] == "completed_pending_independent_v110_audit"
    assert written["progress_writer_source"] == "v97-captured-v94-base-writer"
    assert written["provider_calls"] == 0
    assert (
        runner.v106.v103.v100.v97.v94._canonical_hash(  # noqa: SLF001
            written, "report_hash"
        )
        == written["report_hash"]
    )


def test_v109_static_bindings_accept_only_the_audited_v106_stop() -> None:
    manifest = _manifest()
    v92_manifest = load_v92_official_matrix_manifest(runner.v106.v103.v100.v97.V92_MANIFEST)
    report = runner.v106.v103.v100.v97.v94._load_json(  # noqa: SLF001
        runner.v106.v103.v100.v97.V92_REPORT
    )
    with (  # noqa: SLF001
        runner._v109_configuration(),
        runner.v106._v106_configuration(),
        runner.v106.v103._v103_configuration(),
        runner.v106.v103.v100._v100_base_configuration(),
    ):
        runner._validate_static_bindings(  # noqa: SLF001
            manifest,
            v92_manifest,
            report,
            v92_manifest_path=runner.v106.v103.v100.v97.V92_MANIFEST,
            v92_report_path=runner.v106.v103.v100.v97.V92_REPORT,
        )


def test_v109_configuration_is_scoped_and_restored() -> None:
    original_identity = runner.v106.IDENTITY
    original_output = runner.v106.OUTPUT_ROOT
    original_writer = runner.v106._write_progress  # noqa: SLF001
    original_inventory = runner.v106._inventory  # noqa: SLF001
    with runner._v109_configuration():  # noqa: SLF001
        assert runner.v106.IDENTITY == runner.IDENTITY
        assert runner.v106.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert runner.v106._write_progress is runner._write_progress  # noqa: SLF001
        assert runner.v106._inventory is runner._inventory  # noqa: SLF001
    assert runner.v106.IDENTITY == original_identity
    assert runner.v106.OUTPUT_ROOT == original_output
    assert runner.v106._write_progress is original_writer  # noqa: SLF001
    assert runner.v106._inventory is original_inventory  # noqa: SLF001


def test_v109_progress_writer_propagates_to_the_v94_execution_layer() -> None:
    original_writer = runner.v106.v103.v100.v97.v94._write_progress  # noqa: SLF001
    with runner._v109_configuration():  # noqa: SLF001
        assert runner.v106._write_progress is runner._write_progress  # noqa: SLF001
        with runner.v106._v106_configuration():  # noqa: SLF001
            assert runner.v106.v103._write_progress is runner._write_progress  # noqa: SLF001
            with runner.v106.v103._v103_configuration():  # noqa: SLF001
                assert runner.v106.v103.v100._write_progress is runner._write_progress  # noqa: SLF001
                with runner.v106.v103.v100._v100_base_configuration():  # noqa: SLF001
                    assert (
                        runner.v106.v103.v100.v97._write_progress  # noqa: SLF001
                        is runner._write_progress  # noqa: SLF001
                    )
                    with runner.v106.v103.v100.v97._v97_base_configuration():  # noqa: SLF001
                        assert (
                            runner.v106.v103.v100.v97.v94._write_progress  # noqa: SLF001
                            is runner._write_progress  # noqa: SLF001
                        )
    assert runner.v106.v103.v100.v97.v94._write_progress is original_writer  # noqa: SLF001


def test_v109_does_not_modify_the_frozen_v106_runner() -> None:
    assert runner.v69._hash_file(Path(runner.v106.__file__)) == (  # noqa: SLF001
        "0b2f1b8aee07d1448f26835e2cb7dcafd688ec325a4f24fddfdb3824bd3fd5b6"
    )


def test_v109_materializer_replaces_only_the_expected_v97_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def fake_materialize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        observed.append(kwargs["command_tag_version"])
        return {"task_id": "task"}

    monkeypatch.setattr(runner, "_V69_MATERIALIZE_TASK", fake_materialize)
    assert runner._v109_materialize_task(  # noqa: SLF001
        object(), command_tag_version="v97"
    ) == {"task_id": "task"}
    assert observed == ["v109"]
    with pytest.raises(ConfigurationError, match="unexpected command-image tag"):
        runner._v109_materialize_task(object(), command_tag_version="v106")  # noqa: SLF001


def test_v109_task_set_reseals_every_receipt_with_v109_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _manifest()
    fresh_images = _fresh_images()
    receipts = [
        {
            "format_id": "verigym_deepseek_harness_hwe_v103_task_materialization_receipt_v1",
            "identity": "deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1",
            "task_id": item.task_id,
            "final_inventory_command_image_source": "fresh-materialization-lock",
            "final_inventory_command_image": fresh_images[item.task_id],
            "task_receipt_hash": "1" * 64,
        }
        for item in manifest.schedule
    ]
    predecessor = {
        "format_id": "verigym_deepseek_harness_hwe_v106_task_materialization_set_v1",
        "identity": "deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1",
        "task_receipts": receipts,
        "task_receipt_hashes": ["1" * 64] * 5,
        "receipt_hash": "2" * 64,
    }
    monkeypatch.setattr(
        runner,
        "_V106_MATERIALIZE_TASKS",
        lambda *args, **kwargs: (predecessor, {}),
    )
    value, locks = runner._materialize_tasks(  # noqa: SLF001
        manifest,
        object(),  # type: ignore[arg-type]
        root=tmp_path,
    )
    assert locks == {}
    assert value["identity"] == runner.IDENTITY
    assert value["progress_writer_source"] == manifest.progress_writer_source
    assert all(receipt["identity"] == runner.IDENTITY for receipt in value["task_receipts"])
    assert all(
        receipt["format_id"] == "verigym_deepseek_harness_hwe_v109_task_materialization_receipt_v1"
        for receipt in value["task_receipts"]
    )
    assert value["task_receipt_hashes"] == [
        receipt["task_receipt_hash"] for receipt in value["task_receipts"]
    ]
    assert value["receipt_hash"] == content_hash(
        {key: item for key, item in value.items() if key != "receipt_hash"}
    )


def test_v109_inventory_preserves_fresh_binding_and_reseals_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    fresh_images = _fresh_images()
    required = {
        manifest.controller_image_id,
        manifest.workspace_runtime_image_id,
        *(item.official_verifier_image for item in manifest.schedule),
        *fresh_images.values(),
    }
    monkeypatch.setattr(runner.v106, "_ACTIVE_FRESH_COMMAND_IMAGES", fresh_images)
    monkeypatch.setattr(
        runner.v106.v103.v100.v97.v94.dind,
        "_inner",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, ("\n".join(sorted(required)) + "\n").encode(), b""
        ),
    )
    inventory = runner._inventory("dind", manifest)  # noqa: SLF001
    assert inventory["identity"] == runner.IDENTITY
    assert inventory["format_id"] == ("verigym_deepseek_harness_hwe_v109_execution_inventory_v1")
    assert inventory["required_image_count"] == 12
    assert inventory["fresh_command_images_by_task"] == fresh_images
    assert inventory["historical_command_images_required"] is False


def test_v109_contract_requires_v110_audit_and_retires_v108() -> None:
    manifest = _manifest()
    common = _contract_inputs(manifest)
    contract = runner._scaffold_contract(manifest, **common)  # noqa: SLF001
    assert contract["v107_audit_completed"] is True
    assert contract["v106_data_volume_reused"] is False
    assert contract["v108_identity_retired"] is True
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v110_audit"] is True
    assert "requires_independent_v107_audit" not in contract


def test_v109_records_the_fresh_authorization_post_merge_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_materialize(arguments: argparse.Namespace) -> dict[str, Any]:
        observed["post_merge_main_run_id"] = arguments.post_merge_main_run_id
        return {"status": "observed"}

    monkeypatch.setattr(runner.v106, "materialize", fake_materialize)
    result = runner.materialize(argparse.Namespace(post_merge_main_run_id=123456789))
    assert result == {"status": "observed"}
    assert observed == {"post_merge_main_run_id": 123456789}


def test_v109_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001
