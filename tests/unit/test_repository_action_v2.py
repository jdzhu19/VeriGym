from __future__ import annotations

import json

import pytest

from verigym.core.hashing import content_hash
from verigym.protocols.repository_action import (
    RepositoryActionProtocolViolation,
    action_registry,
    extract_json_content,
    extract_transport_action,
    prompt_contract,
    repository_action_state_failure,
    repository_tool_definitions,
    resolve_repository_action_protocol,
    validate_canonical_action,
    validate_repository_action_protocol_binding,
)
from verigym.schemas.action_protocol import ProviderNativeToolCall, RepositoryActionProtocolSpec
from verigym.schemas.common import AgentDescriptor
from verigym.schemas.task import TaskRef
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite


def _task():  # type: ignore[no-untyped-def]
    suite = RepositoryRtlSuite()
    return suite.load_task(
        TaskRef(id="repo-rtl/counter-wrap", suite="repo-rtl", native_id="counter-wrap")
    )


def _valid(action: str = "read_file", arguments: dict[str, object] | None = None) -> str:
    return json.dumps(
        {
            "protocol": "repository_action.v2",
            "action": action,
            "arguments": arguments if arguments is not None else {"path": "repository/README.md"},
        },
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    ("wrapper", "decision"),
    [
        ("{}", None),
        (" \n{}\t", "outer_whitespace_stripped"),
        ("\ufeff{}", "leading_bom_removed"),
        ("```json\n{}\n```", "response_wide_json_fence_unwrapped"),
        ("```\n{}\n```", "response_wide_unlabeled_fence_unwrapped"),
    ],
)
def test_representation_only_normalization_accepts_exact_permitted_forms(
    wrapper: str, decision: str | None
) -> None:
    value = _valid()
    parsed, record = extract_json_content(wrapper.format(value), max_response_bytes=262_144)
    assert parsed["action"] == "read_file"  # type: ignore[index]
    if decision is not None:
        assert decision in record.decisions


@pytest.mark.parametrize(
    ("raw", "subcategory"),
    [
        ("", "agent_empty_output"),
        ("not json", "agent_malformed_json"),
        ('prefix {"protocol":"repository_action.v2"} suffix', "agent_extra_prose"),
        ("```json\n{}\n``` trailing", "agent_extra_prose"),
        ('{"a":1,"a":2}', "agent_malformed_json"),
        ('{"protocol":"repository_action.v2",}', "agent_malformed_json"),
        ("// comment\n{}", "agent_extra_prose"),
    ],
)
def test_normalizer_never_repairs_or_extracts_invalid_content(raw: str, subcategory: str) -> None:
    with pytest.raises(RepositoryActionProtocolViolation) as raised:
        extract_json_content(raw, max_response_bytes=262_144)
    assert raised.value.subcategory == subcategory


def test_response_byte_bound_is_checked_before_parsing() -> None:
    with pytest.raises(RepositoryActionProtocolViolation) as raised:
        extract_json_content("{" + ("x" * 2048), max_response_bytes=1024)
    assert raised.value.subcategory == "agent_response_oversized"


def test_invalid_utf8_is_never_decoded_lossily() -> None:
    with pytest.raises(RepositoryActionProtocolViolation) as raised:
        extract_json_content(b"\xff", max_response_bytes=1024)
    assert raised.value.subcategory == "agent_malformed_json"


@pytest.mark.parametrize(
    ("value", "subcategory"),
    [
        ([], "agent_non_object_json"),
        ([{}, {}], "agent_multiple_actions"),
        ({"actions": [{}, {}]}, "agent_multiple_actions"),
        (
            {"protocol": "repository_action.v2", "action": "shell", "arguments": {}},
            "agent_unknown_action",
        ),
        (
            {
                "protocol": "repository_action.v2",
                "action": "read_file",
                "arguments": {"path": 4},
            },
            "agent_invalid_arguments",
        ),
        (
            {
                "protocol": "repository_action.v2",
                "action": "read_file",
                "arguments": {},
            },
            "agent_invalid_arguments",
        ),
        (
            {
                "protocol": "repository_action.v2",
                "action": "inspect_diff",
                "arguments": {"unexpected": True},
            },
            "agent_invalid_arguments",
        ),
        (
            {
                "protocol": "repository_action.v2",
                "action": "read_file",
                "arguments": {"path": "/etc/passwd"},
            },
            "agent_invalid_arguments",
        ),
        (
            {
                "protocol": "repository_action.v2",
                "action": "finish",
                "arguments": {"message": "done\u0000"},
            },
            "agent_invalid_arguments",
        ),
        (
            {
                "protocol": "repository_action.v2",
                "action": "read_file",
                "arguments": {"path": "../hidden/test.sv"},
            },
            "agent_invalid_arguments",
        ),
        (
            {
                "protocol": "repository_action.v2",
                "action": "run_public_test",
                "arguments": {"test_id": "not-registered"},
            },
            "agent_invalid_arguments",
        ),
    ],
)
def test_canonical_validator_is_strict_and_task_bound(value: object, subcategory: str) -> None:
    with pytest.raises(RepositoryActionProtocolViolation) as raised:
        validate_canonical_action(value, task=_task())
    assert raised.value.subcategory == subcategory


def test_native_tool_call_and_json_content_are_separate_transport_adapters() -> None:
    call = ProviderNativeToolCall(
        call_id="safe-call-1",
        name="read_file",
        arguments_json='{"path":"repository/README.md"}',
    )
    value, normalization = extract_transport_action(
        transport="native_tool_call",
        text="",
        native_tool_calls=[call],
        max_response_bytes=262_144,
    )
    assert normalization is None
    action, arguments = validate_canonical_action(value, task=_task())
    assert action.action == "read_file"
    assert arguments.path == "repository/README.md"  # type: ignore[attr-defined]

    with pytest.raises(RepositoryActionProtocolViolation) as raised:
        extract_transport_action(
            transport="json_content",
            text=_valid(),
            native_tool_calls=[call],
            max_response_bytes=262_144,
        )
    assert raised.value.subcategory == "agent_unsupported_transport"

    with pytest.raises(RepositoryActionProtocolViolation) as raised_multiple:
        extract_transport_action(
            transport="native_tool_call",
            text="",
            native_tool_calls=[call, call],
            max_response_bytes=262_144,
        )
    assert raised_multiple.value.subcategory == "agent_multiple_actions"


def test_registry_prompt_and_resolver_are_deterministic_and_fail_closed() -> None:
    task = _task().model_copy(
        update={"budget": _task().budget.model_copy(update={"max_model_calls": 6})}
    )
    descriptor = AgentDescriptor(
        name="fixture-agent",
        version="1",
        api_version="1.0",
        provider="tests",
    )
    first = resolve_repository_action_protocol(
        agent_descriptor=descriptor,
        protocol_spec=RepositoryActionProtocolSpec(),
        agent_options={
            "action_protocol": "repository_action.v2",
            "action_transport": "json_content",
            "max_completion_calls": 6,
            "max_response_bytes": 262_144,
        },
        task=task,
    )
    second = resolve_repository_action_protocol(
        agent_descriptor=descriptor,
        protocol_spec=RepositoryActionProtocolSpec(),
        agent_options={
            "action_protocol": "repository_action.v2",
            "action_transport": "json_content",
            "max_completion_calls": 6,
            "max_response_bytes": 262_144,
        },
        task=task,
    )
    assert first == second
    assert first is not None
    assert first.action_registry_hash
    assert first.state_machine_id == "repository_action_state_machine_v2"
    assert first.configuration_fingerprint == content_hash(
        first.model_dump(mode="json", exclude={"schema_version", "configuration_fingerprint"})
    )
    assert action_registry()["one_action_per_turn"] is True
    assert prompt_contract()["registry_hash"] == first.action_registry_hash
    validate_repository_action_protocol_binding(expected=first, resolved=second)
    with pytest.raises(ValueError, match="action_transport"):
        validate_repository_action_protocol_binding(
            expected=first,
            resolved=first.model_copy(update={"action_transport": "native_tool_call"}),
        )


def test_versioned_state_machine_preserves_legacy_and_allows_no_public_test_finish() -> None:
    legacy = prompt_contract("repository_action_state_machine_v1")
    current = prompt_contract("repository_action_state_machine_v2")
    assert legacy["prompt_contract_id"] == "repository_action_v2_prompt_v1"
    assert "state_machine_id" not in legacy
    assert current["prompt_contract_id"] == "repository_action_v2_prompt_v2"
    assert current["state_machine_id"] == "repository_action_state_machine_v2"

    common = {
        "patch_applied": True,
        "public_observed": False,
        "diff_observed": True,
        "finished": False,
    }
    assert (
        repository_action_state_failure(
            "finish",
            state_machine_id="repository_action_state_machine_v2",
            public_test_required=False,
            **common,
        )
        is None
    )
    assert (
        repository_action_state_failure(
            "finish",
            state_machine_id="repository_action_state_machine_v2",
            public_test_required=True,
            **common,
        )
        == "agent_finish_invalid"
    )
    assert (
        repository_action_state_failure(
            "finish",
            state_machine_id="repository_action_state_machine_v1",
            public_test_required=False,
            **common,
        )
        == "agent_finish_invalid"
    )


def test_protocol_spec_rejects_mixed_prompt_and_state_machine_versions() -> None:
    with pytest.raises(ValueError, match="versions must match"):
        RepositoryActionProtocolSpec(
            prompt_contract_id="repository_action_v2_prompt_v1",
            state_machine_id="repository_action_state_machine_v2",
        )


def test_v5_prompt_contract_extends_v4_finalization_budget_rules() -> None:
    spec = RepositoryActionProtocolSpec(
        prompt_contract_id="repository_action_v2_prompt_v5",
        state_machine_id="repository_action_state_machine_v3",
    )
    contract = prompt_contract(
        "repository_action_state_machine_v3",
        prompt_contract_id=spec.prompt_contract_id,
    )

    assert contract["prompt_contract_id"] == "repository_action_v2_prompt_v5"
    assert any("remaining wall time" in rule for rule in contract["rules"])
    assert any("typed finish" in rule for rule in contract["rules"])


def test_v6_prompt_contract_adds_broker_enforced_finalization_guard() -> None:
    spec = RepositoryActionProtocolSpec(
        prompt_contract_id="repository_action_v2_prompt_v6",
        state_machine_id="repository_action_state_machine_v3",
    )
    contract = prompt_contract(
        "repository_action_state_machine_v3",
        prompt_contract_id=spec.prompt_contract_id,
    )

    assert contract["prompt_contract_id"] == "repository_action_v2_prompt_v6"
    assert any("twelve file calls" in rule for rule in contract["rules"])
    assert any("ninety-second reserve" in rule for rule in contract["rules"])
    assert any("broker-advertised next actions" in rule for rule in contract["rules"])


def test_v7_prompt_contract_adds_functional_repair_loop() -> None:
    spec = RepositoryActionProtocolSpec(
        prompt_contract_id="repository_action_v2_prompt_v7",
        state_machine_id="repository_action_state_machine_v3",
    )
    contract = prompt_contract(
        "repository_action_state_machine_v3",
        prompt_contract_id=spec.prompt_contract_id,
    )

    assert contract["prompt_contract_id"] == "repository_action_v2_prompt_v7"
    assert any("functional smoke" in rule for rule in contract["rules"])
    assert any("repair the current candidate" in rule for rule in contract["rules"])


def test_v8_prompt_and_tool_contract_advertise_compatible_patch_grammar() -> None:
    contract = prompt_contract(
        "repository_action_state_machine_v3",
        prompt_contract_id="repository_action_v2_prompt_v8",
    )
    compatible = repository_tool_definitions(
        dialect="mcp",
        patch_format_profile="strict_unified_and_codex_native_v1",
    )
    default = repository_tool_definitions(dialect="mcp")
    compatible_patch = next(item for item in compatible if item["name"] == "apply_patch")
    default_patch = next(item for item in default if item["name"] == "apply_patch")

    assert contract["prompt_contract_id"] == "repository_action_v2_prompt_v8"
    assert any("Codex-native" in rule for rule in contract["rules"])
    assert "*** Begin Patch" in compatible_patch["description"]
    assert "*** Begin Patch" not in default_patch["description"]


@pytest.mark.parametrize("case", range(5))
def test_five_historical_v1_shapes_counterfactually_reject_multiple_actions(case: int) -> None:
    del case
    legacy = {
        "schema_version": "1.0",
        "actions": [
            {"type": "apply_patch", "patch": "bounded historical patch omitted"},
            {
                "type": "tool_call",
                "tool": "repository.public_test",
                "arguments": {"test_id": "counter-wrap-public"},
            },
            {"type": "tool_call", "tool": "file.diff", "arguments": {}},
            {"type": "final", "message": "done"},
        ],
    }
    with pytest.raises(RepositoryActionProtocolViolation) as raised:
        validate_canonical_action(legacy, task=_task())
    assert raised.value.subcategory == "agent_multiple_actions"
