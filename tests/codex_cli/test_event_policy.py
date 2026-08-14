from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym_codex_cli.event_policy import (
    EventPolicyContext,
    evaluate_event_policy,
)
from verigym_codex_cli.events import parse_event_stream

pytestmark = [pytest.mark.codex_cli, pytest.mark.codex_cli_readonly_agent]


def _context(tmp_path: Path) -> EventPolicyContext:
    workspace = tmp_path / "fresh-empty"
    workspace.mkdir(exist_ok=True)
    return EventPolicyContext(
        working_directory=workspace,
        working_directory_identity="fresh_empty_temporary_directory",
        sandbox_identity="read-only",
        network_policy="disabled",
        mcp_policy="disabled",
    )


def _stream(*events: dict[str, object]) -> str:
    records = [*events, {"type": "turn.completed"}]
    return "\n".join(json.dumps(record, sort_keys=True) for record in records)


def _item(item_type: str, **values: object) -> dict[str, object]:
    return {"type": "item.completed", "item": {"type": item_type, **values}}


@pytest.mark.parametrize(
    ("event", "classification"),
    [
        (_item("plan", status="completed"), "harness_plan_only"),
        (_item("file_read", path="rtl/candidate.v"), "read_only_empty_workdir_inspection"),
        (
            _item("command_execution", command="pwd", status="completed"),
            "read_only_empty_workdir_inspection",
        ),
        (
            _item(
                "command_execution",
                command="/bin/bash -lc \"sed -n '1,160p' README.md\"",
                status="failed",
                exit_code=1,
            ),
            "read_only_empty_workdir_inspection",
        ),
    ],
)
def test_typed_policy_permits_only_classified_non_side_effecting_events(
    tmp_path: Path,
    event: dict[str, object],
    classification: str,
) -> None:
    parsed = parse_event_stream(_stream(event))
    result = evaluate_event_policy(
        parsed,
        _context(tmp_path),
        policy_id="typed_readonly_empty_workdir_v1",
    )
    assert result.policy_passed is True
    assert result.tool_event_count == 1
    assert result.classified_events[0].classification == classification
    assert result.classified_events[0].allowed is True


@pytest.mark.parametrize(
    ("event", "classification"),
    [
        (_item("file_write", path="rtl/candidate.v"), "side_effecting_local_tool"),
        (_item("file_change", path="rtl/candidate.v"), "side_effecting_local_tool"),
        (_item("file_read", path="../hidden/test.sv"), "unknown_tool"),
        (_item("file_read", path="/etc/passwd"), "unknown_tool"),
        (_item("file_read", path=".codex/config.toml"), "unknown_tool"),
        (
            _item("command_execution", command="curl https://example.invalid"),
            "network_tool",
        ),
        (_item("mcp_tool_call", name="mcp.read"), "mcp_or_external_tool"),
        (_item("tool_call", name="custom.external"), "mcp_or_external_tool"),
        (_item("future_tool", name="unclassified"), "unknown_tool"),
    ],
)
def test_typed_policy_fails_closed_for_forbidden_and_unknown_events(
    tmp_path: Path,
    event: dict[str, object],
    classification: str,
) -> None:
    parsed = parse_event_stream(_stream(event))
    result = evaluate_event_policy(
        parsed,
        _context(tmp_path),
        policy_id="typed_readonly_empty_workdir_v1",
    )
    assert result.policy_passed is False
    assert result.forbidden_event_count == 1
    assert result.classified_events[0].classification == classification
    assert result.classified_events[0].allowed is False


def test_zero_tools_policy_accepts_only_a_stream_with_no_tool_availability_events(
    tmp_path: Path,
) -> None:
    no_tools = evaluate_event_policy(
        parse_event_stream(_stream()),
        _context(tmp_path),
        policy_id="text_only_zero_tools_v1",
    )
    assert no_tools.policy_passed is True
    assert no_tools.tool_event_count == 0

    plan = evaluate_event_policy(
        parse_event_stream(_stream(_item("plan", status="completed"))),
        _context(tmp_path),
        policy_id="text_only_zero_tools_v1",
    )
    assert plan.policy_passed is False
    assert plan.tool_event_count == 1


def test_public_test_command_accounting_counts_only_exact_started_invocations() -> None:
    parsed = parse_event_stream(
        _stream(
            {
                "type": "item.started",
                "item": {
                    "type": "command_execution",
                    "command": "verigym-public-test list",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "verigym-public-test list",
                    "status": "completed",
                },
            },
            {
                "type": "item.started",
                "item": {
                    "type": "command_execution",
                    "command": (
                        "/bin/bash -lc '/usr/local/bin/verigym-public-test run counter-wrap-public'"
                    ),
                },
            },
            {
                "type": "item.started",
                "item": {
                    "type": "command_execution",
                    "command": "echo verigym-public-test list",
                },
            },
        )
    )
    assert parsed.command_count == 3
    assert parsed.public_test_command_count == 2


def test_provider_usage_preserves_cached_input_tokens() -> None:
    parsed = parse_event_stream(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cached_input_tokens": 75,
                },
            }
        )
    )

    assert parsed.input_tokens == 100
    assert parsed.output_tokens == 20
    assert parsed.total_tokens == 120
    assert parsed.cached_input_tokens == 75


def test_sanitized_historical_six_events_have_exact_readonly_classification(
    tmp_path: Path,
) -> None:
    fixture = Path("tests/fixtures/codex_cli/historical_track_a_counter_sanitized.jsonl")
    raw = fixture.read_text(encoding="utf-8")
    assert "private" not in raw.lower()
    assert "reasoning" not in raw.lower()
    parsed = parse_event_stream(raw)
    result = evaluate_event_policy(
        parsed,
        _context(tmp_path),
        policy_id="typed_readonly_empty_workdir_v1",
    )
    assert result.policy_passed is True
    assert result.tool_event_count == 6
    assert result.read_only_tool_event_count == 6
    assert result.side_effecting_tool_event_count == 0
    assert result.external_network_tool_event_count == 0
    assert result.mcp_tool_event_count == 0
    assert result.workspace_write_count == 0
    assert {event.classification for event in result.classified_events} == {
        "read_only_empty_workdir_inspection"
    }
    assert all(event.execution_occurred is True for event in result.classified_events)
    assert all(event.shell_event is True for event in result.classified_events)
    assert [event.output_returned_to_model for event in result.classified_events] == [
        False,
        True,
        False,
        True,
        False,
        True,
    ]
