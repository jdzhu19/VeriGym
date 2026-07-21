"""Model-call tracing, redaction boundary, and budget accounting."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from verigym.core.artifact_policy import bound_text, bound_value
from verigym.core.episode import BudgetTracker, TerminationReason
from verigym.core.redaction import redact_mapping
from verigym.core.trace import TraceWriter
from verigym.models.base import ModelClient, ModelClientError
from verigym.schemas.model import (
    ModelClientErrorInfo,
    ModelErrorCategory,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)


class ModelBudgetError(Exception):
    def __init__(self, reason: TerminationReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class ModelGateway:
    """The only orchestration boundary allowed to invoke a model client."""

    def __init__(
        self,
        *,
        run_id: str,
        client: ModelClient,
        trace: TraceWriter,
        tracker: BudgetTracker,
        max_visible_bytes: int,
        temperature: float = 0.0,
        top_p: float | None = None,
    ) -> None:
        self.run_id = run_id
        self.client = client
        self.trace = trace
        self.tracker = tracker
        self.max_visible_bytes = max_visible_bytes
        self.temperature = temperature
        self.top_p = top_p

    def create_request(
        self,
        messages: Sequence[ModelMessage],
        *,
        max_output_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelRequest:
        request_number = self.tracker.model_calls + 1
        return ModelRequest(
            request_id=f"{self.run_id}-model-{request_number:04d}",
            messages=[message.model_copy(deep=True) for message in messages],
            temperature=self.temperature,
            top_p=self.top_p,
            max_output_tokens=max_output_tokens,
            metadata=metadata or {},
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        exhausted = self.tracker.exhausted_before_model()
        if exhausted is not None:
            raise ModelBudgetError(exhausted)
        bounded_request, request_truncated = self._bounded_request(request)
        request_event = self.trace.emit(
            "model_request",
            {
                "model": self._model_reference(),
                "request": bounded_request,
                "content_truncated": request_truncated,
            },
        )
        self.tracker.consume_model_call()
        started = time.monotonic()
        try:
            response = self.client.generate(request)
            if response.request_id != request.request_id:
                raise ModelClientError(
                    ModelClientErrorInfo(
                        category=ModelErrorCategory.INVALID_RESPONSE,
                        message="model response request_id does not match its request",
                    )
                )
        except ModelClientError as exc:
            latency = time.monotonic() - started
            self.tracker.record_model_usage(None)
            error_payload, error_truncated = bound_value(
                exc.info.model_dump(mode="json"), self.max_visible_bytes
            )
            self.trace.emit(
                "model_response",
                {
                    "model": self._model_reference(),
                    "request_id": request.request_id,
                    "finish_reason": "error",
                    "usage": None,
                    "latency_s": latency,
                    "error": error_payload,
                    "content_truncated": error_truncated,
                },
                parent_event_id=request_event.event_id,
            )
            raise
        response.latency_s = time.monotonic() - started
        self.tracker.record_model_usage(response.usage)
        bounded_text, response_truncated = bound_text(response.text, self.max_visible_bytes)
        self.trace.emit(
            "model_response",
            {
                "model": self._model_reference(),
                "request_id": request.request_id,
                "response_id": response.response_id,
                "text": bounded_text,
                "content_truncated": response_truncated,
                "finish_reason": response.finish_reason.value,
                "usage": response.usage.model_dump(mode="json"),
                "latency_s": response.latency_s,
                "error": None,
            },
            parent_event_id=request_event.event_id,
        )
        exhausted_after = self.tracker.exhausted_after_model()
        if exhausted_after is not None:
            raise ModelBudgetError(exhausted_after)
        return response

    def emit_parsed_action(self, request_id: str, action: dict[str, Any]) -> None:
        bounded_action, truncated = bound_value(action, self.max_visible_bytes)
        self.trace.emit(
            "agent_action_parsed",
            {
                "request_id": request_id,
                "action": bounded_action,
                "content_truncated": truncated,
            },
        )

    def emit_action_rejected(
        self,
        request_id: str,
        *,
        category: str,
        message: str,
        invalid_count: int,
    ) -> None:
        self.trace.emit(
            "agent_action_rejected",
            {
                "request_id": request_id,
                "category": category,
                "message": message,
                "invalid_count": invalid_count,
            },
        )

    def _model_reference(self) -> dict[str, Any]:
        descriptor = self.client.descriptor
        return {
            "name": descriptor.name,
            "provider": descriptor.provider,
            "model_id": descriptor.model_id,
            "client_name": descriptor.client_name,
            "client_version": descriptor.client_version,
            "configuration_fingerprint": descriptor.configuration_fingerprint,
        }

    def _bounded_request(self, request: ModelRequest) -> tuple[dict[str, Any], bool]:
        remaining = self.max_visible_bytes
        truncated = False
        messages: list[dict[str, str]] = []
        for message in request.messages:
            bounded, item_truncated = bound_text(message.content, max(0, remaining))
            encoded_length = len(bounded.encode("utf-8"))
            remaining = max(0, remaining - encoded_length)
            truncated = truncated or item_truncated
            messages.append({"role": message.role, "content": bounded})
        metadata, metadata_truncated = bound_value(
            redact_mapping(request.metadata), self.max_visible_bytes
        )
        return (
            {
                "schema_version": request.schema_version,
                "request_id": request.request_id,
                "messages": messages,
                "temperature": request.temperature,
                "max_output_tokens": request.max_output_tokens,
                "stop": request.stop,
                "metadata": metadata,
            },
            truncated or metadata_truncated,
        )


__all__ = ["ModelBudgetError", "ModelGateway"]
