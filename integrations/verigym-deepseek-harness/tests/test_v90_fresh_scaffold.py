from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV90FreshScaffoldManifest,
    load_v69_manifest,
    load_v79_dind_successor_manifest,
    load_v90_fresh_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import materialize_hwe_deepseek_harness_v90_fresh_scaffold as runner  # noqa: E402

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v90_fresh_scaffold_timeout_successor_v1.json"
)


def test_v90_manifest_freezes_fresh_data2_scaffold_and_closed_flags() -> None:
    manifest = load_v90_fresh_scaffold_manifest(_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV90FreshScaffoldManifest)
    assert manifest.identity == runner.IDENTITY
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v90-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert "v83" not in manifest.dind_data_backing
    assert manifest.v83_data_volume_reused is False
    assert manifest.v85_data_volume_reused is False
    assert manifest.v87_data_volume_reused is False
    assert manifest.source_preparation_docker_control_timeout_seconds == 300
    assert manifest.readiness_probe_timeout_retryable is True
    assert manifest.provider_clients_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v90_static_predecessor_bindings_match_frozen_evidence() -> None:
    manifest = load_v90_fresh_scaffold_manifest(_MANIFEST)
    upstream = load_v69_manifest(runner.UPSTREAM_MANIFEST)
    v79 = load_v79_dind_successor_manifest(runner.V79_MANIFEST)
    contract = runner._load_json(runner.V79_PROVIDER_CONTRACT)  # noqa: SLF001
    v87 = runner._load_json(runner.V87_REPORT)  # noqa: SLF001

    runner._validate_static_bindings(  # noqa: SLF001
        manifest,
        upstream,
        v79,
        contract,
        v87,
        upstream_path=runner.UPSTREAM_MANIFEST,
        v79_path=runner.V79_MANIFEST,
        contract_path=runner.V79_PROVIDER_CONTRACT,
        v87_path=runner.V87_REPORT,
    )


def test_v90_rejects_a_relabelled_v87_physical_open(tmp_path: Path) -> None:
    manifest = load_v90_fresh_scaffold_manifest(_MANIFEST)
    upstream = load_v69_manifest(runner.UPSTREAM_MANIFEST)
    v79 = load_v79_dind_successor_manifest(runner.V79_MANIFEST)
    contract = runner._load_json(runner.V79_PROVIDER_CONTRACT)  # noqa: SLF001
    v87 = runner._load_json(runner.V87_REPORT)  # noqa: SLF001
    changed = copy.deepcopy(v87)
    changed["physical_data_volume_open_count"] = 0
    base = {key: value for key, value in changed.items() if key != "report_hash"}
    changed["report_hash"] = content_hash(base)
    changed_path = tmp_path / "v87-report.json"
    changed_bytes = json.dumps(changed, sort_keys=True).encode()
    changed_path.write_bytes(changed_bytes)
    manifest_value = manifest.model_dump(mode="json")
    manifest_value.update(
        {
            "v87_report_sha256": hashlib.sha256(changed_bytes).hexdigest(),
            "v87_report_hash": changed["report_hash"],
        }
    )
    manifest_base = {key: value for key, value in manifest_value.items() if key != "manifest_hash"}
    manifest_value["manifest_hash"] = content_hash(manifest_base)
    changed_manifest = DeepSeekHarnessV90FreshScaffoldManifest.model_validate(manifest_value)

    with pytest.raises(ConfigurationError, match="exact audited v87"):
        runner._validate_static_bindings(  # noqa: SLF001
            changed_manifest,
            upstream,
            v79,
            contract,
            changed,
            upstream_path=runner.UPSTREAM_MANIFEST,
            v79_path=runner.V79_MANIFEST,
            contract_path=runner.V79_PROVIDER_CONTRACT,
            v87_path=changed_path,
        )


def test_v90_helper_binding_targets_only_the_new_backing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "IDENTITY",
        "OUTPUT_ROOT",
        "DIND_PARENT",
        "DIND_DATA_BACKING",
        "DIND_SOCKET_BACKING",
    ):
        monkeypatch.setattr(runner.v83, name, getattr(runner.v83, name))
    monkeypatch.setattr(runner.v83, "IDENTITY", runner._ORIGINAL_V83_IDENTITY)  # noqa: SLF001
    runner._configure_v83_helpers()  # noqa: SLF001
    assert runner.v83.IDENTITY == runner.IDENTITY
    assert runner.v83.DIND_PARENT == runner.DIND_PARENT
    assert runner.v83.DIND_DATA_BACKING == runner.DIND_DATA_BACKING
    assert runner.v83.DIND_SOCKET_BACKING == runner.DIND_SOCKET_BACKING


def test_v90_retag_recomputes_the_canonical_receipt() -> None:
    original = {
        "schema_version": "1.0",
        "format_id": "old",
        "identity": runner.IDENTITY,
    }
    value = {**original, "receipt_hash": content_hash(original)}
    retagged = runner._retag(  # noqa: SLF001
        value,
        hash_field="receipt_hash",
        format_id="new",
        extra={"physical_data_volume_open_count": 1},
    )
    receipt_hash = retagged.pop("receipt_hash")
    assert retagged["format_id"] == "new"
    assert receipt_hash == content_hash(retagged)


def test_v90_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001


def test_v90_contract_requires_timeout_in_every_task_receipt() -> None:
    manifest = load_v90_fresh_scaffold_manifest(_MANIFEST)
    upstream = load_v69_manifest(runner.UPSTREAM_MANIFEST)
    receipts = [
        {
            "task_id": task.task_id,
            "source_preparation_docker_control_timeout_seconds": 300,
        }
        for task in upstream.primary_tasks
    ]
    common = {
        "source_commit": "1" * 40,
        "post_merge_main_run_id": 1,
        "runtime_receipt": {"receipt_hash": "2" * 64},
        "controller_receipt": {"receipt_hash": "3" * 64},
        "inventory": {"inventory_hash": "4" * 64},
        "cleanup": {"receipt_hash": "5" * 64},
    }

    contract = runner._scaffold_contract(  # noqa: SLF001
        manifest,
        upstream,
        receipts,
        **common,
    )
    assert contract["source_preparation_docker_control_timeout_seconds"] == 300
    assert contract["requires_independent_v91_audit"] is True

    receipts[0].pop("source_preparation_docker_control_timeout_seconds")
    with pytest.raises(ConfigurationError, match="partial execution scaffold"):
        runner._scaffold_contract(  # noqa: SLF001
            manifest,
            upstream,
            receipts,
            **common,
        )
