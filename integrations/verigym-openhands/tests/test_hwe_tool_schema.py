from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from verigym_openhands._hwe_tool_schema import without_openhands_tool_metadata
from verigym_openhands.hwe_tool_choice import (
    MetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM,
    ProviderToolArgumentsPolicyError,
    ValidatedResponsesRecoveryStateRequiredToolLLM,
)
from verigym_openhands.trajectory import snapshot_openhands_tools


def _provider_tools(*, responses: bool = False) -> list[dict[str, Any]]:
    values = [
        {
            "name": "shell",
            "description": "run a command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "summary": {"type": "string"},
                    "security_risk": {"enum": ["LOW", "HIGH"], "type": "string"},
                },
                "required": ["command", "summary", "security_risk"],
                "additionalProperties": False,
            },
        },
        {
            "name": "finish",
            "description": "finish",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "security_risk": {"enum": ["LOW", "HIGH"], "type": "string"},
                },
                "required": ["summary", "security_risk"],
                "additionalProperties": False,
            },
        },
    ]
    if responses:
        return [{"type": "function", **value} for value in values]
    return [{"type": "function", "function": value} for value in values]


def _metadata_free_llm() -> MetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM:
    return MetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM(
        model="openai/test-model",
        api_key="test-only",
        base_url="https://example.invalid/v1",
        api_mode="chat",
        native_tool_calling=True,
        capability_overrides={"supports_responses_api": False},
        recovery_state_path="/not-read-by-this-test",
    )


@pytest.mark.parametrize("responses", [False, True])
def test_metadata_normalization_keeps_only_semantic_finish_summary(responses: bool) -> None:
    original = _provider_tools(responses=responses)
    normalized = without_openhands_tool_metadata(original)

    assert original == _provider_tools(responses=responses)
    shell_parameters = (
        normalized[0]["parameters"] if responses else normalized[0]["function"]["parameters"]
    )
    finish_parameters = (
        normalized[1]["parameters"] if responses else normalized[1]["function"]["parameters"]
    )
    assert shell_parameters["properties"] == {"command": {"type": "string"}}
    assert shell_parameters["required"] == ["command"]
    assert finish_parameters["properties"] == {"summary": {"type": "string"}}
    assert finish_parameters["required"] == ["summary"]


def test_metadata_normalization_rejects_malformed_provider_schema() -> None:
    with pytest.raises(ValueError, match="malformed"):
        without_openhands_tool_metadata([{"type": "function"}])


def test_metadata_free_llm_rebinds_chat_and_responses_schemas() -> None:
    llm = _metadata_free_llm()
    chat_tools = _provider_tools()
    chat_result = ([], chat_tools, False, {"tools": deepcopy(chat_tools)}, {"route": "chat"})
    responses_tools = _provider_tools(responses=True)
    responses_result = (
        None,
        [],
        responses_tools,
        {"tool_choice": "required"},
        {"route": "responses"},
    )
    with (
        patch.object(
            ValidatedResponsesRecoveryStateRequiredToolLLM,
            "_finalize_completion_params",
            autospec=True,
            return_value=chat_result,
        ),
        patch.object(
            ValidatedResponsesRecoveryStateRequiredToolLLM,
            "_finalize_responses_params",
            autospec=True,
            return_value=responses_result,
        ),
    ):
        chat = llm._finalize_completion_params([], [], True, {})
        responses = llm._finalize_responses_params(None, [], [], None, False, True, {})

    assert chat[1] == without_openhands_tool_metadata(chat_tools)
    assert chat[3]["tools"] == chat[1]
    assert responses[2] == without_openhands_tool_metadata(responses_tools)


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("shell", '{"command":"pwd","summary":"inspect /data/private"}', "raw host path"),
        ("shell", '{"command":"pwd","summary":"inspect files"}', "forbidden SDK"),
        ("read_file", '{"path":"rtl/top.sv","security_risk":"LOW"}', "forbidden SDK"),
    ],
)
def test_metadata_free_llm_rejects_sdk_metadata_before_agent_execution(
    name: str, arguments: str, message: str
) -> None:
    llm = _metadata_free_llm()
    response = SimpleNamespace(
        message=SimpleNamespace(tool_calls=[SimpleNamespace(name=name, arguments=arguments)])
    )
    with (
        patch.object(
            ValidatedResponsesRecoveryStateRequiredToolLLM,
            "completion",
            autospec=True,
            return_value=response,
        ),
        pytest.raises(ProviderToolArgumentsPolicyError, match=message),
    ):
        llm.completion(messages=[], tools=[])


def test_metadata_free_llm_keeps_semantic_finish_summary() -> None:
    llm = _metadata_free_llm()
    response = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[SimpleNamespace(name="finish", arguments='{"summary":"done"}')]
        )
    )
    with patch.object(
        ValidatedResponsesRecoveryStateRequiredToolLLM,
        "completion",
        autospec=True,
        return_value=response,
    ):
        assert llm.completion(messages=[], tools=[]) is response


def test_snapshot_uses_the_same_metadata_free_provider_schema() -> None:
    schema = _provider_tools()[0]
    tool = SimpleNamespace(to_openai_tool=lambda **_kwargs: deepcopy(schema))

    assert snapshot_openhands_tools([tool], without_sdk_metadata=True) == (
        without_openhands_tool_metadata([schema])
    )
