from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from litellm import ChatCompletionMessageToolCall
from litellm.types.utils import Message as LiteLLMMessage
from openhands.sdk.llm import ImageContent, Message, MessageToolCall, TextContent
from openhands.sdk.tool import ToolDefinition

from verigym_openhands._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
)
from verigym_openhands.hwe_agent import _identity
from verigym_openhands.hwe_config import resolve_hwe_settings
from verigym_openhands.hwe_v21_protocol import (
    OPENHANDS_V21_MAX_PROVIDER_CALLS,
    OPENHANDS_V21_MAX_PROVIDER_TOKENS,
    V21ProtocolViolation,
    V21RequiredToolAtomicShapeRecoveryLLM,
)
from verigym_openhands.hwe_v22 import (
    build_v22_protocol_receipt,
    classify_v22_campaign_result,
    seal_v22_decision_receipt,
    seal_v22_trajectory_receipt,
    validate_v22_decision_receipt,
    validate_v22_protocol_receipt,
)
from verigym_openhands.hwe_v22_protocol import (
    OPENHANDS_V22_MAX_PROVIDER_CALLS,
    OPENHANDS_V22_MAX_PROVIDER_TOKENS,
    OPENHANDS_V22_MULTI_TOOL_RECOVERY_MESSAGE,
    OPENHANDS_V22_MULTI_TOOL_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_V22_TOOL_CHOICE_POLICY,
    V22ProtocolViolation,
    V22RequiredToolAtomicShapeRecoveryLLM,
)


class _CopyableResponse(SimpleNamespace):
    def model_copy(self, *, update: dict[str, Any]) -> _CopyableResponse:
        values = dict(vars(self))
        values.update(update)
        return _CopyableResponse(**values)


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
    tool_names: list[str],
    *,
    arguments: str = '{"summary":"done"}',
    text: str | None = None,
    reasoning_content: str | None = None,
) -> _CopyableResponse:
    calls = [
        MessageToolCall(
            id=f"call-{index}",
            name=name,
            arguments=arguments,
            origin="completion",
        )
        for index, name in enumerate(tool_names, start=1)
    ]
    content = [TextContent(text=text)] if text is not None else []
    return _CopyableResponse(
        message=Message(
            role="assistant",
            content=content,
            tool_calls=calls or None,
            reasoning_content=reasoning_content,
        )
    )


def _sdk_normalized_chat_response(
    tool_names: list[str],
    *,
    content: str = "",
    arguments: str = "{}",
) -> _CopyableResponse:
    message = LiteLLMMessage(
        role="assistant",
        content=content,
        tool_calls=[
            ChatCompletionMessageToolCall(
                id=f"call-{index}",
                type="function",
                function={"name": name, "arguments": arguments},
            )
            for index, name in enumerate(tool_names, start=1)
        ],
    )
    return _CopyableResponse(message=Message.from_llm_chat_message(message))


def _response_with_content(
    tool_names: list[str],
    content: list[Any],
) -> _CopyableResponse:
    response = _response(tool_names, arguments="{}")
    response.message = response.message.model_copy(update={"content": content})
    return response


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


def _llm(path: Path) -> V22RequiredToolAtomicShapeRecoveryLLM:
    return V22RequiredToolAtomicShapeRecoveryLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path=path,
        max_provider_calls=OPENHANDS_V22_MAX_PROVIDER_CALLS,
        max_provider_tokens=OPENHANDS_V22_MAX_PROVIDER_TOKENS,
    )


def _v21_llm(path: Path) -> V21RequiredToolAtomicShapeRecoveryLLM:
    return V21RequiredToolAtomicShapeRecoveryLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path=path,
        max_provider_calls=OPENHANDS_V21_MAX_PROVIDER_CALLS,
        max_provider_tokens=OPENHANDS_V21_MAX_PROVIDER_TOKENS,
    )


def _recovered_protocol_receipt() -> dict[str, Any]:
    return build_v22_protocol_receipt(
        provider={
            "provider_call_count": 3,
            "successful_provider_response_count": 3,
            "provider_usage_record_count": 3,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        protocol={
            "required_tool_request_count": 3,
            "canonical_tool_response_count": 2,
            "mixed_content_tool_response_count": 1,
            "content_only_response_count": 0,
            "multi_tool_shape_recovery_count": 1,
            "rejected_provider_tool_call_count": 2,
            "multi_tool_recovery_response_shape": {
                "classification": "tool_calls",
                "tool_call_count": 2,
                "text_part_count": 1,
                "nonempty_text_part_count": 0,
                "reasoning_content_present": False,
                "responses_reasoning_present": False,
                "thinking_blocks_present": False,
                "raw_model_content_persisted": False,
                "raw_tool_arguments_persisted": False,
            },
            "format_recovery_count": 1,
            "recovery_forced_request_count": 1,
            "recovery_validated_tool_count": 1,
            "over_budget_response_count": 0,
        },
        broker_decision_steps=2,
    )


def test_v22_atomically_replaces_exact_two_calls_before_dispatch(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    raw_arguments = '{"path":".","untrusted":"must-not-persist"}'
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_sdk_normalized_chat_response(
            ["list_files", "inspect_diff"],
            arguments=raw_arguments,
        ),
    ):
        result = llm.completion(messages=_messages(), tools=_tools())

    assert result.message.tool_calls is None
    assert result.message.content == [TextContent(text=OPENHANDS_V22_MULTI_TOOL_RECOVERY_MESSAGE)]
    assert "list_files" not in result.message.model_dump_json()
    assert "inspect_diff" not in result.message.model_dump_json()
    assert "must-not-persist" not in result.message.model_dump_json()
    assert llm.canonical_tool_response_count == 0
    assert llm.multi_tool_shape_recovery_count == 1
    assert llm.rejected_provider_tool_call_count == 2
    assert llm.multi_tool_recovery_response_shape["tool_call_count"] == 2
    assert llm.multi_tool_recovery_response_shape["text_part_count"] == 1
    assert llm.multi_tool_recovery_response_shape["nonempty_text_part_count"] == 0


def test_v22_fixes_real_sdk_empty_string_normalization_without_changing_v21(
    tmp_path: Path,
) -> None:
    response = _sdk_normalized_chat_response(["list_files", "inspect_diff"])
    assert response.message.content == [TextContent(text="")]

    v22 = _llm(tmp_path / "v22-recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=response,
    ):
        recovered = v22.completion(messages=_messages(), tools=_tools())
    assert recovered.message.tool_calls is None
    assert v22.multi_tool_shape_recovery_count == 1

    v21 = _v21_llm(tmp_path / "v21-recovery.json")
    with (
        patch(
            "openhands.sdk.llm.llm.LLM.completion",
            autospec=True,
            return_value=response,
        ),
        pytest.raises(V21ProtocolViolation, match="exactly one tool call"),
    ):
        v21.completion(messages=_messages(), tools=_tools())
    assert v21.multi_tool_shape_recovery_count == 0


@pytest.mark.parametrize(
    "content",
    [
        [TextContent(text=" ")],
        [TextContent(text=""), TextContent(text="")],
        [ImageContent(image_urls=["data:image/png;base64,AA=="])],
    ],
)
def test_v22_refuses_nonexact_empty_content_shapes(
    tmp_path: Path,
    content: list[Any],
) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with (
        patch(
            "openhands.sdk.llm.llm.LLM.completion",
            autospec=True,
            return_value=_response_with_content(
                ["list_files", "inspect_diff"],
                content,
            ),
        ),
        pytest.raises(V22ProtocolViolation, match="exactly one tool call"),
    ):
        llm.completion(messages=_messages(), tools=_tools())
    assert llm.multi_tool_shape_recovery_count == 0


def test_v22_requires_one_canonical_call_after_shape_recovery(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    completion = AsyncMock(
        side_effect=[
            _response(["list_files", "inspect_diff"], arguments="{}"),
            _response(["finish"], text="The patch is ready."),
        ]
    )
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        rejected = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        _write_recovery_state(state)
        accepted = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert rejected.message.tool_calls is None
    assert accepted.message.tool_calls is not None
    assert accepted.message.tool_calls[0].name == "finish"
    assert llm.required_tool_request_count == 2
    assert llm.canonical_tool_response_count == 1
    assert llm.multi_tool_shape_recovery_count == 1
    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_tool_count == 1


def test_v22_refuses_second_multiple_call_response(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    completion = AsyncMock(
        side_effect=[
            _response(["list_files", "inspect_diff"], arguments="{}"),
            _response(["read_file", "shell"], arguments="{}"),
        ]
    )
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        _write_recovery_state(state)
        with pytest.raises(V22ProtocolViolation, match="after recovery was consumed"):
            asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))


def test_v22_refuses_multiple_calls_with_public_text(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response(
            ["list_files", "inspect_diff"],
            arguments="{}",
            text="I will run both.",
        ),
    ):
        with pytest.raises(V22ProtocolViolation, match="exactly one tool call"):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.multi_tool_shape_recovery_count == 0


@pytest.mark.parametrize(
    ("tool_names", "reasoning_content", "error"),
    [
        (["list_files", "inspect_diff", "read_file"], None, "exactly one tool call"),
        (["list_files", "inspect_diff"], "private reasoning", "private reasoning"),
    ],
)
def test_v22_refuses_unapproved_multiple_call_shapes(
    tmp_path: Path,
    tool_names: list[str],
    reasoning_content: str | None,
    error: str,
) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response(
            tool_names,
            arguments="{}",
            reasoning_content=reasoning_content,
        ),
    ):
        with pytest.raises(V22ProtocolViolation, match=error):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.multi_tool_shape_recovery_count == 0


def test_v22_shares_one_budget_between_content_and_shape_recovery(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    completion = AsyncMock(
        side_effect=[
            _response([], text="I need to inspect the repository."),
            _response(["list_files", "inspect_diff"], arguments="{}"),
        ]
    )
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        _write_recovery_state(state)
        with pytest.raises(V22ProtocolViolation, match="after recovery was consumed"):
            asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert llm.content_only_response_count == 1
    assert llm.multi_tool_shape_recovery_count == 0


def test_v22_receipt_binds_atomic_rejection_and_masking() -> None:
    receipt = _recovered_protocol_receipt()

    assert receipt["multi_tool_shape_recovery_count"] == 1
    assert receipt["rejected_provider_tool_call_count"] == 2
    assert receipt["rejected_sibling_tool_calls_dispatched"] is False
    assert receipt["raw_rejected_provider_arguments_persisted"] is False
    assert receipt["synthetic_recovery_message_sha256"] == (
        OPENHANDS_V22_MULTI_TOOL_RECOVERY_MESSAGE_SHA256
    )
    assert receipt["synthetic_recovery_message_supervised"] is False
    assert receipt["recoverable_text_part_counts"] == [0, 1]
    assert receipt["normalized_empty_text_content_allowed"] is True
    assert receipt["nonempty_or_whitespace_text_in_shape_recovery_allowed"] is False

    changed = dict(receipt)
    changed["rejected_provider_tool_call_count"] = 1
    body = {key: value for key, value in changed.items() if key != "receipt_hash"}
    from verigym.core.hashing import content_hash

    changed["receipt_hash"] = content_hash(body)
    with pytest.raises(ValueError, match="accounting"):
        validate_v22_protocol_receipt(changed)


def test_v22_settings_freeze_exact_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only")
    settings = resolve_hwe_settings(
        {
            "model_id": "openai/deepseek-v4-flash",
            "max_iterations": 64,
            "max_provider_billed_units": 1_000_000,
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "tool_choice_policy": OPENHANDS_V22_TOOL_CHOICE_POLICY,
        },
        task_wall_time_s=3_600,
    )

    assert settings.safe_dict()["provider_token_accounting"] == ("post_response_pre_dispatch_v22")
    identity = _identity(settings, tool_calls=1, patches=0)
    assert identity.harness_id == "openhands-sdk-1.42.1-hwe-native-shell-v22"
    assert identity.tool_use_policy == (
        "repository_action_state_machine_required_tool_sdk_normalized_empty_shape_recovery_v22"
    )


def test_v22_seals_six_planes_and_exact_64k_decisions() -> None:
    protocol = _recovered_protocol_receipt()
    scorecard = {
        "task_id": "cva6-pr3231",
        "run_id": "run-v39-training",
        "resolved": True,
        "verifier_results": [
            {
                "status": "passed",
                "error_category": "success",
                "tests_passed": 3,
                "tests_total": 3,
            }
        ],
    }
    result = classify_v22_campaign_result(
        scorecard,
        agent_protocol_valid=True,
        trajectory_eligible=True,
        infrastructure_valid=True,
        security_valid=True,
        admit_to_sft=True,
    )
    transcript_hash = "a" * 64
    validated_trajectory = {
        "transcript_hash": transcript_hash,
        "format_recovery_count": 1,
        "assistant_decision_count": 2,
        "format_recoveries": [{"assistant_message_index": 2}],
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": OPENHANDS_V22_MULTI_TOOL_RECOVERY_MESSAGE,
            },
        ],
    }
    with patch(
        "verigym_openhands.hwe_v22.validate_openhands_training_trajectory",
        return_value=validated_trajectory,
    ):
        trajectory = seal_v22_trajectory_receipt(
            trajectory=validated_trajectory,
            protocol_receipt=protocol,
            campaign_result=result,
        )
    decision = seal_v22_decision_receipt(
        records=[
            {
                "record_hash": "b" * 64,
                "transcript_hash": transcript_hash,
                "eligible": True,
                "truncation": "error",
                "input_loss_masked": True,
                "token_count": 65_536,
            }
        ],
        trajectory_receipt=trajectory,
    )

    assert result["sft_admitted"] is True
    assert trajectory["synthetic_shape_recovery_assistant_loss_mask"] == 0
    assert decision["maximum_token_count"] == 65_536
    assert decision["synthetic_shape_recovery_assistant_supervised"] is False
    assert validate_v22_decision_receipt(decision) == decision

    changed = dict(validated_trajectory)
    changed["messages"] = [
        *validated_trajectory["messages"][:2],
        {"role": "assistant", "content": "changed"},
    ]
    with (
        patch(
            "verigym_openhands.hwe_v22.validate_openhands_training_trajectory",
            return_value=changed,
        ),
        pytest.raises(ValueError, match="synthetic recovery binding"),
    ):
        seal_v22_trajectory_receipt(
            trajectory=changed,
            protocol_receipt=protocol,
            campaign_result=result,
        )
