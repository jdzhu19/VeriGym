from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from verigym.core.hashing import content_hash
from verigym.hwe import materialization_preflight as preflight

_runner = importlib.import_module("scripts.preflight_cva6_hwe_command_materialization")


def _directories(tmp_path: Path) -> dict[str, Path]:
    result = {name: tmp_path / name for name in ("control", "docker", "scratch", "output")}
    for path in result.values():
        path.mkdir()
    return result


def _stat(*, free_bytes: int, free_inodes: int) -> SimpleNamespace:
    return SimpleNamespace(
        f_frsize=4096,
        f_bsize=4096,
        f_bavail=free_bytes // 4096,
        f_favail=free_inodes,
    )


def test_materialization_headroom_passes_absolute_byte_and_inode_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directories = _directories(tmp_path)
    monkeypatch.setattr(
        preflight.os,
        "statvfs",
        lambda _path: _stat(free_bytes=256 * 1024**3, free_inodes=1_000_000),
    )

    receipt = preflight.require_materialization_headroom(
        control_root=directories["control"],
        docker_root=directories["docker"],
        scratch_root=directories["scratch"],
        output_parent=directories["output"],
    )

    assert receipt["status"] == "passed"
    assert receipt["provider_calls"] == 0
    assert receipt["model_process_count"] == 0
    assert receipt["policy"] == {
        "absolute_thresholds": True,
        "percentage_thresholds": False,
        "planned_command_image_count": 6,
        "maximum_bytes_per_command_image": 8 * 1024**3,
        "docker_headroom_multiplier": 2,
    }
    base = {key: value for key, value in receipt.items() if key != "preflight_hash"}
    assert receipt["preflight_hash"] == content_hash(base)


def test_materialization_headroom_rejects_docker_bytes_with_content_free_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directories = _directories(tmp_path)

    def fake_statvfs(path: Path) -> SimpleNamespace:
        free_bytes = 64 * 1024**3 if Path(path).name == "docker" else 256 * 1024**3
        return _stat(free_bytes=free_bytes, free_inodes=1_000_000)

    monkeypatch.setattr(preflight.os, "statvfs", fake_statvfs)

    with pytest.raises(preflight.MaterializationHeadroomError) as raised:
        preflight.require_materialization_headroom(
            control_root=directories["control"],
            docker_root=directories["docker"],
            scratch_root=directories["scratch"],
            output_parent=directories["output"],
        )

    receipt = raised.value.receipt
    assert receipt["status"] == "rejected_insufficient_headroom"
    docker = next(item for item in receipt["filesystems"] if item["role"] == "docker_root")
    assert docker["bytes_satisfied"] is False
    assert docker["inodes_satisfied"] is True
    assert all(str(path) not in str(receipt) for path in directories.values())


def test_materialization_headroom_rejects_low_inodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directories = _directories(tmp_path)
    monkeypatch.setattr(
        preflight.os,
        "statvfs",
        lambda _path: _stat(free_bytes=256 * 1024**3, free_inodes=5_000),
    )

    receipt = preflight.materialization_headroom_receipt(
        control_root=directories["control"],
        docker_root=directories["docker"],
        scratch_root=directories["scratch"],
        output_parent=directories["output"],
    )

    assert receipt["status"] == "rejected_insufficient_headroom"
    assert all(item["inodes_satisfied"] is False for item in receipt["filesystems"])


def test_docker_root_discovery_rejects_unbounded_output_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive = b"credential-value" * 400
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=sensitive,
        ),
    )

    with pytest.raises(Exception) as raised:
        preflight.discover_docker_root()

    assert sensitive.decode() not in str(raised.value)


def test_preflight_runner_atomically_persists_rejected_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directories = _directories(tmp_path)
    monkeypatch.setattr(_runner, "discover_docker_root", lambda: directories["docker"])
    monkeypatch.setattr(
        preflight.os,
        "statvfs",
        lambda _path: _stat(free_bytes=1024**3, free_inodes=1_000_000),
    )
    receipt_path = tmp_path / "headroom-receipt.json"

    with pytest.raises(preflight.MaterializationHeadroomError):
        _runner.preflight(
            scratch_root=directories["scratch"],
            output_parent=directories["output"],
            receipt_path=receipt_path,
        )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rejected_insufficient_headroom"
    assert receipt["provider_calls"] == 0
    assert receipt["raw_command_output_persisted"] is False
