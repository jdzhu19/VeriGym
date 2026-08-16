from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from verigym.core.hashing import canonical_json, content_hash
from verigym.evolution.memory import build_agent_version
from verigym.schemas.evolution import AgentVersionManifest

from verigym_claude_cli.agent import _identity, _training_system_prompt
from verigym_claude_cli.broker import BrokerStats
from verigym_claude_cli.capabilities import discover_capabilities
from verigym_claude_cli.config import agent_settings
from verigym_claude_cli.events import EventParseError, ProviderTokenMonitor, parse_event_stream
from verigym_claude_cli.invocation import (
    CLAUDE_BUILTIN_TOOL_NAMES,
    build_arguments,
    sanitized_invocation,
)
from verigym_claude_cli.mcp_tools import CLAUDE_TOOL_NAMES
from verigym_claude_cli.process import resolve_executable, trusted_mcp_pythonpath
from verigym_claude_cli.util import redact_value


@pytest.fixture
def configured_fake(short_broker_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    executable = Path(__file__).with_name("fake_claude.py")
    broker_root = short_broker_root
    monkeypatch.setenv("VERIGYM_CLAUDE_BINARY", str(executable))
    monkeypatch.setenv("VERIGYM_CLAUDE_BROKER_ROOT", str(broker_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-only-not-a-real-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid/api")
    return broker_root


def test_capabilities_and_invocation_apply_broker_and_provider_limits(
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
            "max_tool_calls": 32,
            "max_patch_calls": 8,
            "max_consecutive_rejected_calls": 3,
            "max_provider_billed_units": 2_000_000,
            "max_budget_usd": 2.0,
        },
        capabilities,
        task_wall_time_s=1800,
    )
    socket_path = configured_fake / "run" / "mcp.sock"
    arguments = build_arguments(
        settings,
        socket_path=socket_path,
        run_id="run-1",
        provider_system_prompt=_training_system_prompt(),
    )
    invocation = sanitized_invocation(arguments, settings)
    assert arguments[arguments.index("--append-system-prompt") + 1] == _training_system_prompt()
    assert _training_system_prompt() not in canonical_json(invocation)
    assert invocation["provider_system_prompt_transport"] == "sanitized_cli_argument"
    assert invocation["provider_system_prompt_persisted_in_argv"] is True
    assert invocation["provider_system_prompt_contains_task_context"] is False
    assert (
        invocation["provider_system_prompt_sha256"]
        == hashlib.sha256(_training_system_prompt().encode("utf-8")).hexdigest()
    )
    assert arguments[arguments.index("--tools") + 1] == ""
    assert arguments[arguments.index("--allowedTools") + 1] == ",".join(CLAUDE_TOOL_NAMES)
    assert arguments[arguments.index("--disallowedTools") + 1] == ",".join(
        CLAUDE_BUILTIN_TOOL_NAMES
    )
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
    assert arguments[arguments.index("--max-budget-usd") + 1] == "2"
    assert invocation["internal_turn_limit"] is None
    assert invocation["model_call_limit"] is None
    assert invocation["model_token_limit"] == 2_000_000
    assert invocation["model_token_limit_scope"] == "cache_inclusive_stream_observed"
    assert invocation["budget_limit"] == 2.0
    assert invocation["broker_max_tool_calls"] == 32
    assert invocation["broker_max_patch_calls"] == 8
    assert invocation["broker_max_consecutive_rejected_calls"] == 3
    assert settings.safe_configuration(capabilities)["broker_resource_limits_configured"] is True
    assert settings.safe_configuration(capabilities)["model_token_limit_configured"] is True
    assert settings.safe_configuration(capabilities)["budget_limit_configured"] is True


def test_mcp_child_receives_only_the_resolved_verigym_import_roots(
    configured_fake: Path,
) -> None:
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    settings = agent_settings(
        {"model_id": "deepseek-v4-flash[1m]"},
        capabilities,
        task_wall_time_s=600,
    )
    pythonpath = trusted_mcp_pythonpath()
    arguments = build_arguments(
        settings,
        socket_path=configured_fake / "unused.sock",
        run_id="mcp-pythonpath",
        provider_system_prompt=_training_system_prompt(),
        mcp_pythonpath=pythonpath,
    )
    mcp = json.loads(arguments[arguments.index("--mcp-config") + 1])
    server_arguments = mcp["mcpServers"]["verigym"]["args"]
    assert f"PYTHONPATH={pythonpath}" in server_arguments
    assert all(value.startswith("/") for value in pythonpath.split(os.pathsep))


def test_invocation_rejects_an_empty_provider_system_prompt(
    configured_fake: Path,
) -> None:
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    settings = agent_settings(
        {"model_id": "deepseek-v4-flash[1m]"},
        capabilities,
        task_wall_time_s=600,
    )
    with pytest.raises(ValueError, match="provider system prompt"):
        build_arguments(
            settings,
            socket_path=configured_fake / "unused.sock",
            run_id="missing-system-prompt",
            provider_system_prompt="",
        )


@pytest.mark.parametrize(
    "options",
    [
        {"max_tool_calls": 32},
        {
            "max_tool_calls": 8,
            "max_patch_calls": 9,
            "max_consecutive_rejected_calls": 3,
        },
        {
            "max_tool_calls": 32,
            "max_patch_calls": 8,
            "max_consecutive_rejected_calls": 0,
        },
    ],
)
def test_broker_limits_are_all_or_none_and_bounded(
    configured_fake: Path,
    options: dict[str, int],
) -> None:
    del configured_fake
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    with pytest.raises(ValueError, match="limits|limit|must be in"):
        agent_settings(
            {"model_id": "deepseek-v4-flash[1m]", **options},
            capabilities,
            task_wall_time_s=600,
        )


def test_nonfinal_prose_masking_is_opt_in_training_only(configured_fake: Path) -> None:
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    settings = agent_settings(
        {
            "model_id": "deepseek-v4-flash",
            "campaign_role": "training",
            "capture_training_transcript": True,
            "mask_nonfinal_assistant_prose": True,
        },
        capabilities,
        task_wall_time_s=600,
    )
    assert settings.mask_nonfinal_assistant_prose is True
    assert settings.safe_configuration(capabilities)["mask_nonfinal_assistant_prose"] is True
    with pytest.raises(ValueError, match="requires capture_training_transcript"):
        agent_settings(
            {
                "model_id": "deepseek-v4-flash",
                "mask_nonfinal_assistant_prose": True,
            },
            capabilities,
            task_wall_time_s=600,
        )


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
    ["max_turns", "max_model_calls", "max_output_tokens", "max_total_tokens"],
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


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("max_provider_billed_units", 0),
        ("max_provider_billed_units", 100_000_001),
        ("max_budget_usd", 0),
        ("max_budget_usd", 101),
    ],
)
def test_provider_limits_are_positive_and_bounded(
    configured_fake: Path,
    option: str,
    value: int,
) -> None:
    _executable, capabilities = discover_capabilities(resolve_executable(), force=True)
    with pytest.raises(ValueError, match="provider.*(?:limit|budget)|must be in"):
        agent_settings(
            {"model_id": "deepseek-v4-flash[1m]", option: value},
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
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_creation_input_tokens": 60,
                "cache_read_input_tokens": 30,
            },
            "total_cost_usd": 1.25,
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
    assert parsed.input_tokens == 100
    assert parsed.output_tokens == 20
    assert parsed.total_tokens == 120
    assert parsed.cache_creation_input_tokens == 60
    assert parsed.cache_read_input_tokens == 30
    assert parsed.cost_usd == 1.25
    assert parsed.thinking_block_count == 1
    assert "must never be persisted" not in json.dumps(
        [event.safe_dict() for event in parsed.events]
    )


def test_live_provider_monitor_deduplicates_partial_messages_and_includes_cache() -> None:
    monitor = ProviderTokenMonitor(1_000)

    def event(message_id: str, output_tokens: int) -> bytes:
        return json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": message_id,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": output_tokens,
                        "cache_creation_input_tokens": 20,
                        "cache_read_input_tokens": 100,
                    },
                },
            }
        ).encode()

    monitor.observe(event("message-1", 1))
    monitor.observe(event("message-1", 5))
    monitor.observe(event("message-2", 7))

    snapshot = monitor.snapshot()
    assert snapshot.input_tokens == 20
    assert snapshot.output_tokens == 12
    assert snapshot.cache_creation_input_tokens == 40
    assert snapshot.cache_read_input_tokens == 200
    assert snapshot.billed_tokens == 272
    assert monitor.exhausted() is False


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


def test_stream_parser_distinguishes_missing_mcp_inventory() -> None:
    event = {
        "type": "system",
        "subtype": "init",
        "model": "deepseek-v4-flash[1m]",
        "tools": list(CLAUDE_TOOL_NAMES[:-1]),
    }
    with pytest.raises(EventParseError, match="omitted required"):
        parse_event_stream(
            json.dumps(event),
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


def test_stream_parser_preserves_cli_synthetic_server_failure() -> None:
    events = [
        {
            "type": "system",
            "subtype": "init",
            "model": "deepseek-v4-flash[1m]",
            "tools": list(CLAUDE_TOOL_NAMES),
        },
        {"type": "system", "subtype": "api_retry", "attempt": 10},
        {
            "type": "assistant",
            "error": "server_error",
            "message": {
                "model": "<synthetic>",
                "content": [{"type": "text", "text": "request failed"}],
            },
        },
        {"type": "result", "subtype": "success", "is_error": True},
    ]
    parsed = parse_event_stream(
        "\n".join(json.dumps(event) for event in events),
        requested_model_id="deepseek-v4-flash[1m]",
        expected_context_window_tokens=1_000_000,
    )
    assert not parsed.successful
    assert parsed.observed_model_id == "deepseek-v4-flash[1m]"
    assert parsed.failure_message == "Claude assistant reported server_error"


def test_stream_parser_rejects_synthetic_failure_with_successful_result() -> None:
    events = [
        {
            "type": "system",
            "subtype": "init",
            "model": "deepseek-v4-flash[1m]",
            "tools": list(CLAUDE_TOOL_NAMES),
        },
        {
            "type": "assistant",
            "error": "server_error",
            "message": {"model": "<synthetic>", "content": []},
        },
        {"type": "result", "subtype": "success", "is_error": False},
    ]
    with pytest.raises(EventParseError, match="synthetic failure ended"):
        parse_event_stream(
            "\n".join(json.dumps(event) for event in events),
            requested_model_id="deepseek-v4-flash[1m]",
            expected_context_window_tokens=None,
        )


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
