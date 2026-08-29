from __future__ import annotations

import json
import re
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions

from verigym_openhands._hwe_tool_schema import (
    with_workspace_relative_hwe_constraints,
    without_openhands_tool_metadata,
)
from verigym_openhands.hwe_tool_choice import (
    MetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM,
    ProviderToolArgumentsPolicyError,
    ValidatedResponsesRecoveryStateRequiredToolLLM,
    WorkspaceRelativeMetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM,
)
from verigym_openhands.trajectory import (
    OpenHandsTrajectoryInfrastructureError,
    snapshot_openhands_tools,
)


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


def _workspace_relative_llm() -> (
    WorkspaceRelativeMetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM
):
    return WorkspaceRelativeMetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM(
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


def test_workspace_constraints_bind_exact_six_tools_without_mutating_input() -> None:
    original = deepseek_harness_tool_definitions()
    constrained = with_workspace_relative_hwe_constraints(original)

    assert original == deepseek_harness_tool_definitions()
    assert [item["function"]["name"] for item in constrained] == [
        "apply_patch",
        "finish",
        "inspect_diff",
        "list_files",
        "read_file",
        "shell",
    ]
    by_name = {item["function"]["name"]: item["function"] for item in constrained}
    for name, function in by_name.items():
        assert function["parameters"]["additionalProperties"] is False, name
    no_host_pattern = (
        r"^(?![\s\S]*(?:^|[^A-Za-z0-9._-])/(?:home|data|hpc)"
        r"(?:/|$|[^A-Za-z0-9._-]))(?![\s\S]*[A-Za-z]:\\)[\s\S]*$"
    )
    relative_pattern = (
        r"^(?!/)(?![A-Za-z]:[\\/])"
        r"(?![\s\S]*(?:^|[^A-Za-z0-9._-])/(?:home|data|hpc)"
        r"(?:/|$|[^A-Za-z0-9._-]))(?![\s\S]*[A-Za-z]:\\)[\s\S]*$"
    )
    assert by_name["list_files"]["parameters"]["properties"]["path"]["pattern"] == (
        relative_pattern
    )
    assert by_name["read_file"]["parameters"]["properties"]["path"]["pattern"] == (relative_pattern)
    assert by_name["shell"]["parameters"]["properties"]["cwd"]["pattern"] == relative_pattern
    assert by_name["shell"]["parameters"]["properties"]["command"]["pattern"] == (no_host_pattern)
    assert by_name["apply_patch"]["parameters"]["properties"]["patch"]["pattern"] == (
        no_host_pattern
    )
    assert by_name["finish"]["parameters"]["properties"]["summary"]["pattern"] == (no_host_pattern)
    assert re.fullmatch(no_host_pattern, "inspect repository/core/decoder.sv")
    assert not re.fullmatch(no_host_pattern, "inspect /data/private/decoder.sv")
    assert not re.fullmatch(no_host_pattern, "line one\n/home/user/decoder.sv")
    assert re.fullmatch(no_host_pattern, "riscv::CSR_MCOUNTINHIBIT:\nnext line")
    assert not re.fullmatch(no_host_pattern, r"inspect C:\private\decoder.sv")
    assert (
        "workspace-relative"
        in (by_name["shell"]["parameters"]["properties"]["command"]["description"])
    )


def test_workspace_constraints_reject_schema_drift() -> None:
    tools = deepseek_harness_tool_definitions()
    tools.pop()
    with pytest.raises(ValueError, match="exact six tools"):
        with_workspace_relative_hwe_constraints(tools)


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


def test_workspace_relative_llm_rebinds_both_provider_routes() -> None:
    llm = _workspace_relative_llm()
    chat_tools = deepseek_harness_tool_definitions()
    chat_result = ([], chat_tools, False, {"tools": deepcopy(chat_tools)}, {"route": "chat"})
    responses_tools = [{"type": "function", **deepcopy(item["function"])} for item in chat_tools]
    responses_result = (
        None,
        [],
        responses_tools,
        {"tool_choice": "required"},
        {"route": "responses"},
    )
    parent = MetadataFreeValidatedResponsesRecoveryStateRequiredToolLLM
    with (
        patch.object(
            parent,
            "_finalize_completion_params",
            autospec=True,
            return_value=chat_result,
        ),
        patch.object(
            parent,
            "_finalize_responses_params",
            autospec=True,
            return_value=responses_result,
        ),
    ):
        chat = llm._finalize_completion_params([], [], True, {})
        responses = llm._finalize_responses_params(None, [], [], None, False, True, {})

    assert chat[1] == with_workspace_relative_hwe_constraints(chat_tools)
    assert chat[3]["tools"] == chat[1]
    assert responses[2] == with_workspace_relative_hwe_constraints(responses_tools)


@pytest.mark.parametrize(
    ("name", "arguments", "message", "field", "kind"),
    [
        (
            "shell",
            '{"command":"pwd","summary":"inspect /data/private"}',
            "raw host path",
            "summary",
            "raw_host_path",
        ),
        (
            "shell",
            '{"command":"pwd","summary":"inspect files"}',
            "forbidden SDK",
            "summary",
            "forbidden_sdk_metadata",
        ),
        (
            "read_file",
            '{"path":"rtl/top.sv","security_risk":"LOW"}',
            "forbidden SDK",
            "security_risk",
            "forbidden_sdk_metadata",
        ),
    ],
)
def test_metadata_free_llm_rejects_sdk_metadata_before_agent_execution(
    name: str,
    arguments: str,
    message: str,
    field: str,
    kind: str,
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
        pytest.raises(ProviderToolArgumentsPolicyError, match=message) as caught,
    ):
        llm.completion(messages=[], tools=[])
    assert caught.value.tool_name == name
    assert caught.value.argument_field == field
    assert caught.value.violation_kind == kind


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


def test_metadata_free_llm_accepts_colon_terminated_rtl_labels_in_patch() -> None:
    llm = _metadata_free_llm()
    patch_text = """*** Begin Patch
*** Update File: core/csr_regfile.sv
@@
-        riscv::CSR_MCOUNTINHIBIT:
+        riscv::CSR_MCOUNTINHIBIT: begin
*** End Patch
"""
    response = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    name="apply_patch",
                    arguments=json.dumps({"patch": patch_text}),
                )
            ]
        )
    )
    with patch.object(
        ValidatedResponsesRecoveryStateRequiredToolLLM,
        "completion",
        autospec=True,
        return_value=response,
    ):
        assert llm.completion(messages=[], tools=[]) is response


@pytest.mark.parametrize(
    "path",
    [
        "/home/private/top.sv",
        "/data/private/top.sv",
        "/hpc/private/top.sv",
        r"C:\private\top.sv",
    ],
)
def test_metadata_free_llm_rejects_decoded_absolute_paths(path: str) -> None:
    llm = _metadata_free_llm()
    response = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    name="read_file",
                    arguments=json.dumps({"path": path}),
                )
            ]
        )
    )
    with (
        patch.object(
            ValidatedResponsesRecoveryStateRequiredToolLLM,
            "completion",
            autospec=True,
            return_value=response,
        ),
        pytest.raises(ProviderToolArgumentsPolicyError, match="raw host path") as caught,
    ):
        llm.completion(messages=[], tools=[])

    assert caught.value.argument_field == "path"
    assert caught.value.violation_kind == "raw_host_path"


def test_metadata_free_llm_does_not_treat_json_newline_escape_as_drive_path() -> None:
    llm = _metadata_free_llm()
    response = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    name="apply_patch",
                    arguments='{"patch":"riscv::CSR_MCOUNTINHIBIT:\\n"',
                )
            ]
        )
    )
    with patch.object(
        ValidatedResponsesRecoveryStateRequiredToolLLM,
        "completion",
        autospec=True,
        return_value=response,
    ):
        assert llm.completion(messages=[], tools=[]) is response


def test_metadata_free_llm_rejects_escaped_windows_path_in_malformed_json() -> None:
    llm = _metadata_free_llm()
    response = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    name="read_file",
                    arguments=r'{"path":"C:\\private\\top.sv"',
                )
            ]
        )
    )
    with (
        patch.object(
            ValidatedResponsesRecoveryStateRequiredToolLLM,
            "completion",
            autospec=True,
            return_value=response,
        ),
        pytest.raises(ProviderToolArgumentsPolicyError, match="raw host path") as caught,
    ):
        llm.completion(messages=[], tools=[])

    assert caught.value.argument_field == "unparsed"
    assert caught.value.violation_kind == "raw_host_path"


def test_snapshot_uses_the_same_metadata_free_provider_schema() -> None:
    schema = _provider_tools()[0]
    tool = SimpleNamespace(to_openai_tool=lambda **_kwargs: deepcopy(schema))

    assert snapshot_openhands_tools([tool], without_sdk_metadata=True) == (
        without_openhands_tool_metadata([schema])
    )


def test_snapshot_uses_the_same_workspace_relative_provider_schema() -> None:
    schemas = deepseek_harness_tool_definitions()
    tools = [
        SimpleNamespace(to_openai_tool=lambda schema=schema, **_kwargs: deepcopy(schema))
        for schema in schemas
    ]

    assert snapshot_openhands_tools(
        tools,
        without_sdk_metadata=True,
        workspace_relative_constraints=True,
    ) == with_workspace_relative_hwe_constraints(schemas)


def test_snapshot_rejects_workspace_constraints_without_metadata_normalization() -> None:
    schema = deepseek_harness_tool_definitions()[0]
    tool = SimpleNamespace(to_openai_tool=lambda **_kwargs: deepcopy(schema))
    with pytest.raises(OpenHandsTrajectoryInfrastructureError, match="require metadata-free"):
        snapshot_openhands_tools([tool], workspace_relative_constraints=True)
