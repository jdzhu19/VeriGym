"""Secret-free OpenHands SDK settings."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from verigym.core.hashing import content_hash
from verigym.core.repository_observation import resolve_repository_observation_policy
from verigym.evolution.memory import validate_agent_version
from verigym.plugin_api import JsonValue
from verigym.schemas.evolution import AgentVersionManifest

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_OPTIONS = {
    "model_id",
    "base_url_env",
    "api_key_env",
    "max_iterations",
    "max_process_time_s",
    "expected_sdk_version",
    "campaign_role",
    "agent_version_id",
    "agent_version_hash",
    "agent_version_manifest_json",
    "observation_policy_id",
    "observation_policy",
}


@dataclass(frozen=True)
class OpenHandsSettings:
    model_id: str
    base_url_env: str
    api_key_env: str
    max_iterations: int
    process_timeout_s: float
    campaign_role: str
    agent_version_id: str | None
    agent_version_hash: str | None
    observation_policy_id: str
    configuration_fingerprint: str

    def safe_dict(self) -> dict[str, JsonValue]:
        return {
            "model_id": self.model_id,
            "base_url_env": self.base_url_env,
            "api_key_env": self.api_key_env,
            "max_iterations": self.max_iterations,
            "process_timeout_s": self.process_timeout_s,
            "campaign_role": self.campaign_role,
            "agent_version_id": self.agent_version_id,
            "agent_version_hash": self.agent_version_hash,
            "sdk_version": "1.42.1",
            "include_default_tools": [],
            "explicit_tools": [],
            "plugins": [],
            "client_tools": [],
            "workspace_policy": "private_empty_non_repository",
            "mcp_servers": ["verigym"],
            "observation_policy_id": self.observation_policy_id,
            "configuration_fingerprint": self.configuration_fingerprint,
        }


def openhands_settings(
    options: Mapping[str, JsonValue],
    *,
    task_wall_time_s: int,
) -> OpenHandsSettings:
    unknown = sorted(set(options) - _OPTIONS)
    if unknown:
        raise ValueError("unknown OpenHands agent options: " + ", ".join(unknown))
    model_id = _text(options.get("model_id"), "model_id")
    base_url_env = _environment_name(options.get("base_url_env", "VERIGYM_MODEL_BASE_URL"))
    api_key_env = _environment_name(options.get("api_key_env", "VERIGYM_MODEL_API_KEY"))
    base_url = os.environ.get(base_url_env)
    api_key = os.environ.get(api_key_env)
    if not base_url or not api_key:
        raise ValueError("OpenHands model endpoint environment is incomplete")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("OpenHands base URL must be a credential-free HTTP(S) endpoint")
    max_iterations = _integer(options.get("max_iterations", 128), "max_iterations")
    if not 1 <= max_iterations <= 128:
        raise ValueError("OpenHands max_iterations must be in [1, 128]")
    requested_timeout = options.get("max_process_time_s", task_wall_time_s)
    if isinstance(requested_timeout, bool) or not isinstance(requested_timeout, int | float):
        raise ValueError("OpenHands process timeout must be numeric")
    timeout = min(float(requested_timeout), float(task_wall_time_s))
    if not 0 < timeout <= 4200:
        raise ValueError("OpenHands process timeout must be in (0, 4200]")
    if options.get("expected_sdk_version", "1.42.1") != "1.42.1":
        raise ValueError("OpenHands SDK version differs from the frozen 1.42.1 pin")
    role = _text(options.get("campaign_role", "development"), "campaign_role")
    if role not in {"development", "evaluation", "training"}:
        raise ValueError("OpenHands campaign role is unsupported")
    version_id = options.get("agent_version_id")
    version_hash = options.get("agent_version_hash")
    if (version_id is None) != (version_hash is None):
        raise ValueError("OpenHands agent version ID and hash must be supplied together")
    if version_id is not None:
        version_id = _text(version_id, "agent_version_id")
    if version_hash is not None and (
        not isinstance(version_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", version_hash)
    ):
        raise ValueError("OpenHands agent version hash must be lowercase SHA-256")
    raw_manifest = options.get("agent_version_manifest_json")
    raw_observation_policy = options.get(
        "observation_policy_id", options.get("observation_policy", "repository_observation_v1")
    )
    observation_policy = resolve_repository_observation_policy(raw_observation_policy)
    observation_policy_id = (
        observation_policy.policy_id if observation_policy is not None else "legacy"
    )
    if version_id is not None:
        if not isinstance(raw_manifest, str):
            raise ValueError("OpenHands versioned policy requires its manifest JSON")
        try:
            version = validate_agent_version(
                AgentVersionManifest.model_validate(json.loads(raw_manifest))
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("OpenHands agent version manifest is invalid") from exc
        if (
            version.agent_version_id != version_id
            or version.version_hash != version_hash
            or version.base_agent_id != "openhands-repository-agent"
            or version.model_id != model_id
        ):
            raise ValueError("OpenHands agent version differs from the requested model")
    elif raw_manifest is not None:
        raise ValueError("OpenHands agent version manifest requires its ID and hash")
    safe = {
        "model_id": model_id,
        "base_url_origin": (
            f"{parsed.scheme}://{parsed.hostname}"
            + (f":{parsed.port}" if parsed.port is not None else "")
        ),
        "base_url_env": base_url_env,
        "api_key_env": api_key_env,
        "max_iterations": max_iterations,
        "process_timeout_s": timeout,
        "campaign_role": role,
        "sdk_version": "1.42.1",
        "agent_version_id": version_id,
        "agent_version_hash": version_hash,
        "tools": "repository_action.v2",
        "observation_policy_id": observation_policy_id,
    }
    return OpenHandsSettings(
        model_id=model_id,
        base_url_env=base_url_env,
        api_key_env=api_key_env,
        max_iterations=max_iterations,
        process_timeout_s=timeout,
        campaign_role=role,
        agent_version_id=version_id,
        agent_version_hash=version_hash,
        observation_policy_id=observation_policy_id,
        configuration_fingerprint=content_hash(safe),
    )


def _environment_name(value: JsonValue) -> str:
    if not isinstance(value, str) or not _ENV_NAME.fullmatch(value):
        raise ValueError("OpenHands environment names must use upper snake case")
    return value


def _text(value: JsonValue | None, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"OpenHands {label} must be bounded printable text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"OpenHands {label} must be an integer")
    return value


__all__ = ["OpenHandsSettings", "openhands_settings"]
