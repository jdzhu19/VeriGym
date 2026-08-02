"""Strict transport-injected OpenAI-compatible chat-completions client."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from verigym.core.hashing import content_hash
from verigym.models.base import ModelClient, ModelClientError
from verigym.schemas.action_protocol import ProviderNativeToolCall
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import ModelDescriptor
from verigym.schemas.model import (
    ModelClientErrorInfo,
    ModelErrorCategory,
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelRunConfig,
    NormalizedModelUsage,
    ProviderRequestIdentity,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class _ProtocolViolation(ValueError):
    pass


class OpenAICompatibleTransport(Protocol):
    def create_chat_completion(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        connect_timeout_s: float,
        read_timeout_s: float,
        request_timeout_s: float,
        max_response_bytes: int,
    ) -> Mapping[str, Any]: ...


class HttpxOpenAITransport:
    """Bound and parse remote bytes without recording response bodies on errors."""

    def create_chat_completion(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        connect_timeout_s: float,
        read_timeout_s: float,
        request_timeout_s: float,
        max_response_bytes: int,
    ) -> Mapping[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - optional dependency.
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.CONFIGURATION,
                    message="OpenAI-compatible HTTP support requires the optional 'httpx' package",
                )
            ) from exc
        timeout = httpx.Timeout(
            request_timeout_s,
            connect=connect_timeout_s,
            read=read_timeout_s,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST", url, headers=dict(headers), json=dict(payload)
                ) as response:
                    status = response.status_code
                    if status >= 400:
                        raise _status_error(status)
                    length = response.headers.get("content-length")
                    if length is not None:
                        try:
                            declared = int(length)
                        except ValueError as exc:
                            raise ModelClientError(
                                ModelClientErrorInfo(
                                    category=ModelErrorCategory.PROTOCOL_ERROR,
                                    message=(
                                        "OpenAI-compatible endpoint returned invalid Content-Length"
                                    ),
                                )
                            ) from exc
                        if declared > max_response_bytes:
                            raise _response_limit_error()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > max_response_bytes:
                            raise _response_limit_error()
                        body.extend(chunk)
            try:
                data = json.loads(bytes(body))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ModelClientError(
                    ModelClientErrorInfo(
                        category=ModelErrorCategory.MALFORMED_RESPONSE,
                        message="OpenAI-compatible endpoint returned malformed JSON",
                    )
                ) from exc
        except ModelClientError:
            raise
        except httpx.TimeoutException as exc:
            code = (
                "connect_timeout" if isinstance(exc, httpx.ConnectTimeout) else "response_timeout"
            )
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.TIMEOUT,
                    message="OpenAI-compatible request timed out",
                    retryable=True,
                    provider_code=code,
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.PROVIDER_UNAVAILABLE,
                    message=f"OpenAI-compatible transport failed: {type(exc).__name__}",
                    retryable=True,
                )
            ) from exc
        if not isinstance(data, Mapping):
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.MALFORMED_RESPONSE,
                    message="OpenAI-compatible endpoint returned a non-object JSON response",
                )
            )
        return cast(Mapping[str, Any], data)


class OpenAICompatibleModelClient(ModelClient):
    """Provider-neutral normalized client with secret-free request identity."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        base_url_env: str | None = None,
        client_id: str = "openai-compatible",
        provider_id: str = "openai-compatible",
        model_id: str | None = None,
        api_key: str | None = None,
        api_key_env: str | None = None,
        connect_timeout_s: float = 10.0,
        read_timeout_s: float = 60.0,
        request_timeout_s: float = 90.0,
        max_response_bytes: int = 4 * 1024 * 1024,
        require_exact_model_id: bool = False,
        transport: OpenAICompatibleTransport | None = None,
    ) -> None:
        if not _SAFE_NAME.fullmatch(client_id):
            raise _configuration_error("client ID must be a safe bounded identifier")
        if not _SAFE_NAME.fullmatch(provider_id):
            raise _configuration_error("provider ID must be a safe bounded identifier")
        if base_url_env is not None and not _SAFE_NAME.fullmatch(base_url_env):
            raise _configuration_error("base URL environment name is invalid")
        if api_key_env is not None and not _SAFE_NAME.fullmatch(api_key_env):
            raise _configuration_error("credential environment name is invalid")
        environment_base_url = os.environ.get(base_url_env) if base_url_env else None
        if base_url is not None and environment_base_url and base_url != environment_base_url:
            raise _configuration_error("resolved base URL differs from its environment source")
        resolved_base_url = base_url or environment_base_url
        self._base_url = self._safe_base_url(resolved_base_url) if resolved_base_url else None
        self._base_url_env = base_url_env
        self._client_id = client_id
        self._provider_id = provider_id
        self._model_id = model_id
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._request_timeout_s = request_timeout_s
        self._max_response_bytes = max_response_bytes
        self._require_exact_model_id = require_exact_model_id
        self._transport = transport or HttpxOpenAITransport()
        safe_configuration = {
            "base_url": self._base_url,
            "base_url_source": base_url_env or ("literal" if self._base_url else None),
            "provider_id": provider_id,
            "client_id": client_id,
            "model_id": model_id,
            "authentication_mode": "bearer_explicit_in_memory" if api_key else "bearer_env",
            "credential_env_name": None if api_key else api_key_env,
            "credential_persisted": False,
            "credential_hashed": False,
            "connect_timeout_s": connect_timeout_s,
            "read_timeout_s": read_timeout_s,
            "request_timeout_s": request_timeout_s,
            "max_response_bytes": max_response_bytes,
            "require_exact_model_id": require_exact_model_id,
            "protocol": "openai_compatible",
        }
        self.descriptor = ModelDescriptor(
            schema_version=SCHEMA_VERSION,
            name=client_id,
            version="0.2.0",
            api_version=PLUGIN_API_VERSION,
            provider=provider_id,
            capabilities=[
                "text",
                "chat_completions",
                "optional_network",
                "bounded_response",
                "safe_request_identity",
            ],
            model_id=model_id or "unconfigured",
            client_name="openai-compatible",
            client_version="0.2.0",
            api_compatibility="openai.chat.completions",
            configuration_fingerprint=content_hash(safe_configuration),
            configuration=safe_configuration,
        )

    def clone_for_run(
        self, configuration: ModelRunConfig | None = None
    ) -> OpenAICompatibleModelClient:
        config = configuration or ModelRunConfig()
        base_url_env = config.base_url_env or self._base_url_env
        base_url = config.base_url or self._base_url
        if base_url is None and base_url_env is not None:
            value = os.environ.get(base_url_env)
            base_url = value if value else None
        return OpenAICompatibleModelClient(
            base_url=base_url,
            base_url_env=base_url_env,
            client_id=self._client_id,
            provider_id=config.provider_id or self._provider_id,
            model_id=config.model_id or self._model_id,
            api_key=self._api_key,
            api_key_env=config.api_key_env or self._api_key_env,
            connect_timeout_s=config.connect_timeout_s,
            read_timeout_s=config.read_timeout_s,
            request_timeout_s=config.request_timeout_s,
            max_response_bytes=config.max_response_bytes,
            require_exact_model_id=config.require_exact_model_id,
            transport=self._transport,
        )

    def request_identity(self, request: ModelRequest) -> ProviderRequestIdentity | None:
        if self._base_url is None or self._model_id is None:
            return None
        parsed = urlsplit(self._base_url)
        metadata = request.metadata
        return ProviderRequestIdentity(
            provider_id=self._provider_id,
            protocol="openai_compatible",
            requested_model_id=self._model_id,
            endpoint_origin=urlunsplit((parsed.scheme, parsed.netloc, "", "", "")),
            normalized_base_url=self._base_url,
            base_url_hash=content_hash(self._base_url),
            request_parameters_hash=content_hash(
                {
                    "temperature": request.temperature,
                    "top_p": request.top_p,
                    "max_output_tokens": request.max_output_tokens,
                    "stop": request.stop,
                }
            ),
            prompt_payload_hash=content_hash(
                [message.model_dump(mode="json") for message in request.messages]
            ),
            prompt_policy_hash=_optional_metadata_hash(metadata, "prompt_policy_hash"),
            agent_configuration_hash=_optional_metadata_hash(metadata, "agent_configuration_hash"),
            action_protocol_hash=_optional_metadata_hash(metadata, "action_protocol_hash"),
            connect_timeout_s=self._connect_timeout_s,
            read_timeout_s=self._read_timeout_s,
            request_timeout_s=self._request_timeout_s,
            max_response_bytes=self._max_response_bytes,
            authentication_mode=("bearer_explicit_in_memory" if self._api_key else "bearer_env"),
            credential_env_name=None if self._api_key else self._api_key_env,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        missing = [
            label
            for label, value in (("base URL", self._base_url), ("model identifier", self._model_id))
            if not value
        ]
        if missing:
            raise _configuration_error(f"OpenAI-compatible client is missing {', '.join(missing)}")
        api_key = self._api_key
        if api_key is None and self._api_key_env:
            api_key = os.environ.get(self._api_key_env)
        if not api_key:
            source = self._api_key_env or "an explicitly configured credential"
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.AUTHENTICATION,
                    message=f"OpenAI-compatible credential is unavailable from {source}",
                )
            )
        assert self._base_url is not None and self._model_id is not None
        payload: dict[str, Any] = {
            "model": self._model_id,
            "messages": [message.model_dump(mode="json") for message in request.messages],
            "temperature": request.temperature,
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop:
            payload["stop"] = request.stop
        try:
            data = self._transport.create_chat_completion(
                url=f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                payload=payload,
                connect_timeout_s=self._connect_timeout_s,
                read_timeout_s=self._read_timeout_s,
                request_timeout_s=self._request_timeout_s,
                max_response_bytes=self._max_response_bytes,
            )
        except ModelClientError:
            raise
        except TimeoutError as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.TIMEOUT,
                    message="OpenAI-compatible transport timed out",
                    retryable=True,
                )
            ) from exc
        except Exception as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.PROVIDER_UNAVAILABLE,
                    message=f"OpenAI-compatible transport failed: {type(exc).__name__}",
                    retryable=True,
                )
            ) from exc
        return self._parse_response(request, data)

    def _parse_response(self, request: ModelRequest, data: Mapping[str, Any]) -> ModelResponse:
        try:
            choices = data["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("exactly one choice is required")
            choice = choices[0]
            if not isinstance(choice, Mapping):
                raise ValueError("choice must be an object")
            message = choice["message"]
            if not isinstance(message, Mapping):
                raise ValueError("choice.message must be an object")
            content = message.get("content")
            native_tool_calls = _parse_native_tool_calls(message.get("tool_calls"))
            if content is None and native_tool_calls:
                content = ""
            if not isinstance(content, str):
                raise ValueError("choice.message.content must be text or null with tool calls")
            observed_model = _optional_safe_text(data.get("model"), "model", 256)
            if self._require_exact_model_id and observed_model != self._model_id:
                raise _ProtocolViolation("observed provider model differs from the requested model")
            usage = _parse_usage(data)
            cost, cost_currency, cost_unit = _parse_cost(data)
            response_id = data.get("id")
            safe_response_id = (
                response_id
                if isinstance(response_id, str) and _SAFE_ID.fullmatch(response_id)
                else None
            )
            return ModelResponse(
                request_id=request.request_id,
                response_id=safe_response_id,
                provider_model_id=observed_model,
                system_fingerprint=_optional_safe_text(
                    data.get("system_fingerprint"), "system_fingerprint", 256
                ),
                text=content,
                native_tool_calls=native_tool_calls,
                finish_reason=_normalize_finish_reason(choice.get("finish_reason")),
                usage=usage,
                cost=cost,
                cost_currency=cost_currency,
                cost_unit=cost_unit,
            )
        except _ProtocolViolation as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.PROTOCOL_ERROR,
                    message=f"invalid OpenAI-compatible protocol response: {exc}",
                )
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.MALFORMED_RESPONSE,
                    message=f"invalid OpenAI-compatible response: {exc}",
                )
            ) from exc

    @staticmethod
    def _safe_base_url(value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise _configuration_error(
                "base URL must be an http(s) URL without embedded credentials, "
                "query parameters, or fragments"
            )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _parse_usage(data: Mapping[str, Any]) -> NormalizedModelUsage:
    if "usage" not in data or data["usage"] is None:
        return NormalizedModelUsage()
    value = data["usage"]
    if not isinstance(value, Mapping):
        raise _ProtocolViolation("usage must be an object when present")
    parsed: dict[str, int | None] = {}
    for output, provider in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        raw = value.get(provider)
        if raw is not None and (not isinstance(raw, int) or isinstance(raw, bool) or raw < 0):
            raise _ProtocolViolation(f"usage.{provider} must be a non-negative integer")
        parsed[output] = raw
    input_tokens = parsed["input_tokens"]
    output_tokens = parsed["output_tokens"]
    total_tokens = parsed["total_tokens"]
    if (
        input_tokens is not None
        and output_tokens is not None
        and total_tokens is not None
        and total_tokens != input_tokens + output_tokens
    ):
        raise _ProtocolViolation("usage.total_tokens is inconsistent")
    return NormalizedModelUsage(
        input_tokens=parsed["input_tokens"],
        output_tokens=parsed["output_tokens"],
        total_tokens=parsed["total_tokens"],
    )


def _parse_native_tool_calls(value: Any) -> list[ProviderNativeToolCall]:
    if value is None:
        return []
    if not isinstance(value, list) or not value:
        raise _ProtocolViolation("message.tool_calls must be a non-empty list when present")
    result: list[ProviderNativeToolCall] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - {"id", "type", "function", "index"}:
            raise _ProtocolViolation("native tool call has an invalid envelope")
        if item.get("type") != "function":
            raise _ProtocolViolation("only native function tool calls are supported")
        function = item.get("function")
        if not isinstance(function, Mapping) or set(function) - {"name", "arguments"}:
            raise _ProtocolViolation("native tool call function has an invalid envelope")
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not name or len(name) > 128:
            raise _ProtocolViolation("native tool call name is invalid")
        if not isinstance(arguments, str) or len(arguments.encode("utf-8")) > 4 * 1024 * 1024:
            raise _ProtocolViolation("native tool call arguments are invalid")
        raw_id = item.get("id")
        safe_id = raw_id if isinstance(raw_id, str) and _SAFE_ID.fullmatch(raw_id) else None
        result.append(ProviderNativeToolCall(call_id=safe_id, name=name, arguments_json=arguments))
    return result


def _parse_cost(data: Mapping[str, Any]) -> tuple[float | None, str | None, str | None]:
    if "cost" not in data or data["cost"] is None:
        return None, None, None
    value = data["cost"]
    if not isinstance(value, Mapping) or set(value) - {"amount", "currency", "unit"}:
        raise _ProtocolViolation("cost must be an object with amount and one identity when present")
    amount = value.get("amount")
    if (
        not isinstance(amount, int | float)
        or isinstance(amount, bool)
        or not float(amount) >= 0.0
        or not float(amount) < float("inf")
    ):
        raise _ProtocolViolation("cost.amount must be a finite non-negative number")
    currency = value.get("currency")
    unit = value.get("unit")
    for label, candidate in (("currency", currency), ("unit", unit)):
        if candidate is not None and (
            not isinstance(candidate, str)
            or not candidate
            or len(candidate) > 64
            or any(ord(character) < 33 or ord(character) > 126 for character in candidate)
        ):
            raise _ProtocolViolation(f"cost.{label} must be a bounded printable identifier")
    if (currency is None) == (unit is None):
        raise _ProtocolViolation("cost must declare exactly one currency or provider unit")
    return float(amount), currency, unit


def _optional_safe_text(value: Any, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{label} must be bounded non-empty text when present")
    return value


def _optional_metadata_hash(metadata: Mapping[str, Any], name: str) -> str | None:
    value = metadata.get(name)
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def _status_error(status: int) -> ModelClientError:
    category = (
        ModelErrorCategory.AUTHENTICATION
        if status in {401, 403}
        else ModelErrorCategory.RATE_LIMIT
        if status == 429
        else ModelErrorCategory.PROVIDER_UNAVAILABLE
        if status >= 500
        else ModelErrorCategory.PROTOCOL_ERROR
    )
    return ModelClientError(
        ModelClientErrorInfo(
            category=category,
            message=f"OpenAI-compatible endpoint returned HTTP {status}",
            retryable=status == 429 or status >= 500,
            provider_code=str(status),
        )
    )


def _response_limit_error() -> ModelClientError:
    return ModelClientError(
        ModelClientErrorInfo(
            category=ModelErrorCategory.OUTPUT_LIMIT,
            message="OpenAI-compatible response exceeded the configured byte limit",
        )
    )


def _configuration_error(message: str) -> ModelClientError:
    return ModelClientError(
        ModelClientErrorInfo(category=ModelErrorCategory.CONFIGURATION, message=message)
    )


def _normalize_finish_reason(value: Any) -> ModelFinishReason:
    mapping = {
        "stop": ModelFinishReason.STOP,
        "length": ModelFinishReason.LENGTH,
        "tool_calls": ModelFinishReason.TOOL_CALL,
        "content_filter": ModelFinishReason.CONTENT_FILTER,
    }
    return mapping.get(value, ModelFinishReason.UNKNOWN)


__all__ = [
    "HttpxOpenAITransport",
    "OpenAICompatibleModelClient",
    "OpenAICompatibleTransport",
]
