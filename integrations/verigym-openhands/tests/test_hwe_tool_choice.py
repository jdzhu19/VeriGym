from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from openhands.sdk.tool import FinishTool, ToolDefinition

from verigym_openhands._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_MESSAGE,
    OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
)
from verigym_openhands.hwe_tool_choice import (
    RecoveryForcedFinishLLM,
    RecoveryStateForcedFinishLLM,
    RecoveryToolChoiceViolation,
    RequiredToolChoiceLLM,
    ValidatedRecoveryStateForcedFinishLLM,
    ValidatedResponsesRecoveryStateForcedFinishLLM,
)


def _messages() -> list[Message]:
    return [Message(role="user", content=[TextContent(text="Use one tool.")])]


def _tools() -> list[ToolDefinition]:
    return list(FinishTool.create())


def _llm() -> RequiredToolChoiceLLM:
    return RequiredToolChoiceLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
    )


def _recovery_llm() -> RecoveryForcedFinishLLM:
    return RecoveryForcedFinishLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
    )


def _recovery_state_llm(path: Path) -> RecoveryStateForcedFinishLLM:
    return RecoveryStateForcedFinishLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path=path,
    )


def _validated_recovery_state_llm(path: Path) -> ValidatedRecoveryStateForcedFinishLLM:
    return ValidatedRecoveryStateForcedFinishLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path=path,
    )


def _validated_responses_recovery_state_llm(
    path: Path,
) -> ValidatedResponsesRecoveryStateForcedFinishLLM:
    return ValidatedResponsesRecoveryStateForcedFinishLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        litellm_extra_body={"thinking": {"type": "disabled"}},
        recovery_state_path=path,
    )


def _response(tool_name: str | None) -> SimpleNamespace:
    calls = (
        [
            MessageToolCall(
                id="call-1",
                name=tool_name,
                arguments="{}",
                origin="completion",
            )
        ]
        if tool_name is not None
        else None
    )
    return SimpleNamespace(message=Message(role="assistant", tool_calls=calls))


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


def _recovery_messages() -> list[Message]:
    return [
        *_messages(),
        Message(role="assistant", content=[TextContent(text="Task complete.")]),
        Message(role="user", content=[TextContent(text=OPENHANDS_FORMAT_RECOVERY_MESSAGE)]),
    ]


def _merged_recovery_messages() -> list[Message]:
    return [
        Message(role="system", content=[TextContent(text="Use tools.")]),
        Message(
            role="user",
            content=[
                TextContent(text="Original task context."),
                TextContent(text=OPENHANDS_FORMAT_RECOVERY_MESSAGE),
            ],
        ),
    ]


def test_required_tool_choice_reaches_sync_sdk_completion() -> None:
    llm = _llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == "required"


def test_required_tool_choice_reaches_async_sdk_completion() -> None:
    llm = _llm()
    completion = AsyncMock(return_value=object())
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert completion.call_args.kwargs["tool_choice"] == "required"


@pytest.mark.parametrize("choice", ["auto", "none", {"type": "function"}])
def test_required_tool_choice_cannot_be_weakened(choice: object) -> None:
    with pytest.raises(ValueError, match="cannot be weakened"):
        _llm().completion(messages=_messages(), tools=_tools(), tool_choice=choice)


def test_required_tool_choice_rejects_empty_tool_contract() -> None:
    with pytest.raises(ValueError, match="non-empty tool contract"):
        _llm().completion(messages=_messages(), tools=[])


def test_recovery_policy_keeps_normal_turn_on_auto() -> None:
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert "tool_choice" not in completion.call_args.kwargs


def test_recovery_policy_forces_exact_finish_on_trusted_feedback() -> None:
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_recovery_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_policy_forces_finish_through_async_sdk_path() -> None:
    llm = _recovery_llm()
    completion = AsyncMock(return_value=object())
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_recovery_messages(), tools=_tools()))

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_policy_accepts_sdk_merged_user_blocks() -> None:
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_merged_recovery_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_policy_rejects_feedback_that_is_not_the_final_block() -> None:
    messages = _merged_recovery_messages()
    messages[-1].content = [
        TextContent(text=OPENHANDS_FORMAT_RECOVERY_MESSAGE),
        TextContent(text="Untrusted trailing text."),
    ]
    llm = _recovery_llm()
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=messages, tools=_tools())

    assert "tool_choice" not in completion.call_args.kwargs


def test_recovery_policy_rejects_missing_finish_tool() -> None:
    with pytest.raises(ValueError, match="exactly one finish tool"):
        _recovery_llm().completion(messages=_recovery_messages(), tools=[])


def test_recovery_policy_rejects_caller_owned_tool_choice() -> None:
    with pytest.raises(ValueError, match="adapter-owned"):
        _recovery_llm().completion(
            messages=_messages(),
            tools=_tools(),
            tool_choice="required",
        )


def test_recovery_state_policy_keeps_normal_turn_on_auto(tmp_path: Path) -> None:
    llm = _recovery_state_llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert "tool_choice" not in completion.call_args.kwargs


def test_recovery_state_policy_forces_finish_after_valid_receipt(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _recovery_state_llm(state)
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=object(),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_state_policy_forces_finish_through_async_path(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _recovery_state_llm(state)
    completion = AsyncMock(return_value=object())
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }


def test_recovery_state_policy_fails_closed_on_tampered_receipt(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    state.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="state changed"):
        _recovery_state_llm(state).completion(messages=_messages(), tools=_tools())


def test_recovery_state_policy_rejects_missing_finish_after_receipt(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)

    with pytest.raises(ValueError, match="exactly one finish tool"):
        _recovery_state_llm(state).completion(messages=_messages(), tools=[])


def test_validated_recovery_policy_accepts_exact_finish_and_counts_request(
    tmp_path: Path,
) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _validated_recovery_state_llm(state)
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response("finish"),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert completion.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "finish"},
    }
    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_finish_count == 1


def test_validated_recovery_policy_counts_async_exact_finish(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _validated_recovery_state_llm(state)
    completion = AsyncMock(return_value=_response("finish"))
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_finish_count == 1


@pytest.mark.parametrize("tool_name", [None, "shell"])
def test_validated_recovery_policy_rejects_non_finish_response(
    tmp_path: Path,
    tool_name: str | None,
) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _validated_recovery_state_llm(state)
    with (
        patch(
            "openhands.sdk.llm.llm.LLM.completion",
            autospec=True,
            return_value=_response(tool_name),
        ),
        pytest.raises(RecoveryToolChoiceViolation, match="exactly one finish"),
    ):
        llm.completion(messages=_messages(), tools=_tools())

    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_finish_count == 0


def test_responses_recovery_policy_keeps_normal_turn_on_chat(tmp_path: Path) -> None:
    llm = _validated_responses_recovery_state_llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response("shell"),
    ) as completion:
        llm.completion(messages=_messages(), tools=_tools())

    assert "tool_choice" not in completion.call_args.kwargs
    assert llm.recovery_forced_request_count == 0


def test_responses_recovery_policy_uses_named_finish_and_validates(
    tmp_path: Path,
) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _validated_responses_recovery_state_llm(state)
    with patch(
        "openhands.sdk.llm.llm.LLM.responses",
        autospec=True,
        return_value=_response("finish"),
    ) as responses:
        llm.completion(messages=_messages(), tools=_tools())

    assert responses.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "name": "finish",
    }
    assert [tool.name for tool in responses.call_args.kwargs["tools"]] == ["finish"]
    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_finish_count == 1


def test_responses_recovery_policy_uses_async_responses_path(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _validated_responses_recovery_state_llm(state)
    responses = AsyncMock(return_value=_response("finish"))
    with patch("openhands.sdk.llm.llm.LLM.aresponses", responses):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert responses.call_args.kwargs["tool_choice"] == {
        "type": "function",
        "name": "finish",
    }
    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_finish_count == 1


@pytest.mark.parametrize("tool_name", [None, "shell"])
def test_responses_recovery_policy_rejects_non_finish_response(
    tmp_path: Path,
    tool_name: str | None,
) -> None:
    state = tmp_path / "recovery.json"
    _write_recovery_state(state)
    llm = _validated_responses_recovery_state_llm(state)
    with (
        patch(
            "openhands.sdk.llm.llm.LLM.responses",
            autospec=True,
            return_value=_response(tool_name),
        ),
        pytest.raises(RecoveryToolChoiceViolation, match="exactly one finish"),
    ):
        llm.completion(messages=_messages(), tools=_tools())

    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_finish_count == 0


def test_responses_recovery_rebinds_sdk_auto_choice_and_disables_thinking(
    tmp_path: Path,
) -> None:
    llm = _validated_responses_recovery_state_llm(tmp_path / "recovery.json")
    base_result = (
        None,
        [],
        [],
        {"tool_choice": "auto", "extra_body": {"thinking": {"type": "disabled"}}},
        {},
    )
    with patch(
        "openhands.sdk.llm.llm.LLM._finalize_responses_params",
        autospec=True,
        return_value=base_result,
    ):
        result = llm._finalize_responses_params(
            None,
            [],
            _tools(),
            None,
            False,
            False,
            {"tool_choice": {"type": "function", "name": "finish"}},
        )

    call_kwargs = result[3]
    assert call_kwargs["tool_choice"] == {"type": "function", "name": "finish"}
    assert call_kwargs["reasoning"] == {"effort": "none"}
    assert call_kwargs["store"] is False
    assert "extra_body" not in call_kwargs


def test_responses_recovery_coalesces_adjacent_text_outputs(tmp_path: Path) -> None:
    llm = _validated_responses_recovery_state_llm(tmp_path / "recovery.json")
    input_items = [
        {
            "type": "function_call",
            "id": "fc_call-1",
            "call_id": "call-1",
            "name": "shell",
            "arguments": "{}",
        },
        {"type": "function_call_output", "call_id": "call-1", "output": "header\n"},
        {"type": "function_call_output", "call_id": "call-1", "output": "detail"},
        {"type": "message", "role": "user", "content": []},
    ]
    base_result = (None, input_items, [], {"tool_choice": "auto"}, {})
    with patch(
        "openhands.sdk.llm.llm.LLM._finalize_responses_params",
        autospec=True,
        return_value=base_result,
    ):
        result = llm._finalize_responses_params(
            None,
            input_items,
            _tools(),
            None,
            False,
            False,
            {"tool_choice": {"type": "function", "name": "finish"}},
        )

    assert result[1] == [
        input_items[0],
        {"type": "function_call_output", "call_id": "call-1", "output": "header\ndetail"},
        input_items[3],
    ]
    assert llm.recovery_coalesced_output_count == 1


@pytest.mark.parametrize(
    "input_items",
    [
        [
            {"type": "function_call_output", "call_id": "call-1", "output": ["image"]},
        ],
        [
            {"type": "function_call_output", "call_id": "call-1", "output": "first"},
            {"type": "message", "role": "user", "content": []},
            {"type": "function_call_output", "call_id": "call-1", "output": "second"},
        ],
    ],
)
def test_responses_recovery_rejects_unsafe_output_coalescing(
    tmp_path: Path,
    input_items: list[dict[str, object]],
) -> None:
    llm = _validated_responses_recovery_state_llm(tmp_path / "recovery.json")
    base_result = (None, input_items, [], {"tool_choice": "auto"}, {})
    with (
        patch(
            "openhands.sdk.llm.llm.LLM._finalize_responses_params",
            autospec=True,
            return_value=base_result,
        ),
        pytest.raises(ValueError),
    ):
        llm._finalize_responses_params(
            None,
            input_items,
            _tools(),
            None,
            False,
            False,
            {"tool_choice": {"type": "function", "name": "finish"}},
        )


def test_responses_recovery_records_content_free_response_shape(tmp_path: Path) -> None:
    llm = _validated_responses_recovery_state_llm(tmp_path / "recovery.json")
    llm._recovery_allowed_tool_names = ("finish",)
    raw = SimpleNamespace(
        output=[
            SimpleNamespace(type="reasoning"),
            SimpleNamespace(type="function_call", name="finish"),
        ]
    )
    converted = _response("finish")
    with patch(
        "openhands.sdk.llm.llm.LLM._build_responses_result",
        autospec=True,
        return_value=converted,
    ):
        assert llm._build_responses_result(raw) is converted

    assert llm.recovery_response_shape == {
        "raw_output_count": 2,
        "raw_output_types": ["reasoning", "function_call"],
        "raw_function_names": ["finish"],
        "converted_tool_call_count": 1,
        "converted_tool_names": ["finish"],
        "converted_text_part_count": 0,
    }


def test_responses_recovery_hashes_unexpected_response_names(tmp_path: Path) -> None:
    llm = _validated_responses_recovery_state_llm(tmp_path / "recovery.json")
    llm._recovery_allowed_tool_names = ("finish",)
    raw = SimpleNamespace(output=[SimpleNamespace(type="function_call", name="untrusted-name")])
    converted = _response(None)
    with patch(
        "openhands.sdk.llm.llm.LLM._build_responses_result",
        autospec=True,
        return_value=converted,
    ):
        llm._build_responses_result(raw)

    receipt = llm.recovery_response_shape
    assert receipt["raw_function_names"] != ["untrusted-name"]
    assert receipt["raw_function_names"][0].startswith("unexpected_sha256:")
