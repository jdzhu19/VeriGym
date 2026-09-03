from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.campaign import HWE_WORKSPACE_RUNTIME_IMAGE_ID
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV94RuntimeCompleteScaffoldManifest,
    load_v92_official_matrix_manifest,
    load_v94_runtime_complete_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v94_runtime_complete_scaffold as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v94_runtime_complete_scaffold_v1.json"
)


def test_v94_manifest_freezes_fresh_data2_runtime_complete_scaffold() -> None:
    manifest = load_v94_runtime_complete_scaffold_manifest(_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV94RuntimeCompleteScaffoldManifest)
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v94-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert manifest.workspace_runtime_image_id == HWE_WORKSPACE_RUNTIME_IMAGE_ID
    assert manifest.required_inner_image_count == 12
    assert manifest.runtime_prepare_task_count == 5
    assert manifest.harness_initialize_required is True
    assert manifest.preflight_inner_network_internal is True
    assert manifest.tasks_rematerialized_from_completed_local_archives is True
    assert manifest.v90_data_volume_reused is False
    assert manifest.v92_data_volume_reused is False
    assert manifest.provider_credentials_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v94_static_bindings_accept_only_the_audited_v92_stop() -> None:
    manifest = load_v94_runtime_complete_scaffold_manifest(_MANIFEST)
    v92_manifest = load_v92_official_matrix_manifest(runner.V92_MANIFEST)
    report = runner._load_json(runner.V92_REPORT)  # noqa: SLF001
    runner._validate_static_bindings(  # noqa: SLF001
        manifest,
        v92_manifest,
        report,
        v92_manifest_path=runner.V92_MANIFEST,
        v92_report_path=runner.V92_REPORT,
    )


def test_v94_rejects_a_relabelled_provider_consumption(tmp_path: Path) -> None:
    manifest = load_v94_runtime_complete_scaffold_manifest(_MANIFEST)
    v92_manifest = load_v92_official_matrix_manifest(runner.V92_MANIFEST)
    changed = copy.deepcopy(runner._load_json(runner.V92_REPORT))  # noqa: SLF001
    changed["provider_episode_count"] = 1
    base = {key: value for key, value in changed.items() if key != "report_hash"}
    changed["report_hash"] = content_hash(base)
    changed_path = tmp_path / "v92-report.json"
    changed_bytes = json.dumps(changed, sort_keys=True).encode()
    changed_path.write_bytes(changed_bytes)
    manifest_value = manifest.model_dump(mode="json")
    manifest_value.update(
        {
            "v92_report_sha256": hashlib.sha256(changed_bytes).hexdigest(),
            "v92_report_hash": changed["report_hash"],
        }
    )
    manifest_base = {key: value for key, value in manifest_value.items() if key != "manifest_hash"}
    manifest_value["manifest_hash"] = content_hash(manifest_base)
    changed_manifest = DeepSeekHarnessV94RuntimeCompleteScaffoldManifest.model_validate(
        manifest_value
    )
    with pytest.raises(ConfigurationError, match="exact audited v92"):
        runner._validate_static_bindings(  # noqa: SLF001
            changed_manifest,
            v92_manifest,
            changed,
            v92_manifest_path=runner.V92_MANIFEST,
            v92_report_path=changed_path,
        )


def test_v94_host_bootstrap_set_contains_the_missing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v94_runtime_complete_scaffold_manifest(_MANIFEST)
    monkeypatch.setattr(runner.dind, "_dind_image", lambda _image: None)

    def inspect(_kind: str, value: str) -> dict[str, object]:
        assert value == manifest.controller_image_tag
        return {
            "Id": manifest.controller_image_id,
            "RepoTags": [manifest.controller_image_tag],
            "RepoDigests": ["node@" + manifest.controller_image_repository_digest],
        }

    def image(image_id: str, *, role: str) -> dict[str, object]:
        if role == "workspace runtime":
            return {
                "Id": image_id,
                "RepoTags": manifest.workspace_runtime_host_repo_tags,
            }
        return {"Id": image_id, "RepoTags": []}

    monkeypatch.setattr(runner.dind, "_inspect", inspect)
    monkeypatch.setattr(runner.dind, "_image", image)
    images = runner._validate_host_images(manifest)  # noqa: SLF001
    assert len(images) == 2
    assert len({item["image_id"] for item in images}) == 2
    assert images[1] == {
        "role": "workspace_runtime",
        "source": HWE_WORKSPACE_RUNTIME_IMAGE_ID,
        "image_id": HWE_WORKSPACE_RUNTIME_IMAGE_ID,
    }


def test_v94_internal_preflight_network_is_created_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v94_runtime_complete_scaffold_manifest(_MANIFEST)
    calls: list[list[str]] = []
    responses = iter(
        [
            subprocess.CompletedProcess([], 1, b"", b"not found"),
            subprocess.CompletedProcess([], 0, b"network-id\n", b""),
            subprocess.CompletedProcess(
                [],
                0,
                json.dumps(
                    {
                        "Name": manifest.preflight_inner_network,
                        "Driver": "bridge",
                        "Internal": True,
                        "Scope": "local",
                    }
                ).encode(),
                b"",
            ),
        ]
    )

    def inner(arguments: list[str], *, container: str, timeout_s: int):
        assert container == "dind"
        assert timeout_s == 30
        calls.append(arguments)
        return next(responses)

    monkeypatch.setattr(runner.dind, "_inner", inner)
    runner._create_internal_preflight_network("dind", manifest)  # noqa: SLF001
    assert calls[1] == [
        "network",
        "create",
        "--driver",
        "bridge",
        "--internal",
        manifest.preflight_inner_network,
    ]


def test_v94_contract_requires_runtime_and_harness_preflights() -> None:
    manifest = load_v94_runtime_complete_scaffold_manifest(_MANIFEST)
    schedule = [item.task_id for item in manifest.schedule]
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
            "task_receipts": [{"task_id": task_id} for task_id in schedule],
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
    assert contract["workspace_runtime_image_id"] == HWE_WORKSPACE_RUNTIME_IMAGE_ID
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v95_audit"] is True

    common["inventory"] = {
        "inventory_hash": "6" * 64,
        "required_image_count": 11,
        "workspace_runtime_image_present": False,
    }
    with pytest.raises(ConfigurationError, match="partial or provider-crossing"):
        runner._scaffold_contract(manifest, **common)  # noqa: SLF001


def test_v94_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001
