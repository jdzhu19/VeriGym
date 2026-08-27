"""Frozen identities for the bounded five-task OpenHands HWE collection pilot."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.memory import build_agent_version, validate_agent_version
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest, TaskSplitManifest

from .hwe_agent import OpenHandsHweAgentAdapter
from .trajectory import validate_openhands_training_trajectory

OPENHANDS_HWE_PILOT_FORMAT = "verigym_openhands_hwe_five_task_pilot_v1"
OPENHANDS_HWE_PILOT_REPORT_FORMAT = "verigym_openhands_hwe_five_task_campaign_report_v1"
OPENHANDS_HWE_PILOT_TASKS = (
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2248",
    "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2282",
)
OPENHANDS_HWE_NEW_TASKS = tuple(
    task_id for task_id in OPENHANDS_HWE_PILOT_TASKS if not task_id.endswith("__pr-2944")
)
OPENHANDS_HWE_PREDECESSOR_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944"
OPENHANDS_HWE_MODEL = "openai/deepseek-v4-flash"
OPENHANDS_HWE_MODEL_IDENTITY = "deepseek-v4-flash"
OPENHANDS_HWE_SDK_VERSION = "1.42.1"
OPENHANDS_HWE_LITELLM_VERSION = "1.93.0"
OPENHANDS_HWE_BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"
OPENHANDS_HWE_API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"
OPENHANDS_HWE_OPT_IN_ENV = "VERIGYM_RUN_OPENHANDS_HWE_PILOT"
OPENHANDS_HWE_AGENT_VERSION_ID = "openhands-deepseek-v4-flash-hwe-five-task-pilot-v1"

_PREDECESSOR_SOURCE_COMMIT = "3e0cc0a22f7005ba8b4573b80b08b1f46971ed3f"
_PREDECESSOR_REPORT_FORMAT = "verigym_openhands_hwe_single_trajectory_qualification_v1"
_PREDECESSOR_TRAJECTORY_SHA256 = "ccc8bbf307b5cd674a39161475f428201c9bbc77ac85f5e78e948ccc25d56771"
_PREDECESSOR_TRAJECTORY_HASH = "7ed148bf5e206d214d7abfdd5612275283e1e2e0643c8b8df3d5dcd5107c7416"
_OPENHANDS_SDK_WHEEL_SHA256 = "10af3d6caf1075ecbb8520db1150c0ec0179ee352b19f0395d2273afda6004d2"
_LITELLM_WHEEL_SHA256 = "ad5f7bf4e10cefa32273f0e8092eaf6c757aeb1c6484c0c3d8908e0342bde759"


@dataclass(frozen=True)
class OpenHandsHwePredecessor:
    """Hash-bound prior verifier-passed trajectory that must not be sampled again."""

    report: dict[str, Any]
    report_hash: str
    trajectory: dict[str, Any]
    trajectory_path: Path


def validate_pilot_split(split: TaskSplitManifest) -> None:
    """Require all five pilot tasks to remain in the frozen training split."""

    training = {entry.task_id for entry in split.training}
    nontraining = {entry.task_id for entry in (*split.validation, *split.heldout)}
    if not set(OPENHANDS_HWE_PILOT_TASKS).issubset(training):
        raise ValueError("OpenHands pilot task is absent from the frozen training split")
    if set(OPENHANDS_HWE_PILOT_TASKS) & nontraining:
        raise ValueError("OpenHands pilot task leaked into validation or held-out")


def load_predecessor_qualification(root: Path) -> OpenHandsHwePredecessor:
    """Validate and load the immutable PR-2944 positive trajectory."""

    directory = _safe_directory(root, "OpenHands predecessor qualification")
    report = _json_object(directory / "qualification-report.json")
    report_hash = report.get("report_hash")
    base = {key: value for key, value in report.items() if key != "report_hash"}
    required = {
        "format_id": _PREDECESSOR_REPORT_FORMAT,
        "status": "passed",
        "source_commit": _PREDECESSOR_SOURCE_COMMIT,
        "task_id": OPENHANDS_HWE_PREDECESSOR_TASK,
        "model_transport_id": OPENHANDS_HWE_MODEL,
        "model_identity": OPENHANDS_HWE_MODEL_IDENTITY,
        "openhands_sdk_version": OPENHANDS_HWE_SDK_VERSION,
        "seed": 484,
        "max_context_tokens": 65_536,
        "max_output_tokens": 2_048,
        "truncation": "error",
        "truncation_applied": False,
        "infrastructure_valid": True,
        "ordinary_verifier_resolved": True,
        "trajectory_sft_eligible": True,
        "trajectory_file_sha256": _PREDECESSOR_TRAJECTORY_SHA256,
        "trajectory_hash": _PREDECESSOR_TRAJECTORY_HASH,
    }
    if not isinstance(report_hash, str) or content_hash(base) != report_hash:
        raise ValueError("OpenHands predecessor qualification report identity changed")
    if any(report.get(key) != expected for key, expected in required.items()):
        raise ValueError("OpenHands predecessor qualification contract changed")
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("OpenHands predecessor qualification lacks a run ID")
    trajectory_path = (
        directory / "runs" / run_id / "artifacts" / "openhands_sdk" / "training-trajectory.json"
    )
    trajectory_payload = _regular_bytes(trajectory_path, 64 * 1024 * 1024)
    if hash_bytes(trajectory_payload) != _PREDECESSOR_TRAJECTORY_SHA256:
        raise ValueError("OpenHands predecessor trajectory file identity changed")
    parsed = json.loads(trajectory_payload)
    if not isinstance(parsed, dict):
        raise ValueError("OpenHands predecessor trajectory is not an object")
    trajectory = validate_openhands_training_trajectory(parsed)
    if (
        trajectory.get("task_id") != OPENHANDS_HWE_PREDECESSOR_TASK
        or trajectory.get("transcript_hash") != _PREDECESSOR_TRAJECTORY_HASH
        or trajectory.get("verifier_resolved") is not True
        or trajectory.get("sft_eligible") is not True
    ):
        raise ValueError("OpenHands predecessor trajectory eligibility changed")
    return OpenHandsHwePredecessor(
        report=report,
        report_hash=report_hash,
        trajectory=trajectory,
        trajectory_path=trajectory_path,
    )


def build_pilot_agent_version(
    *,
    source_commit: str,
    image_locks: Mapping[str, Any],
) -> AgentVersionManifest:
    """Freeze the exact policy used by the four new OpenHands episodes."""

    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise ValueError("OpenHands pilot source commit must be a full Git SHA")
    if set(image_locks) != set(OPENHANDS_HWE_NEW_TASKS):
        raise ValueError("OpenHands pilot agent version requires exactly four image locks")
    agent = OpenHandsHweAgentAdapter()
    spec = agent.prompt_policy_spec
    assert spec is not None
    lock_receipts: dict[str, str] = {}
    image_hashes: dict[str, str] = {}
    for task_id in OPENHANDS_HWE_NEW_TASKS:
        lock = image_locks[task_id]
        if getattr(lock, "task_id", None) != task_id:
            raise ValueError("OpenHands pilot image lock task identity changed")
        lock_hash = str(getattr(lock, "lock_hash", ""))
        agent_image = str(getattr(lock, "derived_agent_image_id", ""))
        verifier_image = str(getattr(lock, "verifier_base_image_id", ""))
        if len(lock_hash) != 64 or not agent_image.startswith("sha256:"):
            raise ValueError("OpenHands pilot image lock is incomplete")
        lock_receipts[task_id] = lock_hash
        image_hashes[f"task-agent:{task_id}"] = agent_image.removeprefix("sha256:")
        image_hashes[f"task-verifier:{task_id}"] = verifier_image.removeprefix("sha256:")
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
        agent_version_id=OPENHANDS_HWE_AGENT_VERSION_ID,
        parent_version_hash=None,
        update_type="none",
        executable_in_m10b=False,
        base_agent_id=agent.descriptor.name,
        agent_descriptor_hash=content_hash(agent.descriptor),
        model_id=OPENHANDS_HWE_MODEL,
        reasoning_effort="thinking-disabled",
        auth_semantic_id="deepseek.env-bearer.v1",
        runtime_identity_hash=content_hash(
            {
                "python_executable_sha256": hash_bytes(Path(sys.executable).read_bytes()),
                "openhands_sdk_version": OPENHANDS_HWE_SDK_VERSION,
                "litellm_version": OPENHANDS_HWE_LITELLM_VERSION,
                "collection_profile_id": "hwe_standard_v2",
                "tool_contract_id": "hwe_native_shell_v2",
                "task_image_lock_hashes": lock_receipts,
                "agent_runtime_network": "none",
            }
        ),
        tool_policy_hash=content_hash(deepseek_harness_tool_definitions()),
        prompt_contract_hash=prompt_contract_hash,
        source_commit=source_commit,
        package_hashes={
            "litellm-1.93.0-wheel": _LITELLM_WHEEL_SHA256,
            "openhands-sdk-1.42.1-wheel": _OPENHANDS_SDK_WHEEL_SHA256,
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


def seal_campaign_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return an immutable content-addressed campaign report."""

    base = {key: item for key, item in value.items() if key != "report_hash"}
    return {**base, "report_hash": content_hash(base)}


def _safe_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved


def _regular_bytes(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError(f"unsafe OpenHands pilot input: {path.name}")
    return path.read_bytes()


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(_regular_bytes(path, 64 * 1024 * 1024))
    if not isinstance(value, dict):
        raise ValueError(f"OpenHands pilot JSON is not an object: {path.name}")
    return value


__all__ = [
    "OPENHANDS_HWE_AGENT_VERSION_ID",
    "OPENHANDS_HWE_API_KEY_ENV",
    "OPENHANDS_HWE_BASE_URL_ENV",
    "OPENHANDS_HWE_MODEL",
    "OPENHANDS_HWE_MODEL_IDENTITY",
    "OPENHANDS_HWE_NEW_TASKS",
    "OPENHANDS_HWE_OPT_IN_ENV",
    "OPENHANDS_HWE_PILOT_FORMAT",
    "OPENHANDS_HWE_PILOT_REPORT_FORMAT",
    "OPENHANDS_HWE_PILOT_TASKS",
    "OPENHANDS_HWE_PREDECESSOR_TASK",
    "OPENHANDS_HWE_SDK_VERSION",
    "OpenHandsHwePredecessor",
    "build_pilot_agent_version",
    "load_predecessor_qualification",
    "seal_campaign_report",
    "validate_pilot_split",
]
