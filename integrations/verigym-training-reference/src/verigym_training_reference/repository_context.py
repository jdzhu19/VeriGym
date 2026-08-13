"""Deterministic, bounded context projection for repository rollouts."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, cast

from verigym.core.artifact_policy import bound_text, bound_value

REPOSITORY_OBSERVATION_MAX_BYTES = 32 * 1024

_TASK_DESCRIPTION_BYTES = 4 * 1024
_SELECTED_FILES_BYTES = 4 * 1024
_VISIBLE_DIRECTORIES_BYTES = 4 * 1024
_VISIBLE_FILES_BYTES = 8 * 1024
_TOOL_STDOUT_BYTES = 16 * 1024
_TOOL_STDERR_BYTES = 2 * 1024
_SMALL_VALUE_BYTES = 2 * 1024
_PREVIOUS_ACTION_BYTES = 4 * 1024
_HISTORY_BYTES = 8 * 1024
_HISTORY_TOOL_STDOUT_BYTES = 3 * 1024
_HISTORY_TOOL_STDERR_BYTES = 512


def project_repository_observation(
    value: object,
    *,
    max_bytes: int = REPOSITORY_OBSERVATION_MAX_BYTES,
) -> tuple[object, bool]:
    """Project one public observation into a prompt-safe repository context.

    Repository tasks can contain thousands of files. The ordinary initial observation exposes
    their complete flat inventory, which is useful for audit but is not a usable model prompt.
    This projection keeps a shallow directory outline, a bounded shallow-first file sample, and
    bounded selected/tool content. Omission counts remain explicit.
    """

    if max_bytes < 4 * 1024:
        raise ValueError("repository observation projection requires at least 4096 bytes")
    if not isinstance(value, dict):
        return bound_value(value, max_bytes)
    prior_projection = value.get("context_projection")
    if (
        isinstance(prior_projection, dict)
        and prior_projection.get("format_id") == "verigym_repository_context_projection_v1"
    ):
        bounded, final_truncated = bound_value(value, max_bytes)
        if final_truncated:
            raise RuntimeError("broker-projected repository context exceeds its byte bound")
        return bounded, bool(prior_projection.get("content_truncated"))

    raw_visible = value.get("visible_files", [])
    visible = sorted(
        {item for item in raw_visible if isinstance(item, str)}
        if isinstance(raw_visible, list)
        else set(),
        key=lambda item: (_path_depth(item), item),
    )
    directories = sorted(_directory_outline(visible), key=lambda item: (_path_depth(item), item))
    visible_preview = _bounded_string_list(visible, _VISIBLE_FILES_BYTES)
    directory_preview = _bounded_string_list(directories, _VISIBLE_DIRECTORIES_BYTES)

    selected, selected_truncated = _project_selected_files(value.get("selected_files"))
    previous, previous_truncated = _project_tool_result(value.get("previous_tool_result"))
    task_description, task_description_truncated = _optional_text(
        value.get("task_description"), _TASK_DESCRIPTION_BYTES
    )
    message, message_truncated = _optional_text(value.get("message"), _SMALL_VALUE_BYTES)
    reminders, reminders_truncated = _project_reminders(value.get("policy_reminders"))

    projected: dict[str, Any] = {
        "schema_version": value.get("schema_version"),
        "task_id": value.get("task_id"),
        "task_description": task_description,
        "visible_directory_outline": directory_preview,
        "visible_files": visible_preview,
        "selected_files": selected,
        "previous_tool_result": previous,
        "remaining_budget": _bounded_mapping(value.get("remaining_budget")),
        "diff_summary": _bounded_mapping(value.get("diff_summary")),
        "policy_reminders": reminders,
        "episode_status": value.get("episode_status"),
        "message": message,
    }
    projection = {
        "format_id": "verigym_repository_context_projection_v1",
        "rolling_context": True,
        "visible_file_count": len(visible),
        "visible_file_included_count": len(visible_preview),
        "visible_file_omitted_count": len(visible) - len(visible_preview),
        "visible_directory_count": len(directories),
        "visible_directory_included_count": len(directory_preview),
        "visible_directory_omitted_count": len(directories) - len(directory_preview),
        "selected_files_truncated": selected_truncated,
        "previous_tool_result_truncated": previous_truncated,
        "task_description_truncated": task_description_truncated,
        "message_truncated": message_truncated,
        "policy_reminders_truncated": reminders_truncated,
    }
    projection["content_truncated"] = any(
        (
            projection["visible_file_omitted_count"],
            projection["visible_directory_omitted_count"],
            selected_truncated,
            previous_truncated,
            task_description_truncated,
            message_truncated,
            reminders_truncated,
        )
    )
    projected["context_projection"] = projection
    bounded, final_truncated = bound_value(projected, max_bytes)
    if final_truncated:
        raise RuntimeError("repository context projection exceeded its deterministic byte bound")
    return bounded, bool(projection["content_truncated"])


def repository_turn_messages(
    *,
    task_id: str,
    task_description: object,
    contract: dict[str, Any],
    public_test_ids: object,
    observation: object,
    broker_observation_truncated: bool,
    state: object,
    turn: int,
    previous_action: dict[str, Any] | None,
    history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build one self-contained turn without replaying unbounded raw action history."""

    projected, projected_truncated = project_repository_observation(observation)
    bounded_description, task_description_truncated = _optional_text(
        task_description, _TASK_DESCRIPTION_BYTES
    )
    bounded_history = _bounded_history(history)
    payload = {
        "task": {
            "id": task_id,
            "description": bounded_description,
            "submission_kind": "patch",
        },
        "prompt_contract": contract,
        "public_test_ids": public_test_ids if isinstance(public_test_ids, list) else [],
        "turn": turn,
        "state": state if isinstance(state, str) else "awaiting_action",
        "previous_action": previous_action,
        "bounded_history": bounded_history,
        "observation": projected,
        "context_policy": {
            "format_id": "verigym_repository_rolling_context_v1",
            "broker_observation_truncated": broker_observation_truncated,
            "projected_observation_truncated": projected_truncated,
            "raw_action_history_included": False,
            "latest_tool_observation_included": observation is not None,
            "task_description_truncated": task_description_truncated,
            "history_entry_count": len(history),
            "history_included_count": len(bounded_history),
            "history_omitted_count": len(history) - len(bounded_history),
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a bounded repository repair agent. Return exactly one JSON object "
                "matching the supplied repository_action.v2 contract and no prose. Every "
                "response must contain exactly the top-level keys protocol, action, and "
                "arguments. Example shape: "
                '{"protocol":"repository_action.v2","action":"read_file",'
                '"arguments":{"path":"repository/example.sv"}}. Replace the example action '
                "and arguments with the single action needed for the current turn."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        },
    ]


def repository_native_tool_messages(
    *,
    task_id: str,
    task_description: object,
    contract: dict[str, Any],
    public_test_ids: object,
    observation: object,
    broker_observation_truncated: bool,
) -> list[dict[str, str]]:
    """Build the initial prompt for a provider-native repository tool loop."""

    projected, projected_truncated = project_repository_observation(observation)
    bounded_description, task_description_truncated = _optional_text(
        task_description, _TASK_DESCRIPTION_BYTES
    )
    payload = {
        "task": {
            "id": task_id,
            "description": bounded_description,
            "submission_kind": "patch",
        },
        "repository_action_contract": contract,
        "transport": "provider_native_tool_call",
        "public_test_ids": public_test_ids if isinstance(public_test_ids, list) else [],
        "initial_observation": projected,
        "context_policy": {
            "format_id": "verigym_repository_native_tool_context_v1",
            "broker_observation_truncated": broker_observation_truncated,
            "projected_observation_truncated": projected_truncated,
            "task_description_truncated": task_description_truncated,
            "hidden_assets_included": False,
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a bounded repository repair agent. Use exactly one supplied repository "
                "function per turn and do not mix prose with a tool call. Read visible files "
                "before editing, use only declared public tests, inspect the candidate diff, "
                "then call finish. Shell, network, hidden assets, and reference solutions are "
                "unavailable."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        },
    ]


def previous_repository_action(raw_action: str, response: dict[str, Any]) -> dict[str, Any]:
    """Keep the immediately preceding action identifiable without replaying full history."""

    bounded, truncated = bound_text(raw_action, _PREVIOUS_ACTION_BYTES)
    return {
        "action_name": response.get("action_name"),
        "accepted": response.get("accepted"),
        "protocol_error": response.get("protocol_error"),
        "raw_action": bounded,
        "raw_action_sha256": hashlib.sha256(raw_action.encode("utf-8")).hexdigest(),
        "raw_action_truncated": truncated,
        "broker_response_hash": response.get("response_hash"),
    }


def repository_history_entry(raw_action: str, response: dict[str, Any]) -> dict[str, Any]:
    """Build a compact prior-turn record for bounded multi-turn working context."""

    return {
        "action": previous_repository_action(raw_action, response),
        "observation": _history_observation(response.get("observation")),
        "state": response.get("state"),
        "turn": response.get("turn"),
    }


def _directory_outline(paths: list[str]) -> set[str]:
    directories: set[str] = set()
    for raw in paths:
        path = PurePosixPath(raw)
        parts = path.parts[:-1]
        for length in range(1, len(parts) + 1):
            directories.add(PurePosixPath(*parts[:length]).as_posix() + "/")
    return directories


def _path_depth(value: str) -> int:
    return len(PurePosixPath(value.rstrip("/")).parts)


def _bounded_string_list(values: list[str], max_bytes: int) -> list[str]:
    result: list[str] = []
    used = 2
    for value in values:
        rendered = json.dumps(value, ensure_ascii=False).encode("utf-8")
        added = len(rendered) + (1 if result else 0)
        if used + added > max_bytes:
            break
        result.append(value)
        used += added
    return result


def _bounded_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used = 2
    for entry in reversed(history):
        rendered = json.dumps(
            entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        added = len(rendered) + (1 if selected else 0)
        if used + added > _HISTORY_BYTES:
            break
        selected.append(entry)
        used += added
    return list(reversed(selected))


def _history_observation(value: object) -> object | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        bounded, _truncated = bound_value(value, _SMALL_VALUE_BYTES)
        return cast(object, bounded)
    result = value.get("previous_tool_result")
    tool: object | None = None
    if isinstance(result, dict):
        stdout, stdout_truncated = _optional_text(result.get("stdout"), _HISTORY_TOOL_STDOUT_BYTES)
        stderr, stderr_truncated = _optional_text(result.get("stderr"), _HISTORY_TOOL_STDERR_BYTES)
        tool = {
            "tool": result.get("tool"),
            "success": result.get("success"),
            "category": result.get("category"),
            "message": result.get("message"),
            "stdout": stdout,
            "stderr": stderr,
            "output_truncated": bool(result.get("output_truncated")) or stdout_truncated,
            "history_projection_truncated": stdout_truncated or stderr_truncated,
        }
    return {
        "previous_tool_result": tool,
        "diff_summary": _bounded_mapping(value.get("diff_summary")),
        "message": value.get("message"),
    }


def _project_selected_files(value: object) -> tuple[dict[str, str], bool]:
    if not isinstance(value, dict):
        return {}, value is not None
    result: dict[str, str] = {}
    remaining = _SELECTED_FILES_BYTES
    truncated = False
    for path, content in sorted(value.items(), key=lambda item: str(item[0])):
        if not isinstance(path, str) or not isinstance(content, str):
            truncated = True
            continue
        overhead = len(json.dumps(path, ensure_ascii=False).encode("utf-8")) + 4
        allowance = max(0, remaining - overhead)
        bounded, shortened = bound_text(content, allowance)
        result[path] = bounded
        remaining -= overhead + len(bounded.encode("utf-8"))
        truncated = truncated or shortened
        if remaining <= 4:
            truncated = truncated or len(result) < len(value)
            break
    return result, truncated


def _project_tool_result(value: object) -> tuple[object | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, dict):
        bounded, truncated = bound_value(value, _SMALL_VALUE_BYTES)
        return bounded, truncated
    stdout, stdout_truncated = _optional_text(value.get("stdout"), _TOOL_STDOUT_BYTES)
    stderr, stderr_truncated = _optional_text(value.get("stderr"), _TOOL_STDERR_BYTES)
    message, message_truncated = _optional_text(value.get("message"), _SMALL_VALUE_BYTES)
    metadata, metadata_truncated = bound_value(value.get("metadata", {}), _SMALL_VALUE_BYTES)
    artifacts, artifacts_truncated = bound_value(value.get("artifacts", []), _SMALL_VALUE_BYTES)
    diagnostics, diagnostics_truncated = bound_value(
        value.get("diagnostics", []), _SMALL_VALUE_BYTES
    )
    projected = {
        "schema_version": value.get("schema_version"),
        "tool": value.get("tool"),
        "success": value.get("success"),
        "category": value.get("category"),
        "message": message,
        "exit_code": value.get("exit_code"),
        "stdout": stdout,
        "stderr": stderr,
        "duration_s": value.get("duration_s"),
        "output_truncated": bool(value.get("output_truncated")) or stdout_truncated,
        "artifacts": artifacts,
        "diagnostics": diagnostics,
        "metadata": metadata,
    }
    return projected, any(
        (
            stdout_truncated,
            stderr_truncated,
            message_truncated,
            metadata_truncated,
            artifacts_truncated,
            diagnostics_truncated,
        )
    )


def _project_reminders(value: object) -> tuple[list[str], bool]:
    if not isinstance(value, list):
        return [], value is not None
    strings = [item for item in value if isinstance(item, str)]
    projected = _bounded_string_list(strings, _SMALL_VALUE_BYTES)
    return projected, len(projected) != len(value)


def _bounded_mapping(value: object) -> object:
    bounded, _truncated = bound_value(value if isinstance(value, dict) else {}, _SMALL_VALUE_BYTES)
    return bounded


def _optional_text(value: object, max_bytes: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, str):
        return None, True
    return bound_text(value, max_bytes)


__all__ = [
    "REPOSITORY_OBSERVATION_MAX_BYTES",
    "project_repository_observation",
    "previous_repository_action",
    "repository_history_entry",
    "repository_turn_messages",
]
