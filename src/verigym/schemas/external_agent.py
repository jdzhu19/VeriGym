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
    executable_name: str
    executable_sha256: str
    executable_version: str
    capability_fingerprint: str
    configuration_fingerprint: str
    invocation_count: int = Field(ge=0)
    integration_track: Literal["codex_cli_external_agent"] | None = None
    auth_mode_label: str | None = None
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
