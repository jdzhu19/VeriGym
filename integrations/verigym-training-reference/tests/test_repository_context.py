from __future__ import annotations

import hashlib
import json

from verigym_training_reference.repository_context import (
    REPOSITORY_OBSERVATION_MAX_BYTES,
    previous_repository_action,
    project_repository_observation,
    repository_history_entry,
    repository_turn_messages,
)


def _large_observation() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "task_id": "hwe-bench/openhwgroup__cva6__pr-2170",
        "task_description": "repair the uncacheable store lane" * 1000,
        "visible_files": [
            f"repository/core/cache/subsystem_{index:04d}/module_{index:04d}.sv"
            for index in range(6000)
        ],
        "selected_files": {"README.md": "instructions\n" * 2000},
        "previous_tool_result": None,
        "remaining_budget": {"turns": 128, "tool_calls": 512},
        "diff_summary": {"changed_files": [], "added_lines": 0, "deleted_lines": 0},
        "policy_reminders": ["Only task-allowed tools may be used."],
        "episode_status": "running",
        "message": None,
    }


def test_repository_context_projects_large_tree_with_explicit_omission_counts() -> None:
    projected, truncated = project_repository_observation(_large_observation())

    assert truncated is True
    assert isinstance(projected, dict)
    assert len(json.dumps(projected, separators=(",", ":")).encode()) < (
        REPOSITORY_OBSERVATION_MAX_BYTES
    )
    projection = projected["context_projection"]
    assert projection["format_id"] == "verigym_repository_context_projection_v1"
    assert projection["visible_file_count"] == 6000
    assert projection["visible_file_omitted_count"] > 0
    assert "repository/" in projected["visible_directory_outline"]
    assert projected["task_description"]


def test_repository_context_projection_is_idempotent_at_the_broker_boundary() -> None:
    first, first_truncated = project_repository_observation(_large_observation())
    second, second_truncated = project_repository_observation(first)

    assert second == first
    assert second_truncated == first_truncated is True


def test_repository_turn_context_does_not_replay_raw_action_history() -> None:
    raw_action = "x" * 20_000
    previous = previous_repository_action(
        raw_action,
        {
            "accepted": True,
            "action_name": "read_file",
            "protocol_error": None,
            "response_hash": "a" * 64,
        },
    )
    messages = repository_turn_messages(
        task_id="suite/task",
        task_description="repair it",
        contract={"protocol": "repository_action.v2"},
        public_test_ids=[],
        observation={
            "task_id": "suite/task",
            "previous_tool_result": {
                "tool": "file.read",
                "success": True,
                "category": "success",
                "stdout": "source\n" * 10_000,
            },
        },
        broker_observation_truncated=False,
        state="awaiting_action",
        turn=1,
        previous_action=previous,
        history=[
            repository_history_entry(
                '{"action":"read_file"}',
                {
                    "turn": 0,
                    "state": "awaiting_action",
                    "observation": {
                        "previous_tool_result": {
                            "tool": "file.read",
                            "success": True,
                            "category": "success",
                            "stdout": "older source\n" * 1000,
                        }
                    },
                },
            )
        ],
    )
    payload = json.loads(messages[1]["content"])

    assert len(messages) == 2
    assert (
        '{"protocol":"repository_action.v2","action":"read_file",'
        '"arguments":{"path":"repository/example.sv"}}' in messages[0]["content"]
    )
    assert payload["context_policy"]["raw_action_history_included"] is False
    assert payload["context_policy"]["history_included_count"] == 1
    assert payload["bounded_history"][0]["observation"]["previous_tool_result"]["stdout"]
    assert payload["previous_action"]["raw_action_truncated"] is True
    assert (
        payload["previous_action"]["raw_action_sha256"]
        == hashlib.sha256(raw_action.encode()).hexdigest()
    )
    assert len(payload["observation"]["previous_tool_result"]["stdout"].encode()) <= 16 * 1024
    assert len(messages[1]["content"].encode()) < REPOSITORY_OBSERVATION_MAX_BYTES
