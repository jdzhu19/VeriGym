"""Frozen two-task canary for the repaired provider-path validator."""

from __future__ import annotations

import copy
import json
import sys
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
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.options import validate_plugin_options

from . import hwe_v17_canary_v3 as _v3
from . import hwe_v17_canary_v4 as _v4
from ._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
    OPENHANDS_PATH_POLICY_RECOVERY_BUDGET,
    OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_PATH_POLICY_RECOVERY_POLICY,
    OPENHANDS_SDK_STOP_CONTINUATION_BUDGET,
    OPENHANDS_SDK_STOP_CONTINUATION_POLICY,
)
from .hwe_agent import OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY, OpenHandsHweAgentAdapter

OPENHANDS_V18_REPAIR_CANARY_FORMAT = "verigym_openhands_hwe_v18_repair_canary_v1"
OPENHANDS_V18_REPAIR_CANARY_REPORT_FORMAT = "verigym_openhands_hwe_v18_repair_canary_report_v1"
OPENHANDS_V18_REPAIR_CANARY_GATE_FORMAT = "verigym_openhands_hwe_v18_repair_canary_gate_v1"
OPENHANDS_V18_REPAIR_CANARY_IMAGE_LOCK_RECEIPT_FORMAT = (
    "verigym_openhands_hwe_v18_repair_canary_image_locks_v1"
)
OPENHANDS_V18_REPAIR_CANARY_CAMPAIGN_ID = "openhands-hwe-v18-repair-canary-v1"
OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID = (
    "openhands-deepseek-v4-flash-hwe-v18-repair-canary-v1"
)
OPENHANDS_V18_REPAIR_CANARY_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V18_REPAIR_CANARY_V1"
OPENHANDS_V18_REPAIR_CANARY_CONTRACT_FILE = "qwen35_hwe_openhands_v18_repair_canary_v1.json"
OPENHANDS_V18_REPAIR_CANARY_SECURITY_REPORT_PREFIX = "openhands-hwe-v18-repair-canary-v1"
OPENHANDS_V18_REPAIR_CANARY_PREFLIGHT_PREFIX = "openhands-v18-repair-canary-v1-preflight"

OPENHANDS_V18_REPAIR_CANARY_BASE_URL_ENV = _v4.OPENHANDS_V17_CANARY_BASE_URL_ENV
OPENHANDS_V18_REPAIR_CANARY_API_KEY_ENV = _v4.OPENHANDS_V17_CANARY_API_KEY_ENV
OPENHANDS_V18_REPAIR_CANARY_MODEL = _v4.OPENHANDS_V17_CANARY_MODEL
OPENHANDS_V18_REPAIR_CANARY_MODEL_IDENTITY = _v4.OPENHANDS_V17_CANARY_MODEL_IDENTITY
OPENHANDS_V18_REPAIR_CANARY_SDK_VERSION = _v4.OPENHANDS_V17_CANARY_SDK_VERSION
OPENHANDS_V18_REPAIR_CANARY_LITELLM_VERSION = _v4.OPENHANDS_V17_CANARY_LITELLM_VERSION
OPENHANDS_V18_REPAIR_CANARY_TIKTOKEN_VERSION = _v4.OPENHANDS_V17_CANARY_TIKTOKEN_VERSION
OPENHANDS_V18_REPAIR_CANARY_TOOL_CHOICE_POLICY = _v4.OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY
OPENHANDS_V18_REPAIR_CANARY_MAX_ITERATIONS = _v4.OPENHANDS_V17_CANARY_MAX_ITERATIONS
OPENHANDS_V18_REPAIR_CANARY_MAX_OUTPUT_TOKENS = _v4.OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS
OPENHANDS_V18_REPAIR_CANARY_MAX_CONTEXT_TOKENS = _v4.OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS
OPENHANDS_V18_REPAIR_CANARY_PROVIDER_ARGUMENT_VALIDATOR = (
    "decoded_json_string_leaf_host_path_validator_v1"
)
OPENHANDS_V18_REPAIR_CANARY_SEED = 488
OPENHANDS_V18_REPAIR_CANARY_SAMPLE_INDEX = 4

OPENHANDS_V18_REPAIR_CANARY_PR2469 = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2469"
OPENHANDS_V18_REPAIR_CANARY_PR3204 = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
OPENHANDS_V18_REPAIR_CANARY_PR3168 = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3168"
OPENHANDS_V18_REPAIR_CANARY_SCHEDULE = (
    ("training", OPENHANDS_V18_REPAIR_CANARY_PR2469),
    ("validation", OPENHANDS_V18_REPAIR_CANARY_PR3204),
)
OPENHANDS_V18_REPAIR_CANARY_TASKS = tuple(
    task_id for _role, task_id in OPENHANDS_V18_REPAIR_CANARY_SCHEDULE
)

OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2248",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2282",
)
OPENHANDS_V18_REPAIR_EXCLUDED_ATTEMPTS = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2468",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3191",
)
OPENHANDS_V18_REPAIR_REMAINING_TRAINING_ORDER = tuple(
    f"hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-{suffix}"
    for suffix in ("2549", "2589", "2802", "2916")
)
OPENHANDS_V18_REPAIR_REMAINING_VALIDATION_ORDER = (OPENHANDS_V18_REPAIR_CANARY_PR3168,)
OPENHANDS_V18_REPAIR_TRAINING_TARGET = 8
OPENHANDS_V18_REPAIR_VALIDATION_TARGET = 2

_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"

_BINDINGS: dict[str, dict[str, str]] = {
    OPENHANDS_V18_REPAIR_CANARY_PR2469: {
        "role": "training",
        "task_hash": "2c90d93d3516bc8308b045de42cc177ec6820e98953f4a28e502a96bbc97f56e",
        "source_hash": "faf37d7a51fc87cf706afe6609e6bfd21cc63a90128be154b08a51c380784f00",
        "image_lock_hash": "a237392f6dacf52f89b5b446d7455e3aa9f627fad149f84212fd2124da51f0db",
        "agent_image": "sha256:30eb9e93a79ad33b15ac0b5573d33700ebe29ede93938b25ebb66b0680d6268c",
        "verifier_image": "sha256:42d986a58b6c12855c04d83ed0feef7a3a4506d0cc83dfa7cd98049cb31fc7e0",
    },
    OPENHANDS_V18_REPAIR_CANARY_PR3204: {
        "role": "validation",
        "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
        "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
        "image_lock_hash": "b3fe6732fe4d9b52a6444cda90b25add311665af537acf6b389ad1fdafa1933b",
        "agent_image": "sha256:2713ee1efe1d83a655b5dbee775b8c59b3af3614b4233346b779df3a63f5e276",
        "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
    },
}

_PRIOR_PASS_EVIDENCE = {
    OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES[0]: {
        "episode_id": "training-pr2944-s486",
        "trajectory_file_sha256": (
            "c1ed33da089ab637fb36e8278bfa4952b8a7ea01da66e6daa5ef90759d6a4371"
        ),
    },
    OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES[1]: {
        "episode_id": "training-pr2248-s486",
        "trajectory_file_sha256": (
            "b39478423ea72f38c18abfc8b29affe1bca8ce17f40190675756a2921c19a9dc"
        ),
    },
    OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES[2]: {
        "episode_id": "training-pr2282-s487",
        "trajectory_file_sha256": (
            "2b1322e65a137635ccf0931808ab1e33c8a273bf1039d28657e0b3526ce2ad8f"
        ),
    },
}


@dataclass(frozen=True)
class V18RepairCanaryGate:
    """Result of the repaired-validator canary and exact remaining-capacity gate."""

    canary_passed: bool
    formal_collection_allowed: bool
    pr2469_passed: bool
    pr3204_passed: bool
    training_capacity_sufficient: bool
    validation_capacity_sufficient: bool
    prior_training_pass_count: int
    maximum_training_pass_count: int
    maximum_validation_pass_count: int
    reason: str | None


def expected_v18_repair_canary_contract() -> dict[str, Any]:
    """Return the complete repaired-validator canary contract."""

    parent = _v4.expected_v17_canary_contract()
    teacher = copy.deepcopy(parent["teacher"])
    teacher.update(
        {
            "scaffold": "openhands-sdk-1.42.1-verigym-broker-v2-v18-path-validator-fixed-v1",
            "provider_argument_validator_policy_id": (
                OPENHANDS_V18_REPAIR_CANARY_PROVIDER_ARGUMENT_VALIDATOR
            ),
        }
    )
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V18_REPAIR_CANARY_FORMAT,
        "scope": "two_task_repaired_validator_capacity_canary",
        "source": copy.deepcopy(parent["source"]),
        "teacher": teacher,
        "task_bindings": copy.deepcopy(_BINDINGS),
        "schedule": [
            {
                "episode_id": f"{role}-pr{task_id.rsplit('-', 1)[-1]}-s488",
                "role": role,
                "task_id": task_id,
                "seed": OPENHANDS_V18_REPAIR_CANARY_SEED,
                "sample_index": OPENHANDS_V18_REPAIR_CANARY_SAMPLE_INDEX,
            }
            for role, task_id in OPENHANDS_V18_REPAIR_CANARY_SCHEDULE
        ],
        "prior_pass_evidence": copy.deepcopy(_PRIOR_PASS_EVIDENCE),
        "gate": {
            "all_scheduled_tasks_require_verifier_pass": True,
            "all_verifier_passes_require_fresh_exact_trajectory": True,
            "downstream_capacity_required_for_formal_collection": True,
            "zero_failure_slack": True,
            "infrastructure_or_security_failure_policy": "stop_immediately",
            "allowed_recovery_counter_states": [[0, 0, 0], [1, 1, 1]],
            "format_recovery_requires_sdk_continuation_unless_path_feedback_resumed": True,
            "allowed_combined_recovery_paths": list(
                parent["gate"]["allowed_combined_recovery_paths"]
            ),
            "allowed_path_policy_recovery_counter_states": [[0, 0, 0], [1, 1, 1]],
            "path_policy_recovery_policy_id": OPENHANDS_PATH_POLICY_RECOVERY_POLICY,
            "path_policy_recovery_budget": OPENHANDS_PATH_POLICY_RECOVERY_BUDGET,
            "path_policy_recovery_message_sha256": OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE_SHA256,
            "path_policy_recovery_requires_same_session": True,
            "path_policy_recovery_requires_one_canonical_tool": True,
            "bounded_iteration_limit_is_model_nonfinish": True,
            "raw_rejected_provider_arguments_persisted": False,
            "truncation_allowed": False,
        },
        "formal_collection_capacity": {
            "training_target_distinct_tasks": OPENHANDS_V18_REPAIR_TRAINING_TARGET,
            "validation_target_distinct_tasks": OPENHANDS_V18_REPAIR_VALIDATION_TARGET,
            "prior_successful_training_task_ids": list(OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES),
            "attempted_task_ids_excluded_from_reexecution": list(
                OPENHANDS_V18_REPAIR_EXCLUDED_ATTEMPTS
            ),
            "canary_training_task_id": OPENHANDS_V18_REPAIR_CANARY_PR2469,
            "canary_validation_task_id": OPENHANDS_V18_REPAIR_CANARY_PR3204,
            "post_canary_training_attempt_order": list(
                OPENHANDS_V18_REPAIR_REMAINING_TRAINING_ORDER
            ),
            "post_canary_validation_attempt_order": list(
                OPENHANDS_V18_REPAIR_REMAINING_VALIDATION_ORDER
            ),
            "stop_at_target": True,
            "capacity_recalculated_after_each_attempt": True,
            "task_retries": 0,
            "provider_request_retries": 0,
            "heldout_tasks_eligible": False,
        },
        "heldout_task_ids_loaded": [],
        "benchmark_score_claimed": False,
        "production_training_ready": False,
    }
    return {**base, "contract_hash": content_hash(base)}


def expected_v18_repair_canary_overlay() -> dict[str, Any]:
    """Return the compact on-disk identity for the code-frozen contract."""

    contract = expected_v18_repair_canary_contract()
    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V18_REPAIR_CANARY_FORMAT,
        "scope": contract["scope"],
        "contract_hash": contract["contract_hash"],
    }
    return {**base, "overlay_hash": content_hash(base)}


def load_v18_repair_canary_contract(path: Path) -> dict[str, Any]:
    """Load only the exact compact v18 repaired-validator canary identity."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 256 * 1024:
        raise ValueError("OpenHands v18 repair canary contract must be a small regular file")
    parsed = json.loads(path.read_bytes())
    if not isinstance(parsed, dict) or parsed != expected_v18_repair_canary_overlay():
        raise ValueError("OpenHands v18 repair canary contract identity changed")
    return expected_v18_repair_canary_contract()


def derive_v18_repair_task_split(split: TaskSplitManifest) -> TaskSplitManifest:
    """Use the frozen public v17 role overlay without loading held-out assets."""

    return _v3.derive_v17_v3_task_split(split)


def validate_v18_repair_canary_source(
    contract: Mapping[str, Any],
    *,
    split: TaskSplitManifest,
    task_split_path: Path,
    qualification_progress_path: Path,
) -> None:
    """Validate source evidence and the two new task/source/role bindings."""

    if dict(contract) != expected_v18_repair_canary_contract():
        raise ValueError("OpenHands v18 repair canary contract identity changed")
    _v3.validate_v17_canary_source(
        _v3.expected_v17_canary_contract(),
        split=split,
        task_split_path=task_split_path,
        qualification_progress_path=qualification_progress_path,
    )
    derived = derive_v18_repair_task_split(split)
    entries = {entry.task_id: entry for entry in (*derived.training, *derived.validation)}
    roles = {
        entry.task_id: role
        for role, values in (("training", derived.training), ("validation", derived.validation))
        for entry in values
    }
    for task_id, binding in _BINDINGS.items():
        entry = entries.get(task_id)
        if (
            entry is None
            or entry.task_hash != binding["task_hash"]
            or entry.source_hash != binding["source_hash"]
            or roles.get(task_id) != binding["role"]
        ):
            raise ValueError("OpenHands v18 repair canary task/source/role binding changed")


def build_v18_repair_canary_agent_version(
    *, source_commit: str, image_locks: Mapping[str, Any]
) -> AgentVersionManifest:
    """Freeze a distinct source-, validator-, task-, and image-bound canary identity."""

    if len(source_commit) != 40 or any(char not in "0123456789abcdef" for char in source_commit):
        raise ValueError("OpenHands v18 repair canary requires a full Git SHA")
    if set(image_locks) != set(OPENHANDS_V18_REPAIR_CANARY_TASKS):
        raise ValueError("OpenHands v18 repair canary requires exactly two image locks")
    image_hashes: dict[str, str] = {}
    lock_receipts: dict[str, str] = {}
    for task_id in OPENHANDS_V18_REPAIR_CANARY_TASKS:
        lock = image_locks[task_id]
        binding = _BINDINGS[task_id]
        if (
            getattr(lock, "task_id", None) != task_id
            or getattr(lock, "task_hash", None) != binding["task_hash"]
            or getattr(lock, "source_hash", None) != binding["source_hash"]
            or getattr(lock, "lock_hash", None) != binding["image_lock_hash"]
            or getattr(lock, "derived_agent_image_id", None) != binding["agent_image"]
            or getattr(lock, "verifier_base_image_id", None) != binding["verifier_image"]
        ):
            raise ValueError("OpenHands v18 repair canary image-lock binding changed")
        suffix = task_id.rsplit("-", 1)[-1]
        lock_receipts[task_id] = binding["image_lock_hash"]
        image_hashes[f"pr{suffix}-agent"] = binding["agent_image"].removeprefix("sha256:")
        image_hashes[f"pr{suffix}-verifier"] = binding["verifier_image"].removeprefix("sha256:")

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
        agent_version_id=OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID,
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=False,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id=OPENHANDS_V18_REPAIR_CANARY_MODEL,
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash=content_hash(
            {
                "python_executable_sha256": hash_bytes(Path(sys.executable).read_bytes()),
                "openhands_sdk_version": OPENHANDS_V18_REPAIR_CANARY_SDK_VERSION,
                "litellm_version": OPENHANDS_V18_REPAIR_CANARY_LITELLM_VERSION,
                "tiktoken_version": OPENHANDS_V18_REPAIR_CANARY_TIKTOKEN_VERSION,
                "canary_contract_hash": expected_v18_repair_canary_contract()["contract_hash"],
                "collection_profile_id": "hwe_production_native_shell_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "tool_choice_policy": OPENHANDS_V18_REPAIR_CANARY_TOOL_CHOICE_POLICY,
                "provider_tool_schema_policy": (
                    "canonical_hwe_without_sdk_metadata_workspace_relative_path_recovery_v4"
                ),
                "provider_argument_validator_policy_id": (
                    OPENHANDS_V18_REPAIR_CANARY_PROVIDER_ARGUMENT_VALIDATOR
                ),
                "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
                "sdk_stop_continuation_policy": OPENHANDS_SDK_STOP_CONTINUATION_POLICY,
                "sdk_stop_continuation_budget": OPENHANDS_SDK_STOP_CONTINUATION_BUDGET,
                "path_policy_recovery_policy_id": OPENHANDS_PATH_POLICY_RECOVERY_POLICY,
                "path_policy_recovery_budget": OPENHANDS_PATH_POLICY_RECOVERY_BUDGET,
                "path_policy_recovery_message_sha256": (
                    OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE_SHA256
                ),
                "bounded_iteration_termination_policy_id": (
                    OPENHANDS_BOUNDED_ITERATION_TERMINATION_POLICY
                ),
                "provider_call_accounting": "conversation_agent_attempt_counter_v2",
                "task_image_lock_hashes": lock_receipts,
                "seed": OPENHANDS_V18_REPAIR_CANARY_SEED,
                "sample_index": OPENHANDS_V18_REPAIR_CANARY_SAMPLE_INDEX,
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


def build_v18_repair_canary_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build the exact repaired-validator canary options with no retries."""

    version = validate_agent_version(agent_version)
    if (
        seed != OPENHANDS_V18_REPAIR_CANARY_SEED
        or version.agent_version_id != OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V18_REPAIR_CANARY_MODEL
    ):
        raise ValueError("OpenHands v18 repair canary options require the frozen identity")
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V18_REPAIR_CANARY_MODEL,
            "base_url_env": OPENHANDS_V18_REPAIR_CANARY_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V18_REPAIR_CANARY_API_KEY_ENV,
            "max_iterations": OPENHANDS_V18_REPAIR_CANARY_MAX_ITERATIONS,
            "max_process_time_s": 3_600,
            "max_output_tokens": OPENHANDS_V18_REPAIR_CANARY_MAX_OUTPUT_TOKENS,
            "max_context_tokens": OPENHANDS_V18_REPAIR_CANARY_MAX_CONTEXT_TOKENS,
            "seed": seed,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "expected_sdk_version": OPENHANDS_V18_REPAIR_CANARY_SDK_VERSION,
            "campaign_role": "training",
            "capture_training_transcript": True,
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": json.dumps(
                version.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ),
            "collection_profile_id": "hwe_production_native_shell_v2",
            "tool_choice_policy": OPENHANDS_V18_REPAIR_CANARY_TOOL_CHOICE_POLICY,
        }
    )


def validate_v18_repair_runtime_evidence(
    broker: Mapping[str, Any],
    summary: Mapping[str, Any],
    accounting: ExternalAgentAccounting,
    *,
    verifier_resolved: bool,
) -> str:
    """Apply the frozen v4 accounting and bounded-nonfinish validator."""

    return _v4.validate_v17_runtime_evidence(
        broker,
        summary,
        accounting,
        verifier_resolved=verifier_resolved,
    )


def evaluate_v18_repair_canary_gate(
    attempts: Sequence[Mapping[str, Any]],
) -> V18RepairCanaryGate:
    """Require both zero-slack canary tasks to yield exact verifier-pass trajectories."""

    if [attempt.get("task_id") for attempt in attempts] != list(OPENHANDS_V18_REPAIR_CANARY_TASKS):
        raise ValueError("OpenHands v18 repair canary attempts are incomplete or out of order")
    required = (
        "infrastructure_valid",
        "runtime_evidence_valid",
        "security_scan_passed",
        "truncation_applied",
        "recovery_accounting_valid",
    )
    for attempt in attempts:
        if any(key not in attempt for key in required):
            raise ValueError("OpenHands v18 repair canary attempt evidence is incomplete")
        if (
            attempt["infrastructure_valid"] is not True
            or attempt["runtime_evidence_valid"] is not True
            or attempt["security_scan_passed"] is not True
            or attempt["truncation_applied"] is not False
            or attempt["recovery_accounting_valid"] is not True
        ):
            return V18RepairCanaryGate(
                canary_passed=False,
                formal_collection_allowed=False,
                pr2469_passed=False,
                pr3204_passed=False,
                training_capacity_sufficient=False,
                validation_capacity_sufficient=False,
                prior_training_pass_count=len(OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES),
                maximum_training_pass_count=0,
                maximum_validation_pass_count=0,
                reason="invalid_attempt_evidence",
            )
    by_task = {str(attempt["task_id"]): attempt for attempt in attempts}

    def passed(task_id: str) -> bool:
        attempt = by_task[task_id]
        return (
            attempt.get("ordinary_verifier_resolved") is True
            and attempt.get("fresh_exact_trajectory") is True
        )

    pr2469 = passed(OPENHANDS_V18_REPAIR_CANARY_PR2469)
    pr3204 = passed(OPENHANDS_V18_REPAIR_CANARY_PR3204)
    maximum_training = (
        len(OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES)
        + int(pr2469)
        + len(OPENHANDS_V18_REPAIR_REMAINING_TRAINING_ORDER)
    )
    maximum_validation = int(pr3204) + len(OPENHANDS_V18_REPAIR_REMAINING_VALIDATION_ORDER)
    training_capacity = maximum_training >= OPENHANDS_V18_REPAIR_TRAINING_TARGET
    validation_capacity = maximum_validation >= OPENHANDS_V18_REPAIR_VALIDATION_TARGET
    canary_passed = pr2469 and pr3204
    if not pr2469:
        reason = "pr2469_required_pass_missing"
    elif not pr3204:
        reason = "pr3204_required_pass_missing"
    elif not training_capacity:
        reason = "training_capacity_exhausted"
    elif not validation_capacity:
        reason = "validation_capacity_exhausted"
    else:
        reason = None
    return V18RepairCanaryGate(
        canary_passed=canary_passed,
        formal_collection_allowed=canary_passed and training_capacity and validation_capacity,
        pr2469_passed=pr2469,
        pr3204_passed=pr3204,
        training_capacity_sufficient=training_capacity,
        validation_capacity_sufficient=validation_capacity,
        prior_training_pass_count=len(OPENHANDS_V18_REPAIR_PRIOR_TRAINING_PASSES),
        maximum_training_pass_count=maximum_training,
        maximum_validation_pass_count=maximum_validation,
        reason=reason,
    )


def seal_v18_repair_canary_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal one sanitized v18 canary report or progress record."""

    base = {key: item for key, item in value.items() if key != "report_hash"}
    return {**base, "report_hash": content_hash(base)}


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V18_REPAIR_")] + [
    "V18RepairCanaryGate",
    "build_v18_repair_canary_agent_options",
    "build_v18_repair_canary_agent_version",
    "derive_v18_repair_task_split",
    "evaluate_v18_repair_canary_gate",
    "expected_v18_repair_canary_contract",
    "expected_v18_repair_canary_overlay",
    "load_v18_repair_canary_contract",
    "seal_v18_repair_canary_report",
    "validate_v18_repair_canary_source",
    "validate_v18_repair_runtime_evidence",
]
