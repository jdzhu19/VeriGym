from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verigym.core.errors import PathPolicyError
from verigym.core.repository_tool_broker import (
    RepositoryToolBroker,
    RepositoryToolBrokerLimits,
)
from verigym.schemas.common import ErrorCategory
from verigym.schemas.tool import CompletedCommand, ToolResult


class _Bridge:
    def __init__(
        self,
        *,
        path_failure: str | None = None,
        patch_rejected: bool = False,
        result_category: ErrorCategory | None = None,
        result_message: str = "",
        public_result: CompletedCommand | None = None,
    ) -> None:
        self.path_failure = path_failure
        self.patch_rejected = patch_rejected
        self.result_category = result_category
        self.result_message = result_message
        self.public_result = public_result

    def invoke_workspace_tool(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        if self.path_failure is not None:
            raise PathPolicyError(self.path_failure)
        if self.patch_rejected:
            return ToolResult(
                tool=tool,
                success=False,
                category=ErrorCategory.PERMISSION_DENIED,
                message="patch context does not match the workspace at /private/site/path",
            )
        if self.result_category is not None:
            return ToolResult(
                tool=tool,
                success=False,
                category=self.result_category,
                message=self.result_message,
            )
        return ToolResult(tool=tool, success=True, category=ErrorCategory.SUCCESS)

    def execute_public_test(self, _test_id: str) -> CompletedCommand:
        if self.public_result is None:
            raise AssertionError("no public-test result was configured")
        return self.public_result


def _broker(tmp_path: Path, bridge: _Bridge) -> RepositoryToolBroker:
    return RepositoryToolBroker(
        bridge=bridge,  # type: ignore[arg-type]
        socket_path=tmp_path / "broker" / "mcp.sock",
        public_test_ids=(),
    )


def _payload(response: dict[str, Any]) -> dict[str, Any]:
    content = response["content"]
    assert isinstance(content, list)
    observation = json.loads(content[0]["text"])
    assert isinstance(observation, dict)
    result = observation["result"]
    assert isinstance(result, dict)
    return result


def test_recoverable_broker_error_returns_safe_state_and_next_actions(tmp_path: Path) -> None:
    broker = _broker(tmp_path, _Bridge(patch_rejected=True))

    response = broker._dispatch(  # noqa: SLF001
        {
            "name": "apply_patch",
            "arguments": {
                "patch": (
                    "*** Begin Patch\n*** Update File: rtl/counter.v\n@@\n-old\n+new\n*** End Patch"
                )
            },
        }
    )
    payload = _payload(response)

    assert response["isError"] is True
    assert payload["error_subcategory"] == "patch_context"
    assert payload["state"]["phase"] == "working"
    assert "apply_patch" in payload["next_allowed_actions"]
    assert "/private/site/path" not in json.dumps(response)
    assert broker.stats().policy_failure is None


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("invalid unified patch hunk header", "patch_header"),
        ("invalid unified patch hunk body", "patch_body"),
    ],
)
def test_malformed_patch_hunks_are_recoverable(
    message: str,
    category: str,
    tmp_path: Path,
) -> None:
    broker = _broker(
        tmp_path,
        _Bridge(result_category=ErrorCategory.PERMISSION_DENIED, result_message=message),
    )

    response = broker._dispatch(  # noqa: SLF001
        {
            "name": "apply_patch",
            "arguments": {"patch": "--- a/rtl/counter.v\n+++ b/rtl/counter.v\n@@ broken\n"},
        }
    )
    payload = _payload(response)
    stats = broker.stats()

    assert response["isError"] is True
    assert payload["error_subcategory"] == category
    assert payload["state"]["phase"] == "working"
    assert "apply_patch" in payload["next_allowed_actions"]
    assert stats.policy_failure is None
    assert stats.policy_failure_subcategory is None
    assert stats.rejected_calls == 1


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        ("absolute path access denied: /private/site/path", "absolute"),
        ("parent path traversal is not allowed: ../secret", "traversal"),
        ("path is outside editable globs: rtl/other.v", "outside_editable"),
        ("path is read-only: rtl/locked.v", "readonly"),
        ("workspace symlink is forbidden: rtl/link.v", "symlink"),
        ("workspace hardlink is forbidden: rtl/alias.v", "hardlink"),
        ("hidden asset access denied: hidden/reference.v", "hidden_or_protected"),
        ("repository path policy denied the request", "unspecified"),
    ],
)
def test_path_boundary_violations_remain_terminal_and_redacted(
    tmp_path: Path,
    failure: str,
    category: str,
) -> None:
    broker = _broker(tmp_path, _Bridge(path_failure=failure))

    response = broker._dispatch(  # noqa: SLF001
        {"name": "read_file", "arguments": {"path": "rtl/counter.v"}}
    )
    payload = _payload(response)

    assert response["isError"] is True
    assert payload["error_subcategory"] == "workspace_path_policy"
    assert payload["terminal_tool_name"] == "read_file"
    assert payload["path_violation_category"] == category
    assert payload["state"]["phase"] == "terminal_failure"
    assert payload["next_allowed_actions"] == []
    assert "/private/site/path" not in json.dumps(response)
    stats = broker.stats()
    assert stats.policy_failure is not None
    assert stats.policy_failure_subcategory == "workspace_path_policy"
    assert stats.terminal_tool_name == "read_file"
    assert stats.terminal_path_category == category
    assert stats.infrastructure_failure_subcategory is None
    assert broker.cancellation_event.is_set()


def test_workspace_internal_error_records_only_a_bounded_subcategory(tmp_path: Path) -> None:
    broker = _broker(
        tmp_path,
        _Bridge(
            result_category=ErrorCategory.INTERNAL_ERROR,
            result_message="private implementation detail at /private/site/path",
        ),
    )

    response = broker._dispatch(  # noqa: SLF001
        {"name": "read_file", "arguments": {"path": "repository/completion.txt"}}
    )
    payload = _payload(response)
    stats = broker.stats()

    assert response["isError"] is True
    assert payload["state"]["phase"] == "terminal_failure"
    assert payload["next_allowed_actions"] == []
    assert stats.infrastructure_failure is not None
    assert stats.infrastructure_failure_subcategory == "workspace_tool_internal_error"
    assert stats.policy_failure_subcategory is None


def test_commercial_feedback_worker_subcategory_reaches_broker_stats(tmp_path: Path) -> None:
    completed = CompletedCommand(
        argv=["verigym-agent-feedback", "ppa"],
        cwd=".",
        exit_code=1,
        stdout=json.dumps(
            {
                "protocol": "verigym_agent_feedback_v2",
                "category": "infrastructure_error",
                "infrastructure_subcategory": "agent_worker_scheduler",
            }
        ),
        failure_origin="control_plane",
        failure_reason="agent_worker_scheduler",
    )
    broker = RepositoryToolBroker(
        bridge=_Bridge(public_result=completed),  # type: ignore[arg-type]
        socket_path=tmp_path / "broker" / "mcp.sock",
        public_test_ids=("ppa",),
    )

    broker._run_public_test({"test_id": "ppa"})  # noqa: SLF001
    stats = broker.stats()

    assert stats.infrastructure_failure_subcategory == "agent_worker_scheduler"
    assert "/" not in (stats.infrastructure_failure or "")


def test_successful_broker_result_includes_current_minimal_state(tmp_path: Path) -> None:
    broker = _broker(tmp_path, _Bridge())

    response = broker._dispatch(  # noqa: SLF001
        {"name": "read_file", "arguments": {"path": "rtl/counter.v"}}
    )
    payload = _payload(response)

    assert response["isError"] is False
    assert payload["state"] == {
        "phase": "working",
        "patch_applied": False,
        "compile_passed": False,
        "public_feedback_observed": False,
        "latest_diff_observed": False,
        "finished": False,
    }
    assert payload["next_allowed_actions"] == [
        "list_files",
        "read_file",
        "apply_patch",
    ]


def test_limit_reaching_error_does_not_advertise_another_action(tmp_path: Path) -> None:
    broker = RepositoryToolBroker(
        bridge=_Bridge(),  # type: ignore[arg-type]
        socket_path=tmp_path / "broker" / "mcp.sock",
        public_test_ids=(),
        limits=RepositoryToolBrokerLimits(
            max_tool_calls=5,
            max_patch_calls=2,
            max_consecutive_rejected_calls=1,
        ),
    )

    response = broker._dispatch(  # noqa: SLF001
        {"name": "finish", "arguments": {}}
    )
    payload = _payload(response)

    assert payload["state"]["phase"] == "terminal_failure"
    assert payload["next_allowed_actions"] == []
    assert broker.stats().limit_failure == "repository_consecutive_rejection_limit"


def test_budget_state_reports_rounded_wall_time_without_absolute_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((100.0, 112.6, 112.6))
    monkeypatch.setattr("verigym.core.repository_tool_broker.time.monotonic", lambda: next(moments))
    broker = RepositoryToolBroker(
        bridge=_Bridge(),  # type: ignore[arg-type]
        socket_path=tmp_path / "broker" / "mcp.sock",
        public_test_ids=(),
        limits=RepositoryToolBrokerLimits(
            max_tool_calls=40,
            max_patch_calls=20,
            max_consecutive_rejected_calls=3,
        ),
        wall_time_s=300,
    )

    response = broker._dispatch(  # noqa: SLF001
        {"name": "read_file", "arguments": {"path": "rtl/counter.v"}}
    )
    state = _payload(response)["state"]
    stats = broker.stats()

    assert state["elapsed_wall_time_s"] == 13
    assert state["remaining_wall_time_s"] == 287
    assert state["max_tool_calls"] == 40
    assert state["max_patch_calls"] == 20
    assert state["max_consecutive_rejected_calls"] == 3
    assert "deadline" not in json.dumps(response).lower()
    assert stats.wall_time_s == 300
    assert stats.elapsed_wall_time_s == 13
    assert stats.remaining_wall_time_s == 287


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("invalid unified patch: expected '---' header", "patch_format"),
        ("invalid unified patch hunk header", "patch_header"),
        ("invalid unified patch hunk body", "patch_body"),
        ("patch context does not match the workspace", "patch_context"),
        ("patch hunk line counts do not match its header", "patch_count"),
        ("patch hunk is out of range or overlaps a prior hunk", "patch_range"),
        ("patch file has no hunks", "patch_empty"),
        ("renames are not supported by file.apply_patch", "patch_rename"),
    ],
)
def test_recoverable_patch_errors_have_fixed_categories(
    tmp_path: Path,
    message: str,
    category: str,
) -> None:
    broker = _broker(
        tmp_path,
        _Bridge(result_category=ErrorCategory.PERMISSION_DENIED, result_message=message),
    )

    response = broker._dispatch(  # noqa: SLF001
        {
            "name": "apply_patch",
            "arguments": {"patch": "--- a/rtl/counter.v\n+++ b/rtl/counter.v\n@@ broken\n"},
        }
    )

    assert _payload(response)["error_subcategory"] == category
    assert broker.stats().policy_failure is None
