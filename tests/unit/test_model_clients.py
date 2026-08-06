from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from verigym.core.episode import BudgetTracker
from verigym.core.model_gateway import ModelGateway
from verigym.core.trace import TraceWriter, read_trace
from verigym.models.base import ModelClientError
from verigym.models.openai_compatible import OpenAICompatibleModelClient
from verigym.models.static import StaticModelClient, StaticResponseSpec
from verigym.schemas.model import (
    ModelErrorCategory,
    ModelMessage,
    ModelRequest,
    NormalizedModelUsage,
)
from verigym.schemas.task import BudgetSpec


def request(request_id: str = "request-1") -> ModelRequest:
    return ModelRequest(
        request_id=request_id,
        messages=[ModelMessage(role="user", content="visible prompt")],
    )


def test_static_client_is_deterministic_sequenced_and_clone_isolated() -> None:
    client = StaticModelClient(
        name="test-static",
        responses=[
            StaticResponseSpec(
                text="first",
                usage=NormalizedModelUsage(input_tokens=2, output_tokens=3),
            ),
            "second",
        ],
    )
    first = client.generate(request("one"))
    second = client.generate(request("two"))
    assert first.text == "first"
    assert first.usage.total_tokens == 5
    assert second.text == "second"
    assert second.usage.total_tokens is None
    assert client.call_count == 2

    clone = client.clone_for_run()
    assert clone.call_count == 0
    assert clone.generate(request("clone")).text == "first"
    assert client.call_count == 2

    with pytest.raises(ModelClientError) as raised:
        client.generate(request("exhausted"))
    assert raised.value.info.category == ModelErrorCategory.EXHAUSTED


class FakeTransport:
    def __init__(self, result: Mapping[str, Any] | Exception) -> None:
        self.result = result
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
                "headers": dict(headers),
                "payload": dict(payload),
                "timeouts": (
                    connect_timeout_s,
                    read_timeout_s,
                    request_timeout_s,
                ),
                "max_response_bytes": max_response_bytes,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_openai_compatible_mock_success_normalizes_response_without_network() -> None:
    transport = FakeTransport(
        {
            "id": "provider-response",
            "model": "provider-observed-model",
            "system_fingerprint": "fp_test_observation",
            "choices": [{"message": {"content": "candidate"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 11,
                "total_tokens": 18,
            },
        }
    )
    client = OpenAICompatibleModelClient(
        base_url="https://models.example.test/v1",
        model_id="demo-model",
        api_key="unit-test-secret",
        connect_timeout_s=1,
        read_timeout_s=2,
        request_timeout_s=3,
        transport=transport,
    )
    response = client.generate(request())
    assert response.text == "candidate"
    assert response.provider_model_id == "provider-observed-model"
    assert response.system_fingerprint == "fp_test_observation"
    assert response.finish_reason.value == "stop"
    assert response.usage.model_dump() == {
        "schema_version": "1.0",
        "input_tokens": 7,
        "output_tokens": 11,
        "total_tokens": 18,
    }
    assert transport.calls[0]["url"] == "https://models.example.test/v1/chat/completions"
    assert transport.calls[0]["timeouts"] == (1, 2, 3)
    assert transport.calls[0]["max_response_bytes"] == 4 * 1024 * 1024


@pytest.mark.parametrize(
    ("transport_error", "category"),
    [
        (TimeoutError("slow"), ModelErrorCategory.TIMEOUT),
        (OSError("offline"), ModelErrorCategory.PROVIDER_UNAVAILABLE),
    ],
)
def test_openai_compatible_transport_errors_are_structured(
    transport_error: Exception,
    category: ModelErrorCategory,
) -> None:
    client = OpenAICompatibleModelClient(
        base_url="https://models.example.test/v1",
        model_id="demo-model",
        api_key="unit-test-secret",
        transport=FakeTransport(transport_error),
    )
    with pytest.raises(ModelClientError) as raised:
        client.generate(request())
    assert raised.value.info.category == category
    assert "unit-test-secret" not in raised.value.info.model_dump_json()


def test_openai_configuration_fingerprint_and_descriptor_exclude_credentials() -> None:
    first = OpenAICompatibleModelClient(
        base_url="https://models.example.test/v1",
        model_id="demo-model",
        api_key="first-secret",
        transport=FakeTransport({}),
    )
    second = OpenAICompatibleModelClient(
        base_url="https://models.example.test/v1",
        model_id="demo-model",
        api_key="second-secret",
        transport=FakeTransport({}),
    )
    serialized = first.descriptor.model_dump_json()
    assert first.descriptor.configuration_fingerprint == (
        second.descriptor.configuration_fingerprint
    )
    assert "first-secret" not in serialized
    assert "second-secret" not in serialized
    assert "Authorization" not in serialized

    with pytest.raises(ModelClientError) as raised:
        OpenAICompatibleModelClient(
            base_url="https://credential:secret@models.example.test/v1",
            model_id="demo-model",
        )
    assert raised.value.info.category == ModelErrorCategory.CONFIGURATION
    assert "credential:secret" not in raised.value.info.message


def test_openai_missing_configuration_is_actionable_and_structured() -> None:
    client = OpenAICompatibleModelClient(transport=FakeTransport({}))
    with pytest.raises(ModelClientError) as raised:
        client.generate(request())
    assert raised.value.info.category == ModelErrorCategory.CONFIGURATION
    assert "base URL" in raised.value.info.message
    assert "model identifier" in raised.value.info.message


def test_model_gateway_redacts_metadata_and_bounds_persisted_content(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    client = StaticModelClient(name="bounded", responses=["x" * 200])
    gateway = ModelGateway(
        run_id="bounded-run",
        client=client,
        trace=TraceWriter(trace_path, "bounded-run"),
        tracker=BudgetTracker(BudgetSpec(max_turns=1, max_tool_calls=0, max_model_calls=1)),
        max_visible_bytes=32,
    )
    model_request = gateway.create_request(
        [ModelMessage(role="user", content="visible")],
        metadata={"api_key": "trace-secret", "nested": {"access_token": "also-secret"}},
    )
    response = gateway.generate(model_request)
    gateway.emit_parsed_action(
        model_request.request_id,
        {"type": "apply_patch", "patch": "y" * 200},
    )
    assert response.text == "x" * 200
    serialized = trace_path.read_text(encoding="utf-8")
    assert "trace-secret" not in serialized
    assert "also-secret" not in serialized
    events = read_trace(trace_path, expected_run_id="bounded-run")
    model_response = next(event for event in events if event.event_type == "model_response")
    assert model_response.payload["content_truncated"] is True
    assert len(model_response.payload["text"].encode("utf-8")) <= 32
    parsed = next(event for event in events if event.event_type == "agent_action_parsed")
    assert parsed.payload["content_truncated"] is True
    assert parsed.payload["action"]["content_omitted"] is True


def test_model_gateway_binds_provider_identity_metadata(tmp_path) -> None:
    prompt_hash = "a" * 64
    agent_hash = "b" * 64
    protocol_hash = "c" * 64
    gateway = ModelGateway(
        run_id="binding-run",
        client=StaticModelClient(name="binding", responses=["done"]),
        trace=TraceWriter(tmp_path / "trace.jsonl", "binding-run"),
        tracker=BudgetTracker(BudgetSpec(max_model_calls=1)),
        max_visible_bytes=1024,
        prompt_policy_hash=prompt_hash,
        agent_configuration_hash=agent_hash,
        action_protocol_hash=protocol_hash,
    )
    request = gateway.create_request(
        [ModelMessage(role="user", content="visible")],
        metadata={"interaction_mode": "agent"},
    )
    assert request.metadata == {
        "interaction_mode": "agent",
        "prompt_policy_hash": prompt_hash,
        "agent_configuration_hash": agent_hash,
        "action_protocol_hash": protocol_hash,
    }
    with pytest.raises(ValueError, match="prompt_policy_hash differs"):
        gateway.create_request(
            [ModelMessage(role="user", content="visible")],
            metadata={"prompt_policy_hash": "d" * 64},
        )
