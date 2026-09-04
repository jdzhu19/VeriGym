from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    load_v121_bounded_dind_start_diagnostic_manifest,
)
from verigym.runtimes.docker.engine import EngineResult

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import (  # noqa: E402
    run_hwe_deepseek_harness_v121_bounded_dind_start_diagnostic as runner,
)


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
        dind_data_volume="verigym-deepseek-harness-v121-dind-data",
        dind_socket_volume="verigym-deepseek-harness-v121-dind-socket",
        startup_attempt_limit=1,
        startup_command_timeout_seconds=60,
        readiness_timeout_seconds=120,
        cleanup_command_timeout_seconds=60,
        maximum_diagnostic_output_bytes=65536,
    )


def test_v121_manifest_freezes_diagnostic_only_closed_policy() -> None:
    manifest = load_v121_bounded_dind_start_diagnostic_manifest(runner.MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.v119_audit_commit == "c22066916ba51e8c74678be2b0af6ac8d438ac9a"
    assert manifest.v119_post_merge_main_run_id == 33820413201
    assert manifest.startup_attempt_limit == 1
    assert manifest.maximum_diagnostic_output_bytes == 65536
    assert manifest.v118_volume_inspection_allowed is False
    assert manifest.v118_volume_mutation_allowed is False
    assert manifest.task_archive_access_allowed is False
    assert manifest.task_materialization_allowed is False
    assert manifest.base_reference_verification_allowed is False
    assert manifest.harness_controller_allowed is False
    assert manifest.docker_network_creation_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_request_started is False
    assert manifest.provider_calls == 0
    assert all(getattr(manifest, name) is False for name in runner._CLOSED_FLAGS)


@pytest.mark.parametrize(
    ("result", "phase", "expected"),
    [
        (_result(timed_out=True), "docker_run", "docker_run_timeout"),
        (_result(truncated=True), "docker_run", "diagnostic_output_bound_exceeded"),
        (
            _result(exit_code=125, stderr="write failed: no space left on device"),
            "docker_run",
            "no_space_left",
        ),
        (
            _result(exit_code=125, stderr="OCI runtime create failed: sentinel"),
            "docker_run",
            "oci_runtime_create_failed",
        ),
        (
            _result(exit_code=125, stderr="opaque sentinel"),
            "docker_run",
            "unclassified_docker_run_failure",
        ),
    ],
)
def test_v121_failure_classification_is_allowlisted_and_content_free(
    result: EngineResult, phase: str, expected: str
) -> None:
    assert runner._classify_failure(phase, result) == expected


def test_v121_successful_start_uses_exactly_one_detached_run_and_exports_no_raw_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
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
            if arguments[:4] == ["exec", "diagnostic", "docker", "info"]:
                return _result(stdout=json.dumps({"Driver": "vfs", "DefaultRuntime": "runc"}))
            if arguments[:4] == ["exec", "diagnostic", "docker", "version"]:
                return _result(stdout="23.0.6\n")
            raise AssertionError(arguments)

    receipt = runner._run_startup_diagnostic(manifest, Engine(), "diagnostic")  # type: ignore[arg-type]

    assert receipt["status"] == "passed"
    assert receipt["diagnostic_category"] == "dind_ready"
    assert receipt["startup_attempt_count"] == 1
    assert sum(call[0] == "run" and "--detach" in call for call in calls) == 1
    serialized = json.dumps(receipt, sort_keys=True)
    assert "DOCKER_TLS_CERTDIR" not in serialized
    assert "c" * 64 not in serialized
    assert str(control) not in serialized
    assert receipt["raw_stdout_persisted"] is False
    assert receipt["raw_stderr_persisted"] is False


def test_v121_failed_start_receipt_discards_raw_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    secret = "unique-raw-daemon-sentinel"
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            del arguments, timeout_s, max_output_bytes
            return _result(
                exit_code=125,
                stderr=f"OCI runtime create failed: {secret} /private/host/path",
            )

    receipt = runner._run_startup_diagnostic(manifest, Engine(), "diagnostic")  # type: ignore[arg-type]

    assert receipt["status"] == "startup_failed"
    assert receipt["diagnostic_category"] == "oci_runtime_create_failed"
    serialized = json.dumps(receipt, sort_keys=True)
    assert secret not in serialized
    assert "/private/host/path" not in serialized
    assert receipt["docker_run_stderr_bytes"] > 0


def test_v121_cleanup_handles_failed_run_rm_and_removes_volumes_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    data = tmp_path / "data"
    socket = tmp_path / "socket"
    data.mkdir(mode=0o700)
    socket.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "DIND_DATA_BACKING", data)
    monkeypatch.setattr(runner, "DIND_SOCKET_BACKING", socket)
    removed_containers: set[str] = set()
    removed_volumes: set[str] = set()
    helper_name: str | None = None
    calls: list[list[str]] = []

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            nonlocal helper_name
            del timeout_s, max_output_bytes
            calls.append(arguments)
            if arguments[0] == "run":
                helper_name = arguments[arguments.index("--name") + 1]
                return _result(
                    exit_code=125,
                    stderr="OCI runtime create failed: unique-cleanup-raw-sentinel",
                )
            if arguments[:2] == ["container", "inspect"]:
                name = arguments[2]
                if name == "main" or name in removed_containers:
                    return _result(exit_code=1, stderr="No such container")
                return _result(stdout="[{}]")
            if arguments[:2] == ["rm", "--force"]:
                removed_containers.add(arguments[2])
                return _result(stdout=arguments[2])
            if arguments[:2] == ["volume", "inspect"]:
                name = arguments[2]
                if name in removed_volumes:
                    return _result(exit_code=1, stderr="No such volume")
                role = "data" if name == manifest.dind_data_volume else "socket"
                backing = data if role == "data" else socket
                return _result(
                    stdout=json.dumps(
                        [
                            {
                                "Driver": "local",
                                "Labels": {
                                    "verigym.owner": runner.IDENTITY,
                                    "verigym.role": role,
                                },
                                "Options": {
                                    "device": str(backing),
                                    "o": "bind",
                                    "type": "none",
                                },
                            }
                        ]
                    )
                )
            if arguments[:2] == ["volume", "rm"]:
                removed_volumes.add(arguments[2])
                return _result(stdout=arguments[2])
            raise AssertionError(arguments)

    receipt = runner._cleanup(
        manifest,
        Engine(),  # type: ignore[arg-type]
        main_name="main",
        data_attempted=True,
        socket_attempted=True,
    )

    assert helper_name in removed_containers
    assert removed_volumes == {manifest.dind_data_volume, manifest.dind_socket_volume}
    assert receipt["cleanup_helper_status"] == "oci_runtime_create_failed"
    assert receipt["cleanup_helper_container_removed"] is True
    assert receipt["data_volume_removed"] is True
    assert receipt["socket_volume_removed"] is True
    assert receipt["volume_removal_independent_of_cleanup_helper"] is True
    assert receipt["status"] == "cleanup_unconfirmed"
    assert "unique-cleanup-raw-sentinel" not in json.dumps(receipt, sort_keys=True)
    assert all("v118" not in " ".join(call) for call in calls)


def test_v121_execution_boundary_rejects_provider_and_docker_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = SimpleNamespace(
        manifest=runner.MANIFEST,
        output=runner.OUTPUT_ROOT,
        post_merge_main_run_id=1,
    )
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1000)
    for name in runner._PROVIDER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-exported")
    with pytest.raises(ConfigurationError, match="provider"):
        runner._require_execution_boundary(arguments)
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("DOCKER_HOST", "unix:///unapproved.sock")
    with pytest.raises(ConfigurationError, match="default local Docker"):
        runner._require_execution_boundary(arguments)
