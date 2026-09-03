from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
    load_v92_official_matrix_manifest,
    load_v112_data2_control_headroom_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v112_data2_control_headroom_scaffold as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v112_data2_control_headroom_scaffold_v1.json"
)


def _manifest() -> DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest:
    return load_v112_data2_control_headroom_scaffold_manifest(_MANIFEST)


def _fresh_images() -> dict[str, str]:
    return {
        item.task_id: "sha256:" + f"{index:x}" * 64
        for index, item in enumerate(_manifest().schedule, start=10)
    }


def _headroom_receipt(status: str = "passed") -> dict[str, Any]:
    filesystems = [
        {
            "role": role,
            "minimum_free_bytes": values[0],
            "observed_free_bytes": values[0] + 1,
            "minimum_free_inodes": values[1],
            "observed_free_inodes": values[1] + 1,
            "bytes_satisfied": True,
            "inodes_satisfied": True,
        }
        for role, values in runner._HEADROOM_REQUIREMENTS.items()  # noqa: SLF001
    ]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_command_image_materialization_headroom_v1",
        "status": status,
        "policy": {
            "absolute_thresholds": True,
            "percentage_thresholds": False,
            "planned_command_image_count": 6,
            "maximum_bytes_per_command_image": 8 * 1024**3,
            "docker_headroom_multiplier": 2,
        },
        "filesystems": filesystems,
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_command_output_persisted": False,
    }
    return {**base, "preflight_hash": content_hash(base)}


def _bind_temporary_data2_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    paths = {
        "control": tmp_path / "control",
        "data": tmp_path / "docker" / "data",
        "socket": tmp_path / "docker" / "socket",
        "runtime": tmp_path / "runtime",
        "scratch": tmp_path / "scratch",
        "output_parent": tmp_path / "experiments",
    }
    for path in paths.values():
        path.mkdir(parents=True)
    monkeypatch.setattr(runner, "_DATA2_ROOT", tmp_path)
    monkeypatch.setattr(runner, "CONTROL_ROOT", paths["control"])
    monkeypatch.setattr(runner, "DIND_DATA_BACKING", paths["data"])
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", paths["socket"])
    monkeypatch.setattr(runner, "RUNTIME_TMP", paths["runtime"])
    monkeypatch.setattr(runner, "OUTPUT_ROOT", paths["output_parent"] / "v112")
    monkeypatch.setattr(runner.v109.v106.v103.v100.v97.v94, "SCRATCH_ROOT", paths["scratch"])
    return paths


def _contract_inputs(
    manifest: DeepSeekHarnessV112Data2ControlHeadroomScaffoldManifest,
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


def test_v112_manifest_freezes_fresh_data2_control_headroom_scaffold() -> None:
    manifest = _manifest()
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.inherited_control_headroom_root == "/"
    assert manifest.control_headroom_root == str(runner.CONTROL_ROOT)
    assert manifest.system_root_headroom_required is False
    assert manifest.all_campaign_writable_roots_under_data2 is True
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v112-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.v109_data_volume_reused is False
    assert manifest.v111_identity_retired is True
    assert manifest.provider_credentials_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v112_substitutes_only_the_control_root_and_preserves_thresholds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _bind_temporary_data2_paths(monkeypatch, tmp_path)
    observed: dict[str, Path] = {}

    def fake_headroom(**kwargs: Path) -> dict[str, Any]:
        observed.update(kwargs)
        return _headroom_receipt()

    monkeypatch.setattr(runner, "_V94_REQUIRE_MATERIALIZATION_HEADROOM", fake_headroom)
    result = runner._data2_control_headroom(  # noqa: SLF001
        control_root=Path("/"),
        docker_root=paths["data"],
        scratch_root=paths["scratch"],
        output_parent=paths["output_parent"],
    )
    assert observed == {
        "control_root": paths["control"],
        "docker_root": paths["data"],
        "scratch_root": paths["scratch"],
        "output_parent": paths["output_parent"],
    }
    assert result["control_headroom_root"] == str(paths["control"])
    assert result["inherited_control_headroom_root"] == "/"
    assert result["system_root_headroom_required"] is False
    assert result["thresholds_changed"] is False
    assert {
        item["role"]: (item["minimum_free_bytes"], item["minimum_free_inodes"])
        for item in result["filesystems"]
    } == runner._HEADROOM_REQUIREMENTS  # noqa: SLF001
    assert result["preflight_hash"] == content_hash(
        {key: value for key, value in result.items() if key != "preflight_hash"}
    )


@pytest.mark.parametrize("field", ["control_root", "docker_root", "scratch_root", "output_parent"])
def test_v112_rejects_any_unexpected_inherited_headroom_path(
    field: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _bind_temporary_data2_paths(monkeypatch, tmp_path)
    arguments = {
        "control_root": Path("/"),
        "docker_root": paths["data"],
        "scratch_root": paths["scratch"],
        "output_parent": paths["output_parent"],
    }
    arguments[field] = tmp_path / "unexpected"
    with pytest.raises(ConfigurationError, match="arguments changed"):
        runner._data2_control_headroom(**arguments)  # noqa: SLF001


def test_v112_rejects_a_changed_threshold_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _bind_temporary_data2_paths(monkeypatch, tmp_path)
    changed = _headroom_receipt()
    changed["filesystems"][0]["minimum_free_bytes"] -= 1
    monkeypatch.setattr(
        runner,
        "_V94_REQUIRE_MATERIALIZATION_HEADROOM",
        lambda **kwargs: changed,
    )
    with pytest.raises(ConfigurationError, match="changed materialization headroom thresholds"):
        runner._data2_control_headroom(  # noqa: SLF001
            control_root=Path("/"),
            docker_root=paths["data"],
            scratch_root=paths["scratch"],
            output_parent=paths["output_parent"],
        )


def test_v112_configuration_propagates_headroom_to_v94_and_restores() -> None:
    v94 = runner.v109.v106.v103.v100.v97.v94
    original = v94.require_materialization_headroom
    with runner._v112_configuration():  # noqa: SLF001
        assert runner.v109.IDENTITY == runner.IDENTITY
        assert runner.v109.CONTROL_ROOT == runner.CONTROL_ROOT
        assert v94.require_materialization_headroom is runner._data2_control_headroom  # noqa: SLF001
        with runner.v109._v109_configuration():  # noqa: SLF001
            with runner.v109.v106._v106_configuration():  # noqa: SLF001
                with runner.v109.v106.v103._v103_configuration():  # noqa: SLF001
                    with runner.v109.v106.v103.v100._v100_base_configuration():  # noqa: SLF001
                        with runner.v109.v106.v103.v100.v97._v97_base_configuration():  # noqa: SLF001
                            assert (
                                v94.require_materialization_headroom
                                is runner._data2_control_headroom  # noqa: SLF001
                            )
                            assert v94.CONTROL_ROOT == runner.CONTROL_ROOT
    assert v94.require_materialization_headroom is original


def test_v112_progress_writer_calls_the_frozen_base_writer(tmp_path: Path) -> None:
    progress = {
        "schema_version": "1.0",
        "format_id": "predecessor",
        "identity": runner.IDENTITY,
        "status": "completed_pending_independent_v110_audit",
        "provider_calls": 0,
    }
    runner._write_progress(tmp_path, progress)  # noqa: SLF001
    written = runner.v109.v106.v103.v100.v97.v94._load_json(  # noqa: SLF001
        tmp_path / "execution-scaffold-progress.json"
    )
    assert written["format_id"] == "verigym_deepseek_harness_hwe_v112_scaffold_progress_v1"
    assert written["status"] == "completed_pending_independent_v113_audit"
    assert written["control_headroom_root"] == str(runner.CONTROL_ROOT)
    assert written["system_root_headroom_required"] is False
    assert written["provider_calls"] == 0
    assert (
        runner.v109.v106.v103.v100.v97.v94._canonical_hash(  # noqa: SLF001
            written, "report_hash"
        )
        == written["report_hash"]
    )


def test_v112_static_bindings_accept_only_the_audited_v109_stop() -> None:
    manifest = _manifest()
    v92_manifest = load_v92_official_matrix_manifest(runner.v109.v106.v103.v100.v97.V92_MANIFEST)
    report = runner.v109.v106.v103.v100.v97.v94._load_json(  # noqa: SLF001
        runner.v109.v106.v103.v100.v97.V92_REPORT
    )
    with (  # noqa: SLF001
        runner._v112_configuration(),
        runner.v109._v109_configuration(),
        runner.v109.v106._v106_configuration(),
        runner.v109.v106.v103._v103_configuration(),
        runner.v109.v106.v103.v100._v100_base_configuration(),
    ):
        runner._validate_static_bindings(  # noqa: SLF001
            manifest,
            v92_manifest,
            report,
            v92_manifest_path=runner.v109.v106.v103.v100.v97.V92_MANIFEST,
            v92_report_path=runner.v109.v106.v103.v100.v97.V92_REPORT,
        )


def test_v112_does_not_modify_the_frozen_v109_runner() -> None:
    assert runner.v69._hash_file(Path(runner.v109.__file__)) == (  # noqa: SLF001
        "a666fb6cff83bf6634125aa91058000e951448b761a31d123793c91538258208"
    )


def test_v112_materializer_replaces_only_the_expected_v97_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def fake_materialize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        observed.append(kwargs["command_tag_version"])
        return {"task_id": "task"}

    monkeypatch.setattr(runner, "_V69_MATERIALIZE_TASK", fake_materialize)
    assert runner._v112_materialize_task(  # noqa: SLF001
        object(), command_tag_version="v97"
    ) == {"task_id": "task"}
    assert observed == ["v112"]
    with pytest.raises(ConfigurationError, match="unexpected command-image tag"):
        runner._v112_materialize_task(object(), command_tag_version="v109")  # noqa: SLF001


def test_v112_task_set_reseals_every_receipt_with_v112_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _manifest()
    receipts = [
        {
            "format_id": "verigym_deepseek_harness_hwe_v109_task_materialization_receipt_v1",
            "identity": "deepseek-harness-hwe-v109-progress-writer-scaffold-v1",
            "task_id": item.task_id,
            "task_receipt_hash": "1" * 64,
        }
        for item in manifest.schedule
    ]
    predecessor = {
        "format_id": "verigym_deepseek_harness_hwe_v109_task_materialization_set_v1",
        "identity": "deepseek-harness-hwe-v109-progress-writer-scaffold-v1",
        "task_receipts": receipts,
        "task_receipt_hashes": ["1" * 64] * 5,
        "receipt_hash": "2" * 64,
    }
    monkeypatch.setattr(
        runner, "_V109_MATERIALIZE_TASKS", lambda *args, **kwargs: (predecessor, {})
    )
    value, locks = runner._materialize_tasks(  # noqa: SLF001
        manifest,
        object(),  # type: ignore[arg-type]
        root=tmp_path,
    )
    assert locks == {}
    assert value["identity"] == runner.IDENTITY
    assert value["control_headroom_root"] == str(runner.CONTROL_ROOT)
    assert value["system_root_headroom_required"] is False
    assert all(receipt["identity"] == runner.IDENTITY for receipt in value["task_receipts"])
    assert all(
        receipt["format_id"] == "verigym_deepseek_harness_hwe_v112_task_materialization_receipt_v1"
        for receipt in value["task_receipts"]
    )
    assert value["receipt_hash"] == content_hash(
        {key: item for key, item in value.items() if key != "receipt_hash"}
    )


def test_v112_contract_requires_v113_audit_and_retires_v111() -> None:
    manifest = _manifest()
    contract = runner._scaffold_contract(manifest, **_contract_inputs(manifest))  # noqa: SLF001
    assert contract["v110_audit_completed"] is True
    assert contract["v109_data_volume_reused"] is False
    assert contract["v111_identity_retired"] is True
    assert contract["system_root_headroom_required"] is False
    assert contract["headroom_thresholds_changed"] is False
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v113_audit"] is True
    assert "requires_independent_v110_audit" not in contract


def test_v112_records_the_fresh_authorization_post_merge_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_materialize(arguments: argparse.Namespace) -> dict[str, Any]:
        observed["post_merge_main_run_id"] = arguments.post_merge_main_run_id
        return {"status": "observed"}

    monkeypatch.setattr(runner.v109, "materialize", fake_materialize)
    result = runner.materialize(argparse.Namespace(post_merge_main_run_id=123456789))
    assert result == {"status": "observed"}
    assert observed == {"post_merge_main_run_id": 123456789}


def test_v112_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001
