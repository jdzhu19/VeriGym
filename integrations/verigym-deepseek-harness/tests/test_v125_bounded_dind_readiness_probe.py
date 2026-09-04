from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import run_hwe_deepseek_harness_v123_bounded_dind_identity_probe as v123_runner
from scripts import run_hwe_deepseek_harness_v125_bounded_dind_readiness_probe as runner
from verigym.core.errors import ConfigurationError
from verigym.hwe.deepseek_harness_campaign import (
    load_v125_bounded_dind_readiness_probe_manifest,
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
        dind_data_volume="verigym-deepseek-harness-v125-dind-data",
        dind_socket_volume="verigym-deepseek-harness-v125-dind-socket",
        startup_attempt_limit=1,
        startup_command_timeout_seconds=60,
        readiness_timeout_seconds=120,
        readiness_command_timeout_seconds=5,
        readiness_poll_interval_seconds=1,
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


def test_v125_manifest_freezes_exact_readiness_and_closed_policy() -> None:
    manifest = load_v125_bounded_dind_readiness_probe_manifest(runner.MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.v124_audit_commit == "013154e899b4a0622dabf75f51d87a309d1b5b3b"
    assert manifest.v124_post_merge_main_run_id == 33826887799
    assert manifest.startup_attempt_limit == 1
    assert manifest.readiness_timeout_seconds == 120
    assert manifest.readiness_command_timeout_seconds == 5
    assert manifest.readiness_poll_interval_seconds == 1
    assert manifest.json_info_readiness_allowed is False
    assert manifest.fixed_poll_count_cap_allowed is False
    assert manifest.explicit_readiness_requires_empty_stderr is True
    assert manifest.explicit_readiness_requires_three_values is True
    assert manifest.explicit_readiness_requires_exact_identity is True
    assert manifest.predecessor_volume_inspection_allowed is False
    assert manifest.predecessor_volume_mutation_allowed is False
    assert manifest.task_archive_access_allowed is False
    assert manifest.task_materialization_allowed is False
    assert manifest.harness_controller_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.provider_credentials_available is False
    assert manifest.provider_request_started is False
    assert manifest.provider_calls == 0
    assert all(getattr(manifest, name) is False for name in runner._CLOSED_FLAGS)


def test_v125_waits_through_false_positive_then_qualifies_exact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    readiness_calls = 0
    legacy_identity = v123_runner.IDENTITY
    legacy_control = v123_runner.CONTROL_ROOT

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            nonlocal readiness_calls
            assert max_output_bytes == 65536
            if arguments[0] == "run":
                assert timeout_s == 60
                return _result(stdout="c" * 64 + "\n")
            if arguments[:2] == ["container", "inspect"]:
                return _outer_inspect(manifest, control)
            if arguments[:4] == ["exec", "probe", "docker", "info"]:
                readiness_calls += 1
                assert timeout_s == 5
                assert "{{json .}}" not in arguments
                if readiness_calls == 1:
                    return _result(stdout="\t\t\n", stderr="cannot connect to daemon")
                return _result(stdout="23.0.6\tvfs\trunc\n")
            raise AssertionError(arguments)

    receipt = runner._run_readiness_probe(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "passed"
    assert receipt["diagnostic_category"] == "dind_identity_qualified"
    assert receipt["daemon_ready"] is True
    assert receipt["identity_qualified"] is True
    assert receipt["readiness_poll_count"] == 2
    assert receipt["readiness_stderr_bytes"] == 0
    assert receipt["readiness_value_count"] == 3
    assert receipt["json_info_readiness_used"] is False
    assert receipt["fixed_poll_count_cap_used"] is False
    assert v123_runner.IDENTITY == legacy_identity
    assert v123_runner.CONTROL_ROOT == legacy_control


def test_v125_has_no_twenty_four_poll_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    readiness_calls = 0

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            nonlocal readiness_calls
            del timeout_s, max_output_bytes
            if arguments[0] == "run":
                return _result(stdout="d" * 64 + "\n")
            if arguments[:2] == ["container", "inspect"]:
                return _outer_inspect(manifest, control)
            if arguments[:4] == ["exec", "probe", "docker", "info"]:
                readiness_calls += 1
                if readiness_calls <= 25:
                    return _result(exit_code=1, stderr="daemon unavailable")
                return _result(stdout="23.0.6\tvfs\trunc\n")
            raise AssertionError(arguments)

    receipt = runner._run_readiness_probe(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "passed"
    assert receipt["readiness_poll_count"] == 26
    assert readiness_calls == 26


def test_v125_clean_complete_identity_mismatch_fails_immediately_without_raw_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
    secret = "unexpected-runtime-secret"
    sleeps = 0

    def sleep(_: float) -> None:
        nonlocal sleeps
        sleeps += 1

    monkeypatch.setattr(runner.time, "sleep", sleep)

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            del timeout_s, max_output_bytes
            if arguments[0] == "run":
                return _result(stdout="e" * 64 + "\n")
            if arguments[:2] == ["container", "inspect"]:
                return _outer_inspect(manifest, control)
            if arguments[:4] == ["exec", "probe", "docker", "info"]:
                return _result(stdout=f"23.0.6\tvfs\t{secret}\n")
            raise AssertionError(arguments)

    receipt = runner._run_readiness_probe(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "probe_failed"
    assert receipt["diagnostic_category"] == "explicit_info_identity_mismatch"
    assert receipt["readiness_poll_count"] == 1
    assert receipt["readiness_default_runtime_equal"] is False
    assert sleeps == 0
    assert secret not in json.dumps(receipt, sort_keys=True)


def test_v125_monotonic_deadline_stops_transient_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setattr(runner, "CONTROL_ROOT", control)
    ticks = iter((0.0, 0.0, 120.0, 120.0))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(ticks))
    sleeps = 0

    def sleep(_: float) -> None:
        nonlocal sleeps
        sleeps += 1

    monkeypatch.setattr(runner.time, "sleep", sleep)

    class Engine:
        def _invoke(
            self, arguments: list[str], *, timeout_s: int, max_output_bytes: int
        ) -> EngineResult:
            del timeout_s, max_output_bytes
            if arguments[0] == "run":
                return _result(stdout="f" * 64 + "\n")
            if arguments[:2] == ["container", "inspect"]:
                return _outer_inspect(manifest, control)
            if arguments[:4] == ["exec", "probe", "docker", "info"]:
                return _result(exit_code=1, stderr="daemon unavailable")
            raise AssertionError(arguments)

    receipt = runner._run_readiness_probe(manifest, Engine(), "probe")  # type: ignore[arg-type]

    assert receipt["status"] == "probe_failed"
    assert receipt["diagnostic_category"] == "dind_readiness_timeout"
    assert receipt["readiness_last_category"] == "nonzero_exit"
    assert receipt["readiness_poll_count"] == 1
    assert sleeps == 0


@pytest.mark.parametrize(
    ("result", "count", "expected"),
    [
        (_result(timed_out=True), 0, "timeout"),
        (_result(truncated=True), 0, "output_bound_exceeded"),
        (_result(exit_code=1), 0, "nonzero_exit"),
        (_result(stderr="private"), 1, "stderr_present"),
        (_result(), 1, "invalid_value_count"),
        (_result(), 3, "complete_identity"),
    ],
)
def test_v125_readiness_classification_is_allowlisted(
    result: EngineResult, count: int, expected: str
) -> None:
    assert runner._classify_readiness(result, count) == expected


def test_v125_cleanup_uses_only_owned_fresh_v125_resources(
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
                assert helper_name.startswith("verigym-dind-v125-cleanup-")
                assert f"verigym.owner={runner.IDENTITY}" in arguments
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


def test_v125_execution_boundary_rejects_provider_and_docker_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = SimpleNamespace(
        manifest=runner.MANIFEST,
        output=runner.OUTPUT_ROOT,
        post_merge_main_run_id=33826887799,
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


def test_v125_execution_boundary_requires_positive_post_merge_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = SimpleNamespace(
        manifest=runner.MANIFEST,
        output=runner.OUTPUT_ROOT,
        post_merge_main_run_id=0,
    )
    monkeypatch.setenv(runner.OPT_IN_ENV, "1")
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1000)
    for name in runner._PROVIDER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)

    with pytest.raises(ConfigurationError, match="positive post-merge"):
        runner._require_execution_boundary(arguments)
