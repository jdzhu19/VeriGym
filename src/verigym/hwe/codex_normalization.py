"""Normalize public Codex native-shell evidence into the HWE six-tool transcript."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_ID, canonical_hwe_action_json
from verigym.hwe.trajectory import HweEpisodeBudget, HweNormalizedEvent


class HweCausalValidationError(ValueError):
    """A successful public episode that cannot be causally materialized for SFT."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def normalize_codex_hwe_events(
    *,
    protocol_records: Sequence[Mapping[str, object]],
    app_server_jsonl: str,
    terminal_success: bool,
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> tuple[list[HweNormalizedEvent], list[dict[str, Any]]]:
    """Map completed commands/filesystem actions, real patchUpdated diffs, and finish."""

    if not terminal_success:
        raise ValueError("HWE normalization requires a successful terminal turn")
    patches = _patch_updates(app_server_jsonl)
    patch_index = 0
    normalized: list[HweNormalizedEvent] = []
    messages: list[dict[str, Any]] = []
    budget = HweEpisodeBudget(profile_id=profile_id)
    for raw in protocol_records:
        if raw.get("completed") is not True:
            raise ValueError("HWE protocol record is incomplete")
        method = raw.get("method")
        action = raw.get("action")
        changed = _string_tuple(raw.get("changed_paths"))
        if action is None and method in {
            "fs/writeFile",
            "fs/createDirectory",
            "fs/remove",
            "fs/copy",
        }:
            if not changed:
                continue
            if patch_index >= len(patches):
                raise HweCausalValidationError(
                    "filesystem_mutation_without_patch_update",
                    "filesystem mutation lacks patchUpdated; apply_patch cannot be fabricated",
                )
            action = "apply_patch"
            patch, patch_paths = patches[patch_index]
            if patch_paths and set(patch_paths) != set(changed):
                raise HweCausalValidationError(
                    "patch_update_path_mismatch",
                    "patchUpdated paths do not match the observed workspace mutation",
                )
            arguments = {"patch": patch}
            patch_index += 1
            mapping = "item/fileChange/patchUpdated->apply_patch"
        elif action in {"list_files", "read_file", "shell"}:
            arguments_value = raw.get("arguments")
            if not isinstance(arguments_value, dict):
                raise ValueError("HWE protocol record arguments are malformed")
            arguments = dict(arguments_value)
            mapping = (
                "completed interrupted process/start+process/signal->shell"
                if action == "shell" and raw.get("interrupted_by_agent") is True
                else f"completed {method}->{action}"
            )
        else:
            continue
        canonical = json.loads(
            canonical_hwe_action_json(str(action), arguments, profile_id=profile_id)
        )
        arguments = canonical["arguments"]
        before = _integer(raw.get("workspace_epoch_before"), "workspace_epoch_before")
        after = _integer(raw.get("workspace_epoch_after"), "workspace_epoch_after")
        budget.observe(str(action), changed_paths=changed)
        event = HweNormalizedEvent(
            sequence=len(normalized),
            action=action,  # type: ignore[arg-type]
            arguments=arguments,
            workspace_epoch_before=before,
            workspace_epoch_after=after,
            changed_paths=changed,
            raw_observation_sha256=_optional_string(raw.get("raw_sha256")),
            raw_observation_bytes=_integer(raw.get("raw_bytes", 0), "raw_bytes"),
            compact_observation_sha256=_optional_string(raw.get("compact_sha256")),
            compact_observation_tokens=_integer(raw.get("compact_tokens", 0), "compact_tokens"),
            observation_rule_id=_optional_string(raw.get("observation_rule_id")),
            observation_omitted=raw.get("observation_omitted") is True,
            exit_code=_optional_integer(raw.get("exit_code"), "exit_code"),
            duration_ms=_optional_integer(raw.get("duration_ms"), "duration_ms"),
            raw_stdout_bytes=_integer(raw.get("raw_stdout_bytes", 0), "raw_stdout_bytes"),
            raw_stderr_bytes=_integer(raw.get("raw_stderr_bytes", 0), "raw_stderr_bytes"),
            raw_stdout_sha256=_optional_string(raw.get("raw_stdout_sha256")),
            raw_stderr_sha256=_optional_string(raw.get("raw_stderr_sha256")),
            compile_observed=raw.get("compile_observed") is True,
            simulation_observed=raw.get("simulation_observed") is True,
            event_mapping=mapping,
        )
        normalized.append(event)
        observation = _optional_string(raw.get("compact_text")) or _status_text(raw)
        _append_turn(messages, event, observation, profile_id=profile_id)
    if patch_index != len(patches):
        raise HweCausalValidationError(
            "patch_update_without_observed_mutation",
            "patchUpdated has no causally observed filesystem mutation",
        )
    epoch = normalized[-1].workspace_epoch_after if normalized else 0
    finish = HweNormalizedEvent(
        sequence=len(normalized),
        action="finish",
        arguments={"summary": "Candidate completed and submitted for verifier resolution."},
        workspace_epoch_before=epoch,
        workspace_epoch_after=epoch,
        event_mapping="successful turn/completed->synthetic finish",
    )
    budget.observe("finish")
    normalized.append(finish)
    _append_turn(messages, finish, '{"status":"finished"}', profile_id=profile_id)
    messages.append(
        {
            "role": "assistant",
            "content": "Candidate submitted to the frozen HWE verifier.",
        }
    )
    return normalized, messages


def _patch_updates(stdout: str) -> list[tuple[str, tuple[str, ...]]]:
    patches: list[tuple[str, tuple[str, ...]]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("HWE app-server public stream is malformed") from exc
        if not isinstance(event, dict):
            raise ValueError("HWE app-server event is not an object")
        event_type = event.get("type")
        if event_type == "file_change.patch_updated":
            patch = event.get("patch")
            if not isinstance(patch, str) or not patch:
                raise ValueError("HWE patchUpdated event omits its raw incremental diff")
            paths_value = event.get("paths", [])
            if not isinstance(paths_value, list) or any(
                not isinstance(path, str) for path in paths_value
            ):
                raise ValueError("HWE patchUpdated event has malformed changed paths")
            patches.append((patch, tuple(paths_value)))
        elif event_type in {"reasoning", "reasoning_summary", "plan", "plan_update"}:
            continue
    return patches


def _append_turn(
    messages: list[dict[str, Any]],
    event: HweNormalizedEvent,
    observation: str,
    *,
    profile_id: str,
) -> None:
    call_id = f"hwe-call-{event.sequence:04d}"
    canonical = json.loads(
        canonical_hwe_action_json(event.action, event.arguments, profile_id=profile_id)
    )
    messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": event.action,
                        "arguments": json.dumps(
                            canonical["arguments"],
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    },
                }
            ],
        }
    )
    messages.append(
        {
            "role": "tool",
            "content": observation,
            "tool_call_id": call_id,
            "name": event.action,
        }
    )


def _status_text(record: Mapping[str, object]) -> str:
    return json.dumps(
        {"exit_code": record.get("exit_code"), "changed_paths": record.get("changed_paths", ())},
        sort_keys=True,
        separators=(",", ":"),
    )


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"HWE {label} is not a non-negative integer")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _integer(value, label)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("HWE changed_paths is malformed")
    return tuple(value)


__all__ = ["HweCausalValidationError", "normalize_codex_hwe_events"]
