from __future__ import annotations

from pathlib import Path

import pytest
from verigym_deepseek_harness.agent import (
    DeepSeekHarnessHweAgentV3Adapter,
    DeepSeekHarnessHweAgentV4Adapter,
)

from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.trace import TraceWriter, read_trace
from verigym.core.workspace import WorkspacePolicy
from verigym.runtimes.base import RuntimeSession
from verigym.schemas.external_agent import ExternalAgentCallIdentity
from verigym.schemas.runtime import WorkspaceDiff
from verigym.schemas.tool import CommandSpec, CompletedCommand


class _FixedSurfaceSession(RuntimeSession):
    def __init__(self, root: Path, *, command_backend: str) -> None:
        self._root = root
        self._command_backend = command_backend

    @property
    def root(self) -> Path:
        return self._root

    @property
    def external_process_backend(self) -> str:
        return "runtime_external_process_unavailable"

    @property
    def external_agent_command_backend(self) -> str:
        return self._command_backend

    def execute(self, command: CommandSpec) -> CompletedCommand:
        del command
        raise AssertionError("execution is not part of this startup regression")

    def read_file(self, path: str) -> bytes:
        del path
        raise AssertionError("file access is not part of this startup regression")

    def write_file(self, path: str, data: bytes) -> None:
        del path, data
        raise AssertionError("file access is not part of this startup regression")

    def snapshot_diff(self) -> WorkspaceDiff:
        raise AssertionError("diff capture is not part of this startup regression")

    def close(self) -> None:
        return None


def _bridge(tmp_path: Path, *, command_backend: str) -> RuntimeExternalAgentBridge:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return RuntimeExternalAgentBridge(
        session=_FixedSurfaceSession(workspace, command_backend=command_backend),
        artifact_root=tmp_path / f"artifacts-{command_backend}",
        isolation_level="docker_standard",
        policy=WorkspacePolicy(editable_globs=("repository/**",), readonly_globs=("TASK.md",)),
        trace=TraceWriter(tmp_path / f"trace-{command_backend}.jsonl", "test-run"),
    )


def test_v4_accepts_host_control_with_episode_command_image(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, command_backend="episode_container_exec_v1")

    DeepSeekHarnessHweAgentV4Adapter()._validate_execution_surface(bridge)


def test_v4_rejects_a_command_backend_drift(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, command_backend="runtime_external_command_unavailable")

    with pytest.raises(ValueError, match="host Harness control plane"):
        DeepSeekHarnessHweAgentV4Adapter()._validate_execution_surface(bridge)


def test_v3_keeps_the_frozen_outer_runtime_requirement(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, command_backend="episode_container_exec_v1")

    with pytest.raises(ValueError, match="Docker outer runtime"):
        DeepSeekHarnessHweAgentV3Adapter()._validate_execution_surface(bridge)


def test_v4_external_agent_identity_is_schema_valid() -> None:
    identity = ExternalAgentCallIdentity(
        adapter_name="deepseek-harness-hwe-agent-v4",
        adapter_version="0.5.0",
        harness_name="deepseek-harness-python-sdk-source-controller",
        requested_model_id="deepseek-v4-flash",
        observed_model_id="deepseek-v4-flash",
        requested_reasoning_effort="off",
        effective_reasoning_effort="off",
        reasoning_effort_source="verigym_explicit_harness_override",
        inherited_reasoning_effort_allowed=False,
        executable_name="dsh-jsonrpc-agent-source",
        executable_sha256="1" * 64,
        executable_version="0.1.1-rc.2",
        capability_fingerprint="2" * 64,
        configuration_fingerprint="3" * 64,
        invocation_count=1,
        integration_track="deepseek_harness_hwe_native_shell_v4",
        identity_confidence="observed",
        reproducibility_scope="site_specific_cli",
    )
    assert identity.integration_track == "deepseek_harness_hwe_native_shell_v4"


def test_public_provider_marker_has_core_bounding_field(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, command_backend="episode_container_exec_v1")
    bridge.emit_event(
        "deepseek_harness_provider_request_started",
        {
            "provider_request_started": True,
            "provider_request_count_lower_bound": 1,
            "credential_values_persisted": False,
        },
    )
    events = read_trace(tmp_path / "trace-episode_container_exec_v1.jsonl")
    assert events[-1].payload == {
        "provider_request_started": True,
        "provider_request_count_lower_bound": 1,
        "credential_values_persisted": False,
        "content_truncated": False,
    }
