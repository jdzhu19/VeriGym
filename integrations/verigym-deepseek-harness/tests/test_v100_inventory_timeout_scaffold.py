from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV100InventoryTimeoutScaffoldManifest,
    load_v92_official_matrix_manifest,
    load_v100_inventory_timeout_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v100_inventory_timeout_scaffold as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v100_inventory_timeout_scaffold_v1.json"
)


def _manifest() -> DeepSeekHarnessV100InventoryTimeoutScaffoldManifest:
    return load_v100_inventory_timeout_scaffold_manifest(_MANIFEST)


def test_v100_manifest_freezes_fresh_data2_timeout_scaffold() -> None:
    manifest = _manifest()
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v100-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.toolchain_inventory_create_timeout_seconds == 300
    assert manifest.toolchain_inventory_inspect_timeout_seconds == 300
    assert manifest.toolchain_inventory_execute_timeout_seconds == 120
    assert manifest.toolchain_inventory_remove_timeout_seconds == 300
    assert manifest.v97_data_volume_reused is False
    assert manifest.v99_identity_retired is True
    assert manifest.provider_credentials_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v100_static_bindings_accept_only_the_audited_v97_stop() -> None:
    manifest = _manifest()
    v92_manifest = load_v92_official_matrix_manifest(runner.v97.V92_MANIFEST)
    report = runner.v97.v94._load_json(runner.v97.V92_REPORT)  # noqa: SLF001
    with runner._v100_base_configuration():  # noqa: SLF001
        runner._validate_static_bindings(  # noqa: SLF001
            manifest,
            v92_manifest,
            report,
            v92_manifest_path=runner.v97.V92_MANIFEST,
            v92_report_path=runner.v97.V92_REPORT,
        )


def test_v100_rejects_a_relabelled_v97_provider_crossing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _manifest()
    v92_manifest = load_v92_official_matrix_manifest(runner.v97.V92_MANIFEST)
    v92_report = runner.v97.v94._load_json(runner.v97.V92_REPORT)  # noqa: SLF001
    changed = copy.deepcopy(runner.v97.v94._load_json(runner.V97_REPORT))  # noqa: SLF001
    changed["provider_calls"] = 1
    changed["report_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "report_hash"}
    )
    changed_path = tmp_path / "v97-report.json"
    changed_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")
    manifest_value = manifest.model_dump(mode="json")
    manifest_value.update(
        {
            "v97_report_sha256": runner.v69._hash_file(changed_path),  # noqa: SLF001
            "v97_report_hash": changed["report_hash"],
        }
    )
    manifest_value["manifest_hash"] = content_hash(
        {key: value for key, value in manifest_value.items() if key != "manifest_hash"}
    )
    changed_manifest = DeepSeekHarnessV100InventoryTimeoutScaffoldManifest.model_validate(
        manifest_value
    )
    monkeypatch.setattr(runner, "V97_REPORT", changed_path)
    with (
        runner._v100_base_configuration(),
        pytest.raises(ConfigurationError, match="exact audited v97"),
    ):
        runner._validate_static_bindings(  # noqa: SLF001
            changed_manifest,
            v92_manifest,
            v92_report,
            v92_manifest_path=runner.v97.V92_MANIFEST,
            v92_report_path=runner.v97.V92_REPORT,
        )


def test_v100_base_configuration_is_scoped_and_restored() -> None:
    original_identity = runner.v97.IDENTITY
    original_output = runner.v97.OUTPUT_ROOT
    original_writer = runner.v97._write_progress  # noqa: SLF001
    with runner._v100_base_configuration():  # noqa: SLF001
        assert runner.v97.IDENTITY == runner.IDENTITY
        assert runner.v97.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert runner.v97._write_progress is runner._write_progress  # noqa: SLF001
    assert runner.v97.IDENTITY == original_identity
    assert runner.v97.OUTPUT_ROOT == original_output
    assert runner.v97._write_progress is original_writer  # noqa: SLF001


def test_v100_does_not_modify_the_frozen_v97_runner() -> None:
    assert runner.v69._hash_file(Path(runner.v97.__file__)) == (  # noqa: SLF001
        "bc7e7c0df6337bf66411a5d5be49ace4fc7415c52263a54ea06f91fa6b39fbea"
    )


def test_v100_inventory_commands_use_only_their_manifest_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    observed: list[tuple[list[str], int]] = []

    def fake_bounded(
        command: list[str],
        *,
        timeout: int,
        return_stdout: bool = False,
        require_empty: bool = False,
    ) -> bytes:
        del return_stdout, require_empty
        observed.append((command, timeout))
        return b"container-id\n"

    monkeypatch.setattr(runner, "_V69_BOUNDED_COMMAND", fake_bounded)
    create = [
        "docker",
        "create",
        "--label",
        f"org.verigym.owner={runner.IDENTITY}",
        "--label",
        "org.verigym.role=toolchain_inventory",
    ]
    remove = ["docker", "container", "rm", "--force", "container-id"]
    execute = ["docker", "start", "--attach", "container-id"]
    other = ["docker", "image", "inspect", "image-id"]

    runner._inventory_bounded_command(  # noqa: SLF001
        manifest, create, timeout=30, return_stdout=True
    )
    runner._inventory_bounded_command(  # noqa: SLF001
        manifest, remove, timeout=30, return_stdout=True
    )
    runner._inventory_bounded_command(  # noqa: SLF001
        manifest, execute, timeout=120, return_stdout=True
    )
    runner._inventory_bounded_command(manifest, other, timeout=30)  # noqa: SLF001
    assert [timeout for _command, timeout in observed] == [300, 300, 120, 30]

    with pytest.raises(ConfigurationError, match="create inherited an unexpected bound"):
        runner._inventory_bounded_command(manifest, create, timeout=31)  # noqa: SLF001


def test_v100_inventory_inspection_uses_the_manifest_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[int] = []

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        del args
        observed.append(kwargs["timeout"])
        return subprocess.CompletedProcess([], 0, b'[{"Id":"container-id"}]', b"")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._inventory_docker_inspect(_manifest(), "container-id") == {  # noqa: SLF001
        "Id": "container-id"
    }
    assert observed == [300]


def test_v100_inventory_patch_is_scoped_and_retags_images() -> None:
    manifest = _manifest()
    original_bounded = runner.v69._bounded_command  # noqa: SLF001
    original_inspect = runner.v69._docker_inspect  # noqa: SLF001
    original_materialize = runner.v69._materialize_task  # noqa: SLF001
    with runner._v100_inventory_controls(manifest):  # noqa: SLF001
        assert runner.v69._bounded_command is not original_bounded  # noqa: SLF001
        assert runner.v69._docker_inspect is not original_inspect  # noqa: SLF001
        assert runner.v69._materialize_task is runner._v100_materialize_task  # noqa: SLF001
    assert runner.v69._bounded_command is original_bounded  # noqa: SLF001
    assert runner.v69._docker_inspect is original_inspect  # noqa: SLF001
    assert runner.v69._materialize_task is original_materialize  # noqa: SLF001


def test_v100_materializer_replaces_only_the_expected_v97_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def fake_materialize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        observed.append(kwargs["command_tag_version"])
        return {"task_id": "task"}

    monkeypatch.setattr(runner, "_V69_MATERIALIZE_TASK", fake_materialize)
    assert runner._v100_materialize_task(  # noqa: SLF001
        object(), command_tag_version="v97"
    ) == {"task_id": "task"}
    assert observed == ["v100"]
    with pytest.raises(ConfigurationError, match="unexpected command-image tag"):
        runner._v100_materialize_task(object(), command_tag_version="v94")  # noqa: SLF001


def test_v100_task_set_reseals_all_timeout_bindings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _manifest()
    receipts = [
        {"task_id": item.task_id, "task_receipt_hash": "1" * 64} for item in manifest.schedule
    ]
    predecessor = {
        "format_id": "predecessor",
        "identity": "predecessor",
        "task_receipts": receipts,
        "task_receipt_hashes": ["1" * 64] * 5,
        "task_count": 5,
        "receipt_hash": "2" * 64,
    }
    monkeypatch.setattr(
        runner,
        "_V97_MATERIALIZE_TASKS",
        lambda *args, **kwargs: (predecessor, {}),
    )
    value, locks = runner._materialize_tasks(  # noqa: SLF001
        manifest,
        object(),  # type: ignore[arg-type]
        upstream=object(),
        v79_manifest=object(),
        v79_contract={},
        instances={},
        archive_root=tmp_path,
        rg_binary=tmp_path / "rg",
        rg_archive=tmp_path / "rg.tar.gz",
        root=tmp_path,
    )
    assert locks == {}
    assert value["identity"] == runner.IDENTITY
    assert value["toolchain_inventory_create_timeout_seconds"] == 300
    assert value["toolchain_inventory_execute_timeout_seconds"] == 120
    sealed_receipts = value["task_receipts"]
    assert all(
        item["toolchain_inventory_remove_timeout_seconds"] == 300 for item in sealed_receipts
    )
    assert value["task_receipt_hashes"] == [item["task_receipt_hash"] for item in sealed_receipts]
    assert (
        content_hash({key: item for key, item in value.items() if key != "receipt_hash"})
        == value["receipt_hash"]
    )


def test_v100_contract_requires_complete_semantic_gates() -> None:
    manifest = _manifest()
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
        "post_merge_main_run_id": 33782913003,
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
    assert contract["v99_identity_retired"] is True
    assert contract["v100_tasks_materialized_from_completed_local_archives"] is True
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v101_audit"] is True

    task_receipts[0]["security_scan_semantics_match"] = False
    with pytest.raises(ConfigurationError, match="partial or provider-crossing"):
        runner._scaffold_contract(manifest, **common)  # noqa: SLF001


def test_v100_rejects_any_other_post_merge_run_before_execution() -> None:
    with pytest.raises(ConfigurationError, match="exact audited post-merge main run"):
        runner.materialize(argparse.Namespace(post_merge_main_run_id=1))


def test_v100_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001
