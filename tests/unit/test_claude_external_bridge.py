from __future__ import annotations

from pathlib import Path

from verigym.core.external_agent import _IDENTITY_EVENT_TYPES, RuntimeExternalAgentBridge
from verigym.core.orchestrator import (
    _external_agent_artifact_namespace,
    _external_agent_isolation_label,
)
from verigym.core.trace import TraceWriter, read_trace
from verigym.core.workspace import WorkspacePolicy
from verigym.runtimes.local import LocalRuntimeSession
from verigym.schemas.external_agent import ExternalAgentAccounting, ExternalAgentCallIdentity
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.tool import CommandSpec


def test_claude_bridge_uses_core_workspace_tools_and_own_event_namespace(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "repository").mkdir(parents=True)
    (source / "repository" / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    (source / "TASK.md").write_text("task\n", encoding="utf-8")
    session = LocalRuntimeSession(SessionSpec(source_dir=str(source), label="agent"))
    try:
        trace = TraceWriter(tmp_path / "trace.jsonl", "run")
        bridge = RuntimeExternalAgentBridge(
            session=session,
            artifact_root=tmp_path / "artifacts" / "claude_cli",
            isolation_level="docker_standard",
            policy=WorkspacePolicy(
                editable_globs=("repository/**",),
                readonly_globs=("TASK.md",),
            ),
            trace=trace,
        )
        assert bridge.command_execution_backend == "runtime_external_command_unavailable"
        result = bridge.invoke_workspace_tool(
            "file.write",
            {"path": "repository/a.sv", "content": "module fixed; endmodule\n"},
        )
        assert result.success
        assert bridge.execute_command(CommandSpec(argv=["/bin/true"])).exit_code == 0
        identity = ExternalAgentCallIdentity(
            adapter_name="claude-cli-agent",
            adapter_version="0.1.0",
            harness_name="verigym-claude-mcp-external-agent-bridge",
            requested_model_id="deepseek-v4-flash[1m]",
            observed_model_id="deepseek-v4-flash",
            executable_name="claude",
            executable_sha256="0" * 64,
            executable_version="2.1.168",
            capability_fingerprint="1" * 64,
            configuration_fingerprint="2" * 64,
            invocation_count=1,
            integration_track="claude_cli_external_agent",
            execution_surface="claude_cli",
            interaction_class="cli_agent_workspace_writing",
            harness_id="claude-code-2.1.168",
            model_client_kind="cli_agent_mediated",
            agent_harness_kind="claude_cli",
            tool_availability_policy="verigym_mcp_only_no_builtin_tools_v1",
            tool_use_policy="docker_runtime_workspace_tools_v1",
            tool_event_count=0,
            side_effecting_tool_event_count=0,
            read_only_tool_event_count=0,
            external_network_tool_event_count=0,
            mcp_tool_event_count=0,
            workspace_write_count=1,
            chat_eval_compatible=False,
            pure_api_model_eval=False,
            direct_api_benchmark=False,
            identity_confidence="observed",
            reproducibility_scope="mutable_remote_observation",
        )
        bridge.emit_event("claude_cli_identity_observed", identity.model_dump(mode="json"))
        bridge.record_accounting(ExternalAgentAccounting(process_wall_time_s=1, cli_event_count=3))
        assert bridge.observations == [identity]
        assert [event.event_type for event in read_trace(tmp_path / "trace.jsonl")] == [
            "claude_cli_identity_observed",
            "claude_cli_accounting_recorded",
        ]
    finally:
        session.close()


def test_external_agent_artifacts_and_isolation_are_role_aware() -> None:
    assert _external_agent_artifact_namespace("codex-cli-agent") == "codex_cli"
    assert _external_agent_artifact_namespace("claude-cli-agent") == "claude_cli"
    assert _external_agent_artifact_namespace("deepseek-harness-hwe-agent") == "deepseek_harness"
    assert (
        _external_agent_isolation_label("claude-cli-agent", "docker_outer_runtime_delegated")
        == "host_claude_control_plane_runtime_mcp_delegated"
    )
    assert (
        _external_agent_isolation_label(
            "deepseek-harness-hwe-agent", "docker_outer_runtime_delegated"
        )
        == "host_deepseek_harness_control_plane_runtime_tools_delegated"
    )
    assert "openhands_sdk_identity_observed" in _IDENTITY_EVENT_TYPES
