from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import run_hwe_deepseek_harness_v123_bounded_dind_identity_probe as runner
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    load_v123_bounded_dind_identity_probe_manifest,
)
from verigym.runtimes.docker.engine import EngineResult


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
        dind_data_volume="verigym-deepseek-harness-v123-dind-data",
        dind_socket_volume="verigym-deepseek-harness-v123-dind-socket",
        startup_attempt_limit=1,
        startup_command_timeout_seconds=60,
        readiness_timeout_seconds=120,
        probe_command_timeout_seconds=30,
        cleanup_command_timeout_seconds=60,
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


def test_v123_manifest_freezes_identity_probe_only_closed_policy() -> None:
    manifest = load_v123_bounded_dind_identity_probe_manifest(runner.MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.v122_audit_commit == "34a2854afcaa64a6de8a0fbca94ffd50dbb168db"
    assert manifest.v122_post_merge_main_run_id == 33823592366
    assert manifest.startup_attempt_limit == 1
    assert manifest.maximum_diagnostic_output_bytes == 65536
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
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


def test_v123_explicit_info_qualifies_identity_when_legacy_formatter_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
    calls: list[list[str]] = []
    secret = "legacy-template-secret"

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
            if arguments[:4] == ["exec", "probe", "docker", "info"]:
                if "{{json .}}" in arguments:
                    return _result(stdout=json.dumps({"ClientInfo": {}}))
                return _result(stdout="23.0.6\tvfs\trunc\n")
            if arguments[:4] == ["exec", "probe", "docker", "version"]:
                return _result(exit_code=1, stderr=f"template execution failed: {secret}")
            raise AssertionError(arguments)

    receipt = runner._run_identity_probe(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "passed"
    assert receipt["diagnostic_category"] == "dind_identity_qualified"
    assert receipt["identity_qualified"] is True
    assert receipt["legacy_version_category"] == "formatter_failure"
    assert receipt["json_info_server_version_present"] is False
    assert receipt["explicit_info_server_version_equal"] is True
    assert receipt["explicit_info_driver_equal"] is True
    assert receipt["explicit_info_default_runtime_equal"] is True
    assert sum(call[0] == "run" and "--detach" in call for call in calls) == 1
    serialized = json.dumps(receipt, sort_keys=True)
    assert secret not in serialized
    assert "c" * 64 not in serialized
    assert str(control) not in serialized
    assert receipt["raw_stdout_persisted"] is False
    assert receipt["raw_stderr_persisted"] is False
    assert receipt["raw_output_hashed"] is False


def test_v123_explicit_info_mismatch_fails_closed_without_raw_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
    secret = "unexpected-runtime-secret"

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            del timeout_s, max_output_bytes
            if arguments[0] == "run":
                return _result(stdout="d" * 64 + "\n")
            if arguments[:2] == ["container", "inspect"]:
                return _outer_inspect(manifest, control)
            if arguments[:4] == ["exec", "probe", "docker", "info"]:
                if "{{json .}}" in arguments:
                    return _result(stdout=json.dumps({"Driver": "vfs"}))
                return _result(stdout=f"23.0.6\tvfs\t{secret}\n")
            if arguments[:4] == ["exec", "probe", "docker", "version"]:
                return _result(stdout="23.0.6\n")
            raise AssertionError(arguments)

    receipt = runner._run_identity_probe(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "probe_failed"
    assert receipt["diagnostic_category"] == "explicit_info_identity_failed"
    assert receipt["explicit_info_default_runtime_equal"] is False
    assert secret not in json.dumps(receipt, sort_keys=True)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_result(), "success"),
        (_result(exit_code=1, stderr="template: cannot evaluate"), "formatter_failure"),
        (_result(exit_code=1, stderr="cannot connect to daemon"), "daemon_connect_failure"),
        (_result(exit_code=1, stderr="API version mismatch"), "api_negotiation_failure"),
        (_result(exit_code=1, stderr="opaque"), "other_command_failure"),
        (_result(timed_out=True), "timeout"),
        (_result(truncated=True), "output_bound_exceeded"),
    ],
)
def test_v123_legacy_classification_is_allowlisted(result: EngineResult, expected: str) -> None:
    assert runner._legacy_category(result) == expected


def test_v123_cleanup_removes_only_owned_fresh_resources(
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

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            nonlocal helper_name
            del timeout_s, max_output_bytes
            if arguments[0] == "run":
                helper_name = arguments[arguments.index("--name") + 1]
                return _result(exit_code=125, stderr="OCI runtime create failed: private")
            if arguments[:2] == ["container", "inspect"]:
                name = arguments[2]
                if name == "main" or name in removed_containers:
                    return _result(exit_code=1, stderr="No such container")
                return _result(
                    stdout=json.dumps(
                        [
                            {
                                "Config": {
                                    "Labels": {
                                        "verigym.owner": runner.IDENTITY,
                                        "verigym.role": "identity-probe-cleanup",
                                    }
                                }
                            }
                        ]
                    )
                )
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
                                "Name": name,
                                "Driver": "local",
                                "Labels": {"verigym.owner": runner.IDENTITY, "verigym.role": role},
                                "Options": {"device": str(backing), "o": "bind", "type": "none"},
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
    assert receipt["status"] == "cleanup_unconfirmed"
    assert "private" not in json.dumps(receipt, sort_keys=True)


def test_v123_execution_boundary_rejects_provider_and_docker_endpoint(
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
