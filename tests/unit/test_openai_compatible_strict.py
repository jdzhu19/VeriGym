from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from verigym.models.base import ModelClientError
from verigym.models.openai_compatible import (
    HttpxOpenAITransport,
    OpenAICompatibleModelClient,
)
from verigym.schemas.model import (
    ModelClientErrorInfo,
    ModelErrorCategory,
    ModelMessage,
    ModelRequest,
    ModelRunConfig,
)


class FakeProvider:
    def __init__(self, outcome: Mapping[str, Any] | Exception) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "url": url,
                "authorization_present": "Authorization" in headers,
                "payload": dict(payload),
                "connect_timeout_s": connect_timeout_s,
                "read_timeout_s": read_timeout_s,
                "request_timeout_s": request_timeout_s,
                "max_response_bytes": max_response_bytes,
            }
        )
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _request() -> ModelRequest:
    return ModelRequest(
        request_id="strict-request",
        messages=[ModelMessage(role="user", content="public repository prompt")],
        max_output_tokens=2048,
        metadata={
            "prompt_policy_hash": "a" * 64,
            "agent_configuration_hash": "b" * 64,
        },
    )


def _response(**updates: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": "safe-request-id",
        "model": "exact-model",
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    result.update(updates)
    return result


def _client(outcome: Mapping[str, Any] | Exception) -> OpenAICompatibleModelClient:
    return OpenAICompatibleModelClient(
        base_url="https://provider.example.test/v1",
        provider_id="fake-provider",
        model_id="exact-model",
        api_key="fake-unit-key",
        max_response_bytes=8192,
        require_exact_model_id=True,
        transport=FakeProvider(outcome),
    )


def test_strict_provider_success_and_request_identity_are_secret_free() -> None:
    client = _client(_response())
    identity = client.request_identity(_request())
    assert identity is not None
    assert identity.provider_id == "fake-provider"
    assert identity.requested_model_id == "exact-model"
    assert identity.prompt_policy_hash == "a" * 64
    assert identity.agent_configuration_hash == "b" * 64
    assert identity.credential_persisted is False
    assert identity.credential_hashed is False
    assert "fake-unit-key" not in identity.model_dump_json()
    response = client.generate(_request())
    assert response.response_id == "safe-request-id"
    assert response.usage.total_tokens == 6
    assert response.cost is None
    assert response.cost_currency is None


def test_base_url_and_key_can_be_resolved_only_from_named_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_API_BASE_URL", "https://provider.example.test/v1")
    monkeypatch.setenv("FAKE_API_KEY", "fake-environment-key")
    transport = FakeProvider(_response())
    root = OpenAICompatibleModelClient(transport=transport)
    client = root.clone_for_run(
        ModelRunConfig(
            provider_id="fake-provider",
            base_url_env="FAKE_API_BASE_URL",
            api_key_env="FAKE_API_KEY",
            model_id="exact-model",
            require_exact_model_id=True,
        )
    )
    client.generate(_request())
    serialized = client.descriptor.model_dump_json()
    assert "fake-environment-key" not in serialized
    assert client.descriptor.configuration["base_url_source"] == "FAKE_API_BASE_URL"
    assert client.descriptor.configuration["credential_env_name"] == "FAKE_API_KEY"


@pytest.mark.parametrize(
    ("outcome", "category"),
    [
        (
            ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.AUTHENTICATION,
                    message="provider authentication failed",
                    provider_code="401",
                )
            ),
            ModelErrorCategory.AUTHENTICATION,
        ),
        (
            ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.RATE_LIMIT,
                    message="provider rate limited the request",
                    provider_code="429",
                )
            ),
            ModelErrorCategory.RATE_LIMIT,
        ),
        (TimeoutError("connect timeout"), ModelErrorCategory.TIMEOUT),
        (
            ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.TIMEOUT,
                    message="provider response timed out",
                )
            ),
            ModelErrorCategory.TIMEOUT,
        ),
        (ConnectionError("offline"), ModelErrorCategory.PROVIDER_UNAVAILABLE),
        (
            ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.PROVIDER_UNAVAILABLE,
                    message="provider unavailable",
                    provider_code="503",
                )
            ),
            ModelErrorCategory.PROVIDER_UNAVAILABLE,
        ),
        (
            ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.OUTPUT_LIMIT,
                    message="provider response exceeded the byte limit",
                )
            ),
            ModelErrorCategory.OUTPUT_LIMIT,
        ),
    ],
)
def test_provider_failures_remain_structured_and_separate(
    outcome: Exception,
    category: ModelErrorCategory,
) -> None:
    with pytest.raises(ModelClientError) as raised:
        _client(outcome).generate(_request())
    assert raised.value.info.category == category
    assert "fake-unit-key" not in raised.value.info.model_dump_json()


@pytest.mark.parametrize(
    "outcome",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}, "finish_reason": "stop"}]},
    ],
)
def test_malformed_missing_and_identity_mutated_responses_fail_closed(
    outcome: Mapping[str, Any],
) -> None:
    with pytest.raises(ModelClientError) as raised:
        _client(outcome).generate(_request())
    assert raised.value.info.category == ModelErrorCategory.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    "outcome",
    [
        _response(usage="invalid"),
        _response(usage={"prompt_tokens": -1}),
        _response(usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 99}),
        _response(model="substituted-model"),
        _response(model=None),
        _response(cost={"amount": -1, "currency": "USD"}),
        _response(cost={"amount": 0.1, "currency": "USD", "unit": "credits"}),
    ],
)
def test_protocol_and_identity_inconsistencies_are_separate_from_malformed_json(
    outcome: Mapping[str, Any],
) -> None:
    with pytest.raises(ModelClientError) as raised:
        _client(outcome).generate(_request())
    assert raised.value.info.category == ModelErrorCategory.PROTOCOL_ERROR


def test_missing_usage_is_explicitly_nullable_and_unsafe_request_id_is_dropped() -> None:
    response = _client(_response(id="unsafe request id\n", usage=None)).generate(_request())
    assert response.response_id is None
    assert response.usage.input_tokens is None
    assert response.usage.output_tokens is None
    assert response.usage.total_tokens is None


def test_directly_reported_cost_is_normalized_without_invention() -> None:
    response = _client(_response(cost={"amount": 0.125, "currency": "USD"})).generate(_request())
    assert response.cost == 0.125
    assert response.cost_currency == "USD"
    assert response.cost_unit is None


def test_missing_credentials_fail_before_transport_without_secret_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ABSENT_API_KEY", raising=False)
    transport = FakeProvider(_response())
    client = OpenAICompatibleModelClient(
        base_url="https://provider.example.test/v1",
        provider_id="fake-provider",
        model_id="exact-model",
        api_key_env="ABSENT_API_KEY",
        transport=transport,
    )
    with pytest.raises(ModelClientError) as raised:
        client.generate(_request())
    assert raised.value.info.category == ModelErrorCategory.AUTHENTICATION
    assert transport.calls == []


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, ModelErrorCategory.AUTHENTICATION),
        (403, ModelErrorCategory.AUTHENTICATION),
        (429, ModelErrorCategory.RATE_LIMIT),
        (500, ModelErrorCategory.PROVIDER_UNAVAILABLE),
        (503, ModelErrorCategory.PROVIDER_UNAVAILABLE),
        (400, ModelErrorCategory.PROTOCOL_ERROR),
    ],
)
def test_http_transport_classifies_fake_provider_status_without_reading_error_body(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    category: ModelErrorCategory,
) -> None:
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"provider-secret-error-body", request=request)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ModelClientError) as raised:
        HttpxOpenAITransport().create_chat_completion(
            url="https://provider.example.test/v1/chat/completions",
            headers={"Authorization": "Bearer fake-key"},
            payload={"model": "exact-model", "messages": []},
            connect_timeout_s=1,
            read_timeout_s=2,
            request_timeout_s=3,
            max_response_bytes=1024,
        )
    assert raised.value.info.category == category
    assert "provider-secret-error-body" not in raised.value.info.model_dump_json()
    assert "fake-key" not in raised.value.info.model_dump_json()


@pytest.mark.parametrize(
    ("body", "category"),
    [
        (b"not-json", ModelErrorCategory.MALFORMED_RESPONSE),
        (b"[]", ModelErrorCategory.MALFORMED_RESPONSE),
        (b"x" * 1025, ModelErrorCategory.OUTPUT_LIMIT),
    ],
)
def test_http_transport_rejects_malformed_or_oversized_fake_provider_bytes(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    category: ModelErrorCategory,
) -> None:
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, request=request)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ModelClientError) as raised:
        HttpxOpenAITransport().create_chat_completion(
            url="https://provider.example.test/v1/chat/completions",
            headers={},
            payload={"model": "exact-model", "messages": []},
            connect_timeout_s=1,
            read_timeout_s=2,
            request_timeout_s=3,
            max_response_bytes=1024,
        )
    assert raised.value.info.category == category


@pytest.mark.parametrize("exception", [httpx.ConnectTimeout("connect"), httpx.ReadTimeout("read")])
def test_http_transport_classifies_connect_and_response_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    exception: httpx.TimeoutException,
) -> None:
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        exception.request = request
        raise exception

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ModelClientError) as raised:
        HttpxOpenAITransport().create_chat_completion(
            url="https://provider.example.test/v1/chat/completions",
            headers={},
            payload={"model": "exact-model", "messages": []},
            connect_timeout_s=1,
            read_timeout_s=2,
            request_timeout_s=3,
            max_response_bytes=1024,
        )
    assert raised.value.info.category == ModelErrorCategory.TIMEOUT
