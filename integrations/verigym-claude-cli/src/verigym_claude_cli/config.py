"""Strict Claude CLI execution settings with provider and broker resource caps."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from verigym.evolution.memory import validate_agent_version
from verigym.plugin_api import JsonValue, content_hash
from verigym.schemas.evolution import AgentVersionManifest

from .capabilities import CapabilityReport
from .process import (
    ClaudeProcessError,
    forwarded_proxy_environment_names,
    provider_auth_environment_name,
    provider_base_url,
)

_OPTIONS = {
    "model_id",
    "reasoning_effort",
    "max_process_time_s",
    "max_output_bytes",
    "allow_proxy_environment",
    "prompt_contract_id",
    "expected_context_window",
    "expected_cli_version",
    "expected_cli_executable_sha256",
    "expected_capability_fingerprint",
    "agent_version_id",
    "agent_version_hash",
    "agent_version_manifest_json",
    "campaign_role",
    "capture_training_transcript",
    "max_tool_calls",
    "max_patch_calls",
    "max_consecutive_rejected_calls",
    "max_provider_billed_units",
    "max_budget_usd",
}
_PROMPT_CONTRACT = "claude_cli_workspace_repository_task_context_v5"
_AUTH_IDENTITIES = {
    "ANTHROPIC_AUTH_TOKEN": (
        "anthropic_auth_token_env",
        "claude.auth.anthropic_auth_token_env_custom_base.v1",
    ),
    "ANTHROPIC_API_KEY": (
        "anthropic_api_key_env",
        "claude.auth.anthropic_api_key_env_custom_base.v1",
    ),
}


@dataclass(frozen=True)
class ClaudeSettings:
    integration_track: str
    model_id: str
    requested_reasoning_effort: str
    effective_reasoning_effort: str
    reasoning_effort_source: str
    inherited_reasoning_effort_allowed: bool
    requested_process_timeout_s: float
    task_wall_time_s: float
    effective_process_timeout_s: float
    timeout_clamped: bool
    max_output_bytes: int
    allow_proxy_environment: bool
    forwarded_proxy_environment_names: tuple[str, ...]
    requested_auth_mode: str
    resolved_auth_mode: str
    auth_semantic_id: str
    auth_alias_used: bool
    provider_origin: str
    provider_endpoint_sha256: str
    prompt_contract_id: str
    expected_context_window_tokens: int | None
    agent_version_id: str | None
    agent_version_hash: str | None
    campaign_role: str
    capture_training_transcript: bool
    max_tool_calls: int | None
    max_patch_calls: int | None
    max_consecutive_rejected_calls: int | None
    max_provider_tokens: int
    max_budget_usd: float
    configuration_fingerprint: str

    def safe_configuration(self, capabilities: CapabilityReport) -> dict[str, JsonValue]:
        return {
            "integration_track": self.integration_track,
            "requested_model_id": self.model_id,
            "requested_reasoning_effort": self.requested_reasoning_effort,
            "effective_reasoning_effort": self.effective_reasoning_effort,
            "reasoning_effort_source": self.reasoning_effort_source,
            "inherited_reasoning_effort_allowed": self.inherited_reasoning_effort_allowed,
            "requested_process_timeout_s": self.requested_process_timeout_s,
            "task_wall_time_s": self.task_wall_time_s,
            "effective_process_timeout_s": self.effective_process_timeout_s,
            "timeout_clamped": self.timeout_clamped,
            "max_output_bytes": self.max_output_bytes,
            "allow_proxy_environment": self.allow_proxy_environment,
            "forwarded_proxy_environment_names": list(self.forwarded_proxy_environment_names),
            "requested_auth_mode": self.requested_auth_mode,
            "resolved_auth_mode": self.resolved_auth_mode,
            "auth_semantic_id": self.auth_semantic_id,
            "auth_alias_used": self.auth_alias_used,
            "provider_origin": self.provider_origin,
            "provider_endpoint_sha256": self.provider_endpoint_sha256,
            "prompt_contract_id": self.prompt_contract_id,
            "expected_context_window_tokens": self.expected_context_window_tokens,
            "agent_version_id": self.agent_version_id,
            "agent_version_hash": self.agent_version_hash,
            "campaign_role": self.campaign_role,
            "capture_training_transcript": self.capture_training_transcript,
            "cli_version": capabilities.version_output,
            "cli_executable_sha256": capabilities.executable_sha256,
            "capability_fingerprint": capabilities.capability_fingerprint,
            "execution_surface": "claude_cli",
            "agent_harness_kind": "claude_cli",
            "tool_availability_policy": "verigym_mcp_only_no_builtin_tools_v1",
            "tool_use_policy": "docker_runtime_workspace_tools_v1",
            "process_wall_timeout_configured": True,
            "process_evidence_byte_bound_configured": True,
            "internal_turn_limit_configured": False,
            "model_call_limit_configured": False,
            "model_token_limit_configured": True,
            "model_token_limit": self.max_provider_tokens,
            "model_token_limit_scope": "cache_inclusive_stream_observed",
            "budget_limit_configured": True,
            "budget_limit_usd": self.max_budget_usd,
            "broker_resource_limits_configured": self.max_tool_calls is not None,
            "max_tool_calls": self.max_tool_calls,
            "max_patch_calls": self.max_patch_calls,
            "max_consecutive_rejected_calls": self.max_consecutive_rejected_calls,
        }


def agent_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> ClaudeSettings:
    unknown = sorted(set(options) - _OPTIONS)
    if unknown:
        raise ValueError("unknown Claude CLI agent options: " + ", ".join(unknown))
    model_id = _identifier(options.get("model_id"), "model_id", 256)
    effort = _identifier(options.get("reasoning_effort", "max"), "reasoning_effort", 32)
    if effort != "max":
        raise ValueError("Claude CLI integration currently requires explicit max effort")
    prompt_contract = _identifier(
        options.get("prompt_contract_id", _PROMPT_CONTRACT),
        "prompt_contract_id",
        192,
    )
    if prompt_contract != _PROMPT_CONTRACT:
        raise ValueError("Claude CLI prompt contract differs from the plugin declaration")
    requested_timeout = _number(
        options.get("max_process_time_s", float(task_wall_time_s)),
        "max_process_time_s",
    )
    if requested_timeout <= 0 or requested_timeout > 1800:
        raise ValueError("Claude process timeout must be in (0, 1800] seconds")
    effective_timeout = min(requested_timeout, float(task_wall_time_s))
    max_output = _integer(options.get("max_output_bytes", 8 * 1024 * 1024), "max_output_bytes")
    if max_output < 1024 or max_output > 16 * 1024 * 1024:
        raise ValueError("Claude evidence byte bound must be between 1 KiB and 16 MiB")
    allow_proxy = _boolean(options.get("allow_proxy_environment", False), "allow_proxy_environment")
    campaign_role = _identifier(options.get("campaign_role", "ordinary"), "campaign_role", 32)
    if campaign_role not in {"ordinary", "training", "development", "heldout"}:
        raise ValueError("Claude campaign_role is unsupported")
    capture_transcript = _boolean(
        options.get("capture_training_transcript", False), "capture_training_transcript"
    )
    if capture_transcript and campaign_role != "training":
        raise ValueError("Claude transcript capture is permitted only for the training split")
    raw_limits = (
        options.get("max_tool_calls"),
        options.get("max_patch_calls"),
        options.get("max_consecutive_rejected_calls"),
    )
    if any(value is not None for value in raw_limits) and not all(
        value is not None for value in raw_limits
    ):
        raise ValueError("Claude broker limits must be configured together")
    max_tool_calls: int | None = None
    max_patch_calls: int | None = None
    max_consecutive_rejected_calls: int | None = None
    if all(value is not None for value in raw_limits):
        max_tool_calls = _bounded_limit(raw_limits[0], "max_tool_calls")
        max_patch_calls = _bounded_limit(raw_limits[1], "max_patch_calls")
        max_consecutive_rejected_calls = _bounded_limit(
            raw_limits[2], "max_consecutive_rejected_calls"
        )
        if max_patch_calls > max_tool_calls:
            raise ValueError("Claude patch limit cannot exceed its tool-call limit")
    max_provider_tokens = _integer(
        options.get("max_provider_billed_units", 2_000_000),
        "max_provider_billed_units",
    )
    if not 1 <= max_provider_tokens <= 100_000_000:
        raise ValueError("Claude provider token limit must be in [1, 100000000]")
    max_budget_usd = _number(options.get("max_budget_usd", 2.0), "max_budget_usd")
    if not 0.01 <= max_budget_usd <= 100.0:
        raise ValueError("Claude provider budget must be in [0.01, 100] USD")
    expected_context = options.get("expected_context_window")
    if expected_context is not None:
        expected_context = _integer(expected_context, "expected_context_window")
        if expected_context < 1024 or expected_context > 8_000_000:
            raise ValueError("expected Claude context window is outside the audit bound")
    _validate_capability_expectations(options, capabilities)
    try:
        auth_environment_name = provider_auth_environment_name()
    except ClaudeProcessError as exc:
        raise ValueError(str(exc)) from exc
    auth_mode, auth_semantic_id = _AUTH_IDENTITIES[auth_environment_name]
    try:
        base_url = provider_base_url()
    except ClaudeProcessError as exc:
        raise ValueError(str(exc)) from exc
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ANTHROPIC_BASE_URL must be a credential-free HTTPS URL")
    provider_origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        provider_origin += f":{parsed.port}"
    provider_endpoint_sha256 = hashlib.sha256(base_url.encode("utf-8")).hexdigest()
    version_id, version_hash = _versioned_identity(
        options,
        model_id=model_id,
        reasoning_effort=effort,
        auth_semantic_id=auth_semantic_id,
    )
    safe: dict[str, JsonValue] = {
        "integration_track": "claude_cli_external_agent",
        "model_id": model_id,
        "reasoning_effort": effort,
        "reasoning_effort_source": "verigym_explicit_cli_override",
        "inherited_reasoning_effort_allowed": False,
        "requested_process_timeout_s": requested_timeout,
        "task_wall_time_s": float(task_wall_time_s),
        "effective_process_timeout_s": effective_timeout,
        "timeout_clamped": effective_timeout != requested_timeout,
        "max_output_bytes": max_output,
        "allow_proxy_environment": allow_proxy,
        "forwarded_proxy_environment_names": list(forwarded_proxy_environment_names(allow_proxy)),
        "requested_auth_mode": auth_mode,
        "resolved_auth_mode": auth_mode,
        "auth_semantic_id": auth_semantic_id,
        "auth_alias_used": False,
        "provider_origin": provider_origin,
        "provider_endpoint_sha256": provider_endpoint_sha256,
        "prompt_contract_id": prompt_contract,
        "expected_context_window_tokens": expected_context,
        "agent_version_id": version_id,
        "agent_version_hash": version_hash,
        "campaign_role": campaign_role,
        "capture_training_transcript": capture_transcript,
        "max_tool_calls": max_tool_calls,
        "max_patch_calls": max_patch_calls,
        "max_consecutive_rejected_calls": max_consecutive_rejected_calls,
        "max_provider_billed_units": max_provider_tokens,
        "max_budget_usd": max_budget_usd,
        "capability_fingerprint": capabilities.capability_fingerprint,
        "internal_turn_limit": None,
        "model_call_limit": None,
        "model_token_limit": max_provider_tokens,
        "model_token_limit_scope": "cache_inclusive_stream_observed",
        "budget_limit": max_budget_usd,
    }
    return ClaudeSettings(
        integration_track="claude_cli_external_agent",
        model_id=model_id,
        requested_reasoning_effort=effort,
        effective_reasoning_effort=effort,
        reasoning_effort_source="verigym_explicit_cli_override",
        inherited_reasoning_effort_allowed=False,
        requested_process_timeout_s=requested_timeout,
        task_wall_time_s=float(task_wall_time_s),
        effective_process_timeout_s=effective_timeout,
        timeout_clamped=effective_timeout != requested_timeout,
        max_output_bytes=max_output,
        allow_proxy_environment=allow_proxy,
        forwarded_proxy_environment_names=forwarded_proxy_environment_names(allow_proxy),
        requested_auth_mode=auth_mode,
        resolved_auth_mode=auth_mode,
        auth_semantic_id=auth_semantic_id,
        auth_alias_used=False,
        provider_origin=provider_origin,
        provider_endpoint_sha256=provider_endpoint_sha256,
        prompt_contract_id=prompt_contract,
        expected_context_window_tokens=expected_context,
        agent_version_id=version_id,
        agent_version_hash=version_hash,
        campaign_role=campaign_role,
        capture_training_transcript=capture_transcript,
        max_tool_calls=max_tool_calls,
        max_patch_calls=max_patch_calls,
        max_consecutive_rejected_calls=max_consecutive_rejected_calls,
        max_provider_tokens=max_provider_tokens,
        max_budget_usd=max_budget_usd,
        configuration_fingerprint=content_hash(safe),
    )


def _validate_capability_expectations(
    options: Mapping[str, JsonValue], capabilities: CapabilityReport
) -> None:
    expected = {
        "expected_cli_version": capabilities.version_output,
        "expected_cli_executable_sha256": capabilities.executable_sha256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
    }
    for key, actual in expected.items():
        value = options.get(key)
        if value is not None and value != actual:
            raise ValueError(f"Claude frozen expectation changed: {key}")


def _versioned_identity(
    options: Mapping[str, JsonValue],
    *,
    model_id: str,
    reasoning_effort: str,
    auth_semantic_id: str,
) -> tuple[str | None, str | None]:
    version_id = options.get("agent_version_id")
    version_hash = options.get("agent_version_hash")
    raw_manifest = options.get("agent_version_manifest_json")
    present = any(value is not None for value in (version_id, version_hash, raw_manifest))
    if not present:
        return None, None
    if (
        not isinstance(version_id, str)
        or not isinstance(version_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", version_hash)
        or not isinstance(raw_manifest, str)
    ):
        raise ValueError("Claude versioned identity requires ID, SHA-256, and manifest JSON")
    try:
        payload = json.loads(raw_manifest, object_pairs_hook=_unique_object)
        manifest = validate_agent_version(AgentVersionManifest.model_validate(payload))
    except Exception as exc:
        raise ValueError(f"invalid Claude agent-version manifest: {exc}") from exc
    if (
        manifest.agent_version_id != version_id
        or manifest.version_hash != version_hash
        or manifest.base_agent_id != "claude-cli-agent"
        or manifest.model_id != model_id
        or manifest.reasoning_effort != reasoning_effort
        or manifest.auth_semantic_id != auth_semantic_id
        or manifest.update_type != "none"
        or not manifest.executable_in_m10b
        or manifest.model_weights_modified
    ):
        raise ValueError("agent-version manifest differs from effective Claude settings")
    return version_id, version_hash


def _identifier(value: JsonValue | None, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or value.startswith("-")
    ):
        raise ValueError(f"{label} must be a bounded control-free identifier")
    return value


def _number(value: JsonValue, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _bounded_limit(value: JsonValue | None, label: str) -> int:
    parsed = _integer(value, label)
    if not 1 <= parsed <= 4096:
        raise ValueError(f"{label} must be in [1, 4096]")
    return parsed


def _boolean(value: JsonValue, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("agent-version manifest contains a duplicate key")
        result[key] = value
    return result


__all__ = ["ClaudeSettings", "agent_settings"]
