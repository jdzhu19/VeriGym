from __future__ import annotations

import json
import os
import socket
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    HweOfflineTaskLock,
    load_v69_manifest,
    load_v71_dind_successor_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import materialize_hwe_deepseek_harness_v71_dind as runner  # noqa: E402

_UPSTREAM = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json"
)
_SUCCESSOR = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v71_dind_zero_provider_successor_v1.json"
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
    }


def test_checked_in_v71_successor_binds_v69_and_data2_dind() -> None:
    successor = load_v71_dind_successor_manifest(_SUCCESSOR)
    upstream = load_v69_manifest(_UPSTREAM)
    assert successor.upstream_manifest_hash == upstream.manifest_hash
    assert successor.dind_data_backing == str(runner.DIND_DATA_BACKING)
    assert successor.dind_socket_backing == str(runner.DIND_SOCKET_BACKING)
    assert successor.host_docker_root_used_for_task_layers is False
    assert successor.provider_clients_available is False
    assert successor.registry_access_allowed is False
    assert successor.partial_archive_allowed is False


def test_v71_provider_contract_is_atomic_and_requires_dind_cleanup() -> None:
    successor = load_v71_dind_successor_manifest(_SUCCESSOR)
    upstream = load_v69_manifest(_UPSTREAM)
    receipts = [_receipt(task) for task in upstream.primary_tasks]
    contract = runner._provider_contract(  # noqa: SLF001
        successor,
        upstream,
        receipts,
        source_commit="9" * 40,
        post_merge_main_run_id=123,
        dind_runtime_receipt_hash="a" * 64,
    )
    assert contract["schedule"] == [task.task_id for task in upstream.primary_tasks]
    assert contract["dind_cleanup_confirmed"] is True
    assert contract["host_docker_root_used_for_task_layers"] is False
    assert contract["provider_execution_authorized"] is False
    assert contract["requires_independent_v72_audit"] is True

    with pytest.raises(ConfigurationError, match="partial provider contract"):
        runner._provider_contract(  # noqa: SLF001
            successor,
            upstream,
            receipts[:-1],
            source_commit="9" * 40,
            post_merge_main_run_id=123,
            dind_runtime_receipt_hash="a" * 64,
        )


def test_nested_docker_routing_is_temporary_and_rejects_preexisting_override(
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
        monkeypatch.setenv("DOCKER_HOST", "unix:///unexpected.sock")
        with pytest.raises(ConfigurationError, match="routing changed"):
            with runner._nested_docker(socket_path):  # noqa: SLF001
                pass
    finally:
        listener.close()


def test_v71_runner_has_no_registry_pull_or_provider_surface() -> None:
    source = (_REPOSITORY_ROOT / "scripts/materialize_hwe_deepseek_harness_v71_dind.py").read_text(
        encoding="utf-8"
    )
    assert '["docker", "pull"' not in source
    assert "provider_clients_available" not in source
    assert "DOCKER_HOST" in source
    assert "DOCKER_CONTEXT" in source
    assert "DIND_DATA_BACKING" in source
    assert "host_docker_root_used_for_task_layers" in source
    manifest = json.loads(_SUCCESSOR.read_text(encoding="utf-8"))
    assert manifest["dind_data_backing"].startswith("/data2/")
    assert manifest["formal_collection_allowed"] is False


@pytest.mark.parametrize(
    "name",
    [
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "VERIGYM_DEEPSEEK_API_KEY",
        "VERIGYM_DEEPSEEK_API_BASE_URL",
    ],
)
def test_v71_execution_boundary_rejects_provider_configuration(
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
        runner._require_execution_boundary(  # noqa: SLF001
            Namespace(post_merge_main_run_id=1)
        )


def test_v71_outer_sidecar_requires_only_campaign_mounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = load_v71_dind_successor_manifest(_SUCCESSOR)
    root = runner.OUTPUT_ROOT
    inspection = {
        "HostConfig": {
            "Privileged": True,
            "NetworkMode": "none",
            "Binds": ["present"],
            "PortBindings": {},
        },
        "Config": {
            "Labels": {
                "verigym.owner": runner.dind._DIND_OWNER,  # noqa: SLF001
                "verigym.role": "daemon",
            },
            "Env": ["DOCKER_TLS_CERTDIR="],
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": successor.dind_data_volume,
                "Destination": "/var/lib/docker",
            },
            {
                "Type": "volume",
                "Name": successor.dind_socket_volume,
                "Destination": "/var/run",
            },
            {"Type": "bind", "Source": str(root), "Destination": str(root)},
            {
                "Type": "bind",
                "Source": str(root / "dind-empty-home"),
                "Destination": "/verigym-host-sentinel",
                "RW": False,
            },
        ],
    }
    monkeypatch.setattr(runner.dind, "_inspect", lambda kind, value: inspection)
    runner._validate_outer_sidecar("daemon", successor, root=root)  # noqa: SLF001

    inspection["Mounts"].append(
        {
            "Type": "bind",
            "Source": "/var/run/docker.sock",
            "Destination": "/var/run/docker.sock",
        }
    )
    with pytest.raises(ConfigurationError, match="isolation controls"):
        runner._validate_outer_sidecar("daemon", successor, root=root)  # noqa: SLF001
