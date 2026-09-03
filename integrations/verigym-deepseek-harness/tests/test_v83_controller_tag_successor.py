from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    load_v69_manifest,
    load_v83_execution_scaffold_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import (  # noqa: E402
    materialize_hwe_deepseek_harness_v83_controller_tag_successor as runner,
)

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v83_controller_tag_successor_v1.json"
)
_UPSTREAM = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)


def test_checked_in_v83_successor_is_fresh_credential_free_and_purpose_bound() -> None:
    manifest = load_v83_execution_scaffold_manifest(_MANIFEST)
    assert manifest.identity == runner.IDENTITY
    assert manifest.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert manifest.dind_socket_backing == str(runner.DIND_SOCKET_BACKING)
    assert manifest.dind_data_volume != "verigym-deepseek-harness-v79-dind-data"
    assert manifest.dind_data_volume != "verigym-deepseek-harness-v81-dind-data"
    assert manifest.scaffold_outer_network == "none"
    assert manifest.provider_outer_network == "verigym-hwe-net"
    assert manifest.controller_image_tag == "node:22.19.0-bookworm-slim"
    assert manifest.controller_transfer == ("content_free_read_only_outer_canonical_tag_pipe_v2")
    assert manifest.provider_successor_reopen_budget == 1
    assert manifest.provider_clients_available is False
    assert manifest.registry_access_allowed is False
    assert manifest.partial_archive_allowed is False


def test_v83_scaffold_contract_is_atomic_and_does_not_authorize_provider() -> None:
    manifest = load_v83_execution_scaffold_manifest(_MANIFEST)
    upstream = load_v69_manifest(_UPSTREAM)
    receipts = [{"task_id": task.task_id} for task in upstream.primary_tasks]
    contract = runner._scaffold_contract(  # noqa: SLF001
        manifest,
        upstream,
        receipts,
        source_commit="1" * 40,
        post_merge_main_run_id=123,
        runtime_receipt={"receipt_hash": "2" * 64},
        controller_receipt={"receipt_hash": "3" * 64},
        inventory={"inventory_hash": "4" * 64},
        cleanup={"receipt_hash": "5" * 64},
    )
    without_hash = dict(contract)
    observed = without_hash.pop("contract_hash")
    assert observed == content_hash(without_hash)
    assert contract["schedule"] == [task.task_id for task in upstream.primary_tasks]
    assert contract["provider_execution_scaffold_published"] is True
    assert contract["provider_execution_authorized"] is False
    assert contract["provider_successor_reopen_count"] == 0
    assert contract["requires_independent_v84_audit"] is True
    assert contract["formal_collection_allowed"] is False

    with pytest.raises(ConfigurationError, match="partial execution scaffold"):
        runner._scaffold_contract(  # noqa: SLF001
            manifest,
            upstream,
            receipts[:-1],
            source_commit="1" * 40,
            post_merge_main_run_id=123,
            runtime_receipt={"receipt_hash": "2" * 64},
            controller_receipt={"receipt_hash": "3" * 64},
            inventory={"inventory_hash": "4" * 64},
            cleanup={"receipt_hash": "5" * 64},
        )


def test_v83_execution_boundary_rejects_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in runner.v69._PROVIDER_ENV_NAMES:  # noqa: SLF001
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    arguments = Namespace(post_merge_main_run_id=123)
    runner._require_execution_boundary(arguments)  # noqa: SLF001

    monkeypatch.setenv("VERIGYM_DEEPSEEK_API_KEY", "not-persisted")
    with pytest.raises(ConfigurationError, match="refuses a provider"):
        runner._require_execution_boundary(arguments)  # noqa: SLF001


def test_v83_host_controller_source_is_resolved_by_canonical_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v83_execution_scaffold_manifest(_MANIFEST)
    observed: list[list[str]] = []
    value = {
        "Id": manifest.controller_image_id,
        "RepoTags": [manifest.controller_image_tag],
        "RepoDigests": ["node@" + manifest.controller_image_repository_digest],
    }

    def run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(arguments)
        return subprocess.CompletedProcess([], 0, json.dumps(value), "")

    monkeypatch.setattr(runner.v79, "_validate_dind_image", lambda *_args: None)
    monkeypatch.setattr(runner.subprocess, "run", run)
    runner._validate_host_images(manifest)  # noqa: SLF001
    assert observed == [
        [
            "docker",
            "image",
            "inspect",
            manifest.controller_image_tag,
            "--format",
            "{{json .}}",
        ]
    ]


def test_v83_controller_transfer_uses_tag_and_accepts_absent_inner_repo_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v83_execution_scaffold_manifest(_MANIFEST)
    calls: list[list[str]] = []

    def inner(
        arguments: list[str], *, container: str, timeout_s: int
    ) -> subprocess.CompletedProcess[bytes]:
        del container, timeout_s
        calls.append(arguments)
        if len(calls) <= 2:
            return subprocess.CompletedProcess([], 1, b"", b"not found")
        value = {
            "Id": manifest.controller_image_id,
            "RepoTags": [manifest.controller_image_tag],
            "RepoDigests": [],
        }
        return subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b"")

    transferred: dict[str, str] = {}

    def pipe_image(*, container: str, image_id: str, timeout_s: int) -> tuple[bytes, bytes]:
        del container, timeout_s
        transferred["source"] = image_id
        return b"loaded", b""

    monkeypatch.setattr(runner.dind, "_inner", inner)
    monkeypatch.setattr(runner.dind, "_pipe_image", pipe_image)
    receipt = runner._provision_controller_image("sidecar", manifest)  # noqa: SLF001
    assert transferred == {"source": manifest.controller_image_tag}
    assert receipt["outer_source_repository_digest_verified"] is True
    assert receipt["inner_image_id_verified"] is True
    assert receipt["inner_repository_tag_verified"] is True
    assert receipt["inner_repository_digest_metadata_preserved"] is False
    assert receipt["registry_accessed"] is False


def test_v83_controller_transfer_rejects_wrong_loaded_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v83_execution_scaffold_manifest(_MANIFEST)
    count = 0

    def inner(
        arguments: list[str], *, container: str, timeout_s: int
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal count
        del arguments, container, timeout_s
        count += 1
        if count <= 2:
            return subprocess.CompletedProcess([], 1, b"", b"not found")
        value = {
            "Id": manifest.controller_image_id,
            "RepoTags": [],
            "RepoDigests": [],
        }
        return subprocess.CompletedProcess([], 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(runner.dind, "_inner", inner)
    monkeypatch.setattr(runner.dind, "_pipe_image", lambda **_kwargs: (b"loaded", b""))
    with pytest.raises(ConfigurationError, match="tag identity"):
        runner._provision_controller_image("sidecar", manifest)  # noqa: SLF001


def test_v83_content_free_diagnostic_does_not_persist_output(tmp_path: Path) -> None:
    receipt_path = tmp_path / "diagnostic.json"
    receipt = runner._content_free_bounded_command(  # noqa: SLF001
        [sys.executable, "-c", "print('private-build-output')"],
        timeout=30,
        receipt_path=receipt_path,
    )
    persisted = receipt_path.read_text(encoding="utf-8")
    assert receipt["diagnostic_passed"] is True
    assert receipt["stdout_bytes"] > 0
    assert "private-build-output" not in persisted
    assert receipt["raw_stdout_persisted"] is False


def test_v83_manifest_json_does_not_contain_credentials() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    encoded = json.dumps(value, sort_keys=True).lower()
    assert "api_key" not in encoded
    assert "credential_value" not in encoded
