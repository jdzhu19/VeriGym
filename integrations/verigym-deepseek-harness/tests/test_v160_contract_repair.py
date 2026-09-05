from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from argparse import Namespace
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from scripts import launch_hwe_deepseek_harness_v160_contract_repair as launcher
from scripts import materialize_hwe_deepseek_harness_v160_contract_repair as runner
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV160ContractRepairManifest,
    load_v160_contract_repair_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v160_contract_repair_v1.json"
)
_AUTHORIZATION = _REPOSITORY_ROOT / (
    "docs/audits/2026-09-05_deepseek-harness-v160-contract-repair-authorization.md"
)


class _UnreadableBlockedValues(Mapping[str, str]):
    def __init__(self, values: Mapping[str, str], blocked: set[str]) -> None:
        self._values = dict(values)
        self._blocked = blocked

    def __getitem__(self, name: str) -> str:
        if name in self._blocked:
            raise AssertionError("a blocked environment value was read")
        return self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _sealed_harness_receipt() -> dict[str, object]:
    base: dict[str, object] = {
        "status": "passed",
        "provider_request_started": False,
        "provider_call_count": 0,
        "synthetic_value_scan": {
            "match_count": 0,
            "values_persisted": False,
            "values_hashed": False,
        },
    }
    return {**base, "receipt_hash": content_hash(base)}


def test_v160_manifest_freezes_repair_and_keeps_collection_closed() -> None:
    manifest = load_v160_contract_repair_manifest(_MANIFEST)
    assert manifest.identity == runner.IDENTITY
    assert [int(task.rsplit("-", 1)[1]) for task in manifest.schedule_task_ids] == [
        465,
        1135,
        1780,
        2017,
        2711,
    ]
    assert manifest.compatibility_field == "provider_values_persisted_or_hashed"
    assert manifest.compatibility_value is False
    assert manifest.predecessor_volume_metadata_inspection_allowed is True
    assert manifest.predecessor_volume_content_mount_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.provider_successor_identity.endswith("v162-official-matrix-v1")
    assert manifest.provider_credentials_available is False
    assert manifest.registry_access_allowed is False
    assert manifest.partial_archive_allowed is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


def test_v160_manifest_hash_rejects_repair_mutation() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["predecessor_volume_content_mount_allowed"] = True
    with pytest.raises(ValueError):
        DeepSeekHarnessV160ContractRepairManifest.model_validate(value)


def test_v160_authorization_binds_implementation_and_v159_main_gate() -> None:
    authorization = _AUTHORIZATION.read_text(encoding="utf-8")
    assert hashlib.sha256(_MANIFEST.read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest() in authorization
    assert "33963391618" in authorization


def test_v160_launcher_does_not_read_blocked_values() -> None:
    blocked = set((*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, "DOCKER_HOST", "DOCKER_CONTEXT"))
    source = _UnreadableBlockedValues(
        {
            "PATH": os.environ["PATH"],
            "VERIGYM_DEEPSEEK_API_KEY": "must-not-be-read",
            "OPENAI_API_KEY": "must-not-be-read",
            "DOCKER_HOST": "must-not-be-read",
            "DOCKER_CONTEXT": "must-not-be-read",
        },
        blocked,
    )
    child = launcher._sanitized_child_environment(source)  # noqa: SLF001
    assert child["PATH"] == os.environ["PATH"]
    assert child[runner.OPT_IN_ENV] == "1"
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"
    assert blocked.isdisjoint(child)


def test_v160_repair_derives_legacy_aggregate_without_mutating_input() -> None:
    original = _sealed_harness_receipt()
    frozen = copy.deepcopy(original)
    repaired = runner._repair_harness_receipt(original)  # noqa: SLF001
    assert original == frozen
    assert repaired["provider_values_persisted_or_hashed"] is False
    assert repaired["receipt_hash"] != original["receipt_hash"]
    base = copy.deepcopy(repaired)
    assert (
        content_hash({key: value for key, value in base.items() if key != "receipt_hash"})
        == (repaired["receipt_hash"])
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("synthetic_value_scan", "values_persisted"), True),
        (("synthetic_value_scan", "values_hashed"), True),
        (("synthetic_value_scan", "match_count"), 1),
        (("provider_call_count",), 1),
    ],
)
def test_v160_repair_rejects_unsafe_or_inconsistent_evidence(
    path: tuple[str, ...], value: object
) -> None:
    receipt = _sealed_harness_receipt()
    target = receipt
    for part in path[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value
    base = copy.deepcopy(receipt)
    base.pop("receipt_hash")
    receipt["receipt_hash"] = content_hash(base)
    with pytest.raises(ConfigurationError, match="cannot derive"):
        runner._repair_harness_receipt(receipt)  # noqa: SLF001


def test_v160_repair_rejects_an_invalid_original_self_hash() -> None:
    receipt = _sealed_harness_receipt()
    receipt["receipt_hash"] = "0" * 64
    with pytest.raises(ConfigurationError, match="cannot derive"):
        runner._repair_harness_receipt(receipt)  # noqa: SLF001


def test_v160_source_has_metadata_only_docker_surface() -> None:
    source = inspect.getsource(runner)
    assert '["volume", "inspect", manifest.v158_data_volume]' in source
    assert '"volume_content_mounted": False' in source
    assert '"volume_content_inspected": False' in source
    assert '"volume_mutated": False' in source
    assert '["docker", "run"' not in source
    assert '["docker", "volume", "create"' not in source
    assert '["docker", "volume", "rm"' not in source
    assert "requests." not in source
    assert "urllib" not in source


def test_v160_publication_is_atomic_and_remains_non_authorizing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / runner.IDENTITY
    reconstructed_base: dict[str, object] = {
        "schema_version": "1.0",
        "format_id": "v158-test-contract",
        "identity": "v158-test",
        "task_count": 5,
        "provider_execution_scaffold_published": True,
        "provider_execution_authorized": False,
        "provider_request_started": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "requires_independent_v159_audit": True,
    }
    reconstructed = {
        **reconstructed_base,
        "contract_hash": content_hash(reconstructed_base),
    }
    repaired = {"receipt_hash": "2" * 64}
    volume = {"receipt_hash": "3" * 64}

    monkeypatch.setattr(runner, "OUTPUT_ROOT", output)
    monkeypatch.setattr(runner.os, "getuid", lambda: 1004)
    monkeypatch.setattr(runner.os, "getgid", lambda: 100)
    monkeypatch.setattr(runner, "_require_clean_merged_main", lambda _: "4" * 40)
    monkeypatch.setattr(runner, "_validate_static_files", lambda _: None)
    monkeypatch.setattr(runner, "_validate_predecessor", lambda _: {})
    monkeypatch.setattr(runner, "_validate_frozen_volume", lambda _: volume)
    monkeypatch.setattr(
        runner,
        "_reconstruct_v158_contract",
        lambda _manifest, _values: (reconstructed, repaired),
    )
    for name in (*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, "DOCKER_HOST", "DOCKER_CONTEXT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(runner.CHILD_BOUNDARY_ENV, "1")

    report = runner.materialize(
        Namespace(
            manifest=runner.MANIFEST,
            output=output,
            post_merge_main_run_id=123456,
        )
    )

    assert output.is_dir()
    assert sorted(path.name for path in output.iterdir()) == [
        "contract-repair.json",
        "execution-scaffold-contract.json",
        "execution-scaffold-progress.json",
        "execution-scaffold-report.json",
        "predecessor-validation.json",
        "repaired-harness-initialize.json",
        "volume-metadata.json",
    ]
    assert (output / "execution-scaffold-report.json").read_bytes() == (
        output / "execution-scaffold-progress.json"
    ).read_bytes()
    assert report["status"] == "completed_pending_independent_v161_audit"
    assert report["provider_execution_scaffold_published"] is True
    assert report["provider_execution_authorized"] is False
    assert report["provider_calls"] == 0
    assert report["formal_collection_allowed"] is False
    assert report["formal_collection_started"] is False
    assert report["collection_started"] is False
    assert report["training_started"] is False
    assert report["production_training_ready"] is False


@pytest.mark.skipif(not runner.V158_ROOT.is_dir(), reason="sealed v158 evidence is not local")
def test_v160_reconstructs_the_complete_v158_contract_from_sealed_evidence() -> None:
    manifest = load_v160_contract_repair_manifest(_MANIFEST)
    runner._validate_static_files(manifest)  # noqa: SLF001
    values = runner._validate_predecessor(manifest)  # noqa: SLF001
    contract, repaired = runner._reconstruct_v158_contract(manifest, values)  # noqa: SLF001
    assert repaired["provider_values_persisted_or_hashed"] is False
    assert contract["source_commit"] == manifest.v158_source_commit
    assert contract["post_merge_main_run_id"] == manifest.v158_post_merge_main_run_id
    assert contract["provider_execution_scaffold_published"] is True
    assert contract["provider_execution_authorized"] is False
    assert contract["provider_request_started"] is False
    assert contract["provider_calls"] == 0
    assert contract["task_count"] == 5
    assert contract["dind_cleanup_receipt_hash"] == manifest.v158_cleanup_hash


@pytest.mark.skipif(not runner.V158_ROOT.is_dir(), reason="sealed v158 evidence is not local")
def test_v160_frozen_volume_metadata_is_valid_without_mounting() -> None:
    manifest = load_v160_contract_repair_manifest(_MANIFEST)
    receipt = runner._validate_frozen_volume(manifest)  # noqa: SLF001
    assert receipt["status"] == "passed"
    assert receipt["volume_content_mounted"] is False
    assert receipt["volume_content_inspected"] is False
    assert receipt["volume_mutated"] is False
    assert receipt["container_user_count"] == 0
    assert receipt["socket_volume_present"] is False
    assert receipt["provider_calls"] == 0
