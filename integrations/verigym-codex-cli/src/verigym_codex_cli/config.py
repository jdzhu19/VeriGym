"""Strict per-run configuration for the two Codex CLI tracks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from verigym.plugin_api import JsonValue, ModelRunConfig

from .capabilities import CapabilityReport
from .process import auth_configuration
from .util import clean_identifier, stable_hash

_COMMON_OPTIONS = {
    "sandbox",
    "approval_policy",
    "max_process_time_s",
    "max_output_bytes",
    "allow_proxy_environment",
}
_MODEL_OPTIONS = {*_COMMON_OPTIONS, "reject_tool_use"}
_AGENT_OPTIONS = {*_COMMON_OPTIONS, "model_id"}


@dataclass(frozen=True)
class CodexSettings:
    integration_track: str
    model_id: str
    sandbox_policy: str
    approval_policy: str
    max_process_time_s: float
    max_output_bytes: int
    reject_tool_use: bool
    auth_mode_label: str
    credential_env: str | None
    allow_proxy_environment: bool
    configuration_fingerprint: str

    def safe_configuration(self, capabilities: CapabilityReport) -> dict[str, JsonValue]:
        return {
            "integration_track": self.integration_track,
            "requested_model_id": self.model_id,
            "cli_version": capabilities.version_output,
            "cli_executable_sha256": capabilities.executable_sha256,
            "capability_fingerprint": capabilities.capability_fingerprint,
            "sandbox_policy": self.sandbox_policy,
            "approval_policy": self.approval_policy,
            "empty_working_directory_policy": self.integration_track == "codex_cli_model_proxy",
            "ephemeral_session_policy": True,
            "auth_mode_label": self.auth_mode_label,
            "max_process_time_s": self.max_process_time_s,
            "max_output_bytes": self.max_output_bytes,
            "reject_tool_use": self.reject_tool_use,
            "pure_api_model_eval": False,
            "direct_api_benchmark": False,
        }


def model_settings(config: ModelRunConfig, capabilities: CapabilityReport) -> CodexSettings:
    if config.base_url is not None:
        raise ValueError("codex-cli-exec-model does not accept a direct API base URL")
    if config.temperature != 0.0 or config.top_p is not None:
        raise ValueError("Codex CLI model proxy does not expose temperature or top_p controls")
    model_id = _model_id(config.model_id)
    options = config.client_options
    _reject_unknown(options, _MODEL_OPTIONS, kind="model")
    sandbox = _string(options, "sandbox", "most-restrictive-supported")
    if sandbox == "most-restrictive-supported":
        sandbox = "read-only"
    if sandbox != "read-only" or sandbox not in capabilities.supported_sandbox_modes:
        raise ValueError("Track A requires the supported read-only sandbox")
    approval = _string(options, "approval_policy", "non-interactive")
    if approval not in {"non-interactive", "never"}:
        raise ValueError("Track A requires a non-interactive approval policy")
    reject_tool_use = _boolean(options, "reject_tool_use", True)
    if not reject_tool_use:
        raise ValueError("Track A cannot disable tool-use rejection")
    auth_mode, credential_env = auth_configuration(default_credential_env=config.api_key_env)
    return _settings(
        integration_track="codex_cli_model_proxy",
        model_id=model_id,
        sandbox=sandbox,
        approval=approval,
        timeout=_number(options, "max_process_time_s", config.request_timeout_s),
        max_output=_integer(options, "max_output_bytes", 8 * 1024 * 1024),
        reject_tool_use=True,
        auth_mode=auth_mode,
        credential_env=credential_env,
        allow_proxy=_boolean(options, "allow_proxy_environment", False),
        capabilities=capabilities,
    )


def agent_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexSettings:
    _reject_unknown(options, _AGENT_OPTIONS, kind="agent")
    model = options.get("model_id")
    if not isinstance(model, str):
        raise ValueError("codex-cli-agent requires string agent option model_id")
    model_id = _model_id(model)
    sandbox = _string(options, "sandbox", "workspace-write")
    if sandbox != "workspace-write" or sandbox not in capabilities.supported_sandbox_modes:
        raise ValueError("Track B requires the supported workspace-write sandbox")
    approval = _string(options, "approval_policy", "non-interactive")
    if approval not in {"non-interactive", "never"}:
        raise ValueError("Track B requires a non-interactive approval policy")
    auth_mode, credential_env = auth_configuration()
    timeout = min(
        _number(options, "max_process_time_s", float(task_wall_time_s)),
        float(task_wall_time_s),
    )
    return _settings(
        integration_track="codex_cli_external_agent",
        model_id=model_id,
        sandbox=sandbox,
        approval=approval,
        timeout=timeout,
        max_output=_integer(options, "max_output_bytes", 8 * 1024 * 1024),
        reject_tool_use=False,
        auth_mode=auth_mode,
        credential_env=credential_env,
        allow_proxy=_boolean(options, "allow_proxy_environment", False),
        capabilities=capabilities,
    )


def _settings(
    *,
    integration_track: str,
    model_id: str,
    sandbox: str,
    approval: str,
    timeout: float,
    max_output: int,
    reject_tool_use: bool,
    auth_mode: str,
    credential_env: str | None,
    allow_proxy: bool,
    capabilities: CapabilityReport,
) -> CodexSettings:
    if timeout <= 0 or timeout > 1800:
        raise ValueError("Codex process timeout must be in (0, 1800] seconds")
    if max_output < 1024 or max_output > 16 * 1024 * 1024:
        raise ValueError("Codex output bound must be between 1 KiB and 16 MiB")
    safe = {
        "integration_track": integration_track,
        "model_id": model_id,
        "sandbox": sandbox,
        "approval": approval,
        "timeout": timeout,
        "max_output": max_output,
        "reject_tool_use": reject_tool_use,
        "auth_mode": auth_mode,
        "allow_proxy_environment": allow_proxy,
        "capability_fingerprint": capabilities.capability_fingerprint,
    }
    return CodexSettings(
        integration_track=integration_track,
        model_id=model_id,
        sandbox_policy=sandbox,
        approval_policy=approval,
        max_process_time_s=timeout,
        max_output_bytes=max_output,
        reject_tool_use=reject_tool_use,
        auth_mode_label=auth_mode,
        credential_env=credential_env,
        allow_proxy_environment=allow_proxy,
        configuration_fingerprint=stable_hash(safe),
    )


def _model_id(value: str | None) -> str:
    if value is None:
        raise ValueError("an explicit Codex model ID is required")
    clean = clean_identifier(value, label="Codex model ID")
    if clean.startswith("-"):
        raise ValueError("Codex model ID cannot begin with '-'")
    return clean


def _reject_unknown(
    values: Mapping[str, JsonValue],
    allowed: set[str],
    *,
    kind: str,
) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unsupported Codex CLI {kind} options: {', '.join(unknown)}")


def _string(values: Mapping[str, JsonValue], key: str, default: str) -> str:
    value = values.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"Codex option {key!r} must be a string")
    return clean_identifier(value, label=f"Codex option {key}", max_length=128)


def _boolean(values: Mapping[str, JsonValue], key: str, default: bool) -> bool:
    value = values.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Codex option {key!r} must be boolean")
    return value


def _number(values: Mapping[str, JsonValue], key: str, default: float) -> float:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Codex option {key!r} must be numeric")
    return float(value)


def _integer(values: Mapping[str, JsonValue], key: str, default: int) -> int:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Codex option {key!r} must be an integer")
    return value


__all__ = ["CodexSettings", "agent_settings", "model_settings"]
