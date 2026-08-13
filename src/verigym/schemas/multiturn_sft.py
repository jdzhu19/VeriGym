"""Provider-neutral, verifier-gated multi-turn SFT records."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from verigym.core.hashing import content_hash
from verigym.protocols.repository_action import (
    RepositoryActionProtocolViolation,
    canonical_action_json,
)
from verigym.schemas.base import SCHEMA_VERSION, StrictModel

_HASH = re.compile(r"^[0-9a-f]{64}$")
_PORTABLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+@/\[\]-]{0,255}$")
_CALL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN_CONTENT = re.compile(
    r"(?:"
    r"/(?:home|data|tmp|hpc)/|"
    r"[A-Za-z]:\\|"
    r"\b(?:authorization|password|api[_ -]?key|access[_ -]?token)\s*[:=]|"
    r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\b(?:sk|ds)-[A-Za-z0-9_-]{12,}|"
    r"(?:reference[_ -]?patch|reference[_ -]?solution|golden[_ -]?patch)|"
    r"(?:private[_ -]?reasoning|hidden[_ -]?(?:test|asset))[_/.:=-]"
    r")",
    re.IGNORECASE,
)


def _sha256(value: str) -> str:
    if not _HASH.fullmatch(value):
        raise ValueError("identity must be a lowercase SHA-256 value")
    return value


def _portable(value: str) -> str:
    if not _PORTABLE.fullmatch(value) or value.startswith(("/", "\\")):
        raise ValueError("identity must be bounded, portable, and path-free")
    return value


class SftFunctionCall(StrictModel):
    """Canonical OpenAI function payload; arguments stay a JSON string."""

    name: str
    arguments: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        _portable(value)
        if value not in {
            "list_files",
            "read_file",
            "apply_patch",
            "run_public_test",
            "inspect_diff",
            "finish",
        }:
            raise ValueError("SFT tool call is outside the repository registry")
        return value

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        try:
            value = json.loads(
                self.arguments,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("SFT tool arguments must be strict JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("SFT tool arguments must decode to an object")
        try:
            envelope = json.loads(canonical_action_json(self.name, value))
        except RepositoryActionProtocolViolation as exc:
            raise ValueError("SFT tool arguments differ from the action registry") from exc
        canonical = json.dumps(
            envelope["arguments"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        if self.arguments != canonical:
            raise ValueError("SFT tool arguments must use canonical JSON serialization")
        if _FORBIDDEN_CONTENT.search(self.arguments):
            raise ValueError("SFT tool arguments contain a forbidden private or credential marker")
        return self


class SftToolCall(StrictModel):
    """OpenAI-style assistant tool call."""

    id: str
    type: Literal["function"] = "function"
    function: SftFunctionCall

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _CALL_ID.fullmatch(value):
            raise ValueError("SFT tool-call ID is not portable")
        return value


class MultiTurnSftMessage(StrictModel):
    """One OpenAI-compatible message without a private-reasoning field."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[SftToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    @model_validator(mode="after")
    def role_shape_is_exact(self) -> Self:
        if self.role in {"system", "user"}:
            if not self.content or any(
                value is not None for value in (self.tool_calls, self.tool_call_id, self.name)
            ):
                raise ValueError("system/user SFT messages may contain only non-empty content")
        elif self.role == "assistant":
            if self.tool_call_id is not None or self.name is not None:
                raise ValueError("assistant SFT messages cannot be tool observations")
            has_calls = bool(self.tool_calls)
            has_content = bool(self.content)
            if has_calls == has_content:
                raise ValueError("assistant SFT messages contain one tool call or final content")
            if has_calls and len(self.tool_calls or []) != 1:
                raise ValueError("repository SFT permits exactly one tool call per turn")
        else:
            if (
                not self.content
                or self.tool_calls is not None
                or self.tool_call_id is None
                or self.name is None
                or not _CALL_ID.fullmatch(self.tool_call_id)
            ):
                raise ValueError("tool SFT messages require content, call ID, and tool name")
            _portable(self.name)
            _validate_observation(self.content, self.name)
        if self.content is not None:
            if len(self.content.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("SFT message exceeds the content bound")
            if _FORBIDDEN_CONTENT.search(self.content):
                raise ValueError("SFT message contains a forbidden private or credential marker")
        return self


class VerifiedMultiTurnSftExample(StrictModel):
    """One resolved, infrastructure-valid training-split tool trajectory."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_verified_multiturn_sft_v1"] = "verigym_verified_multiturn_sft_v1"
    sample_id: str
    task_id: str
    official_task_id: str
    task_hash: str
    source_hash: str
    candidate_hash: str
    verifier_hash: str
    provider: str
    model_id: str
    reasoning_effort: Literal["max", "xhigh"]
    client_kind: Literal["cli", "sdk"]
    client_name: str
    client_version: str
    prompt_hash: str
    tool_contract_hash: str
    harness_hash: str
    tokenizer_hash: str
    split: Literal["training"] = "training"
    messages: list[MultiTurnSftMessage] = Field(min_length=5)
    token_count: int = Field(ge=1, le=16_384)
    max_length: Literal[16_384] = 16_384
    truncation: Literal["error"] = "error"
    supervised_roles: tuple[Literal["assistant"], ...] = ("assistant",)
    masked_roles: tuple[Literal["system"], Literal["user"], Literal["tool"]] = (
        "system",
        "user",
        "tool",
    )
    verifier_resolved: Literal[True] = True
    infrastructure_valid: Literal[True] = True
    non_registry_tool_events_observed: Literal[False] = False
    hidden_assets_exported: Literal[False] = False
    reference_solutions_exported: Literal[False] = False
    private_reasoning_exported: Literal[False] = False
    credential_values_exported: Literal[False] = False
    raw_host_paths_exported: Literal[False] = False
    example_hash: str

    @field_validator(
        "sample_id",
        "task_hash",
        "source_hash",
        "candidate_hash",
        "verifier_hash",
        "prompt_hash",
        "tool_contract_hash",
        "harness_hash",
        "tokenizer_hash",
        "example_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator(
        "task_id",
        "official_task_id",
        "provider",
        "model_id",
        "client_name",
    )
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _portable(value)

    @field_validator("client_version")
    @classmethod
    def validate_client_version(cls, value: str) -> str:
        if (
            not value
            or value != value.strip()
            or len(value) > 256
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("client version must be bounded printable text")
        return value

    @model_validator(mode="after")
    def validate_dialogue_and_seal(self) -> Self:
        if [message.role for message in self.messages[:2]] != ["system", "user"]:
            raise ValueError("multi-turn SFT must start with system then user")
        if self.messages[-1].role != "assistant" or self.messages[-1].tool_calls:
            raise ValueError("multi-turn SFT must end in a final assistant message")
        pending: SftToolCall | None = None
        seen_ids: set[str] = set()
        saw_finish = False
        assistant_indices: list[int] = []
        for index, message in enumerate(self.messages):
            if message.role == "assistant":
                assistant_indices.append(index)
                if pending is not None:
                    raise ValueError("assistant emitted another turn before a tool observation")
                if message.tool_calls:
                    call = message.tool_calls[0]
                    if call.id in seen_ids:
                        raise ValueError("SFT tool-call IDs must be unique")
                    seen_ids.add(call.id)
                    pending = call
                    saw_finish = saw_finish or call.function.name == "finish"
                elif index != len(self.messages) - 1:
                    raise ValueError(
                        "assistant final content may appear only after terminal finish"
                    )
            elif message.role == "tool":
                if pending is None:
                    raise ValueError("SFT tool observation has no preceding assistant call")
                if message.tool_call_id != pending.id or message.name != pending.function.name:
                    raise ValueError("SFT tool observation does not match its assistant call")
                _validate_observation(message.content or "", pending.function.name)
                pending = None
            elif index > 1:
                raise ValueError("repository SFT cannot inject system/user messages mid-episode")
        if pending is not None:
            raise ValueError("SFT trajectory ends before a tool observation")
        if not saw_finish:
            raise ValueError("SFT trajectory must contain the canonical finish tool")
        validate_terminal_finish(self.messages)
        if len(assistant_indices) < 2:
            raise ValueError("multi-turn SFT requires tool-call and final assistant supervision")
        identity = self.model_dump(mode="json", exclude={"example_hash"})
        if content_hash(identity) != self.example_hash:
            raise ValueError("multi-turn SFT example identity changed")
        return self


class VerifiedMultiTurnSftDatasetManifest(StrictModel):
    """Immutable dataset identity for the multi-turn SFT mainline."""

    schema_version: str = SCHEMA_VERSION
    format_id: Literal["verigym_verified_multiturn_sft_dataset_v1"] = (
        "verigym_verified_multiturn_sft_dataset_v1"
    )
    record_count: int = Field(ge=1)
    task_ids: list[str] = Field(min_length=1)
    example_hashes: list[str] = Field(min_length=1)
    tokenizer_hash: str
    tool_contract_hash: str
    records_sha256: str
    only_training_split: Literal[True] = True
    only_resolved_samples: Literal[True] = True
    infrastructure_invalid_excluded: Literal[True] = True
    hidden_assets_exported: Literal[False] = False
    reference_solutions_exported: Literal[False] = False
    private_reasoning_exported: Literal[False] = False
    credential_values_exported: Literal[False] = False
    raw_host_paths_exported: Literal[False] = False
    manifest_hash: str

    @field_validator(
        "tokenizer_hash",
        "tool_contract_hash",
        "records_sha256",
        "manifest_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("example_hashes")
    @classmethod
    def validate_example_hashes(cls, values: list[str]) -> list[str]:
        return [_sha256(value) for value in values]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.record_count != len(self.task_ids) or self.record_count != len(self.example_hashes):
            raise ValueError("multi-turn manifest counts disagree")
        if self.task_ids != sorted(set(self.task_ids)):
            raise ValueError("multi-turn dataset tasks must be sorted and unique")
        if len(set(self.example_hashes)) != len(self.example_hashes):
            raise ValueError("multi-turn dataset example hashes must be unique")
        identity = self.model_dump(mode="json", exclude={"manifest_hash"})
        if content_hash(identity) != self.manifest_hash:
            raise ValueError("multi-turn SFT manifest identity changed")
        return self


def seal_multi_turn_example(payload: dict[str, Any]) -> VerifiedMultiTurnSftExample:
    """Calculate the record hash only after all strict fields have been supplied."""

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError("multi-turn SFT payload omits its messages")
    normalized_payload = {
        **payload,
        "messages": [MultiTurnSftMessage.model_validate(message) for message in raw_messages],
    }
    identity = {**normalized_payload, "example_hash": "0" * 64}
    draft = VerifiedMultiTurnSftExample.model_construct(**identity)
    normalized = draft.model_dump(mode="json", exclude={"example_hash"})
    return VerifiedMultiTurnSftExample.model_validate(
        {**normalized_payload, "example_hash": content_hash(normalized)}
    )


def validate_terminal_finish(messages: list[MultiTurnSftMessage]) -> None:
    """Require the final broker action to be an accepted terminal ``finish`` call."""

    if len(messages) < 3:
        raise ValueError("SFT trajectory is too short for terminal finish")
    finish_message, observation, final_message = messages[-3:]
    if (
        finish_message.role != "assistant"
        or not finish_message.tool_calls
        or finish_message.tool_calls[0].function.name != "finish"
        or observation.role != "tool"
        or observation.name != "finish"
        or final_message.role != "assistant"
        or final_message.tool_calls
    ):
        raise ValueError(
            "SFT trajectory must end with finish, its observation, and final assistant"
        )
    value = _observation_value(observation.content or "", "finish")
    result = value["result"]
    if (
        value["is_error"] is not False
        or result.get("accepted") is not True
        or result.get("terminal") is not True
    ):
        raise ValueError("SFT finish observation is not accepted and terminal")


def _validate_observation(content: str, expected_name: str) -> None:
    value = _observation_value(content, expected_name)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content != canonical:
        raise ValueError("SFT tool observation must use canonical JSON serialization")


def _observation_value(content: str, expected_name: str) -> dict[str, Any]:
    try:
        value = json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except ValueError as exc:
        raise ValueError("SFT tool observation must be strict JSON") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0"
        or value.get("protocol") != "repository_action.v2"
        or value.get("tool") != expected_name
        or not isinstance(value.get("is_error"), bool)
        or not isinstance(value.get("result"), dict)
    ):
        raise ValueError("SFT tool observation differs from the canonical contract")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant is forbidden: {value}")


__all__ = [
    "MultiTurnSftMessage",
    "SftFunctionCall",
    "SftToolCall",
    "VerifiedMultiTurnSftDatasetManifest",
    "VerifiedMultiTurnSftExample",
    "seal_multi_turn_example",
    "validate_terminal_finish",
]
