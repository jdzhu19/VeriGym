from __future__ import annotations

from pathlib import Path

import pytest
from verigym_deepseek_harness.agent import (
    DeepSeekHarnessHweAgentV3Adapter,
    DeepSeekHarnessHweAgentV4Adapter,
)

from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.runtimes.base import RuntimeSession
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
