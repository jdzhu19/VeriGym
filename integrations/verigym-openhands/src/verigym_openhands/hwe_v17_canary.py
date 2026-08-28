"""Frozen three-task canary contract for the OpenHands v17 collection policy."""

from __future__ import annotations

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
from verigym.schemas.options import validate_plugin_options

from ._recovery import OPENHANDS_FORMAT_RECOVERY_BUDGET, OPENHANDS_FORMAT_RECOVERY_POLICY
from .hwe_agent import OpenHandsHweAgentAdapter

OPENHANDS_V17_CANARY_FORMAT = "verigym_openhands_hwe_v17_collection_canary_v1"
OPENHANDS_V17_CANARY_REPORT_FORMAT = "verigym_openhands_hwe_v17_collection_canary_report_v1"
OPENHANDS_V17_CANARY_GATE_FORMAT = "verigym_openhands_hwe_v17_collection_canary_gate_v1"
OPENHANDS_V17_CANARY_CAMPAIGN_ID = "openhands-hwe-v17-collection-canary-v1"
OPENHANDS_V17_CANARY_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-v17-collection-canary-v1"
OPENHANDS_V17_CANARY_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_V17_COLLECTION_CANARY_V1"
OPENHANDS_V17_CANARY_BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"
OPENHANDS_V17_CANARY_API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"
OPENHANDS_V17_CANARY_MODEL = "openai/deepseek-v4-flash"
OPENHANDS_V17_CANARY_MODEL_IDENTITY = "deepseek-v4-flash"
OPENHANDS_V17_CANARY_SDK_VERSION = "1.42.1"
OPENHANDS_V17_CANARY_LITELLM_VERSION = "1.93.0"
OPENHANDS_V17_CANARY_TIKTOKEN_VERSION = "0.7.0"
OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY = "validated_responses_recovery_state_required_tool_v17"
OPENHANDS_V17_CANARY_CONTRACT_FILE = "qwen35_hwe_openhands_v17_canary_v1.json"
OPENHANDS_V17_CANARY_SEED = 486
OPENHANDS_V17_CANARY_SAMPLE_INDEX = 2
OPENHANDS_V17_CANARY_MAX_ITERATIONS = 200
OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS = 2_048
OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS = 65_536

OPENHANDS_V17_CANARY_PR2944 = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"
OPENHANDS_V17_CANARY_PR2248 = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2248"
OPENHANDS_V17_CANARY_PR3191 = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3191"
OPENHANDS_V17_CANARY_SCHEDULE = (
    ("training", OPENHANDS_V17_CANARY_PR2944),
    ("training", OPENHANDS_V17_CANARY_PR2248),
    ("validation", OPENHANDS_V17_CANARY_PR3191),
)
OPENHANDS_V17_CANARY_TASKS = tuple(task_id for _role, task_id in OPENHANDS_V17_CANARY_SCHEDULE)

_TASK_SPLIT_HASH = "68c76482f81ac4bbbb64a54d0886fda4b1a0b7c38e489916b919f768ec3146e6"
_TASK_SPLIT_SHA256 = "844bf3f65d648f1e8542b80e55d16d6612b614df5283b350123b33c79b2c13bc"
_QUALIFICATION_SHA256 = "27980ef9b0537c1a1873ea9ad7894c6e0edd3564b5ac503209703322ab8042a3"
_BASELINE_COMMIT = "0ad17bd8259141e63efdfd7914407ed821993b60"
_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"
_TIKTOKEN_WHEEL_SHA256 = "d20b5c6af30e621b4aca094ee61777a44118f52d886dbe4f02b70dfe05c15350"

_BINDINGS: dict[str, dict[str, str]] = {
    OPENHANDS_V17_CANARY_PR2944: {
        "role": "training",
        "task_hash": "ec7f79b3bb830aa0390b3be14635808455cef1c5786f93a676d2d0c5b9ae5277",
        "source_hash": "86228bcc27147400105b29069ee34a2b428cf897be700d77e3ed019760dd1e4f",
        "image_lock_hash": "99cb8d40807c62fdfb0c48f9b1e98bdbfc2a55e73223367c3f81337eea39de0c",
        "agent_image": "sha256:d20ffcf6ba42570d225ec9fe0757f501f654c222250c83e3fd83ab70918834e3",
        "verifier_image": "sha256:91a135852c3ab371c24e2f49fad382568ffb830167d3c26006c26f88fe190b6a",
    },
    OPENHANDS_V17_CANARY_PR2248: {
        "role": "training",
        "task_hash": "164f4bf0ce995f99910369894329e7ff068d4c2a4de431e477a288a8785fee36",
        "source_hash": "8c416582b8d0b7e33ff00d343c7e35ea7a20b9a82a86dc0964f0ffa184e40296",
        "image_lock_hash": "f6f6039a460ccfa6d8e8a3d8ad1ec17e3bfd7eb2fe236002fc84659fa716178e",
        "agent_image": "sha256:d857a665e0f162bae2a4739070b615eea1c9449cdba4d868cbb8f60ab8682d88",
        "verifier_image": "sha256:f7c2d797a9786815d65d328f05fcd4565c922f4a53da53fa121475b3c44df91b",
    },
    OPENHANDS_V17_CANARY_PR3191: {
        "role": "validation",
        "task_hash": "ac576e92711851e49a69039c5270f52f23cfad559bc48f431070e2a7e0d58159",
        "source_hash": "c8533c84cb6aaa6641e42127971b5524c17a579cd1a614aee47074c2d389c3b8",
        "image_lock_hash": "ccc44dda92dfe3c3ab32107365f331d9e667b0fc4fdb9e03e00ceab531816299",
        "agent_image": "sha256:8147c9ed502eb9c0c3806262b17eba1a599b9b73dc7a9ea964af7c95acf18b3c",
        "verifier_image": "sha256:d00d4fa72c0c63cd200391ee8f012fa3190f347e6681ab0b53af53b91e5f8f98",
    },
}


@dataclass(frozen=True)
class V17CanaryGate:
    """Outcome of the three-task canary and downstream-capacity gate."""

    canary_passed: bool
    formal_collection_allowed: bool
    pr2944_passed: bool
    secondary_pass_count: int
    pr3191_passed: bool
    reason: str | None


def expected_v17_canary_contract() -> dict[str, Any]:
    """Return the complete byte-content-independent canary contract."""

    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V17_CANARY_FORMAT,
        "scope": "three_task_precollection_canary",
        "source": {
            "repository": "jdzhu19/VeriGym",
            "baseline_commit": _BASELINE_COMMIT,
            "task_split_manifest_hash": _TASK_SPLIT_HASH,
            "task_split_file_sha256": _TASK_SPLIT_SHA256,
            "qualification_progress_file_sha256": _QUALIFICATION_SHA256,
            "qualification_status": "completed",
        },
        "teacher": {
            "scaffold": "openhands-sdk-1.42.1-verigym-broker-v2-v17",
            "model_transport_id": OPENHANDS_V17_CANARY_MODEL,
            "model_identity": OPENHANDS_V17_CANARY_MODEL_IDENTITY,
            "reasoning": "thinking-disabled",
            "openhands_sdk_version": OPENHANDS_V17_CANARY_SDK_VERSION,
            "litellm_version": OPENHANDS_V17_CANARY_LITELLM_VERSION,
            "tiktoken_version": OPENHANDS_V17_CANARY_TIKTOKEN_VERSION,
            "tool_contract": "hwe_native_shell_v2",
            "tool_schema_count": 6,
            "tool_choice_policy": OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY,
            "provider_tool_schema_policy": (
                "canonical_hwe_without_sdk_metadata_all_string_host_path_constraints_v3"
            ),
            "temperature": 0,
            "top_p": 1,
            "max_context_tokens": OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS,
            "max_output_tokens": OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS,
            "max_iterations": OPENHANDS_V17_CANARY_MAX_ITERATIONS,
            "whole_episode_retries": 0,
            "provider_request_retries": 0,
            "capture_training_transcript": True,
            "sandbox_network": "none",
        },
        "task_bindings": _BINDINGS,
        "schedule": [
            {
                "episode_id": f"{role}-pr{task_id.rsplit('-', 1)[-1]}-s486",
                "role": role,
                "task_id": task_id,
                "seed": OPENHANDS_V17_CANARY_SEED,
                "sample_index": OPENHANDS_V17_CANARY_SAMPLE_INDEX,
            }
            for role, task_id in OPENHANDS_V17_CANARY_SCHEDULE
        ],
        "gate": {
            "pr2944_requires_verifier_pass": True,
            "pr2944_requires_fresh_exact_trajectory": True,
            "secondary_pass_minimum": 1,
            "pr3191_required_for_formal_collection": True,
            "infrastructure_or_security_failure_policy": "stop_immediately",
            "allowed_recovery_counter_states": [[0, 0, 0], [1, 1, 1]],
            "recovered_state_requires_sdk_continuation": [1, 1, 1],
            "truncation_allowed": False,
        },
        "heldout_task_ids_loaded": [],
        "benchmark_score_claimed": False,
        "production_training_ready": False,
    }
    return {**base, "contract_hash": content_hash(base)}


def load_v17_canary_contract(path: Path) -> dict[str, Any]:
    """Load only the exact three-task canary contract."""

    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 256 * 1024:
        raise ValueError("OpenHands v17 canary contract must be a small regular file")
    parsed = json.loads(path.read_bytes())
    if not isinstance(parsed, dict) or parsed != expected_v17_canary_contract():
        raise ValueError("OpenHands v17 canary contract identity changed")
    return parsed


def validate_v17_canary_source(
    contract: Mapping[str, Any],
    *,
    split: TaskSplitManifest,
    task_split_path: Path,
    qualification_progress_path: Path,
) -> None:
    """Bind the canary to the frozen public split without loading held-out assets."""

    if dict(contract) != expected_v17_canary_contract():
        raise ValueError("OpenHands v17 canary contract identity changed")
    if (
        split.manifest_hash != _TASK_SPLIT_HASH
        or hash_bytes(_regular_bytes(task_split_path)) != _TASK_SPLIT_SHA256
        or hash_bytes(_regular_bytes(qualification_progress_path)) != _QUALIFICATION_SHA256
    ):
        raise ValueError("OpenHands v17 canary source evidence changed")
    split_roles = {
        entry.task_id: role
        for role, entries in (("training", split.training), ("validation", split.validation))
        for entry in entries
        if entry.task_id in OPENHANDS_V17_CANARY_TASKS
    }
    if split_roles != {task_id: role for role, task_id in OPENHANDS_V17_CANARY_SCHEDULE}:
        raise ValueError("OpenHands v17 canary task roles changed")
    entries = {entry.task_id: entry for entry in (*split.training, *split.validation)}
    for task_id, binding in _BINDINGS.items():
        entry = entries.get(task_id)
        if (
            entry is None
            or entry.task_hash != binding["task_hash"]
            or entry.source_hash != binding["source_hash"]
        ):
            raise ValueError("OpenHands v17 canary task/source binding changed")


def build_v17_canary_agent_version(
    *, source_commit: str, image_locks: Mapping[str, Any]
) -> AgentVersionManifest:
    """Freeze one new non-diagnostic v17 identity over exactly three task images."""

    if len(source_commit) != 40 or any(char not in "0123456789abcdef" for char in source_commit):
        raise ValueError("OpenHands v17 canary requires a full Git SHA")
    if set(image_locks) != set(OPENHANDS_V17_CANARY_TASKS):
        raise ValueError("OpenHands v17 canary requires exactly three image locks")
    image_hashes: dict[str, str] = {}
    lock_receipts: dict[str, str] = {}
    for task_id in OPENHANDS_V17_CANARY_TASKS:
        lock = image_locks[task_id]
        binding = _BINDINGS[task_id]
        if (
            getattr(lock, "task_id", None) != task_id
            or getattr(lock, "task_hash", binding["task_hash"]) != binding["task_hash"]
            or getattr(lock, "source_hash", binding["source_hash"]) != binding["source_hash"]
            or getattr(lock, "lock_hash", None) != binding["image_lock_hash"]
            or getattr(lock, "derived_agent_image_id", None) != binding["agent_image"]
            or getattr(lock, "verifier_base_image_id", None) != binding["verifier_image"]
        ):
            raise ValueError("OpenHands v17 canary image-lock binding changed")
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
        agent_version_id=OPENHANDS_V17_CANARY_AGENT_VERSION_ID,
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=False,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id=OPENHANDS_V17_CANARY_MODEL,
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash=content_hash(
            {
                "python_executable_sha256": hash_bytes(Path(sys.executable).read_bytes()),
                "openhands_sdk_version": OPENHANDS_V17_CANARY_SDK_VERSION,
                "litellm_version": OPENHANDS_V17_CANARY_LITELLM_VERSION,
                "tiktoken_version": OPENHANDS_V17_CANARY_TIKTOKEN_VERSION,
                "canary_contract_hash": expected_v17_canary_contract()["contract_hash"],
                "collection_profile_id": "hwe_production_native_shell_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "tool_choice_policy": OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY,
                "provider_tool_schema_policy": (
                    "canonical_hwe_without_sdk_metadata_all_string_host_path_constraints_v3"
                ),
                "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
                "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
                "sdk_stop_continuation_policy": "openhands_sdk_blocked_stop_continuation_v1",
                "sdk_stop_continuation_budget": 1,
                "sdk_continuation_tool_choice_policy": "responses_required_validated_v1",
                "provider_call_accounting": "conversation_agent_attempt_counter_v2",
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


def build_v17_canary_agent_options(
    *, seed: int, agent_version: AgentVersionManifest
) -> dict[str, JsonValue]:
    """Build the exact v17 no-retry OpenHands options."""

    version = validate_agent_version(agent_version)
    if (
        version.agent_version_id != OPENHANDS_V17_CANARY_AGENT_VERSION_ID
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != OPENHANDS_V17_CANARY_MODEL
    ):
        raise ValueError("OpenHands v17 canary options require the frozen canary version")
    manifest_json = json.dumps(
        version.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return validate_plugin_options(
        {
            "model_id": OPENHANDS_V17_CANARY_MODEL,
            "base_url_env": OPENHANDS_V17_CANARY_BASE_URL_ENV,
            "api_key_env": OPENHANDS_V17_CANARY_API_KEY_ENV,
            "max_iterations": OPENHANDS_V17_CANARY_MAX_ITERATIONS,
            "max_process_time_s": 3_600,
            "max_output_tokens": OPENHANDS_V17_CANARY_MAX_OUTPUT_TOKENS,
            "max_context_tokens": OPENHANDS_V17_CANARY_MAX_CONTEXT_TOKENS,
            "seed": seed,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "expected_sdk_version": OPENHANDS_V17_CANARY_SDK_VERSION,
            "campaign_role": "training",
            "capture_training_transcript": True,
            "agent_version_id": version.agent_version_id,
            "agent_version_hash": version.version_hash,
            "agent_version_manifest_json": manifest_json,
            "collection_profile_id": "hwe_production_native_shell_v2",
            "tool_choice_policy": OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY,
        }
    )


def validate_v17_recovery_accounting(summary: Mapping[str, Any]) -> str:
    """Accept only direct execution or the exact validated v17 recovery/continuation path."""

    fields = (
        "format_recovery_count",
        "recovery_forced_request_count",
        "recovery_validated_finish_count",
        "recovery_validated_tool_count",
        "sdk_stop_continuation_count",
        "sdk_continuation_forced_request_count",
        "sdk_continuation_validated_tool_count",
    )
    values = tuple(summary.get(field) for field in fields)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("OpenHands v17 recovery accounting is incomplete")
    if values == (0, 0, 0, 0, 0, 0, 0):
        return "direct"
    if values == (1, 1, 0, 1, 1, 1, 1):
        return "validated_required_tool_continuation"
    raise ValueError("OpenHands v17 recovery accounting escaped the frozen states")


def validate_v17_canonical_tool_shape(value: Any, *, label: str) -> None:
    """Require one validated canonical HWE function call in a recovery receipt."""

    allowed_tools = {"list_files", "read_file", "search", "shell", "apply_patch", "finish"}
    if not isinstance(value, dict):
        raise ValueError(f"OpenHands v17 {label} tool receipt is malformed")
    raw_names = value.get("raw_function_names")
    converted_names = value.get("converted_tool_names")
    if (
        value.get("raw_output_count") != 1
        or value.get("raw_output_types") != ["function_call"]
        or value.get("converted_tool_call_count") != 1
        or value.get("converted_text_part_count") != 0
        or not isinstance(raw_names, list)
        or not isinstance(converted_names, list)
        or len(raw_names) != 1
        or raw_names != converted_names
        or raw_names[0] not in allowed_tools
    ):
        raise ValueError(f"OpenHands v17 {label} canonical tool receipt changed")


def evaluate_v17_canary_gate(attempts: Sequence[Mapping[str, Any]]) -> V17CanaryGate:
    """Require PR-2944, one secondary pass, and PR-3191 capacity for collection."""

    if [attempt.get("task_id") for attempt in attempts] != list(OPENHANDS_V17_CANARY_TASKS):
        raise ValueError("OpenHands v17 canary attempts are incomplete or out of order")
    required = (
        "infrastructure_valid",
        "runtime_evidence_valid",
        "security_scan_passed",
        "truncation_applied",
        "recovery_accounting_valid",
    )
    for attempt in attempts:
        if any(key not in attempt for key in required):
            raise ValueError("OpenHands v17 canary attempt evidence is incomplete")
        if (
            attempt["infrastructure_valid"] is not True
            or attempt["runtime_evidence_valid"] is not True
            or attempt["security_scan_passed"] is not True
            or attempt["truncation_applied"] is not False
            or attempt["recovery_accounting_valid"] is not True
        ):
            return V17CanaryGate(False, False, False, 0, False, "invalid_attempt_evidence")
    by_task = {str(attempt["task_id"]): attempt for attempt in attempts}
    primary = by_task[OPENHANDS_V17_CANARY_PR2944]
    pr2944 = (
        primary.get("ordinary_verifier_resolved") is True
        and primary.get("fresh_exact_trajectory") is True
    )
    secondary = sum(
        by_task[task_id].get("ordinary_verifier_resolved") is True
        for task_id in (OPENHANDS_V17_CANARY_PR2248, OPENHANDS_V17_CANARY_PR3191)
    )
    pr3191 = by_task[OPENHANDS_V17_CANARY_PR3191].get("ordinary_verifier_resolved") is True
    canary_passed = pr2944 and secondary >= 1
    if not pr2944:
        reason = "pr2944_required_pass_missing"
    elif secondary < 1:
        reason = "secondary_verifier_pass_missing"
    elif not pr3191:
        reason = "validation_capacity_exhausted"
    else:
        reason = None
    return V17CanaryGate(canary_passed, canary_passed and pr3191, pr2944, secondary, pr3191, reason)


def seal_v17_canary_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Seal a sanitized canary report or progress record."""

    base = {key: item for key, item in value.items() if key != "report_hash"}
    return {**base, "report_hash": content_hash(base)}


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024 * 1024:
        raise ValueError(f"unsafe OpenHands v17 source evidence: {path.name}")
    return path.read_bytes()


__all__ = [name for name in globals() if name.startswith("OPENHANDS_V17_CANARY_")] + [
    "V17CanaryGate",
    "build_v17_canary_agent_options",
    "build_v17_canary_agent_version",
    "evaluate_v17_canary_gate",
    "expected_v17_canary_contract",
    "load_v17_canary_contract",
    "seal_v17_canary_report",
    "validate_v17_canary_source",
    "validate_v17_canonical_tool_shape",
    "validate_v17_recovery_accounting",
]
