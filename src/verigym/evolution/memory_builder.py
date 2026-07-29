"""Strict, bounded Evolve-Context memory-builder contracts and parsing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from verigym.core.hashing import canonical_json, content_hash, hash_bytes
from verigym.schemas.evolution import (
    MemoryBuilderInput,
    MemoryBuilderResult,
    MemoryPack,
    SanitizedTrainingSummary,
)

from .memory import build_memory_pack, validate_memory_pack, validate_training_summary

MEMORY_BUILDER_PROMPT_POLICY = {
    "schema_version": "1.0",
    "policy_id": "evolve_context_memory_builder_v1",
    "input": "sanitized_observable_training_summary",
    "output": "strict_five_section_json_object",
    "private_reasoning_requested": False,
    "heldout_assets_available": False,
    "code_allowed": False,
    "task_specific_content_allowed": False,
}
MEMORY_BUILDER_PROMPT_HASH = content_hash(MEMORY_BUILDER_PROMPT_POLICY)
_SECTION_NAMES = (
    "principles",
    "public_test_strategy",
    "workspace_policy_reminders",
    "debugging_checklist",
    "patch_discipline",
)


def build_memory_builder_input(
    *,
    training_summary: SanitizedTrainingSummary,
    model_identity_hash: str,
    codex_identity_hash: str,
    auth_semantic_id: str,
    runtime_identity_hash: str,
    image_identity_hash: str,
    requested_model_id: str,
    reasoning_effort: str,
    output_schema_hash: str,
    build_id: str = "m10b-memory-synthesis",
    timeout_s: int = 300,
    max_output_bytes: int = 131_072,
) -> MemoryBuilderInput:
    """Bind one authorized model process without exposing held-out material."""

    validate_training_summary(training_summary)
    base = {
        "schema_version": "1.0",
        "build_id": build_id,
        "training_summary": training_summary.model_dump(mode="json"),
        "prompt_contract_hash": MEMORY_BUILDER_PROMPT_HASH,
        "output_schema_hash": output_schema_hash,
        "model_identity_hash": model_identity_hash,
        "codex_identity_hash": codex_identity_hash,
        "auth_semantic_id": auth_semantic_id,
        "runtime_identity_hash": runtime_identity_hash,
        "image_identity_hash": image_identity_hash,
        "requested_model_id": requested_model_id,
        "reasoning_effort": reasoning_effort,
        "timeout_s": timeout_s,
        "max_output_bytes": max_output_bytes,
        "heldout_assets_available": False,
        "private_reasoning_requested": False,
    }
    return MemoryBuilderInput.model_validate({**base, "input_hash": content_hash(base)})


def validate_memory_builder_input(value: MemoryBuilderInput) -> MemoryBuilderInput:
    validate_training_summary(value.training_summary)
    payload = value.model_dump(mode="json")
    expected = payload.pop("input_hash")
    if content_hash(payload) != expected:
        raise ValueError("memory-builder input identity changed")
    if value.prompt_contract_hash != MEMORY_BUILDER_PROMPT_HASH:
        raise ValueError("memory-builder prompt contract changed")
    return value


def render_memory_builder_prompt(request: MemoryBuilderInput) -> str:
    """Render only task-free observable episode summaries; identity hashes stay outside."""

    validate_memory_builder_input(request)
    episodes = [episode.model_dump(mode="json") for episode in request.training_summary.episodes]
    return (
        "You are preparing a small, task-independent memory pack for a repository repair "
        "agent. Generalize only from the sanitized observable summaries below. Do not emit "
        "source code, patches, task IDs, repository paths, hashes, hidden or reference details, "
        "credentials, or private reasoning. Return exactly one JSON object with exactly these "
        "five keys, each mapped to a non-empty array of short general guidance strings: "
        f"{', '.join(_SECTION_NAMES)}. Do not use Markdown fences or additional text.\n\n"
        f"SANITIZED_SUMMARIES={canonical_json(episodes)}"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("memory-builder output contains a duplicate JSON key")
        result[key] = value
    return result


def parse_memory_builder_output(
    text: str,
    *,
    heldout_only_tokens: tuple[str, ...] = (),
) -> MemoryPack:
    """Parse complete raw JSON and derive the trusted hash-bearing MemoryPack."""

    if not text or len(text.encode("utf-8")) > 131_072:
        raise ValueError("memory-builder output is empty or oversized")
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise ValueError("memory-builder output is not one complete JSON object") from exc
    if not isinstance(payload, dict) or set(payload) != set(_SECTION_NAMES):
        raise ValueError("memory-builder output has an unexpected shape")
    values: dict[str, list[str]] = {}
    for name in _SECTION_NAMES:
        items = payload[name]
        if (
            not isinstance(items, list)
            or not items
            or len(items) > 12
            or any(not isinstance(item, str) for item in items)
        ):
            raise ValueError(f"memory-builder section {name!r} is invalid")
        values[name] = items
    return build_memory_pack(values, heldout_only_tokens=heldout_only_tokens)


def build_memory_builder_result(
    *,
    request: MemoryBuilderInput,
    status: str,
    redacted_output: str,
    process_identity_hash: str,
    process_ledger_record_hash: str,
    memory_pack: MemoryPack | None,
    wall_time_s: float,
    input_tokens: int | None,
    output_tokens: int | None,
) -> MemoryBuilderResult:
    validate_memory_builder_input(request)
    if memory_pack is not None:
        validate_memory_pack(memory_pack)
    base: Mapping[str, Any] = {
        "schema_version": "1.0",
        "build_id": request.build_id,
        "status": status,
        "input_hash": request.input_hash,
        "process_identity_hash": process_identity_hash,
        "process_ledger_record_hash": process_ledger_record_hash,
        "redacted_output_hash": hash_bytes(redacted_output.encode("utf-8")),
        "memory_pack": memory_pack.model_dump(mode="json") if memory_pack is not None else None,
        "wall_time_s": wall_time_s,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_processes_started": 1,
        "heldout_assets_available": False,
        "private_reasoning_exported": False,
        "credentials_exported": False,
    }
    return MemoryBuilderResult(**base, output_hash=content_hash(base))


def validate_memory_builder_result(result: MemoryBuilderResult) -> MemoryBuilderResult:
    if result.memory_pack is not None:
        validate_memory_pack(result.memory_pack)
    payload = result.model_dump(mode="json")
    expected = payload.pop("output_hash")
    if content_hash(payload) != expected:
        raise ValueError("memory-builder output identity changed")
    return result


__all__ = [
    "MEMORY_BUILDER_PROMPT_HASH",
    "MEMORY_BUILDER_PROMPT_POLICY",
    "build_memory_builder_input",
    "build_memory_builder_result",
    "parse_memory_builder_output",
    "render_memory_builder_prompt",
    "validate_memory_builder_input",
    "validate_memory_builder_result",
]
