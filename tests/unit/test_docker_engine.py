from __future__ import annotations

from collections.abc import Iterable

import pytest

from verigym.runtimes.docker.engine import DockerCliEngine, EngineResult, execute_container
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
