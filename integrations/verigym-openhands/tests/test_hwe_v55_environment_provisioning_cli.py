from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.hwe.image_transfer import ContentAddressedLayerCache, LayerTransferRetryPolicy

_cli = importlib.import_module("scripts.provision_cva6_pr2728_environment_v55")


def _authorization_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "configs/training/qwen35_hwe_openhands_v55_environment_provisioning_v1.json"
    )


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


def test_v55_cli_accepts_only_authorization_session_and_environment_output() -> None:
    parser = _cli._parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])

    destinations = {action.dest for action in parser._actions}
    assert {"authorization", "session_index", "output"}.issubset(destinations)
    assert "dataset" not in destinations
    assert "v33_root" not in destinations


def test_v55_cli_uses_retry_policy_without_allocating_provider_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _cli._v52_cli._CREDENTIAL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(_cli._v55.OPENHANDS_V55_OPT_IN_ENV, "1")
    monkeypatch.setattr(_cli.os, "getuid", lambda: 1000)
    monkeypatch.setattr(_cli.os, "getgid", lambda: 1000)
    monkeypatch.setattr(_cli, "_OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(_cli, "_require_clean_merged_main", lambda: "d" * 40)
    monkeypatch.setattr(_cli, "_validate_v54_failure_receipt_and_cache", lambda: None)
    observed: dict[str, Any] = {}

    def transfer(_context: object, _root: Path, **values: Any) -> dict[str, Any]:
        observed.update(values)
        return _transfer()

    monkeypatch.setattr(_cli._v53_cli, "_transfer_stage_for_identity", transfer)
    output = tmp_path / _cli._OUTPUT_NAME
    arguments = _cli._parser().parse_args(
        [
            "--authorization",
            str(_authorization_path()),
            "--session-index",
            "1",
            "--output",
            str(output),
        ]
    )

    result = _cli.provision(arguments)

    assert result["provider_task_identity_allocated"] is False
    assert result["benchmark_task_consumed"] is False
    assert observed["identity"] == _cli._v55.OPENHANDS_V55_IDENTITY
    assert observed["version"] == "v55"
    assert observed["cache_root"] == _cli._v55.OPENHANDS_V55_PERSISTENT_LAYER_CACHE
    policy = observed["layer_retry_policy"]
    assert isinstance(policy, LayerTransferRetryPolicy)
    assert policy.maximum_attempts == 3


def test_v55_validates_exact_v54_failure_and_live_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = [b"verified-one", b"verified-two"]
    digests = ["sha256:" + hashlib.sha256(payload).hexdigest() for payload in payloads]
    inventory = [
        {"digest": digest, "size": len(payload), "cache_hit": True}
        for digest, payload in zip(digests, payloads, strict=True)
    ]
    base = {
        "identity": "frozen-v54",
        "status": "frozen_zero_provider_materialization_failed",
        "failure_stage": "pr2728_image_transfer",
        "failure_type": "_CommandFailure",
        "transfer_error": {
            "error_family": "unknown",
            "stderr_bytes": 12,
            "stderr_sha256": "4" * 64,
        },
        "verified_layer_inventory": inventory,
        "output_published": False,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    receipt = {**base, "receipt_hash": content_hash(base)}
    path = tmp_path / "v54.failure.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    binding = {
        "identity": "frozen-v54",
        "status": "frozen_zero_provider_materialization_failed",
        "failure_stage": "pr2728_image_transfer",
        "failure_type": "_CommandFailure",
        "failure_file_sha256": hash_bytes(path.read_bytes()),
        "failure_receipt_hash": receipt["receipt_hash"],
        "transfer_error_family": "unknown",
        "transfer_stderr_bytes": 12,
        "transfer_stderr_sha256": "4" * 64,
        "verified_layer_count": 2,
        "verified_layer_bytes": sum(len(payload) for payload in payloads),
    }
    cache_root = tmp_path / "cache"
    cache = ContentAddressedLayerCache(cache_root)
    staging = cache.task_staging("seed")
    for index, (digest, payload) in enumerate(zip(digests, payloads, strict=True)):
        target = staging / f"layer-{index}"
        target.write_bytes(payload)
        cache.commit(target, digest=digest, size=len(payload))
    monkeypatch.setattr(_cli, "_V54_FAILURE_PATH", path)
    monkeypatch.setattr(_cli._v55, "_V54_FAILURE_BINDING", binding)
    monkeypatch.setattr(_cli._v55, "OPENHANDS_V55_PERSISTENT_LAYER_CACHE", cache_root)

    _cli._validate_v54_failure_receipt_and_cache()

    (cache_root / "sha256" / digests[0].removeprefix("sha256:")).write_bytes(b"changed")
    with pytest.raises(Exception, match="cache (?:inventory checksum|identity) changed"):
        _cli._validate_v54_failure_receipt_and_cache()


def test_v55_session_failure_is_redacted_and_resumes_same_environment_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_cli, "_OUTPUT_ROOT", tmp_path)
    context = _cli._ProvisionContext(authorization={"authorization_hash": "1" * 64})
    context.active_stage = "pr2728_image_transfer"
    context.layer_transfer_attempts = []
    context.verified_layer_inventory = []
    secret = b"credential=must-not-persist: unexpected EOF"
    failure = _cli._v52_cli._CommandFailure("layer_015_attempt_03", secret)
    journal = tmp_path / "environment.attempts"

    _cli._publish_session_failure(
        journal,
        session_index=1,
        context=context,
        exc=failure,
    )

    path = journal / "session-01.failure.json"
    text = path.read_text(encoding="utf-8")
    receipt = json.loads(text)
    assert secret.decode() not in text
    assert receipt["transfer_error"]["error_family"] == "transport"
    assert receipt["transfer_error"]["reason"] == "unexpected_eof"
    assert receipt["session_resumable"] is True
    assert receipt["provider_task_identity_allocated"] is False
    assert receipt["benchmark_task_consumed"] is False
    _cli._validate_session_journal(journal, 2)
    with pytest.raises(ConfigurationError, match="sequence"):
        _cli._validate_session_journal(journal, 1)


def test_v55_nonretryable_session_failure_blocks_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_cli, "_OUTPUT_ROOT", tmp_path)
    context = _cli._ProvisionContext(authorization={"authorization_hash": "1" * 64})
    context.active_stage = "pr2728_image_transfer"
    journal = tmp_path / "environment.attempts"
    failure = _cli._v52_cli._CommandFailure(
        "layer_015_attempt_01",
        b"x509 certificate signed by unknown authority",
    )

    _cli._publish_session_failure(
        journal,
        session_index=1,
        context=context,
        exc=failure,
    )

    with pytest.raises(ConfigurationError, match="session evidence"):
        _cli._validate_session_journal(journal, 2)
