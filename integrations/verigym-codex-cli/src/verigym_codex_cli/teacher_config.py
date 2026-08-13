"""Frozen Codex MCP-only teacher settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

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
}


@dataclass(frozen=True)
class CodexTeacherSettings:
    execution: CodexSettings
    campaign_role: str
    capture_training_transcript: bool


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
    base_options = {
        key: value
        for key, value in options.items()
        if key not in {"campaign_role", "capture_training_transcript"}
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
    )


__all__ = ["CodexTeacherSettings", "teacher_settings"]
