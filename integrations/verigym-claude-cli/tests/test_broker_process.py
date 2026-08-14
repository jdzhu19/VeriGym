from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from verigym.core.repository_tool_broker import RepositoryToolBrokerLimits
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

from verigym_claude_cli.agent import ClaudeCliAgentAdapter, _process_failure
from verigym_claude_cli.broker import BrokerStats, ClaudeToolBroker
from verigym_claude_cli.capabilities import discover_capabilities
from verigym_claude_cli.config import agent_settings
from verigym_claude_cli.events import parse_event_stream
from verigym_claude_cli.invocation import build_arguments
from verigym_claude_cli.process import (
    ClaudeCliProcessRunner,
    ClaudeProcessResult,
    provider_environment,
    resolve_executable,
)


def _timed_out_process() -> ClaudeProcessResult:
    return ClaudeProcessResult(
        arguments=("claude",),
        exit_code=143,
        stdout="",
        stderr="",
        duration_s=1800.0,
        timed_out=True,
        stdout_truncated=True,
        stderr_truncated=False,
        process_group_cleaned=True,
    )


def _broker_stats(*, tool_calls: int) -> BrokerStats:
    return BrokerStats(
        tool_calls=tool_calls,
        command_calls=0,
        public_test_calls=0,
        file_reads=tool_calls,
        file_writes=0,
        patches=0,
        policy_failure=None,
        infrastructure_failure=None,
    )


def test_sustained_broker_activity_makes_timeout_an_agent_failure() -> None:
    active = _process_failure(_timed_out_process(), None, None, _broker_stats(tool_calls=8))
    inactive = _process_failure(_timed_out_process(), None, None, _broker_stats(tool_calls=0))

    assert active is not None
    assert active.failure.kind == "model"
    assert active.failure.category == "agent_timeout"
    assert active.failure.infrastructure is False
    assert inactive is not None
    assert inactive.failure.kind == "runtime"
    assert inactive.failure.category == "timeout"
    assert inactive.failure.infrastructure is True


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


class RetryablePatchBridge(FakeBridge):
    def invoke_workspace_tool(self, tool_name: str, request: dict[str, JsonValue]) -> ToolResult:
        if tool_name == "file.apply_patch":
            return ToolResult(
                tool=tool_name,
                success=False,
                category=ErrorCategory.PERMISSION_DENIED,
                message="patch context does not match the workspace",
            )
        return super().invoke_workspace_tool(tool_name, request)


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
    with pytest.raises(RuntimeError, match="not enabled"):
        broker.training_turns()


def test_broker_capture_is_training_only_and_preserves_canonical_turns(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="training-only"):
        ClaudeToolBroker(
            bridge=FakeBridge(),
            socket_path=tmp_path / "heldout" / "mcp.sock",
            public_test_ids=(),
            capture_training_transcript=True,
            campaign_role="heldout",
        )
    broker = ClaudeToolBroker(
        bridge=FakeBridge(),
        socket_path=tmp_path / "training" / "mcp.sock",
        public_test_ids=(),
        capture_training_transcript=True,
        campaign_role="training",
    )
    broker.start()
    try:
        response = _call(broker.socket_path, "list_files", {"path": "repository"})
    finally:
        broker.stop()

    turns = broker.training_turns()
    assert len(turns) == 1
    assert turns[0].tool_name == "list_files"
    assert json.loads(turns[0].arguments_json) == {"path": "repository", "recursive": True}
    assert turns[0].observation_json == response["content"][0]["text"]


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


def test_patch_context_error_is_retryable_not_terminal_policy(tmp_path: Path) -> None:
    broker = ClaudeToolBroker(
        bridge=RetryablePatchBridge(),
        socket_path=tmp_path / "private" / "mcp.sock",
        public_test_ids=(),
    )
    broker.start()
    try:
        request = {"patch": "--- a/repository/a.sv\n+++ b/repository/a.sv\n@@ -1 +1 @@\n-a\n+b\n"}
        assert _call(broker.socket_path, "apply_patch", request)["isError"] is True
        assert _call(broker.socket_path, "apply_patch", request)["isError"] is True
        assert (
            _call(broker.socket_path, "read_file", {"path": "repository/a.sv"})["isError"] is False
        )
    finally:
        broker.stop()
    stats = broker.stats()
    assert stats.policy_failure is None
    assert stats.infrastructure_failure is None
    assert stats.rejected_calls == 2
    assert stats.patches == 2


def test_broker_stops_at_the_total_tool_call_limit(tmp_path: Path) -> None:
    broker = ClaudeToolBroker(
        bridge=FakeBridge(),
        socket_path=tmp_path / "private" / "mcp.sock",
        public_test_ids=(),
        limits=RepositoryToolBrokerLimits(
            max_tool_calls=3,
            max_patch_calls=2,
            max_consecutive_rejected_calls=2,
        ),
    )
    broker.start()
    try:
        for _ in range(3):
            assert (
                _call(broker.socket_path, "list_files", {"path": "repository"})["isError"] is False
            )
        assert broker.cancellation_event.wait(timeout=1)
        assert (
            _call(broker.socket_path, "read_file", {"path": "repository/a.sv"})["isError"] is True
        )
    finally:
        broker.stop()
    stats = broker.stats()
    assert stats.tool_calls == 3
    assert stats.limit_failure == "repository_tool_call_limit"
    assert stats.max_tool_calls == 3


def test_broker_rejects_the_ninth_patch_without_executing_it(tmp_path: Path) -> None:
    bridge = FakeBridge()
    broker = ClaudeToolBroker(
        bridge=bridge,
        socket_path=tmp_path / "private" / "mcp.sock",
        public_test_ids=(),
        limits=RepositoryToolBrokerLimits(
            max_tool_calls=32,
            max_patch_calls=8,
            max_consecutive_rejected_calls=3,
        ),
    )
    request = {"patch": "--- a/a.sv\n+++ b/a.sv\n@@ -1 +1 @@\n-a\n+b\n"}
    broker.start()
    try:
        for _ in range(8):
            assert _call(broker.socket_path, "apply_patch", request)["isError"] is False
        assert _call(broker.socket_path, "apply_patch", request)["isError"] is True
        assert broker.cancellation_event.wait(timeout=1)
    finally:
        broker.stop()
    stats = broker.stats()
    assert stats.tool_calls == 9
    assert stats.patches == 8
    assert stats.rejected_calls == 1
    assert stats.limit_failure == "repository_patch_call_limit"
    assert len(bridge.events) == 0


def test_broker_stops_after_three_consecutive_rejections_and_resets_on_success(
    tmp_path: Path,
) -> None:
    broker = ClaudeToolBroker(
        bridge=RetryablePatchBridge(),
        socket_path=tmp_path / "private" / "mcp.sock",
        public_test_ids=(),
        limits=RepositoryToolBrokerLimits(
            max_tool_calls=32,
            max_patch_calls=8,
            max_consecutive_rejected_calls=3,
        ),
    )
    request = {"patch": "--- a/a.sv\n+++ b/a.sv\n@@ -1 +1 @@\n-a\n+b\n"}
    broker.start()
    try:
        assert _call(broker.socket_path, "apply_patch", request)["isError"] is True
        assert _call(broker.socket_path, "apply_patch", request)["isError"] is True
        assert (
            _call(broker.socket_path, "read_file", {"path": "repository/a.sv"})["isError"] is False
        )
        for _ in range(3):
            assert _call(broker.socket_path, "apply_patch", request)["isError"] is True
        assert broker.cancellation_event.wait(timeout=1)
    finally:
        broker.stop()
    stats = broker.stats()
    assert stats.rejected_calls == 5
    assert stats.consecutive_rejected_calls == 3
    assert stats.maximum_consecutive_rejected_calls == 3
    assert stats.limit_failure == "repository_consecutive_rejection_limit"


def test_broker_limit_is_an_infrastructure_valid_agent_failure() -> None:
    stats = _broker_stats(tool_calls=32)
    stats = BrokerStats(
        **{
            **stats.__dict__,
            "limit_failure": "repository_tool_call_limit",
            "max_tool_calls": 32,
            "max_patch_calls": 8,
            "max_consecutive_rejected_calls": 3,
        }
    )
    failure = _process_failure(_timed_out_process(), None, None, stats)

    assert failure is not None
    assert failure.failure.kind == "agent"
    assert failure.failure.category == "broker_resource_limit"
    assert failure.failure.infrastructure is False


def test_successful_terminal_without_provider_usage_is_infrastructure_invalid() -> None:
    parsed = parse_event_stream(
        "\n".join(
            (
                json.dumps(
                    {
                        "type": "system",
                        "subtype": "init",
                        "model": "deepseek-v4-flash[1m]",
                        "tools": [
                            "mcp__verigym__list_files",
                            "mcp__verigym__read_file",
                            "mcp__verigym__apply_patch",
                            "mcp__verigym__run_public_test",
                            "mcp__verigym__inspect_diff",
                            "mcp__verigym__finish",
                        ],
                    }
                ),
                json.dumps({"type": "result", "subtype": "success", "is_error": False}),
            )
        ),
        requested_model_id="deepseek-v4-flash[1m]",
        expected_context_window_tokens=None,
    )
    process = ClaudeProcessResult(
        arguments=("claude",),
        exit_code=0,
        stdout="",
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    failure = _process_failure(process, parsed, None, _broker_stats(tool_calls=1))

    assert failure is not None
    assert failure.failure.category == "provider_usage_missing"
    assert failure.failure.infrastructure is True


def test_native_provider_budget_exhaustion_is_an_infrastructure_valid_agent_failure() -> None:
    parsed = parse_event_stream(
        "\n".join(
            (
                json.dumps(
                    {
                        "type": "system",
                        "subtype": "init",
                        "model": "deepseek-v4-flash[1m]",
                        "tools": [
                            "mcp__verigym__list_files",
                            "mcp__verigym__read_file",
                            "mcp__verigym__apply_patch",
                            "mcp__verigym__run_public_test",
                            "mcp__verigym__inspect_diff",
                            "mcp__verigym__finish",
                        ],
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "usage": {"input_tokens": 10, "output_tokens": 10},
                        "total_cost_usd": 2.0,
                    }
                ),
            )
        ),
        requested_model_id="deepseek-v4-flash[1m]",
        expected_context_window_tokens=None,
    )
    process = ClaudeProcessResult(
        arguments=("claude",),
        exit_code=0,
        stdout="",
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    failure = _process_failure(
        process,
        parsed,
        None,
        _broker_stats(tool_calls=1),
        max_budget_usd=2.0,
    )

    assert failure is not None
    assert failure.failure.category == "provider_resource_limit"
    assert failure.failure.infrastructure is False


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
    assert record["max_budget_usd"] == "2"


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


def test_process_runner_kills_the_process_group_when_the_broker_cancels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable_path = Path(__file__).with_name("fake_claude.py")
    monkeypatch.setenv("VERIGYM_CLAUDE_BINARY", str(executable_path))
    monkeypatch.setenv("VERIGYM_CLAUDE_TEST_MODE", "1")
    monkeypatch.setenv("VERIGYM_FAKE_CLAUDE_SCENARIO", "sleep")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/api")
    control = tmp_path / "control-cancellation"
    control.mkdir()
    cancellation = threading.Event()
    timer = threading.Timer(0.1, cancellation.set)
    timer.start()
    started = time.monotonic()
    try:
        result = ClaudeCliProcessRunner(resolve_executable()).run(
            ["--allowedTools", "unused", "--model", "unused"],
            cwd=control,
            timeout_s=10,
            stdin_bytes=b"test",
            environment=provider_environment(
                control,
                allow_proxy_environment=False,
                include_auth=True,
            ),
            cancellation_event=cancellation,
        )
    finally:
        timer.cancel()

    assert time.monotonic() - started < 3
    assert result.broker_cancelled is True
    assert result.timed_out is False
    assert result.process_group_cleaned is True


def test_process_runner_enforces_live_cache_inclusive_provider_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable_path = Path(__file__).with_name("fake_claude.py")
    monkeypatch.setenv("VERIGYM_CLAUDE_BINARY", str(executable_path))
    monkeypatch.setenv("VERIGYM_CLAUDE_TEST_MODE", "1")
    monkeypatch.setenv("VERIGYM_FAKE_CLAUDE_SCENARIO", "provider-token-runaway")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/api")
    control = tmp_path / "control-provider-limit"
    control.mkdir()
    started = time.monotonic()
    result = ClaudeCliProcessRunner(resolve_executable()).run(
        ["--allowedTools", "unused", "--model", "unused"],
        cwd=control,
        timeout_s=10,
        stdin_bytes=b"test",
        environment=provider_environment(
            control,
            allow_proxy_environment=False,
            include_auth=True,
        ),
        max_provider_tokens=250,
    )

    assert time.monotonic() - started < 3
    assert result.provider_cancelled is True
    assert result.provider_limit_failure == "claude_provider_token_limit"
    assert result.observed_provider_billed_tokens is not None
    assert result.observed_provider_billed_tokens >= 250
    assert result.stream_monitor_failed is False
    assert result.process_group_cleaned is True
    failure = _process_failure(result, None, "missing terminal", _broker_stats(tool_calls=0))
    assert failure is not None
    assert failure.failure.category == "provider_resource_limit"
    assert failure.failure.infrastructure is False


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
    assert process_evidence["broker_cancelled"] is False
    usage = json.loads((bridge.artifact_root / "provider-usage.json").read_text(encoding="utf-8"))
    assert usage == {
        "billed_tokens_observed": 26,
        "cache_creation_input_tokens": 5,
        "cache_read_input_tokens": 7,
        "cache_usage_reported": True,
        "cost_usd": 0.125,
        "currency": "USD",
        "input_tokens": 11,
        "output_tokens": 3,
        "provider_report_scope": "claude_cli_terminal_result",
        "provider_limit_failure": None,
        "schema_version": "1.0",
        "total_tokens": 14,
        "usage_complete": True,
        "usage_missing": False,
    }
    summary = json.loads((bridge.artifact_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["ordinary_hidden_verifier_pending"] is False
    assert summary["ordinary_verifier_resolved"] is False
    events = (bridge.artifact_root / "events.json").read_text(encoding="utf-8")
    assert "done" not in events
