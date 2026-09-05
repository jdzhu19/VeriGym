from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts import run_hwe_deepseek_harness_v152_host_headroom_scaffold as runner  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.hwe.deepseek_harness_campaign import (  # noqa: E402
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    load_v152_host_headroom_scaffold_manifest,
)
from verigym.runtimes.docker.engine import EngineResult  # noqa: E402


def _result(
    *,
    exit_code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    truncated: bool = False,
) -> EngineResult:
    return EngineResult(
        argv=["docker"],
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_s=0.01,
        timed_out=timed_out,
        output_truncated=truncated,
    )


def _manifest() -> Any:
    return SimpleNamespace(
        dind_image_id="sha256:" + "a" * 64,
        dind_repository_digest="sha256:" + "b" * 64,
        dind_server_version="23.0.6",
        dind_storage_driver="vfs",
        dind_default_runtime="runc",
        dind_data_volume="verigym-deepseek-harness-v152-dind-data",
        dind_socket_volume="verigym-deepseek-harness-v152-dind-socket",
        host_runtime_state_root="/",
        minimum_host_root_free_bytes=4 * 1024**3,
        minimum_host_root_free_inodes=100_000,
        startup_attempt_limit=1,
        startup_command_timeout_seconds=60,
        readiness_timeout_seconds=120,
        readiness_command_timeout_seconds=5,
        readiness_poll_interval_seconds=1,
        inventory_command_timeout_seconds=10,
        cleanup_command_timeout_seconds=120,
        maximum_diagnostic_output_bytes=65536,
    )


def _outer_inspect(manifest: Any, control: Path) -> EngineResult:
    return _result(
        stdout=json.dumps(
            [
                {
                    "Image": manifest.dind_image_id,
                    "HostConfig": {
                        "Privileged": True,
                        "NetworkMode": "none",
                        "PidsLimit": 32768,
                    },
                    "Config": {"Env": ["DOCKER_TLS_CERTDIR="]},
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Name": manifest.dind_socket_volume,
                            "Destination": "/var/run",
                            "RW": True,
                        },
                        {
                            "Type": "volume",
                            "Name": manifest.dind_data_volume,
                            "Destination": "/var/lib/docker",
                            "RW": True,
                        },
                        {
                            "Type": "bind",
                            "Source": str(control),
                            "Destination": "/verigym-host-sentinel",
                            "RW": False,
                        },
                    ],
                }
            ]
        )
    )


def test_v152_manifest_freezes_zero_provider_host_lifecycle() -> None:
    manifest = load_v152_host_headroom_scaffold_manifest(runner.MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.minimum_host_root_free_bytes == 4 * 1024**3
    assert manifest.minimum_host_root_free_inodes == 100_000
    assert manifest.host_headroom_policy == "absolute-statvfs-before-and-after-v1"
    assert manifest.startup_attempt_limit == 1
    assert manifest.readiness_command_timeout_seconds == 5
    assert manifest.inventory_command_timeout_seconds == 10
    assert tuple(manifest.provider_environment_names) == ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
    assert manifest.v148_volume_inspection_allowed is False
    assert manifest.v148_volume_mount_allowed is False
    assert manifest.v148_volume_mutation_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_calls == 0
    assert all(getattr(manifest, name) is False for name in runner._CLOSED_FLAGS)


def test_v152_refuses_provider_environment_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "must-not-exist"
    arguments = SimpleNamespace(
        manifest=runner.MANIFEST,
        output=runner.OUTPUT_ROOT,
        post_merge_main_run_id=1,
    )
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-read")
    monkeypatch.setattr(runner, "OUTPUT_ROOT", output)
    arguments.output = output

    with pytest.raises(ConfigurationError, match="provider configuration"):
        runner._require_execution_boundary(arguments)

    assert not output.exists()


def test_v152_host_headroom_receipt_uses_absolute_root_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    values = SimpleNamespace(
        f_frsize=4096,
        f_bsize=4096,
        f_bavail=(4 * 1024**3) // 4096,
        f_favail=100_000,
    )
    monkeypatch.setattr(runner.os, "statvfs", lambda path: values if path == "/" else None)

    receipt = runner._host_headroom_receipt(manifest, phase="before")

    assert receipt["status"] == "passed"
    assert receipt["host_runtime_state_root"] == "/"
    assert receipt["bytes_satisfied"] is True
    assert receipt["inodes_satisfied"] is True
    assert receipt["percentage_thresholds"] is False
    assert receipt["provider_calls"] == 0


def test_v152_readiness_uses_only_fresh_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
    monkeypatch.setattr(runner.v125.time, "sleep", lambda _: None)
    calls: list[list[str]] = []

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            del timeout_s, max_output_bytes
            calls.append(arguments)
            if arguments[0] == "run":
                return _result(stdout="c" * 64 + "\n")
            if arguments[:2] == ["container", "inspect"]:
                return _outer_inspect(manifest, control)
            if arguments[:4] == ["exec", arguments[1], "docker", "info"]:
                return _result(stdout="23.0.6\tvfs\trunc\n")
            raise AssertionError(arguments)

    receipt = runner._run_readiness_probe(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "passed"
    assert receipt["identity"] == runner.IDENTITY
    flattened = "\n".join(" ".join(call) for call in calls)
    assert manifest.dind_data_volume in flattened
    assert manifest.dind_socket_volume in flattened
    assert "v148-dind" not in flattened
    assert "--network none" in flattened
    assert "--bridge=none" in flattened


@pytest.mark.parametrize(
    ("bad_role", "stdout", "stderr"),
    [
        ("image", "sha256:unexpected\n", ""),
        ("volume", "", "warning"),
    ],
)
def test_v152_inventory_fails_closed_without_persisting_output(
    bad_role: str,
    stdout: str,
    stderr: str,
) -> None:
    manifest = _manifest()

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            del timeout_s, max_output_bytes
            role = next(
                name
                for name, token in {
                    "container": "container",
                    "image": "image",
                    "volume": "volume",
                    "custom_network": "network",
                }.items()
                if token in arguments
            )
            return _result(
                stdout=stdout if role == bad_role else "",
                stderr=stderr if role == bad_role else "",
            )

    receipt = runner._inventory_receipt(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "inventory_failed"
    assert receipt["mutable_inventory_empty"] is False
    serialized = json.dumps(receipt, sort_keys=True)
    if stdout.strip():
        assert stdout.strip() not in serialized
    if stderr:
        assert stderr not in serialized
    assert receipt["raw_output_hashed"] is False


def test_v152_cleanup_rejects_nonempty_helper_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    data = tmp_path / "data"
    socket = tmp_path / "socket"
    data.mkdir(mode=0o700)
    socket.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "DIND_DATA_BACKING", data)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket)
    containers = {"probe"}
    volumes = {manifest.dind_data_volume, manifest.dind_socket_volume}

    def volume_json(name: str) -> str:
        role = "data" if name == manifest.dind_data_volume else "socket"
        backing = data if role == "data" else socket
        return json.dumps(
            [
                {
                    "Name": name,
                    "Driver": "local",
                    "Labels": {"verigym.owner": runner.IDENTITY, "verigym.role": role},
                    "Options": {
                        "device": str(backing.resolve()),
                        "o": "bind",
                        "type": "none",
                    },
                }
            ]
        )

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            del timeout_s, max_output_bytes
            if arguments[:2] == ["container", "inspect"]:
                name = arguments[2]
                if name not in containers:
                    return _result(exit_code=1, stderr="No such container")
                return _result(
                    stdout=json.dumps(
                        [
                            {
                                "Config": {
                                    "Labels": {
                                        "verigym.owner": runner.IDENTITY,
                                        "verigym.role": "identity-probe-daemon",
                                    }
                                }
                            }
                        ]
                    )
                )
            if arguments[:2] == ["rm", "--force"]:
                containers.discard(arguments[2])
                return _result()
            if arguments[:2] == ["volume", "inspect"]:
                name = arguments[2]
                if name not in volumes:
                    return _result(exit_code=1, stderr="No such volume")
                return _result(stdout=volume_json(name))
            if arguments[:2] == ["volume", "rm"]:
                volumes.discard(arguments[2])
                return _result(stdout=arguments[2] + "\n")
            if arguments[0] == "run":
                assert "v148-dind" not in " ".join(arguments)
                return _result(stdout="unexpected-output")
            raise AssertionError(arguments)

    receipt = runner._cleanup(
        manifest,
        Engine(),  # type: ignore[arg-type]
        main_name="probe",
        data_attempted=True,
        socket_attempted=True,
    )

    assert receipt["status"] == "cleanup_unconfirmed"
    assert receipt["cleanup_helper_required_empty_output"] is True
    assert receipt["data_volume_removed"] is True
    assert receipt["socket_volume_removed"] is True
    assert receipt["v148_volumes_inspected"] is False
    assert "unexpected-output" not in json.dumps(receipt, sort_keys=True)


def test_v152_contract_requires_complete_lifecycle() -> None:
    manifest = load_v152_host_headroom_scaffold_manifest(runner.MANIFEST)
    report = {
        field: "a" * 64
        for field in (
            "predecessor_preflight_hash",
            "host_root_headroom_before_hash",
            "host_image_identity_hash",
            "volume_setup_receipt_hash",
            "readiness_probe_receipt_hash",
            "inventory_receipt_hash",
            "cleanup_receipt_hash",
            "host_root_headroom_after_hash",
        )
    }

    contract = runner._scaffold_contract(manifest, report)

    assert contract["status"] == "passed_pending_independent_v153_audit"
    assert contract["provider_execution_authorized"] is False
    assert contract["v148_volumes_inspected"] is False
    assert contract["provider_calls"] == 0
    assert all(contract[name] is False for name in runner._CLOSED_FLAGS)


def test_v152_runner_has_no_provider_client_or_v148_docker_operation() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert "DeepSeekClient" not in source
    assert "provider_request(" not in source
    assert "docker volume inspect verigym-deepseek-harness-v148" not in source
    assert "frozen_v148_data_volume" not in source
    assert os.path.basename(runner.__file__) in source or runner.IDENTITY in source
