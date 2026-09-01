# OpenHands v36 provider-response root-cause correction

## Scope and immutable evidence

This is an append-only diagnosis of the sealed v36 PR-2330 attempt. It does not modify, retry,
reconstruct, relabel or admit that attempt. PR-2330 remains permanently unavailable to successor
canaries, PR-3204 was not called, and all collection and training flags remain false.

The v36 trace retained no raw provider content or tool arguments. It retained the root exception
type `V19ProtocolViolation` and the SHA-256 of its message:
`9b9bc4357b1abd6a319455ce3ce496292f1aec41cbcf6f2e93ba6e7c897a3418`. Hashing every static v19
provider-shape error maps that value uniquely to:

```text
OpenHands v19 provider response was not one content-free tool call
```

The empty-response message hashes to
`2b4f40d7859951ad738be3ed881c5e863ab7c7fa012758e4890bcc09c6aeeac0`, so the response was not
empty. The v19 branch that produced the observed hash runs only after provider token accounting
and rejects either non-empty public text accompanying tool calls or a tool-call count other than
one. The retained evidence cannot distinguish those two shapes because v19 did not retain a
content-free response-shape sidecar.

Consequently, the earlier v36 failed-closed audit's statement that the provider "made no required
tool call" was stronger than the retained evidence supports. Zero broker tool calls means only
that no provider call passed the pre-dispatch v19 gate. This correction preserves that earlier
audit as historical evidence and narrows the supported conclusion here.

## Primary-source comparison

The frozen SDK is OpenHands SDK 1.42.1, tag ref
`167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`; the installed
`openhands/sdk/agent/response_dispatch.py` hashes to
`7d3860934d86b2bfa28a55ef4ad2a69f4a3abe8f6b5a2d348cfdb4fdb0bf8dc4`.

OpenHands 1.42.1 gives tool calls precedence over visible content in `classify_response`. Its tool
handler keeps text content and supplies it to the first `ActionEvent` as `thought`. `ActionEvent`
then serializes that public thought together with the tool call back into the LLM-visible message.
Thus public text plus a tool call is a supported upstream response, not an SDK ambiguity:

- <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/agent/response_dispatch.py>
- <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/event/llm_convertible/action.py>

DeepSeek's current Chat Completions reference defines `tool_choice=required` as one or more tool
calls, not exactly one, and models assistant `content` as nullable alongside a separate
`tool_calls` array. It explicitly requires callers to validate generated arguments:

- <https://api-docs.deepseek.com/api/create-chat-completion/>
- <https://api-docs.deepseek.com/guides/tool_calls/>

The repository deliberately retains the stricter exactly-one-call invariant because the broker
executes one atomic decision at a time. The incompatibility was v19's additional requirement that
the otherwise canonical tool response contain no visible public text. The SDK and provider schemas
do not impose that condition.

## v20 correction

The successor `required_tool_public_thought_content_recovery_v20` policy changes only the disputed
response boundary:

- exactly one of the frozen six canonical HWE tools remains mandatory;
- optional public text content may accompany that tool and is retained in the first action;
- multiple calls, foreign tools, malformed or duplicate-key JSON, pseudo-finish calls, private
  reasoning, raw host paths and forbidden SDK metadata remain rejected before dispatch;
- the single content-only same-session recovery, 64-call limit, 1,000,000-token provider limit,
  65,536 context, 2,048 output limit and zero retry policy remain unchanged; and
- a content-free response-shape receipt records only counts, classification and presence booleans.
  Raw model content and raw tool arguments remain unpersisted.

V20 uses independent protocol, campaign-result, trajectory and decision receipt format IDs. Its
trajectory receipt explicitly supervises public tool thought and canonical tool decisions while
masking abnormal content-only responses and environment recovery feedback. Exact-64K decisions
continue to use `truncation=error`.

This correction is not retrospective evidence that the v36 response contained one canonical tool.
A multi-call v36 response remains possible. V20 will accept only the upstream-supported
single-tool-plus-public-text shape and will fail closed, with safe shape evidence, on multiple
calls. Any provider validation requires a new identity, changed task schedule, separate merged
authorization and green post-merge checks.
