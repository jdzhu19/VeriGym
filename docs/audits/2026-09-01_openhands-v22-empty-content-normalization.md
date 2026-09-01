# OpenHands v22 SDK-normalized empty-content recovery

Date: 2026-09-01

## Status

- Append-only protocol implementation; this document does not authorize a provider call.
- V21, v39, and the consumed PR-3231 attempt remain immutable and failed closed.
- Formal collection, SFT, GPU use, and held-out loading remain disabled.
- A successor canary requires a new agent/runtime identity, fresh authorization, an unconsumed
  training task, and green post-merge main checks.

## Root cause

V39 received two provider tool calls with transport-level `content=""`, no non-empty public text,
and no private reasoning. Protocol v21 accepted the two-call recovery only when
`content_to_str(message.content)` returned an empty list. The pinned OpenHands SDK converted the
empty string to one `TextContent(text="")`, so v21 observed one text part and rejected the shape.
Its unit test had constructed `Message(content=[])` directly and did not exercise the real
LiteLLM-to-OpenHands conversion.

The upstream boundary was checked against primary project sources:

- OpenHands SDK 1.42.1 `Message.from_llm_chat_message` wraps every string-valued Chat Completions
  content in one `TextContent`, including an empty string:
  <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/llm/message.py>.
- DeepSeek's Chat Completions schema permits one or more calls under required tool choice, so the
  adapter must retain its local exact-one dispatch boundary:
  <https://api-docs.deepseek.com/api/create-chat-completion/> and
  <https://api-docs.deepseek.com/guides/tool_calls/>.
- LiteLLM's upstream issue record shows DeepSeek tool-call assistant messages using string empty
  content or `null`, rather than an empty content list:
  <https://github.com/BerriAI/litellm/issues/9905>.

The repository-specific difference is deliberate: VeriGym does not adopt general parallel tool
dispatch. It atomically rejects both sibling calls, retains no raw call content or arguments, and
uses one bounded same-session recovery before requiring exactly one canonical replacement call.

## V22 contract

V22 leaves v19, v20, v21, and all historical canary artifacts unchanged. It keeps the exact six
HWE tools, 64 provider-call limit, 1,000,000 cumulative provider-token limit, 65,536-token
context, 2,048-token output limit, greedy sampling, one shared Stop-hook recovery, and zero
whole-episode retries.

The only new admissible recovery shape is the SDK-normalized equivalent of v21's text-free shape:

1. Exactly two tool calls.
2. Either zero text parts, or exactly one `TextContent` whose value is exactly `""`.
3. Zero non-empty text parts and no reasoning content, Responses reasoning, or thinking blocks.
4. No previous content-only or multi-tool recovery.

Both calls are rejected atomically before SDK or broker dispatch. The returned assistant message
contains only the same fixed, argument-free synthetic recovery notice used by v21. The provider's
tool names, call IDs, content, and arguments are not copied into the replacement message or safe
receipt. The existing Stop hook then supplies fixed environment feedback, and the next provider
response must be one allowlisted tool with strict JSON and a canonical HWE v2 action.

The following continue to fail closed:

- whitespace-only or non-empty text;
- two or more empty text parts;
- image content;
- any private reasoning field;
- any tool-call count other than the exact two-call recovery or exact one-call dispatch;
- a second recovery, illegal tool, malformed or duplicate-key JSON, non-canonical action, or
  provider/accounting drift.

## Receipt and identity changes

- New tool policy: `required_tool_atomic_shape_recovery_v22`.
- New harness identity: `openhands-sdk-1.42.1-hwe-native-shell-v22`.
- New protocol, campaign-result, trajectory, and decision receipt format IDs are all v22-specific.
- The protocol receipt freezes recoverable text-part counts `[0, 1]`, permits only SDK-normalized
  exact-empty content, and explicitly forbids non-empty or whitespace content.
- A recovered response shape records counts and presence booleans only. Raw rejected provider
  content and raw tool arguments remain unpersisted.
- Synthetic recovery content and feedback remain input-only with loss mask zero; canonical tool
  decisions and allowed public tool thought retain loss mask one.

## Verification

Completed locally without provider credentials or network execution:

- Ruff checks for all changed Python files: passed.
- Python 3.12 OpenHands source mypy: passed for 42 source files.
- Focused v21/v22 protocol tests: 24 passed.
- Full OpenHands integration tests: 410 passed, 15 opt-in/materialization-dependent skips.
- Core credential-free tests: 1,065 passed, 1 real-Codex opt-in skip, 52 deselected.
- HWE integration tests: 50 passed; mypy passed for 9 source files.
- Tracked repository and new-file Ruff/format checks passed; core mypy passed for 208 source
  files.
- Real-shape regression constructs a LiteLLM assistant message with `content=""` and two tool
  calls, converts it through `Message.from_llm_chat_message`, proves v22 recovers it, and proves
  unchanged v21 rejects the same normalized message.
- Negative regressions cover whitespace, multiple empty parts, image content, public mixed text,
  private reasoning, wrong sibling counts, repeated recovery, receipt drift, six result planes,
  and exact-64K decision sealing.

Package, reproducible-build, Docker security, ordinary PR checks, and post-merge main checks
remain required before a successor authorization may be proposed.

## State after this repair

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false` remain unchanged. No provider call, benchmark score, formal
collection episode, or training run is authorized or performed by v22.
