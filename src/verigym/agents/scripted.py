"""Deterministic good and bad agents used by tests and demonstrations."""

from __future__ import annotations

from verigym.agents.base import AgentAdapter, AgentContext
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    FinalSubmissionAction,
    Observation,
    ToolCallAction,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor


def _counter_patch(increment: str) -> str:
    return f"""--- a/rtl/counter.v
+++ b/rtl/counter.v
@@ -7,3 +7,7 @@
     always @(posedge clk) begin
-        q <= 8'h00;
+        if (reset) begin
+            q <= 8'h00;
+        end else begin
+            q <= q + 8'h{increment};
+        end
     end
"""


def _and_gate_patch(operator: str) -> str:
    return f"""--- a/rtl/and_gate.v
+++ b/rtl/and_gate.v
@@ -3,5 +3,5 @@
     input wire b,
     output wire y
 );
-    assign y = 1'b0;
+    assign y = a {operator} b;
 endmodule
"""


class _ScriptedCounterAgent(AgentAdapter):
    increment = "01"

    def __init__(self) -> None:
        self._actions: list[AgentAction] = []
        self._index = 0

    def start(self, context: AgentContext) -> None:
        if context.task.id == "toy-rtl/counter-basic":
            self._actions = self._counter_actions()
        elif context.task.id == "toy-rtl/and-gate-basic":
            self._actions = self._and_gate_actions()
        else:
            raise ValueError(f"scripted toy agent does not support {context.task.id}")
        self._index = 0

    def _counter_actions(self) -> list[AgentAction]:
        return [
            ToolCallAction(tool="file.list", arguments={"path": ".", "recursive": True}),
            ToolCallAction(tool="file.read", arguments={"path": "rtl/counter.v"}),
            ApplyPatchAction(patch=_counter_patch(self.increment)),
            ToolCallAction(
                tool="iverilog.simulate_visible",
                arguments={
                    "sources": ["rtl/counter.v", "visible/tb_smoke.sv"],
                    "top": "tb_smoke",
                    "pass_marker": "VERIGYM_PASS",
                    "fail_marker": "VERIGYM_FAIL",
                },
            ),
            ToolCallAction(tool="file.diff", arguments={}),
            FinalSubmissionAction(message="Counter implementation complete."),
        ]

    def _and_gate_actions(self) -> list[AgentAction]:
        operator = "&" if self.increment == "01" else "|"
        return [
            ToolCallAction(tool="file.list", arguments={"path": ".", "recursive": True}),
            ToolCallAction(tool="file.read", arguments={"path": "rtl/and_gate.v"}),
            ApplyPatchAction(patch=_and_gate_patch(operator)),
            ToolCallAction(
                tool="iverilog.simulate_visible",
                arguments={
                    "sources": ["rtl/and_gate.v", "visible/tb_smoke.sv"],
                    "top": "tb_smoke",
                    "pass_marker": "VERIGYM_PASS",
                    "fail_marker": "VERIGYM_FAIL",
                },
            ),
            ToolCallAction(tool="file.diff", arguments={}),
            FinalSubmissionAction(message="AND-gate implementation complete."),
        ]

    def act(self, observation: Observation) -> AgentAction:
        if self._index >= len(self._actions):
            return FinalSubmissionAction(message="Script exhausted.")
        action = self._actions[self._index]
        self._index += 1
        return action

    def finish(self, result: EpisodeResult) -> None:
        return None


class ScriptedAgent(_ScriptedCounterAgent):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="scripted",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "deterministic",
            "toy-rtl/counter-basic",
            "toy-rtl/and-gate-basic",
            "known-good",
        ],
    )


class ScriptedBadAgent(_ScriptedCounterAgent):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="scripted-bad",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "deterministic",
            "toy-rtl/counter-basic",
            "toy-rtl/and-gate-basic",
            "known-bad",
        ],
    )
    increment = "02"
