"""Strict, bounded Evolve-Context memory-builder contracts and parsing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from verigym.core.external_process_identity import (
    bind_external_process_payload,
    build_external_process_request,
)
from verigym.core.hashing import canonical_json, content_hash, hash_bytes
from verigym.schemas.evolution import (
    MemoryBuilderInput,
    MemoryBuilderResult,
    MemoryPack,
    MemorySynthesisPlan,
    SanitizedTrainingSummary,
)
from verigym.schemas.external_agent import (
    ExternalProcessIdentityPreview,
    ExternalProcessInvocationSpec,
    ExternalProcessPayloadBinding,
    ExternalProcessRequest,
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
MEMORY_BUILDER_PROMPT_CONTRACT_ID = "evolve_context_memory_builder_v1"
_SECTION_NAMES = (
    "principles",
    "public_test_strategy",
    "workspace_policy_reminders",
    "debugging_checklist",
    "patch_discipline",
)
_PROMPT_TEMPLATE = (
    "You are preparing a small, task-independent memory pack for a repository repair "
    "agent. Generalize only from the sanitized observable summaries below. Do not emit "
    "source code, patches, task IDs, repository paths, hashes, hidden or reference details, "
    "credentials, or private reasoning. Return exactly one JSON object with exactly these "
    "five keys, each mapped to a non-empty array of short general guidance strings: "
    "{section_names}. Do not use Markdown fences or additional text.\n\n"
    "SANITIZED_SUMMARIES={sanitized_summaries}"
)
MEMORY_BUILDER_PROMPT_TEMPLATE_HASH = hash_bytes(_PROMPT_TEMPLATE.encode("utf-8"))


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
    prompt = _PROMPT_TEMPLATE.format(
        section_names=", ".join(_SECTION_NAMES),
        sanitized_summaries=canonical_json(episodes),
    )
    encoded = prompt.encode("utf-8")
    if not prompt.strip() or len(encoded) > 2 * 1024 * 1024:
        raise ValueError("memory-builder rendered prompt is empty or oversized")
    return prompt


def build_memory_synthesis_plan(
    *,
    request: MemoryBuilderInput,
    invocation_spec: ExternalProcessInvocationSpec,
    identity_preview: ExternalProcessIdentityPreview,
    payload_binding: ExternalProcessPayloadBinding,
    training_dataset_hash: str,
    training_run_ids: list[str],
    training_source_identities: Mapping[str, str],
    reward_profile_hash: str,
    reward_vector_schema_hash: str,
    plan_id: str = "m10b-memory-synthesis-plan",
) -> MemorySynthesisPlan:
    """Freeze the payload-bound process identity before process authorization."""

    validate_memory_builder_input(request)
    prompt = render_memory_builder_prompt(request)
    if (
        identity_preview.invocation_spec_hash != invocation_spec.invocation_spec_hash
        or payload_binding.invocation_spec_hash != invocation_spec.invocation_spec_hash
        or payload_binding.prompt_contract_id != MEMORY_BUILDER_PROMPT_CONTRACT_ID
        or payload_binding.template_hash != MEMORY_BUILDER_PROMPT_TEMPLATE_HASH
        or payload_binding.input_dataset_hash != training_dataset_hash
        or request.training_summary.trajectory_dataset_hash != training_dataset_hash
        or payload_binding.rendered_prompt_hash != hash_bytes(prompt.encode("utf-8"))
        or payload_binding.stdin_utf8_bytes != len(prompt.encode("utf-8"))
        or invocation_spec.prompt_contract_id != MEMORY_BUILDER_PROMPT_CONTRACT_ID
        or invocation_spec.expected_output_schema_hash != request.output_schema_hash
    ):
        raise ValueError("memory synthesis lifecycle identity differs from rendered input")
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "build_id": request.build_id,
        "invocation_spec": invocation_spec.model_dump(mode="json"),
        "identity_preview": identity_preview.model_dump(mode="json"),
        "payload_binding": payload_binding.model_dump(mode="json"),
        "training_dataset_hash": training_dataset_hash,
        "training_run_ids": sorted(training_run_ids),
        "training_source_identities": dict(sorted(training_source_identities.items())),
        "reward_profile_hash": reward_profile_hash,
        "reward_vector_schema_hash": reward_vector_schema_hash,
        "sanitized_summary_hash": request.training_summary.summary_hash,
        "builder_input_hash": request.input_hash,
        "prompt_contract_id": MEMORY_BUILDER_PROMPT_CONTRACT_ID,
        "prompt_contract_hash": request.prompt_contract_hash,
        "prompt_template_hash": MEMORY_BUILDER_PROMPT_TEMPLATE_HASH,
        "rendered_prompt_hash": payload_binding.rendered_prompt_hash,
        "rendered_prompt_utf8_bytes": payload_binding.stdin_utf8_bytes,
        "output_schema_hash": request.output_schema_hash,
        "model_identity_hash": request.model_identity_hash,
        "codex_identity_hash": request.codex_identity_hash,
        "auth_semantic_id": request.auth_semantic_id,
        "runtime_identity_hash": request.runtime_identity_hash,
        "image_identity_hash": request.image_identity_hash,
        "requested_model_id": request.requested_model_id,
        "reasoning_effort": request.reasoning_effort,
        "timeout_s": request.timeout_s,
        "max_output_bytes": request.max_output_bytes,
        "payload_state": "bound",
        "sealed_before_authorization": True,
    }
    return MemorySynthesisPlan.model_validate({**base, "plan_hash": content_hash(base)})


def validate_memory_synthesis_plan(plan: MemorySynthesisPlan) -> MemorySynthesisPlan:
    """Recompute the complete static and payload-bound synthesis plan identity."""

    payload = plan.model_dump(mode="json")
    expected = payload.pop("plan_hash")
    if content_hash(payload) != expected:
        raise ValueError("memory synthesis plan identity changed")
    if (
        plan.prompt_contract_id != MEMORY_BUILDER_PROMPT_CONTRACT_ID
        or plan.prompt_contract_hash != MEMORY_BUILDER_PROMPT_HASH
        or plan.prompt_template_hash != MEMORY_BUILDER_PROMPT_TEMPLATE_HASH
    ):
        raise ValueError("memory synthesis prompt contract changed")
    return plan


def reconstruct_memory_synthesis_launch(
    *,
    plan: MemorySynthesisPlan,
    request: MemoryBuilderInput,
    frozen_summary: SanitizedTrainingSummary,
    executable_path: Path,
) -> tuple[str, ExternalProcessPayloadBinding, ExternalProcessRequest]:
    """Independently re-render and bind the prompt before process authorization."""

    validate_memory_synthesis_plan(plan)
    validate_memory_builder_input(request)
    validate_training_summary(frozen_summary)
    if (
        request.training_summary != frozen_summary
        or request.input_hash != plan.builder_input_hash
        or frozen_summary.summary_hash != plan.sanitized_summary_hash
        or request.training_summary.trajectory_dataset_hash != plan.training_dataset_hash
    ):
        raise ValueError("memory synthesis frozen training input changed")
    prompt = render_memory_builder_prompt(request)
    binding = bind_external_process_payload(
        plan.invocation_spec,
        prompt,
        template_hash=MEMORY_BUILDER_PROMPT_TEMPLATE_HASH,
        input_dataset_hash=plan.training_dataset_hash,
    )
    if binding != plan.payload_binding:
        raise ValueError("memory synthesis payload reconstruction differs from frozen plan")
    executable_request = build_external_process_request(
        plan.invocation_spec,
        binding,
        prompt,
        executable_path=executable_path,
    )
    return prompt, binding, executable_request


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
    memory_synthesis_plan_hash: str | None = None,
    invocation_spec_hash: str | None = None,
    payload_binding_hash: str | None = None,
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
    lifecycle = (
        memory_synthesis_plan_hash,
        invocation_spec_hash,
        payload_binding_hash,
    )
    if any(value is not None for value in lifecycle):
        if not all(value is not None for value in lifecycle):
            raise ValueError("memory-builder lifecycle result identities are all-or-none")
        base = {
            **base,
            "memory_synthesis_plan_hash": memory_synthesis_plan_hash,
            "invocation_spec_hash": invocation_spec_hash,
            "payload_binding_hash": payload_binding_hash,
        }
    return MemoryBuilderResult(**base, output_hash=content_hash(base))


def validate_memory_builder_result(result: MemoryBuilderResult) -> MemoryBuilderResult:
    if result.memory_pack is not None:
        validate_memory_pack(result.memory_pack)
    payload = result.model_dump(mode="json")
    expected = payload.pop("output_hash")
    candidates = [payload]
    lifecycle_fields = (
        "memory_synthesis_plan_hash",
        "invocation_spec_hash",
        "payload_binding_hash",
    )
    if all(payload[field] is None for field in lifecycle_fields):
        candidates.append(
            {key: value for key, value in payload.items() if key not in lifecycle_fields}
        )
    if all(content_hash(candidate) != expected for candidate in candidates):
        raise ValueError("memory-builder output identity changed")
    return result


__all__ = [
    "MEMORY_BUILDER_PROMPT_CONTRACT_ID",
    "MEMORY_BUILDER_PROMPT_HASH",
    "MEMORY_BUILDER_PROMPT_POLICY",
    "MEMORY_BUILDER_PROMPT_TEMPLATE_HASH",
    "build_memory_builder_input",
    "build_memory_builder_result",
    "build_memory_synthesis_plan",
    "parse_memory_builder_output",
    "reconstruct_memory_synthesis_launch",
    "render_memory_builder_prompt",
    "validate_memory_builder_input",
    "validate_memory_builder_result",
    "validate_memory_synthesis_plan",
]
