from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from verigym.core.hashing import content_hash
from verigym.evolution.training_transcript import (
    build_teacher_transcript,
    validate_teacher_transcript,
)
from verigym.protocols.repository_action import (
    canonical_tool_observation,
    repository_tool_definitions,
)
from verigym.schemas.multiturn_sft import (
    MultiTurnSftMessage,
    VerifiedMultiTurnSftExample,
    seal_multi_turn_example,
)

_HASH = "a" * 64


def _messages() -> list[MultiTurnSftMessage]:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    return [
        MultiTurnSftMessage(role="system", content="Use only repository tools."),
        MultiTurnSftMessage(role="user", content="Repair the visible module."),
        MultiTurnSftMessage.model_validate(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_finish_1",
                        "type": "function",
                        "function": {
                            "name": "finish",
                            "arguments": '{"message":"done"}',
                        },
                    }
                ],
            }
        ),
        MultiTurnSftMessage(
            role="tool",
            name="finish",
            tool_call_id="call_finish_1",
            content=observation,
        ),
        MultiTurnSftMessage(role="assistant", content="The candidate is ready."),
    ]


def _example_payload() -> dict[str, object]:
    return {
        "sample_id": _HASH,
        "task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
        "official_task_id": "openhwgroup/cva6:pr-2032",
        "task_hash": _HASH,
        "source_hash": "b" * 64,
        "candidate_hash": "c" * 64,
        "verifier_hash": "d" * 64,
        "provider": "anthropic-compatible",
        "model_id": "deepseek-v4-flash[1m]",
        "reasoning_effort": "max",
        "client_kind": "cli",
        "client_name": "claude-code",
        "client_version": "1.2.3",
        "prompt_hash": "e" * 64,
        "tool_contract_hash": content_hash(repository_tool_definitions(dialect="openai")),
        "harness_hash": "f" * 64,
        "tokenizer_hash": "0" * 64,
        "messages": _messages(),
        "token_count": 123,
    }


def test_tool_schemas_are_derived_identically_for_openai_and_mcp() -> None:
    openai = repository_tool_definitions(dialect="openai")
    mcp = repository_tool_definitions(dialect="mcp")

    assert (
        [entry["function"]["name"] for entry in openai]
        == [entry["name"] for entry in mcp]
        == ["apply_patch", "finish", "inspect_diff", "list_files", "read_file", "run_public_test"]
    )
    assert [entry["function"]["parameters"] for entry in openai] == [
        entry["inputSchema"] for entry in mcp
    ]
    apply_patch = next(entry for entry in openai if entry["function"]["name"] == "apply_patch")
    assert "*** Update File" in apply_patch["function"]["description"]


def test_assistant_text_may_accompany_a_canonical_tool_call() -> None:
    message = MultiTurnSftMessage.model_validate(
        {
            "role": "assistant",
            "content": "Submitting the bounded candidate.",
            "tool_calls": [
                {
                    "id": "call_finish_with_text",
                    "type": "function",
                    "function": {"name": "finish", "arguments": '{"message":"done"}'},
                }
            ],
        }
    )

    assert message.content == "Submitting the bounded candidate."
    assert message.tool_calls is not None


def test_teacher_capture_is_training_only_and_tamper_evident() -> None:
    transcript = build_teacher_transcript(
        campaign_role="training",
        task_id="suite/task",
        provider="provider",
        model_id="model",
        reasoning_effort="max",
        client_kind="cli",
        client_name="client",
        client_version="1",
        harness_identity={"kind": "test"},
        messages=_messages(),
    )

    assert validate_teacher_transcript(transcript) == transcript
    tampered = {**transcript, "model_id": "other"}
    with pytest.raises(ValueError, match="identity changed"):
        validate_teacher_transcript(tampered)
    with pytest.raises(ValueError, match="only for the training split"):
        build_teacher_transcript(
            campaign_role="heldout",
            task_id="suite/task",
            provider="provider",
            model_id="model",
            reasoning_effort="max",
            client_kind="cli",
            client_name="client",
            client_version="1",
            harness_identity={},
            messages=_messages(),
        )


def test_multiturn_example_masks_only_non_assistant_roles_and_seals_identity() -> None:
    example = seal_multi_turn_example(_example_payload())

    assert example.supervised_roles == ("assistant",)
    assert example.masked_roles == ("system", "user", "tool")
    assert example.truncation == "error"
    assert example.private_reasoning_exported is False
    assert example.reference_solutions_exported is False
    assert VerifiedMultiTurnSftExample.model_validate_json(example.model_dump_json()) == example

    changed = example.model_dump(mode="json")
    changed["messages"][-1]["content"] = "changed"
    with pytest.raises(ValidationError, match="identity changed"):
        VerifiedMultiTurnSftExample.model_validate(changed)


def test_multiturn_example_rejects_duplicate_ids_host_paths_and_over_16k() -> None:
    payload = _example_payload()
    payload["token_count"] = 16_385
    with pytest.raises(ValidationError):
        seal_multi_turn_example(payload)

    host_path = _example_payload()
    messages = [message.model_dump(mode="json", exclude_none=True) for message in _messages()]
    messages[-1]["content"] = "read /home/user/private"
    host_path["messages"] = messages
    with pytest.raises(ValidationError, match="forbidden"):
        seal_multi_turn_example(host_path)

    host_path_argument = _example_payload()
    messages = [message.model_dump(mode="json", exclude_none=True) for message in _messages()]
    messages[2]["tool_calls"][0]["function"]["arguments"] = (  # type: ignore[index]
        '{"message":"inspect /data/private"}'
    )
    host_path_argument["messages"] = messages
    with pytest.raises(ValidationError, match="forbidden"):
        seal_multi_turn_example(host_path_argument)

    duplicate = _example_payload()
    messages = [message.model_dump(mode="json", exclude_none=True) for message in _messages()]
    messages.insert(4, messages[2])
    messages.insert(5, messages[3])
    duplicate["messages"] = messages
    with pytest.raises(ValidationError, match="unique"):
        seal_multi_turn_example(duplicate)


def test_observation_must_be_canonical_and_match_call_id() -> None:
    payload = _example_payload()
    messages = [message.model_dump(mode="json", exclude_none=True) for message in _messages()]
    messages[3]["tool_call_id"] = "call_other"
    payload["messages"] = messages
    with pytest.raises(ValidationError, match="does not match"):
        seal_multi_turn_example(payload)

    payload = _example_payload()
    messages = [message.model_dump(mode="json", exclude_none=True) for message in _messages()]
    messages[3]["content"] = json.dumps(json.loads(messages[3]["content"]), indent=2)
    payload["messages"] = messages
    with pytest.raises(ValidationError, match="canonical"):
        seal_multi_turn_example(payload)


def test_trajectory_requires_an_accepted_terminal_finish_as_the_last_tool() -> None:
    payload = _example_payload()
    messages = [message.model_dump(mode="json", exclude_none=True) for message in _messages()]
    messages[3]["content"] = canonical_tool_observation(
        "finish", {"message": "not ready"}, is_error=True
    )
    payload["messages"] = messages
    with pytest.raises(ValidationError, match="accepted and terminal"):
        seal_multi_turn_example(payload)

    payload = _example_payload()
    messages = [message.model_dump(mode="json", exclude_none=True) for message in _messages()]
    messages.insert(
        -1,
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_list_after_finish",
                    "type": "function",
                    "function": {
                        "name": "list_files",
                        "arguments": '{"path":".","recursive":true}',
                    },
                }
            ],
        },
    )
    messages.insert(
        -1,
        {
            "role": "tool",
            "name": "list_files",
            "tool_call_id": "call_list_after_finish",
            "content": canonical_tool_observation("list_files", {"files": []}, is_error=False),
        },
    )
    payload["messages"] = messages
    with pytest.raises(ValidationError, match="finish, its observation"):
        seal_multi_turn_example(payload)
