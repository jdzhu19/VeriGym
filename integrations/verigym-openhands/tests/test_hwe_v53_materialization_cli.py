from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
from pathlib import Path

import pytest
from verigym.core.hashing import content_hash
from verigym.hwe.image_transfer import ContentAddressedLayerCache

_cli = importlib.import_module("scripts.materialize_cva6_openhands_v53_v23_canary")


def _context(tmp_path: Path) -> object:
    return _cli._v52_cli._RunContext(
        authorization={"authorization_hash": "1" * 64},
        dataset=tmp_path / "dataset.jsonl",
        v33_root=tmp_path / "v33",
        v33_source_lock=tmp_path / "source-lock.json",
        rg_binary=tmp_path / "rg",
        rg_archive=tmp_path / "rg.tar.gz",
    )


def test_v53_cli_requires_every_frozen_materialization_input() -> None:
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


def test_v53_transfer_downloads_only_cache_misses_and_commits_each_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "persistent-cache"
    monkeypatch.setattr(_cli._v53, "OPENHANDS_V53_PERSISTENT_LAYER_CACHE", cache_root)
    tools = tmp_path / "tools"
    tools.mkdir()
    crane = tools / "crane"
    crane.write_bytes(b"pinned-crane")
    crane.chmod(0o700)
    monkeypatch.setattr(_cli._v52_cli, "_TOOL_CACHE", tools)
    monkeypatch.setattr(
        _cli._v52_cli,
        "_CRANE_SHA256",
        hashlib.sha256(b"pinned-crane").hexdigest(),
    )
    execution = {"image_id": "sha256:" + "e" * 64}
    monkeypatch.setattr(_cli._v51, "_validate_local_image", lambda _reference: execution)
    monkeypatch.setattr(_cli._v51, "_validate_headroom", lambda: None)
    monkeypatch.setattr(_cli._v51, "_validate_network", lambda: None)

    layer_payloads = [b"first-layer", b"second-layer"]
    layer_digests = ["sha256:" + hashlib.sha256(item).hexdigest() for item in layer_payloads]
    config = b'{"architecture":"amd64"}'
    config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest_value = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"digest": config_digest, "size": len(config)},
        "layers": [
            {"digest": digest, "size": len(payload)}
            for digest, payload in zip(layer_digests, layer_payloads, strict=True)
        ],
    }
    manifest = json.dumps(manifest_value, separators=(",", ":"), sort_keys=True).encode()
    manifest_digest = "sha256:" + hashlib.sha256(manifest).hexdigest()

    cache = ContentAddressedLayerCache(cache_root)
    seed = cache.task_staging("seed-first")
    seed_file = seed / "first.part"
    seed_file.write_bytes(layer_payloads[0])
    cache.commit(seed_file, digest=layer_digests[0], size=len(layer_payloads[0]))

    roles: list[str] = []

    def fake_controlled(
        _execution: dict[str, object],
        *,
        role: str,
        arguments: list[str],
        work: Path | None = None,
        cache_staging: Path | None = None,
        **_values: object,
    ) -> tuple[bytes, bytes]:
        roles.append(role)
        if role == "candidate_digest":
            return f"{manifest_digest}\n".encode(), b""
        if role == "candidate_manifest":
            return manifest + b"\n", b""
        if role == "candidate_config":
            return config + b"\n", b""
        if role.startswith("layer_"):
            assert cache_staging is not None
            digest = arguments[-1].rsplit("/", 1)[1]
            payload = layer_payloads[layer_digests.index(digest)]
            (cache_staging / digest).write_bytes(payload)
            return b"", b"progress stays private"
        if role == "candidate_assembly":
            assert work is not None
            (work / "candidate-image.tar").write_bytes(b"docker-tar")
            return b"", b""
        raise AssertionError(role)

    monkeypatch.setattr(_cli, "_controlled", fake_controlled)
    state = {"candidate": False, "sentinel": False}
    sentinel = _cli._v51._sentinel_reference()

    def inspect(reference: str) -> dict[str, str] | None:
        if reference == _cli._v52_cli._REFERENCE and state["candidate"]:
            return {"Id": config_digest}
        if reference == sentinel and state["sentinel"]:
            return {"Id": config_digest}
        return None

    monkeypatch.setattr(_cli._v51, "_inspect_host_image", inspect)
    monkeypatch.setattr(
        _cli._v51,
        "_validated_crane_tarball",
        lambda *_args, **_kwargs: {},
    )

    def bounded(arguments: list[str], *, timeout: int, **_values: object) -> object:
        del timeout
        if arguments[:3] == ["docker", "image", "load"]:
            state["sentinel"] = True
        elif arguments[:3] == ["docker", "image", "tag"]:
            state["candidate"] = True
        elif arguments[:3] == ["docker", "image", "rm"]:
            state["sentinel"] = False
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr(_cli._v52_cli, "_bounded_run", bounded)
    root = tmp_path / "result-staging"
    root.mkdir()

    receipt = _cli._transfer_stage(_context(tmp_path), root)

    assert roles == [
        "candidate_digest",
        "candidate_manifest",
        "candidate_config",
        "layer_001",
        "candidate_assembly",
    ]
    assert receipt["layer_inventory"] == [
        {"digest": layer_digests[0], "size": len(layer_payloads[0]), "cache_hit": True},
        {"digest": layer_digests[1], "size": len(layer_payloads[1]), "cache_hit": False},
    ]
    assert receipt["layer_download_count"] == 1
    assert receipt["temporary_archive_cleanup_count"] == 1
    assert state == {"candidate": True, "sentinel": False}
    assert {
        item["digest"]: (item["size"], item["cache_hit"])
        for item in cache.bounded_inventory(layer_digests)
    } == {
        layer_digests[0]: (len(layer_payloads[0]), True),
        layer_digests[1]: (len(layer_payloads[1]), True),
    }


def test_v53_failure_receipt_keeps_only_verified_layer_inventory_and_redacted_error(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context.active_stage = "pr2728_image_transfer"
    context.verified_layer_inventory = [
        {"digest": "sha256:" + "a" * 64, "size": 123, "cache_hit": False}
    ]
    secret = b"tls certificate failed credential=must-not-persist"
    failure = _cli._v52_cli._CommandFailure("layer_003", secret)
    path = tmp_path / "v53.failure.json"

    _cli._publish_failure(path, context=context, exc=failure)

    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["verified_layer_inventory"] == context.verified_layer_inventory
    assert receipt["transfer_error"]["error_family"] == "tls"
    assert receipt["transfer_error"]["stderr_sha256"] == hashlib.sha256(secret).hexdigest()
    assert secret.decode() not in path.read_text(encoding="utf-8")
    base = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    assert receipt["receipt_hash"] == content_hash(base)


def test_v53_digest_qualified_payload_accepts_only_exact_bytes_or_one_cli_newline() -> None:
    payload = b'{"config":true}'
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    assert (
        _cli._digest_qualified_payload(
            payload + b"\n", digest=digest, size=len(payload), label="config"
        )
        == payload
    )
    with pytest.raises(Exception, match="identity changed"):
        _cli._digest_qualified_payload(
            payload + b"x", digest=digest, size=len(payload), label="config"
        )
