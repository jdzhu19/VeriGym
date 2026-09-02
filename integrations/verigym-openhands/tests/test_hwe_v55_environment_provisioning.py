from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

from verigym_openhands.hwe_v55_environment_provisioning import (
    OPENHANDS_V55_OPT_IN_ENV,
    build_v55_environment_manifest,
    run_v55_environment_provisioning,
    validate_v55_authorization,
    validate_v55_environment_manifest,
)


def _authorization() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[3]
        / "configs/training/qwen35_hwe_openhands_v55_environment_provisioning_v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _transfer() -> dict[str, Any]:
    digest = "sha256:" + "a" * 64
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v55_pr2728_image_transfer_v2",
        "task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728",
        "platform": "linux/amd64",
        "verifier_image": "sha256:" + "b" * 64,
        "manifest_digest": "sha256:" + "c" * 64,
        "manifest_size": 100,
        "config_digest": "sha256:" + "b" * 64,
        "config_size": 50,
        "layer_inventory": [{"digest": digest, "size": 123, "cache_hit": True}],
        "layer_download_count": 0,
        "all_layers_verified_before_assembly": True,
        "assembly_source": "verified_content_addressed_cache",
        "temporary_archive_cleanup_count": 1,
        "raw_stderr_persisted": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "layer_runner_maximum_attempts": 3,
        "layer_transfer_attempts": [
            {
                "digest": digest,
                "size": 123,
                "cache_hit": True,
                "attempt_count": 0,
                "failed_attempts": [],
                "completed": True,
            }
        ],
        "layer_download_attempt_count": 0,
        "provider_retry_count": 0,
    }
    return {**base, "receipt_hash": content_hash(base)}


def test_v55_authorization_allocates_only_an_environment_identity() -> None:
    authorization = validate_v55_authorization(_authorization())

    assert authorization["provider_task_identity_allocated"] is False
    assert authorization["benchmark_task_consumed"] is False
    assert authorization["layer_maximum_attempts"] == 3
    assert authorization["authorized_actions"]["qualify_pr2728_public_task"] is False
    assert authorization["authorized_actions"]["invoke_provider"] is False
    assert not {"model", "seed", "sample_index", "campaign_id"}.intersection(authorization)


def test_v55_atomically_publishes_only_environment_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V55_OPT_IN_ENV, "1")
    output = tmp_path / "environment.json"
    observed_staging: list[Path] = []

    def provision(staging: Path) -> dict[str, Any]:
        observed_staging.append(staging)
        assert staging.name.startswith(".environment.json.v55-staging-")
        return _transfer()

    result = run_v55_environment_provisioning(
        authorization=_authorization(),
        session_index=1,
        main_commit="d" * 40,
        provision=provision,
        output=output,
    )

    persisted = validate_v55_environment_manifest(json.loads(output.read_text()))
    assert result == persisted
    assert result["status"] == "environment_provisioned_pending_public_qualification"
    assert result["provider_task_identity_allocated"] is False
    assert result["benchmark_task_consumed"] is False
    assert result["public_qualification_completed"] is False
    assert observed_staging[0].exists() is False


def test_v55_failure_publishes_no_partial_environment_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V55_OPT_IN_ENV, "1")
    output = tmp_path / "environment.json"

    def fail(_staging: Path) -> dict[str, Any]:
        raise RuntimeError("failed before manifest")

    with pytest.raises(RuntimeError, match="failed before manifest"):
        run_v55_environment_provisioning(
            authorization=_authorization(),
            session_index=1,
            main_commit="d" * 40,
            provision=fail,
            output=output,
        )

    assert output.exists() is False
    assert not list(tmp_path.glob(".environment.json.v55-staging-*"))


def test_v55_manifest_and_authorization_fail_closed_on_identity_drift() -> None:
    authorization = _authorization()
    manifest = build_v55_environment_manifest(
        authorization=authorization,
        transfer=_transfer(),
        session_index=1,
        main_commit="e" * 40,
    )
    changed = copy.deepcopy(manifest)
    changed["provider_task_identity_allocated"] = True
    base = {key: value for key, value in changed.items() if key != "manifest_hash"}
    changed["manifest_hash"] = content_hash(base)

    with pytest.raises(ConfigurationError, match="manifest policy"):
        validate_v55_environment_manifest(changed)

    changed_authorization = copy.deepcopy(authorization)
    changed_authorization["model"] = "forbidden-provider-model"
    base = {
        key: value for key, value in changed_authorization.items() if key != "authorization_hash"
    }
    changed_authorization["authorization_hash"] = content_hash(base)
    with pytest.raises(ConfigurationError, match="authorization policy"):
        validate_v55_authorization(changed_authorization)
