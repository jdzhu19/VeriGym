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
from verigym_openhands.hwe_v20 import (
    build_v20_protocol_receipt,
    classify_v20_campaign_result,
    seal_v20_decision_receipt,
    seal_v20_trajectory_receipt,
    validate_v20_decision_receipt,
)
from verigym_openhands.hwe_v20_protocol import (
    OPENHANDS_V20_MAX_PROVIDER_CALLS,
    OPENHANDS_V20_MAX_PROVIDER_TOKENS,
    OPENHANDS_V20_TOOL_CHOICE_POLICY,
    V20ProtocolViolation,
    V20RequiredToolPublicThoughtLLM,
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
    tool_names: list[str],
    *,
    arguments: str = '{"summary":"done"}',
    text: str | None = None,
    reasoning_content: str | None = None,
) -> SimpleNamespace:
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
    return SimpleNamespace(
        message=Message(
            role="assistant",
            content=content,
            tool_calls=calls or None,
            reasoning_content=reasoning_content,
        )
    )


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


def _llm(path: Path) -> V20RequiredToolPublicThoughtLLM:
    return V20RequiredToolPublicThoughtLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path=path,
        max_provider_calls=OPENHANDS_V20_MAX_PROVIDER_CALLS,
        max_provider_tokens=OPENHANDS_V20_MAX_PROVIDER_TOKENS,
    )


def test_v20_accepts_one_canonical_tool_with_public_thought(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response(["finish"], text="The patch is ready."),
    ) as completion:
        result = llm.completion(messages=_messages(), tools=_tools())

    assert result.message.tool_calls[0].name == "finish"
    assert result.message.content == [TextContent(text="The patch is ready.")]
    assert completion.call_args.kwargs["tool_choice"] == "required"
    assert llm.required_tool_request_count == 1
    assert llm.canonical_tool_response_count == 1
    assert llm.mixed_content_tool_response_count == 1
    assert llm.content_free_tool_response_count == 0
    assert llm.provider_response_shape == {
        "classification": "tool_calls_with_content",
        "tool_call_count": 1,
        "text_part_count": 1,
        "nonempty_text_part_count": 1,
        "reasoning_content_present": False,
        "responses_reasoning_present": False,
        "thinking_blocks_present": False,
        "raw_model_content_persisted": False,
        "raw_tool_arguments_persisted": False,
    }


def test_v20_rejects_multiple_tool_calls_before_dispatch(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response(["list_files", "finish"], arguments="{}"),
    ):
        with pytest.raises(V20ProtocolViolation, match="exactly one tool call"):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.provider_response_shape["tool_call_count"] == 2
    assert llm.canonical_tool_response_count == 0


def test_v20_rejects_private_reasoning_but_records_only_its_presence(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response(
            ["finish"],
            text="The patch is ready.",
            reasoning_content="private reasoning must not enter the transcript",
        ),
    ):
        with pytest.raises(V20ProtocolViolation, match="private reasoning"):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.provider_response_shape["reasoning_content_present"] is True
    assert llm.provider_response_shape["raw_model_content_persisted"] is False
    assert llm.canonical_tool_response_count == 0


def test_v20_keeps_one_content_only_same_session_recovery(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    completion = AsyncMock(
        side_effect=[
            _response([], text="I need to inspect the source."),
            _response(["finish"], text="Now complete."),
        ]
    )
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        first = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        _write_recovery_state(state)
        second = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert first.message.tool_calls is None
    assert second.message.tool_calls[0].name == "finish"
    assert llm.required_tool_request_count == 2
    assert llm.content_only_response_count == 1
    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_tool_count == 1
    assert llm.mixed_content_tool_response_count == 1


def test_v20_receipt_accounts_mixed_and_content_free_tool_responses() -> None:
    receipt = build_v20_protocol_receipt(
        provider={
            "provider_call_count": 3,
            "successful_provider_response_count": 3,
            "provider_usage_record_count": 3,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        protocol={
            "required_tool_request_count": 3,
            "canonical_tool_response_count": 3,
            "mixed_content_tool_response_count": 2,
            "content_only_response_count": 0,
            "format_recovery_count": 0,
            "recovery_forced_request_count": 0,
            "recovery_validated_tool_count": 0,
            "over_budget_response_count": 0,
        },
        broker_decision_steps=3,
    )

    assert receipt["content_free_tool_response_count"] == 1
    assert receipt["mixed_content_tool_response_count"] == 2
    assert receipt["public_tool_thought_supervised"] is True


def test_v20_settings_freeze_exact_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only")
    settings = resolve_hwe_settings(
        {
            "model_id": "openai/deepseek-v4-flash",
            "max_iterations": 64,
            "max_provider_billed_units": 1_000_000,
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "tool_choice_policy": OPENHANDS_V20_TOOL_CHOICE_POLICY,
        },
        task_wall_time_s=3_600,
    )

    assert settings.safe_dict()["provider_token_accounting"] == ("post_response_pre_dispatch_v20")


def test_v20_seals_six_planes_and_exact_64k_public_thought_decisions() -> None:
    protocol = build_v20_protocol_receipt(
        provider={
            "provider_call_count": 2,
            "successful_provider_response_count": 2,
            "provider_usage_record_count": 2,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        protocol={
            "required_tool_request_count": 2,
            "canonical_tool_response_count": 2,
            "mixed_content_tool_response_count": 1,
            "content_only_response_count": 0,
            "format_recovery_count": 0,
            "recovery_forced_request_count": 0,
            "recovery_validated_tool_count": 0,
            "over_budget_response_count": 0,
        },
        broker_decision_steps=2,
    )
    scorecard = {
        "task_id": "cva6-pr3226",
        "run_id": "run-v37-training",
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
    result = classify_v20_campaign_result(
        scorecard,
        agent_protocol_valid=True,
        trajectory_eligible=True,
        infrastructure_valid=True,
        security_valid=True,
        admit_to_sft=True,
    )
    transcript_hash = "a" * 64
    trajectory = seal_v20_trajectory_receipt(
        transcript_hash=transcript_hash,
        protocol_receipt=protocol,
        campaign_result=result,
    )
    decision = seal_v20_decision_receipt(
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
    assert trajectory["public_tool_thought_loss_mask"] == 1
    assert decision["maximum_token_count"] == 65_536
    assert decision["public_tool_thought_supervised"] is True
    assert validate_v20_decision_receipt(decision) == decision


def test_v20_refuses_sft_admission_when_a_result_plane_fails() -> None:
    result = classify_v20_campaign_result(
        {
            "task_id": "cva6-pr3226",
            "run_id": "run-v37-training",
            "resolved": False,
            "verifier_results": [
                {
                    "status": "failed",
                    "error_category": "tests_failed",
                    "tests_passed": 2,
                    "tests_total": 3,
                }
            ],
        },
        agent_protocol_valid=True,
        trajectory_eligible=True,
        infrastructure_valid=True,
        security_valid=True,
        admit_to_sft=True,
    )

    assert result["benchmark_verifier_pass"] is False
    assert result["sft_admitted"] is False
