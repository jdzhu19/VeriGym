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
from verigym.schemas.tool import ToolResult


class _Bridge:
    def __init__(self, *, path_failure: str | None = None, patch_rejected: bool = False) -> None:
        self.path_failure = path_failure
        self.patch_rejected = patch_rejected

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
        return ToolResult(tool=tool, success=True, category=ErrorCategory.SUCCESS)


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
    assert payload["error_subcategory"] == "patch_rejected"
    assert payload["state"]["phase"] == "working"
    assert "apply_patch" in payload["next_allowed_actions"]
    assert "/private/site/path" not in json.dumps(response)
    assert broker.stats().policy_failure is None


@pytest.mark.parametrize(
    "failure",
    [
        "absolute path access denied: /private/site/path",
        "workspace symlink is forbidden: rtl/link.v",
        "workspace hardlink is forbidden: rtl/alias.v",
        "hidden asset access denied: hidden/reference.v",
    ],
)
def test_path_boundary_violations_remain_terminal_and_redacted(
    tmp_path: Path,
    failure: str,
) -> None:
    broker = _broker(tmp_path, _Bridge(path_failure=failure))

    response = broker._dispatch(  # noqa: SLF001
        {"name": "read_file", "arguments": {"path": "rtl/counter.v"}}
    )
    payload = _payload(response)

    assert response["isError"] is True
    assert payload["error_subcategory"] == "workspace_path_policy"
    assert payload["state"]["phase"] == "terminal_failure"
    assert payload["next_allowed_actions"] == []
    assert "/private/site/path" not in json.dumps(response)
    assert broker.stats().policy_failure is not None


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
