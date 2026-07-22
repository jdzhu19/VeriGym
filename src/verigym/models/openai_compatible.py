"""Optional, transport-injected OpenAI-compatible chat-completions client."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from verigym.core.hashing import content_hash
from verigym.models.base import ModelClient, ModelClientError
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
)


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
    ) -> Mapping[str, Any]: ...


class HttpxOpenAITransport:
    """Lazily import the optional HTTP dependency only for real requests."""

    def create_chat_completion(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        connect_timeout_s: float,
        read_timeout_s: float,
        request_timeout_s: float,
    ) -> Mapping[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - depends on optional environment.
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
                response = client.post(url, headers=dict(headers), json=dict(payload))
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.TIMEOUT,
                    message="OpenAI-compatible request timed out",
                    retryable=True,
                )
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            category = (
                ModelErrorCategory.AUTHENTICATION
                if status in {401, 403}
                else ModelErrorCategory.RATE_LIMIT
                if status == 429
                else ModelErrorCategory.TRANSPORT
            )
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=category,
                    message=f"OpenAI-compatible endpoint returned HTTP {status}",
                    retryable=status == 429 or status >= 500,
                    provider_code=str(status),
                )
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.TRANSPORT,
                    message=f"OpenAI-compatible request failed: {type(exc).__name__}",
                    retryable=True,
                )
            ) from exc
        if not isinstance(data, Mapping):
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.INVALID_RESPONSE,
                    message="OpenAI-compatible endpoint returned a non-object JSON response",
                )
            )
        return cast(Mapping[str, Any], data)


class OpenAICompatibleModelClient(ModelClient):
    """Normalize an OpenAI-compatible chat-completions endpoint without core coupling."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
        api_key_env: str | None = None,
        connect_timeout_s: float = 10.0,
        read_timeout_s: float = 60.0,
        request_timeout_s: float = 90.0,
        transport: OpenAICompatibleTransport | None = None,
    ) -> None:
        self._base_url = self._safe_base_url(base_url) if base_url else None
        self._model_id = model_id
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._request_timeout_s = request_timeout_s
        self._transport = transport or HttpxOpenAITransport()
        safe_configuration = {
            "base_url": self._base_url,
            "model_id": model_id,
            "credential_source": "explicit" if api_key else api_key_env,
            "connect_timeout_s": connect_timeout_s,
            "read_timeout_s": read_timeout_s,
            "request_timeout_s": request_timeout_s,
        }
        self.descriptor = ModelDescriptor(
            schema_version=SCHEMA_VERSION,
            name="openai-compatible",
            version="0.1.0",
            api_version=PLUGIN_API_VERSION,
            provider="openai-compatible",
            capabilities=["text", "chat_completions", "optional_network"],
            model_id=model_id or "unconfigured",
            client_name="openai-compatible",
            client_version="0.1.0",
            api_compatibility="openai.chat.completions",
            configuration_fingerprint=content_hash(safe_configuration),
            configuration=safe_configuration,
        )

    def clone_for_run(
        self, configuration: ModelRunConfig | None = None
    ) -> OpenAICompatibleModelClient:
        config = configuration or ModelRunConfig()
        return OpenAICompatibleModelClient(
            base_url=config.base_url or self._base_url,
            model_id=config.model_id or self._model_id,
            api_key=self._api_key,
            api_key_env=config.api_key_env or self._api_key_env,
            connect_timeout_s=config.connect_timeout_s,
            read_timeout_s=config.read_timeout_s,
            request_timeout_s=config.request_timeout_s,
            transport=self._transport,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        missing = [
            label
            for label, value in (("base URL", self._base_url), ("model identifier", self._model_id))
            if not value
        ]
        if missing:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.CONFIGURATION,
                    message=f"OpenAI-compatible client is missing {', '.join(missing)}",
                )
            )
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
                    category=ModelErrorCategory.TRANSPORT,
                    message=f"OpenAI-compatible transport failed: {type(exc).__name__}",
                    retryable=True,
                )
            ) from exc
        return self._parse_response(request, data)

    @staticmethod
    def _parse_response(request: ModelRequest, data: Mapping[str, Any]) -> ModelResponse:
        try:
            choices = data["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("exactly one choice is required")
            choice = choices[0]
            if not isinstance(choice, Mapping):
                raise ValueError("choice must be an object")
            message = choice["message"]
            if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
                raise ValueError("choice.message.content must be text")
            finish = _normalize_finish_reason(choice.get("finish_reason"))
            usage_value = data.get("usage", {})
            if not isinstance(usage_value, Mapping):
                usage_value = {}
            usage = NormalizedModelUsage(
                input_tokens=_optional_int(usage_value.get("prompt_tokens")),
                output_tokens=_optional_int(usage_value.get("completion_tokens")),
                total_tokens=_optional_int(usage_value.get("total_tokens")),
            )
            response_id = data.get("id")
            if response_id is not None and not isinstance(response_id, str):
                response_id = str(response_id)
            provider_model_id = data.get("model")
            if provider_model_id is not None and not isinstance(provider_model_id, str):
                provider_model_id = str(provider_model_id)
            system_fingerprint = data.get("system_fingerprint")
            if system_fingerprint is not None and not isinstance(system_fingerprint, str):
                system_fingerprint = str(system_fingerprint)
            return ModelResponse(
                request_id=request.request_id,
                response_id=response_id,
                provider_model_id=provider_model_id,
                system_fingerprint=system_fingerprint,
                text=str(message["content"]),
                finish_reason=finish,
                usage=usage,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.INVALID_RESPONSE,
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
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.CONFIGURATION,
                    message=(
                        "base URL must be an http(s) URL without embedded credentials, "
                        "query parameters, or fragments"
                    ),
                )
            )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _normalize_finish_reason(value: Any) -> ModelFinishReason:
    mapping = {
        "stop": ModelFinishReason.STOP,
        "length": ModelFinishReason.LENGTH,
        "tool_calls": ModelFinishReason.TOOL_CALL,
        "content_filter": ModelFinishReason.CONTENT_FILTER,
    }
    return mapping.get(value, ModelFinishReason.UNKNOWN)


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


__all__ = [
    "HttpxOpenAITransport",
    "OpenAICompatibleModelClient",
    "OpenAICompatibleTransport",
]
