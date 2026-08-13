"""Opt-in capture format for public multi-turn teacher transcripts."""

from __future__ import annotations

from typing import Any, Literal

from verigym.core.hashing import content_hash
from verigym.protocols.repository_action import repository_tool_definitions
from verigym.schemas.multiturn_sft import MultiTurnSftMessage, validate_terminal_finish


def build_teacher_transcript(
    *,
    campaign_role: Literal["training", "development", "heldout"],
    task_id: str,
    provider: str,
    model_id: str,
    reasoning_effort: Literal["max", "xhigh"],
    client_kind: Literal["cli", "sdk"],
    client_name: str,
    client_version: str,
    harness_identity: dict[str, Any],
    messages: list[MultiTurnSftMessage],
    non_registry_tool_events_observed: bool = False,
) -> dict[str, Any]:
    """Seal public observations only; capture is forbidden outside training campaigns."""

    if campaign_role != "training":
        raise ValueError("broker transcript capture is permitted only for the training split")
    if non_registry_tool_events_observed:
        raise ValueError("non-registry events make a transcript ineligible for multi-turn SFT")
    normalized = [message.model_dump(mode="json", exclude_none=True) for message in messages]
    _validate_sequence(messages)
    tools = repository_tool_definitions(dialect="openai")
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_teacher_multiturn_transcript_v1",
        "campaign_role": "training",
        "task_id": task_id,
        "provider": provider,
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
        "client_kind": client_kind,
        "client_name": client_name,
        "client_version": client_version,
        "prompt_hash": content_hash(normalized[:2]),
        "tool_contract_hash": content_hash(tools),
        "harness_hash": content_hash(harness_identity),
        "messages": normalized,
        "sft_eligible": True,
        "non_registry_tool_events_observed": False,
        "raw_provider_events_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "private_reasoning_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    return {**base, "transcript_hash": content_hash(base)}


def validate_teacher_transcript(value: dict[str, Any]) -> dict[str, Any]:
    """Reject changed, held-out, non-MCP, or structurally incomplete captures."""

    identity = dict(value)
    expected = identity.pop("transcript_hash", None)
    if not isinstance(expected, str) or content_hash(identity) != expected:
        raise ValueError("teacher transcript identity changed")
    if (
        value.get("format_id") != "verigym_teacher_multiturn_transcript_v1"
        or value.get("campaign_role") != "training"
        or value.get("sft_eligible") is not True
        or value.get("non_registry_tool_events_observed") is not False
        or value.get("tool_contract_hash")
        != content_hash(repository_tool_definitions(dialect="openai"))
    ):
        raise ValueError("teacher transcript is not eligible for the current tool contract")
    for field in (
        "raw_provider_events_exported",
        "hidden_assets_exported",
        "reference_solutions_exported",
        "private_reasoning_exported",
        "credential_values_exported",
        "raw_host_paths_exported",
    ):
        if value.get(field) is not False:
            raise ValueError(f"teacher transcript violates the {field} boundary")
    raw_messages = value.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError("teacher transcript omits messages")
    messages = [MultiTurnSftMessage.model_validate(message) for message in raw_messages]
    _validate_sequence(messages)
    if value.get("prompt_hash") != content_hash(
        [message.model_dump(mode="json", exclude_none=True) for message in messages[:2]]
    ):
        raise ValueError("teacher transcript prompt identity changed")
    return dict(value)


def _validate_sequence(messages: list[MultiTurnSftMessage]) -> None:
    if len(messages) < 5 or [message.role for message in messages[:2]] != ["system", "user"]:
        raise ValueError("teacher transcript must start with system and user messages")
    if messages[-1].role != "assistant" or messages[-1].tool_calls:
        raise ValueError("teacher transcript must end in final assistant content")
    pending_id: str | None = None
    pending_name: str | None = None
    seen: set[str] = set()
    saw_finish = False
    for index, message in enumerate(messages):
        if message.role == "assistant" and message.tool_calls:
            if pending_id is not None:
                raise ValueError("teacher emitted a second action before its observation")
            call = message.tool_calls[0]
            if call.id in seen:
                raise ValueError("teacher tool-call IDs are not unique")
            seen.add(call.id)
            pending_id = call.id
            pending_name = call.function.name
            saw_finish = saw_finish or pending_name == "finish"
        elif message.role == "tool":
            if message.tool_call_id != pending_id or message.name != pending_name:
                raise ValueError("teacher tool observation does not match its call")
            pending_id = None
            pending_name = None
        elif index > 1 and index != len(messages) - 1:
            raise ValueError("teacher transcript contains an unexpected message role")
    if pending_id is not None or not saw_finish:
        raise ValueError("teacher transcript is incomplete or lacks finish")
    validate_terminal_finish(messages)


__all__ = ["build_teacher_transcript", "validate_teacher_transcript"]
