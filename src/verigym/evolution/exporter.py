"""Deterministic, zero-call export of observable repository trajectories."""

from __future__ import annotations

import json
import os
import re
import stat
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from verigym.core.artifact_policy import bound_text, bound_value
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import canonical_json, content_hash, hash_bytes
from verigym.core.trace import read_trace
from verigym.experiments.state import (
    atomic_dump_json,
    atomic_dump_jsonl,
    atomic_write_text,
    load_json_model,
    load_jsonl_models,
)
from verigym.reporting.loader import ValidatedRun, load_report_inputs
from verigym.schemas.evolution import (
    AgentVersionManifest,
    AgentVersionSetManifest,
    BoundedObservableText,
    CandidateFreezeObservation,
    ContentClass,
    EpisodeOutcomeObservation,
    EpisodeTrajectory,
    PublicTestObservation,
    RewardDerivationRecord,
    RewardProfile,
    TaskSplitManifest,
    TrajectoryDatasetManifest,
    TrajectoryDatasetStatistics,
    TrajectoryEligibility,
    TrajectoryEvent,
    TrajectoryEventType,
    TrajectoryIndexRecord,
    WorkspaceDeltaRecord,
)
from verigym.schemas.task import VeriTask

from .memory import validate_agent_version
from .rewards import (
    REPO_RTL_SPARSE_V1,
    classify_outcome,
    derive_reward,
    recompute_reward,
    reward_vector,
)
from .splits import validate_task_split

_EXPORT_POLICY_PAYLOAD = {
    "schema_version": "1.0",
    "policy_id": "observable_repo_trajectory_v1",
    "max_events": 2048,
    "max_event_bytes": 16 * 1024,
    "max_total_bytes": 1024 * 1024,
    "max_message_bytes": 4096,
    "unknown_content": "reject",
    "hidden_or_secret_content": "reject",
}
EXPORT_POLICY_HASH = content_hash(_EXPORT_POLICY_PAYLOAD)
_MAX_EVENTS = 2048
_MAX_EVENT_BYTES = 16 * 1024
_MAX_TRAJECTORY_BYTES = 1024 * 1024
_MAX_DATASET_BYTES = 256 * 1024 * 1024
_FORBIDDEN_KEY = re.compile(
    r"(?:chain.?of.?thought|private.?reason|hidden.?source|hidden.?output|reference.?patch|"
    r"golden.?rtl|credential.?value|proxy.?value|auth.?file|authorization|api.?key|"
    r"access.?token|cookie|refresh.?token)",
    re.IGNORECASE,
)
_FORBIDDEN_VALUE = re.compile(
    r"(?:/(?:data|etc|home|proc|root|run|sys|tmp|var)/|\\\\Users\\\\|"
    r"BEGIN [A-Z ]*PRIVATE KEY|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"https?://[^/\s:@]+:[^/\s@]+@)",
    re.IGNORECASE,
)
_SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "agent-version-manifest": AgentVersionManifest,
    "agent-version-set-manifest": AgentVersionSetManifest,
    "episode-trajectory": EpisodeTrajectory,
    "reward-derivation-record": RewardDerivationRecord,
    "reward-profile": RewardProfile,
    "task-split-manifest": TaskSplitManifest,
    "trajectory-dataset-manifest": TrajectoryDatasetManifest,
    "trajectory-event": TrajectoryEvent,
}


def _safe_json(value: Any, *, key: str = "") -> None:
    if (
        key
        and _FORBIDDEN_KEY.search(key)
        and key
        not in {
            "credential_values_exported",
            "hidden_regression_passed",
            "hidden_assets_exported",
            "private_reasoning_exported",
            "raw_host_paths_exported",
            "reference_solution_exported",
        }
    ):
        raise ConfigurationError(f"trajectory field is non-exportable: {key}")
    if isinstance(value, dict):
        for child_key, child in value.items():
            _safe_json(child, key=str(child_key))
    elif isinstance(value, list):
        for child in value:
            _safe_json(child, key=key)
    elif isinstance(value, str):
        if any(ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in value):
            raise ConfigurationError("trajectory contains unsafe control characters")
        if _FORBIDDEN_VALUE.search(value):
            raise ConfigurationError("trajectory contains a raw host path or credential-shaped URL")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError(f"trajectory JSON contains a duplicate key: {key!r}")
        value[key] = item
    return value


def _bounded_text(value: str, limit: int = 4096) -> BoundedObservableText:
    bounded, truncated = bound_text(value, limit)
    return BoundedObservableText(
        text=bounded,
        original_bytes=len(value.encode("utf-8")),
        original_sha256=hash_bytes(value.encode("utf-8")),
        truncated=truncated,
    )


def _event(
    events: list[TrajectoryEvent],
    event_type: TrajectoryEventType,
    content_class: ContentClass,
    payload: dict[str, Any],
) -> None:
    if len(events) >= _MAX_EVENTS:
        return
    _safe_json(payload)
    original_hash = content_hash(payload)
    bounded, truncated = bound_value(payload, _MAX_EVENT_BYTES)
    if not isinstance(bounded, dict):
        raise ConfigurationError("bounded trajectory event payload is not an object")
    events.append(
        TrajectoryEvent(
            sequence=len(events),
            event_type=event_type,
            content_class=content_class,
            payload=bounded,
            payload_sha256=original_hash,
            truncated=truncated,
        )
    )


def _split_for(task_id: str, manifest: TaskSplitManifest) -> str:
    for name in ("training", "validation", "heldout"):
        entries = getattr(manifest, name)
        if any(entry.task_id == task_id for entry in entries):
            return name
    raise ConfigurationError(f"run task is not present in the frozen split: {task_id}")


def _trajectory_eligibility(outcome: str) -> TrajectoryEligibility:
    if outcome == "infrastructure_invalid":
        return TrajectoryEligibility(eligible=False, reason="infrastructure_invalid")
    if outcome == "cancelled_or_interrupted":
        return TrajectoryEligibility(eligible=False, reason="cancelled_or_interrupted")
    return TrajectoryEligibility(eligible=True, reason="eligible")


def _codex_messages(run_dir: Path) -> list[str]:
    path = run_dir / "artifacts" / "codex_cli" / "parsed_events.jsonl"
    if not path.is_file():
        return []
    if path.is_symlink() or path.stat().st_size > 32 * 1024 * 1024:
        raise ConfigurationError("Codex parsed-event artifact is unsafe")
    messages: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"Codex parsed-event artifact is malformed at line {line_number}"
            ) from exc
        if not isinstance(payload, dict):
            raise ConfigurationError("Codex parsed-event record is not an object")
        if payload.get("category") != "message_completed":
            continue
        nested = payload.get("payload")
        text = nested.get("text") if isinstance(nested, dict) else None
        if isinstance(text, str) and text.strip():
            _safe_json(text)
            messages.append(text)
    return messages


def _trace_events(run: ValidatedRun, run_dir: Path, task: VeriTask) -> list[TrajectoryEvent]:
    events: list[TrajectoryEvent] = []
    category = (
        run.plan_item.category
        if run.plan_item is not None and run.plan_item.category is not None
        else str(task.metadata.get("category", "repository_rtl_repair"))
    )
    _event(
        events,
        "task_observation",
        "public_task",
        {
            "public_task_category": category,
            "task_type": task.task_type.value,
            "interaction_mode": run.manifest.interaction_mode,
            "editable_path_count": len(task.workspace.editable_globs),
            "public_test_interface_present": (
                "repository.public_test" in task.interaction.allowed_tools
            ),
        },
    )
    for message in _codex_messages(run_dir):
        _event(
            events,
            "agent_message",
            "agent_generated",
            _bounded_text(message).model_dump(mode="json"),
        )
    for source in read_trace(run_dir / "trace.jsonl", expected_run_id=run.manifest.run_id):
        if len(events) >= _MAX_EVENTS - 6:
            break
        payload = source.payload
        if source.event_type == "agent_action":
            action_type = str(payload.get("type", "unknown"))
            if action_type in {"message", "final"}:
                observed_message = payload.get("message")
                if isinstance(observed_message, str) and observed_message.strip():
                    _event(
                        events,
                        "agent_message",
                        "agent_generated",
                        _bounded_text(observed_message).model_dump(mode="json"),
                    )
            elif action_type in {"tool_call", "apply_patch"}:
                tool = (
                    str(payload.get("tool", "unknown"))
                    if action_type == "tool_call"
                    else "file.apply_patch"
                )
                arguments = payload.get("arguments")
                _event(
                    events,
                    "tool_invocation",
                    "workspace_metadata",
                    {
                        "tool_name": tool,
                        "argument_names": (
                            sorted(str(key) for key in arguments)
                            if isinstance(arguments, dict)
                            else ["patch"]
                            if action_type == "apply_patch"
                            else []
                        ),
                        "source_event_sequence": source.sequence,
                    },
                )
        elif source.event_type == "tool_request":
            arguments = payload.get("arguments")
            tool = str(payload.get("tool", "unknown"))
            public_test_id = (
                arguments.get("test_id")
                if isinstance(arguments, dict)
                and isinstance(arguments.get("test_id"), str)
                and tool == "repository.public_test"
                else None
            )
            _event(
                events,
                "tool_invocation",
                "workspace_metadata",
                {
                    "tool_name": tool,
                    "argument_names": (
                        sorted(str(key) for key in arguments) if isinstance(arguments, dict) else []
                    ),
                    "public_test_id": public_test_id,
                    "source_event_sequence": source.sequence,
                },
            )
        elif source.event_type == "tool_result":
            tool = str(payload.get("tool", "unknown"))
            result_payload: dict[str, Any] = {
                "tool_name": tool,
                "success": bool(payload.get("success", False)),
                "category": str(payload.get("category", "unknown")),
                "source_event_sequence": source.sequence,
            }
            if tool == "repository.public_test":
                observed_message = payload.get("message")
                if isinstance(observed_message, str) and observed_message:
                    result_payload["bounded_public_output"] = _bounded_text(
                        observed_message
                    ).model_dump(mode="json")
            _event(events, "tool_result", "public_tool_output", result_payload)
        elif source.event_type == "codex_cli_event_observed":
            _event(
                events,
                "tool_invocation",
                "workspace_metadata",
                {
                    "tool_name": "codex_cli_event",
                    "event_category": str(payload.get("category", "unknown"))[:128],
                    "upstream_type": str(payload.get("upstream_type", "unknown"))[:128],
                    "source_event_sequence": source.sequence,
                },
            )
    patch = run.manifest.repository_candidate.patch if run.manifest.repository_candidate else None
    delta = WorkspaceDeltaRecord(
        changed_files=run.scorecard.patch.changed_files[:256],
        added_lines=max(0, run.scorecard.patch.added_lines),
        deleted_lines=max(0, run.scorecard.patch.deleted_lines),
        outside_expected_files=run.scorecard.patch.changes_outside_expected_files[:256],
        patch_sha256=patch.patch_hash if patch is not None else None,
        patch_reproducible=patch.reapply_exact if patch is not None else None,
    )
    _event(events, "workspace_delta", "workspace_metadata", delta.model_dump(mode="json"))
    for public_outcome in run.manifest.repository_public_tests:
        observation = PublicTestObservation(
            test_id=public_outcome.test_id,
            passed=public_outcome.passed,
            failure_category=None if public_outcome.passed else public_outcome.category,
        )
        _event(events, "public_test", "public_tool_output", observation.model_dump(mode="json"))
    if run.manifest.candidate_hash is not None:
        candidate = CandidateFreezeObservation(
            candidate_hash=run.manifest.candidate_hash,
            patch_hash=patch.patch_hash if patch is not None else None,
            final_repository_hash=patch.candidate_repository_hash if patch is not None else None,
            patch_reproducible=patch.reapply_exact if patch is not None else None,
            changed_file_count=len(patch.changed_files) if patch is not None else 0,
        )
        _event(
            events,
            "candidate_freeze",
            "candidate_public",
            candidate.model_dump(mode="json"),
        )
    reward = reward_vector(run.manifest, run.scorecard)
    outcome = EpisodeOutcomeObservation(
        outcome_kind=reward.outcome_kind,
        scorecard_status=run.scorecard.status,
        termination_reason=run.scorecard.termination_reason,
        resolved=run.scorecard.resolved,
        infrastructure_error=not bool(reward.infrastructure_valid),
        policy_failure=reward.outcome_kind == "contained_workspace_policy_failure",
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
    )
    _event(events, "episode_outcome", "score_summary", outcome.model_dump(mode="json"))
    _event(
        events,
        "usage",
        "score_summary",
        {
            "wall_time_s": reward.wall_time_s,
            "input_tokens": reward.input_tokens,
            "output_tokens": reward.output_tokens,
            "public_tool_calls": reward.public_tool_calls,
        },
    )
    _event(events, "reward", "score_summary", reward.model_dump(mode="json"))
    return events


def _trajectory(
    run: ValidatedRun,
    *,
    root: Path,
    task: VeriTask,
    split_manifest: TaskSplitManifest,
    version: AgentVersionManifest,
) -> EpisodeTrajectory:
    run_dir = root / run.relative_path
    if run.plan_item is not None:
        options = run.plan_item.system.agent_options
        if (
            options.get("agent_version_id") != version.agent_version_id
            or options.get("agent_version_hash") != version.version_hash
        ):
            raise ConfigurationError("run plan does not bind its assigned frozen agent version")
        raw_memory = options.get("memory_pack")
        if version.memory_pack_hash is None:
            if raw_memory is not None:
                raise ConfigurationError("v0 run unexpectedly contains a memory pack")
        elif (
            not isinstance(raw_memory, dict)
            or raw_memory.get("content_hash") != version.memory_pack_hash
        ):
            raise ConfigurationError("v1 run memory pack differs from its frozen version")
    manifest_bytes = (run_dir / "run_manifest.json").read_bytes()
    scorecard_bytes = (run_dir / "scorecard.json").read_bytes()
    artifact_bytes = (run_dir / "artifact_manifest.json").read_bytes()
    split = _split_for(run.manifest.task_id, split_manifest)
    observation = (
        run.manifest.external_agent_observations[0]
        if run.manifest.external_agent_observations
        else None
    )
    auth_semantic_id = (
        observation.auth_semantic_id
        if observation is not None and observation.auth_semantic_id is not None
        else "offline.none"
    )
    model_identity_hash = content_hash(
        {
            "model_descriptor": run.manifest.model,
            "requested_model_id": (
                observation.requested_model_id if observation is not None else None
            ),
            "observed_model_id": (
                observation.observed_model_id if observation is not None else None
            ),
        }
    )
    codex_identity_hash = content_hash(
        observation if observation is not None else {"codex_cli": "not_observed"}
    )
    external_image = (
        run.plan_item.docker_config.external_agent.expected_image_id
        if run.plan_item is not None
        and run.plan_item.docker_config is not None
        and run.plan_item.docker_config.external_agent is not None
        else None
    )
    verifier_image = (
        run.manifest.runtime.image.resolved_image_id
        if run.manifest.runtime.image is not None
        else None
    )
    image_hash = (
        content_hash({"agent_image": external_image, "verifier_image": verifier_image})
        if external_image is not None or verifier_image is not None
        else None
    )
    events = _trace_events(run, run_dir, task)
    reward = reward_vector(run.manifest, run.scorecard)
    outcome = classify_outcome(run.scorecard)
    eligibility = _trajectory_eligibility(outcome)
    event_bytes = sum(len(canonical_json(event).encode("utf-8")) + 1 for event in events)
    if event_bytes > _MAX_TRAJECTORY_BYTES:
        raise ConfigurationError("trajectory exceeds the total-byte bound")
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "trajectory_id": f"trajectory:{run.manifest.run_id}",
        "run_id": run.manifest.run_id,
        "experiment_id": run.manifest.experiment_id,
        "plan_item_id": run.manifest.plan_item_id,
        "task_id": run.manifest.task_id,
        "task_hash": run.manifest.task_hash,
        "source_hash": run.manifest.source_hash,
        "base_repository_hash": (
            run.manifest.repository_task_identity.base_repository_hash
            if run.manifest.repository_task_identity is not None
            else None
        ),
        "split_id": split_manifest.split_id,
        "split": split,
        "agent_version_id": version.agent_version_id,
        "agent_version_hash": version.version_hash,
        "model_identity_hash": model_identity_hash,
        "codex_identity_hash": codex_identity_hash,
        "auth_semantic_id": auth_semantic_id,
        "prompt_hash": run.manifest.prompt_policy_hash or content_hash(run.manifest.prompt_policy),
        "memory_pack_hash": version.memory_pack_hash,
        "runtime_identity_hash": content_hash(run.manifest.runtime),
        "image_identity_hash": image_hash,
        "verifier_identity_hash": run.manifest.verifier_hash,
        "toolchain_identity_hash": content_hash(
            {
                "toolchain_profiles": run.manifest.toolchain_profiles,
                "resolved_profile_hash": run.manifest.resolved_profile_hash,
                "runtime_image": run.manifest.runtime.image,
            }
        ),
        "base_seed": run.manifest.base_seed
        if run.manifest.base_seed is not None
        else run.manifest.seed,
        "sample_index": run.manifest.sample_index or 0,
        "events": [event.model_dump(mode="json") for event in events],
        "event_count": len(events),
        "events_hash": content_hash(events),
        "run_manifest_hash": hash_bytes(manifest_bytes),
        "scorecard_hash": hash_bytes(scorecard_bytes),
        "artifact_manifest_hash": hash_bytes(artifact_bytes),
        "export_policy_id": "observable_repo_trajectory_v1",
        "eligibility": eligibility.model_dump(mode="json"),
        "reward": reward.model_dump(mode="json"),
        "reward_hash": content_hash(reward),
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solution_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
        "total_bytes": event_bytes,
    }
    _safe_json(base)
    return EpisodeTrajectory(**base, trajectory_hash=content_hash(base))


def _version_set(versions: Mapping[str, AgentVersionManifest]) -> AgentVersionSetManifest:
    ordered = [validate_agent_version(versions[key]) for key in sorted(versions)]
    payload = [item.model_dump(mode="json") for item in ordered]
    return AgentVersionSetManifest(versions=ordered, version_set_hash=content_hash(payload))


def _statistics(trajectories: list[EpisodeTrajectory]) -> TrajectoryDatasetStatistics:
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "record_count": len(trajectories),
        "eligible_count": sum(item.eligibility.eligible for item in trajectories),
        "outcome_counts": dict(
            sorted(Counter(item.reward.outcome_kind for item in trajectories).items())
        ),
        "split_counts": dict(sorted(Counter(item.split for item in trajectories).items())),
        "agent_version_counts": dict(
            sorted(Counter(item.agent_version_id for item in trajectories).items())
        ),
    }
    return TrajectoryDatasetStatistics(**base, statistics_hash=content_hash(base))


def _reward_record(run: ValidatedRun, trajectory: EpisodeTrajectory) -> RewardDerivationRecord:
    return derive_reward(
        run.manifest,
        run.scorecard,
        manifest_sha256=trajectory.run_manifest_hash,
        scorecard_sha256=trajectory.scorecard_hash,
        artifact_manifest_sha256=trajectory.artifact_manifest_hash,
    )


def _write_checksums(root: Path) -> None:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ConfigurationError("trajectory dataset contains a symlink")
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        relative = path.relative_to(root).as_posix()
        lines.append(f"{hash_bytes(path.read_bytes())}  {relative}")
    atomic_write_text(root / "SHA256SUMS", "\n".join(lines) + "\n")


class TrajectoryExporter:
    """Export only integrity-validated ordinary run artifacts."""

    def export(
        self,
        source: Path,
        output: Path,
        *,
        split_manifest: TaskSplitManifest,
        agent_versions: Mapping[str, AgentVersionManifest],
        run_agent_versions: Mapping[str, str],
        source_commit: str,
        package_identities: Mapping[str, str],
        reward_profile: RewardProfile = REPO_RTL_SPARSE_V1,
        dataset_id: str = "verigym-observable-trajectories",
    ) -> TrajectoryDatasetManifest:
        validate_task_split(split_manifest)
        version_set = _version_set(agent_versions)
        inputs = load_report_inputs(source)
        if inputs.invalid_inputs:
            raise ConfigurationError("trajectory export rejects corrupt or unsafe input artifacts")
        destination = output.expanduser()
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
                raise ConfigurationError("trajectory output must be a new or empty real directory")
        else:
            destination.mkdir(parents=True)
        (destination / "schemas").mkdir()
        trajectories: list[EpisodeTrajectory] = []
        rewards: list[RewardDerivationRecord] = []
        excluded: dict[str, str] = {}
        for run in sorted(inputs.valid_runs, key=lambda item: (item.plan_index, item.attempt)):
            version_id = run_agent_versions.get(run.manifest.run_id)
            if version_id is None:
                raise ConfigurationError(
                    f"run lacks a frozen agent-version assignment: {run.manifest.run_id}"
                )
            try:
                version = agent_versions[version_id]
            except KeyError as exc:
                raise ConfigurationError(f"unknown frozen agent version: {version_id}") from exc
            task = load_json_model(
                inputs.root / run.relative_path / "task_snapshot.json",
                VeriTask,
            )
            trajectory = _trajectory(
                run,
                root=inputs.root,
                task=task,
                split_manifest=split_manifest,
                version=version,
            )
            trajectories.append(trajectory)
            rewards.append(_reward_record(run, trajectory))
            if not trajectory.eligibility.eligible:
                excluded[trajectory.run_id] = trajectory.eligibility.reason
        trajectories.sort(key=lambda item: item.trajectory_id)
        rewards.sort(key=lambda item: item.run_id)
        _safe_json(split_manifest.model_dump(mode="json"))
        _safe_json(version_set.model_dump(mode="json"))
        _safe_json(reward_profile.model_dump(mode="json"))
        indices = [
            TrajectoryIndexRecord(
                trajectory_id=item.trajectory_id,
                run_id=item.run_id,
                task_id=item.task_id,
                split=item.split,
                agent_version_id=item.agent_version_id,
                eligible=item.eligibility.eligible,
                outcome_kind=item.reward.outcome_kind,
                trajectory_hash=item.trajectory_hash,
            )
            for item in trajectories
        ]
        atomic_dump_jsonl(destination / "trajectories.jsonl", trajectories)
        atomic_dump_jsonl(destination / "index.jsonl", indices)
        atomic_dump_jsonl(destination / "rewards.jsonl", rewards)
        atomic_dump_json(destination / "task-split-manifest.json", split_manifest)
        atomic_dump_json(destination / "reward-profile-manifest.json", reward_profile)
        atomic_dump_json(destination / "agent-version-manifest.json", version_set)
        statistics = _statistics(trajectories)
        atomic_dump_json(destination / "statistics.json", statistics)
        for name, model in sorted(_SCHEMA_MODELS.items()):
            atomic_dump_json(
                destination / "schemas" / f"{name}.schema.json",
                model.model_json_schema(mode="serialization"),
            )
        trajectory_bytes = (destination / "trajectories.jsonl").stat().st_size
        if trajectory_bytes > _MAX_DATASET_BYTES:
            raise ConfigurationError("trajectory dataset exceeds the total-byte bound")
        input_set_hash = content_hash(
            [
                {
                    "run_id": item.run_id,
                    "run_manifest_hash": item.run_manifest_hash,
                    "scorecard_hash": item.scorecard_hash,
                    "artifact_manifest_hash": item.artifact_manifest_hash,
                }
                for item in trajectories
            ]
        )
        dataset_identity = {
            "trajectory_hashes": [item.trajectory_hash for item in trajectories],
            "reward_hashes": [item.reward_hash for item in rewards],
            "split_manifest_hash": split_manifest.manifest_hash,
            "agent_version_manifest_hash": version_set.version_set_hash,
            "export_policy_hash": EXPORT_POLICY_HASH,
            "reward_profile_hash": reward_profile.profile_hash,
        }
        manifest = TrajectoryDatasetManifest(
            dataset_id=dataset_id,
            source_experiment_ids=[inputs.experiment_id],
            input_set_hash=input_set_hash,
            split_manifest_hash=split_manifest.manifest_hash,
            agent_version_manifest_hash=version_set.version_set_hash,
            export_policy_hash=EXPORT_POLICY_HASH,
            reward_profile_hash=reward_profile.profile_hash,
            included_run_ids=[item.run_id for item in trajectories],
            excluded_runs=excluded,
            record_count=len(trajectories),
            eligible_record_count=sum(item.eligibility.eligible for item in trajectories),
            byte_count=trajectory_bytes,
            licenses=sorted(
                {
                    task.source.license or "unknown"
                    for run in inputs.valid_runs
                    for task in [
                        load_json_model(
                            inputs.root / run.relative_path / "task_snapshot.json",
                            VeriTask,
                        )
                    ]
                }
            ),
            attributions=sorted(
                {
                    task.source.attribution or "unknown"
                    for run in inputs.valid_runs
                    for task in [
                        load_json_model(
                            inputs.root / run.relative_path / "task_snapshot.json",
                            VeriTask,
                        )
                    ]
                }
            ),
            source_commit=source_commit,
            package_identities=dict(sorted(package_identities.items())),
            dataset_hash=content_hash(dataset_identity),
        )
        _safe_json(manifest.model_dump(mode="json"))
        atomic_dump_json(destination / "dataset-manifest.json", manifest)
        _write_checksums(destination)
        validate_trajectory_dataset(destination)
        return manifest


def _validate_trajectory(item: EpisodeTrajectory) -> None:
    for event in item.events:
        _safe_json(event.payload)
        if content_hash(event.payload) != event.payload_sha256 and not event.truncated:
            raise ConfigurationError("trajectory event payload identity changed")
    if content_hash(item.events) != item.events_hash:
        raise ConfigurationError("trajectory event-set identity changed")
    if content_hash(item.reward) != item.reward_hash:
        raise ConfigurationError("trajectory reward identity changed")
    payload = item.model_dump(mode="json")
    expected = payload.pop("trajectory_hash")
    if content_hash(payload) != expected:
        raise ConfigurationError("trajectory identity changed")


def _validate_reward_record(
    record: RewardDerivationRecord,
    trajectory: EpisodeTrajectory,
    profile: RewardProfile,
) -> None:
    if (
        record.run_id != trajectory.run_id
        or record.reward != trajectory.reward
        or record.reward_hash != trajectory.reward_hash
        or record.source_artifact_hashes
        != {
            "artifact_manifest.json": trajectory.artifact_manifest_hash,
            "run_manifest.json": trajectory.run_manifest_hash,
            "scorecard.json": trajectory.scorecard_hash,
        }
        or record.scalar_profile_id != profile.profile_id
        or record.scalar_profile_hash != profile.profile_hash
        or record.scalar_reward != profile.outcome_values[record.reward.outcome_kind]
        or content_hash(record.reward) != record.reward_hash
    ):
        raise ConfigurationError("reward derivation differs from its trajectory or profile")


def _validate_profile(profile: RewardProfile) -> None:
    payload = profile.model_dump(mode="json")
    expected = payload.pop("profile_hash")
    if content_hash(payload) != expected:
        raise ConfigurationError("reward profile identity changed")


def validate_trajectory_dataset(root: Path) -> TrajectoryDatasetManifest:
    """Validate a sealed dataset without model, runtime, verifier, or network calls."""

    destination = root.resolve(strict=True)
    if destination.is_symlink() or not destination.is_dir():
        raise ConfigurationError("trajectory dataset root is unsafe")
    checksums = destination / "SHA256SUMS"
    if checksums.is_symlink() or not checksums.is_file():
        raise ConfigurationError("trajectory dataset has no safe SHA256SUMS")
    for directory, names, _files in os.walk(destination, followlinks=False):
        for name in names:
            metadata = os.lstat(Path(directory) / name)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ConfigurationError("trajectory dataset contains an unsafe directory entry")
    expected_paths: set[str] = set()
    for line in checksums.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if (
            not separator
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in expected_paths
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ConfigurationError("trajectory checksum manifest is malformed")
        path = destination / relative
        metadata = os.lstat(path)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or hash_bytes(path.read_bytes()) != digest
        ):
            raise ConfigurationError(f"trajectory checksum failed: {relative}")
        expected_paths.add(relative)
    actual_paths = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if expected_paths != actual_paths:
        raise ConfigurationError("trajectory checksum manifest does not cover every file")
    manifest = load_json_model(
        destination / "dataset-manifest.json",
        TrajectoryDatasetManifest,
    )
    split = load_json_model(destination / "task-split-manifest.json", TaskSplitManifest)
    validate_task_split(split)
    versions = load_json_model(
        destination / "agent-version-manifest.json",
        AgentVersionSetManifest,
    )
    for version in versions.versions:
        validate_agent_version(version)
    if (
        content_hash([item.model_dump(mode="json") for item in versions.versions])
        != versions.version_set_hash
    ):
        raise ConfigurationError("agent version-set identity changed")
    profile = load_json_model(
        destination / "reward-profile-manifest.json",
        RewardProfile,
    )
    _validate_profile(profile)
    trajectories = load_jsonl_models(destination / "trajectories.jsonl", EpisodeTrajectory)
    indices = load_jsonl_models(destination / "index.jsonl", TrajectoryIndexRecord)
    rewards = load_jsonl_models(destination / "rewards.jsonl", RewardDerivationRecord)
    statistics = load_json_model(
        destination / "statistics.json",
        TrajectoryDatasetStatistics,
    )
    for item in trajectories:
        _validate_trajectory(item)
    if [item.run_id for item in rewards] != [item.run_id for item in trajectories]:
        raise ConfigurationError("reward records differ from trajectories.jsonl")
    for record, trajectory in zip(rewards, trajectories, strict=True):
        _validate_reward_record(record, trajectory, profile)
    if statistics != _statistics(trajectories):
        raise ConfigurationError("trajectory statistics differ from their records")
    expected_indices = [
        TrajectoryIndexRecord(
            trajectory_id=item.trajectory_id,
            run_id=item.run_id,
            task_id=item.task_id,
            split=item.split,
            agent_version_id=item.agent_version_id,
            eligible=item.eligibility.eligible,
            outcome_kind=item.reward.outcome_kind,
            trajectory_hash=item.trajectory_hash,
        )
        for item in trajectories
    ]
    if indices != expected_indices:
        raise ConfigurationError("trajectory index differs from trajectories.jsonl")
    if manifest.record_count != len(trajectories):
        raise ConfigurationError("trajectory manifest record count changed")
    if manifest.eligible_record_count != sum(item.eligibility.eligible for item in trajectories):
        raise ConfigurationError("trajectory manifest eligibility count changed")
    expected_excluded = {
        item.run_id: item.eligibility.reason
        for item in trajectories
        if not item.eligibility.eligible
    }
    if (
        manifest.included_run_ids != [item.run_id for item in trajectories]
        or manifest.excluded_runs != expected_excluded
    ):
        raise ConfigurationError("trajectory manifest inclusion accounting changed")
    if manifest.byte_count != (destination / "trajectories.jsonl").stat().st_size:
        raise ConfigurationError("trajectory manifest byte count changed")
    if manifest.input_set_hash != content_hash(
        [
            {
                "run_id": item.run_id,
                "run_manifest_hash": item.run_manifest_hash,
                "scorecard_hash": item.scorecard_hash,
                "artifact_manifest_hash": item.artifact_manifest_hash,
            }
            for item in trajectories
        ]
    ):
        raise ConfigurationError("trajectory input-set identity changed")
    dataset_identity = {
        "trajectory_hashes": [item.trajectory_hash for item in trajectories],
        "reward_hashes": [item.reward_hash for item in rewards],
        "split_manifest_hash": split.manifest_hash,
        "agent_version_manifest_hash": versions.version_set_hash,
        "export_policy_hash": EXPORT_POLICY_HASH,
        "reward_profile_hash": profile.profile_hash,
    }
    if (
        manifest.dataset_hash != content_hash(dataset_identity)
        or manifest.split_manifest_hash != split.manifest_hash
        or manifest.agent_version_manifest_hash != versions.version_set_hash
        or manifest.reward_profile_hash != profile.profile_hash
        or manifest.export_policy_hash != EXPORT_POLICY_HASH
    ):
        raise ConfigurationError("trajectory dataset binding changed")
    for name, model in sorted(_SCHEMA_MODELS.items()):
        expected_schema = model.model_json_schema(mode="serialization")
        actual_schema = json.loads(
            (destination / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
        if actual_schema != expected_schema:
            raise ConfigurationError(f"trajectory embedded schema changed: {name}")
    return manifest


def replay_trajectory_dataset(root: Path, source: Path) -> TrajectoryDatasetManifest:
    """Recompute dataset rewards and source bindings without any external call."""

    manifest = validate_trajectory_dataset(root)
    inputs = load_report_inputs(source)
    if inputs.invalid_inputs:
        raise ConfigurationError("trajectory replay rejects corrupt source run artifacts")
    runs = {run.manifest.run_id: run for run in inputs.valid_runs}
    trajectories = load_jsonl_models(root / "trajectories.jsonl", EpisodeTrajectory)
    rewards = load_jsonl_models(root / "rewards.jsonl", RewardDerivationRecord)
    for trajectory, record in zip(trajectories, rewards, strict=True):
        try:
            run = runs[trajectory.run_id]
        except KeyError as exc:
            raise ConfigurationError("trajectory source run is unavailable during replay") from exc
        recompute_reward(record, run.manifest, run.scorecard)
        run_dir = inputs.root / run.relative_path
        if (
            hash_bytes((run_dir / "run_manifest.json").read_bytes()) != trajectory.run_manifest_hash
            or hash_bytes((run_dir / "scorecard.json").read_bytes()) != trajectory.scorecard_hash
            or hash_bytes((run_dir / "artifact_manifest.json").read_bytes())
            != trajectory.artifact_manifest_hash
            or run.manifest.task_hash != trajectory.task_hash
            or run.manifest.source_hash != trajectory.source_hash
        ):
            raise ConfigurationError("trajectory replay source/task/artifact binding changed")
    return manifest


def inspect_trajectory_source(root: Path) -> dict[str, Any]:
    inputs = load_report_inputs(root)
    return {
        "schema_version": "1.0",
        "source_kind": inputs.source_kind,
        "experiment_id": inputs.experiment_id,
        "planned_count": inputs.planned_count,
        "valid_run_count": len(inputs.valid_runs),
        "invalid_input_count": len(inputs.invalid_inputs),
        "model_calls": 0,
        "runtime_calls": 0,
        "network_calls": 0,
    }


__all__ = [
    "EXPORT_POLICY_HASH",
    "TrajectoryExporter",
    "inspect_trajectory_source",
    "replay_trajectory_dataset",
    "validate_trajectory_dataset",
]
