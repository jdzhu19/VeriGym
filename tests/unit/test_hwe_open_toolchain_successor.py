from __future__ import annotations

import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.open_toolchain_successor import (
    V174_IDENTITY,
    OpenToolchainV174SuccessorManifest,
    exact_repository_digest,
    load_v174_successor_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v174_open_toolchain_repair_v1.json"
)
_DIGEST = "sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca"


def test_checked_in_v174_successor_is_closed_and_fresh() -> None:
    manifest = load_v174_successor_manifest(_MANIFEST)
    assert manifest.identity == V174_IDENTITY
    assert manifest.upstream_identity.endswith("v172-open-toolchain-qualification-v1")
    assert "v174" in manifest.output_root
    assert "v174" in manifest.scratch_root
    assert "v174" in manifest.dind_data_volume
    assert "v174" in manifest.dind_socket_volume
    assert manifest.final_dockerfile.endswith("Dockerfile.v174")
    assert manifest.dind_repository_name == "docker"
    assert manifest.provider_clients_available is False
    assert manifest.provider_calls == 0
    assert manifest.registry_access_allowed is False
    assert manifest.local_runtime_allowed is False
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False
    assert manifest.requires_independent_v175_audit is True
    assert manifest.v176_canary_authorized is False


def test_exact_repository_digest_accepts_frozen_docker_representation() -> None:
    assert (
        exact_repository_digest(
            [f"docker@{_DIGEST}"],
            expected_repository="docker",
            expected_digest=_DIGEST,
        )
        == f"docker@{_DIGEST}"
    )


@pytest.mark.parametrize(
    "entries",
    [
        [f"wrong@{_DIGEST}"],
        ["docker@sha256:" + "0" * 64],
        [f"docker{_DIGEST}"],
        [_DIGEST],
        [f"docker@{_DIGEST}", f"docker@{_DIGEST}"],
        [],
        None,
    ],
)
def test_exact_repository_digest_rejects_drift(entries: object) -> None:
    with pytest.raises(ConfigurationError, match="repository"):
        exact_repository_digest(
            entries,
            expected_repository="docker",
            expected_digest=_DIGEST,
        )


def test_successor_manifest_rejects_mutation_with_recomputed_hash() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["dind_repository_name"] = "not-docker"
    value.pop("manifest_hash")
    value["manifest_hash"] = content_hash(value)
    with pytest.raises(ValueError, match="dind_repository_name"):
        OpenToolchainV174SuccessorManifest.model_validate(value)


def test_successor_manifest_loader_rejects_symlink(tmp_path: Path) -> None:
    linked = tmp_path / "manifest.json"
    linked.symlink_to(_MANIFEST)
    with pytest.raises(ConfigurationError, match="unsafe"):
        load_v174_successor_manifest(linked)
