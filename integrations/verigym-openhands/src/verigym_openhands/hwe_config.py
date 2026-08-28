"""Frozen, secret-free settings for the OpenHands HWE native-shell backend."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from verigym.core.hashing import content_hash
from verigym.evolution.memory import validate_agent_version
from verigym.plugin_api import JsonValue
from verigym.schemas.evolution import AgentVersionManifest

from verigym_openhands._recovery import (
    OPENHANDS_FORMAT_RECOVERY_BUDGET,
    OPENHANDS_FORMAT_RECOVERY_POLICY,
)

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_OPTIONS = {
    "model_id",
    "base_url_env",
    "api_key_env",
    "max_iterations",
    "max_process_time_s",
    "max_output_tokens",
    "max_context_tokens",
    "seed",
    "temperature",
    "top_p",
    "whole_episode_retries",
    "expected_sdk_version",
    "campaign_role",
    "capture_training_transcript",
    "agent_version_id",
    "agent_version_hash",
    "agent_version_manifest_json",
    "collection_profile_id",
    "tool_choice_policy",
}


@dataclass(frozen=True)
class OpenHandsHweSettings:
    model_id: str
    base_url_env: str
    api_key_env: str
    max_iterations: int
    process_timeout_s: float
    max_output_tokens: int
    max_context_tokens: int
    seed: int
    campaign_role: str
    capture_training_transcript: bool
    tool_choice_policy: str
    agent_version_id: str | None
    agent_version_hash: str | None
    configuration_fingerprint: str

    def safe_dict(self) -> dict[str, JsonValue]:
        return {
            "model_id": self.model_id,
            "base_url_env": self.base_url_env,
            "api_key_env": self.api_key_env,
            "max_iterations": self.max_iterations,
            "max_provider_calls": self.max_iterations,
            "provider_call_accounting": (
                "conversation_agent_attempt_counter_v2"
                if self.tool_choice_policy
                in {
                    "validated_responses_recovery_state_required_tool_v17",
                    "validated_responses_recovery_state_required_tool_v18",
                }
                else "adapter_attempt_counter_v1"
            ),
            "process_timeout_s": self.process_timeout_s,
            "max_output_tokens": self.max_output_tokens,
            "max_context_tokens": self.max_context_tokens,
            "seed": self.seed,
            "temperature": 0,
            "top_p": 1,
            "whole_episode_retries": 0,
            "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
            "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
            "same_session_recovery": True,
            "termination_authority": "broker_typed_finish",
            "hook_subprocess_locale": "C",
            "provider_thinking_mode": "disabled",
            "tool_choice_policy": self.tool_choice_policy,
            "campaign_role": self.campaign_role,
            "capture_training_transcript": self.capture_training_transcript,
            "agent_version_id": self.agent_version_id,
            "agent_version_hash": self.agent_version_hash,
            "sdk_version": "1.42.1",
            "collection_profile_id": "hwe_production_native_shell_v2",
            "tool_contract": "hwe_native_shell_v2",
            "configuration_fingerprint": self.configuration_fingerprint,
        }


def resolve_hwe_settings(
    options: Mapping[str, JsonValue], *, task_wall_time_s: int
) -> OpenHandsHweSettings:
    """Resolve a deterministic no-retry 64K HWE rollout configuration."""

    unknown = sorted(set(options) - _OPTIONS)
    if unknown:
        raise ValueError("unknown OpenHands HWE options: " + ", ".join(unknown))
    model_id = _text(options.get("model_id"), "model_id")
    base_url_env = _environment_name(options.get("base_url_env", "VERIGYM_MODEL_BASE_URL"))
    api_key_env = _environment_name(options.get("api_key_env", "VERIGYM_MODEL_API_KEY"))
    base_url = os.environ.get(base_url_env)
    api_key = os.environ.get(api_key_env)
    if not base_url or not api_key:
        raise ValueError("OpenHands HWE model endpoint environment is incomplete")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("OpenHands HWE base URL must be credential-free HTTP(S)")
    max_iterations = _integer(options.get("max_iterations", 200), "max_iterations")
    if not 1 <= max_iterations <= 200:
        raise ValueError("OpenHands HWE max_iterations must be in [1, 200]")
    max_output_tokens = _integer(options.get("max_output_tokens", 256), "max_output_tokens")
    if not 1 <= max_output_tokens <= 2048:
        raise ValueError("OpenHands HWE max_output_tokens must be in [1, 2048]")
    max_context_tokens = _integer(options.get("max_context_tokens", 65_536), "max_context_tokens")
    if max_context_tokens != 65_536:
        raise ValueError("OpenHands HWE freezes a 65536-token context")
    seed = _integer(options.get("seed", 484), "seed")
    if not 0 <= seed <= 2_147_483_647:
        raise ValueError("OpenHands HWE seed is outside the supported range")
    if options.get("temperature", 0) != 0 or options.get("top_p", 1) != 1:
        raise ValueError("OpenHands HWE freezes greedy sampling")
    if options.get("whole_episode_retries", 0) != 0:
        raise ValueError("OpenHands HWE forbids whole-episode retries")
    if options.get("expected_sdk_version", "1.42.1") != "1.42.1":
        raise ValueError("OpenHands HWE SDK version differs from 1.42.1")
    if options.get("collection_profile_id", "hwe_production_native_shell_v2") != (
        "hwe_production_native_shell_v2"
    ):
        raise ValueError("OpenHands HWE collection profile changed")
    tool_choice_policy = _text(options.get("tool_choice_policy", "auto"), "tool_choice_policy")
    if tool_choice_policy not in {
        "auto",
        "required",
        "recovery_forced_finish",
        "recovery_forced_finish_v5",
        "recovery_state_forced_finish_v6",
        "validated_recovery_state_forced_finish_v7",
        "validated_recovery_state_forced_finish_v8",
        "validated_responses_recovery_state_forced_finish_v9",
        "validated_responses_recovery_state_required_tool_v11",
        "validated_responses_recovery_state_required_tool_v12",
        "validated_responses_recovery_state_required_tool_v13",
        "validated_responses_recovery_state_required_tool_v14",
        "validated_responses_recovery_state_required_tool_v15",
        "validated_responses_recovery_state_required_tool_v16",
        "validated_responses_recovery_state_required_tool_v17",
        "validated_responses_recovery_state_required_tool_v18",
    }:
        raise ValueError("OpenHands HWE tool choice policy is unsupported")
    role = _text(options.get("campaign_role", "development"), "campaign_role")
    if role not in {"development", "evaluation", "training"}:
        raise ValueError("OpenHands HWE campaign role is unsupported")
    capture = _boolean(options.get("capture_training_transcript", False), "capture transcript")
    if capture and role != "training":
        raise ValueError("OpenHands HWE transcript capture is training-only")
    timeout_value = options.get("max_process_time_s", task_wall_time_s)
    if isinstance(timeout_value, bool) or not isinstance(timeout_value, int | float):
        raise ValueError("OpenHands HWE process timeout must be numeric")
    process_timeout_s = min(float(timeout_value), float(task_wall_time_s))
    if not 0 < process_timeout_s <= 4200:
        raise ValueError("OpenHands HWE process timeout must be in (0, 4200]")
    version_id, version_hash = _agent_version(options, model_id=model_id)
    safe = {
        "model_id": model_id,
        "base_url_origin": (
            f"{parsed.scheme}://{parsed.hostname}"
            + (f":{parsed.port}" if parsed.port is not None else "")
        ),
        "base_url_env": base_url_env,
        "api_key_env": api_key_env,
        "max_iterations": max_iterations,
        "max_provider_calls": max_iterations,
        "provider_call_accounting": (
            "conversation_agent_attempt_counter_v2"
            if tool_choice_policy
            in {
                "validated_responses_recovery_state_required_tool_v17",
                "validated_responses_recovery_state_required_tool_v18",
            }
            else "adapter_attempt_counter_v1"
        ),
        "process_timeout_s": process_timeout_s,
        "max_output_tokens": max_output_tokens,
        "max_context_tokens": max_context_tokens,
        "seed": seed,
        "temperature": 0,
        "top_p": 1,
        "whole_episode_retries": 0,
        "format_recovery_policy_id": OPENHANDS_FORMAT_RECOVERY_POLICY,
        "format_recovery_budget": OPENHANDS_FORMAT_RECOVERY_BUDGET,
        "same_session_recovery": True,
        "termination_authority": "broker_typed_finish",
        "hook_subprocess_locale": "C",
        "provider_thinking_mode": "disabled",
        "tool_choice_policy": tool_choice_policy,
        "campaign_role": role,
        "capture_training_transcript": capture,
        "agent_version_id": version_id,
        "agent_version_hash": version_hash,
        "sdk_version": "1.42.1",
        "collection_profile_id": "hwe_production_native_shell_v2",
        "tool_contract": "hwe_native_shell_v2",
    }
    return OpenHandsHweSettings(
        model_id=model_id,
        base_url_env=base_url_env,
        api_key_env=api_key_env,
        max_iterations=max_iterations,
        process_timeout_s=process_timeout_s,
        max_output_tokens=max_output_tokens,
        max_context_tokens=max_context_tokens,
        seed=seed,
        campaign_role=role,
        capture_training_transcript=capture,
        tool_choice_policy=tool_choice_policy,
        agent_version_id=version_id,
        agent_version_hash=version_hash,
        configuration_fingerprint=content_hash(safe),
    )


def _agent_version(
    options: Mapping[str, JsonValue], *, model_id: str
) -> tuple[str | None, str | None]:
    version_id = options.get("agent_version_id")
    version_hash = options.get("agent_version_hash")
    manifest_json = options.get("agent_version_manifest_json")
    if (version_id is None) != (version_hash is None):
        raise ValueError("OpenHands HWE agent version ID and hash must be supplied together")
    if version_id is None:
        if manifest_json is not None:
            raise ValueError("OpenHands HWE version manifest requires its ID and hash")
        return None, None
    parsed_id = _text(version_id, "agent_version_id")
    if not isinstance(version_hash, str) or not _HASH.fullmatch(version_hash):
        raise ValueError("OpenHands HWE agent version hash must be lowercase SHA-256")
    if not isinstance(manifest_json, str):
        raise ValueError("OpenHands HWE versioned policy requires its manifest JSON")
    try:
        version = validate_agent_version(
            AgentVersionManifest.model_validate(json.loads(manifest_json))
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("OpenHands HWE agent version manifest is invalid") from exc
    if (
        version.agent_version_id != parsed_id
        or version.version_hash != version_hash
        or version.base_agent_id != "openhands-hwe-agent"
        or version.model_id != model_id
    ):
        raise ValueError("OpenHands HWE agent version differs from the requested model")
    return parsed_id, version_hash


def _environment_name(value: JsonValue) -> str:
    if not isinstance(value, str) or not _ENV_NAME.fullmatch(value):
        raise ValueError("OpenHands HWE environment names must use upper snake case")
    return value


def _text(value: JsonValue | None, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"OpenHands HWE {label} must be bounded printable text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"OpenHands HWE {label} must be an integer")
    return value


def _boolean(value: JsonValue, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"OpenHands HWE {label} must be a boolean")
    return value


__all__ = ["OpenHandsHweSettings", "resolve_hwe_settings"]
