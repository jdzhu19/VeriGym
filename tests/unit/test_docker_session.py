from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError, MissingDependencyError, PathPolicyError
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.docker.engine import EngineResult
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import RuntimeDescriptor, ToolchainProfile
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.tool import CommandSpec

IMAGE_ID = "sha256:" + "d" * 64


class RecordingDockerEngine:
    backend_type = "recording_docker"

    def __init__(self) -> None:
        self.inspect_image_calls: list[str] = []
        self.pull_calls: list[str] = []
        self.create_arguments: list[list[str]] = []
        self.containers: dict[str, dict[str, Any]] = {}
        self.removed: list[str] = []
        self.killed: list[str] = []
        self.closed = False
        self.fail_removal = False
        self.missing_commands: set[str] = set()

    def version(self) -> dict[str, Any]:
        return {
            "Client": {"Version": "fake-client"},
            "Server": {
                "Version": "fake-server",
                "ApiVersion": "1.99",
                "Os": "linux",
                "Arch": "amd64",
            },
        }

    def info(self) -> dict[str, Any]:
        return {
            "MemoryLimit": True,
            "SwapLimit": True,
            "CpuCfsPeriod": True,
            "CpuCfsQuota": True,
            "PidsLimit": True,
            "SecurityOptions": ["name=seccomp,profile=builtin"],
        }

    def inspect_image(self, reference: str) -> dict[str, Any] | None:
        self.inspect_image_calls.append(reference)
        return {
            "Id": IMAGE_ID,
            "RepoDigests": None,
            "Created": "2026-01-01T00:00:00Z",
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {"User": "10001:10001", "Env": ["PATH=/usr/bin"]},
        }

    def pull_image(self, reference: str) -> None:
        self.pull_calls.append(reference)

    def create_container(self, arguments: list[str]) -> str:
        self.create_arguments.append(list(arguments))
        container_id = f"container-{len(self.create_arguments):04d}"
        image_index = arguments.index(IMAGE_ID)
        command = arguments[image_index + 1 :]
        environments = _all_option_values(arguments[:image_index], "--env")
        labels = _all_option_values(arguments[:image_index], "--label")
        mounts = _all_option_values(arguments[:image_index], "--mount")
        mount_payload = []
        for raw_mount in mounts:
            values = dict(part.split("=", 1) for part in raw_mount.split(",") if "=" in part)
            mount_payload.append(
                {
                    "Type": values["type"],
                    "Source": values["src"],
                    "Target": values["dst"],
                }
            )
        tmpfs = _option_value(arguments, "--tmpfs")
        self.containers[container_id] = {
            "payload": {
                "HostConfig": {
                    "NetworkMode": _option_value(arguments, "--network"),
                    "ReadonlyRootfs": "--read-only" in arguments,
                    "Privileged": False,
                    "CapDrop": [_option_value(arguments, "--cap-drop")],
                    "SecurityOpt": [_option_value(arguments, "--security-opt")],
                    "Init": "--init" in arguments,
                    "Memory": int(_option_value(arguments, "--memory")),
                    "MemorySwap": int(_option_value(arguments, "--memory-swap")),
                    "NanoCpus": round(float(_option_value(arguments, "--cpus")) * 1e9),
                    "PidsLimit": int(_option_value(arguments, "--pids-limit")),
                    "Tmpfs": {"/tmp": tmpfs.split(":", 1)[1]},
                    "Mounts": mount_payload,
                },
                "Config": {
                    "User": _option_value(arguments, "--user"),
                    "StopTimeout": int(_option_value(arguments, "--stop-timeout")),
                    "Env": environments,
                    "Labels": dict(value.split("=", 1) for value in labels),
                },
                "State": {"Status": "created", "OOMKilled": False, "ExitCode": 0},
            },
            "command": command,
        }
        return container_id

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        return self.containers[container_id]["payload"]

    def start_attach(
        self, container_id: str, *, timeout_s: int, max_output_bytes: int
    ) -> EngineResult:
        command = self.containers[container_id]["command"]
        state = self.containers[container_id]["payload"]["State"]
        stdout = ""
        stderr = ""
        exit_code = 0
        timed_out = False
        truncated = False
        if command and command[0] in self.missing_commands:
            stderr = f"{command[0]}: not found\n"
            exit_code = 127
            state.update({"Status": "exited", "ExitCode": 127})
        elif command == ["id", "-u"]:
            stdout = "10001\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["id", "-g"]:
            stdout = "10001\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["iverilog", "-V"]:
            stdout = "Icarus Verilog version 12.0 (stable) (v12_0)\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["vvp", "-V"]:
            stdout = "Icarus Verilog runtime version 12.0 (stable) (v12_0)\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["yosys", "-V"]:
            stdout = (
                "Yosys 0.67+post (git sha1 b8e7da6f40ae8f552c116bf6c359b07c6533e159, gcc 14.2.0)\n"
            )
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["yosys-abc", "-c", "version; quit"]:
            stdout = "UC Berkeley, ABC 1.01 (compiled Jul 22 2026 00:00:00)\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["verigym-toolchain-identity"]:
            stdout = (
                "Yosys vendored source identity: "
                "b8e7da6f40ae8f552c116bf6c359b07c6533e159\n"
                "ABC vendored source identity: "
                "e026ed5380f3bdc3beea2ff9ffc23236fc549d5b\n"
            )
            state.update({"Status": "exited", "ExitCode": 0})
        elif command and command[0] == "sleepy":
            stdout = "partial\n"
            timed_out = True
            state.update({"Status": "running", "ExitCode": 0})
        elif command and command[0] == "hungry":
            exit_code = 137
            state.update({"Status": "exited", "OOMKilled": True, "ExitCode": 137})
        elif command and command[0] == "daemon-broken":
            exit_code = 125
            state.update({"Status": "created", "Error": "runtime create failed", "ExitCode": 125})
        elif command and command[0] == "large-output":
            stdout = "x" * max_output_bytes
            truncated = True
            state.update({"Status": "exited", "ExitCode": 0})
        else:
            stdout = "ok\n"
            state.update({"Status": "exited", "ExitCode": 0})
        return EngineResult(
            argv=["docker", "start", "--attach", container_id],
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=0.01,
            timed_out=timed_out,
            output_truncated=truncated,
        )

    def kill_container(self, container_id: str) -> EngineResult:
        self.killed.append(container_id)
        self.containers[container_id]["payload"]["State"].update(
            {"Status": "exited", "ExitCode": 137}
        )
        return _engine_success()

    def remove_container(self, container_id: str, *, force: bool = True) -> EngineResult:
        del force
        if self.fail_removal:
            return EngineResult(
                argv=["docker", "rm", container_id],
                exit_code=1,
                stdout="",
                stderr="daemon cleanup error",
                duration_s=0.01,
            )
        self.removed.append(container_id)
        self.containers.pop(container_id, None)
        return _engine_success()

    def list_managed_containers(self) -> list[str]:
        return sorted(self.containers)

    def list_managed_volumes(self) -> list[str]:
        return []

    def close(self) -> None:
        self.closed = True


def _engine_success() -> EngineResult:
    return EngineResult(
        argv=["docker"],
        exit_code=0,
        stdout="",
        stderr="",
        duration_s=0.01,
    )


def _option_value(arguments: list[str], option: str) -> str:
    return arguments[arguments.index(option) + 1]


def _all_option_values(arguments: list[str], option: str) -> list[str]:
    return [arguments[index + 1] for index, value in enumerate(arguments) if value == option]


def _prepared_runtime(
    engine: RecordingDockerEngine,
    **configuration: object,
) -> DockerRuntime:
    config = DockerRuntimeConfig.model_validate({"image": "example:test", **configuration})
    runtime = DockerRuntime(config, engine=engine)
    runtime.prepare("unit-run")
    return runtime


def test_runtime_resolves_once_and_uses_same_image_for_distinct_sessions(tmp_path: Path) -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine)
    source = tmp_path / "source"
    source.mkdir()
    (source / "visible.txt").write_text("public", encoding="utf-8")
    agent = runtime.create_session(SessionSpec(source_dir=str(source), label="agent"))
    verifier = runtime.create_session(SessionSpec(source_dir=str(source), label="verifier"))
    try:
        result = agent.execute(CommandSpec(argv=["/usr/bin/example-tool"], timeout_s=5))
        verifier_result = verifier.execute(CommandSpec(argv=["example-tool"], timeout_s=5))
        assert result.argv == ["example-tool"]
        assert result.exit_code == 0
        assert verifier_result.exit_code == 0
        assert engine.inspect_image_calls == ["example:test"]
        assert all(IMAGE_ID in arguments for arguments in engine.create_arguments)
        records = runtime.descriptor.sessions
        agent_record = next(record for record in records if record.role == "agent")
        verifier_record = next(record for record in records if record.role == "verifier")
        assert agent_record.session_id != verifier_record.session_id
        assert agent_record.container_ids != verifier_record.container_ids
        assert agent_record.resolved_image_id == verifier_record.resolved_image_id == IMAGE_ID
    finally:
        agent.close()
        verifier.close()
        runtime.close()
    assert runtime.descriptor.cleanup is not None
    assert runtime.descriptor.cleanup.complete
    assert engine.list_managed_containers() == []


def test_timeout_oom_output_limit_and_control_plane_are_structured(tmp_path: Path) -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine, max_command_time_s=3)
    source = tmp_path / "source"
    source.mkdir()
    session = runtime.create_session(
        SessionSpec(source_dir=str(source), label="agent", max_output_bytes=32)
    )
    try:
        timeout = session.execute(CommandSpec(argv=["sleepy"], timeout_s=20))
        assert timeout.timed_out
        assert not timeout.oom_killed
        assert timeout.failure_reason == "timeout"
        assert timeout.failure_origin == "candidate_process"
        assert timeout.metadata["effective_timeout_s"] == 3
        oom = session.execute(CommandSpec(argv=["hungry"], timeout_s=3))
        assert oom.oom_killed
        assert not oom.timed_out
        assert oom.exit_code == 137
        assert oom.failure_reason == "out_of_memory"
        assert oom.failure_origin == "candidate_process"
        bounded = session.execute(CommandSpec(argv=["large-output"], timeout_s=3))
        assert bounded.output_truncated
        assert len(bounded.stdout) == 32
        daemon = session.execute(CommandSpec(argv=["daemon-broken"], timeout_s=3))
        assert daemon.error is not None
        assert daemon.failure_reason == "container_start_failed"
        assert daemon.failure_origin == "control_plane"
    finally:
        session.close()
        runtime.close()


def test_freeze_prevents_toc_tou_mutation_and_close_is_idempotent(tmp_path: Path) -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine)
    source = tmp_path / "source"
    source.mkdir()
    session = runtime.create_session(SessionSpec(source_dir=str(source), label="agent"))
    session.write_file("candidate.txt", b"final")
    session.freeze()
    with pytest.raises(PathPolicyError, match="not writable"):
        session.write_file("candidate.txt", b"changed")
    with pytest.raises(PathPolicyError, match="frozen"):
        session.execute(CommandSpec(argv=["example-tool"]))
    session.close()
    session.close()
    runtime.close()
    runtime.close()
    record = next(record for record in runtime.descriptor.sessions if record.role == "agent")
    assert record.frozen
    assert record.cleanup_complete


def test_cleanup_failure_preserves_primary_timeout_and_is_reported(tmp_path: Path) -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine)
    engine.fail_removal = True
    source = tmp_path / "source"
    source.mkdir()
    session = runtime.create_session(SessionSpec(source_dir=str(source), label="agent"))
    result = session.execute(CommandSpec(argv=["sleepy"], timeout_s=2))
    assert result.timed_out
    assert result.failure_reason == "timeout"
    assert "cleanup_warning" in result.metadata
    session.close()
    runtime.close()
    assert runtime.descriptor.cleanup is not None
    assert not runtime.descriptor.cleanup.complete
    assert runtime.descriptor.cleanup.warnings
    assert engine.list_managed_containers()


def test_runtime_descriptor_round_trip_and_exact_image_replay(tmp_path: Path) -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine)
    descriptor = runtime.descriptor
    restored = RuntimeDescriptor.model_validate_json(descriptor.model_dump_json())
    assert restored == descriptor
    runtime.close()

    replay_engine = RecordingDockerEngine()
    template = DockerRuntime(engine=replay_engine)
    replay_runtime = template.configure_for_replay(restored)
    replay_runtime.prepare("replay-run")
    source = tmp_path / "source"
    source.mkdir()
    session = replay_runtime.create_session(SessionSpec(source_dir=str(source), label="verifier"))
    session.execute(CommandSpec(argv=["example-tool"]))
    session.close()
    replay_runtime.close()
    assert replay_engine.inspect_image_calls == [IMAGE_ID]
    assert all(IMAGE_ID in arguments for arguments in replay_engine.create_arguments)
    replay_records = replay_runtime.descriptor.sessions
    assert [record.role for record in replay_records] == ["verifier"]
    assert len(replay_engine.create_arguments) == 1


def test_candidate_resource_failure_metadata_reaches_iverilog_tools() -> None:
    from verigym.schemas.common import ErrorCategory
    from verigym.schemas.tool import CompletedCommand
    from verigym.tools.iverilog import IverilogCompileRequest, IverilogCompileTool

    request = IverilogCompileRequest(sources=["rtl/a.v"], top="a")
    completed = CompletedCommand(
        argv=["iverilog"],
        cwd=".",
        exit_code=137,
        oom_killed=True,
        failure_reason="out_of_memory",
        failure_origin="candidate_process",
    )
    result = IverilogCompileTool().parse_result(request, completed, context=None)  # type: ignore[arg-type]
    assert result.category == ErrorCategory.OUT_OF_MEMORY
    assert result.metadata["candidate_failure"] is True
    assert result.metadata["resource_origin"] == "candidate_process"


def _profile_for_recording_image() -> ToolchainProfile:
    profile = build_registries(discover_external=False).profiles.get("open-yosys-toy-area-v1")
    profile.runtime.requested_image = "example:test"
    profile.container_image = "example:test"
    return profile


def test_docker_profile_resolution_records_actual_tools_and_is_canonical() -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine)
    profile = _profile_for_recording_image()
    try:
        first = resolve_toolchain_profile(
            profile,
            runtime,
            source_paths=["rtl/counter.v"],
            top_module="counter",
            reference_candidate_hash="a" * 64,
        )
        second = resolve_toolchain_profile(
            profile,
            runtime,
            source_paths=["rtl/counter.v"],
            top_module="counter",
            reference_candidate_hash="a" * 64,
        )
    finally:
        runtime.close()
    assert first == second
    assert first.runtime_identity.resolved_image_id == IMAGE_ID
    tools = {tool.logical_name: tool for tool in first.tool_identities}
    assert tools["yosys"].version == "0.67"
    assert tools["yosys"].git_hash == "b8e7da6f40ae8f552c116bf6c359b07c6533e159"
    assert tools["yosys-abc"].version == "1.01"
    assert tools["yosys-abc"].git_hash == "e026ed5380f3bdc3beea2ff9ffc23236fc549d5b"
    assert first.generated_script_hash


@pytest.mark.parametrize("missing", ["yosys", "yosys-abc"])
def test_docker_profile_resolution_distinguishes_missing_tools(missing: str) -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine)
    engine.missing_commands.add(missing)
    try:
        with pytest.raises(MissingDependencyError, match="identity command"):
            resolve_toolchain_profile(
                _profile_for_recording_image(),
                runtime,
                source_paths=["rtl/counter.v"],
                top_module="counter",
                reference_candidate_hash="a" * 64,
            )
    finally:
        runtime.close()


def test_docker_profile_resolution_refuses_observed_git_mismatch() -> None:
    engine = RecordingDockerEngine()
    runtime = _prepared_runtime(engine)
    profile = _profile_for_recording_image()
    profile.tools[0].git_hash = "0" * 40
    try:
        with pytest.raises(ConfigurationError, match="git identity"):
            resolve_toolchain_profile(
                profile,
                runtime,
                source_paths=["rtl/counter.v"],
                top_module="counter",
                reference_candidate_hash="a" * 64,
            )
    finally:
        runtime.close()
