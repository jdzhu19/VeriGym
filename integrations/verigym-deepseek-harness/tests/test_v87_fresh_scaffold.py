from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    DeepSeekHarnessV87FreshScaffoldManifest,
    load_v69_manifest,
    load_v79_dind_successor_manifest,
    load_v87_fresh_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import materialize_hwe_deepseek_harness_v87_fresh_scaffold as runner  # noqa: E402

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v87_fresh_scaffold_successor_v1.json"
)


def test_v87_manifest_freezes_fresh_data2_scaffold_and_closed_flags() -> None:
    manifest = load_v87_fresh_scaffold_manifest(_MANIFEST)
    assert isinstance(manifest, DeepSeekHarnessV87FreshScaffoldManifest)
    assert manifest.identity == runner.IDENTITY
    assert manifest.dind_data_volume == "verigym-deepseek-harness-v87-dind-data"
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_data_backing.startswith("/data2/")
    assert "v83" not in manifest.dind_data_backing
    assert manifest.v83_data_volume_reused is False
    assert manifest.v85_data_volume_reused is False
    assert manifest.readiness_probe_timeout_retryable is True
    assert manifest.provider_clients_available is False
    assert manifest.formal_collection_allowed is False
    assert manifest.collection_started is False
    assert manifest.training_started is False


def test_v87_static_predecessor_bindings_match_frozen_evidence() -> None:
    manifest = load_v87_fresh_scaffold_manifest(_MANIFEST)
    upstream = load_v69_manifest(runner.UPSTREAM_MANIFEST)
    v79 = load_v79_dind_successor_manifest(runner.V79_MANIFEST)
    contract = runner._load_json(runner.V79_PROVIDER_CONTRACT)  # noqa: SLF001
    v85 = runner._load_json(runner.V85_REPORT)  # noqa: SLF001

    runner._validate_static_bindings(  # noqa: SLF001
        manifest,
        upstream,
        v79,
        contract,
        v85,
        upstream_path=runner.UPSTREAM_MANIFEST,
        v79_path=runner.V79_MANIFEST,
        contract_path=runner.V79_PROVIDER_CONTRACT,
        v85_path=runner.V85_REPORT,
    )


def test_v87_rejects_a_relabelled_v85_provider_boundary(tmp_path: Path) -> None:
    manifest = load_v87_fresh_scaffold_manifest(_MANIFEST)
    upstream = load_v69_manifest(runner.UPSTREAM_MANIFEST)
    v79 = load_v79_dind_successor_manifest(runner.V79_MANIFEST)
    contract = runner._load_json(runner.V79_PROVIDER_CONTRACT)  # noqa: SLF001
    v85 = runner._load_json(runner.V85_REPORT)  # noqa: SLF001
    changed = copy.deepcopy(v85)
    changed["attempts"][0]["provider_marker"] = "started_valid"
    base = {key: value for key, value in changed.items() if key != "report_hash"}
    changed["report_hash"] = content_hash(base)
    changed_path = tmp_path / "v85-report.json"
    changed_bytes = json.dumps(changed, sort_keys=True).encode()
    changed_path.write_bytes(changed_bytes)
    manifest_value = manifest.model_dump(mode="json")
    manifest_value.update(
        {
            "v85_report_sha256": hashlib.sha256(changed_bytes).hexdigest(),
            "v85_report_hash": changed["report_hash"],
        }
    )
    manifest_base = {key: value for key, value in manifest_value.items() if key != "manifest_hash"}
    manifest_value["manifest_hash"] = content_hash(manifest_base)
    changed_manifest = DeepSeekHarnessV87FreshScaffoldManifest.model_validate(manifest_value)

    with pytest.raises(ConfigurationError, match="exact audited v85"):
        runner._validate_static_bindings(  # noqa: SLF001
            changed_manifest,
            upstream,
            v79,
            contract,
            changed,
            upstream_path=runner.UPSTREAM_MANIFEST,
            v79_path=runner.V79_MANIFEST,
            contract_path=runner.V79_PROVIDER_CONTRACT,
            v85_path=changed_path,
        )


def test_v87_helper_binding_targets_only_the_new_backing(
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


def test_v87_retag_recomputes_the_canonical_receipt() -> None:
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


def test_v87_manifest_contains_no_provider_environment_names() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True)
    assert all(name not in encoded for name in runner.v69._PROVIDER_ENV_NAMES)  # noqa: SLF001
