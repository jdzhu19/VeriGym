from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from verigym.plugin_api import (
    AgentContext,
    CompletedCommand,
    ErrorCategory,
    ExternalAgentAccounting,
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalReadOnlyMountIdentity,
    FinalSubmissionAction,
    JsonValue,
    PathPolicyError,
    ToolResult,
)
from verigym.prompts.policy import resolve_prompt_policy
from verigym.schemas.agent import BudgetRemaining, EpisodeResult, Observation
from verigym.schemas.common import InteractionMode
from verigym.suites.toy_rtl.adapter import ToyRtlSuite

from verigym_claude_cli.agent import ClaudeCliAgentAdapter
from verigym_claude_cli.broker import ClaudeToolBroker
from verigym_claude_cli.capabilities import discover_capabilities
from verigym_claude_cli.config import agent_settings
from verigym_claude_cli.events import parse_event_stream
from verigym_claude_cli.invocation import build_arguments
from verigym_claude_cli.process import (
    ClaudeCliProcessRunner,
    provider_environment,
    resolve_executable,
)


class FakeBridge:
    isolation_level = "docker_standard"
    editable_globs = ("repository/**",)
    readonly_globs = ("TASK.md",)
    execution_backend = "docker_outer_runtime_delegated"
    logical_workspace_root = "/workspace"
    read_only_mounts: list[ExternalReadOnlyMountIdentity] = []

    def __init__(self, root: Path | None = None) -> None:
        self.workspace_root = root or Path("/workspace")
        self.artifact_root = (root / "artifacts") if root is not None else Path("/artifacts")
        self.events: list[tuple[str, dict[str, JsonValue]]] = []
        self.accounting: ExternalAgentAccounting | None = None

    def execute_process(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        raise AssertionError(request)

    def invoke_workspace_tool(self, tool_name: str, request: dict[str, JsonValue]) -> ToolResult:
        return ToolResult(
            tool=tool_name,
            success=True,
            category=ErrorCategory.SUCCESS,
            stdout=json.dumps(request, sort_keys=True),
        )

    def execute_public_test(self, test_id: str) -> CompletedCommand:
        return CompletedCommand(argv=["verigym-public-test", "run", test_id], cwd=".", exit_code=0)

    def emit_event(self, event_type: str, payload: dict[str, JsonValue]) -> None:
        self.events.append((event_type, payload))

    def record_accounting(self, accounting: ExternalAgentAccounting) -> None:
        self.accounting = accounting


class ExplodingBridge(FakeBridge):
    def invoke_workspace_tool(self, tool_name: str, request: dict[str, JsonValue]) -> ToolResult:
        raise RuntimeError("simulated bridge control-plane failure")


class PolicyRejectingBridge(FakeBridge):
    def invoke_workspace_tool(self, tool_name: str, request: dict[str, JsonValue]) -> ToolResult:
        del tool_name, request
        raise PathPolicyError("simulated absolute-path policy rejection")


def _call(socket_path: Path, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"name": name, "arguments": arguments}).encode() + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(payload)
        data = bytearray()
        while not data.endswith(b"\n"):
            data.extend(client.recv(65536))
    result = json.loads(data)
    assert isinstance(result, dict)
    return result


def test_broker_routes_only_typed_workspace_and_runtime_calls(tmp_path: Path) -> None:
    bridge = FakeBridge()
    broker = ClaudeToolBroker(
        bridge=bridge,
        socket_path=tmp_path / "private" / "mcp.sock",
        public_test_ids=("smoke",),
    )
    broker.start()
    try:
        assert (
            _call(broker.socket_path, "read_file", {"path": "repository/a.sv"})["isError"] is False
        )
        assert (
            _call(
                broker.socket_path,
                "apply_patch",
                {
                    "patch": (
                        "*** Begin Patch\n*** Update File: repository/a.sv\n"
                        "@@\n-a\n+b\n*** End Patch"
                    )
                },
            )["isError"]
            is False
        )
        assert (
            _call(broker.socket_path, "run_public_test", {"test_id": "smoke"})["isError"] is False
        )
        assert _call(broker.socket_path, "inspect_diff", {})["isError"] is False
        assert _call(broker.socket_path, "finish", {"message": "done"})["isError"] is False
        assert _call(broker.socket_path, "run_command", {"argv": ["id"]})["isError"] is True
        assert _call(broker.socket_path, "Bash", {"command": "id"})["isError"] is True
    finally:
        broker.stop()
    stats = broker.stats()
    assert stats.tool_calls == 5
    assert stats.command_calls == 0
    assert stats.public_test_calls == 1
    assert stats.file_reads == 1
    assert stats.patches == 1
    assert stats.diff_inspections == 1
    assert stats.finish_calls == 1
    assert stats.finished is True


def test_unexpected_bridge_exception_is_infrastructure_not_policy(tmp_path: Path) -> None:
    broker = ClaudeToolBroker(
        bridge=ExplodingBridge(),
        socket_path=tmp_path / "private" / "mcp.sock",
        public_test_ids=(),
    )
    broker.start()
    try:
        assert _call(broker.socket_path, "read_file", {"path": "repository/a.sv"})["isError"]
    finally:
        broker.stop()
    stats = broker.stats()
    assert stats.policy_failure is None
    assert stats.infrastructure_failure == "simulated bridge control-plane failure"


def test_bridge_path_rejection_is_policy_not_infrastructure(tmp_path: Path) -> None:
    broker = ClaudeToolBroker(
        bridge=PolicyRejectingBridge(),
        socket_path=tmp_path / "private" / "mcp.sock",
        public_test_ids=(),
    )
    broker.start()
    try:
        assert _call(broker.socket_path, "read_file", {"path": "repository/a.sv"})["isError"]
    finally:
        broker.stop()
    stats = broker.stats()
    assert stats.policy_failure == "simulated absolute-path policy rejection"
    assert stats.infrastructure_failure is None


def test_fake_process_receives_explicit_max_effort_without_output_token_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable_path = Path(__file__).with_name("fake_claude.py")
    broker_root = tmp_path / "broker"
    broker_root.mkdir(mode=0o700)
    monkeypatch.setenv("VERIGYM_CLAUDE_BINARY", str(executable_path))
    monkeypatch.setenv("VERIGYM_CLAUDE_BROKER_ROOT", str(broker_root))
    monkeypatch.setenv("VERIGYM_CLAUDE_TEST_MODE", "1")
    monkeypatch.setenv("VERIGYM_FAKE_CLAUDE_LOG", str(tmp_path / "fake.json"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/api")
    monkeypatch.setenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "123")
    executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    settings = agent_settings(
        {
            "model_id": "deepseek-v4-flash[1m]",
            "expected_context_window": 1_000_000,
        },
        capabilities,
        task_wall_time_s=1800,
    )
    control = tmp_path / "control"
    control.mkdir()
    arguments = build_arguments(
        settings,
        socket_path=tmp_path / "unused.sock",
        run_id="fake-run",
    )
    result = ClaudeCliProcessRunner(executable).run(
        arguments,
        cwd=control,
        timeout_s=10,
        stdin_bytes=b"test",
        environment=provider_environment(
            control,
            allow_proxy_environment=False,
            include_auth=True,
        ),
    )
    assert result.exit_code == 0
    parsed = parse_event_stream(
        result.stdout,
        requested_model_id=settings.model_id,
        expected_context_window_tokens=1_000_000,
    )
    assert parsed.per_response_max_output_tokens == 32_000
    record = json.loads((tmp_path / "fake.json").read_text(encoding="utf-8"))
    assert record["anthropic_api_key_present"] is False
    assert record["anthropic_auth_token_present"] is True
    assert record["anthropic_base_url_present"] is True
    assert record["effort"] == "max"
    assert record["nonessential_traffic_disabled"] == "1"
    assert record["max_mcp_output_tokens"] == str(512 * 1024)
    assert record["max_output_environment_present"] is False


def test_process_redacts_gateway_token_from_both_output_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-only-super-secret-auth-token"
    executable_path = Path(__file__).with_name("fake_claude.py")
    monkeypatch.setenv("VERIGYM_CLAUDE_BINARY", str(executable_path))
    monkeypatch.setenv("VERIGYM_CLAUDE_TEST_MODE", "1")
    monkeypatch.setenv("VERIGYM_FAKE_CLAUDE_SCENARIO", "echo-auth")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", secret)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/api")
    control = tmp_path / "control-redaction"
    control.mkdir()
    environment = provider_environment(
        control,
        allow_proxy_environment=False,
        include_auth=True,
    )
    result = ClaudeCliProcessRunner(resolve_executable()).run(
        ["--allowedTools", "unused", "--model", "unused"],
        cwd=control,
        timeout_s=10,
        stdin_bytes=b"test",
        environment=environment,
    )
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert "<redacted-anthropic_auth_token>" in result.stdout
    assert "<redacted-anthropic_auth_token>" in result.stderr


def test_adapter_runs_one_outer_turn_and_writes_content_free_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable_path = Path(__file__).with_name("fake_claude.py")
    broker_root = tmp_path / "broker"
    broker_root.mkdir(mode=0o700)
    monkeypatch.setenv("VERIGYM_CLAUDE_BINARY", str(executable_path))
    monkeypatch.setenv("VERIGYM_CLAUDE_BROKER_ROOT", str(broker_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/api")
    task = ToyRtlSuite().load_task(next(iter(ToyRtlSuite().discover())))
    agent = ClaudeCliAgentAdapter()
    options: dict[str, JsonValue] = {
        "model_id": "deepseek-v4-flash[1m]",
        "reasoning_effort": "max",
        "expected_context_window": 1_000_000,
    }
    policy = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=agent,
        agent_options=options,
        task=task,
    )
    bridge = FakeBridge(tmp_path / "workspace")
    bridge.workspace_root.mkdir()
    bridge.artifact_root.mkdir()
    context = AgentContext(
        run_id="claude-fake-run",
        task=task,
        seed=3,
        agent_options=options,
        external_bridge=bridge,
        prompt_policy=policy,
    )
    agent.start(context)
    action = agent.act(
        Observation(
            task_id=task.id,
            remaining_budget=BudgetRemaining(
                turns=1,
                tool_calls=0,
                wall_time_s=task.budget.max_wall_time_s,
            ),
            episode_status="running",
        )
    )
    assert isinstance(action, FinalSubmissionAction)
    agent.finish(
        EpisodeResult(
            run_id="claude-fake-run",
            resolved=False,
            termination_reason="final_submission",
        )
    )
    assert bridge.accounting is not None
    assert bridge.accounting.cli_event_count == 3
    assert any(event == "claude_cli_identity_observed" for event, _payload in bridge.events)
    process_evidence = json.loads(
        (bridge.artifact_root / "process.json").read_text(encoding="utf-8")
    )
    assert process_evidence["raw_stdout_persisted"] is False
    assert process_evidence["stderr_content_persisted"] is False
    summary = json.loads((bridge.artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["ordinary_hidden_verifier_pending"] is False
    assert summary["ordinary_verifier_resolved"] is False
    events = (bridge.artifact_root / "events.json").read_text(encoding="utf-8")
    assert "done" not in events
