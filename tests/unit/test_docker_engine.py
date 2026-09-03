from __future__ import annotations

import os
import socket
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from verigym.runtimes.docker.engine import (
    DockerCliEngine,
    EngineResult,
    execute_container,
    validate_local_docker_host,
)
from verigym.runtimes.docker.errors import DockerDaemonError


def _result(
    argv: list[str],
    *,
    exit_code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
    duration_s: float = 0.01,
    timed_out: bool = False,
    output_truncated: bool = False,
) -> EngineResult:
    return EngineResult(
        argv=argv,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_s=duration_s,
        timed_out=timed_out,
        output_truncated=output_truncated,
    )


class PhaseEngine:
    def __init__(
        self,
        *,
        start: EngineResult,
        waits: Iterable[EngineResult],
        logs: EngineResult,
        kill: EngineResult | None = None,
    ) -> None:
        self.start_result = start
        self.wait_results = iter(waits)
        self.logs_result = logs
        self.kill_result = kill or _result(["docker", "kill"])
        self.calls: list[tuple[str, int | None]] = []

    def start_container(self, container_id: str) -> EngineResult:
        self.calls.append((f"start:{container_id}", None))
        return self.start_result

    def wait_container(self, container_id: str, *, timeout_s: int) -> EngineResult:
        self.calls.append((f"wait:{container_id}", timeout_s))
        return next(self.wait_results)

    def logs_container(self, container_id: str, *, max_output_bytes: int) -> EngineResult:
        self.calls.append((f"logs:{container_id}", max_output_bytes))
        return self.logs_result

    def kill_container(self, container_id: str) -> EngineResult:
        self.calls.append((f"kill:{container_id}", None))
        return self.kill_result


def test_start_latency_is_not_charged_to_candidate_runtime_timeout() -> None:
    engine = PhaseEngine(
        start=_result(["docker", "start"], duration_s=5.0),
        waits=[_result(["docker", "wait"], stdout="0\n", duration_s=56.0)],
        logs=_result(["docker", "logs"], stdout="healthy\n", duration_s=0.5),
    )

    result = execute_container(
        engine,  # type: ignore[arg-type]
        "container-1",
        timeout_s=60,
        max_output_bytes=4096,
    )

    assert not result.timed_out
    assert result.exit_code == 0
    assert result.stdout == "healthy\n"
    assert sum(result.phase_durations_s.values()) == 61.5
    assert result.execution_protocol == "docker_detached_start_wait_logs_v1"
    assert engine.calls == [
        ("start:container-1", None),
        ("wait:container-1", 60),
        ("logs:container-1", 4096),
    ]


def test_runtime_timeout_kills_waits_and_then_collects_bounded_logs() -> None:
    engine = PhaseEngine(
        start=_result(["docker", "start"]),
        waits=[
            _result(["docker", "wait"], exit_code=-9, duration_s=60.0, timed_out=True),
            _result(["docker", "wait"], stdout="137\n", duration_s=0.2),
        ],
        logs=_result(
            ["docker", "logs"],
            stdout="partial\n",
            duration_s=0.1,
            output_truncated=True,
        ),
    )

    result = execute_container(
        engine,  # type: ignore[arg-type]
        "container-2",
        timeout_s=60,
        max_output_bytes=1024,
    )

    assert result.timed_out
    assert result.exit_code == 137
    assert result.stdout == "partial\n"
    assert result.output_truncated
    assert engine.calls == [
        ("start:container-2", None),
        ("wait:container-2", 60),
        ("kill:container-2", None),
        ("wait:container-2", 60),
        ("logs:container-2", 1024),
    ]


def test_control_plane_failure_retains_only_structured_phase_diagnostics() -> None:
    engine = PhaseEngine(
        start=_result(
            ["docker", "start"],
            exit_code=-9,
            stderr="daemon endpoint detail",
            duration_s=60.0,
            timed_out=True,
        ),
        waits=[],
        logs=_result(["docker", "logs"]),
    )

    with pytest.raises(DockerDaemonError) as raised:
        execute_container(
            engine,  # type: ignore[arg-type]
            "container-3",
            timeout_s=60,
            max_output_bytes=1024,
        )

    assert raised.value.subreason == "container_start_timeout"
    assert raised.value.origin == "container_execution"
    assert raised.value.details == {
        "stage": "container start",
        "duration_s": 60.0,
        "timed_out": True,
        "exit_code": -9,
    }
    assert "daemon endpoint detail" not in str(raised.value)


def test_control_plane_failure_does_not_promote_raw_transport_output() -> None:
    engine = PhaseEngine(
        start=_result(
            ["docker", "start"],
            exit_code=1,
            stderr="candidate-controlled or daemon diagnostic bytes",
            duration_s=0.5,
        ),
        waits=[],
        logs=_result(["docker", "logs"]),
    )

    with pytest.raises(DockerDaemonError) as raised:
        execute_container(
            engine,  # type: ignore[arg-type]
            "container-raw-diagnostic",
            timeout_s=60,
            max_output_bytes=1024,
        )

    assert raised.value.subreason == "container_start_failed"
    assert "diagnostic bytes" not in str(raised.value)
    assert raised.value.details["stage"] == "container start"


def test_docker_cli_uses_separate_control_runtime_and_log_deadlines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = DockerCliEngine(executable="/usr/bin/docker")
    observed: list[tuple[list[str], int, int]] = []

    def invoke(
        arguments: list[str],
        *,
        timeout_s: int,
        max_output_bytes: int = 1024 * 1024,
    ) -> EngineResult:
        observed.append((arguments, timeout_s, max_output_bytes))
        return _result(["docker", *arguments], stdout="0\n" if arguments[0] == "wait" else "")

    monkeypatch.setattr(engine, "_invoke", invoke)
    engine.start_container("container-4")
    engine.wait_container("container-4", timeout_s=37)
    engine.logs_container("container-4", max_output_bytes=1234)

    assert observed == [
        (["start", "container-4"], 60, 1024 * 1024),
        (["wait", "container-4"], 37, 64 * 1024),
        (["logs", "container-4"], 60, 1234),
    ]


def test_docker_cli_exec_uses_argv_options_and_a_candidate_only_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = DockerCliEngine(executable="/usr/bin/docker")
    observed: list[tuple[list[str], int, int]] = []

    def invoke(
        arguments: list[str],
        *,
        timeout_s: int,
        max_output_bytes: int = 1024 * 1024,
    ) -> EngineResult:
        observed.append((arguments, timeout_s, max_output_bytes))
        return _result(["docker", *arguments])

    monkeypatch.setattr(engine, "_invoke", invoke)
    engine.exec_container(
        "container-5",
        argv=["/bin/bash", "-lc", "printf ok"],
        user="10001:10001",
        cwd="/workspace/repository",
        environment={"PATH": "/usr/bin", "HOME": "/tmp/home"},
        timeout_s=17,
        max_output_bytes=2048,
    )
    engine.top_container("container-5")

    assert observed == [
        (
            [
                "exec",
                "--user",
                "10001:10001",
                "--workdir",
                "/workspace/repository",
                "--env",
                "HOME=/tmp/home",
                "--env",
                "PATH=/usr/bin",
                "container-5",
                "/bin/bash",
                "-lc",
                "printf ok",
            ],
            17,
            2048,
        ),
        (["top", "container-5", "-eo", "pid,ppid,comm"], 60, 256 * 1024),
    ]


class _CompletedPopen:
    def __init__(
        self,
        argv: list[str],
        *,
        stdout: Any,
        stderr: Any,
        env: dict[str, str],
        **kwargs: Any,
    ) -> None:
        del argv, stderr, kwargs
        self.pid = os.getpid()
        self.returncode = 0
        self.environment = dict(env)
        stdout.write(b"{}\n")

    def communicate(self, timeout: int | None = None) -> tuple[None, None]:
        del timeout
        return None, None


def _unix_socket(path: Path) -> socket.socket:
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.bind(str(path))
    return endpoint


def test_docker_cli_propagates_only_an_explicit_local_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_path = tmp_path / "docker.sock"
    endpoint = _unix_socket(socket_path)
    observed: list[dict[str, str]] = []

    def popen(*args: Any, **kwargs: Any) -> _CompletedPopen:
        process = _CompletedPopen(*args, **kwargs)
        observed.append(process.environment)
        return process

    monkeypatch.setattr("verigym.runtimes.docker.engine.subprocess.Popen", popen)
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted.example:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "untrusted-context")
    monkeypatch.setenv("VERIGYM_UNRELATED_SECRET", "must-not-propagate")
    try:
        DockerCliEngine(executable="/usr/bin/docker").version()
        DockerCliEngine(executable="/usr/bin/docker", docker_host=f"unix://{socket_path}").version()
    finally:
        endpoint.close()

    assert "DOCKER_HOST" not in observed[0]
    assert observed[1]["DOCKER_HOST"] == f"unix://{socket_path}"
    assert set(observed[1]) == {"PATH", "LANG", "LC_ALL", "DOCKER_HOST"}


@pytest.mark.parametrize(
    "value",
    [
        "tcp://127.0.0.1:2375",
        "ssh://docker.example",
        "unix://relative/docker.sock",
        "unix:///tmp/docker.sock?query=1",
        "unix:///tmp/docker.sock#fragment",
        "unix:///tmp/%64ocker.sock",
    ],
)
def test_local_docker_host_rejects_remote_relative_or_encoded_endpoints(value: str) -> None:
    with pytest.raises(ValueError, match="docker_host"):
        validate_local_docker_host(value)


def test_local_docker_host_rejects_symlinks_and_non_sockets(tmp_path: Path) -> None:
    regular = tmp_path / "not-a-socket"
    regular.write_text("not a socket", encoding="utf-8")
    link = tmp_path / "socket-link"
    link.symlink_to(regular)

    with pytest.raises(ValueError, match="not a Unix socket"):
        validate_local_docker_host(f"unix://{regular}")
    with pytest.raises(ValueError, match="canonical and not a symlink"):
        validate_local_docker_host(f"unix://{link}")
