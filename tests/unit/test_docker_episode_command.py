from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from verigym.runtimes.docker.engine import EngineResult
from verigym.runtimes.docker.episode_command import DockerEpisodeCommandExecutor
from verigym.runtimes.docker.mounts import MountSpec
from verigym.schemas.common import RuntimeImageIdentity
from verigym.schemas.runtime import (
    DockerCommandImageRuntimeConfig,
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
)
from verigym.schemas.tool import CommandSpec

IMAGE_ID = "sha256:" + "c" * 64
VERIFIER_IMAGE_ID = "sha256:" + "d" * 64
RG_SHA256 = "e" * 64
USER = "10001:10001"


class EpisodeEngine:
    backend_type = "episode-test"

    def __init__(self) -> None:
        self.create_calls = 0
        self.start_calls = 0
        self.exec_calls: list[dict[str, object]] = []
        self.killed: list[str] = []
        self.removed: list[str] = []
        self.running = False
        self.leaked = False
        self.fail_kill = False
        self.payload: dict[str, Any] = {}

    def create_container(self, arguments: list[str]) -> str:
        self.create_calls += 1
        image_index = arguments.index(IMAGE_ID)
        environment = _all_values(arguments[:image_index], "--env")
        labels = _all_values(arguments[:image_index], "--label")
        mounts = _all_values(arguments[:image_index], "--mount")
        mount_payload = []
        for raw in mounts:
            values = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
            mount_payload.append(
                {
                    "Type": values["type"],
                    "Source": values["src"],
                    "Target": values["dst"],
                    "ReadOnly": "readonly" in raw.split(","),
                }
            )
        tmpfs = _value(arguments, "--tmpfs")
        self.payload = {
            "HostConfig": {
                "NetworkMode": _value(arguments, "--network"),
                "ReadonlyRootfs": "--read-only" in arguments,
                "Privileged": False,
                "CapDrop": [_value(arguments, "--cap-drop")],
                "SecurityOpt": [_value(arguments, "--security-opt")],
                "Init": "--init" in arguments,
                "PidMode": "",
                "IpcMode": _value(arguments, "--ipc"),
                "Memory": int(_value(arguments, "--memory")),
                "MemorySwap": int(_value(arguments, "--memory-swap")),
                "NanoCpus": round(float(_value(arguments, "--cpus")) * 1e9),
                "PidsLimit": int(_value(arguments, "--pids-limit")),
                "Tmpfs": {"/tmp": tmpfs.split(":", 1)[1]},
                "Mounts": mount_payload,
            },
            "Config": {
                "User": _value(arguments, "--user"),
                "StopTimeout": int(_value(arguments, "--stop-timeout")),
                "Env": environment,
                "Labels": dict(item.split("=", 1) for item in labels),
            },
            "State": {"Status": "created", "OOMKilled": False, "ExitCode": 0},
        }
        assert arguments[image_index + 1 :] == ["/usr/bin/tail", "-f", "/dev/null"]
        return "episode-1"

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        assert container_id == "episode-1"
        return self.payload

    def start_container(self, container_id: str) -> EngineResult:
        assert container_id == "episode-1"
        self.start_calls += 1
        self.running = True
        self.payload["State"]["Status"] = "running"
        return _result()

    def exec_container(
        self,
        container_id: str,
        *,
        argv: list[str],
        user: str,
        cwd: str,
        environment: dict[str, str],
        timeout_s: int,
        max_output_bytes: int,
    ) -> EngineResult:
        assert container_id == "episode-1"
        self.exec_calls.append(
            {
                "argv": argv,
                "user": user,
                "cwd": cwd,
                "environment": environment,
                "timeout_s": timeout_s,
                "max_output_bytes": max_output_bytes,
            }
        )
        command = argv[2]
        if command == "timeout":
            return _result(timed_out=True, exit_code=-9, stdout="partial\n")
        if command == "oom":
            return _result(exit_code=137)
        if command == "leak":
            self.leaked = True
        return _result(stdout="ok\n")

    def top_container(self, container_id: str) -> EngineResult:
        assert container_id == "episode-1"
        output = "PID PPID COMMAND\n100 0 docker-init\n101 100 tail\n"
        if self.leaked:
            output += "222 101 sleep\n"
        return _result(stdout=output)

    def kill_container(self, container_id: str) -> EngineResult:
        self.killed.append(container_id)
        if self.fail_kill:
            return _result(exit_code=1)
        self.running = False
        self.payload["State"]["Status"] = "exited"
        return _result()

    def remove_container(self, container_id: str, *, force: bool = True) -> EngineResult:
        assert force
        self.removed.append(container_id)
        return _result()


def _result(
    *,
    exit_code: int | None = 0,
    stdout: str = "",
    timed_out: bool = False,
) -> EngineResult:
    return EngineResult(
        argv=["docker"],
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        duration_s=0.01,
        timed_out=timed_out,
    )


def _value(arguments: list[str], option: str) -> str:
    return arguments[arguments.index(option) + 1]


def _all_values(arguments: list[str], option: str) -> list[str]:
    return [arguments[index + 1] for index, value in enumerate(arguments) if value == option]


def _config() -> DockerCommandImageRuntimeConfig:
    return DockerCommandImageRuntimeConfig(
        image="example:command",
        expected_image_id=IMAGE_ID,
        expected_rg_version="ripgrep 14.1.1",
        expected_rg_sha256=RG_SHA256,
        protocol="hwe_command_image_v1",
        execution_backend="episode_container_exec_v1",
        required_image_labels={"org.verigym.runtime.role": "hwe-command"},
        run_as_user=USER,
        max_command_time_s=7,
        max_output_bytes=4096,
    )


def _executor(engine: EpisodeEngine) -> DockerEpisodeCommandExecutor:
    image = RuntimeImageIdentity(
        requested_reference="example:command",
        resolved_image_id=IMAGE_ID,
        os="linux",
        architecture="amd64",
        configured_image_user=USER,
        effective_user=USER,
    )
    active: set[str] = set()

    def register(container_id: str) -> None:
        active.add(container_id)

    def remove(container_id: str) -> str | None:
        result = engine.remove_container(container_id, force=True)
        active.discard(container_id)
        return None if result.exit_code == 0 else "cleanup failed"

    return DockerEpisodeCommandExecutor(
        engine=engine,  # type: ignore[arg-type]
        image=image,
        config=_config(),
        run_id="run-1",
        session_id="session-1",
        register_container=register,
        remove_container=remove,
    )


def test_episode_container_is_reused_without_codex_environment(tmp_path: Path) -> None:
    engine = EpisodeEngine()
    executor = _executor(engine)
    mounts = [MountSpec(tmp_path, "/workspace/repository", False)]

    first = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "first"], timeout_s=30), mounts=mounts
    )
    second = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "second"], timeout_s=5), mounts=mounts
    )

    assert first.exit_code == second.exit_code == 0
    assert engine.create_calls == engine.start_calls == 1
    assert len(engine.exec_calls) == 2
    assert first.metadata["episode_container_reused"] is False
    assert second.metadata["episode_container_reused"] is True
    assert second.metadata["command_execution_backend"] == "episode_container_exec_v1"
    assert engine.exec_calls[0]["timeout_s"] == 7
    assert engine.exec_calls[1]["timeout_s"] == 5
    environment = engine.exec_calls[0]["environment"]
    assert isinstance(environment, dict)
    assert "CODEX_HOME" not in environment


def test_timeout_destroys_and_poisons_episode_container(tmp_path: Path) -> None:
    engine = EpisodeEngine()
    executor = _executor(engine)
    mounts = [MountSpec(tmp_path, "/workspace/repository", False)]

    timed_out = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "timeout"], timeout_s=3), mounts=mounts
    )
    rejected = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "later"], timeout_s=3), mounts=mounts
    )

    assert timed_out.timed_out
    assert timed_out.failure_reason == "timeout"
    assert engine.killed == engine.removed == ["episode-1"]
    assert rejected.failure_reason == "episode_container_poisoned"
    assert len(engine.exec_calls) == 1


def test_exec_exit_137_conservatively_invalidates_episode_container(tmp_path: Path) -> None:
    engine = EpisodeEngine()
    executor = _executor(engine)
    result = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "oom"], timeout_s=3),
        mounts=[MountSpec(tmp_path, "/workspace/repository", False)],
    )

    assert result.oom_killed
    assert result.failure_reason == "out_of_memory"
    assert engine.killed == engine.removed == ["episode-1"]


def test_background_process_leak_is_redacted_and_fails_closed(tmp_path: Path) -> None:
    engine = EpisodeEngine()
    executor = _executor(engine)
    result = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "leak"], timeout_s=3),
        mounts=[MountSpec(tmp_path, "/workspace/repository", False)],
    )

    assert result.failure_reason == "residual_process_detected"
    assert result.failure_origin == "candidate_process"
    assert result.metadata["process_inventory"] == {
        "expected_count": 2,
        "observed_count": 3,
        "raw_process_data_persisted": False,
    }
    assert "sleep" not in str(result.metadata)
    assert engine.killed == engine.removed == ["episode-1"]


def test_closing_episode_executor_removes_container_and_rejects_later_commands(
    tmp_path: Path,
) -> None:
    engine = EpisodeEngine()
    executor = _executor(engine)
    mounts = [MountSpec(tmp_path, "/workspace/repository", False)]
    first = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "first"], timeout_s=3), mounts=mounts
    )

    assert first.exit_code == 0
    assert executor.close() is None
    assert engine.killed == engine.removed == ["episode-1"]
    rejected = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "later"], timeout_s=3), mounts=mounts
    )
    assert rejected.failure_reason == "episode_container_poisoned"


def test_successful_force_remove_supersedes_best_effort_kill_failure(tmp_path: Path) -> None:
    engine = EpisodeEngine()
    executor = _executor(engine)
    result = executor.execute(
        CommandSpec(argv=["/bin/bash", "-lc", "first"], timeout_s=3),
        mounts=[MountSpec(tmp_path, "/workspace/repository", False)],
    )
    engine.fail_kill = True

    assert result.exit_code == 0
    assert executor.close() is None
    assert engine.killed == engine.removed == ["episode-1"]


def test_command_image_is_separate_from_external_agent_and_verifier_roles() -> None:
    command = _config()
    external = DockerExternalAgentRuntimeConfig(
        image="example:agent",
        expected_image_id="sha256:" + "a" * 64,
        expected_executable_name="codex",
        expected_executable_path="/usr/local/bin/codex",
        expected_executable_version="codex-cli 0.147.0",
        expected_executable_sha256="b" * 64,
        process_argv=["/usr/local/bin/codex", "exec-server"],
        protocol="legacy",
        required_image_labels={"org.verigym.runtime.role": "external-agent"},
        run_as_user=USER,
    )
    with pytest.raises(ValidationError, match="mutually exclusive"):
        DockerRuntimeConfig(
            image="example:verifier",
            expected_image_id=VERIFIER_IMAGE_ID,
            command_image=command,
            external_agent=external,
        )
    with pytest.raises(ValidationError, match="separately identified"):
        DockerRuntimeConfig(
            image=command.image,
            expected_image_id=VERIFIER_IMAGE_ID,
            command_image=command,
        )
