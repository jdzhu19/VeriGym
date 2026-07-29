"""Independent deterministic acceptance agents for repo-RTL conformance."""

from __future__ import annotations

from verigym.agents.base import AgentAdapter, AgentContext, AgentTerminationError
from verigym.core.episode import TerminationReason
from verigym.schemas.agent import (
    AgentAction,
    ApplyPatchAction,
    EpisodeResult,
    FinalSubmissionAction,
    Observation,
    ToolCallAction,
)
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import AgentDescriptor, ErrorCategory
from verigym.schemas.score import EpisodeFailure

_GOOD_PATCHES = {
    "repo-rtl/counter-wrap": """--- a/repository/rtl/wrap_counter.sv
+++ b/repository/rtl/wrap_counter.sv
@@ -9,11 +9,7 @@
         if (rst) begin
             count <= 4'h0;
         end else if (enable) begin
-            if (count == 4'hf) begin
-                count <= 4'hf;
-            end else begin
-                count <= count + 4'h1;
-            end
+            count <= count + 4'h1;
         end
     end
 endmodule
""",
    "repo-rtl/pipeline-stall-backpressure": """--- a/repository/rtl/pipeline_stage.sv
+++ b/repository/rtl/pipeline_stage.sv
@@ -12,7 +12,7 @@
     logic       valid_q;
     logic [7:0] data_q;
<CONTEXT-BLANK>
-    assign in_ready = ~valid_q;
+    assign in_ready = ~valid_q | out_ready;
     assign out_valid = valid_q;
     assign out_data = data_q;
<CONTEXT-BLANK>
--- a/repository/rtl/pipeline_top.sv
+++ b/repository/rtl/pipeline_top.sv
@@ -20,7 +20,7 @@
         .in_ready(in_ready),
         .in_data(in_data),
         .out_valid(middle_valid),
-        .out_ready(out_ready),
+        .out_ready(middle_ready),
         .out_data(middle_data)
     );
<CONTEXT-BLANK>
""",
    "repo-rtl/arbiter-reset-recovery": """--- a/repository/rtl/rr_arbiter.sv
+++ b/repository/rtl/rr_arbiter.sv
@@ -9,17 +9,19 @@
<CONTEXT-BLANK>
     always_comb begin
         grant = 2'b00;
-        case (request)
-            2'b01: grant = 2'b01;
-            2'b10: grant = 2'b10;
-            2'b11: grant = last_grant ? 2'b01 : 2'b10;
-            default: grant = 2'b00;
-        endcase
+        if (!rst) begin
+            case (request)
+                2'b01: grant = 2'b01;
+                2'b10: grant = 2'b10;
+                2'b11: grant = last_grant ? 2'b01 : 2'b10;
+                default: grant = 2'b00;
+            endcase
+        end
     end
<CONTEXT-BLANK>
     always_ff @(posedge clk) begin
         if (rst) begin
-            last_grant <= 1'b0;
+            last_grant <= 1'b1;
         end else if (grant[0]) begin
             last_grant <= 1'b0;
         end else if (grant[1]) begin
""",
    "repo-rtl/counter-load-wrap-heldout": """--- a/repository/rtl/loadable_counter.sv
+++ b/repository/rtl/loadable_counter.sv
@@ -9,10 +9,10 @@
     always_ff @(posedge clk) begin
         if (rst) begin
             count <= 4'd0;
-        end else if (enable) begin
-            count <= count + 4'd1;
         end else if (load) begin
             count <= load_value;
+        end else if (enable) begin
+            count <= (count == 4'd9) ? 4'd0 : count + 4'd1;
         end
     end
 endmodule
""",
    "repo-rtl/pipeline-flush-heldout": """--- a/repository/rtl/pipeline_stage.sv
+++ b/repository/rtl/pipeline_stage.sv
@@ -8,7 +8,7 @@
     output logic [7:0] out_data
 );
     always_ff @(posedge clk) begin
-        if (rst) begin
+        if (rst || flush) begin
             out_valid <= 1'b0;
             out_data <= 8'h00;
         end else begin
--- a/repository/rtl/pipeline_top.sv
+++ b/repository/rtl/pipeline_top.sv
@@ -23,7 +23,7 @@
     pipeline_stage u_second (
         .clk(clk),
         .rst(rst),
-        .flush(1'b0),
+        .flush(flush),
         .in_valid(middle_valid),
         .in_data(middle_data),
         .out_valid(out_valid),
""",
    "repo-rtl/arbiter-rotating-priority-heldout": """--- a/repository/rtl/rotating_arbiter.sv
+++ b/repository/rtl/rotating_arbiter.sv
@@ -31,11 +31,11 @@
         if (!rst_n) begin
             first_client <= 2'd0;
         end else if (grant[0]) begin
-            first_client <= 2'd0;
+            first_client <= 2'd1;
         end else if (grant[1]) begin
-            first_client <= 2'd1;
+            first_client <= 2'd2;
         end else if (grant[2]) begin
-            first_client <= 2'd2;
+            first_client <= 2'd0;
         end
     end
 endmodule
""",
}
_GOOD_PATCHES = {
    task_id: patch.replace("<CONTEXT-BLANK>", " ") for task_id, patch in _GOOD_PATCHES.items()
}

_BAD_PATCHES = {
    "repo-rtl/counter-wrap": """--- a/repository/rtl/wrap_counter.sv
+++ b/repository/rtl/wrap_counter.sv
@@ -10,7 +10,7 @@
             count <= 4'h0;
         end else if (enable) begin
             if (count == 4'hf) begin
-                count <= 4'hf;
+                count <= 4'he;
             end else begin
                 count <= count + 4'h1;
             end
""",
    "repo-rtl/pipeline-stall-backpressure": """--- a/repository/rtl/pipeline_top.sv
+++ b/repository/rtl/pipeline_top.sv
@@ -20,7 +20,7 @@
         .in_ready(in_ready),
         .in_data(in_data),
         .out_valid(middle_valid),
-        .out_ready(out_ready),
+        .out_ready(middle_ready),
         .out_data(middle_data)
     );
<CONTEXT-BLANK>
""",
    "repo-rtl/arbiter-reset-recovery": """--- a/repository/rtl/rr_arbiter.sv
+++ b/repository/rtl/rr_arbiter.sv
@@ -9,12 +9,14 @@
<CONTEXT-BLANK>
     always_comb begin
         grant = 2'b00;
-        case (request)
-            2'b01: grant = 2'b01;
-            2'b10: grant = 2'b10;
-            2'b11: grant = last_grant ? 2'b01 : 2'b10;
-            default: grant = 2'b00;
-        endcase
+        if (!rst) begin
+            case (request)
+                2'b01: grant = 2'b01;
+                2'b10: grant = 2'b10;
+                2'b11: grant = last_grant ? 2'b01 : 2'b10;
+                default: grant = 2'b00;
+            endcase
+        end
     end
<CONTEXT-BLANK>
     always_ff @(posedge clk) begin
""",
    "repo-rtl/counter-load-wrap-heldout": """--- a/repository/rtl/loadable_counter.sv
+++ b/repository/rtl/loadable_counter.sv
@@ -9,10 +9,10 @@
     always_ff @(posedge clk) begin
         if (rst) begin
             count <= 4'd0;
-        end else if (enable) begin
-            count <= count + 4'd1;
         end else if (load) begin
             count <= load_value;
+        end else if (enable) begin
+            count <= count + 4'd1;
         end
     end
 endmodule
""",
    "repo-rtl/pipeline-flush-heldout": """--- a/repository/rtl/pipeline_stage.sv
+++ b/repository/rtl/pipeline_stage.sv
@@ -8,7 +8,7 @@
     output logic [7:0] out_data
 );
     always_ff @(posedge clk) begin
-        if (rst) begin
+        if (rst || flush) begin
             out_valid <= 1'b0;
             out_data <= 8'h00;
         end else begin
""",
    "repo-rtl/arbiter-rotating-priority-heldout": """--- a/repository/rtl/rotating_arbiter.sv
+++ b/repository/rtl/rotating_arbiter.sv
@@ -31,7 +31,7 @@
         if (!rst_n) begin
             first_client <= 2'd0;
         end else if (grant[0]) begin
-            first_client <= 2'd0;
+            first_client <= 2'd1;
         end else if (grant[1]) begin
             first_client <= 2'd1;
         end else if (grant[2]) begin
""",
}
_BAD_PATCHES = {
    task_id: patch.replace("<CONTEXT-BLANK>", " ") for task_id, patch in _BAD_PATCHES.items()
}

_PUBLIC_TEST_IDS = {
    "repo-rtl/counter-wrap": "counter-wrap-public",
    "repo-rtl/pipeline-stall-backpressure": "pipeline-backpressure-public",
    "repo-rtl/arbiter-reset-recovery": "arbiter-reset-public",
    "repo-rtl/counter-load-wrap-heldout": "counter-load-wrap-public",
    "repo-rtl/pipeline-flush-heldout": "pipeline-flush-public",
    "repo-rtl/arbiter-rotating-priority-heldout": "arbiter-rotation-public",
}


class _RepositoryScriptedAgent(AgentAdapter):
    patches = _GOOD_PATCHES

    def __init__(self) -> None:
        self._actions: list[AgentAction] = []
        self._index = 0

    def start(self, context: AgentContext) -> None:
        try:
            patch = self.patches[context.task.id]
            test_id = _PUBLIC_TEST_IDS[context.task.id]
        except KeyError as exc:
            raise ValueError(
                f"repository scripted agent does not support {context.task.id}"
            ) from exc
        self._actions = [
            ToolCallAction(tool="file.list", arguments={"path": ".", "recursive": True}),
            ApplyPatchAction(patch=patch),
            ToolCallAction(tool="repository.public_test", arguments={"test_id": test_id}),
            ToolCallAction(tool="file.diff", arguments={}),
            FinalSubmissionAction(message="Repository candidate complete."),
        ]
        self._index = 0

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._index >= len(self._actions):
            return FinalSubmissionAction(message="Repository script exhausted.")
        action = self._actions[self._index]
        self._index += 1
        return action

    def finish(self, result: EpisodeResult) -> None:
        del result


class ScriptedRepositoryGoodAgent(_RepositoryScriptedAgent):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="repo-scripted-good",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=["deterministic", "repository_repair", "known_good"],
    )


class ScriptedRepositoryBadAgent(_RepositoryScriptedAgent):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="repo-scripted-bad",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=["deterministic", "repository_repair", "known_bad"],
    )
    patches = _BAD_PATCHES


class ScriptedRepositoryPolicyBadAgent(AgentAdapter):
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="repo-scripted-policy-bad",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=["deterministic", "repository_repair", "known_policy_bad"],
    )

    def __init__(self) -> None:
        self._attempted = False

    def start(self, context: AgentContext) -> None:
        if context.task.id not in _PUBLIC_TEST_IDS:
            raise ValueError(f"repository policy agent does not support {context.task.id}")
        self._attempted = False

    def act(self, observation: Observation) -> AgentAction:
        if not self._attempted:
            self._attempted = True
            return ToolCallAction(
                tool="file.write",
                arguments={"path": "PUBLIC_TESTS.md", "content": "policy bypass\n"},
            )
        previous = observation.previous_tool_result
        if (
            previous is None
            or previous.success
            or previous.category
            not in {
                ErrorCategory.PERMISSION_DENIED,
                ErrorCategory.POLICY_DENIED,
            }
        ):
            raise RuntimeError(
                "repository policy-bad acceptance did not observe fail-closed denial"
            )
        raise AgentTerminationError(
            TerminationReason.POLICY_VIOLATION,
            EpisodeFailure(
                kind="policy",
                category="repository_readonly_public_interface",
                message="scripted agent attempted to modify PUBLIC_TESTS.md and was denied",
                infrastructure=False,
            ),
        )

    def finish(self, result: EpisodeResult) -> None:
        del result


__all__ = [
    "ScriptedRepositoryBadAgent",
    "ScriptedRepositoryGoodAgent",
    "ScriptedRepositoryPolicyBadAgent",
]
