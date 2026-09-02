from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest
from verigym.core.hashing import content_hash

_cli = importlib.import_module("scripts.materialize_cva6_openhands_v52_v23_canary")


def _context(tmp_path: Path) -> object:
    return _cli._RunContext(
        authorization={"authorization_hash": "1" * 64},
        dataset=tmp_path / "dataset.jsonl",
        v33_root=tmp_path / "v33",
        v33_source_lock=tmp_path / "source-lock.json",
        rg_binary=tmp_path / "rg",
        rg_archive=tmp_path / "rg.tar.gz",
    )


def test_v52_cli_requires_every_frozen_materialization_input() -> None:
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


def test_v52_toolchain_inventory_is_bounded_and_content_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = (
        f"{'1' * 64}  /usr/bin/make\n"
        f"{'2' * 64}  /tools/verilator/bin/verilator\n"
        f"{'3' * 64}  /tools/verilator/bin/verilator_bin\n"
    ).encode()
    observed: dict[str, object] = {}

    def fake_run(**values: object) -> tuple[bytes, bytes]:
        observed.update(values)
        return stdout, b""

    monkeypatch.setattr(_cli, "_run_controlled_container", fake_run)

    inventory = _cli._inventory_toolchain(f"sha256:{'4' * 64}")

    assert observed["network"] == "none"
    assert observed["tool_cache"] is None
    assert observed["work"] is None
    assert [item["path"] for item in inventory] == [
        "/usr/bin/make",
        "/tools/verilator/bin/verilator",
        "/tools/verilator/bin/verilator_bin",
    ]
    assert {item["role"] for item in inventory} == {"build_tool", "simulator"}


def test_v52_failure_receipt_redacts_transfer_stderr_and_freezes_identity(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context.active_stage = "pr2728_image_transfer"
    secret = b"tls certificate failed credential=must-not-persist"
    failure = _cli._CommandFailure("candidate_pull", secret)
    path = tmp_path / "v52.failure.json"

    _cli._publish_failure(path, context=context, exc=failure)

    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["status"] == "frozen_zero_provider_materialization_failed"
    assert receipt["output_published"] is False
    assert receipt["canary_contract_published"] is False
    assert receipt["provider_calls"] == 0
    assert receipt["transfer_error"] == {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_redacted_transfer_failure_v1",
        "stage": "candidate_pull",
        "error_family": "tls",
        "stderr_bytes": len(secret),
        "stderr_sha256": hashlib.sha256(secret).hexdigest(),
        "raw_stderr_persisted": False,
    }
    assert secret.decode() not in path.read_text(encoding="utf-8")
    base = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    assert receipt["receipt_hash"] == content_hash(base)


def test_v52_container_validation_requires_exact_mounts_and_isolation(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "tools"
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    for path in (tools, work, cache):
        path.mkdir()
    image_id = f"sha256:{'5' * 64}"
    arguments = ["pull", "immutable", "/transfer/image.tar"]
    mounts = {
        "/tools": (tools.resolve(), False),
        "/transfer": (work.resolve(), True),
        "/cache": (cache.resolve(), True),
    }
    value = {
        "Image": image_id,
        "Path": "/tools/crane",
        "Args": arguments,
        "HostConfig": {
            "NetworkMode": "verigym-hwe-net",
            "IpcMode": "none",
            "PidMode": "",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 1024**3,
            "MemorySwap": 1024**3,
            "NanoCpus": 2_000_000_000,
            "PidsLimit": 128,
        },
        "Config": {
            "User": f"{os.getuid()}:{os.getgid()}",
            "Env": ["HOME=/nonexistent"],
        },
        "Mounts": [
            {"Type": "bind", "Destination": destination, "Source": str(source), "RW": rw}
            for destination, (source, rw) in mounts.items()
        ],
    }

    _cli._validate_container(
        value,
        image_id,
        "verigym-hwe-net",
        "/tools/crane",
        arguments,
        mounts,
    )

    value["HostConfig"]["NetworkMode"] = "bridge"
    with pytest.raises(Exception, match="container controls changed"):
        _cli._validate_container(
            value,
            image_id,
            "verigym-hwe-net",
            "/tools/crane",
            arguments,
            mounts,
        )
