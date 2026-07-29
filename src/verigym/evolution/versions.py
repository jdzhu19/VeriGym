"""Immutable Evolve-Context version freezing and zero-call replay."""

from __future__ import annotations

from verigym.core.hashing import content_hash
from verigym.experiments.schemas import PlanItem
from verigym.schemas.evolution import (
    AgentLineage,
    AgentUpdateManifest,
    AgentVersionManifest,
    AgentVersionSetManifest,
    MemoryPack,
    RewardVector,
    RunAgentVersionAssignment,
    RunAgentVersionAssignments,
    SanitizedTrainingSummary,
    TrajectoryDatasetManifest,
)

from .memory import (
    build_agent_version,
    validate_agent_version,
    validate_memory_pack,
    validate_training_summary,
)


def freeze_context_update(
    *,
    parent: AgentVersionManifest,
    dataset: TrajectoryDatasetManifest,
    training_summary: SanitizedTrainingSummary,
    memory_pack: MemoryPack,
    memory_builder_identity_hash: str,
    memory_builder_input_hash: str,
    memory_builder_output_hash: str,
    process_ledger_hash: str,
    version_id: str = "codex-cli-agent-v1",
    update_id: str = "evolve-context-v0-to-v1",
) -> tuple[AgentVersionManifest, AgentUpdateManifest]:
    """Freeze v1 so only its bounded memory differs from v0."""

    validate_agent_version(parent)
    validate_training_summary(training_summary)
    validate_memory_pack(memory_pack)
    if parent.update_type != "none" or parent.memory_pack_hash is not None:
        raise ValueError("Evolve-Context parent must be a memory-free base version")
    if training_summary.trajectory_dataset_hash != dataset.dataset_hash:
        raise ValueError("training summary and trajectory dataset identities disagree")
    v1 = build_agent_version(
        agent_version_id=version_id,
        status="frozen",
        parent_version_hash=parent.version_hash,
        update_type="context_memory",
        executable_in_m10b=True,
        base_agent_id=parent.base_agent_id,
        agent_descriptor_hash=parent.agent_descriptor_hash,
        model_id=parent.model_id,
        reasoning_effort=parent.reasoning_effort,
        auth_semantic_id=parent.auth_semantic_id,
        runtime_identity_hash=parent.runtime_identity_hash,
        tool_policy_hash=parent.tool_policy_hash,
        prompt_contract_hash=parent.prompt_contract_hash,
        source_commit=parent.source_commit,
        package_hashes=parent.package_hashes,
        image_hashes=parent.image_hashes,
        training_dataset_hash=dataset.dataset_hash,
        reward_schema_hash=content_hash(RewardVector.model_json_schema(mode="serialization")),
        reward_profile_hash=dataset.reward_profile_hash,
        memory_builder_identity_hash=memory_builder_identity_hash,
        memory_pack_hash=memory_pack.content_hash,
        model_weights_modified=False,
    )
    update_base = {
        "schema_version": "1.0",
        "update_id": update_id,
        "update_type": "context_memory",
        "parent_version_hash": parent.version_hash,
        "result_version_hash": v1.version_hash,
        "training_summary_hash": training_summary.summary_hash,
        "memory_builder_input_hash": memory_builder_input_hash,
        "memory_builder_output_hash": memory_builder_output_hash,
        "memory_pack_hash": memory_pack.content_hash,
        "process_ledger_hash": process_ledger_hash,
        "heldout_assets_loaded": False,
        "model_weights_modified": False,
    }
    update = AgentUpdateManifest.model_validate(
        {**update_base, "update_hash": content_hash(update_base)}
    )
    return v1, update


def replay_context_update(
    *,
    parent: AgentVersionManifest,
    result: AgentVersionManifest,
    update: AgentUpdateManifest,
    dataset: TrajectoryDatasetManifest,
    training_summary: SanitizedTrainingSummary,
    memory_pack: MemoryPack,
) -> None:
    """Validate frozen hashes without calling the memory builder."""

    validate_agent_version(parent)
    validate_agent_version(result)
    validate_training_summary(training_summary)
    validate_memory_pack(memory_pack)
    update_payload = update.model_dump(mode="json")
    update_hash = update_payload.pop("update_hash")
    if content_hash(update_payload) != update_hash:
        raise ValueError("agent update manifest identity changed")
    checks = {
        "parent": update.parent_version_hash == parent.version_hash,
        "result": update.result_version_hash == result.version_hash,
        "dataset": result.training_dataset_hash == dataset.dataset_hash,
        "summary": (
            update.training_summary_hash == training_summary.summary_hash
            and training_summary.trajectory_dataset_hash == dataset.dataset_hash
        ),
        "memory": (
            update.memory_pack_hash == memory_pack.content_hash
            and result.memory_pack_hash == memory_pack.content_hash
        ),
        "lineage": result.parent_version_hash == parent.version_hash,
        "weights": not result.model_weights_modified and not update.model_weights_modified,
    }
    mismatches = sorted(name for name, valid in checks.items() if not valid)
    if mismatches:
        raise ValueError("Evolve-Context replay mismatch: " + ", ".join(mismatches))


def build_run_version_assignments(
    assignments: list[RunAgentVersionAssignment],
) -> RunAgentVersionAssignments:
    """Freeze an explicit deterministic run-to-version provenance map."""

    ordered = sorted(assignments, key=lambda item: item.run_id)
    base = {
        "schema_version": "1.0",
        "assignments": [item.model_dump(mode="json") for item in ordered],
    }
    return RunAgentVersionAssignments.model_validate({**base, "manifest_hash": content_hash(base)})


def validate_run_version_assignments(
    manifest: RunAgentVersionAssignments,
) -> RunAgentVersionAssignments:
    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ValueError("run/version assignment manifest identity changed")
    return manifest


_STABLE_VERSION_FIELDS = (
    "base_agent_id",
    "agent_descriptor_hash",
    "model_id",
    "reasoning_effort",
    "auth_semantic_id",
    "runtime_identity_hash",
    "tool_policy_hash",
    "prompt_contract_hash",
    "source_commit",
    "package_hashes",
    "image_hashes",
)


def build_agent_lineage(
    *,
    parent: AgentVersionManifest,
    result: AgentVersionManifest,
    update: AgentUpdateManifest,
    lineage_id: str = "m10b-evolve-context-lineage",
) -> AgentLineage:
    """Bind the only executable M10B update: a memory-free v0 to context-only v1."""

    validate_agent_version(parent)
    validate_agent_version(result)
    if parent.update_type != "none" or result.update_type != "context_memory":
        raise ValueError("M10B lineage must bind a base version to one context-memory version")
    if result.parent_version_hash != parent.version_hash:
        raise ValueError("agent lineage parent identity differs")
    if (
        update.parent_version_hash != parent.version_hash
        or update.result_version_hash != result.version_hash
        or update.memory_pack_hash != result.memory_pack_hash
    ):
        raise ValueError("agent update does not bind the requested versions")
    changed = [
        field
        for field in _STABLE_VERSION_FIELDS
        if getattr(parent, field) != getattr(result, field)
    ]
    if changed:
        raise ValueError(
            "context-memory update changed stable identity fields: " + ", ".join(changed)
        )
    base = {
        "schema_version": "1.0",
        "lineage_id": lineage_id,
        "versions": [
            parent.model_dump(mode="json"),
            result.model_dump(mode="json"),
        ],
        "updates": [update.model_dump(mode="json")],
    }
    return AgentLineage.model_validate({**base, "lineage_hash": content_hash(base)})


def validate_agent_lineage(lineage: AgentLineage) -> AgentLineage:
    payload = lineage.model_dump(mode="json")
    expected = payload.pop("lineage_hash")
    if content_hash(payload) != expected:
        raise ValueError("agent lineage identity changed")
    if len(lineage.versions) != 2 or len(lineage.updates) != 1:
        raise ValueError("M10B lineage requires exactly v0, v1, and one context update")
    rebuilt = build_agent_lineage(
        parent=lineage.versions[0],
        result=lineage.versions[1],
        update=lineage.updates[0],
        lineage_id=lineage.lineage_id,
    )
    if rebuilt != lineage:
        raise ValueError("agent lineage content differs from its canonical form")
    return lineage


def build_agent_version_set(
    versions: list[AgentVersionManifest],
) -> AgentVersionSetManifest:
    """Freeze a stable, ID-sorted set used by experiment and exporter inputs."""

    ordered = sorted(
        (validate_agent_version(version) for version in versions), key=lambda x: x.agent_version_id
    )
    base = {
        "schema_version": "1.0",
        "versions": [version.model_dump(mode="json") for version in ordered],
    }
    return AgentVersionSetManifest.model_validate(
        {
            **base,
            "version_set_hash": content_hash(
                [version.model_dump(mode="json") for version in ordered]
            ),
        }
    )


def validate_agent_version_set(
    manifest: AgentVersionSetManifest,
) -> AgentVersionSetManifest:
    rebuilt = build_agent_version_set(manifest.versions)
    if rebuilt != manifest:
        raise ValueError("agent version-set identity or ordering changed")
    return manifest


def validate_plan_agent_version_binding(
    *,
    version: AgentVersionManifest,
    item: PlanItem,
    source_commit: str,
    package_hashes: dict[str, str],
) -> AgentVersionManifest:
    """Bind a frozen version to one ordinary immutable experiment plan item."""

    validate_agent_version(version)
    image_hashes: dict[str, str] = {}
    if item.docker_config is not None:
        verifier = item.docker_config.expected_image_id
        external = item.docker_config.external_agent
        if verifier is not None:
            image_hashes["verifier"] = verifier.removeprefix("sha256:")
        if external is not None:
            image_hashes["agent"] = external.expected_image_id.removeprefix("sha256:")
    expected = {
        "base_agent_id": item.system.agent_id,
        "agent_descriptor_hash": content_hash(item.system.agent_descriptor),
        "runtime_identity_hash": item.runtime_identity_hash,
        "tool_policy_hash": item.tool_policy_hash,
        "prompt_contract_hash": item.prompt_policy_hash,
        "source_commit": source_commit,
        "package_hashes": dict(sorted(package_hashes.items())),
        "image_hashes": dict(sorted(image_hashes.items())),
    }
    mismatches = sorted(name for name, value in expected.items() if getattr(version, name) != value)
    if mismatches:
        raise ValueError(
            "agent version differs from its frozen experiment plan: " + ", ".join(mismatches)
        )
    return version


__all__ = [
    "build_agent_lineage",
    "build_agent_version_set",
    "build_run_version_assignments",
    "freeze_context_update",
    "replay_context_update",
    "validate_agent_lineage",
    "validate_plan_agent_version_binding",
    "validate_agent_version_set",
    "validate_run_version_assignments",
]
