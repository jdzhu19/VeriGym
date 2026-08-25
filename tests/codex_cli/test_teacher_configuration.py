from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from verigym_codex_cli.capabilities import discover_capabilities
from verigym_codex_cli.events import parse_event_stream
from verigym_codex_cli.process import CodexProcessResult
from verigym_codex_cli.teacher_agent import (
    CodexCliMcpTeacherAdapter,
    _preparse_process_failure,
    _provider_usage_failure,
    _record_postparse_failure_evidence,
    _write_content_free_evidence,
)
from verigym_codex_cli.teacher_config import teacher_settings
from verigym_codex_cli.teacher_invocation import (
    build_teacher_arguments,
    sanitized_teacher_invocation,
)

from verigym.core.repository_tool_broker import RepositoryToolBrokerStats
from verigym.protocols.repository_action import repository_tool_definitions

pytestmark = pytest.mark.codex_cli


def test_codex_distribution_excludes_test_sources() -> None:
    manifest = Path("integrations/verigym-codex-cli/MANIFEST.in").read_text(encoding="utf-8")

    assert manifest.splitlines() == ["prune tests"]


def _timed_out_process() -> CodexProcessResult:
    return CodexProcessResult(
        arguments=("codex",),
        exit_code=143,
        stdout="",
        stderr="",
        duration_s=1800.0,
        timed_out=True,
        stdout_truncated=True,
        stderr_truncated=False,
        process_group_cleaned=True,
    )


def _broker_stats(*, tool_calls: int) -> RepositoryToolBrokerStats:
    return RepositoryToolBrokerStats(
        tool_calls=tool_calls,
        command_calls=0,
        public_test_calls=0,
        file_reads=tool_calls,
        file_writes=0,
        patches=0,
        policy_failure=None,
        infrastructure_failure=None,
    )


def test_episode_deadline_is_an_agent_failure_with_or_without_mcp_activity() -> None:
    active = _preparse_process_failure(_timed_out_process(), _broker_stats(tool_calls=8))
    inactive = _preparse_process_failure(_timed_out_process(), _broker_stats(tool_calls=0))

    assert active is not None
    assert active.failure.kind == "model"
    assert active.failure.category == "agent_timeout"
    assert active.failure.infrastructure is False
    assert inactive is not None
    assert inactive.failure.kind == "model"
    assert inactive.failure.category == "agent_timeout"
    assert inactive.failure.infrastructure is False


def test_timed_out_teacher_evidence_records_explicitly_missing_usage(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    del fake_codex
    _executable, capabilities = discover_capabilities(force=True)
    root = tmp_path / "evidence"
    root.mkdir()

    _write_content_free_evidence(
        root,
        capabilities=capabilities,
        invocation={"model_id": "gpt-5.4", "reasoning_effort": "xhigh"},
        process=_timed_out_process(),
        event_summaries=[],
        broker=_broker_stats(tool_calls=0).__dict__,
        identity=None,
        accounting=None,
        provider_usage={
            "usage_complete": False,
            "usage_missing": True,
            "input_tokens": None,
            "output_tokens": None,
            "cached_input_tokens": None,
            "cost_usd": None,
        },
        transcript=None,
        failure_category="agent_timeout",
    )

    usage = json.loads((root / "provider-usage.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    process = json.loads((root / "process.json").read_text(encoding="utf-8"))
    assert usage["usage_complete"] is False
    assert usage["input_tokens"] is None
    assert process["timed_out"] is True
    assert summary["failure_category"] == "agent_timeout"
    assert summary["training_transcript_captured"] is False
    assert not (root / "training-transcript.json").exists()
    assert not (root / "identity.json").exists()


def test_postparse_failure_evidence_keeps_usage_without_transcript(
    fake_codex: tuple[Path, Path, object],
    tmp_path: Path,
) -> None:
    del fake_codex
    _executable, capabilities = discover_capabilities(force=True)
    stdout = json.dumps(
        {
            "type": "turn.completed",
            "model": "gpt-5.4",
            "usage": {"input_tokens": 11, "output_tokens": 7},
        },
        separators=(",", ":"),
    )
    root = tmp_path / "evidence"
    root.mkdir()
    bridge = Mock()
    bridge.artifact_root = root

    _record_postparse_failure_evidence(
        bridge,
        capabilities=capabilities,
        invocation={"model_id": "gpt-5.4", "reasoning_effort": "xhigh"},
        process=CodexProcessResult(
            arguments=("codex",),
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_s=1.0,
            timed_out=False,
            stdout_truncated=False,
            stderr_truncated=False,
            process_group_cleaned=True,
        ),
        broker=_broker_stats(tool_calls=0),
        parsed=parse_event_stream(stdout),
        failure_category="training_transcript_ineligible",
    )

    usage = json.loads((root / "provider-usage.json").read_text(encoding="utf-8"))
    accounting = json.loads((root / "accounting.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert usage["usage_complete"] is True
    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 7
    assert accounting["total_tokens"] == 18
    assert summary["failure_category"] == "training_transcript_ineligible"
    assert summary["training_transcript_captured"] is False
    assert not (root / "training-transcript.json").exists()
    bridge.record_accounting.assert_called_once()


def test_teacher_is_exact_gpt54_xhigh_required_mcp_only(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del fake_codex
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "inherited_codex_login")
    _identity, capabilities = discover_capabilities(force=True)
    settings = teacher_settings(
        {
            "campaign_role": "training",
            "capture_training_transcript": True,
            "model_id": "gpt-5.4",
            "reasoning_effort": "xhigh",
            "max_tool_calls": 32,
            "max_patch_calls": 8,
            "max_consecutive_rejected_calls": 3,
        },
        capabilities,
        task_wall_time_s=300,
    )
    arguments = build_teacher_arguments(
        capabilities, settings, socket_path=tmp_path / "broker.sock"
    )
    safe = sanitized_teacher_invocation(arguments, settings, capabilities)

    assert settings.execution.model_id == "gpt-5.4"
    assert settings.execution.effective_reasoning_effort == "xhigh"
    assert "features.shell_tool=false" in arguments
    assert 'web_search="disabled"' in arguments
    assert "mcp_servers.verigym.required=true" in arguments
    assert safe["mcp_tool_names"] == [
        definition["name"] for definition in repository_tool_definitions(dialect="mcp")
    ]
    assert safe["features_shell_tool"] is False
    assert safe["web_search_enabled"] is False
    assert safe["broker_max_tool_calls"] == 32
    assert safe["broker_max_patch_calls"] == 8
    assert safe["broker_max_consecutive_rejected_calls"] == 3
    assert "<private-broker-launch>" in str(safe)
    assert CodexCliMcpTeacherAdapter.prompt_policy_spec.prompt_contract_id == (
        "codex_cli_mcp_repository_task_context_v1"
    )


def test_teacher_refuses_non_training_or_model_substitution(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del fake_codex
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "inherited_codex_login")
    _identity, capabilities = discover_capabilities(force=True)
    with pytest.raises(ValueError, match="captured training"):
        teacher_settings(
            {"campaign_role": "heldout", "capture_training_transcript": True},
            capabilities,
            task_wall_time_s=300,
        )
    with pytest.raises(ValueError, match="requires gpt-5.4"):
        teacher_settings(
            {
                "campaign_role": "training",
                "capture_training_transcript": True,
                "model_id": "other",
            },
            capabilities,
            task_wall_time_s=300,
        )


def test_teacher_broker_limits_are_all_or_none_and_bounded(
    fake_codex: tuple[Path, Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del fake_codex
    monkeypatch.setenv("VERIGYM_CODEX_AUTH_MODE", "inherited_codex_login")
    _identity, capabilities = discover_capabilities(force=True)
    common = {"campaign_role": "training", "capture_training_transcript": True}
    with pytest.raises(ValueError, match="limits must be configured together"):
        teacher_settings(
            {**common, "max_tool_calls": 32},
            capabilities,
            task_wall_time_s=600,
        )
    with pytest.raises(ValueError, match="patch limit"):
        teacher_settings(
            {
                **common,
                "max_tool_calls": 8,
                "max_patch_calls": 9,
                "max_consecutive_rejected_calls": 3,
            },
            capabilities,
            task_wall_time_s=600,
        )


def test_teacher_broker_limit_is_an_infrastructure_valid_agent_failure() -> None:
    stats = _broker_stats(tool_calls=32)
    stats = RepositoryToolBrokerStats(
        **{
            **stats.__dict__,
            "limit_failure": "repository_tool_call_limit",
            "max_tool_calls": 32,
            "max_patch_calls": 8,
            "max_consecutive_rejected_calls": 3,
        }
    )
    failure = _preparse_process_failure(_timed_out_process(), stats)

    assert failure is not None
    assert failure.failure.kind == "agent"
    assert failure.failure.category == "broker_resource_limit"
    assert failure.failure.infrastructure is False


def test_teacher_missing_provider_usage_is_infrastructure_invalid() -> None:
    parsed = parse_event_stream('{"type":"turn.completed"}')
    failure = _provider_usage_failure(parsed)

    assert failure is not None
    assert failure.failure.kind == "runtime"
    assert failure.failure.category == "provider_usage_missing"
    assert failure.failure.infrastructure is True
