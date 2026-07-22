"""Deterministic no-network model client for tests and demonstrations."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import Field

from verigym.core.hashing import content_hash
from verigym.models.base import ModelClient, ModelClientError
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION, StrictModel
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


class StaticResponseSpec(StrictModel):
    text: str
    finish_reason: ModelFinishReason = ModelFinishReason.STOP
    usage: NormalizedModelUsage = Field(default_factory=NormalizedModelUsage)


class StaticModelClient(ModelClient):
    """Return a fixed ordered response sequence with explicit exhaustion."""

    def __init__(
        self,
        *,
        name: str,
        responses: Sequence[str | StaticResponseSpec],
        model_id: str | None = None,
        repeat_last: bool = False,
        sample_responses: Sequence[Sequence[str | StaticResponseSpec]] | None = None,
        _selected_sample_index: int | None = None,
    ) -> None:
        self._name = name
        self._specs = tuple(
            item if isinstance(item, StaticResponseSpec) else StaticResponseSpec(text=item)
            for item in responses
        )
        self._repeat_last = repeat_last
        self._sample_specs = (
            tuple(
                tuple(
                    item if isinstance(item, StaticResponseSpec) else StaticResponseSpec(text=item)
                    for item in sequence
                )
                for sequence in sample_responses
            )
            if sample_responses is not None
            else None
        )
        self._selected_sample_index = _selected_sample_index
        self._index = 0
        configuration = {
            "response_count": len(self._specs),
            "response_hashes": [content_hash(spec) for spec in self._specs],
            "repeat_last": repeat_last,
            "sample_response_hashes": (
                [[content_hash(spec) for spec in sequence] for sequence in self._sample_specs]
                if self._sample_specs is not None
                else None
            ),
        }
        self.descriptor = ModelDescriptor(
            schema_version=SCHEMA_VERSION,
            name=name,
            version="0.1.0",
            api_version=PLUGIN_API_VERSION,
            provider="verigym-static",
            capabilities=[
                "text",
                "deterministic",
                "offline",
                "response_sequence",
                *(["independent_sample_sequences"] if self._sample_specs is not None else []),
            ],
            model_id=model_id or name,
            client_name="static",
            client_version="0.1.0",
            api_compatibility="verigym.model.v1",
            configuration_fingerprint=content_hash(configuration),
            configuration=configuration,
        )

    @property
    def call_count(self) -> int:
        return self._index

    def generate(self, request: ModelRequest) -> ModelResponse:
        specs = self._active_specs()
        if self._index < len(specs):
            spec = specs[self._index]
        elif self._repeat_last and specs:
            spec = specs[-1]
        else:
            raise ModelClientError(
                ModelClientErrorInfo(
                    category=ModelErrorCategory.EXHAUSTED,
                    message=(
                        f"static model {self.descriptor.name!r} exhausted its "
                        f"{len(specs)} configured response(s)"
                    ),
                    retryable=False,
                )
            )
        response_index = self._index
        self._index += 1
        return ModelResponse(
            request_id=request.request_id,
            response_id=(
                f"{self.descriptor.name}-sample-{self._selected_sample_index:04d}-"
                f"{response_index:04d}"
                if self._selected_sample_index is not None
                else f"{self.descriptor.name}-{response_index:04d}"
            ),
            text=spec.text,
            finish_reason=spec.finish_reason,
            usage=spec.usage.model_copy(deep=True),
        )

    def clone_for_run(self, configuration: ModelRunConfig | None = None) -> StaticModelClient:
        sample_index = configuration.sample_index if configuration is not None else None
        if self._sample_specs is not None:
            if sample_index is None:
                sample_index = 0
            if sample_index >= len(self._sample_specs):
                raise ValueError(
                    f"static model {self._name!r} has no fixture sequence for "
                    f"sample index {sample_index}"
                )
        return StaticModelClient(
            name=self._name,
            responses=self._specs,
            model_id=self.descriptor.model_id,
            repeat_last=self._repeat_last,
            sample_responses=self._sample_specs,
            _selected_sample_index=sample_index,
        )

    def _active_specs(self) -> tuple[StaticResponseSpec, ...]:
        if self._sample_specs is None:
            return self._specs
        index = self._selected_sample_index if self._selected_sample_index is not None else 0
        return self._sample_specs[index]

    def reset(self) -> None:
        self._index = 0


COUNTER_GOOD_SOURCE = """module counter (
    input wire clk,
    input wire reset,
    output reg [7:0] q
);

    always @(posedge clk) begin
        if (reset) begin
            q <= 8'h00;
        end else begin
            q <= q + 8'h01;
        end
    end
endmodule
"""

COUNTER_BAD_SOURCE = COUNTER_GOOD_SOURCE.replace("8'h01", "8'h02")

VERILOG_EVAL_FIXTURE_GOOD_SOURCE = """module TopModule (
    input logic a,
    input logic b,
    output logic y
);
    assign y = a & b;
endmodule
"""

VERILOG_EVAL_FIXTURE_BAD_SOURCE = VERILOG_EVAL_FIXTURE_GOOD_SOURCE.replace("a & b", "a | b")

AND_GATE_GOOD_SOURCE = """module and_gate (
    input wire a,
    input wire b,
    output wire y
);
    assign y = a & b;
endmodule
"""

AND_GATE_BAD_SOURCE = AND_GATE_GOOD_SOURCE.replace("a & b", "a | b")

COUNTER_GOOD_PATCH = """--- a/rtl/counter.v
+++ b/rtl/counter.v
@@ -7,3 +7,7 @@
     always @(posedge clk) begin
-        q <= 8'h00;
+        if (reset) begin
+            q <= 8'h00;
+        end else begin
+            q <= q + 8'h01;
+        end
     end
"""


def _react_response(action: dict[str, object]) -> str:
    return json.dumps(action, sort_keys=True, separators=(",", ":"))


def builtin_model_clients() -> list[ModelClient]:
    """Return fresh named offline fixtures plus an unconfigured optional client."""

    from verigym.models.openai_compatible import OpenAICompatibleModelClient

    synthetic_usage = NormalizedModelUsage(input_tokens=20, output_tokens=30, total_tokens=50)
    return [
        StaticModelClient(
            name="static-counter-good",
            responses=[StaticResponseSpec(text=COUNTER_GOOD_SOURCE, usage=synthetic_usage)],
        ),
        StaticModelClient(
            name="static-counter-good-fenced",
            responses=[
                StaticResponseSpec(
                    text=f"```verilog\n{COUNTER_GOOD_SOURCE}```",
                    usage=synthetic_usage,
                )
            ],
        ),
        StaticModelClient(
            name="static-counter-bad",
            responses=[StaticResponseSpec(text=COUNTER_BAD_SOURCE, usage=synthetic_usage)],
        ),
        StaticModelClient(
            name="static-verilog-eval-fixture-good",
            responses=[
                StaticResponseSpec(text=VERILOG_EVAL_FIXTURE_GOOD_SOURCE, usage=synthetic_usage)
            ],
        ),
        StaticModelClient(
            name="static-verilog-eval-fixture-mixed",
            responses=[VERILOG_EVAL_FIXTURE_GOOD_SOURCE],
            sample_responses=[
                [StaticResponseSpec(text=VERILOG_EVAL_FIXTURE_GOOD_SOURCE, usage=synthetic_usage)],
                [StaticResponseSpec(text=VERILOG_EVAL_FIXTURE_BAD_SOURCE, usage=synthetic_usage)],
                [StaticResponseSpec(text=VERILOG_EVAL_FIXTURE_GOOD_SOURCE, usage=synthetic_usage)],
                [StaticResponseSpec(text="not RTL", usage=synthetic_usage)],
            ],
        ),
        StaticModelClient(
            name="static-and-gate-mixed",
            responses=[AND_GATE_GOOD_SOURCE],
            sample_responses=[
                [StaticResponseSpec(text=AND_GATE_GOOD_SOURCE, usage=synthetic_usage)],
                [StaticResponseSpec(text=AND_GATE_BAD_SOURCE, usage=synthetic_usage)],
                [StaticResponseSpec(text=AND_GATE_GOOD_SOURCE, usage=synthetic_usage)],
                [StaticResponseSpec(text="not RTL", usage=synthetic_usage)],
            ],
        ),
        StaticModelClient(
            name="static-react-counter-good",
            responses=[
                StaticResponseSpec(
                    text=_react_response(
                        {
                            "type": "tool_call",
                            "tool": "file.read",
                            "arguments": {"path": "rtl/counter.v"},
                        }
                    ),
                    usage=synthetic_usage,
                ),
                StaticResponseSpec(
                    text=_react_response({"type": "apply_patch", "patch": COUNTER_GOOD_PATCH}),
                    usage=synthetic_usage,
                ),
                StaticResponseSpec(
                    text=_react_response(
                        {
                            "type": "tool_call",
                            "tool": "iverilog.simulate_visible",
                            "arguments": {
                                "sources": ["rtl/counter.v", "visible/tb_smoke.sv"],
                                "top": "tb_smoke",
                                "pass_marker": "VERIGYM_PASS",
                                "fail_marker": "VERIGYM_FAIL",
                            },
                        }
                    ),
                    usage=synthetic_usage,
                ),
                StaticResponseSpec(
                    text=_react_response(
                        {"type": "final", "message": "Counter implementation complete."}
                    ),
                    usage=synthetic_usage,
                ),
            ],
        ),
        StaticModelClient(
            name="static-react-malformed",
            responses=["not-json", "{", '{"type":"unknown"}'],
        ),
        StaticModelClient(name="static-exhausted", responses=[]),
        OpenAICompatibleModelClient(),
    ]


__all__ = [
    "AND_GATE_BAD_SOURCE",
    "AND_GATE_GOOD_SOURCE",
    "COUNTER_BAD_SOURCE",
    "COUNTER_GOOD_PATCH",
    "COUNTER_GOOD_SOURCE",
    "VERILOG_EVAL_FIXTURE_BAD_SOURCE",
    "VERILOG_EVAL_FIXTURE_GOOD_SOURCE",
    "StaticModelClient",
    "StaticResponseSpec",
    "builtin_model_clients",
]
