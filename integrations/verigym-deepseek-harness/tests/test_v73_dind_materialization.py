from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    HweOfflineTaskLock,
    load_v69_manifest,
    load_v73_dind_successor_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import materialize_hwe_deepseek_harness_v73_dind as runner  # noqa: E402

_UPSTREAM = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)
_SUCCESSOR = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v73_dind_zero_provider_successor_v1.json"
)


def _receipt(task: HweOfflineTaskLock) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "agent_toolchain_id": task.agent_toolchain_id,
        "official_verifier_image": task.official_verifier_image,
        "base_failed": True,
        "base_infrastructure_error": False,
        "reference_passed": True,
        "verifier_network": "none",
        "provider_calls": 0,
        "command_diagnostic_hash": "d" * 64,
    }


def test_checked_in_v73_successor_binds_v71_stop_and_fresh_data2_dind() -> None:
    successor = load_v73_dind_successor_manifest(_SUCCESSOR)
    upstream = load_v69_manifest(_UPSTREAM)
    assert successor.upstream_manifest_hash == upstream.manifest_hash
    assert successor.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert successor.dind_socket_backing == str(runner.DIND_SOCKET_BACKING)
    assert successor.dind_data_volume != successor.retired_dind_data_volume
    assert successor.dind_data_backing != successor.retired_dind_data_backing
    assert successor.command_diagnostic_max_bytes == runner.MAX_COMMAND_DIAGNOSTIC_BYTES
    assert successor.host_docker_root_used_for_task_layers is False
    assert successor.provider_clients_available is False
    assert successor.registry_access_allowed is False
    assert successor.partial_archive_allowed is False


def test_v73_provider_contract_is_atomic_and_binds_real_cleanup() -> None:
    successor = load_v73_dind_successor_manifest(_SUCCESSOR)
    upstream = load_v69_manifest(_UPSTREAM)
    receipts = [_receipt(task) for task in upstream.primary_tasks]
    contract = runner._provider_contract(  # noqa: SLF001
        successor,
        upstream,
        receipts,
        source_commit="9" * 40,
        post_merge_main_run_id=123,
        dind_runtime_receipt_hash="a" * 64,
        dind_cleanup_receipt_hash="b" * 64,
    )
    assert contract["schedule"] == [task.task_id for task in upstream.primary_tasks]
    assert contract["dind_cleanup_confirmed"] is True
    assert contract["dind_cleanup_receipt_hash"] == "b" * 64
    assert contract["retired_v71_data_volume_reused"] is False
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v74_audit"] is True

    with pytest.raises(ConfigurationError, match="partial provider contract"):
        runner._provider_contract(  # noqa: SLF001
            successor,
            upstream,
            receipts[:-1],
            source_commit="9" * 40,
            post_merge_main_run_id=123,
            dind_runtime_receipt_hash="a" * 64,
            dind_cleanup_receipt_hash="b" * 64,
        )


def test_content_free_build_diagnostic_accepts_nonempty_output(tmp_path: Path) -> None:
    receipt_path = tmp_path / "diagnostic.json"
    receipt = runner._content_free_bounded_command(  # noqa: SLF001
        [
            sys.executable,
            "-c",
            "import sys; print('private-stdout'); print('private-stderr', file=sys.stderr)",
        ],
        timeout=30,
        receipt_path=receipt_path,
    )
    persisted = receipt_path.read_text(encoding="utf-8")
    assert receipt["diagnostic_passed"] is True
    assert receipt["stdout_bytes"] > 0
    assert receipt["stderr_bytes"] > 0
    assert "private-stdout" not in persisted
    assert "private-stderr" not in persisted
    assert receipt["raw_stdout_persisted"] is False
    assert receipt["raw_stderr_persisted"] is False


def test_content_free_build_diagnostic_records_failure_and_bound(tmp_path: Path) -> None:
    failed = tmp_path / "failed.json"
    with pytest.raises(ConfigurationError, match="bounded build command"):
        runner._content_free_bounded_command(  # noqa: SLF001
            [sys.executable, "-c", "print('failure-body'); raise SystemExit(7)"],
            timeout=30,
            receipt_path=failed,
        )
    failed_value = json.loads(failed.read_text(encoding="utf-8"))
    assert failed_value["returncode"] == 7
    assert failed_value["diagnostic_passed"] is False
    assert "failure-body" not in failed.read_text(encoding="utf-8")

    oversized = tmp_path / "oversized.json"
    with pytest.raises(ConfigurationError, match="bounded build command"):
        runner._content_free_bounded_command(  # noqa: SLF001
            [sys.executable, "-c", "print('123456789', end='')"],
            timeout=30,
            receipt_path=oversized,
            maximum_output_bytes=8,
        )
    assert json.loads(oversized.read_text(encoding="utf-8"))["output_within_bound"] is False


def test_socket_cleanup_is_networkless_bounded_and_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = load_v73_dind_successor_manifest(_SUCCESSOR)
    socket_backing = tmp_path / "socket"
    socket_backing.mkdir(mode=0o700)
    stale = socket_backing / "docker.pid"
    stale.write_text("stale", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, timeout_s: int = 60) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        if command[:3] == ["docker", "run", "--rm"]:
            stale.unlink()
            socket_backing.chmod(0o700)
            return subprocess.CompletedProcess(command, 0, b"cleanup-private", b"")
        return subprocess.CompletedProcess(command, 1, b"", b"")

    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket_backing)
    monkeypatch.setattr(runner.dind, "_bind_backed_volume", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner.dind, "_remove_volume", lambda name: True)
    monkeypatch.setattr(runner.dind, "_run", fake_run)
    receipt = runner._clean_socket_volume(successor, root=output)  # noqa: SLF001
    command = commands[0]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command.count("--volume") == 1
    assert command.count("--cap-add") == 3
    assert receipt["cleanup_confirmed"] is True
    assert receipt["socket_backing_empty"] is True
    assert "cleanup-private" not in (output / "dind-cleanup-receipt.json").read_text()


def test_nested_docker_routing_is_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    socket_path = tmp_path / "docker.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(socket_path))
    try:
        with runner._nested_docker(socket_path):  # noqa: SLF001
            assert os.environ["DOCKER_HOST"] == f"unix://{socket_path}"
        assert "DOCKER_HOST" not in os.environ
    finally:
        listener.close()


@pytest.mark.parametrize("name", ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"])
def test_v73_execution_boundary_rejects_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    for provider_name in runner.v69._PROVIDER_ENV_NAMES:  # noqa: SLF001
        monkeypatch.delenv(provider_name, raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv(name, "present-but-never-read")
    monkeypatch.setattr(runner.os, "getuid", lambda: 1000)
    monkeypatch.setattr(runner.os, "getgid", lambda: 1000)
    with pytest.raises(ConfigurationError, match="provider configuration"):
        runner._require_execution_boundary(Namespace(post_merge_main_run_id=1))  # noqa: SLF001


def test_v73_runner_has_no_registry_pull_or_provider_surface() -> None:
    source = (_REPOSITORY_ROOT / "scripts/materialize_hwe_deepseek_harness_v73_dind.py").read_text(
        encoding="utf-8"
    )
    assert '["docker", "pull"' not in source
    assert "DIND_DATA_BACKING" in source
    assert "raw_stdout_persisted" in source
    manifest = json.loads(_SUCCESSOR.read_text(encoding="utf-8"))
    assert manifest["dind_data_backing"].startswith("/data2/")
    assert manifest["formal_collection_allowed"] is False
