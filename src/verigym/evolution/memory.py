"""Bounded memory-pack policy and immutable agent-version helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from verigym.core.hashing import canonical_json, content_hash
from verigym.schemas.evolution import (
    AgentVersionManifest,
    EpisodeTrajectory,
    MemoryPack,
    MemoryPackSection,
    SanitizedTrainingEpisode,
    SanitizedTrainingSummary,
)

_SECTION_ORDER = (
    "principles",
    "public_test_strategy",
    "workspace_policy_reminders",
    "debugging_checklist",
    "patch_discipline",
)
_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("code_fence", re.compile(r"```|~~~")),
    (
        "rtl_code",
        re.compile(
            r"\b(?:module|endmodule|always_(?:ff|comb)|assign|logic|wire|reg)\b"
            r"|(?:<=|=>)|\b\d+'\s*[bdho][0-9a-fxz_]+",
            re.IGNORECASE,
        ),
    ),
    ("task_id", re.compile(r"\brepo-rtl[/_:-]|\brepo_[a-z0-9_-]+", re.IGNORECASE)),
    (
        "repository_path",
        re.compile(r"(?:^|\s)(?:/|\.{1,2}/)|\b[\w.-]+/(?:[\w.-]+/)*[\w.-]+|\.(?:sv|v)\b"),
    ),
    ("hash", re.compile(r"\b[0-9a-f]{40,64}\b", re.IGNORECASE)),
    (
        "hidden_or_reference",
        re.compile(r"\b(?:hidden|golden|reference patch|reference solution)\b", re.IGNORECASE),
    ),
    (
        "credential",
        re.compile(
            r"\b(?:credential|password|api[_ -]?key|auth(?:entication)? file|proxy value|token)\b",
            re.IGNORECASE,
        ),
    ),
)


def _memory_payload(sections: Sequence[MemoryPackSection]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "policy_id": "task_independent_code_free_memory_v1",
        "sections": [section.model_dump(mode="json") for section in sections],
        "task_independent": True,
        "code_free": True,
    }


def validate_memory_text(text: str, *, heldout_only_tokens: Sequence[str] = ()) -> None:
    """Reject code, identifiers, paths, secrets, and held-out-specific content."""

    if not text or text != text.strip() or len(text) > 512:
        raise ValueError("memory items must be nonempty trimmed strings up to 512 characters")
    if any(ord(character) < 32 and character not in {"\t"} for character in text):
        raise ValueError("memory items cannot contain control characters")
    for category, pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"memory content policy rejected {category}")
    lowered = text.casefold()
    for token in heldout_only_tokens:
        normalized = token.strip().casefold()
        if len(normalized) >= 4 and normalized in lowered:
            raise ValueError("memory contains held-out-only content")


def build_memory_pack(
    values: Mapping[str, Sequence[str]],
    *,
    heldout_only_tokens: Sequence[str] = (),
    memory_pack_id: str = "evolve-context-v1-memory",
) -> MemoryPack:
    """Validate model output and create one canonical code-free memory pack."""

    if set(values) != set(_SECTION_ORDER):
        raise ValueError("memory builder output must contain exactly the five approved sections")
    sections: list[MemoryPackSection] = []
    for name in _SECTION_ORDER:
        items = list(values[name])
        if not items:
            raise ValueError(f"memory section {name!r} is empty")
        for item in items:
            validate_memory_text(item, heldout_only_tokens=heldout_only_tokens)
        sections.append(MemoryPackSection(section=name, items=items))  # type: ignore[arg-type]
    payload = _memory_payload(sections)
    encoded = canonical_json(payload).encode("utf-8")
    if len(encoded) > 16_384:
        raise ValueError("memory pack exceeds the 16 KiB content limit")
    return MemoryPack(
        memory_pack_id=memory_pack_id,
        sections=sections,
        total_utf8_bytes=len(encoded),
        content_hash=content_hash(payload),
    )


def validate_memory_pack(
    memory: MemoryPack,
    *,
    heldout_only_tokens: Sequence[str] = (),
) -> MemoryPack:
    """Recompute the content identity without calling the memory builder."""

    rebuilt = build_memory_pack(
        {section.section: section.items for section in memory.sections},
        heldout_only_tokens=heldout_only_tokens,
        memory_pack_id=memory.memory_pack_id,
    )
    if rebuilt != memory:
        raise ValueError("memory pack content or identity changed after freezing")
    return memory


def build_agent_version(**values: Any) -> AgentVersionManifest:
    """Create a frozen version whose identity covers every normalized schema field."""

    payload = dict(values)
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("status", "frozen")
    payload.setdefault("model_weights_modified", False)
    payload.pop("version_hash", None)
    provisional = AgentVersionManifest(**payload, version_hash="0" * 64)
    normalized = provisional.model_dump(mode="json", exclude={"version_hash"})
    return provisional.model_copy(update={"version_hash": content_hash(normalized)})


def validate_agent_version(version: AgentVersionManifest) -> AgentVersionManifest:
    payload = version.model_dump(mode="json")
    expected = payload.pop("version_hash")
    if content_hash(payload) != expected:
        raise ValueError("agent version identity changed after freezing")
    return version


def prepare_training_summary(
    trajectories: Sequence[EpisodeTrajectory],
    *,
    split_manifest_hash: str,
    trajectory_dataset_hash: str,
    summary_id: str = "m10b-v0-training-summary",
) -> SanitizedTrainingSummary:
    """Strip task identities and retain only bounded observable learning signals."""

    episodes: list[SanitizedTrainingEpisode] = []
    for trajectory in sorted(trajectories, key=lambda item: item.trajectory_id):
        if trajectory.split != "training" or not trajectory.eligibility.eligible:
            continue
        category = "repository_rtl_repair"
        actions: list[str] = []
        public: list[bool] = []
        failure_labels: list[str] = []
        for event in trajectory.events:
            if event.event_type == "task_observation":
                value = event.payload.get("public_task_category")
                if isinstance(value, str):
                    category = value
            elif event.event_type in {"tool_invocation", "workspace_delta", "candidate_freeze"}:
                actions.append(event.event_type)
            elif event.event_type == "public_test":
                passed = event.payload.get("passed")
                if isinstance(passed, bool):
                    public.append(passed)
            elif event.event_type == "episode_outcome":
                label = event.payload.get("outcome_kind")
                if isinstance(label, str) and label != "resolved_candidate":
                    failure_labels.append(label)
        reward = trajectory.reward
        episodes.append(
            SanitizedTrainingEpisode(
                public_task_category=category,
                observable_action_summary=actions[:64],
                public_test_outcomes=public[:64],
                patch_metrics={
                    "changed_file_count": reward.changed_file_count or 0,
                    "added_lines": reward.added_lines or 0,
                    "deleted_lines": reward.deleted_lines or 0,
                    "public_tool_calls": reward.public_tool_calls or 0,
                },
                outcome_kind=reward.outcome_kind,
                reward=reward,
                compile_passed=(
                    bool(reward.candidate_compile_passed)
                    if reward.candidate_compile_passed is not None
                    else None
                ),
                hidden_regression_passed=(
                    bool(reward.hidden_regression_passed)
                    if reward.hidden_regression_passed is not None
                    else None
                ),
                generalized_failure_labels=sorted(set(failure_labels))[:32],
            )
        )
    if not episodes:
        raise ValueError("sanitized training summary has no eligible training trajectories")
    base = {
        "schema_version": "1.0",
        "summary_id": summary_id,
        "split_manifest_hash": split_manifest_hash,
        "trajectory_dataset_hash": trajectory_dataset_hash,
        "episodes": [episode.model_dump(mode="json") for episode in episodes],
        "hidden_assets_included": False,
        "references_included": False,
        "private_reasoning_included": False,
        "heldout_assets_included": False,
    }
    return SanitizedTrainingSummary.model_validate({**base, "summary_hash": content_hash(base)})


def validate_training_summary(summary: SanitizedTrainingSummary) -> SanitizedTrainingSummary:
    payload = summary.model_dump(mode="json")
    expected = payload.pop("summary_hash")
    if content_hash(payload) != expected:
        raise ValueError("sanitized training summary identity changed")
    return summary


__all__ = [
    "build_agent_version",
    "build_memory_pack",
    "prepare_training_summary",
    "validate_agent_version",
    "validate_memory_pack",
    "validate_memory_text",
    "validate_training_summary",
]
