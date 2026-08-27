"""Strict contract checks for the bounded OpenHands HWE development SFT pilot."""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.memory import build_agent_version, validate_agent_version
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
from verigym.plugin_api import JsonValue
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest, TaskSplitManifest
from verigym.schemas.options import validate_plugin_options

from .hwe_agent import OpenHandsHweAgentAdapter

OPENHANDS_BOUNDED_SFT_PILOT_FORMAT = "verigym_qwen35_hwe_openhands_bounded_sft_pilot_v1"
OPENHANDS_BOUNDED_SFT_PILOT_CONTRACT_HASH = (
    "882a2bfc9b7d4c0e43bcc9d97724b7dcdd05c6129d63e0ab85461c9d6ab3037d"
)
OPENHANDS_BOUNDED_SFT_PILOT_BASELINE_COMMIT = "0ad17bd8259141e63efdfd7914407ed821993b60"
OPENHANDS_BOUNDED_SFT_PILOT_SPLIT_HASH = (
    "68c76482f81ac4bbbb64a54d0886fda4b1a0b7c38e489916b919f768ec3146e6"
)
OPENHANDS_BOUNDED_SFT_PILOT_SPLIT_SHA256 = (
    "844bf3f65d648f1e8542b80e55d16d6612b614df5283b350123b33c79b2c13bc"
)
OPENHANDS_BOUNDED_SFT_PILOT_QUALIFICATION_SHA256 = (
    "27980ef9b0537c1a1873ea9ad7894c6e0edd3564b5ac503209703322ab8042a3"
)
OPENHANDS_BOUNDED_SFT_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-bounded-sft-pilot-v1"
OPENHANDS_BOUNDED_SFT_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_BOUNDED_SFT_PILOT_V1"
OPENHANDS_BOUNDED_SFT_BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"
OPENHANDS_BOUNDED_SFT_API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"

_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"

OPENHANDS_BOUNDED_SFT_TRAINING_TASKS = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2248",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2282",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2468",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2469",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2589",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2802",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2916",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3168",
)
OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3191",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204",
)
OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS = (
    "hwe-bench/repo-repair-v1/chipsalliance__rocket-chip__pr-3065",
    "hwe-bench/repo-repair-v1/lowRISC__ibex__pr-222",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2374",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2945",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3107",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3171",
)


@dataclass(frozen=True)
class BoundedSftDataGate:
    """Result of applying the frozen training/validation admission gate."""

    satisfied: bool
    eligible_training_trajectories: int
    distinct_training_tasks: int
    eligible_validation_trajectories: int
    distinct_validation_tasks: int
    reason: str | None


def build_bounded_sft_agent_version(
    *, source_commit: str, image_locks: Mapping[str, Any]
) -> AgentVersionManifest:
    """Bind every train/validation task image and the exact OpenHands policy."""

    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise ValueError("bounded SFT agent version requires a full Git SHA")
    expected_tasks = set(
        (*OPENHANDS_BOUNDED_SFT_TRAINING_TASKS, *OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)
    )
    if set(image_locks) != expected_tasks:
        raise ValueError("bounded SFT agent version requires every train/validation image lock")

    lock_receipts: dict[str, str] = {}
    agent_image_receipts: dict[str, str] = {}
    verifier_image_receipts: dict[str, str] = {}
    for task_id in sorted(expected_tasks):
        lock = image_locks[task_id]
        if getattr(lock, "task_id", None) != task_id:
            raise ValueError("bounded SFT image lock task identity changed")
        lock_hash = str(getattr(lock, "lock_hash", ""))
        agent_image = str(getattr(lock, "derived_agent_image_id", ""))
        verifier_image = str(getattr(lock, "verifier_base_image_id", ""))
        if (
            len(lock_hash) != 64
            or not agent_image.startswith("sha256:")
            or not verifier_image.startswith("sha256:")
        ):
            raise ValueError("bounded SFT image lock is incomplete")
        lock_receipts[task_id] = lock_hash
        agent_image_receipts[task_id] = agent_image.removeprefix("sha256:")
        verifier_image_receipts[task_id] = verifier_image.removeprefix("sha256:")

    # AgentVersionManifest is transported through bounded plugin options. Bind the
    # complete task-to-image maps by content hash so the manifest remains below the
    # generic 4096-byte per-string boundary without weakening image identity.
    image_hashes = {
        "bounded_sft_agent_image_set": content_hash(agent_image_receipts),
        "bounded_sft_verifier_image_set": content_hash(verifier_image_receipts),
    }

    agent = OpenHandsHweAgentAdapter()
    spec = agent.prompt_policy_spec
    assert spec is not None
    prompt_contract_hash = content_hash(
        {
            "resolver_id": "agent_execution_prompt_policy_v1",
            "prompt_contract_id": spec.prompt_contract_id,
            "prompt_contract_version": spec.prompt_contract_version,
            "interaction_mode": InteractionMode.AGENT,
            "task_context_policy": spec.task_context_policy,
            "base_instruction_policy": spec.base_instruction_policy,
            "content_visibility_policy": spec.content_visibility_policy,
            "max_prompt_bytes": spec.max_prompt_bytes,
            "max_task_context_bytes": spec.max_task_context_bytes,
            "agent_descriptor_hash": content_hash(agent.descriptor),
        }
    )
    package_root = Path(__file__).resolve().parent
    source_hashes = {
        path.name: hash_bytes(path.read_bytes())
        for path in sorted(package_root.glob("*.py"))
        if path.is_file() and not path.is_symlink()
    }
    version = build_agent_version(
        agent_version_id=OPENHANDS_BOUNDED_SFT_AGENT_VERSION_ID,
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=False,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id="openai/deepseek-v4-flash",
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash=content_hash(
            {
                "python_executable_sha256": hash_bytes(Path(sys.executable).read_bytes()),
                "openhands_sdk_version": "1.42.1",
                "litellm_version": "1.93.0",
                "tiktoken_version": "0.7.0",
                "pilot_contract_hash": OPENHANDS_BOUNDED_SFT_PILOT_CONTRACT_HASH,
                "collection_profile_id": "hwe_production_native_shell_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "task_image_lock_hashes": lock_receipts,
                "agent_runtime_network": "none",
                "whole_episode_retries": 0,
                "provider_request_retries": 0,
            }
        ),
        tool_policy_hash=content_hash(deepseek_harness_tool_definitions()),
        prompt_contract_hash=prompt_contract_hash,
        source_commit=source_commit,
        package_hashes={
            "litellm-1.93.0-wheel": _LITELLM_WHEEL_SHA256,
            "openhands-sdk-1.42.1-wheel": _OPENHANDS_SDK_WHEEL_SHA256,
            "tiktoken-0.7.0-wheel": _TIKTOKEN_WHEEL_SHA256,
            "verigym-openhands-source": content_hash(source_hashes),
            "verigym-source-commit": content_hash(source_commit),
        },
        image_hashes=image_hashes,
        training_dataset_hash=None,
        reward_schema_hash=None,
        reward_profile_hash=None,
        memory_builder_identity_hash=None,
        memory_pack_hash=None,
        model_weights_modified=False,
    )
    return validate_agent_version(version)


def build_bounded_sft_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build and prevalidate the exact per-episode OpenHands plugin options."""

    version = validate_agent_version(agent_version)
    if (
        version.agent_version_id != OPENHANDS_BOUNDED_SFT_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != "openai/deepseek-v4-flash"
    ):
        raise ValueError("bounded SFT agent options require the frozen agent version")
    manifest_json = json.dumps(
        version.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    options: dict[str, JsonValue] = {
        "model_id": "openai/deepseek-v4-flash",
        "base_url_env": OPENHANDS_BOUNDED_SFT_BASE_URL_ENV,
        "api_key_env": OPENHANDS_BOUNDED_SFT_API_KEY_ENV,
        "max_iterations": 200,
        "max_process_time_s": 3_600,
        "max_output_tokens": 2_048,
        "max_context_tokens": 65_536,
        "seed": seed,
        "temperature": 0,
        "top_p": 1,
        "whole_episode_retries": 0,
        "expected_sdk_version": "1.42.1",
        "campaign_role": "training",
        "capture_training_transcript": True,
        "agent_version_id": version.agent_version_id,
        "agent_version_hash": version.version_hash,
        "agent_version_manifest_json": manifest_json,
        "collection_profile_id": "hwe_production_native_shell_v2",
    }
    return validate_plugin_options(options)


def load_bounded_sft_pilot_contract(path: Path) -> dict[str, Any]:
    """Read and validate the exact bounded pilot contract."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError("bounded SFT pilot contract must be a small regular file")
    parsed = json.loads(path.read_bytes())
    if not isinstance(parsed, dict):
        raise ValueError("bounded SFT pilot contract must be a JSON object")
    return validate_bounded_sft_pilot_contract(parsed)


def validate_bounded_sft_pilot_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    """Reject contract, schedule, split, model, or leakage drift."""

    contract = dict(value)
    supplied_hash = contract.get("contract_hash")
    base = {key: item for key, item in contract.items() if key != "contract_hash"}
    computed_hash = content_hash(base)
    if supplied_hash != computed_hash or computed_hash != OPENHANDS_BOUNDED_SFT_PILOT_CONTRACT_HASH:
        raise ValueError("bounded SFT pilot contract identity changed")
    if contract.get("format_id") != OPENHANDS_BOUNDED_SFT_PILOT_FORMAT:
        raise ValueError("bounded SFT pilot format changed")

    source = _mapping(contract, "source")
    _require_equal(source, "baseline_commit", OPENHANDS_BOUNDED_SFT_PILOT_BASELINE_COMMIT)
    _require_equal(source, "task_split_manifest_hash", OPENHANDS_BOUNDED_SFT_PILOT_SPLIT_HASH)
    _require_equal(source, "task_split_file_sha256", OPENHANDS_BOUNDED_SFT_PILOT_SPLIT_SHA256)
    _require_equal(
        source,
        "qualification_progress_file_sha256",
        OPENHANDS_BOUNDED_SFT_PILOT_QUALIFICATION_SHA256,
    )
    _require_equal(source, "qualification_status", "completed")

    teacher = _mapping(contract, "teacher")
    frozen_teacher = {
        "scaffold": "openhands-sdk-1.42.1-verigym-broker-v1",
        "model_transport_id": "openai/deepseek-v4-flash",
        "model_identity": "deepseek-v4-flash",
        "reasoning": "thinking-disabled",
        "openhands_sdk_version": "1.42.1",
        "litellm_version": "1.93.0",
        "tiktoken_version": "0.7.0",
        "tool_contract": "hwe_native_shell_v2",
        "tool_schema_count": 6,
        "temperature": 0,
        "top_p": 1,
        "max_context_tokens": 65_536,
        "max_output_tokens": 2_048,
        "max_iterations": 200,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "capture_training_transcript": True,
        "sandbox_network": "none",
    }
    if teacher != frozen_teacher:
        raise ValueError("bounded SFT teacher or tool policy changed")

    student = _mapping(contract, "student")
    if (
        student.get("base_model") != "Qwen3.5-9B"
        or student.get("trust_remote_code") is not False
        or student.get("rllm_commit") != "1d1109a655e291b3001d8526d7c9ecc5b9328226"
        or student.get("verl_version") != "0.8.0"
    ):
        raise ValueError("bounded SFT student software identity changed")

    collection = _mapping(contract, "collection")
    training = _schedule(collection, "training_schedule", expected_count=16)
    validation = _schedule(collection, "validation_schedule", expected_count=4)
    heldout = _string_sequence(collection, "heldout_task_ids")
    if tuple(heldout) != OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS:
        raise ValueError("bounded SFT held-out order or membership changed")
    _validate_schedule(training, role="training", allowed=OPENHANDS_BOUNDED_SFT_TRAINING_TASKS)
    _validate_schedule(
        validation,
        role="validation",
        allowed=OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS,
    )
    if sum(bool(item.get("predecessor")) for item in training) != 1:
        raise ValueError("bounded SFT schedule requires exactly one predecessor")
    predecessor = next(item for item in training if item.get("predecessor"))
    predecessor_contract = _mapping(collection, "predecessor")
    if predecessor.get("episode_id") != predecessor_contract.get("episode_id"):
        raise ValueError("bounded SFT predecessor schedule binding changed")
    _require_equal(
        predecessor_contract,
        "dataset_hash",
        "e1331ed287cedc76141d9f882992c4a159b76c759371170d259aa6d15492f511",
    )
    _require_equal(
        predecessor_contract,
        "trajectory_hash",
        "7ed148bf5e206d214d7abfdd5612275283e1e2e0643c8b8df3d5dcd5107c7416",
    )
    for key, expected in (
        ("scheduled_training_episodes", 16),
        ("scheduled_validation_episodes", 4),
        ("scheduled_heldout_tasks", 6),
        ("new_provider_episode_limit", 19),
    ):
        _require_equal(collection, key, expected)

    bindings = _mapping(contract, "task_bindings")
    expected_tasks = set(
        (
            *OPENHANDS_BOUNDED_SFT_TRAINING_TASKS,
            *OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS,
            *OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS,
        )
    )
    if set(bindings) != expected_tasks:
        raise ValueError("bounded SFT task bindings changed")
    for task_id, expected_role in (
        *((task_id, "training") for task_id in OPENHANDS_BOUNDED_SFT_TRAINING_TASKS),
        *((task_id, "validation") for task_id in OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS),
        *((task_id, "heldout") for task_id in OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS),
    ):
        binding = _mapping(bindings, task_id)
        _require_equal(binding, "role", expected_role)
        for field in ("task_hash", "source_hash"):
            digest = binding.get(field)
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError(f"bounded SFT {field} is invalid for {task_id}")

    gate = _mapping(contract, "data_gate")
    frozen_gate = {
        "admission": "ordinary_verifier_passed_and_exact_64k_only",
        "target_training_trajectories": 16,
        "minimum_training_trajectories": 8,
        "minimum_distinct_training_tasks": 8,
        "minimum_validation_trajectories": 2,
        "minimum_distinct_validation_tasks": 2,
        "overlength_allowed": False,
        "truncation": "error",
        "heldout_trajectory_collection_before_training_allowed": False,
        "production_benchmark_claim_allowed": False,
    }
    if gate != frozen_gate:
        raise ValueError("bounded SFT data gate changed")
    training_profile = _mapping(contract, "training")
    if (
        training_profile.get("maximum_optimizer_steps") != 48
        or training_profile.get("epochs_over_eligible_trajectories") != 3
        or training_profile.get("optimizer_step_allowed") is not True
        or training_profile.get("production_checkpoint_allowed") is not False
    ):
        raise ValueError("bounded SFT development training boundary changed")
    scheduler = _mapping(contract, "scheduler")
    if (
        scheduler.get("policy") != "ephemeral_noninteractive_lsf_payload_v1"
        or scheduler.get("persistent_bash_allocation_allowed") is not False
        or scheduler.get("retain_gpu_allocation_after_payload") is not False
    ):
        raise ValueError("bounded SFT scheduler policy changed")
    acceptance = _mapping(contract, "acceptance")
    if acceptance != {
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "hpc_jobs_submitted": False,
        "new_hpc_jobs_submitted": False,
    }:
        raise ValueError("bounded SFT preregistration acceptance state changed")
    return contract


def validate_bounded_sft_source(
    contract: Mapping[str, Any],
    *,
    split: TaskSplitManifest,
    task_split_path: Path,
    qualification_progress_path: Path,
) -> None:
    """Bind the contract to the exact completed qualification split and files."""

    validate_bounded_sft_pilot_contract(contract)
    if split.manifest_hash != OPENHANDS_BOUNDED_SFT_PILOT_SPLIT_HASH:
        raise ValueError("bounded SFT task split manifest changed")
    if hash_bytes(_regular_bytes(task_split_path)) != OPENHANDS_BOUNDED_SFT_PILOT_SPLIT_SHA256:
        raise ValueError("bounded SFT task split file changed")
    qualification_payload = _regular_bytes(qualification_progress_path)
    if hash_bytes(qualification_payload) != OPENHANDS_BOUNDED_SFT_PILOT_QUALIFICATION_SHA256:
        raise ValueError("bounded SFT qualification progress changed")
    qualification = json.loads(qualification_payload)
    if not isinstance(qualification, dict) or qualification.get("status") != "completed":
        raise ValueError("bounded SFT qualification is not complete")
    if qualification.get("task_split_hash") != split.manifest_hash:
        raise ValueError("bounded SFT qualification references another split")

    bindings = _mapping(contract, "task_bindings")
    for role, entries in (
        ("training", split.training),
        ("validation", split.validation),
        ("heldout", split.heldout),
    ):
        expected = {
            task_id
            for task_id, raw in bindings.items()
            if _mapping(bindings, task_id).get("role") == role
        }
        actual = {entry.task_id for entry in entries}
        if actual != expected:
            raise ValueError(f"bounded SFT {role} task membership changed")
        for entry in entries:
            binding = _mapping(bindings, entry.task_id)
            if binding.get("task_hash") != entry.task_hash:
                raise ValueError(f"bounded SFT task hash changed for {entry.task_id}")
            if binding.get("source_hash") != entry.source_hash:
                raise ValueError(f"bounded SFT source hash changed for {entry.task_id}")


def evaluate_bounded_sft_data_gate(attempts: Sequence[Mapping[str, Any]]) -> BoundedSftDataGate:
    """Evaluate verifier-passed exact-data yield without admitting held-out attempts."""

    training_ids = set(OPENHANDS_BOUNDED_SFT_TRAINING_TASKS)
    validation_ids = set(OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS)
    heldout_ids = set(OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS)
    eligible_training: list[str] = []
    eligible_validation: list[str] = []
    episode_ids: set[str] = set()
    for attempt in attempts:
        episode_id = attempt.get("episode_id")
        task_id = attempt.get("task_id")
        if not isinstance(episode_id, str) or not episode_id or episode_id in episode_ids:
            raise ValueError("bounded SFT attempt episode ID is missing or duplicated")
        episode_ids.add(episode_id)
        if task_id in heldout_ids:
            raise ValueError("bounded SFT held-out task was collected before training")
        if task_id not in training_ids | validation_ids:
            raise ValueError("bounded SFT attempt uses an unscheduled task")
        eligible = (
            attempt.get("infrastructure_valid") is True
            and attempt.get("ordinary_verifier_resolved") is True
            and attempt.get("exact_64k_eligible") is True
            and attempt.get("truncation_applied") is False
        )
        if eligible and task_id in training_ids:
            eligible_training.append(str(task_id))
        if eligible and task_id in validation_ids:
            eligible_validation.append(str(task_id))

    train_count = len(eligible_training)
    train_tasks = len(set(eligible_training))
    validation_count = len(eligible_validation)
    validation_tasks = len(set(eligible_validation))
    reason: str | None = None
    if train_count < 8:
        reason = "minimum_training_trajectories_not_met"
    elif train_tasks < 8:
        reason = "minimum_distinct_training_tasks_not_met"
    elif validation_count < 2:
        reason = "minimum_validation_trajectories_not_met"
    elif validation_tasks < 2:
        reason = "minimum_distinct_validation_tasks_not_met"
    return BoundedSftDataGate(
        satisfied=reason is None,
        eligible_training_trajectories=train_count,
        distinct_training_tasks=train_tasks,
        eligible_validation_trajectories=validation_count,
        distinct_validation_tasks=validation_tasks,
        reason=reason,
    )


def _validate_schedule(
    schedule: Sequence[Mapping[str, Any]], *, role: str, allowed: Sequence[str]
) -> None:
    episode_ids = [item.get("episode_id") for item in schedule]
    if any(not isinstance(item, str) or not item for item in episode_ids):
        raise ValueError(f"bounded SFT {role} episode ID is invalid")
    if len(set(episode_ids)) != len(episode_ids):
        raise ValueError(f"bounded SFT {role} episode ID is duplicated")
    for item in schedule:
        task_id = item.get("task_id")
        sample_index = item.get("sample_index")
        seed = item.get("seed")
        if task_id not in allowed or sample_index not in (0, 1) or seed != 484 + sample_index:
            raise ValueError(f"bounded SFT {role} schedule changed")
    counts = Counter(str(item["task_id"]) for item in schedule)
    if role == "training":
        if set(counts) != set(allowed) or set(counts.values()) - {1, 2}:
            raise ValueError("bounded SFT training coverage changed")
        if sum(count == 2 for count in counts.values()) != 5:
            raise ValueError("bounded SFT training repeat count changed")
    elif any(count != 2 for count in counts.values()) or set(counts) != set(allowed):
        raise ValueError("bounded SFT validation coverage changed")


def _schedule(value: Mapping[str, Any], key: str, *, expected_count: int) -> list[dict[str, Any]]:
    raw = value.get(key)
    if not isinstance(raw, list) or len(raw) != expected_count:
        raise ValueError(f"bounded SFT {key} must contain {expected_count} episodes")
    if any(not isinstance(item, dict) for item in raw):
        raise ValueError(f"bounded SFT {key} contains a non-object")
    return [dict(item) for item in raw]


def _string_sequence(value: Mapping[str, Any], key: str) -> list[str]:
    raw = value.get(key)
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError(f"bounded SFT {key} must be a string list")
    return list(raw)


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value.get(key)
    if not isinstance(raw, dict):
        raise ValueError(f"bounded SFT {key} must be an object")
    return raw


def _require_equal(value: Mapping[str, Any], key: str, expected: object) -> None:
    if value.get(key) != expected:
        raise ValueError(f"bounded SFT {key} changed")


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError(f"unsafe bounded SFT source file: {path.name}")
    return path.read_bytes()


__all__ = [
    "OPENHANDS_BOUNDED_SFT_AGENT_VERSION_ID",
    "OPENHANDS_BOUNDED_SFT_API_KEY_ENV",
    "OPENHANDS_BOUNDED_SFT_BASE_URL_ENV",
    "OPENHANDS_BOUNDED_SFT_HELDOUT_TASKS",
    "OPENHANDS_BOUNDED_SFT_PILOT_CONTRACT_HASH",
    "OPENHANDS_BOUNDED_SFT_PILOT_FORMAT",
    "OPENHANDS_BOUNDED_SFT_OPT_IN_ENV",
    "OPENHANDS_BOUNDED_SFT_TRAINING_TASKS",
    "OPENHANDS_BOUNDED_SFT_VALIDATION_TASKS",
    "BoundedSftDataGate",
    "build_bounded_sft_agent_options",
    "build_bounded_sft_agent_version",
    "evaluate_bounded_sft_data_gate",
    "load_bounded_sft_pilot_contract",
    "validate_bounded_sft_pilot_contract",
    "validate_bounded_sft_source",
]
