"""Provider-independent model requests, responses, usage, and errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from verigym.schemas.action_protocol import ProviderNativeToolCall
from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ModelDescriptor
from verigym.schemas.options import JsonValue, validate_plugin_options


class ModelFinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALL = "tool_call"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


class ModelErrorCategory(StrEnum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    TRANSPORT = "transport"
    RATE_LIMIT = "rate_limit"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROTOCOL_ERROR = "protocol_error"
    MALFORMED_RESPONSE = "malformed_response"
    EXHAUSTED = "exhausted"
    INTERNAL = "internal"


class ModelMessage(StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class NormalizedModelUsage(StrictModel):
    schema_version: str = SCHEMA_VERSION
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def fill_total_when_known(self) -> NormalizedModelUsage:
        if (
            self.total_tokens is None
            and self.input_tokens is not None
            and self.output_tokens is not None
        ):
            self.total_tokens = self.input_tokens + self.output_tokens
        return self


class ModelClientErrorInfo(StrictModel):
    schema_version: str = SCHEMA_VERSION
    category: ModelErrorCategory
    message: str
    retryable: bool = False
    provider_code: str | None = None


class ModelRequest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    request_id: str
    messages: list[ModelMessage] = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    stop: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(StrictModel):
    schema_version: str = SCHEMA_VERSION
    request_id: str
    response_id: str | None = None
    provider_model_id: str | None = None
    system_fingerprint: str | None = None
    text: str
    native_tool_calls: list[ProviderNativeToolCall] = Field(default_factory=list)
    finish_reason: ModelFinishReason = ModelFinishReason.UNKNOWN
    usage: NormalizedModelUsage = Field(default_factory=NormalizedModelUsage)
    latency_s: float = Field(default=0.0, ge=0.0)
    cost: float | None = Field(default=None, ge=0.0)
    cost_currency: str | None = Field(default=None, min_length=1, max_length=64)
    cost_unit: str | None = Field(default=None, min_length=1, max_length=64)
    error: ModelClientErrorInfo | None = None

    @model_validator(mode="after")
    def validate_cost_identity(self) -> ModelResponse:
        if self.cost_currency is not None and self.cost_unit is not None:
            raise ValueError("model response cost cannot declare currency and provider unit")
        if self.cost is None and (self.cost_currency is not None or self.cost_unit is not None):
            raise ValueError("model response cost identity requires a cost value")
        return self


class ModelRunConfig(StrictModel):
    """Secret-free per-run options understood by compatible model clients."""

    base_url: str | None = None
    base_url_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    provider_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    model_id: str | None = None
    api_key_env: str | None = None
    connect_timeout_s: float = Field(default=10.0, gt=0.0)
    read_timeout_s: float = Field(default=60.0, gt=0.0)
    request_timeout_s: float = Field(default=90.0, gt=0.0)
    max_response_bytes: int = Field(default=4 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    require_exact_model_id: bool = False
    temperature: float = Field(default=0.0, ge=0.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    sample_index: int | None = Field(default=None, ge=0)
    client_options: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("client_options", mode="before")
    @classmethod
    def validate_client_options(cls, value: object) -> dict[str, JsonValue]:
        return validate_plugin_options(value)

    @model_validator(mode="after")
    def validate_endpoint_source(self) -> ModelRunConfig:
        if self.base_url is not None and self.base_url_env is not None:
            raise ValueError("model base URL must use either a literal or an environment source")
        return self


class GenerationParameters(StrictModel):
    schema_version: str = SCHEMA_VERSION
    temperature: float = Field(default=0.0, ge=0.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_output_tokens: int | None = Field(default=None, ge=1)


class ProviderRequestIdentity(StrictModel):
    """Secret-free identity of one credential-bearing remote request."""

    schema_version: str = SCHEMA_VERSION
    provider_id: str
    protocol: Literal["openai_compatible"]
    requested_model_id: str
    endpoint_origin: str
    normalized_base_url: str
    base_url_hash: str
    request_parameters_hash: str
    prompt_payload_hash: str
    prompt_policy_hash: str | None = None
    agent_configuration_hash: str | None = None
    action_protocol_hash: str | None = None
    connect_timeout_s: float = Field(gt=0.0)
    read_timeout_s: float = Field(gt=0.0)
    request_timeout_s: float = Field(gt=0.0)
    max_response_bytes: int = Field(ge=1024)
    authentication_mode: Literal["bearer_env", "bearer_explicit_in_memory"]
    credential_env_name: str | None = None
    credential_persisted: Literal[False] = False
    credential_hashed: Literal[False] = False


class ModelCallIdentity(StrictModel):
    """Requested versus observed identity for one model call."""

    schema_version: str = SCHEMA_VERSION
    request_id: str
    adapter_name: str
    adapter_version: str | None = None
    requested_model_id: str
    observed_provider_model_id: str | None = None
    system_fingerprint: str | None = None
    endpoint_origin: str | None = None
    generation: GenerationParameters
    identity_confidence: Literal["exact", "provider_observed", "requested_only", "unknown"]
    reproducibility_scope: Literal[
        "exact_offline_fixture",
        "mutable_remote_observation",
        "requested_remote_identity",
        "unknown",
    ]
    mutable_remote_service: bool
    provider_request: ProviderRequestIdentity | None = None
    safe_provider_request_id: str | None = None
    latency_s: float | None = Field(default=None, ge=0.0)
    usage: NormalizedModelUsage | None = None
    usage_missing: bool | None = None
    cost: float | None = Field(default=None, ge=0.0)
    cost_currency: str | None = None
    cost_unit: str | None = None


__all__ = [
    "ModelCallIdentity",
    "ModelClientErrorInfo",
    "ModelDescriptor",
    "ModelErrorCategory",
    "ModelFinishReason",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelRunConfig",
    "NormalizedModelUsage",
    "GenerationParameters",
    "ProviderRequestIdentity",
]
