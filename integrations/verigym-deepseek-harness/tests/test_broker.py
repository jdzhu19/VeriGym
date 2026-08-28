from __future__ import annotations

from pathlib import Path
from typing import Any

from verigym_deepseek_harness.broker import DeepSeekHarnessHweBroker

from verigym.schemas.common import ErrorCategory
from verigym.schemas.tool import CommandSpec, CompletedCommand, ToolResult


class _Bridge:
    def __init__(self, workspace: Path) -> None:
        self.workspace_root = workspace
        self.calls: list[tuple[str, dict[str, Any]]] = []

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
        return CompletedCommand(
            argv=command.argv,
            cwd=command.cwd,
            exit_code=0,
            stdout="ok\n",
        )


def _broker(tmp_path: Path) -> tuple[DeepSeekHarnessHweBroker, _Bridge]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    bridge = _Bridge(workspace)
    broker = DeepSeekHarnessHweBroker(
        bridge=bridge,  # type: ignore[arg-type]
        socket_path=tmp_path / "control" / "broker.sock",
        private_audit_root=tmp_path / "audit",
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
        assert ephemeral["ok"] is True
        assert [name for name, _request in bridge.calls] == ["shell"]
        assert broker.stats().rejection_codes == (
            "raw_host_path",
            "raw_host_path",
            "raw_host_path",
        )
    finally:
        broker.stop()
