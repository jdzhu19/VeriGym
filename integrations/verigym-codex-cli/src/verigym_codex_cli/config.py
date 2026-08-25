"""Strict per-run configuration for the two Codex CLI agent tracks."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from verigym.evolution.memory import validate_agent_version, validate_memory_pack
from verigym.hwe.campaign import HWE_CODEX_PROMPT_CONTRACT_ID
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID, HWE_TOOL_CONTRACT_V2_ID
from verigym.plugin_api import JsonValue
from verigym.schemas.evolution import AgentVersionManifest, MemoryPack

from .auth import AuthModeResolution
from .capabilities import CapabilityReport
from .process import (
    auth_identity_configuration,
    forwarded_proxy_environment_names,
    forwarded_runtime_proxy_environment_names,
)
from .util import clean_identifier, stable_hash

_COMMON_OPTIONS = {
    "sandbox",
    "approval_policy",
    "reasoning_effort",
    "max_process_time_s",
    "max_output_bytes",
    "allow_proxy_environment",
    "prompt_contract_id",
    "expected_cli_version",
    "expected_cli_executable_sha256",
    "expected_capability_fingerprint",
    "expected_requested_auth_mode",
    "expected_resolved_auth_mode",
    "expected_auth_semantic_id",
    "expected_execution_backend",
}
_READONLY_OPTIONS = {*_COMMON_OPTIONS, "model_id"}
_AGENT_OPTIONS = {
    *_COMMON_OPTIONS,
    "model_id",
    "agent_version_id",
    "agent_version_hash",
    "agent_version_manifest_json",
    "memory_pack",
    "collection_profile_id",
    "agent_image_lock_hash",
}
_CONFORMANCE_REASONING_EFFORT = "xhigh"
_WORKSPACE_REASONING_EFFORTS = frozenset({"xhigh", "max"})
_READONLY_PROMPT_CONTRACT = "codex_cli_readonly_verilog_task_context_v1"
_WORKSPACE_PROMPT_CONTRACT = "codex_cli_workspace_verilog_task_context_v1"
_HWE_PROMPT_CONTRACT = HWE_CODEX_PROMPT_CONTRACT_ID
ReasoningEffortSource = Literal["verigym_explicit_cli_override"]
_REASONING_EFFORT_SOURCE: ReasoningEffortSource = "verigym_explicit_cli_override"


@dataclass(frozen=True)
class CodexSettings:
    integration_track: str
    model_id: str
    requested_reasoning_effort: str
    effective_reasoning_effort: str
    reasoning_effort_source: ReasoningEffortSource
    inherited_reasoning_effort_allowed: bool
    sandbox_policy: str
    sandbox_backend: str
    sandbox_backend_source: str
    approval_policy: str
    requested_process_timeout_s: float
    task_wall_time_s: float
    effective_process_timeout_s: float
    timeout_clamped: bool
    max_process_time_s: float
    max_output_bytes: int
    tool_availability_policy: str
    tool_use_policy: str
    requested_auth_mode: str
    resolved_auth_mode: str
    auth_semantic_id: str
    auth_alias_used: bool
    credential_env: str | None
    allow_proxy_environment: bool
    forwarded_proxy_environment_names: tuple[str, ...]
    runtime_forwarded_proxy_environment_names: tuple[str, ...]
    prompt_contract_id: str
    expected_execution_backend: str | None
    agent_version_id: str | None
    agent_version_hash: str | None
    memory_pack_hash: str | None
    configuration_fingerprint: str

    @property
    def auth_mode_label(self) -> str:
        """Backward-compatible provenance label."""

        return self.requested_auth_mode

    def safe_configuration(self, capabilities: CapabilityReport) -> dict[str, JsonValue]:
        return {
            "integration_track": self.integration_track,
            "requested_model_id": self.model_id,
            "requested_reasoning_effort": self.requested_reasoning_effort,
            "effective_reasoning_effort": self.effective_reasoning_effort,
            "reasoning_effort_source": self.reasoning_effort_source,
            "inherited_reasoning_effort_allowed": self.inherited_reasoning_effort_allowed,
            "cli_version": capabilities.version_output,
            "cli_executable_sha256": capabilities.executable_sha256,
            "capability_fingerprint": capabilities.capability_fingerprint,
            "sandbox_policy": self.sandbox_policy,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_backend_source": self.sandbox_backend_source,
            "approval_policy": self.approval_policy,
            "empty_working_directory_policy": (
                self.integration_track == "codex_cli_readonly_single_turn_agent"
            ),
            "ephemeral_session_policy": True,
            "auth_mode_label": self.auth_mode_label,
            "requested_auth_mode": self.requested_auth_mode,
            "resolved_auth_mode": self.resolved_auth_mode,
            "auth_semantic_id": self.auth_semantic_id,
            "auth_alias_used": self.auth_alias_used,
            "requested_process_timeout_s": self.requested_process_timeout_s,
            "task_wall_time_s": self.task_wall_time_s,
            "effective_process_timeout_s": self.effective_process_timeout_s,
            "timeout_clamped": self.timeout_clamped,
            "max_process_time_s": self.max_process_time_s,
            "max_output_bytes": self.max_output_bytes,
            "allow_proxy_environment": self.allow_proxy_environment,
            "proxy_environment_allowed": self.allow_proxy_environment,
            "forwarded_proxy_environment_names": list(self.forwarded_proxy_environment_names),
            "runtime_forwarded_proxy_environment_names": list(
                self.runtime_forwarded_proxy_environment_names
            ),
            "synthesized_control_plane_environment_names": (
                ["NO_PROXY", "no_proxy"] if self.allow_proxy_environment else []
            ),
            "mandatory_loopback_bypass_present": True,
            "prompt_contract_id": self.prompt_contract_id,
            "expected_execution_backend": self.expected_execution_backend,
            "agent_version_id": self.agent_version_id,
            "agent_version_hash": self.agent_version_hash,
            "memory_pack_hash": self.memory_pack_hash,
            "execution_surface": "codex_cli",
            "interaction_class": (
                "cli_agent_single_turn_readonly"
                if self.integration_track == "codex_cli_readonly_single_turn_agent"
                else "cli_agent_workspace_writing"
            ),
            "model_client_kind": "cli_agent_mediated",
            "agent_harness_kind": "codex_cli",
            "tool_availability_policy": self.tool_availability_policy,
            "tool_use_policy": self.tool_use_policy,
            "chat_eval_compatible": False,
            "pure_api_model_eval": False,
            "direct_api_benchmark": False,
        }


def readonly_agent_settings(
    options: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    *,
    task_wall_time_s: int,
) -> CodexSettings:
    _reject_unknown(options, _READONLY_OPTIONS, kind="read-only agent")
    model = options.get("model_id")
    if not isinstance(model, str):
        raise ValueError("codex-cli-readonly-agent requires string agent option model_id")
    model_id = _model_id(model)
    sandbox = _string(options, "sandbox", "most-restrictive-supported")
    if sandbox == "most-restrictive-supported":
        sandbox = "read-only"
    if sandbox != "read-only" or sandbox not in capabilities.supported_sandbox_modes:
        raise ValueError("read-only Codex CLI agent requires the supported read-only sandbox")
    approval = _string(options, "approval_policy", "non-interactive")
    if approval not in {"non-interactive", "never"}:
        raise ValueError("read-only Codex CLI agent requires non-interactive approval")
    auth_resolution, credential_env = auth_identity_configuration()
    _validate_identity_expectations(
        options,
        capabilities,
        auth_resolution,
        prompt_contract_id=_READONLY_PROMPT_CONTRACT,
    )
    requested_timeout = _number(
        options,
        "max_process_time_s",
        float(task_wall_time_s),
    )
    task_wall_time = float(task_wall_time_s)
    return _settings(
        integration_track="codex_cli_readonly_single_turn_agent",
        model_id=model_id,
        reasoning_effort=_reasoning_effort(
            options,
            allowed=frozenset({_CONFORMANCE_REASONING_EFFORT}),
            integration="read-only conformance",
        ),
        sandbox=sandbox,
        sandbox_backend="codex_cli_default",
        sandbox_backend_source="codex_cli_default",
        approval=approval,
        requested_timeout=requested_timeout,
        task_wall_time=task_wall_time,
        effective_timeout=min(requested_timeout, task_wall_time),
        max_output=_integer(options, "max_output_bytes", 8 * 1024 * 1024),
        tool_availability_policy="codex_cli_builtin_tools_readonly_sandboxed",
        tool_use_policy="typed_readonly_empty_workdir_v1",
        auth_resolution=auth_resolution,
        credential_env=credential_env,
        allow_proxy=_boolean(options, "allow_proxy_environment", False),
        prompt_contract_id=_READONLY_PROMPT_CONTRACT,
        expected_execution_backend=_optional_string(
            options,
            "expected_execution_backend",
        ),
        agent_version_id=None,
        agent_version_hash=None,
        memory_pack_hash=None,
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
    collection_profile = _optional_string(options, "collection_profile_id")
    hwe_collection = collection_profile is not None
    if hwe_collection and collection_profile != HWE_COLLECTION_PROFILE_V2_ID:
        raise ValueError("Codex HWE collection profile is unsupported")
    image_lock_hash = _optional_string(options, "agent_image_lock_hash")
    if hwe_collection:
        if image_lock_hash is None or not re.fullmatch(r"[0-9a-f]{64}", image_lock_hash):
            raise ValueError("Codex HWE collection requires an agent-image lock hash")
        if model_id != "gpt-5.4":
            raise ValueError("Codex HWE collection freezes GPT-5.4")
    elif image_lock_hash is not None:
        raise ValueError("agent-image lock hash is HWE-only")
    sandbox = _string(options, "sandbox", "workspace-write")
    if sandbox != "workspace-write" or sandbox not in capabilities.supported_sandbox_modes:
        raise ValueError("Track B requires the supported workspace-write sandbox")
    approval = _string(options, "approval_policy", "non-interactive")
    if approval not in {"non-interactive", "never"}:
        raise ValueError("Track B requires a non-interactive approval policy")
    auth_resolution, credential_env = auth_identity_configuration()
    _validate_identity_expectations(
        options,
        capabilities,
        auth_resolution,
        prompt_contract_id=_HWE_PROMPT_CONTRACT if hwe_collection else _WORKSPACE_PROMPT_CONTRACT,
    )
    requested_timeout = _number(
        options,
        "max_process_time_s",
        float(task_wall_time_s),
    )
    task_wall_time = float(task_wall_time_s)
    effort = _reasoning_effort(
        options,
        allowed=frozenset({"xhigh"}) if hwe_collection else _WORKSPACE_REASONING_EFFORTS,
        integration="HWE native-shell" if hwe_collection else "workspace agent",
    )
    agent_version_id, agent_version_hash, memory_pack = _versioned_context(
        options,
        model_id=model_id,
        reasoning_effort=effort,
        auth_semantic_id=auth_resolution.auth_semantic_id,
    )
    return _settings(
        integration_track=(
            "codex_cli_hwe_native_shell" if hwe_collection else "codex_cli_external_agent"
        ),
        model_id=model_id,
        reasoning_effort=effort,
        sandbox=sandbox,
        sandbox_backend="codex_cli_default",
        sandbox_backend_source="codex_cli_default",
        approval=approval,
        requested_timeout=requested_timeout,
        task_wall_time=task_wall_time,
        effective_timeout=min(requested_timeout, task_wall_time),
        max_output=_integer(
            options,
            "max_output_bytes",
            32 * 1024 * 1024 if hwe_collection else 8 * 1024 * 1024,
        ),
        tool_availability_policy=(
            HWE_TOOL_CONTRACT_V2_ID if hwe_collection else "codex_cli_visible_workspace_tools"
        ),
        tool_use_policy=(
            HWE_COLLECTION_PROFILE_V2_ID if hwe_collection else "visible_task_workspace_policy_v2"
        ),
        auth_resolution=auth_resolution,
        credential_env=credential_env,
        allow_proxy=_boolean(options, "allow_proxy_environment", False),
        prompt_contract_id=_HWE_PROMPT_CONTRACT if hwe_collection else _WORKSPACE_PROMPT_CONTRACT,
        expected_execution_backend=_optional_string(
            options,
            "expected_execution_backend",
        ),
        agent_version_id=agent_version_id,
        agent_version_hash=agent_version_hash,
        memory_pack_hash=memory_pack.content_hash if memory_pack is not None else None,
        capabilities=capabilities,
    )


def settings_for_execution_backend(
    settings: CodexSettings,
    execution_backend: str,
) -> CodexSettings:
    """Bind Docker delegation without changing the owner-facing auth semantics."""

    if (
        settings.expected_execution_backend is not None
        and settings.expected_execution_backend != execution_backend
    ):
        raise ValueError("external-agent execution backend differs from the frozen expectation")
    if execution_backend == "host_local_trusted":
        return settings
    if execution_backend != "docker_outer_runtime_delegated":
        raise ValueError(f"unsupported external-agent execution backend: {execution_backend}")
    runtime_tool_policy = (
        "hwe_standard_v2"
        if settings.integration_track == "codex_cli_hwe_native_shell"
        else "docker_runtime_isolated_workspace_policy_v3"
    )
    fingerprint = stable_hash(
        {
            "base_configuration_fingerprint": settings.configuration_fingerprint,
            "execution_backend": execution_backend,
            "sandbox_policy": "outer_runtime_delegated",
            "sandbox_backend": "verigym_docker_outer_runtime",
            "sandbox_backend_source": "verigym_runtime_effective_controls",
            "tool_use_policy": runtime_tool_policy,
        }
    )
    return replace(
        settings,
        sandbox_policy="outer_runtime_delegated",
        sandbox_backend="verigym_docker_outer_runtime",
        sandbox_backend_source="verigym_runtime_effective_controls",
        tool_use_policy=runtime_tool_policy,
        configuration_fingerprint=fingerprint,
    )


def _settings(
    *,
    integration_track: str,
    model_id: str,
    reasoning_effort: str,
    sandbox: str,
    sandbox_backend: str,
    sandbox_backend_source: str,
    approval: str,
    requested_timeout: float,
    task_wall_time: float,
    effective_timeout: float,
    max_output: int,
    tool_availability_policy: str,
    tool_use_policy: str,
    auth_resolution: AuthModeResolution,
    credential_env: str | None,
    allow_proxy: bool,
    prompt_contract_id: str,
    expected_execution_backend: str | None,
    agent_version_id: str | None,
    agent_version_hash: str | None,
    memory_pack_hash: str | None,
    capabilities: CapabilityReport,
) -> CodexSettings:
    max_timeout = 3600 if integration_track == "codex_cli_hwe_native_shell" else 1800
    if requested_timeout <= 0 or requested_timeout > max_timeout:
        raise ValueError(f"Codex process timeout must be in (0, {max_timeout}] seconds")
    if task_wall_time <= 0 or effective_timeout <= 0:
        raise ValueError("Codex task wall-time budget must be positive")
    max_output_limit = (
        32 * 1024 * 1024 if integration_track == "codex_cli_hwe_native_shell" else 16 * 1024 * 1024
    )
    if max_output < 1024 or max_output > max_output_limit:
        raise ValueError(
            f"Codex output bound must be between 1 KiB and {max_output_limit // (1024 * 1024)} MiB"
        )
    forwarded_proxy_names = forwarded_proxy_environment_names(allow_proxy)
    runtime_forwarded_proxy_names = forwarded_runtime_proxy_environment_names(allow_proxy)
    timeout_clamped = effective_timeout != requested_timeout
    safe = {
        "integration_track": integration_track,
        "model_id": model_id,
        "requested_reasoning_effort": reasoning_effort,
        "effective_reasoning_effort": reasoning_effort,
        "reasoning_effort_source": _REASONING_EFFORT_SOURCE,
        "inherited_reasoning_effort_allowed": False,
        "sandbox": sandbox,
        "sandbox_backend": sandbox_backend,
        "sandbox_backend_source": sandbox_backend_source,
        "approval": approval,
        "requested_process_timeout_s": requested_timeout,
        "task_wall_time_s": task_wall_time,
        "effective_process_timeout_s": effective_timeout,
        "timeout_clamped": timeout_clamped,
        "max_output": max_output,
        "tool_availability_policy": tool_availability_policy,
        "tool_use_policy": tool_use_policy,
        "requested_auth_mode": auth_resolution.requested_auth_mode,
        "resolved_auth_mode": auth_resolution.resolved_auth_mode,
        "auth_semantic_id": auth_resolution.auth_semantic_id,
        "auth_alias_used": auth_resolution.auth_alias_used,
        "allow_proxy_environment": allow_proxy,
        "proxy_environment_allowed": allow_proxy,
        "forwarded_proxy_environment_names": list(forwarded_proxy_names),
        "runtime_forwarded_proxy_environment_names": list(runtime_forwarded_proxy_names),
        "synthesized_control_plane_environment_names": (
            ["NO_PROXY", "no_proxy"] if allow_proxy else []
        ),
        "mandatory_loopback_bypass_present": True,
        "prompt_contract_id": prompt_contract_id,
        "expected_execution_backend": expected_execution_backend,
        "agent_version_id": agent_version_id,
        "agent_version_hash": agent_version_hash,
        "memory_pack_hash": memory_pack_hash,
        "capability_fingerprint": capabilities.capability_fingerprint,
    }
    return CodexSettings(
        integration_track=integration_track,
        model_id=model_id,
        requested_reasoning_effort=reasoning_effort,
        effective_reasoning_effort=reasoning_effort,
        reasoning_effort_source=_REASONING_EFFORT_SOURCE,
        inherited_reasoning_effort_allowed=False,
        sandbox_policy=sandbox,
        sandbox_backend=sandbox_backend,
        sandbox_backend_source=sandbox_backend_source,
        approval_policy=approval,
        requested_process_timeout_s=requested_timeout,
        task_wall_time_s=task_wall_time,
        effective_process_timeout_s=effective_timeout,
        timeout_clamped=timeout_clamped,
        max_process_time_s=effective_timeout,
        max_output_bytes=max_output,
        tool_availability_policy=tool_availability_policy,
        tool_use_policy=tool_use_policy,
        requested_auth_mode=auth_resolution.requested_auth_mode,
        resolved_auth_mode=auth_resolution.resolved_auth_mode,
        auth_semantic_id=auth_resolution.auth_semantic_id,
        auth_alias_used=auth_resolution.auth_alias_used,
        credential_env=credential_env,
        allow_proxy_environment=allow_proxy,
        forwarded_proxy_environment_names=forwarded_proxy_names,
        runtime_forwarded_proxy_environment_names=runtime_forwarded_proxy_names,
        prompt_contract_id=prompt_contract_id,
        expected_execution_backend=expected_execution_backend,
        agent_version_id=agent_version_id,
        agent_version_hash=agent_version_hash,
        memory_pack_hash=memory_pack_hash,
        configuration_fingerprint=stable_hash(safe),
    )


def _versioned_context(
    options: Mapping[str, JsonValue],
    *,
    model_id: str,
    reasoning_effort: str,
    auth_semantic_id: str,
) -> tuple[str | None, str | None, MemoryPack | None]:
    version_id = _optional_string(options, "agent_version_id")
    version_hash = _optional_string(options, "agent_version_hash")
    raw_manifest = options.get("agent_version_manifest_json")
    raw_memory = options.get("memory_pack")
    if (version_id is None) != (version_hash is None):
        raise ValueError("agent_version_id and agent_version_hash must be supplied together")
    if version_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", version_hash):
        raise ValueError("agent_version_hash must be lowercase SHA-256")
    if version_id is None:
        if raw_manifest is not None or raw_memory is not None:
            raise ValueError("versioned context requires a frozen agent-version identity")
        return None, None, None
    if not isinstance(raw_manifest, str):
        raise ValueError("versioned context requires agent_version_manifest_json")
    try:
        payload = json.loads(raw_manifest, object_pairs_hook=_unique_object)
        manifest = validate_agent_version(AgentVersionManifest.model_validate(payload))
    except Exception as exc:
        raise ValueError(f"invalid agent-version manifest: {exc}") from exc
    if (
        manifest.agent_version_id != version_id
        or manifest.version_hash != version_hash
        or manifest.base_agent_id != "codex-cli-agent"
        or manifest.model_id != model_id
        or manifest.reasoning_effort != reasoning_effort
        or manifest.auth_semantic_id != auth_semantic_id
        or not manifest.executable_in_m10b
        or manifest.model_weights_modified
    ):
        raise ValueError("agent-version manifest differs from effective Codex settings")
    if manifest.update_type == "none":
        if raw_memory is not None or manifest.memory_pack_hash is not None:
            raise ValueError("base agent version must remain memory-free")
        return version_id, version_hash, None
    if manifest.update_type != "context_memory" or raw_memory is None:
        raise ValueError("M10B evolved versions require a frozen context memory pack")
    try:
        memory = validate_memory_pack(MemoryPack.model_validate(raw_memory))
    except Exception as exc:
        raise ValueError(f"invalid versioned memory pack: {exc}") from exc
    if memory.content_hash != manifest.memory_pack_hash:
        raise ValueError("memory pack does not match the frozen agent-version manifest")
    return version_id, version_hash, memory


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("agent-version manifest contains a duplicate JSON key")
        result[key] = value
    return result


def _model_id(value: str | None) -> str:
    if value is None:
        raise ValueError("an explicit Codex model ID is required")
    clean = clean_identifier(value, label="Codex model ID")
    if clean.startswith("-"):
        raise ValueError("Codex model ID cannot begin with '-'")
    return clean


def _reasoning_effort(
    values: Mapping[str, JsonValue],
    *,
    allowed: frozenset[str],
    integration: str,
) -> str:
    effort = _string(
        values,
        "reasoning_effort",
        _CONFORMANCE_REASONING_EFFORT,
    )
    if effort not in allowed:
        expected = ", ".join(repr(value) for value in sorted(allowed))
        raise ValueError(f"Codex CLI {integration} requires reasoning_effort in {{{expected}}}")
    return effort


def _validate_identity_expectations(
    values: Mapping[str, JsonValue],
    capabilities: CapabilityReport,
    auth_resolution: AuthModeResolution,
    *,
    prompt_contract_id: str,
) -> None:
    expectations = {
        "expected_cli_version": capabilities.version_output,
        "expected_cli_executable_sha256": capabilities.executable_sha256,
        "expected_capability_fingerprint": capabilities.capability_fingerprint,
        "expected_requested_auth_mode": auth_resolution.requested_auth_mode,
        "expected_resolved_auth_mode": auth_resolution.resolved_auth_mode,
        "expected_auth_semantic_id": auth_resolution.auth_semantic_id,
        "prompt_contract_id": prompt_contract_id,
    }
    for key, observed in expectations.items():
        expected = _optional_string(values, key)
        if expected is not None and expected != observed:
            raise ValueError(f"Codex identity expectation differs for {key}")


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


def _optional_string(values: Mapping[str, JsonValue], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
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


__all__ = [
    "CodexSettings",
    "agent_settings",
    "readonly_agent_settings",
    "settings_for_execution_backend",
]
