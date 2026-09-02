from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest
from verigym.core.hashing import content_hash, hash_bytes
from verigym.hwe.image_transfer import ContentAddressedLayerCache

_cli = importlib.import_module("scripts.materialize_cva6_openhands_v54_v23_canary")


def _context(tmp_path: Path) -> object:
    return _cli._v52_cli._RunContext(
        authorization={"authorization_hash": "1" * 64},
        dataset=tmp_path / "dataset.jsonl",
        v33_root=tmp_path / "v33",
        v33_source_lock=tmp_path / "source-lock.json",
        rg_binary=tmp_path / "rg",
        rg_archive=tmp_path / "rg.tar.gz",
    )


def test_v54_cli_requires_every_frozen_materialization_input() -> None:
    parser = _cli._parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])

    destinations = {action.dest for action in parser._actions}
    assert {
        "authorization",
        "dataset",
        "v33_root",
        "v33_source_lock",
        "rg_binary",
        "rg_release_archive",
        "output",
    }.issubset(destinations)


def test_v54_transfer_uses_new_identity_and_shared_verified_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def transfer(_context: object, _root: Path, **values: object) -> dict[str, object]:
        observed.update(values)
        return {"receipt_hash": "1" * 64}

    monkeypatch.setattr(_cli._v53_cli, "_transfer_stage_for_identity", transfer)

    assert _cli._transfer_stage(_context(tmp_path), tmp_path) == {"receipt_hash": "1" * 64}
    assert observed == {
        "identity": "openhands-hwe-v54-v23-canary-materialization-v1",
        "version": "v54",
        "cache_root": Path("/data/jzhu484/Agent/.verigym-tmp/openhands-hwe-pr2728-layer-cache-v2"),
    }


def test_v54_validates_exact_v53_failure_and_live_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = [b"verified-one", b"verified-two"]
    digests = ["sha256:" + hashlib.sha256(payload).hexdigest() for payload in payloads]
    inventory = [
        {"digest": digest, "size": len(payload), "cache_hit": False}
        for digest, payload in zip(digests, payloads, strict=True)
    ]
    base = {
        "identity": "frozen-v53",
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
    path = tmp_path / "v53.failure.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    binding = {
        "identity": "frozen-v53",
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
    monkeypatch.setattr(_cli, "_V53_FAILURE_PATH", path)
    monkeypatch.setattr(_cli._v54, "_V53_FAILURE_BINDING", binding)
    monkeypatch.setattr(_cli._v54, "OPENHANDS_V54_PERSISTENT_LAYER_CACHE", cache_root)

    _cli._validate_v53_failure_receipt_and_cache()

    (cache_root / "sha256" / digests[0].removeprefix("sha256:")).write_bytes(b"changed")
    with pytest.raises(Exception, match="cache (?:inventory checksum|identity) changed"):
        _cli._validate_v53_failure_receipt_and_cache()


def test_v54_failure_receipt_redacts_transfer_output(tmp_path: Path) -> None:
    context = _context(tmp_path)
    context.active_stage = "pr2728_image_transfer"
    context.verified_layer_inventory = [
        {"digest": "sha256:" + "a" * 64, "size": 123, "cache_hit": True}
    ]
    secret = b"tls certificate failed credential=must-not-persist"
    failure = _cli._v52_cli._CommandFailure("layer_016", secret)
    path = tmp_path / "v54.failure.json"

    _cli._publish_failure(path, context=context, exc=failure)

    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["verified_layer_inventory"] == context.verified_layer_inventory
    assert receipt["transfer_error"]["error_family"] == "tls"
    assert receipt["transfer_error"]["stderr_sha256"] == hashlib.sha256(secret).hexdigest()
    assert secret.decode() not in path.read_text(encoding="utf-8")
    unsealed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    assert receipt["receipt_hash"] == content_hash(unsealed)
