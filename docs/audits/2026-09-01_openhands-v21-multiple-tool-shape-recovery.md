# OpenHands v21 multiple-tool response-shape recovery

Date: 2026-09-01

## Status

- Protocol implementation only; no provider execution is authorized by this document.
- `openhands-hwe-v38-numpy-pinned-provider-canary-v1` remains failed and frozen.
- The v38 PR-3226 attempt must not be rerun or reclassified.
- Formal collection, SFT, GPU use, and held-out loading remain disabled.
- A successor canary requires a distinct agent/runtime identity, fresh eligible tasks, a separate
  authorization merge, and green post-merge main checks.

## Observed failure and upstream behavior

The sealed v38 first response contained two tool calls, no non-empty public text, and no private
reasoning. V20 rejected the response before OpenHands or the HWE broker dispatched either call.
The failed episode used one provider request, produced zero broker decisions and zero tool,
command, read, write, patch, or finish events, and did not start PR-3204.

The failure exposed a contract mismatch rather than an infrastructure failure:

- DeepSeek documents `tool_choice=required` as requiring **one or more** tools, not exactly one:
  <https://api-docs.deepseek.com/api/create-chat-completion/>.
- The same API schema warns callers to validate generated arguments before executing a function.
- OpenHands SDK 1.42.1 iterates over every sibling tool call and its async path schedules the
  resulting actions through the multi-action executor:
  <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/agent/response_dispatch.py>.
- DeepSeek's newer harness treats sibling-call execution as an explicit scheduler problem with
  argument-sensitive parallel eligibility, exclusive mutation barriers, model-order commits, and
  abort handling:
  <https://github.com/deepseek-ai/deepseek-harness/blob/master/.agents/notes/implemented/feature/2026-07-10-parallel-tool-call-execution.md>
  and
  <https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/agent-loop/src/tool-calls.ts>.

The pinned OpenHands integration does not implement those scheduler invariants. Merely deleting
v20's exact-one check would therefore allow multiple sibling actions to enter SDK dispatch and
would change the frozen broker decision order and mutation boundary.

## V21 repair contract

V21 is append-only and leaves v19, v20, v37, and v38 evidence unchanged. It keeps the same exact
six HWE tools, 64 provider-call limit, 1,000,000 cumulative provider-token limit, 65,536-token
context, 2,048-token output limit, greedy sampling, one Stop-hook recovery, and zero whole-episode
retries.

The new recovery path is deliberately narrower than general sibling-call support:

1. Only a first response containing exactly two tool calls, zero text parts, and no private
   reasoning is recoverable.
2. Both calls are rejected atomically before OpenHands dispatch. No tool name, call ID, or raw
   argument enters the returned OpenHands message, broker, trajectory, summary, or failure receipt.
3. The adapter returns one fixed, argument-free assistant message whose SHA-256 is frozen by the
   v21 protocol receipt. The existing trusted Stop hook adds its fixed environment feedback in the
   same session.
4. Content-only recovery and two-call shape recovery share a single budget. Either consumes the
   only recovery; they cannot be combined.
5. The next provider response must contain exactly one allowlisted tool with strict JSON and a
   canonical HWE v2 action. A second multiple-call response, any other sibling count, mixed text,
   private reasoning, illegal tool, non-canonical arguments, counter drift, or budget drift fails
   closed.
6. Provider usage is accounted after receipt and before dispatch. The protocol receipt reconciles
   successful provider responses as canonical decisions plus the single optional rejected shape,
   while broker decisions equal canonical responses only.
7. The fixed synthetic recovery message and Stop-hook feedback are retained only as future-decision
   input and have loss mask zero. Canonical tool decisions and permitted public tool thought retain
   loss mask one.

## Security and artifact implications

- Accepted responses still dispatch at most one tool call.
- Rejected sibling calls never produce `ActionEvent` or broker tool receipts.
- Raw rejected provider content and arguments remain transient and are not persisted.
- The safe recovery sidecar records only response shape booleans/counts and fixed hashes.
- The installed OpenHands SDK remains unmodified.
- This protocol repair does not authorize a provider call and does not make v38 evidence eligible.

## Required verification before successor authorization

- Focused sync/async tests for atomic replacement, no raw-argument persistence, exact-one recovery,
  shared recovery exhaustion, mixed-content rejection, receipt drift, six planes, and exact 64K.
- Existing v19/v20 protocol and isolation regressions.
- Full OpenHands credential-free tests and Python 3.12 type checking.
- Repository Ruff, format, mypy, core/HWE/OpenHands tests, package/reproducible-build, and Docker
  security checks through the ordinary eight-class PR and post-merge main workflows.
