from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from verigym_deepseek_harness.broker import (
    DeepSeekHarnessHweBroker,
    openhands_v23_progress_gate_state,
)

from verigym.schemas.common import ErrorCategory
from verigym.schemas.tool import CommandSpec, CompletedCommand, ToolResult


class _Bridge:
    def __init__(self, workspace: Path, *, mutate_on_shell: bool = False) -> None:
        self.workspace_root = workspace
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.editable_globs = ("*.sv",)
        self._mutate_on_shell = mutate_on_shell

    def invoke_workspace_tool(self, name: str, request: dict[str, Any]) -> ToolResult:
        self.calls.append((name, request))
        return ToolResult(
            tool=name,
            success=True,
            category=ErrorCategory.SUCCESS,
            stdout="No candidate diff.\n",
        )

    def execute_external_agent_command(self, command: CommandSpec) -> CompletedCommand:
        self.calls.append(("shell", command.model_dump(mode="json")))
        if self._mutate_on_shell:
            (self.workspace_root / "a.sv").write_text(
                "module changed; endmodule\n", encoding="utf-8"
            )
        return CompletedCommand(
            argv=command.argv,
            cwd=command.cwd,
            exit_code=0,
            stdout="ok\n",
        )


def _broker(
    tmp_path: Path,
    *,
    v23: bool = False,
    mutate_on_shell: bool = False,
) -> tuple[DeepSeekHarnessHweBroker, _Bridge]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    bridge = _Bridge(workspace, mutate_on_shell=mutate_on_shell)
    broker = DeepSeekHarnessHweBroker(
        bridge=bridge,  # type: ignore[arg-type]
        socket_path=tmp_path / "control" / "broker.sock",
        private_audit_root=tmp_path / "audit",
        openhands_v23_controls=v23,
    )
    return broker, bridge


def test_broker_accepts_one_typed_finish_and_closes_the_episode(tmp_path: Path) -> None:
    broker, bridge = _broker(tmp_path)
    try:
        response = broker._dispatch(  # noqa: SLF001
            {"id": "call-1", "name": "finish", "arguments": {"summary": "done"}}
        )
        assert response["ok"] is True
        assert response["workspace_epoch_before"] == response["workspace_epoch_after"] == 0
        assert bridge.calls == [("file.diff", {})]
        assert broker.events()[0].action == "finish"
        assert broker.call_ids() == ("call-1",)
        assert broker.stats().finished is True
        terminal = broker._dispatch(  # noqa: SLF001
            {"operation": "verigym_hwe_terminal_status_v1"}
        )
        assert terminal == {
            "ok": True,
            "finished": True,
            "policy_failed": False,
            "infrastructure_failed": False,
        }
        assert broker.stats().tool_calls == 1
        rejected = broker._dispatch(  # noqa: SLF001
            {"id": "call-2", "name": "inspect_diff", "arguments": {}}
        )
        assert rejected["error"] == "episode_finished"
    finally:
        broker.stop()
    assert broker.stats().raw_audit_manifest["records"] == 1  # type: ignore[index]


def test_broker_rejects_foreign_tools_and_escaping_paths_without_execution(
    tmp_path: Path,
) -> None:
    broker, bridge = _broker(tmp_path)
    try:
        foreign = broker._dispatch(  # noqa: SLF001
            {"id": "call-1", "name": "bash", "arguments": {"command": "true"}}
        )
        escaping = broker._dispatch(  # noqa: SLF001
            {"id": "call-2", "name": "read_file", "arguments": {"path": "../secret"}}
        )
        assert foreign["error"] == "invalid_request"
        assert escaping["error"] == "invalid_arguments"
        assert bridge.calls == []
        assert broker.events() == ()
        assert broker.stats().rejection_codes == ("invalid_request", "invalid_arguments")
    finally:
        broker.stop()


def test_broker_rejects_raw_host_paths_before_any_side_effect(tmp_path: Path) -> None:
    broker, bridge = _broker(tmp_path)
    try:
        read = broker._dispatch(  # noqa: SLF001
            {
                "id": "call-1",
                "name": "read_file",
                "arguments": {"path": "/data/private/repository/a.sv"},
            }
        )
        shell = broker._dispatch(  # noqa: SLF001
            {
                "id": "call-2",
                "name": "shell",
                "arguments": {"command": "sed -n '1,2p' /home/user/a.sv"},
            }
        )
        bare_root = broker._dispatch(  # noqa: SLF001
            {
                "id": "call-bare-root",
                "name": "shell",
                "arguments": {"command": "ls /hpc"},
            }
        )
        relative_data = broker._dispatch(  # noqa: SLF001
            {
                "id": "call-relative-data",
                "name": "read_file",
                "arguments": {"path": "docs/data/example.txt"},
            }
        )
        ephemeral = broker._dispatch(  # noqa: SLF001
            {
                "id": "call-3",
                "name": "shell",
                "arguments": {"command": "mkdir -p /tmp/verigym-test"},
            }
        )
        assert read == {
            "ok": False,
            "error": "raw_host_path",
            "text": "tool arguments must use workspace-relative paths",
        }
        assert shell == read
        assert bare_root == read
        assert relative_data["ok"] is True
        assert ephemeral["ok"] is True
        assert [name for name, _request in bridge.calls] == ["file.read", "shell"]
        assert broker.stats().rejection_codes == (
            "raw_host_path",
            "raw_host_path",
            "raw_host_path",
        )
    finally:
        broker.stop()


def test_v23_injects_checkpoint_at_16_and_terminates_no_progress_at_32(
    tmp_path: Path,
) -> None:
    broker, bridge = _broker(tmp_path, v23=True)
    try:
        responses = [
            broker._dispatch(  # noqa: SLF001
                {"id": f"call-{index}", "name": "list_files", "arguments": {}}
            )
            for index in range(1, 33)
        ]

        assert all(response["ok"] is True for response in responses)
        assert "progress checkpoint" in responses[15]["text"].casefold()
        receipt = broker.openhands_v23_progress_receipt()
        assert receipt["progress_checkpoint_action"] == 16
        assert receipt["progress_checkpoint_injected"] is True
        assert receipt["no_progress_action"] == 32
        assert receipt["no_progress_terminated"] is True
        assert receipt["progress_gate_state"] == "terminated_no_progress"
        assert broker.stats().policy_failure == "no_progress"
        assert len(bridge.calls) == 32
        rejected = broker._dispatch(  # noqa: SLF001
            {"id": "call-33", "name": "list_files", "arguments": {}}
        )
        assert rejected["error"] == "no_progress"
        assert len(bridge.calls) == 32
    finally:
        broker.stop()


def test_v23_first_effective_modification_permanently_releases_action_32_gate(
    tmp_path: Path,
) -> None:
    broker, _bridge = _broker(tmp_path, v23=True, mutate_on_shell=True)
    try:
        modified = broker._dispatch(  # noqa: SLF001
            {"id": "call-1", "name": "shell", "arguments": {"command": "apply fix"}}
        )
        for index in range(2, 33):
            response = broker._dispatch(  # noqa: SLF001
                {"id": f"call-{index}", "name": "list_files", "arguments": {}}
            )
            assert response["ok"] is True

        assert modified["ok"] is True
        receipt = broker.openhands_v23_progress_receipt()
        assert receipt["first_effective_modification_action"] == 1
        assert receipt["progress_checkpoint_injected"] is False
        assert receipt["no_progress_terminated"] is False
        assert receipt["progress_gate_state"] == "released_after_modification"
        assert broker.stats().policy_failure is None
    finally:
        broker.stop()


@pytest.mark.parametrize(
    ("action_count", "first_modification"),
    [(33, None), (33, 33), (20, 21), (0, 0)],
)
def test_v23_progress_projection_rejects_impossible_sequences(
    action_count: int,
    first_modification: int | None,
) -> None:
    with pytest.raises(ValueError, match="OpenHands v23"):
        openhands_v23_progress_gate_state(
            action_count=action_count,
            first_effective_modification_action=first_modification,
        )
