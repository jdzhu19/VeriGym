from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from verigym.runtimes.docker.control_plane_environment import (
    build_trusted_host_app_server_environment,
)
from verigym.runtimes.docker.engine import DockerCliEngine, EngineResult
from verigym.runtimes.docker.errors import DockerContainerError
from verigym.runtimes.docker.external_process import (
    _APP_SERVER_CONFIG_OVERRIDES,
    DockerExternalProcessExecutor,
    _hwe_request_profile_id,
    _is_logical_workspace_uri,
    _run_app_server,
    _sanitize_and_bound,
)
from verigym.schemas.common import RuntimeImageIdentity
from verigym.schemas.external_agent import ExternalProcessRequest
from verigym.schemas.runtime import DockerExternalAgentRuntimeConfig

VERIFIER_IMAGE_ID = "sha256:" + "a" * 64
AGENT_IMAGE_ID = "sha256:" + "b" * 64
CONTAINER_ID = "c" * 64
CODEX_BINARY_SHA256 = "d" * 64


class ExternalProcessEngine:
    backend_type = "fake_docker"

    def __init__(self) -> None:
        self.arguments: list[str] = []
        self.payload: dict[str, Any] | None = None
        self.removed = False
        self.killed = False

    def create_container(self, arguments: list[str]) -> str:
        self.arguments = list(arguments)
        image_index = arguments.index(AGENT_IMAGE_ID)
        control = arguments[:image_index]
        environment = _key_values(control, "--env")
        labels = _key_values(control, "--label")
        mounts = [
            dict(part.split("=", 1) for part in value.split(","))
            for value in _values(control, "--mount")
        ]
        tmpfs = _value(control, "--tmpfs")
        self.payload = {
            "HostConfig": {
                "NetworkMode": _value(control, "--network"),
                "ReadonlyRootfs": "--read-only" in control,
                "Privileged": False,
                "CapDrop": [_value(control, "--cap-drop")],
                "CapAdd": None,
                "SecurityOpt": [_value(control, "--security-opt")],
                "Init": "--init" in control,
                "PidMode": "",
                "IpcMode": _value(control, "--ipc"),
                "UsernsMode": "",
                "Devices": None,
                "Binds": None,
                "Memory": int(_value(control, "--memory")),
                "MemorySwap": int(_value(control, "--memory-swap")),
                "NanoCpus": round(float(_value(control, "--cpus")) * 1_000_000_000),
                "PidsLimit": int(_value(control, "--pids-limit")),
                "Tmpfs": {"/tmp": tmpfs.split(":", 1)[1]},
                "Mounts": [
                    {
                        "Type": item["type"],
                        "Source": item["src"],
                        "Target": item["dst"],
                    }
                    for item in mounts
                ],
            },
            "Config": {
                "User": _value(control, "--user"),
                "StopTimeout": int(_value(control, "--stop-timeout")),
                "Env": [f"{name}={value}" for name, value in environment.items()],
                "Labels": labels,
            },
            "State": {
                "Running": True,
                "Status": "running",
                "OOMKilled": False,
                "ExitCode": 0,
            },
        }
        return CONTAINER_ID

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        assert container_id == CONTAINER_ID
        assert self.payload is not None
        return self.payload

    def start_attach_streaming(self, container_id: str) -> subprocess.Popen[bytes]:
        assert container_id == CONTAINER_ID
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

    def kill_container(self, container_id: str) -> EngineResult:
        assert container_id == CONTAINER_ID
        assert self.payload is not None
        self.killed = True
        self.payload["State"].update({"Running": False, "Status": "exited", "ExitCode": 137})
        return _success()

    def remove_container(self, container_id: str, *, force: bool = True) -> EngineResult:
        assert container_id == CONTAINER_ID
        assert force
        self.removed = True
        return _success()

    def list_managed_containers(self) -> list[str]:
        return [] if self.removed else [CONTAINER_ID[:12]]

    def version(self) -> dict[str, Any]:  # pragma: no cover - protocol-only method
        raise AssertionError

    def info(self) -> dict[str, Any]:  # pragma: no cover - protocol-only method
        raise AssertionError

    def inspect_image(self, reference: str) -> dict[str, Any] | None:  # pragma: no cover
        raise AssertionError(reference)

    def pull_image(self, reference: str) -> None:  # pragma: no cover
        raise AssertionError(reference)

    def start_container(self, container_id: str) -> EngineResult:  # pragma: no cover
        raise AssertionError(container_id)

    def wait_container(
        self, container_id: str, *, timeout_s: int
    ) -> EngineResult:  # pragma: no cover
        raise AssertionError((container_id, timeout_s))

    def container_logs(
        self, container_id: str, *, max_output_bytes: int
    ) -> EngineResult:  # pragma: no cover
        raise AssertionError((container_id, max_output_bytes))

    def list_managed_volumes(self) -> list[str]:  # pragma: no cover
        raise AssertionError

    def close(self) -> None:
        return None


def _success() -> EngineResult:
    return EngineResult(
        argv=["docker"],
        exit_code=0,
        stdout="",
        stderr="",
        duration_s=0.01,
    )


def test_container_cleanup_controls_tolerate_bounded_daemon_queueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = DockerCliEngine(executable="/usr/bin/docker")
    observed: list[tuple[list[str], int]] = []

    def invoke(
        arguments: list[str],
        *,
        timeout_s: int,
        max_output_bytes: int = 1024 * 1024,
    ) -> EngineResult:
        del max_output_bytes
        observed.append((arguments, timeout_s))
        stdout = (
            '[{"State":{"Running":false}}]'
            if arguments[0] == "inspect"
            else CONTAINER_ID
            if arguments[0] == "create"
            else ""
        )
        return EngineResult(
            argv=["docker", *arguments],
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_s=0.01,
        )

    monkeypatch.setattr(engine, "_invoke", invoke)
    assert engine.create_container(["image-id", "true"]) == CONTAINER_ID
    engine.inspect_container(CONTAINER_ID)
    engine.kill_container(CONTAINER_ID)
    engine.remove_container(CONTAINER_ID)
    assert engine.list_managed_containers() == []

    assert [timeout for _, timeout in observed] == [60, 60, 60, 60, 60]


def _value(arguments: list[str], name: str) -> str:
    return arguments[arguments.index(name) + 1]


def _values(arguments: list[str], name: str) -> list[str]:
    return [arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == name]


def _key_values(arguments: list[str], name: str) -> dict[str, str]:
    return {
        key: value for item in _values(arguments, name) for key, _, value in [item.partition("=")]
    }


def _agent_config() -> DockerExternalAgentRuntimeConfig:
    return DockerExternalAgentRuntimeConfig(
        image="verigym/codex-exec-server:test",
        expected_image_id=AGENT_IMAGE_ID,
        expected_executable_name="codex",
        expected_executable_path="/usr/local/bin/codex",
        expected_executable_version="codex-cli 0.144.6",
        expected_executable_sha256=CODEX_BINARY_SHA256,
        process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
        protocol="codex_app_server_remote_environment_v1",
        required_image_labels={"org.example.credentials": "absent"},
        run_as_user=f"{os.getuid()}:{os.getgid()}",
        max_process_time_s=30,
        max_output_bytes=1024 * 1024,
    )


def _identity(image_id: str, reference: str) -> RuntimeImageIdentity:
    user = f"{os.getuid()}:{os.getgid()}"
    return RuntimeImageIdentity(
        requested_reference=reference,
        resolved_image_id=image_id,
        os="linux",
        architecture="amd64",
        configured_image_user="10001:10001",
        effective_user=user,
    )


def _request(executable: Path, **updates: object) -> ExternalProcessRequest:
    values: dict[str, object] = {
        "protocol": "codex_app_server_remote_environment_v1",
        "runtime_role": "agent",
        "argv": ["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
        "logical_cwd": "/workspace",
        "stdin_text": "Return one RTL candidate.",
        "stdin_transport": "runtime_protocol_adapter",
        "network_policy": "none",
        "mount_policy": "task_workspace_only",
        "writable_destinations": ["/workspace", "/tmp"],
        "container_environment_names": [],
        "integration_track": "codex_cli_external_agent",
        "workspace_mode": "visible_task_workspace",
        "logical_workspace_root": "/workspace",
        "requested_model_id": "gpt-5.4",
        "requested_reasoning_effort": "xhigh",
        "executable_path": executable,
        "executable_name": executable.name,
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "executable_version": "codex-cli 0.144.6",
        "capability_fingerprint": "e" * 64,
        "requested_auth_mode": "chatgpt_cli_session",
        "resolved_auth_mode": "inherited_codex_login",
        "auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
        "allow_proxy_environment": False,
        "forwarded_proxy_environment_names": [],
        "timeout_s": 30,
        "max_output_bytes": 1024 * 1024,
        "editable_globs": ["rtl/**"],
        "readonly_globs": ["tests/**"],
    }
    values.update(updates)
    return ExternalProcessRequest.model_validate(values)


def test_hwe_v9_prompt_contract_resolves_to_v2_collection_profile() -> None:
    request = SimpleNamespace(
        invocation_spec=SimpleNamespace(prompt_contract_id="codex_cli_hwe_native_shell_context_v9")
    )
    assert _hwe_request_profile_id(request) == "hwe_standard_v2"  # type: ignore[arg-type]


def test_runtime_owns_container_process_and_records_effective_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "codex-control-plane"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    workspace = tmp_path / "visible"
    workspace.mkdir()
    (workspace / "rtl").mkdir()
    (workspace / "rtl" / "TopModule.sv").write_text("module TopModule; endmodule\n")
    engine = ExternalProcessEngine()
    registered: list[str] = []
    removed: list[str] = []

    def fake_app_server(
        request: ExternalProcessRequest,
        *,
        broker_url: str,
        workspace: Path,
        effective_timeout_s: float,
        broker_health_check: Any,
    ) -> dict[str, Any]:
        assert request.requested_model_id == "gpt-5.4"
        assert broker_url.startswith("ws://127.0.0.1:")
        assert workspace == (tmp_path / "visible").resolve()
        assert effective_timeout_s == 30
        assert callable(broker_health_check)
        return {
            "stdout": (
                '{"type":"thread.started","model":"gpt-5.4"}\n'
                f'{{"type":"agent_message","text":"{workspace}"}}\n'
                '{"type":"turn.completed","status":"completed"}\n'
            ),
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "terminal_event_seen": True,
            "process_group_cleaned": True,
            "failure_reason": None,
            "failure_origin": None,
            "user_config_metadata_unchanged": True,
        }

    monkeypatch.setattr(
        "verigym.runtimes.docker.external_process._run_app_server",
        fake_app_server,
    )

    def remove(container_id: str) -> str | None:
        removed.append(container_id)
        result = engine.remove_container(container_id)
        return None if result.exit_code == 0 else "cleanup failed"

    result = DockerExternalProcessExecutor(
        engine=engine,
        verifier_image=_identity(VERIFIER_IMAGE_ID, "verifier:test"),
        agent_image=_identity(AGENT_IMAGE_ID, "agent:test"),
        agent_config=_agent_config(),
        run_id="unit-run",
        session_id="unit-session",
        register_container=registered.append,
        remove_container=remove,
    ).execute(_request(executable), workspace)

    assert registered == [CONTAINER_ID]
    assert removed == [CONTAINER_ID]
    assert engine.killed
    assert engine.arguments[-4:] == [
        "/usr/local/bin/codex",
        "exec-server",
        "--listen",
        "stdio://",
    ]
    assert _value(engine.arguments, "--network") == "none"
    assert _value(engine.arguments, "--ipc") == "none"
    assert _value(engine.arguments, "--user") == f"{os.getuid()}:{os.getgid()}"
    assert "--read-only" in engine.arguments
    assert "--init" in engine.arguments
    assert _value(engine.arguments, "--cap-drop") == "ALL"
    assert _value(engine.arguments, "--security-opt") == "no-new-privileges:true"
    assert _value(engine.arguments, "--memory") == str(512 * 1024 * 1024)
    assert _value(engine.arguments, "--memory-swap") == str(512 * 1024 * 1024)
    assert _value(engine.arguments, "--cpus") == "1"
    assert _value(engine.arguments, "--pids-limit") == "128"
    assert _value(engine.arguments, "--tmpfs") == (
        "/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777"
    )
    assert _values(engine.arguments, "--mount") == [
        f"type=bind,src={workspace.resolve()},dst=/workspace"
    ]
    environment = _key_values(engine.arguments, "--env")
    assert environment["PATH"] == (
        "/tools/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin"
    )
    assert result.exit_code == 0
    assert result.terminal_event_seen
    assert result.cleanup_complete
    assert result.security.effective_controls_verified
    assert result.security.container_exit_inspected
    assert result.security.cleanup_verified
    assert result.security.environment_names == [
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TMPDIR",
    ]
    assert not result.security.credential_environment_names_in_container
    assert not result.security.proxy_environment_names_in_container
    assert result.runtime_identity.agent_image_id == AGENT_IMAGE_ID
    assert result.runtime_identity.verifier_image_id == VERIFIER_IMAGE_ID
    assert result.runtime_identity.agent_executable_sha256 == CODEX_BINARY_SHA256
    assert str(workspace) not in result.stdout
    assert "<task_workspace>" in result.stdout


def test_external_process_request_fails_closed_on_runtime_policy_changes(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    generic_request = _request(executable, argv=["another-agent", "--stdio"])
    assert generic_request.argv == ["another-agent", "--stdio"]
    with pytest.raises(ValidationError, match="credential or proxy"):
        _request(executable, container_environment_names=["OPENAI_API_KEY"])
    with pytest.raises(ValidationError, match="writable destinations"):
        _request(executable, writable_destinations=["/workspace"])


def test_runtime_rejects_request_limits_above_its_own_ceiling(tmp_path: Path) -> None:
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    executor = DockerExternalProcessExecutor(
        engine=ExternalProcessEngine(),
        verifier_image=_identity(VERIFIER_IMAGE_ID, "verifier:test"),
        agent_image=_identity(AGENT_IMAGE_ID, "agent:test"),
        agent_config=_agent_config(),
        run_id="unit-run",
        session_id="unit-session",
        register_container=lambda _container_id: None,
        remove_container=lambda _container_id: None,
    )
    with pytest.raises(ValueError, match="argv differs"):
        executor.execute(_request(executable, argv=["another-agent", "--stdio"]), tmp_path)
    with pytest.raises(ValueError, match="timeout exceeds"):
        executor.execute(_request(executable, timeout_s=31), tmp_path)


def test_external_agent_config_requires_commit_bound_image_and_binary_hash() -> None:
    with pytest.raises(ValidationError, match="expected image ID"):
        DockerExternalAgentRuntimeConfig(
            image="agent:test",
            expected_image_id="agent:test",
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256=CODEX_BINARY_SHA256,
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={"org.example.credentials": "absent"},
            run_as_user=f"{os.getuid()}:{os.getgid()}",
        )
    with pytest.raises(ValidationError, match="executable hash"):
        DockerExternalAgentRuntimeConfig(
            image="agent:test",
            expected_image_id=AGENT_IMAGE_ID,
            expected_executable_name="codex",
            expected_executable_path="/usr/local/bin/codex",
            expected_executable_version="codex-cli 0.144.6",
            expected_executable_sha256="not-a-hash",
            process_argv=["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
            protocol="codex_app_server_remote_environment_v1",
            required_image_labels={"org.example.credentials": "absent"},
            run_as_user=f"{os.getuid()}:{os.getgid()}",
        )


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("file:///workspace", True),
        ("/workspace", False),
        ("file:///workspace/../host", False),
        ("file://host/workspace", False),
        ("file:///workspace?escape=1", False),
        (None, False),
    ],
)
def test_remote_environment_cwd_requires_exact_canonical_workspace_uri(
    value: str | None,
    accepted: bool,
) -> None:
    assert _is_logical_workspace_uri(value) is accepted


def test_host_control_plane_enables_only_the_explicit_system_proxy_path() -> None:
    assert "features.respect_system_proxy=true" in _APP_SERVER_CONFIG_OVERRIDES
    assert "features.network_proxy=false" in _APP_SERVER_CONFIG_OVERRIDES
    assert "features.web_search=false" not in _APP_SERVER_CONFIG_OVERRIDES


def test_app_server_retains_terminal_notification_that_precedes_turn_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "fake-app-server"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    result = {}
    if method == "environment/info":
        result = {"cwd": "file:///workspace", "shell": {"name": "bash", "path": "/bin/bash"}}
    elif method == "thread/start":
        result = {"thread": {"id": "thread-1"}, "model": "gpt-5.4"}
    elif method == "turn/start":
        print(json.dumps({"jsonrpc": "2.0", "method": "turn/completed", "params": {
            "threadId": "thread-1", "turn": {"status": "completed", "error": None}
        }}), flush=True)
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('model = "fake"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    result = _run_app_server(
        _request(executable),
        broker_url="ws://127.0.0.1:1/fake",
        workspace=tmp_path,
        effective_timeout_s=5,
    )
    assert result["exit_code"] == 0
    assert result["terminal_event_seen"] is True
    assert result["timed_out"] is False
    assert result["user_config_metadata_unchanged"] is True
    assert '"type":"turn.completed"' in result["stdout"]


def test_app_server_eof_is_observable_without_waiting_for_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "exits-immediately"
    executable.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    executable.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    started = time.monotonic()
    result = _run_app_server(
        _request(executable),
        broker_url="ws://127.0.0.1:1/fake",
        workspace=tmp_path,
        effective_timeout_s=5,
    )
    assert time.monotonic() - started < 2
    assert result["failure_reason"] == "app_server_protocol_error"
    assert result["failure_origin"] == "host_control_plane"
    assert result["timed_out"] is False
    assert any(marker in result["stdout"] for marker in ("stdout closed", "stdin closed"))


def test_app_server_stops_immediately_when_broker_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "fake-app-server"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" in request:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}), flush=True)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    checks = 0

    def broker_health_check() -> None:
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise DockerContainerError(
                "external-agent stdio broker failed: HweExecProtocolError",
                subreason="hwe_protocol_test_failure",
            )

    started = time.monotonic()
    result = _run_app_server(
        _request(executable),
        broker_url="ws://127.0.0.1:1/fake",
        workspace=tmp_path,
        effective_timeout_s=30,
        broker_health_check=broker_health_check,
    )
    assert time.monotonic() - started < 2
    assert result["failure_reason"] == "hwe_protocol_test_failure"
    assert result["failure_origin"] == "broker"
    assert result["timed_out"] is False


def test_loopback_proxy_attempt_has_stable_host_control_plane_taxonomy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "proxy-error-app-server"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    if request["method"] == "environment/info":
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {
                "message": (
                    "exec-server connection attempt failed: "
                    "Proxy connection failed: HTTP CONNECT failed with status 502"
                )
            },
        }
    else:
        response = {"jsonrpc": "2.0", "id": request["id"], "result": {}}
    print(json.dumps(response), flush=True)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    result = _run_app_server(
        _request(executable),
        broker_url="ws://127.0.0.1:32123/verigym-test",
        workspace=tmp_path,
        effective_timeout_s=5,
    )

    assert result["failure_reason"] == "control_plane_loopback_proxy"
    assert result["failure_origin"] == "host_control_plane"
    assert result["exit_code"] is None
    assert result["terminal_event_seen"] is False


def test_all_proxy_values_are_redacted_from_runtime_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    values = {
        "HTTP_PROXY": "http://proxy-user:proxy-password@proxy.invalid:8080",
        "HTTPS_PROXY": "http://proxy-user:proxy-password@proxy.invalid:8443",
        "NO_PROXY": "private.invalid",
        "http_proxy": "http://ignored-lower.invalid:8080",
        "https_proxy": "http://ignored-lower.invalid:8443",
        "no_proxy": "ignored.lower.invalid",
        "ALL_PROXY": "http://ignored-all.invalid:1080",
        "all_proxy": "http://ignored-all-lower.invalid:1080",
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    environment = build_trusted_host_app_server_environment(
        allow_proxy_environment=True,
        forwarded_proxy_environment_names=("HTTP_PROXY", "HTTPS_PROXY"),
        broker_url="ws://127.0.0.1:32123/verigym-test",
    )
    request = _request(
        executable,
        allow_proxy_environment=True,
        forwarded_proxy_environment_names=["HTTP_PROXY", "HTTPS_PROXY"],
    )
    raw = "\n".join([*values.values(), environment.values["NO_PROXY"]])

    clean, truncated = _sanitize_and_bound(
        raw,
        request=request,
        workspace=tmp_path,
        proxy_values=environment.redaction_values,
    )

    assert not truncated
    assert "<redacted-proxy>" in clean
    assert all(value not in clean for value in values.values())
    assert environment.values["NO_PROXY"] not in clean
