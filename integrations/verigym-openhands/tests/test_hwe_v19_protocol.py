from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from openhands.sdk.tool import ToolDefinition

from verigym_openhands._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
)
from verigym_openhands.hwe_config import resolve_hwe_settings
from verigym_openhands.hwe_v19_protocol import (
    OPENHANDS_V19_MAX_PROVIDER_CALLS,
    OPENHANDS_V19_MAX_PROVIDER_TOKENS,
    V19ProtocolViolation,
    V19ProviderTokenBudgetExceeded,
    V19PseudoFinishViolation,
    V19RequiredToolContentRecoveryLLM,
)


def _tools() -> list[ToolDefinition[Any, Any]]:
    return cast(
        list[ToolDefinition[Any, Any]],
        [
            SimpleNamespace(name=name)
            for name in (
                "apply_patch",
                "finish",
                "inspect_diff",
                "list_files",
                "read_file",
                "shell",
            )
        ],
    )


def _messages() -> list[Message]:
    return [Message(role="user", content=[TextContent(text="Use one tool.")])]


def _response(
    tool_name: str | None,
    *,
    arguments: str = '{"summary":"done"}',
    text: str | None = None,
) -> SimpleNamespace:
    calls = (
        [
            MessageToolCall(
                id="call-1",
                name=tool_name,
                arguments=arguments,
                origin="completion",
            )
        ]
        if tool_name is not None
        else None
    )
    content = [TextContent(text=text)] if text is not None else []
    return SimpleNamespace(message=Message(role="assistant", content=content, tool_calls=calls))


def _write_recovery_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "format_id": "verigym_openhands_format_recovery_state_v1",
                "policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                "recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
                "recovery_count": 1,
                "model_visible_message_sha256": OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
                "same_session": True,
                "whole_episode_retries": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _llm(path: Path) -> V19RequiredToolContentRecoveryLLM:
    return V19RequiredToolContentRecoveryLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path=path,
        max_provider_calls=OPENHANDS_V19_MAX_PROVIDER_CALLS,
        max_provider_tokens=OPENHANDS_V19_MAX_PROVIDER_TOKENS,
    )


def test_v19_sync_requests_required_and_accepts_one_canonical_tool(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response("finish"),
    ) as completion:
        result = llm.completion(messages=_messages(), tools=_tools())

    assert result.message.tool_calls[0].name == "finish"
    assert completion.call_args.kwargs["tool_choice"] == "required"
    assert llm.required_tool_request_count == 1
    assert llm.canonical_tool_response_count == 1
    assert llm.content_only_response_count == 0


def test_v19_async_content_recovery_retains_one_prose_response(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    completion = AsyncMock(
        side_effect=[_response(None, text="I need to inspect the source."), _response("finish")]
    )
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        first = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        _write_recovery_state(state)
        second = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert first.message.tool_calls is None
    assert second.message.tool_calls[0].name == "finish"
    assert [call.kwargs["tool_choice"] for call in completion.call_args_list] == [
        "required",
        "required",
    ]
    assert llm.required_tool_request_count == 2
    assert llm.content_only_response_count == 1
    assert llm.canonical_tool_response_count == 1
    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_tool_count == 1


def test_v19_rejects_second_content_only_before_agent_dispatch(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        side_effect=[_response(None, text="First prose."), _response(None, text="Again.")],
    ):
        llm.completion(messages=_messages(), tools=_tools())
        _write_recovery_state(state)
        with pytest.raises(V19ProtocolViolation, match="second content-only"):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.required_tool_request_count == 2
    assert llm.canonical_tool_response_count == 0


def test_v19_rejects_recovery_counter_drift_without_provider_call(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _llm(state)
    with patch("openhands.sdk.llm.llm.LLM.completion", autospec=True) as completion:
        with pytest.raises(V19ProtocolViolation, match="does not match"):
            llm.completion(messages=_messages(), tools=_tools())

    completion.assert_not_called()
    assert llm.provider_call_count == 0


def test_v19_rejects_mixed_prose_and_tool_or_illegal_tool(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response("finish", text="Done."),
    ):
        with pytest.raises(V19ProtocolViolation, match="content-free tool"):
            llm.completion(messages=_messages(), tools=_tools())

    other = _llm(tmp_path / "other-recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response("foreign_tool", arguments="{}"),
    ):
        with pytest.raises(V19ProtocolViolation, match="illegal tool"):
            other.completion(messages=_messages(), tools=_tools())


def test_v19_rejects_pseudo_finish(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response("finish", arguments="{}"),
    ):
        with pytest.raises(V19PseudoFinishViolation, match="non-canonical finish"):
            llm.completion(messages=_messages(), tools=_tools())


def test_v19_over_budget_response_is_counted_but_not_accepted(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with (
        patch(
            "openhands.sdk.llm.llm.LLM.completion",
            autospec=True,
            return_value=_response("finish"),
        ),
        patch.object(
            V19RequiredToolContentRecoveryLLM,
            "_current_provider_tokens",
            return_value=OPENHANDS_V19_MAX_PROVIDER_TOKENS + 1,
        ),
    ):
        with pytest.raises(V19ProviderTokenBudgetExceeded, match="budget"):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.provider_call_count == 1
    assert llm.required_tool_request_count == 1
    assert llm.over_budget_response_count == 1
    assert llm.canonical_tool_response_count == 0


def test_v19_responses_special_turn_is_also_required(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.responses",
        autospec=True,
        return_value=_response("finish"),
    ) as responses:
        llm.responses(messages=_messages(), tools=_tools())

    assert responses.call_args.kwargs["tool_choice"] == "required"
    assert llm.required_tool_request_count == 1


def test_v19_rejects_missing_token_accounting_before_dispatch(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with (
        patch(
            "openhands.sdk.llm.llm.LLM.completion",
            autospec=True,
            return_value=_response("finish"),
        ),
        patch.object(
            V19RequiredToolContentRecoveryLLM,
            "_current_provider_tokens",
            return_value=None,
        ),
    ):
        with pytest.raises(V19ProtocolViolation, match="accounting is unavailable"):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.provider_call_count == 1
    assert llm.canonical_tool_response_count == 0


def test_v19_settings_freeze_call_token_context_and_output_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only")
    options = {
        "model_id": "openai/deepseek-v4-flash",
        "max_iterations": 64,
        "max_provider_tokens": 1_000_000,
        "max_context_tokens": 65_536,
        "max_output_tokens": 2_048,
        "tool_choice_policy": "required_tool_content_recovery_v19",
    }
    settings = resolve_hwe_settings(options, task_wall_time_s=3_600)
    assert settings.safe_dict()["max_provider_tokens"] == 1_000_000
    assert settings.safe_dict()["provider_token_accounting"] == ("post_response_pre_dispatch_v19")

    for changed in (
        {"max_iterations": 63},
        {"max_provider_tokens": 999_999},
        {"max_context_tokens": 65_535},
        {"max_output_tokens": 2_047},
    ):
        with pytest.raises(ValueError, match="v19|65536"):
            resolve_hwe_settings({**options, **changed}, task_wall_time_s=3_600)
