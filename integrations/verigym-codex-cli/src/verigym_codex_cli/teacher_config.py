"""Frozen Codex MCP-only teacher settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from verigym.core.repository_observation import resolve_repository_observation_policy
from verigym.plugin_api import JsonValue

from .capabilities import CapabilityReport
from .config import CodexSettings, readonly_agent_settings
from .util import stable_hash

_TEACHER_OPTIONS = {
    "model_id",
    "reasoning_effort",
    "max_process_time_s",
    "max_output_bytes",
    "allow_proxy_environment",
    "expected_cli_version",
    "expected_cli_executable_sha256",
    "expected_capability_fingerprint",
    "expected_requested_auth_mode",
    "expected_resolved_auth_mode",
    "expected_auth_semantic_id",
    "capture_training_transcript",
    "campaign_role",
    "max_tool_calls",
    "max_patch_calls",
    "max_consecutive_rejected_calls",
    "observation_policy_id",
    "observation_policy",
    "transcript_format",
}


@dataclass(frozen=True)
class CodexTeacherSettings:
    execution: CodexSettings
    campaign_role: str
    capture_training_transcript: bool
    max_tool_calls: int | None
    max_patch_calls: int | None
    max_consecutive_rejected_calls: int | None
    observation_policy_id: str
    transcript_format: str


def teacher_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexTeacherSettings:
    unknown = sorted(set(options) - _TEACHER_OPTIONS)
    if unknown:
        raise ValueError("unknown Codex MCP teacher options: " + ", ".join(unknown))
    role = options.get("campaign_role")
    capture = options.get("capture_training_transcript")
    if role != "training" or capture is not True:
        raise ValueError("Codex MCP teacher is available only for captured training campaigns")
    raw_limits = (
        options.get("max_tool_calls"),
        options.get("max_patch_calls"),
        options.get("max_consecutive_rejected_calls"),
    )
    if any(value is not None for value in raw_limits) and not all(
        value is not None for value in raw_limits
    ):
        raise ValueError("Codex teacher broker limits must be configured together")
    max_tool_calls: int | None = None
    max_patch_calls: int | None = None
    max_consecutive_rejected_calls: int | None = None
    if all(value is not None for value in raw_limits):
        max_tool_calls = _limit(raw_limits[0], "max_tool_calls")
        max_patch_calls = _limit(raw_limits[1], "max_patch_calls")
        max_consecutive_rejected_calls = _limit(raw_limits[2], "max_consecutive_rejected_calls")
        if max_patch_calls > max_tool_calls:
            raise ValueError("Codex teacher patch limit cannot exceed its tool-call limit")
    raw_observation_policy = options.get(
        "observation_policy_id", options.get("observation_policy", "repository_observation_v1")
    )
    observation_policy = resolve_repository_observation_policy(raw_observation_policy)
    observation_policy_id = (
        observation_policy.policy_id if observation_policy is not None else "legacy"
    )
    transcript_format = options.get("transcript_format", "v1")
    if transcript_format not in {"v1", "v2"}:
        raise ValueError("Codex teacher transcript_format must be v1 or v2")
    if transcript_format == "v2" and observation_policy is None:
        raise ValueError(
            "Codex teacher transcript_format v2 requires the bounded observation policy"
        )
    base_options = {
        key: value
        for key, value in options.items()
        if key
        not in {
            "campaign_role",
            "capture_training_transcript",
            "max_tool_calls",
            "max_patch_calls",
            "max_consecutive_rejected_calls",
            "observation_policy_id",
            "observation_policy",
            "transcript_format",
        }
    }
    base_options.setdefault("model_id", "gpt-5.4")
    base_options.setdefault("reasoning_effort", "xhigh")
    base_options.setdefault("sandbox", "read-only")
    base = readonly_agent_settings(
        base_options,
        capabilities,
        task_wall_time_s=task_wall_time_s,
    )
    if base.model_id != "gpt-5.4" or base.effective_reasoning_effort != "xhigh":
        raise ValueError("Codex MCP teacher requires gpt-5.4 with xhigh reasoning")
    fingerprint = stable_hash(
        {
            "base_configuration_fingerprint": base.configuration_fingerprint,
            "integration_track": "codex_cli_mcp_teacher",
            "campaign_role": "training",
            "capture_training_transcript": True,
            "tool_availability_policy": "verigym_required_allowlisted_mcp_only_v1",
            "tool_use_policy": "repository_action_state_machine_v2",
            "max_tool_calls": max_tool_calls,
            "max_patch_calls": max_patch_calls,
            "max_consecutive_rejected_calls": max_consecutive_rejected_calls,
            "observation_policy_id": observation_policy_id,
            "transcript_format": transcript_format,
        }
    )
    execution = replace(
        base,
        integration_track="codex_cli_external_agent",
        tool_availability_policy="verigym_required_allowlisted_mcp_only_v1",
        tool_use_policy="repository_action_state_machine_v2",
        configuration_fingerprint=fingerprint,
    )
    return CodexTeacherSettings(
        execution=execution,
        campaign_role="training",
        capture_training_transcript=True,
        max_tool_calls=max_tool_calls,
        max_patch_calls=max_patch_calls,
        max_consecutive_rejected_calls=max_consecutive_rejected_calls,
        observation_policy_id=observation_policy_id,
        transcript_format=transcript_format,
    )


def _limit(value: JsonValue | None, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4096:
        raise ValueError(f"Codex teacher {label} must be in [1, 4096]")
    return value


__all__ = ["CodexTeacherSettings", "teacher_settings"]
