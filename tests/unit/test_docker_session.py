from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import ConfigurationError, MissingDependencyError, PathPolicyError
from verigym.core.hashing import hash_directory
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.docker import runtime as docker_runtime_module
from verigym.runtimes.docker.engine import EngineResult
from verigym.runtimes.docker.mounts import MountSpec
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.runtimes.docker.session import _external_process_mounts
from verigym.schemas.common import RuntimeDescriptor, ToolchainProfile
from verigym.schemas.runtime import (
    DockerCommandImageRuntimeConfig,
    DockerExternalAgentRuntimeConfig,
    DockerRuntimeConfig,
    SessionReadOnlyMount,
    SessionSpec,
)
from verigym.schemas.tool import CommandSpec

IMAGE_ID = "sha256:" + "d" * 64
AGENT_IMAGE_ID = "sha256:" + "e" * 64
CODEX_SHA256 = "a" * 64
LAUNCHER_SHA256 = "b" * 64


def test_hwe_external_process_mount_maps_only_the_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    public = tmp_path / "public"
    workspace.mkdir()
    public.mkdir()
    mounts = _external_process_mounts(
        [
            MountSpec(source=public, destination="/verigym-public", read_only=True),
            MountSpec(source=workspace, destination="/workspace", read_only=False),
        ],
        logical_workspace_root="/workspace/repository",
    )
    assert [(item.destination, item.read_only) for item in mounts] == [
        ("/verigym-public", True),
        ("/workspace/repository", False),
    ]


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
        self.oom_public_tests = False
        self.missing_commands: set[str] = set()
        self.image_labels: dict[str, str] = {}

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
            "Id": (
                AGENT_IMAGE_ID
                if "repository-agent" in reference or "command" in reference
                else IMAGE_ID
            ),
            "RepoDigests": None,
            "Created": "2026-01-01T00:00:00Z",
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "User": "10001:10001",
                "Env": ["PATH=/usr/bin"],
                "Labels": self.image_labels,
            },
        }

    def pull_image(self, reference: str) -> None:
        self.pull_calls.append(reference)

    def create_container(self, arguments: list[str]) -> str:
        self.create_arguments.append(list(arguments))
        container_id = f"container-{len(self.create_arguments):04d}"
        image_index = next(
            index for index, value in enumerate(arguments) if value in {IMAGE_ID, AGENT_IMAGE_ID}
        )
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
                    "ReadOnly": "readonly" in raw_mount.split(","),
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
                    "PidMode": "",
                    "IpcMode": _option_value(arguments, "--ipc"),
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
            "image": arguments[image_index],
        }
        return container_id

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        return self.containers[container_id]["payload"]

    def start_container(self, container_id: str) -> EngineResult:
        self.containers[container_id]["payload"]["State"].update({"Status": "running"})
        return _engine_success()

    def wait_container(self, container_id: str, *, timeout_s: int) -> EngineResult:
        container = self.containers[container_id]
        execution = container.get("execution")
        if execution is None:
            execution = self.start_attach(
                container_id,
                timeout_s=timeout_s,
                max_output_bytes=1024 * 1024,
            )
            container["execution"] = execution
        state = container["payload"]["State"]
        if execution.timed_out and state.get("Status") == "running":
            return EngineResult(
                argv=["docker", "wait", container_id],
                exit_code=-9,
                stdout="",
                stderr="",
                duration_s=0.01,
                timed_out=True,
            )
        return EngineResult(
            argv=["docker", "wait", container_id],
            exit_code=0,
            stdout=f"{state['ExitCode']}\n",
            stderr="",
            duration_s=0.01,
        )

    def logs_container(self, container_id: str, *, max_output_bytes: int) -> EngineResult:
        execution = self.containers[container_id]["execution"]
        stdout_bytes = execution.stdout.encode()
        stderr_bytes = execution.stderr.encode()
        truncated = (
            execution.output_truncated
            or len(stdout_bytes) > max_output_bytes
            or len(stderr_bytes) > max_output_bytes
        )
        return EngineResult(
            argv=["docker", "logs", container_id],
            exit_code=0,
            stdout=stdout_bytes[:max_output_bytes].decode(),
            stderr=stderr_bytes[:max_output_bytes].decode(),
            duration_s=0.01,
            output_truncated=truncated,
        )

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
        if command[:2] == ["sh", "-c"] and "__VERIGYM_IMAGE_PROBE_V1__" in command[2]:
            marker = "__VERIGYM_IMAGE_PROBE_V1__"
            if "rg_sha256" in command[2]:
                stdout = (
                    f"{marker}:uid\n10001\n"
                    f"{marker}:gid\n10001\n"
                    f"{marker}:rg_version\nripgrep 15.2.0 (rev e89fff89ac)\n"
                    f"{marker}:rg_sha256\n{CODEX_SHA256}  ../usr/local/bin/rg\n"
                    f"{marker}:keepalive\ntail\n"
                )
            elif "binary_sha256" in command[2]:
                stderr = "WARNING: proceeding, even though PATH aliases could not be created\n"
                stdout = (
                    f"{marker}:uid\n10001\n"
                    f"{marker}:gid\n10001\n"
                    f"{marker}:version\ncodex-cli 0.144.6\n"
                    f"{marker}:binary_sha256\n"
                    f"{CODEX_SHA256}  ../usr/local/bin/codex\n"
                )
                if command[6] == "1":
                    stdout += (
                        f"{marker}:iverilog\n"
                        "Icarus Verilog version 12.0 (stable) (v12_0)\n"
                        f"{marker}:vvp\n"
                        "Icarus Verilog runtime version 12.0 (stable) (v12_0)\n"
                        f"{marker}:launcher_sha256\n"
                        f"{LAUNCHER_SHA256}  ../usr/local/bin/verigym-public-test\n"
                    )
            else:
                stdout = (
                    f"{marker}:uid\n10001\n"
                    f"{marker}:gid\n10001\n"
                    f"{marker}:iverilog\n"
                    "Icarus Verilog version 12.0 (stable) (v12_0)\n"
                    f"{marker}:vvp\n"
                    "Icarus Verilog runtime version 12.0 (stable) (v12_0)\n"
                )
            state.update({"Status": "exited", "ExitCode": 0})
        elif command and command[0] in self.missing_commands:
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
        elif command == ["codex", "--version"]:
            stdout = "codex-cli 0.144.6\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["sha256sum", "../usr/local/bin/codex"]:
            stdout = f"{CODEX_SHA256}  ../usr/local/bin/codex\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command == ["sha256sum", "../usr/local/bin/verigym-public-test"]:
            stdout = f"{LAUNCHER_SHA256}  ../usr/local/bin/verigym-public-test\n"
            state.update({"Status": "exited", "ExitCode": 0})
        elif command[:2] == ["/usr/local/bin/verigym-public-test", "run"]:
            if self.oom_public_tests:
                exit_code = 137
                state.update({"Status": "exited", "OOMKilled": True, "ExitCode": 137})
            else:
                stdout = json.dumps(
                    {
                        "schema_version": "1.0",
                        "protocol": "verigym_public_test_v1",
                        "test_id": command[2],
                        "passed": True,
                        "category": "passed",
                    }
                )
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
        assert agent.external_process_backend == "runtime_external_process_unavailable"
        assert agent.external_agent_command_backend == "runtime_external_command_unavailable"
        assert agent.logical_workspace_root == "/workspace"
        assert (
            runtime.environment_summary()["external_agent_execution_backend"]
            == "runtime_external_process_unavailable"
        )
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


def test_repository_public_test_uses_separate_read_only_mount_and_agent_image(
    tmp_path: Path,
) -> None:
    engine = RecordingDockerEngine()
    engine.image_labels = {
        "org.verigym.runtime.role": "repository-agent",
        "org.verigym.codex.version": "0.144.6",
        "org.verigym.codex.binary.sha256": CODEX_SHA256,
        "org.verigym.public_test_launcher.sha256": LAUNCHER_SHA256,
        "org.verigym.credential_material": "absent",
    }
    runtime = _prepared_runtime(
        engine,
        external_agent=DockerExternalAgentRuntimeConfig(
            image="example:repository-agent",
            expected_image_id=AGENT_IMAGE_ID,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256=CODEX_SHA256,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels=engine.image_labels,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
            max_process_time_s=300,
            max_output_bytes=1024 * 1024,
        ),
    )
    source = tmp_path / "source"
    source.mkdir()
    (source / "TASK.md").write_text("visible\n", encoding="utf-8")
    public = tmp_path / "public"
    public.mkdir()
    (public / "test-contract.json").write_text("{}\n", encoding="utf-8")
    session = runtime.create_session(
        SessionSpec(
            source_dir=str(source),
            label="agent",
            read_only_mounts=[
                SessionReadOnlyMount(
                    source_dir=str(public),
                    destination="/verigym-public",
                    content_hash=hash_directory(public),
                    label="public_tests",
                )
            ],
        )
    )
    try:
        assert session.external_read_only_mounts[0].destination == "/verigym-public"
        result = session.execute_public_test("counter-wrap-public")
        assert result.exit_code == 0
        assert result.metadata["public_assets_read_only"] is True
        arguments = engine.create_arguments[-1]
        mount_values = _all_option_values(arguments, "--mount")
        assert any(
            "dst=/verigym-public" in value and value.endswith(",readonly") for value in mount_values
        )
        assert any("dst=/workspace" in value and "readonly" not in value for value in mount_values)
        assert _option_value(arguments, "--network") == "none"
        assert "--read-only" in arguments
        assert _option_value(arguments, "--cap-drop") == "ALL"
        assert _option_value(arguments, "--security-opt") == "no-new-privileges:true"
        engine.oom_public_tests = True
        oom = session.execute_public_test("counter-wrap-public")
        assert oom.oom_killed
        assert oom.failure_reason == "out_of_memory"
        assert oom.failure_origin == "candidate_process"
    finally:
        session.close()
        runtime.close()
    assert engine.list_managed_containers() == []
    assert runtime.descriptor.cleanup is not None
    assert runtime.descriptor.cleanup.complete


def test_fresh_image_identity_uses_one_combined_container_per_role() -> None:
    docker_runtime_module._IMAGE_OBSERVATION_CACHE.clear()
    engine = RecordingDockerEngine()
    engine.image_labels = {
        "org.verigym.runtime.role": "repository-agent",
        "org.verigym.codex.version": "0.144.6",
        "org.verigym.codex.binary.sha256": CODEX_SHA256,
        "org.verigym.public_test_launcher.sha256": LAUNCHER_SHA256,
    }
    runtime = _prepared_runtime(
        engine,
        external_agent=DockerExternalAgentRuntimeConfig(
            image="example:repository-agent",
            expected_image_id=AGENT_IMAGE_ID,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256=CODEX_SHA256,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels=engine.image_labels,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
        ),
    )
    try:
        assert len(engine.create_arguments) == 2
        verifier_command = engine.create_arguments[0][
            engine.create_arguments[0].index(IMAGE_ID) + 1 :
        ]
        agent_command = engine.create_arguments[1][
            engine.create_arguments[1].index(AGENT_IMAGE_ID) + 1 :
        ]
        assert verifier_command[:2] == ["sh", "-c"]
        assert agent_command[:2] == ["sh", "-c"]
        assert "__VERIGYM_IMAGE_PROBE_V1__" in verifier_command[2]
        assert "__VERIGYM_IMAGE_PROBE_V1__" in agent_command[2]
    finally:
        runtime.close()
        docker_runtime_module._IMAGE_OBSERVATION_CACHE.clear()


def test_external_agent_shell_uses_credential_free_networkless_command_image(
    tmp_path: Path,
) -> None:
    engine = RecordingDockerEngine()
    engine.image_labels = {
        "org.verigym.runtime.role": "repository-agent",
        "org.verigym.codex.version": "0.144.6",
        "org.verigym.codex.binary.sha256": CODEX_SHA256,
        "org.verigym.public_test_launcher.sha256": LAUNCHER_SHA256,
    }
    runtime = _prepared_runtime(
        engine,
        external_agent=DockerExternalAgentRuntimeConfig(
            image="example:repository-agent",
            expected_image_id=AGENT_IMAGE_ID,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256=CODEX_SHA256,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="deepseek_harness_hwe_command_image_v1",
            required_image_labels=engine.image_labels,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
            max_process_time_s=300,
            max_output_bytes=1024 * 1024,
        ),
    )
    source = tmp_path / "source"
    source.mkdir()
    (source / "rtl").mkdir()
    session = runtime.create_session(SessionSpec(source_dir=str(source), label="agent"))
    try:
        result = session.execute_external_agent_command(
            CommandSpec(argv=["/bin/bash", "-lc", "pwd"], cwd="rtl", timeout_s=5)
        )
        assert result.exit_code == 0
        assert result.metadata["credential_environment_names"] == []
        assert result.metadata["network_mode"] == "none"
        arguments = engine.create_arguments[-1]
        image_index = arguments.index(AGENT_IMAGE_ID)
        assert arguments[image_index + 1 :] == ["/bin/bash", "-lc", "pwd"]
        assert _option_value(arguments, "--network") == "none"
        environment = _all_option_values(arguments[:image_index], "--env")
        assert not any("KEY" in value or "TOKEN" in value for value in environment)
        assert _option_value(arguments, "--workdir") == "/workspace/repository/rtl"
        with pytest.raises(ValueError, match="exact /bin/bash"):
            session.execute_external_agent_command(CommandSpec(argv=["true"]))
    finally:
        session.close()
        runtime.close()


def test_codex_free_command_role_prepares_and_executes_without_external_process(
    tmp_path: Path,
) -> None:
    engine = RecordingDockerEngine()
    engine.image_labels = {
        "org.verigym.runtime.role": "hwe-cva6-command",
        "org.verigym.command.rg.sha256": CODEX_SHA256,
        "org.verigym.codex.present": "absent",
    }
    runtime = _prepared_runtime(
        engine,
        command_image=DockerCommandImageRuntimeConfig(
            image="example:command",
            expected_image_id=AGENT_IMAGE_ID,
            expected_rg_version="ripgrep 15.2.0 (rev e89fff89ac)",
            expected_rg_sha256=CODEX_SHA256,
            protocol="hwe_command_image_v1",
            execution_backend="ephemeral_container_v1",
            required_image_labels=engine.image_labels,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
            max_command_time_s=300,
            max_output_bytes=1024 * 1024,
        ),
    )
    source = tmp_path / "source"
    source.mkdir()
    session = runtime.create_session(SessionSpec(source_dir=str(source), label="agent"))
    try:
        assert session.external_process_backend == "runtime_external_process_unavailable"
        assert session.external_agent_command_backend == "ephemeral_container_v1"
        result = session.execute_external_agent_command(
            CommandSpec(argv=["/bin/bash", "-lc", "pwd"], timeout_s=5)
        )
        assert result.exit_code == 0
        assert result.metadata["command_image_protocol"] == "hwe_command_image_v1"
        assert result.metadata["command_execution_backend"] == "ephemeral_container_v1"
        summary = runtime.environment_summary()
        assert summary["external_agent_execution_backend"] == (
            "runtime_external_process_unavailable"
        )
        assert summary["external_agent_command_execution_backend"] == ("ephemeral_container_v1")
        assert summary["docker_role_images"]["external_agent"] is None
        assert summary["docker_role_images"]["command"]["resolved_image_id"] == AGENT_IMAGE_ID
        arguments = engine.create_arguments[-1]
        image_index = arguments.index(AGENT_IMAGE_ID)
        environment = _all_option_values(arguments[:image_index], "--env")
        assert not any(value.startswith("CODEX_HOME=") for value in environment)
    finally:
        session.close()
        runtime.close()


def test_episode_command_role_exposes_external_agent_command_backend(tmp_path: Path) -> None:
    engine = RecordingDockerEngine()
    engine.image_labels = {
        "org.verigym.runtime.role": "hwe-cva6-command",
        "org.verigym.command.rg.sha256": CODEX_SHA256,
        "org.verigym.codex.present": "absent",
    }
    runtime = _prepared_runtime(
        engine,
        command_image=DockerCommandImageRuntimeConfig(
            image="example:command",
            expected_image_id=AGENT_IMAGE_ID,
            expected_rg_version="ripgrep 15.2.0 (rev e89fff89ac)",
            expected_rg_sha256=CODEX_SHA256,
            protocol="hwe_command_image_v1",
            execution_backend="episode_container_exec_v1",
            required_image_labels=engine.image_labels,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
            max_command_time_s=300,
            max_output_bytes=1024 * 1024,
        ),
    )
    source = tmp_path / "source"
    source.mkdir()
    session = runtime.create_session(SessionSpec(source_dir=str(source), label="agent"))
    try:
        assert session.external_process_backend == "runtime_external_process_unavailable"
        assert session.external_agent_command_backend == "episode_container_exec_v1"
        assert runtime.environment_summary()["external_agent_command_execution_backend"] == (
            "episode_container_exec_v1"
        )
    finally:
        session.close()
        runtime.close()


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


def test_runtime_template_creates_fresh_engines_for_an_explicit_docker_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[object, str | None]] = []

    class ExplicitEngine:
        def __init__(self, *, docker_host: str | None = None) -> None:
            created.append((self, docker_host))

    monkeypatch.setattr(
        "verigym.runtimes.docker.runtime.DockerCliEngine",
        ExplicitEngine,
    )
    docker_host = "unix:///data2/jiadongzhu/docker/campaign/socket/docker.sock"
    template = DockerRuntime(docker_host=docker_host)
    first = template.configure(DockerRuntimeConfig(image=IMAGE_ID, pull_policy="never"))
    second = template.configure(DockerRuntimeConfig(image=IMAGE_ID, pull_policy="never"))

    assert first._get_engine() is not second._get_engine()  # noqa: SLF001
    assert [item[1] for item in created] == [docker_host, docker_host]


def test_runtime_rejects_an_engine_and_docker_host_together() -> None:
    with pytest.raises(ConfigurationError, match="either engine or docker_host"):
        DockerRuntime(engine=RecordingDockerEngine(), docker_host="unix:///unused/docker.sock")


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
