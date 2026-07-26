"""Persistent identity and accounting for externally executed coding agents."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ExternalAgentCallIdentity(StrictModel):
    schema_version: str = SCHEMA_VERSION
    adapter_name: str
    adapter_version: str
    harness_name: str
    requested_model_id: str | None
    observed_model_id: str | None
    requested_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=32)
    effective_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=32)
    reasoning_effort_source: Literal["verigym_explicit_cli_override"] | None = None
    inherited_reasoning_effort_allowed: bool | None = None
    executable_name: str
    executable_sha256: str
    executable_version: str
    capability_fingerprint: str
    configuration_fingerprint: str
    invocation_count: int = Field(ge=0)
    integration_track: (
        Literal[
            "codex_cli_readonly_single_turn_agent",
            "codex_cli_external_agent",
        ]
        | None
    ) = None
    execution_surface: Literal["codex_cli"] | None = None
    interaction_class: (
        Literal[
            "cli_agent_single_turn_readonly",
            "cli_agent_workspace_writing",
        ]
        | None
    ) = None
    harness_id: str | None = Field(default=None, min_length=1, max_length=128)
    model_client_kind: Literal["cli_agent_mediated"] | None = None
    agent_harness_kind: Literal["codex_cli"] | None = None
    tool_availability_policy: str | None = Field(default=None, min_length=1, max_length=128)
    tool_use_policy: str | None = Field(default=None, min_length=1, max_length=128)
    tool_event_count: int | None = Field(default=None, ge=0)
    side_effecting_tool_event_count: int | None = Field(default=None, ge=0)
    read_only_tool_event_count: int | None = Field(default=None, ge=0)
    external_network_tool_event_count: int | None = Field(default=None, ge=0)
    mcp_tool_event_count: int | None = Field(default=None, ge=0)
    workspace_write_count: int | None = Field(default=None, ge=0)
    chat_eval_compatible: bool | None = None
    pure_api_model_eval: bool | None = None
    direct_api_benchmark: bool | None = None
    auth_mode_label: str | None = None
    requested_auth_mode: str | None = Field(default=None, min_length=1, max_length=64)
    resolved_auth_mode: str | None = Field(default=None, min_length=1, max_length=64)
    auth_semantic_id: str | None = Field(default=None, min_length=1, max_length=128)
    auth_alias_used: bool | None = None
    sandbox_policy: str | None = None
    approval_policy: str | None = None
    identity_confidence: Literal["observed", "requested_only", "unknown"]
    reproducibility_scope: Literal[
        "site_specific_cli",
        "mutable_remote_observation",
        "unknown",
    ]

    @field_validator(
        "executable_sha256",
        "capability_fingerprint",
        "configuration_fingerprint",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("external-agent identity hashes must be lowercase SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_authentication_identity(self) -> ExternalAgentCallIdentity:
        values = (
            self.requested_auth_mode,
            self.resolved_auth_mode,
            self.auth_semantic_id,
            self.auth_alias_used,
        )
        if any(value is not None for value in values) and any(value is None for value in values):
            raise ValueError(
                "external-agent authentication identity fields must be recorded together"
            )
        if (
            self.requested_auth_mode is not None
            and self.auth_mode_label is not None
            and self.requested_auth_mode != self.auth_mode_label
        ):
            raise ValueError("auth_mode_label must preserve the requested authentication mode")
        reasoning_values = (
            self.requested_reasoning_effort,
            self.effective_reasoning_effort,
            self.reasoning_effort_source,
            self.inherited_reasoning_effort_allowed,
        )
        if any(value is not None for value in reasoning_values) and any(
            value is None for value in reasoning_values
        ):
            raise ValueError(
                "external-agent reasoning-effort identity fields must be recorded together"
            )
        if (
            self.requested_reasoning_effort is not None
            and self.requested_reasoning_effort != self.effective_reasoning_effort
        ):
            raise ValueError("external-agent requested and effective reasoning effort must match")
        if self.inherited_reasoning_effort_allowed is True:
            raise ValueError("external-agent reasoning effort cannot permit inherited values")
        semantic_values = (
            self.execution_surface,
            self.interaction_class,
            self.harness_id,
            self.model_client_kind,
            self.agent_harness_kind,
            self.tool_availability_policy,
            self.tool_use_policy,
            self.tool_event_count,
            self.side_effecting_tool_event_count,
            self.read_only_tool_event_count,
            self.external_network_tool_event_count,
            self.mcp_tool_event_count,
            self.workspace_write_count,
            self.chat_eval_compatible,
            self.pure_api_model_eval,
            self.direct_api_benchmark,
        )
        if any(value is not None for value in semantic_values) and any(
            value is None for value in semantic_values
        ):
            raise ValueError("external-agent semantic identity fields must be recorded together")
        if self.execution_surface is not None:
            assert self.tool_event_count is not None
            assert self.side_effecting_tool_event_count is not None
            assert self.read_only_tool_event_count is not None
            assert self.external_network_tool_event_count is not None
            assert self.mcp_tool_event_count is not None
            if (
                self.side_effecting_tool_event_count
                + self.read_only_tool_event_count
                + self.external_network_tool_event_count
                + self.mcp_tool_event_count
                > self.tool_event_count
            ):
                raise ValueError("external-agent classified tool counts exceed total tool events")
            if (
                self.chat_eval_compatible is not False
                or self.pure_api_model_eval is not False
                or self.direct_api_benchmark is not False
            ):
                raise ValueError(
                    "Codex CLI agent identities cannot claim direct or ChatEval status"
                )
        return self


class ExternalAgentAccounting(StrictModel):
    schema_version: str = SCHEMA_VERSION
    process_wall_time_s: float = Field(ge=0.0)
    cli_event_count: int = Field(ge=0)
    external_tool_call_count: int | None = Field(default=None, ge=0)
    external_command_count: int | None = Field(default=None, ge=0)
    external_file_read_count: int | None = Field(default=None, ge=0)
    external_file_write_count: int | None = Field(default=None, ge=0)
    external_patch_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0.0)
    currency: str | None = None

    @model_validator(mode="after")
    def validate_totals_and_cost(self) -> ExternalAgentAccounting:
        if (
            self.total_tokens is None
            and self.input_tokens is not None
            and self.output_tokens is not None
        ):
            self.total_tokens = self.input_tokens + self.output_tokens
        if self.currency is not None and self.cost is None:
            raise ValueError("external-agent currency requires a known cost")
        return self


__all__ = ["ExternalAgentAccounting", "ExternalAgentCallIdentity"]
