from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
from verigym_codex_cli.capabilities import runtime_capabilities
from verigym_codex_cli.config import (
    agent_settings,
    readonly_agent_settings,
    settings_for_execution_backend,
)
from verigym_codex_cli.runtime_execution import execute_runtime_process

from verigym.schemas.external_agent import (
    ExternalAgentAccounting,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalProcessRuntimeIdentity,
    ExternalProcessSecurityEvidence,
)

pytestmark = [pytest.mark.codex_cli]

IMAGE_A = "sha256:" + "a" * 64
IMAGE_B = "sha256:" + "b" * 64


class RuntimeBridge:
    execution_backend = "docker_outer_runtime_delegated"
    logical_workspace_root = "/workspace"
    editable_globs = ("rtl/**",)
    readonly_globs = ("README.md", "visible/**")

    def __init__(self, root: Path) -> None:
        self.workspace_root = root
        self.artifact_root = root / "artifacts"
        self.isolation_level = "docker_standard"
        self.requests: list[ExternalProcessRequest] = []

    def execute_process(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        self.requests.append(request)
        return ExternalProcessResult(
            exit_code=0,
            stdout=(
                '{"type":"thread.started","model":"fake-model"}\n'
                '{"type":"item.completed","item":{"type":"agent_message",'
                '"text":"module TopModule; endmodule"}}\n'
                '{"type":"turn.completed","status":"completed"}\n'
            ),
            stderr="",
            duration_s=0.25,
            timed_out=False,
            stdout_truncated=False,
            stderr_truncated=False,
            output_limit_hit=False,
            oom_killed=False,
            process_group_cleaned=True,
            cleanup_complete=True,
            terminal_event_seen=True,
            runtime_identity=ExternalProcessRuntimeIdentity(
                execution_owner="verigym_runtime",
                execution_backend="docker_outer_runtime_delegated",
                protocol="codex_app_server_remote_environment_v1",
                verifier_image_id=IMAGE_A,
                agent_image_id=IMAGE_B,
                agent_image_reference="agent:test",
                agent_image_os="linux",
                agent_image_architecture="amd64",
                agent_image_user="10001:10001",
                agent_executable_name="codex",
                agent_executable_sha256="c" * 64,
                agent_executable_version="codex-cli 0.144.6",
                container_id="d" * 64,
                host_executable_name=request.executable_name,
                host_executable_sha256=request.executable_sha256,
                host_executable_version=request.executable_version,
                capability_fingerprint=request.capability_fingerprint,
                configuration_fingerprint="e" * 64,
                logical_workspace_root="/workspace",
            ),
            security=ExternalProcessSecurityEvidence(
                boundary="docker_outer_runtime",
                network_mode="none",
                read_only_rootfs=True,
                non_root=True,
                cap_drop=["ALL"],
                no_new_privileges=True,
                init=True,
                private_pid_namespace=True,
                private_ipc_namespace=True,
                mount_destinations=["/workspace"],
                writable_destinations=["/workspace", "/tmp"],
                environment_names=["CODEX_HOME", "HOME", "LANG", "LC_ALL", "PATH", "TMPDIR"],
                credential_environment_names_in_container=[],
                proxy_environment_names_in_container=[],
                host_home_mounted=False,
                source_repository_mounted=False,
                hidden_verifier_mounted=False,
                docker_socket_mounted=False,
                credential_files_mounted=False,
                api_key_environment_forwarded=False,
                credential_contents_accessed_by_verigym=False,
                user_config_contents_accessed_by_verigym=False,
                user_config_metadata_unchanged=True,
                provider_network_in_container=False,
                broker_transport="loopback_websocket_to_container_stdio",
                broker_listen_scope="127.0.0.1",
                effective_controls_verified=True,
                container_exit_inspected=True,
                cleanup_verified=True,
                container_removed=True,
                broker_stopped=True,
                process_group_cleaned=True,
                workspace_empty_before=(True if request.workspace_mode == "fresh_empty" else None),
                workspace_empty_after=(True if request.workspace_mode == "fresh_empty" else None),
                workspace_changed_paths=[],
                memory_bytes=512 * 1024 * 1024,
                cpus=1.0,
                pids_limit=128,
                tmpfs_bytes=64 * 1024 * 1024,
                output_limit_bytes=request.max_output_bytes,
                effective_timeout_s=request.timeout_s,
            ),
        )

    def emit_event(self, event_type: str, payload: dict[str, object]) -> None:
        del event_type, payload

    def record_accounting(self, accounting: ExternalAgentAccounting) -> None:
        del accounting


@pytest.mark.parametrize(
    ("track", "workspace_mode"),
    [
        ("readonly", "fresh_empty"),
        ("agent", "visible_task_workspace"),
    ],
)
def test_plugin_delegates_model_process_to_runtime_without_launching_fake_codex(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
    track: Literal["readonly", "agent"],
    workspace_mode: Literal["fresh_empty", "visible_task_workspace"],
) -> None:
    _executable_path, log, _scenario = fake_codex
    executable, capabilities = runtime_capabilities()
    options: dict[str, object] = {
        "model_id": "fake-model",
        "sandbox": "read-only" if track == "readonly" else "workspace-write",
        "approval_policy": "never",
        "reasoning_effort": "xhigh",
        "max_process_time_s": 300,
    }
    settings = (
        readonly_agent_settings(options, capabilities, task_wall_time_s=300)
        if track == "readonly"
        else agent_settings(options, capabilities, task_wall_time_s=300)
    )
    settings = settings_for_execution_backend(
        settings,
        "docker_outer_runtime_delegated",
    )
    bridge = RuntimeBridge(tmp_path)
    outcome = execute_runtime_process(
        bridge=bridge,
        executable=executable,
        capabilities=capabilities,
        settings=settings,
        prompt="Return one RTL candidate.",
        workspace_mode=workspace_mode,
    )

    assert outcome.process.arguments == ("<runtime-owned-codex-app-server>",)
    assert outcome.process.exit_code == 0
    assert len(bridge.requests) == 1
    request = bridge.requests[0]
    assert request.argv == [
        "/usr/local/bin/codex",
        "exec-server",
        "--listen",
        "stdio://",
    ]
    assert request.logical_cwd == "/workspace"
    assert request.stdin_text == "Return one RTL candidate."
    assert request.network_policy == "none"
    assert request.mount_policy == "task_workspace_only"
    assert request.requested_model_id == "fake-model"
    assert request.requested_reasoning_effort == "xhigh"
    assert request.timeout_s == 300
    assert request.container_environment_names == []
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert records
    assert all(record["kind"] == "diagnostic" for record in records)
