from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from openhands.sdk.agent.parallel_executor import ParallelToolExecutor
from openhands.sdk.conversation.stuck_detector import StuckDetector
from openhands.sdk.event import ActionEvent, ObservationEvent
from openhands.sdk.llm import Message, MessageToolCall, TextContent
from openhands.sdk.mcp.definition import MCPToolObservation
from openhands.sdk.tool import ToolDefinition
from openhands.sdk.tool.schema import Action
from pydantic import Field
from verigym.core.hashing import content_hash
from verigym_deepseek_harness.broker import openhands_v23_progress_gate_state

from verigym_openhands._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
)
from verigym_openhands.hwe_agent import _system_prompt, _v23_terminal_behavior_failure
from verigym_openhands.hwe_config import resolve_hwe_settings
from verigym_openhands.hwe_v23 import (
    build_v23_protocol_receipt,
    seal_v23_progress_receipt,
    validate_v23_progress_receipt,
    validate_v23_protocol_receipt,
)
from verigym_openhands.hwe_v23_protocol import (
    OPENHANDS_V23_MAX_PROVIDER_CALLS,
    OPENHANDS_V23_MAX_PROVIDER_TOKENS,
    OPENHANDS_V23_TOOL_CHOICE_POLICY,
    V23AutoPublicThoughtAtomicRecoveryLLM,
    V23ProtocolViolation,
    V23PseudoFinishViolation,
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
    return [Message(role="user", content=[TextContent(text="Repair the visible task.")])]


def _response(
    calls: list[tuple[str, dict[str, Any] | str]],
    *,
    text: str | None = None,
    reasoning_content: str | None = None,
) -> SimpleNamespace:
    tool_calls = [
        MessageToolCall(
            id=f"call-{index}",
            name=name,
            arguments=(
                arguments
                if isinstance(arguments, str)
                else json.dumps(arguments, separators=(",", ":"))
            ),
            origin="completion",
        )
        for index, (name, arguments) in enumerate(calls, start=1)
    ]
    return SimpleNamespace(
        message=Message(
            role="assistant",
            content=[TextContent(text=text)] if text is not None else [],
            tool_calls=tool_calls or None,
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


def _llm(path: Path) -> V23AutoPublicThoughtAtomicRecoveryLLM:
    return V23AutoPublicThoughtAtomicRecoveryLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path=path,
        max_provider_calls=OPENHANDS_V23_MAX_PROVIDER_CALLS,
        max_provider_tokens=OPENHANDS_V23_MAX_PROVIDER_TOKENS,
    )


def test_v23_ordinary_request_omits_tool_choice_and_keeps_public_siblings(
    tmp_path: Path,
) -> None:
    llm = _llm(tmp_path / "recovery.json")
    response = _response(
        [("list_files", {}), ("read_file", {"path": "rtl/core.sv"})],
        text="Hypothesis: the defect is in rtl/core.sv; inspect the root and source.",
    )
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=response,
    ) as completion:
        result = llm.completion(messages=_messages(), tools=_tools())

    assert "tool_choice" not in completion.call_args.kwargs
    assert result.message.content == response.message.content
    assert [call.name for call in result.message.tool_calls] == ["list_files", "read_file"]
    assert llm.ordinary_auto_request_count == 1
    assert llm.required_tool_request_count == 0
    assert llm.canonical_tool_decision_count == 1
    assert llm.canonical_tool_call_count == 2
    assert llm.public_text_decision_count == 1
    assert llm.sibling_tool_decision_count == 1
    assert llm.decision_tool_call_counts == (2,)


def test_v23_invalid_sibling_rejects_the_whole_decision_before_dispatch(
    tmp_path: Path,
) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response(
            [("list_files", {}), ("read_file", {"path": "../hidden"})],
            text="Inspect both paths.",
        ),
    ):
        with pytest.raises(V23ProtocolViolation, match="non-canonical tool arguments"):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.canonical_tool_decision_count == 0
    assert llm.canonical_tool_call_count == 0
    assert llm.sibling_tool_decision_count == 0
    assert llm.decision_tool_call_counts == ()


def test_v23_only_the_one_same_session_recovery_uses_required(tmp_path: Path) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    completion = AsyncMock(
        side_effect=[
            _response([], text="I need one tool call to continue."),
            _response([("inspect_diff", {})], text="Now inspect the candidate."),
            _response([("finish", {"summary": "done"})], text="Validation is complete."),
        ]
    )
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        first = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        _write_recovery_state(state)
        second = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        third = asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert first.message.tool_calls is None
    assert second.message.tool_calls[0].name == "inspect_diff"
    assert third.message.tool_calls[0].name == "finish"
    assert "tool_choice" not in completion.call_args_list[0].kwargs
    assert completion.call_args_list[1].kwargs["tool_choice"] == "required"
    assert "tool_choice" not in completion.call_args_list[2].kwargs
    assert llm.ordinary_auto_request_count == 2
    assert llm.required_tool_request_count == 1
    assert llm.content_only_response_count == 1
    assert llm.recovery_forced_request_count == 1
    assert llm.recovery_validated_tool_count == 1


def test_v23_recovery_refuses_siblings_and_does_not_drift_back_to_auto(
    tmp_path: Path,
) -> None:
    state = tmp_path / "recovery.json"
    llm = _llm(state)
    completion = AsyncMock(
        side_effect=[
            _response([], text="Need a tool."),
            _response([("list_files", {}), ("inspect_diff", {})]),
        ]
    )
    with patch("openhands.sdk.llm.llm.LLM.acompletion", completion):
        asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))
        _write_recovery_state(state)
        with pytest.raises(V23ProtocolViolation, match="exactly one tool call"):
            asyncio.run(llm.acompletion(messages=_messages(), tools=_tools()))

    assert completion.call_args_list[1].kwargs["tool_choice"] == "required"
    assert llm.canonical_tool_decision_count == 0


@pytest.mark.parametrize(
    ("calls", "reasoning", "error"),
    [
        ([("foreign_tool", {})], None, "illegal tool"),
        ([("shell", {"command": "FOO=bar make"})], None, "non-canonical"),
        (
            [("finish", {"summary": "done"})],
            "private chain of thought",
            "private reasoning",
        ),
    ],
)
def test_v23_private_reasoning_foreign_tools_and_unsafe_arguments_fail_closed(
    tmp_path: Path,
    calls: list[tuple[str, dict[str, Any] | str]],
    reasoning: str | None,
    error: str,
) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response(calls, reasoning_content=reasoning),
    ):
        with pytest.raises(V23ProtocolViolation, match=error):
            llm.completion(messages=_messages(), tools=_tools())

    assert llm.canonical_tool_decision_count == 0
    assert llm.provider_response_shape["raw_model_content_persisted"] is False
    assert llm.provider_response_shape["raw_tool_arguments_persisted"] is False


def test_v23_finish_cannot_be_a_sibling(tmp_path: Path) -> None:
    llm = _llm(tmp_path / "recovery.json")
    with patch(
        "openhands.sdk.llm.llm.LLM.completion",
        autospec=True,
        return_value=_response([("inspect_diff", {}), ("finish", {"summary": "done"})]),
    ):
        with pytest.raises(V23PseudoFinishViolation, match="cannot have sibling"):
            llm.completion(messages=_messages(), tools=_tools())


def test_v23_settings_keep_exact_budgets_and_post_response_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERIGYM_MODEL_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("VERIGYM_MODEL_API_KEY", "test-only")

    settings = resolve_hwe_settings(
        {
            "model_id": "openai/deepseek-v4-flash",
            "max_iterations": 64,
            "max_provider_billed_units": 1_000_000,
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "tool_choice_policy": OPENHANDS_V23_TOOL_CHOICE_POLICY,
        },
        task_wall_time_s=3_600,
    )

    safe = settings.safe_dict()
    assert safe["provider_token_accounting"] == "post_response_pre_dispatch_v23"
    assert safe["termination_authority"] == ("broker_typed_finish_or_v23_progress_or_sdk_stuck")
    assert safe["ordinary_tool_choice"] == "provider_default_auto_omitted"
    assert safe["recovery_tool_choice"] == "required"
    assert safe["stuck_detection_enabled"] is True
    assert safe["pre_edit_checkpoint_action"] == 16
    assert safe["pre_edit_no_progress_action"] == 32


def test_v23_prompt_allows_public_rationale_and_siblings_without_changing_history() -> None:
    historical = _system_prompt()
    v23 = _system_prompt(workspace_relative=True, v23_public_decisions=True)

    assert "exactly one typed tool call" in historical
    assert "exactly one typed tool call" not in v23
    assert "concise public rationale" in v23
    assert "Independent sibling calls" in v23
    assert "do not reveal hidden chain of thought" in v23


def test_v23_no_progress_and_stuck_precede_missing_protocol_receipt() -> None:
    no_progress = _v23_terminal_behavior_failure(
        tool_choice_policy=OPENHANDS_V23_TOOL_CHOICE_POLICY,
        progress_receipt={"no_progress_terminated": True},
        stuck_status="not_stuck",
        protocol_failure=True,
        protocol_receipt=None,
    )
    stuck = _v23_terminal_behavior_failure(
        tool_choice_policy=OPENHANDS_V23_TOOL_CHOICE_POLICY,
        progress_receipt={"no_progress_terminated": False},
        stuck_status="stuck",
        protocol_failure=True,
        protocol_receipt=None,
    )

    assert no_progress is not None and no_progress[0] == "openhands_hwe_v23_no_progress"
    assert stuck is not None and stuck[0] == "openhands_hwe_v23_stuck"


def test_v23_protocol_receipt_seals_sibling_progress_stuck_and_observation_hashes() -> None:
    observation = [
        {
            "sequence": index,
            "raw_sha256": hashlib.sha256(f"raw-{index}".encode()).hexdigest(),
            "raw_bytes": 10 + index,
            "compact_sha256": hashlib.sha256(f"compact-{index}".encode()).hexdigest(),
            "compact_tokens": 20 + index,
            "rule_id": "hwe_repository_observation_v2/read_v23",
            "omitted": index == 0,
        }
        for index in range(3)
    ]
    progress = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_v23_progress_observation_receipt_v1",
        "first_effective_modification_action": 2,
        "progress_checkpoint_action": None,
        "progress_checkpoint_injected": False,
        "progress_checkpoint_sha256": hashlib.sha256(b"checkpoint").hexdigest(),
        "no_progress_action": None,
        "no_progress_terminated": False,
        "progress_gate_state": "released_after_modification",
        "observation_compaction": observation,
    }
    sealed_progress = seal_v23_progress_receipt(progress)
    assert validate_v23_progress_receipt(sealed_progress) == sealed_progress

    receipt = build_v23_protocol_receipt(
        provider={
            "provider_call_count": 3,
            "successful_provider_response_count": 3,
            "provider_usage_record_count": 3,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        protocol={
            "ordinary_auto_request_count": 2,
            "required_tool_request_count": 1,
            "canonical_tool_decision_count": 2,
            "canonical_tool_call_count": 3,
            "public_text_decision_count": 1,
            "content_only_response_count": 1,
            "format_recovery_count": 1,
            "recovery_validated_tool_count": 1,
            "over_budget_response_count": 0,
            "decision_tool_call_counts": [2, 1],
            "sibling_tool_decision_count": 1,
            "sibling_tool_call_count": 2,
        },
        broker={"tool_calls": 3, "decision_steps": 2, "finished": True},
        progress=progress,
        stuck_status="not_stuck",
    )

    assert validate_v23_protocol_receipt(receipt) == receipt
    assert receipt["ordinary_tool_choice_serialization"] == "provider_default_omitted"
    assert receipt["decision_tool_call_counts"] == [2, 1]
    assert receipt["observation_omission_count"] == 1
    assert receipt["progress_observation_receipt_hash"] == sealed_progress["receipt_hash"]


class _ReplayAction(Action):
    sequence: int = Field(ge=0)


class _ReplayState:
    def __init__(self, events: list[Any]) -> None:
        self.events = events

    def active_branch(self, limit: int | None = None) -> list[Any]:
        return self.events[-limit:] if limit is not None else list(self.events)


def test_v23_read_only_replay_does_not_misclassify_three_archived_success_sequences() -> None:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "verigym-deepseek-harness/tests/fixtures/openhands_v23_archived_progress_replay_v1.json"
    )
    replay = json.loads(fixture.read_text(encoding="utf-8"))
    replay_hash = replay.pop("replay_hash")
    assert replay_hash == content_hash(replay)
    assert replay["replay_mode"] == "content_free_read_only"
    assert replay["provider_calls_during_replay"] == 0
    assert replay["model_process_count"] == 0
    assert replay["historical_trajectory_relabelled"] is False
    assert replay["historical_trajectory_rewritten"] is False
    assert len(replay["sequences"]) == 3

    allowed = {"apply_patch", "finish", "inspect_diff", "list_files", "read_file", "shell"}
    for sequence in replay["sequences"]:
        actions = sequence["actions"]
        modifications = sequence["effective_modification_actions"]
        assert actions and actions[-1] == "finish"
        assert set(actions) <= allowed
        assert modifications == sorted(set(modifications))
        assert all(1 <= action <= len(actions) for action in modifications)
        gate = openhands_v23_progress_gate_state(
            action_count=len(actions),
            first_effective_modification_action=modifications[0] if modifications else None,
        )
        assert (
            gate["progress_checkpoint_injected"]
            is sequence["expected_progress_checkpoint_injected"]
        )
        assert gate["no_progress_terminated"] is sequence["expected_no_progress_terminated"]

        sdk_events: list[Any] = []
        for index, name in enumerate(actions):
            call_id = f"{sequence['identity']}-{index}"
            action = ActionEvent(
                thought=[],
                action=_ReplayAction(sequence=index),
                tool_name=name,
                tool_call_id=call_id,
                tool_call=MessageToolCall(
                    id=call_id,
                    name=name,
                    arguments=json.dumps({"sequence": index}),
                    origin="completion",
                ),
                llm_response_id=f"response-{call_id}",
            )
            sdk_events.extend(
                [
                    action,
                    ObservationEvent(
                        tool_name=name,
                        tool_call_id=call_id,
                        observation=MCPToolObservation(
                            content=[TextContent(text=f"receipt-{index}")],
                            is_error=False,
                            tool_name=name,
                        ),
                        action_id=action.id,
                    ),
                ]
            )
        assert StuckDetector(_ReplayState(sdk_events)).is_stuck() is False  # type: ignore[arg-type]
        assert sequence["expected_stuck_status"] == "not_stuck"


def test_sdk_1421_executor_serializes_siblings_in_input_order() -> None:
    execution_order: list[str] = []
    actions = [SimpleNamespace(tool_name="first"), SimpleNamespace(tool_name="second")]

    results = ParallelToolExecutor(max_workers=1).execute_batch(
        actions,  # type: ignore[arg-type]
        lambda action: execution_order.append(action.tool_name) or [action.tool_name],
    )

    assert execution_order == ["first", "second"]
    assert results == [["first"], ["second"]]
