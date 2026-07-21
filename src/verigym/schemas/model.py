"""Provider-independent model requests, responses, usage, and errors."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from verigym.schemas.base import SCHEMA_VERSION, StrictModel
from verigym.schemas.common import ModelDescriptor


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
    TRANSPORT = "transport"
    RATE_LIMIT = "rate_limit"
    INVALID_RESPONSE = "invalid_response"
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
    text: str
    finish_reason: ModelFinishReason = ModelFinishReason.UNKNOWN
    usage: NormalizedModelUsage = Field(default_factory=NormalizedModelUsage)
    latency_s: float = Field(default=0.0, ge=0.0)
    error: ModelClientErrorInfo | None = None


class ModelRunConfig(StrictModel):
    """Secret-free per-run options understood by compatible model clients."""

    base_url: str | None = None
    model_id: str | None = None
    api_key_env: str | None = None
    connect_timeout_s: float = Field(default=10.0, gt=0.0)
    read_timeout_s: float = Field(default=60.0, gt=0.0)
    request_timeout_s: float = Field(default=90.0, gt=0.0)
    temperature: float = Field(default=0.0, ge=0.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    sample_index: int | None = Field(default=None, ge=0)


class GenerationParameters(StrictModel):
    schema_version: str = SCHEMA_VERSION
    temperature: float = Field(default=0.0, ge=0.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_output_tokens: int | None = Field(default=None, ge=1)


__all__ = [
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
]
