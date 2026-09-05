from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym_codex_cli.agenteval_agent import (
    CodexCliAgentEvalAdapter,
    _accounting,
    _agenteval_prompt,
    _identity,
    _parse_returned_event_stream,
    _postparse_scoring_failure,
    _preparse_process_failure,
    _write_scoring_evidence,
)
from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_AGENT_VERSION_HASH,
    AGENTEVAL_AGENT_VERSION_ID,
    AGENTEVAL_PROMPT_HASH,
    AGENTEVAL_PROMPT_INSTRUCTIONS,
    AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    agenteval_settings,
)
from verigym_codex_cli.agenteval_invocation import (
    build_agenteval_arguments,
    sanitized_agenteval_invocation,
)
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.events import (
    ScoringEventError,
    parse_event_stream,
    scoring_mcp_server_category_counts,
    validate_scoring_mcp_stream,
)
from verigym_codex_cli.process import CodexProcessResult

from verigym.core.repository_tool_broker import RepositoryToolBrokerStats
from verigym.prompts.policy import resolve_prompt_policy
from verigym.protocols.repository_action import (
    canonical_tool_observation,
    repository_tool_definitions,
)
from verigym.schemas.common import InteractionMode
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.task import TaskRef
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite

pytestmark = pytest.mark.codex_cli

_CLI_SHA256 = "134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477"


def _settings(fake_codex: tuple[Path, Path, object]):  # type: ignore[no-untyped-def]
    del fake_codex
    _identity, discovered = discover_capabilities(force=True)
    capabilities = replace(
        discovered,
        version_output="codex-cli 0.147.0",
        executable_sha256=_CLI_SHA256,
    )
    options = {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "expected_cli_version": "codex-cli 0.147.0",
        "expected_cli_executable_sha256": _CLI_SHA256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_prompt_hash": AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": "inherited_codex_login",
        "expected_resolved_auth_mode": "inherited_codex_login",
        "expected_auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
    }
    return agenteval_settings(options, capabilities, task_wall_time_s=300), capabilities


def _line(value: dict[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"))


def _finish_stream(*, final_message: bool = True) -> str:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    lines = [
        _line({"type": "turn.started", "model": "gpt-5.4"}),
        _line(
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "verigym",
                    "id": "call_finish",
                    "name": "finish",
                    "arguments": {"message": "done"},
                    "result": observation,
                },
            }
        ),
    ]
    if final_message:
        lines.append(
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "complete"},
                }
            )
        )
    lines.append(
        _line(
            {
                "type": "turn.completed",
                "model": "gpt-5.4",
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }
        )
    )
    return "\n".join(lines)


def test_scoring_settings_and_invocation_are_exact_mcp_only(
    fake_codex: tuple[Path, Path, object], tmp_path: Path
) -> None:
    settings, capabilities = _settings(fake_codex)
    arguments = build_agenteval_arguments(capabilities, settings, socket_path=tmp_path / "mcp.sock")
    safe = sanitized_agenteval_invocation(arguments, settings, capabilities)

    assert settings.max_tool_calls == 40
    assert settings.max_patch_calls == 20
    assert settings.max_consecutive_rejected_calls == 3
    assert settings.max_exploratory_calls == 12
    assert settings.finalization_reserve_s == 90
    assert settings.execution.model_id == "gpt-5.4"
    assert settings.execution.effective_reasoning_effort == "xhigh"
    assert safe["mcp_tool_names"] == [
        item["name"] for item in repository_tool_definitions(dialect="mcp")
    ]
    assert safe["features_shell_tool"] is False
    assert safe["apps_enabled"] is False
    assert safe["mcp_tool_exposure"] == "direct_only_deferred_omitted"
    assert safe["broker_max_exploratory_calls"] == 12
    assert safe["broker_finalization_reserve_s"] == 90
    assert "features.apps=false" in arguments
    assert 'mcp_servers.verigym.omit_tools_from=["deferred"]' in arguments
    assert safe["web_search_enabled"] is False
    assert safe["training_mode"] is False
    assert "--ephemeral" in arguments
    assert "--ignore-user-config" in arguments
    assert CodexCliAgentEvalAdapter.descriptor.name == "codex-cli-agenteval-agent"
    assert CodexCliAgentEvalAdapter.descriptor.version == "10.0.0"
    assert AGENTEVAL_AGENT_VERSION_ID == "codex-cli-agenteval-gpt54-xhigh-v10"
    assert AGENTEVAL_AGENT_VERSION_HASH == (
        "47673eb65a0595944eb622c6f8d8c66df7502e19d2616d03470f08410bfd71b9"
    )
    assert AGENTEVAL_PROMPT_HASH == (
        "fe8bc9e5f2e3b91443bb9130e51b4de7cde4be5fe9d2b4ba97bc16417d0b2e79"
    )
    assert AGENTEVAL_TOOL_POLICY_FINGERPRINT == (
        "0b2c999374b827b9023bec19c2e5eaed6676893a91a1769ac9de1e1d3d5ba643"
    )


def test_scoring_agent_version_is_not_treated_as_prompt_memory(
    fake_codex: tuple[Path, Path, object],
) -> None:
    del fake_codex
    _identity, capabilities = discover_capabilities(force=True)
    capabilities = replace(
        capabilities,
        version_output="codex-cli 0.147.0",
        executable_sha256=_CLI_SHA256,
    )
    options = {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "expected_cli_version": "codex-cli 0.147.0",
        "expected_cli_executable_sha256": _CLI_SHA256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_prompt_hash": AGENTEVAL_PROMPT_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
        "expected_requested_auth_mode": "inherited_codex_login",
        "expected_resolved_auth_mode": "inherited_codex_login",
        "expected_auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
    }
    task = RepositoryRtlSuite().load_task(
        TaskRef(id="repo-rtl/counter-wrap", suite="repo-rtl", native_id="counter-wrap")
    )

    policy = resolve_prompt_policy(
        interaction_mode=InteractionMode.AGENT,
        agent=CodexCliAgentEvalAdapter(),
        agent_options=options,
        task=task,
    )

    assert policy is not None
    assert policy.id == "repository_action_v2_prompt_v6"
    assert policy.version == "6.0.0"
    assert policy.base_instruction_policy == "generated_repository_action_registry_v6"
    assert policy.agent_version_id is None
    assert policy.agent_version_hash is None
    assert policy.memory_pack_hash is None


def test_v3_settings_require_prompt_and_tool_policy_fingerprints(
    fake_codex: tuple[Path, Path, object],
) -> None:
    settings, capabilities = _settings(fake_codex)
    options = {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "expected_cli_version": "codex-cli 0.147.0",
        "expected_cli_executable_sha256": _CLI_SHA256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_requested_auth_mode": settings.execution.requested_auth_mode,
        "expected_resolved_auth_mode": settings.execution.resolved_auth_mode,
        "expected_auth_semantic_id": settings.execution.auth_semantic_id,
        "scoring_agent_version_id": AGENTEVAL_AGENT_VERSION_ID,
        "scoring_agent_version_hash": AGENTEVAL_AGENT_VERSION_HASH,
        "expected_tool_policy_fingerprint": AGENTEVAL_TOOL_POLICY_FINGERPRINT,
    }

    with pytest.raises(ValueError, match="expected_prompt_hash"):
        agenteval_settings(options, capabilities, task_wall_time_s=300)


def test_scoring_event_stream_accepts_finish_and_rejects_builtin_tools() -> None:
    assert validate_scoring_mcp_stream(_finish_stream()) == ("finish",)
    assert validate_scoring_mcp_stream(_finish_stream(final_message=False)) == ("finish",)
    command = _line(
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "pwd"},
        }
    )
    with pytest.raises(ScoringEventError, match="non-MCP") as captured:
        validate_scoring_mcp_stream(command)
    assert captured.value.category == "non_mcp_tool"


def test_scoring_event_stream_leaves_transport_metadata_to_the_validated_broker() -> None:
    lines = _finish_stream(final_message=False).splitlines()
    completed = json.loads(lines[1])
    completed["item"].pop("id")
    completed["item"]["arguments"] = None
    stream = "\n".join([lines[0], _line(completed), lines[2]])

    assert validate_scoring_mcp_stream(stream) == ("finish",)


def test_scoring_event_stream_treats_server_label_as_bounded_advisory_metadata() -> None:
    lines = _finish_stream(final_message=False).splitlines()
    completed = json.loads(lines[1])
    completed["item"]["server"] = "other"
    stream = "\n".join([lines[0], _line(completed), lines[2]])

    assert validate_scoring_mcp_stream(stream) == ("finish",)
    assert scoring_mcp_server_category_counts(stream)["other"] == 1


def test_scoring_event_stream_rejects_noncanonical_mcp_tool() -> None:
    lines = _finish_stream(final_message=False).splitlines()
    completed = json.loads(lines[1])
    completed["item"]["name"] = "other"
    stream = "\n".join([lines[0], _line(completed), lines[2]])

    with pytest.raises(ScoringEventError) as captured:
        validate_scoring_mcp_stream(stream)

    assert captured.value.category == "mcp_tool"


def test_scoring_event_stream_rejects_post_finish_tools_with_bounded_category() -> None:
    lines = _finish_stream().splitlines()
    duplicate = json.loads(lines[1])
    duplicate["item"]["id"] = "call_finish_again"
    stream = "\n".join([*lines[:-1], _line(duplicate), lines[-1]])

    with pytest.raises(ScoringEventError, match="after its final message") as captured:
        validate_scoring_mcp_stream(stream)

    assert captured.value.category == "post_finish_tool"


def test_full_scoring_gate_accepts_official_optional_final_message_shape() -> None:
    stream = _finish_stream(final_message=False)
    parsed = parse_event_stream(stream)
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=0,
        stdout=stream,
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=0,
        file_writes=0,
        patches=0,
        finish_calls=1,
        finished=True,
        policy_failure=None,
        infrastructure_failure=None,
        tool_call_sequence=("finish",),
        accepted_finish_call_index=0,
    )

    failure = _postparse_scoring_failure(
        process,
        broker,
        parsed,
        parse_error=None,
        expected_model_id="gpt-5.4",
    )

    assert failure is None


def test_full_scoring_gate_rejects_event_sequence_not_attested_by_broker() -> None:
    stream = _finish_stream(final_message=False)
    parsed = parse_event_stream(stream)
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=0,
        stdout=stream,
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=0,
        file_writes=0,
        patches=0,
        finish_calls=1,
        finished=True,
        policy_failure=None,
        infrastructure_failure=None,
        tool_call_sequence=("inspect_diff",),
        accepted_finish_call_index=0,
    )

    failure = _postparse_scoring_failure(
        process,
        broker,
        parsed,
        parse_error=None,
        expected_model_id="gpt-5.4",
    )

    assert failure is not None
    assert failure.failure.protocol_error_subcategory == "scoring_event_tool_sequence_mismatch"


def test_full_scoring_gate_accepts_rejected_early_finish_before_broker_accepted_finish() -> None:
    lines = _finish_stream(final_message=False).splitlines()
    early_finish = json.loads(lines[1])
    inspect_diff = json.loads(lines[1])
    inspect_diff["item"]["name"] = "inspect_diff"
    final_finish = json.loads(lines[1])
    stream = "\n".join(
        [lines[0], _line(early_finish), _line(inspect_diff), _line(final_finish), lines[-1]]
    )
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=0,
        stdout=stream,
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=3,
        command_calls=0,
        public_test_calls=0,
        file_reads=0,
        file_writes=0,
        patches=0,
        finish_calls=1,
        finished=True,
        policy_failure=None,
        infrastructure_failure=None,
        tool_call_sequence=("finish", "inspect_diff", "finish"),
        accepted_finish_call_index=2,
    )

    failure = _postparse_scoring_failure(
        process,
        broker,
        parse_event_stream(stream),
        parse_error=None,
        expected_model_id="gpt-5.4",
    )

    assert failure is None


def test_scoring_failure_retains_only_bounded_event_subcategory() -> None:
    stream = _line(
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "private command"},
        }
    )
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=0,
        stdout=stream,
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=0,
        command_calls=0,
        public_test_calls=0,
        file_reads=0,
        file_writes=0,
        patches=0,
        finish_calls=0,
        finished=False,
        policy_failure=None,
        infrastructure_failure=None,
    )

    failure = _postparse_scoring_failure(
        process,
        broker,
        parse_event_stream(stream),
        parse_error=None,
        expected_model_id="gpt-5.4",
    )

    assert failure is not None
    assert failure.failure.category == "scoring_event_ineligible"
    assert failure.failure.protocol_error_subcategory == "scoring_event_non_mcp_tool"
    assert "private command" not in failure.failure.model_dump_json()


def test_scoring_identity_does_not_invent_an_unreported_model(
    fake_codex: tuple[Path, Path, object],
) -> None:
    settings, capabilities = _settings(fake_codex)
    stream = _finish_stream().replace(',"model":"gpt-5.4"', "")
    parsed = parse_event_stream(stream)
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=0,
        file_writes=0,
        patches=0,
        finish_calls=1,
        finished=True,
        policy_failure=None,
        infrastructure_failure=None,
    )

    identity = _identity(settings, capabilities, parsed, broker)

    assert identity.requested_model_id == "gpt-5.4"
    assert identity.observed_model_id is None
    assert identity.identity_confidence == "requested_only"


def test_scoring_evidence_never_exports_a_training_transcript(
    fake_codex: tuple[Path, Path, object], tmp_path: Path
) -> None:
    settings, capabilities = _settings(fake_codex)
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=0,
        stdout=_finish_stream(),
        stderr="private stderr must not be persisted",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=0,
        file_writes=0,
        patches=0,
        finish_calls=1,
        finished=True,
        policy_failure=None,
        infrastructure_failure=None,
    )
    accounting = ExternalAgentAccounting(
        process_wall_time_s=1.0,
        cli_event_count=4,
        external_tool_call_count=1,
    )
    root = tmp_path / "evidence"
    root.mkdir()

    _write_scoring_evidence(
        root,
        capabilities=capabilities,
        invocation={"training_mode": False, "agent_version_id": settings.agent_version_id},
        process=process,
        broker=broker,
        identity=None,
        accounting=accounting,
        parsed=None,
    )

    assert not (root / "training-transcript.json").exists()
    assert not (root / "raw_stdout.jsonl").exists()
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in root.iterdir())
    assert "private stderr" not in persisted
    persisted_summary = json.loads((root / "summary.json").read_text())
    assert persisted_summary["training_mode"] is False
    assert persisted_summary["mcp_server_category_counts"]["exact_verigym"] == 1
    assert json.loads((root / "broker.json").read_text())["tool_call_sequence"] == []


def test_scoring_evidence_persists_only_bounded_broker_failure_subcategory(
    fake_codex: tuple[Path, Path, object], tmp_path: Path
) -> None:
    settings, capabilities = _settings(fake_codex)
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=1,
        stdout=_finish_stream(),
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=1,
        file_writes=0,
        patches=0,
        policy_failure="absolute path rejected at /private/site/path",
        infrastructure_failure=None,
        policy_failure_subcategory="workspace_path_policy",
        terminal_tool_name="read_file",
        terminal_path_category="absolute",
    )
    root = tmp_path / "evidence"
    root.mkdir()

    _write_scoring_evidence(
        root,
        capabilities=capabilities,
        invocation={"training_mode": False, "agent_version_id": settings.agent_version_id},
        process=process,
        broker=broker,
        identity=None,
        accounting=ExternalAgentAccounting(process_wall_time_s=1.0, cli_event_count=4),
        parsed=None,
        failure_category="workspace_policy",
    )

    persisted_broker = json.loads((root / "broker.json").read_text())
    persisted_summary = json.loads((root / "summary.json").read_text())
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in root.iterdir())
    assert persisted_broker["policy_failure"] is True
    assert persisted_broker["policy_failure_subcategory"] == "workspace_path_policy"
    assert persisted_broker["terminal_tool_name"] == "read_file"
    assert persisted_broker["terminal_path_category"] == "absolute"
    assert persisted_summary["failure_subcategory"] == "workspace_path_policy"
    assert "/private/site/path" not in persisted


def test_scoring_evidence_drops_unbounded_terminal_tool_metadata(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    settings, capabilities = _settings(fake_codex)
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=1,
        stdout="",
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=1,
        file_writes=0,
        patches=0,
        policy_failure="private diagnostic at /private/site/path",
        infrastructure_failure=None,
        policy_failure_subcategory="workspace_path_policy",
        terminal_tool_name="private-tool-/private/site/path",
        terminal_path_category="private-path-/private/site/path",
    )
    root = tmp_path / "evidence"
    root.mkdir()

    _write_scoring_evidence(
        root,
        capabilities=capabilities,
        invocation={"training_mode": False, "agent_version_id": settings.agent_version_id},
        process=process,
        broker=broker,
        identity=None,
        accounting=ExternalAgentAccounting(process_wall_time_s=1.0, cli_event_count=0),
        parsed=None,
        failure_category="workspace_policy",
    )

    persisted = "\n".join(path.read_text(encoding="utf-8") for path in root.iterdir())
    persisted_broker = json.loads((root / "broker.json").read_text())
    assert persisted_broker["terminal_tool_name"] is None
    assert persisted_broker["terminal_path_category"] is None
    assert "/private/site/path" not in persisted


def test_returned_policy_failure_keeps_requested_identity_and_incomplete_usage(
    fake_codex: tuple[Path, Path, object],
) -> None:
    settings, capabilities = _settings(fake_codex)
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=1,
        stdout=_line({"type": "turn.started", "model": "gpt-5.4"}) + "\n{malformed",
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=1,
        file_writes=0,
        patches=0,
        finish_calls=0,
        finished=False,
        policy_failure="absolute path rejected",
        infrastructure_failure=None,
        policy_failure_subcategory="workspace_path_policy",
    )

    parsed, parse_error = _parse_returned_event_stream(process.stdout)
    failure = _preparse_process_failure(process, broker)
    identity = _identity(settings, capabilities, parsed, broker)
    accounting = _accounting(process, broker, parsed)

    assert parse_error == "event_stream_malformed_or_incomplete"
    assert failure is not None
    assert failure.failure.kind == "policy"
    assert failure.failure.category == "workspace_policy"
    assert failure.failure.protocol_error_subcategory == "workspace_path_policy"
    assert identity.invocation_count == 1
    assert identity.observed_model_id is None
    assert identity.identity_confidence == "requested_only"
    assert identity.agent_version_hash == AGENTEVAL_AGENT_VERSION_HASH
    assert identity.prompt_contract_hash == AGENTEVAL_PROMPT_HASH
    assert identity.tool_policy_fingerprint == AGENTEVAL_TOOL_POLICY_FINGERPRINT
    assert accounting.usage_complete is False
    assert accounting.input_tokens is None
    assert accounting.output_tokens is None
    assert accounting.total_tokens is None


def test_unrecognized_terminal_subcategory_is_not_persisted_as_diagnostic_text(
    fake_codex: tuple[Path, Path, object],
) -> None:
    del fake_codex
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=1,
        stdout="",
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=1,
        file_writes=0,
        patches=0,
        policy_failure="private diagnostic",
        infrastructure_failure=None,
        policy_failure_subcategory="private diagnostic at /private/site/path",
    )

    failure = _preparse_process_failure(process, broker)

    assert failure is not None
    assert failure.failure.protocol_error_subcategory == "workspace_policy_unspecified"
    assert "/private/site/path" not in failure.failure.model_dump_json()


def test_complete_terminal_usage_is_recorded_without_estimation(
    fake_codex: tuple[Path, Path, object],
) -> None:
    settings, capabilities = _settings(fake_codex)
    parsed, parse_error = _parse_returned_event_stream(_finish_stream())
    process = CodexProcessResult(
        arguments=("codex",),
        exit_code=0,
        stdout=_finish_stream(),
        stderr="",
        duration_s=1.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )
    broker = RepositoryToolBrokerStats(
        tool_calls=1,
        command_calls=0,
        public_test_calls=0,
        file_reads=0,
        file_writes=0,
        patches=0,
        finish_calls=1,
        finished=True,
        policy_failure=None,
        infrastructure_failure=None,
    )

    identity = _identity(settings, capabilities, parsed, broker)
    accounting = _accounting(process, broker, parsed)

    assert parse_error is None
    assert identity.observed_model_id == "gpt-5.4"
    assert identity.identity_confidence == "observed"
    assert accounting.usage_complete is True
    assert accounting.input_tokens == 10
    assert accounting.output_tokens == 4
    assert accounting.total_tokens == 14


def test_v6_prompt_exposes_paths_budgets_compile_ppa_diff_and_finish() -> None:
    instructions = " ".join(AGENTEVAL_PROMPT_INSTRUCTIONS)

    assert "repository-relative paths" in instructions
    assert "editable_globs" in instructions
    assert "recoverable patch category" in instructions
    assert "empty editable file" in instructions
    assert "After every successful patch, compile" in instructions
    assert "PPA is available" in instructions
    assert "40 tool calls" in instructions
    assert "20 patch calls" in instructions
    assert "remaining_wall_time_s" in instructions
    assert "final 90 seconds" in instructions
    assert "12 exploratory file calls" in instructions
    assert "finalization_required" in instructions
    assert "inspect the latest diff" in instructions
    assert "typed finish" in instructions
    assert "Never end the turn with assistant text before typed finish" in instructions


def test_v6_prompt_preserves_paths_and_enforces_finalization_budgets() -> None:
    contract = SimpleNamespace(
        compile_test_id="compile",
        ppa_enabled=True,
        model_dump=lambda **_kwargs: {"compile_test_id": "compile", "ppa_enabled": True},
    )
    context = SimpleNamespace(
        agent_feedback_contract=contract,
        task=SimpleNamespace(
            id="suite/task",
            title="Task",
            description="Description",
            workspace=SimpleNamespace(entrypoints=["repository/rtl/counter.v"]),
        ),
    )
    bridge = SimpleNamespace(
        editable_globs=("repository/rtl/counter.v",),
        readonly_globs=("TASK.md",),
    )
    settings = SimpleNamespace(
        execution=SimpleNamespace(task_wall_time_s=300.0, effective_process_timeout_s=240.0),
        max_tool_calls=40,
        max_patch_calls=20,
        max_consecutive_rejected_calls=3,
        finalization_reserve_s=90,
        max_exploratory_calls=12,
    )

    prompt = json.loads(_agenteval_prompt(context, bridge, settings))

    assert prompt["workspace_policy"]["editable_globs"] == ["repository/rtl/counter.v"]
    assert prompt["workspace_policy"]["editable_paths_must_be_copied_verbatim"] is True
    assert prompt["budgets"] == {
        "task_wall_time_s": 300,
        "process_wall_time_s": 240,
        "max_tool_calls": 40,
        "max_patch_calls": 20,
        "max_consecutive_rejected_calls": 3,
        "finalization_reserve_s": 90,
        "max_exploratory_calls": 12,
    }
