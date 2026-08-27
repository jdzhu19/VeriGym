"""Pure deterministic prompt-policy resolution for every agent execution path."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from verigym.core.hashing import content_hash
from verigym.prompts.builder import PromptBuilder
from verigym.schemas.common import AgentDescriptor, InteractionMode
from verigym.schemas.evolution import AgentVersionManifest, MemoryPack
from verigym.schemas.options import JsonValue
from verigym.schemas.prompt import PromptPolicyDescriptor
from verigym.schemas.task import VeriTask

if TYPE_CHECKING:
    from verigym.agents.base import AgentAdapter


def agent_configuration_hash(
    descriptor: AgentDescriptor,
    options: Mapping[str, JsonValue],
) -> str:
    """Hash the actual generic agent selection without provider-specific logic."""

    return content_hash(
        {"descriptor": descriptor, "options": dict(options)} if options else descriptor
    )


def resolve_prompt_policy(
    *,
    interaction_mode: InteractionMode,
    agent: AgentAdapter,
    agent_options: Mapping[str, JsonValue],
    task: VeriTask,
) -> PromptPolicyDescriptor | None:
    """Resolve one safe prompt identity from the actual agent execution configuration."""

    if agent.requires_model:
        if agent.prompt_policy_spec is None:
            return PromptBuilder(interaction_mode).descriptor
    spec = agent.prompt_policy_spec
    if spec is None:
        return None
    agent_feedback = task.metadata.get("agent_feedback_contract")
    is_agent_eval = isinstance(agent_feedback, dict)
    prompt_contract_id = (
        "repository_action_v2_prompt_v3" if is_agent_eval else spec.prompt_contract_id
    )
    prompt_contract_version = "3.0.0" if is_agent_eval else spec.prompt_contract_version
    task_context_policy = (
        "revision_bound_agent_feedback_v1" if is_agent_eval else spec.task_context_policy
    )
    base_instruction_policy = (
        "generated_repository_action_registry_v3" if is_agent_eval else spec.base_instruction_policy
    )
    content_visibility_policy = (
        "visible_assets_and_revision_bound_feedback_v1"
        if is_agent_eval
        else spec.content_visibility_policy
    )
    contract = agent_options.get("prompt_contract_id")
    if contract is not None and contract != prompt_contract_id:
        raise ValueError("agent prompt contract differs from its plugin declaration")
    base_payload: dict[str, Any] = {
        "resolver_id": "agent_execution_prompt_policy_v1",
        "prompt_contract_id": prompt_contract_id,
        "prompt_contract_version": prompt_contract_version,
        "interaction_mode": interaction_mode,
        "task_context_policy": task_context_policy,
        "task_context_hash": content_hash(
            safe_task_context_identity(task, interaction_mode=interaction_mode)
        ),
        "base_instruction_policy": base_instruction_policy,
        "content_visibility_policy": content_visibility_policy,
        "max_prompt_bytes": spec.max_prompt_bytes,
        "max_task_context_bytes": spec.max_task_context_bytes,
        "agent_descriptor_hash": content_hash(agent.descriptor),
    }
    version_id, version_hash, memory_hash, declared_contract_hash = _resolve_versioned_context(
        agent=agent,
        options=agent_options,
        allowed=spec.versioned_context_allowed,
    )
    if declared_contract_hash is not None and declared_contract_hash != content_hash(
        _prompt_contract_payload(
            resolver_id="agent_execution_prompt_policy_v1",
            prompt_contract_id=prompt_contract_id,
            prompt_contract_version=prompt_contract_version,
            interaction_mode=interaction_mode,
            task_context_policy=task_context_policy,
            base_instruction_policy=base_instruction_policy,
            content_visibility_policy=content_visibility_policy,
            max_prompt_bytes=spec.max_prompt_bytes,
            max_task_context_bytes=spec.max_task_context_bytes,
            agent_descriptor_hash=base_payload["agent_descriptor_hash"],
        )
    ):
        raise ValueError("agent version binds a different prompt contract")
    payload = {
        **base_payload,
        "agent_version_id": version_id,
        "agent_version_hash": version_hash,
        "memory_pack_hash": memory_hash,
    }
    return PromptPolicyDescriptor(
        id=prompt_contract_id,
        version=prompt_contract_version,
        interaction_mode=interaction_mode,
        resolver_id="agent_execution_prompt_policy_v1",
        task_context_policy=task_context_policy,
        task_context_hash=base_payload["task_context_hash"],
        base_instruction_policy=base_instruction_policy,
        content_visibility_policy=content_visibility_policy,
        max_prompt_bytes=spec.max_prompt_bytes,
        max_task_context_bytes=spec.max_task_context_bytes,
        agent_descriptor_hash=base_payload["agent_descriptor_hash"],
        agent_version_id=version_id,
        agent_version_hash=version_hash,
        memory_pack_hash=memory_hash,
        configuration_fingerprint=content_hash(payload),
    )


def prompt_contract_identity_hash(descriptor: PromptPolicyDescriptor) -> str:
    """Return the version-neutral identity bound by an agent-version manifest."""

    if descriptor.resolver_id != "agent_execution_prompt_policy_v1":
        return descriptor.configuration_fingerprint
    return content_hash(
        _prompt_contract_payload(
            resolver_id=descriptor.resolver_id,
            prompt_contract_id=descriptor.id,
            prompt_contract_version=descriptor.version,
            interaction_mode=descriptor.interaction_mode,
            task_context_policy=descriptor.task_context_policy,
            base_instruction_policy=descriptor.base_instruction_policy,
            content_visibility_policy=descriptor.content_visibility_policy,
            max_prompt_bytes=descriptor.max_prompt_bytes,
            max_task_context_bytes=descriptor.max_task_context_bytes,
            agent_descriptor_hash=descriptor.agent_descriptor_hash,
        )
    )


def _prompt_contract_payload(
    *,
    resolver_id: str,
    prompt_contract_id: str,
    prompt_contract_version: str,
    interaction_mode: InteractionMode,
    task_context_policy: str | None,
    base_instruction_policy: str | None,
    content_visibility_policy: str | None,
    max_prompt_bytes: int | None,
    max_task_context_bytes: int | None,
    agent_descriptor_hash: str | None,
) -> dict[str, Any]:
    return {
        "resolver_id": resolver_id,
        "prompt_contract_id": prompt_contract_id,
        "prompt_contract_version": prompt_contract_version,
        "interaction_mode": interaction_mode,
        "task_context_policy": task_context_policy,
        "base_instruction_policy": base_instruction_policy,
        "content_visibility_policy": content_visibility_policy,
        "max_prompt_bytes": max_prompt_bytes,
        "max_task_context_bytes": max_task_context_bytes,
        "agent_descriptor_hash": agent_descriptor_hash,
    }


def safe_task_context_identity(
    task: VeriTask,
    *,
    interaction_mode: InteractionMode,
) -> dict[str, Any]:
    """Return bounded public task identity without hidden/reference metadata."""

    from verigym.core.agent_feedback import public_feedback_test_ids

    public_test_ids = public_feedback_test_ids(task)
    identity = {
        "schema_version": "1.0",
        "task_id": task.id,
        "title_hash": content_hash(task.title),
        "description_hash": content_hash(task.description),
        "interaction_mode": interaction_mode.value,
        "entrypoints": sorted(task.workspace.entrypoints),
        "editable_globs": sorted(task.workspace.editable_globs),
        "readonly_globs": sorted(task.workspace.readonly_globs),
        "allowed_tools": sorted(task.interaction.allowed_tools),
        "denied_tools": sorted(task.interaction.denied_tools),
        "network_policy": task.interaction.network_policy,
        "public_test_ids": public_test_ids,
        "max_wall_time_s": task.budget.max_wall_time_s,
        "max_changed_files": task.workspace.max_changed_files,
        "max_patch_lines": task.workspace.max_patch_lines,
    }
    feedback = task.metadata.get("agent_feedback_contract")
    if isinstance(feedback, dict):
        fingerprint = feedback.get("configuration_fingerprint")
        if isinstance(fingerprint, str):
            identity["agent_feedback_contract_fingerprint"] = fingerprint
    return identity


def validate_prompt_policy_binding(
    *,
    expected: PromptPolicyDescriptor | None,
    expected_hash: str | None,
    resolved: PromptPolicyDescriptor | None,
    resolved_hash: str | None,
) -> None:
    """Fail closed with safe field-level diagnostics and no raw prompt content."""

    mismatches: list[str] = []
    if expected is None or resolved is None:
        if expected != resolved:
            mismatches.append("descriptor")
    else:
        expected_payload = expected.model_dump(mode="json")
        resolved_payload = resolved.model_dump(mode="json")
        for field in sorted(set(expected_payload) | set(resolved_payload)):
            if expected_payload.get(field) != resolved_payload.get(field):
                mismatches.append(field)
    if expected_hash != resolved_hash:
        mismatches.append("hash")
    if resolved is not None and resolved_hash != resolved.configuration_fingerprint:
        mismatches.append("resolved_fingerprint")
    if expected is not None and expected_hash != expected.configuration_fingerprint:
        mismatches.append("expected_fingerprint")
    if mismatches:
        raise ValueError("prompt policy mismatch: " + ", ".join(sorted(set(mismatches))))


def validate_prompt_text(
    prompt: str,
    descriptor: PromptPolicyDescriptor | None,
) -> str:
    """Validate the bounded harness prompt before any external process launch."""

    if descriptor is None or descriptor.resolver_id is None:
        raise ValueError("prompt-bearing agent requires a resolved prompt policy")
    size = len(prompt.encode("utf-8"))
    if descriptor.max_prompt_bytes is None:
        raise ValueError("resolved prompt policy lacks a prompt byte bound")
    if size > descriptor.max_prompt_bytes:
        raise ValueError("agent harness prompt exceeds its resolved byte bound")
    return prompt


def _resolve_versioned_context(
    *,
    agent: AgentAdapter,
    options: Mapping[str, JsonValue],
    allowed: bool,
) -> tuple[str | None, str | None, str | None, str | None]:
    # Imported lazily because the evolution package also exposes experiment
    # services; prompt policy is imported by the core orchestrator itself.
    from verigym.evolution.memory import validate_agent_version, validate_memory_pack

    version_id = _optional_string(options.get("agent_version_id"), "agent_version_id")
    version_hash = _optional_string(options.get("agent_version_hash"), "agent_version_hash")
    raw_manifest = options.get("agent_version_manifest_json")
    raw_memory = options.get("memory_pack")
    present = any(
        value is not None for value in (version_id, version_hash, raw_manifest, raw_memory)
    )
    if present and not allowed:
        raise ValueError("agent prompt contract does not allow versioned context")
    if not present:
        return None, None, None, None
    if version_id is None or version_hash is None or not isinstance(raw_manifest, str):
        raise ValueError("versioned prompt context requires ID, hash, and manifest")
    try:
        payload = json.loads(raw_manifest, object_pairs_hook=_unique_object)
        version = validate_agent_version(AgentVersionManifest.model_validate(payload))
    except Exception as exc:
        raise ValueError(f"invalid prompt agent-version identity: {exc}") from exc
    if (
        version.agent_version_id != version_id
        or version.version_hash != version_hash
        or version.base_agent_id != agent.descriptor.name
        or version.agent_descriptor_hash != content_hash(agent.descriptor)
    ):
        raise ValueError("prompt agent-version identity differs from its manifest")
    if version.update_type == "none":
        if raw_memory is not None or version.memory_pack_hash is not None:
            raise ValueError("base prompt version must remain memory-free")
        return version_id, version_hash, None, version.prompt_contract_hash
    if version.update_type in {"external_checkpoint", "external_adapter"}:
        if raw_memory is not None or version.memory_pack_hash is not None:
            raise ValueError("weight-backed prompt versions must remain memory-free")
        return version_id, version_hash, None, version.prompt_contract_hash
    if version.update_type != "context_memory" or raw_memory is None:
        raise ValueError("evolved prompt version requires its frozen memory pack")
    try:
        memory = validate_memory_pack(MemoryPack.model_validate(raw_memory))
    except Exception as exc:
        raise ValueError(f"invalid prompt memory identity: {exc}") from exc
    if memory.content_hash != version.memory_pack_hash:
        raise ValueError("prompt memory pack differs from the agent-version manifest")
    return version_id, version_hash, memory.content_hash, version.prompt_contract_hash


def _optional_string(value: JsonValue | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{label} must be a bounded non-empty string")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("version manifest contains a duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "agent_configuration_hash",
    "prompt_contract_identity_hash",
    "resolve_prompt_policy",
    "safe_task_context_identity",
    "validate_prompt_policy_binding",
    "validate_prompt_text",
]
