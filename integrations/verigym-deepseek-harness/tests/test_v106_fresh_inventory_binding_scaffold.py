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
    DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    load_v92_official_matrix_manifest,
    load_v106_fresh_inventory_binding_scaffold_manifest,
)
from verigym.hwe.image_lock import HweCommandImageLock

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v106_fresh_inventory_binding_scaffold_v1.json"
)


def _manifest() -> DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest:
    return load_v106_fresh_inventory_binding_scaffold_manifest(_MANIFEST)


def _fresh_images() -> dict[str, str]:
    return {
        item.task_id: "sha256:" + f"{index:x}" * 64
        for index, item in enumerate(_manifest().schedule, start=10)
    }


def _valid_inventory_output(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
    fresh_images: dict[str, str],
) -> bytes:
    image_ids = {
        manifest.controller_image_id,
        manifest.workspace_runtime_image_id,
        *(item.official_verifier_image for item in manifest.schedule),
        *fresh_images.values(),
    }
    return ("\n".join(sorted(image_ids)) + "\n").encode()


def _contract_inputs(
    manifest: DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest,
) -> dict[str, Any]:
    schedule = [item.task_id for item in manifest.schedule]
    fresh_images = _fresh_images()
    task_receipts = [
        {
            "task_id": task_id,
            "historical_derived_image_identity_required": False,
            "historical_derived_command_image": manifest.schedule[index].command_image,
            "fresh_derived_command_image": fresh_images[task_id],
            "cross_build_derived_image_identity_equal": False,
            "command_image_lock_semantics_match": True,
            "security_scan_semantics_match": True,
            "final_inventory_command_image_source": "fresh-materialization-lock",
            "final_inventory_command_image": fresh_images[task_id],
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


def test_v106_manifest_freezes_fresh_data2_inventory_binding() -> None:
    manifest = _manifest()
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v106-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.final_inventory_command_image_source == "fresh-materialization-locks"
    assert manifest.final_inventory_fresh_command_image_count == 5
    assert manifest.required_inner_image_count == 12
    assert manifest.v103_data_volume_reused is False
    assert manifest.v105_identity_retired is True
    assert manifest.provider_credentials_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v106_static_bindings_accept_only_the_audited_v103_stop() -> None:
    manifest = _manifest()
    v92_manifest = load_v92_official_matrix_manifest(runner.v103.v100.v97.V92_MANIFEST)
    report = runner.v103.v100.v97.v94._load_json(  # noqa: SLF001
        runner.v103.v100.v97.V92_REPORT
    )
    with (  # noqa: SLF001
        runner._v106_configuration(),
        runner.v103._v103_configuration(),
        runner.v103.v100._v100_base_configuration(),
    ):
        runner._validate_static_bindings(  # noqa: SLF001
            manifest,
            v92_manifest,
            report,
            v92_manifest_path=runner.v103.v100.v97.V92_MANIFEST,
            v92_report_path=runner.v103.v100.v97.V92_REPORT,
        )


def test_v106_rejects_a_relabelled_v103_provider_crossing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _manifest()
    v92_manifest = load_v92_official_matrix_manifest(runner.v103.v100.v97.V92_MANIFEST)
    v92_report = runner.v103.v100.v97.v94._load_json(  # noqa: SLF001
        runner.v103.v100.v97.V92_REPORT
    )
    changed = copy.deepcopy(
        runner.v103.v100.v97.v94._load_json(runner.V103_REPORT)  # noqa: SLF001
    )
    changed["provider_calls"] = 1
    changed["report_hash"] = content_hash(
        {key: value for key, value in changed.items() if key != "report_hash"}
    )
    changed_path = tmp_path / "v103-report.json"
    changed_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")
    manifest_value = manifest.model_dump(mode="json")
    manifest_value.update(
        {
            "v103_report_sha256": runner.v69._hash_file(changed_path),  # noqa: SLF001
            "v103_report_hash": changed["report_hash"],
        }
    )
    manifest_value["manifest_hash"] = content_hash(
        {key: value for key, value in manifest_value.items() if key != "manifest_hash"}
    )
    changed_manifest = DeepSeekHarnessV106FreshInventoryBindingScaffoldManifest.model_validate(
        manifest_value
    )
    monkeypatch.setattr(runner, "V103_REPORT", changed_path)
    monkeypatch.setattr(runner, "V103_PROGRESS", changed_path)
    with (  # noqa: SLF001
        runner._v106_configuration(),
        runner.v103._v103_configuration(),
        runner.v103.v100._v100_base_configuration(),
        pytest.raises(ConfigurationError, match="exact audited v103"),
    ):
        runner._validate_static_bindings(  # noqa: SLF001
            changed_manifest,
            v92_manifest,
            v92_report,
            v92_manifest_path=runner.v103.v100.v97.V92_MANIFEST,
            v92_report_path=runner.v103.v100.v97.V92_REPORT,
        )


def test_v106_configuration_is_scoped_and_resets_fresh_inventory() -> None:
    original_identity = runner.v103.IDENTITY
    original_output = runner.v103.OUTPUT_ROOT
    original_inventory = runner.v103._inventory  # noqa: SLF001
    with runner._v106_configuration():  # noqa: SLF001
        assert runner.v103.IDENTITY == runner.IDENTITY
        assert runner.v103.OUTPUT_ROOT == runner.OUTPUT_ROOT
        assert runner.v103._inventory is runner._inventory  # noqa: SLF001
        runner._ACTIVE_FRESH_COMMAND_IMAGES = _fresh_images()  # noqa: SLF001
    assert runner.v103.IDENTITY == original_identity
    assert runner.v103.OUTPUT_ROOT == original_output
    assert runner.v103._inventory is original_inventory  # noqa: SLF001
    assert runner._ACTIVE_FRESH_COMMAND_IMAGES is None  # noqa: SLF001


def test_v106_does_not_modify_the_frozen_v103_runner() -> None:
    assert runner.v69._hash_file(Path(runner.v103.__file__)) == (  # noqa: SLF001
        "903eed74f6aa982824addd699bd96d77c396ecaad275602dc810eaf72da42d91"
    )


def test_v106_materializer_replaces_only_the_expected_v97_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def fake_materialize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        observed.append(kwargs["command_tag_version"])
        return {"task_id": "task"}

    monkeypatch.setattr(runner, "_V69_MATERIALIZE_TASK", fake_materialize)
    assert runner._v106_materialize_task(  # noqa: SLF001
        object(), command_tag_version="v97"
    ) == {"task_id": "task"}
    assert observed == ["v106"]
    with pytest.raises(ConfigurationError, match="unexpected command-image tag"):
        runner._v106_materialize_task(object(), command_tag_version="v103")  # noqa: SLF001


def test_v106_task_set_binds_fresh_locks_to_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _manifest()
    predecessor = copy.deepcopy(
        runner.v103.v100.v97.v94._load_json(  # noqa: SLF001
            runner.V103_TASK_MATERIALIZATION
        )
    )
    locks = {
        item.task_id: HweCommandImageLock.model_validate_json(
            (runner.V103_ROOT / "image-locks" / f"pr-{item.pr_number}.json").read_bytes()
        )
        for item in manifest.schedule
    }
    monkeypatch.setattr(
        runner,
        "_V103_MATERIALIZE_TASKS",
        lambda *args, **kwargs: (predecessor, locks),
    )
    monkeypatch.setattr(runner, "_ACTIVE_FRESH_COMMAND_IMAGES", None)
    value, observed_locks = runner._materialize_tasks(  # noqa: SLF001
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
    expected = {task_id: lock.derived_command_image_id for task_id, lock in locks.items()}
    assert observed_locks == locks
    assert value["final_inventory_command_image_source"] == "fresh-materialization-locks"
    assert value["final_inventory_fresh_command_images"] == expected
    assert value["final_inventory_fresh_command_image_count"] == 5
    assert runner._ACTIVE_FRESH_COMMAND_IMAGES == expected  # noqa: SLF001
    assert value["receipt_hash"] == content_hash(
        {key: item for key, item in value.items() if key != "receipt_hash"}
    )

    changed = copy.deepcopy(predecessor)
    changed["task_receipts"][0]["agent_command_image"] = manifest.schedule[0].command_image
    monkeypatch.setattr(
        runner,
        "_V103_MATERIALIZE_TASKS",
        lambda *args, **kwargs: (changed, locks),
    )
    monkeypatch.setattr(runner, "_ACTIVE_FRESH_COMMAND_IMAGES", None)
    with pytest.raises(ConfigurationError, match="receipt binding changed"):
        runner._materialize_tasks(  # noqa: SLF001
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


def test_v106_inventory_requires_fresh_ids_and_not_historical_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    fresh_images = _fresh_images()
    monkeypatch.setattr(runner, "_ACTIVE_FRESH_COMMAND_IMAGES", fresh_images)
    monkeypatch.setattr(
        runner.v103.v100.v97.v94.dind,
        "_inner",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, _valid_inventory_output(manifest, fresh_images), b""
        ),
    )
    inventory = runner._inventory("dind", manifest)  # noqa: SLF001
    assert inventory["required_image_count"] == 12
    assert inventory["fresh_command_images_by_task"] == fresh_images
    assert inventory["historical_command_images_required"] is False
    assert not set(item.command_image for item in manifest.schedule).intersection(
        inventory["required_image_ids"]
    )


def test_v106_inventory_rejects_historical_ids_in_place_of_fresh_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    fresh_images = _fresh_images()
    historical_output = (
        "\n".join(
            sorted(
                {
                    manifest.controller_image_id,
                    manifest.workspace_runtime_image_id,
                    *(item.official_verifier_image for item in manifest.schedule),
                    *(item.command_image for item in manifest.schedule),
                }
            )
        )
        + "\n"
    ).encode()
    monkeypatch.setattr(runner, "_ACTIVE_FRESH_COMMAND_IMAGES", fresh_images)
    monkeypatch.setattr(
        runner.v103.v100.v97.v94.dind,
        "_inner",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, historical_output, b""),
    )
    with pytest.raises(ConfigurationError, match="incomplete or inconsistent"):
        runner._inventory("dind", manifest)  # noqa: SLF001


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "message"),
    [
        (1, b"", b"", "command failed"),
        (0, b"sha256:" + b"1" * 64, b"warning", "command failed"),
        (0, b"not-a-digest\n", b"", "malformed"),
        (0, b"\xff\n", b"", "malformed"),
    ],
)
def test_v106_inventory_rejects_process_and_encoding_errors(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    message: str,
) -> None:
    monkeypatch.setattr(runner, "_ACTIVE_FRESH_COMMAND_IMAGES", _fresh_images())
    monkeypatch.setattr(
        runner.v103.v100.v97.v94.dind,
        "_inner",
        lambda *args, **kwargs: subprocess.CompletedProcess([], returncode, stdout, stderr),
    )
    with pytest.raises(ConfigurationError, match=message):
        runner._inventory("dind", _manifest())  # noqa: SLF001


def test_v106_inventory_rejects_oversized_or_duplicate_fresh_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    fresh_images = _fresh_images()
    monkeypatch.setattr(runner, "_ACTIVE_FRESH_COMMAND_IMAGES", fresh_images)
    monkeypatch.setattr(
        runner.v103.v100.v97.v94.dind,
        "_inner",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, b"x" * (manifest.toolchain_inventory_inspect_output_bound_bytes + 1), b""
        ),
    )
    with pytest.raises(ConfigurationError, match="command failed"):
        runner._inventory("dind", manifest)  # noqa: SLF001

    duplicate = dict(fresh_images)
    duplicate[list(duplicate)[-1]] = next(iter(duplicate.values()))
    monkeypatch.setattr(runner, "_ACTIVE_FRESH_COMMAND_IMAGES", duplicate)
    with pytest.raises(ConfigurationError, match="lacks fresh command-image bindings"):
        runner._inventory("dind", manifest)  # noqa: SLF001


def test_v106_contract_requires_lock_derived_inventory_and_v107_audit() -> None:
    manifest = _manifest()
    common = _contract_inputs(manifest)
    contract = runner._scaffold_contract(manifest, **common)  # noqa: SLF001
    assert contract["v103_data_volume_reused"] is False
    assert contract["v105_identity_retired"] is True
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v107_audit"] is True
    assert contract["final_inventory_command_image_source"] == "fresh-materialization-locks"

    common["inventory"]["fresh_command_images_by_task"] = {}  # type: ignore[index]
    with pytest.raises(ConfigurationError, match="stale or incomplete"):
        runner._scaffold_contract(manifest, **common)  # noqa: SLF001


def test_v106_records_the_fresh_authorization_post_merge_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_materialize(arguments: argparse.Namespace) -> dict[str, Any]:
        observed["post_merge_main_run_id"] = arguments.post_merge_main_run_id
        return {"status": "observed"}

    monkeypatch.setattr(runner.v103, "materialize", fake_materialize)
    result = runner.materialize(argparse.Namespace(post_merge_main_run_id=123456789))
    assert result == {"status": "observed"}
    assert observed == {"post_merge_main_run_id": 123456789}


def test_v106_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001
