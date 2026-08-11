from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from verigym.core.hashing import canonical_json, content_hash
from verigym.evolution.memory import build_agent_version
from verigym.schemas.evolution import AgentVersionManifest

from verigym_claude_cli.agent import _identity
from verigym_claude_cli.broker import BrokerStats
from verigym_claude_cli.capabilities import discover_capabilities
from verigym_claude_cli.config import agent_settings
from verigym_claude_cli.events import EventParseError, parse_event_stream
from verigym_claude_cli.invocation import build_arguments, sanitized_invocation
from verigym_claude_cli.mcp_tools import CLAUDE_TOOL_NAMES
from verigym_claude_cli.process import resolve_executable
from verigym_claude_cli.util import redact_value


@pytest.fixture
def configured_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    executable = Path(__file__).with_name("fake_claude.py")
    broker_root = tmp_path / "broker"
    broker_root.mkdir(mode=0o700)
    monkeypatch.setenv("VERIGYM_CLAUDE_BINARY", str(executable))
    monkeypatch.setenv("VERIGYM_CLAUDE_BROKER_ROOT", str(broker_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/api")
    return broker_root


def test_capabilities_and_invocation_apply_no_agent_or_token_caps(
    configured_fake: Path,
) -> None:
    executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    assert executable.name == "fake_claude.py"
    assert capabilities.model_call_count == 0
    settings = agent_settings(
        {
            "model_id": "deepseek-v4-flash[1m]",
            "reasoning_effort": "max",
            "expected_context_window": 1_000_000,
        },
        capabilities,
        task_wall_time_s=1800,
    )
    socket_path = configured_fake / "run" / "mcp.sock"
    arguments = build_arguments(settings, socket_path=socket_path, run_id="run-1")
    invocation = sanitized_invocation(arguments, settings)
    assert arguments[arguments.index("--tools") + 1] == ""
    assert arguments[arguments.index("--allowedTools") + 1] == ",".join(CLAUDE_TOOL_NAMES)
    mcp = json.loads(arguments[arguments.index("--mcp-config") + 1])
    assert mcp["mcpServers"]["verigym"]["command"] == "/usr/bin/env"
    mcp_arguments = mcp["mcpServers"]["verigym"]["args"]
    assert ["-u", "ANTHROPIC_API_KEY"] == mcp_arguments[:2]
    assert any(
        mcp_arguments[index : index + 2] == ["-u", "ANTHROPIC_AUTH_TOKEN"]
        for index in range(len(mcp_arguments) - 1)
    )
    assert settings.resolved_auth_mode == "anthropic_auth_token_env"
    assert settings.auth_semantic_id == ("claude.auth.anthropic_auth_token_env_custom_base.v1")
    assert (
        settings.provider_endpoint_sha256
        == hashlib.sha256(b"https://provider.invalid/api").hexdigest()
    )
    assert "--max-budget-usd" not in arguments
    assert invocation["internal_turn_limit"] is None
    assert invocation["model_call_limit"] is None
    assert invocation["model_token_limit"] is None
    assert invocation["budget_limit"] is None


def test_api_key_auth_keeps_a_distinct_frozen_semantic(
    configured_fake: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-real-key")
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    settings = agent_settings(
        {"model_id": "deepseek-v4-flash[1m]"},
        capabilities,
        task_wall_time_s=1800,
    )
    assert settings.resolved_auth_mode == "anthropic_api_key_env"
    assert settings.auth_semantic_id == "claude.auth.anthropic_api_key_env_custom_base.v1"


def test_ambiguous_authentication_environment_is_rejected(
    configured_fake: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-real-key")
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    with pytest.raises(ValueError, match="export exactly one credential"):
        agent_settings(
            {"model_id": "deepseek-v4-flash[1m]"},
            capabilities,
            task_wall_time_s=1800,
        )


def test_provider_endpoint_path_is_bound_without_persisting_it(
    configured_fake: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    first = agent_settings(
        {"model_id": "deepseek-v4-flash[1m]"},
        capabilities,
        task_wall_time_s=1800,
    )
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/other")
    second = agent_settings(
        {"model_id": "deepseek-v4-flash[1m]"},
        capabilities,
        task_wall_time_s=1800,
    )
    assert first.provider_origin == second.provider_origin == "https://provider.invalid"
    assert first.provider_endpoint_sha256 != second.provider_endpoint_sha256
    assert first.configuration_fingerprint != second.configuration_fingerprint


def test_frozen_agent_version_binds_claude_model_effort_and_auth_semantic(
    configured_fake: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from verigym_claude_cli.agent import ClaudeCliAgentAdapter

    version = build_agent_version(
        agent_version_id="claude-deepseek-flash-max-v1",
        status="frozen",
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=True,
        base_agent_id="claude-cli-agent",
        agent_descriptor_hash=content_hash(ClaudeCliAgentAdapter.descriptor),
        model_id="deepseek-v4-flash[1m]",
        reasoning_effort="max",
        auth_semantic_id="claude.auth.anthropic_auth_token_env_custom_base.v1",
        runtime_identity_hash="3" * 64,
        tool_policy_hash="4" * 64,
        prompt_contract_hash="5" * 64,
        source_commit="53b0755715a876432ddcdface143632278ccddd3",
        package_hashes={"verigym": "6" * 64, "plugin": "7" * 64},
        image_hashes={"agent": "8" * 64, "verifier": "9" * 64},
        model_weights_modified=False,
    )
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    options = {
        "model_id": "deepseek-v4-flash[1m]",
        "reasoning_effort": "max",
        "agent_version_id": version.agent_version_id,
        "agent_version_hash": version.version_hash,
        "agent_version_manifest_json": canonical_json(version),
    }
    settings = agent_settings(options, capabilities, task_wall_time_s=1800)
    assert settings.agent_version_hash == version.version_hash
    malformed = version.model_dump(mode="json")
    malformed["model_id"] = "deepseek-v4-flash[1m][unexpected]"
    with pytest.raises(ValueError, match="provider-model identifier vocabulary"):
        AgentVersionManifest.model_validate(malformed)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-real-key")
    with pytest.raises(ValueError, match="differs from effective Claude settings"):
        agent_settings(options, capabilities, task_wall_time_s=1800)


@pytest.mark.parametrize(
    "option",
    ["max_turns", "max_model_calls", "max_output_tokens", "max_total_tokens", "max_budget_usd"],
)
def test_artificial_limit_options_are_rejected(
    configured_fake: Path,
    option: str,
) -> None:
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    with pytest.raises(ValueError, match="unknown Claude CLI agent options"):
        agent_settings(
            {"model_id": "deepseek-v4-flash[1m]", option: 1},
            capabilities,
            task_wall_time_s=1800,
        )


def test_stream_parser_records_context_without_message_or_thinking_content() -> None:
    events = [
        {
            "type": "system",
            "subtype": "init",
            "model": "deepseek-v4-flash[1m]",
            "tools": list(CLAUDE_TOOL_NAMES),
        },
        {
            "type": "assistant",
            "message": {
                "model": "deepseek-v4-flash",
                "content": [
                    {"type": "thinking", "thinking": "must never be persisted"},
                    {
                        "type": "tool_use",
                        "name": "mcp__verigym__read_file",
                        "input": {"path": "repository/a.sv"},
                    },
                ],
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 2,
            "result": "complete",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "modelUsage": {
                "deepseek-v4-flash": {
                    "contextWindow": 1_000_000,
                    "maxOutputTokens": 32_000,
                }
            },
        },
    ]
    parsed = parse_event_stream(
        "\n".join(json.dumps(event) for event in events),
        requested_model_id="deepseek-v4-flash[1m]",
        expected_context_window_tokens=1_000_000,
    )
    assert parsed.successful
    assert parsed.observed_model_id == "deepseek-v4-flash"
    assert parsed.context_window_tokens == 1_000_000
    assert parsed.per_response_max_output_tokens == 32_000
    assert parsed.thinking_block_count == 1
    assert "must never be persisted" not in json.dumps(
        [event.safe_dict() for event in parsed.events]
    )


def test_stream_parser_rejects_builtin_tool() -> None:
    events = [
        {
            "type": "system",
            "subtype": "init",
            "model": "deepseek-v4-flash[1m]",
            "tools": list(CLAUDE_TOOL_NAMES),
        },
        {
            "type": "assistant",
            "message": {
                "model": "deepseek-v4-flash",
                "content": [{"type": "tool_use", "name": "Bash", "input": {}}],
            },
        },
        {"type": "result", "subtype": "success", "is_error": False},
    ]
    with pytest.raises(EventParseError, match="outside the MCP allowlist"):
        parse_event_stream(
            "\n".join(json.dumps(event) for event in events),
            requested_model_id="deepseek-v4-flash[1m]",
            expected_context_window_tokens=None,
        )


def test_stream_parser_preserves_remote_failure_after_retry_without_context_usage() -> None:
    events = [
        {
            "type": "system",
            "subtype": "init",
            "model": "deepseek-v4-flash[1m]",
            "tools": list(CLAUDE_TOOL_NAMES),
        },
        {"type": "system", "subtype": "api_retry", "attempt": 1},
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "errors": ["server overloaded"],
        },
    ]
    parsed = parse_event_stream(
        "\n".join(json.dumps(event) for event in events),
        requested_model_id="deepseek-v4-flash[1m]",
        expected_context_window_tokens=1_000_000,
    )
    assert not parsed.successful
    assert parsed.context_window_tokens is None
    assert parsed.failure_message == "server overloaded"


def test_identity_classifies_mcp_transport_once(
    configured_fake: Path,
) -> None:
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    settings = agent_settings(
        {"model_id": "deepseek-v4-flash[1m]"},
        capabilities,
        task_wall_time_s=1800,
    )
    broker = BrokerStats(
        tool_calls=4,
        command_calls=1,
        public_test_calls=0,
        file_reads=2,
        file_writes=0,
        patches=1,
        policy_failure=None,
        infrastructure_failure=None,
    )
    identity = _identity(settings, capabilities, None, broker)
    assert identity.tool_event_count == 4
    assert identity.mcp_tool_event_count == 4
    assert identity.side_effecting_tool_event_count == 0
    assert identity.read_only_tool_event_count == 0
    assert identity.workspace_write_count == 1


def test_token_unit_provenance_is_not_mistaken_for_a_secret() -> None:
    value = redact_value(
        {
            "context_window_tokens": 1_000_000,
            "per_response_max_output_tokens": 32_000,
            "model_token_limit_configured": False,
            "access_token": "must-be-redacted",
        }
    )
    assert value == {
        "context_window_tokens": 1_000_000,
        "per_response_max_output_tokens": 32_000,
        "model_token_limit_configured": False,
        "access_token": "<redacted>",
    }
