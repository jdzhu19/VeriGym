# OpenHands v39 provider canary failed closed

Date: 2026-09-01

Status: sealed ordinary protocol failure; v39 and PR-3231 may not be retried.

## Outcome

The authorized v39 command ran once from merged `main` commit
`732d82f835e9c2ba9e0b681244e5edc1410c1484`, after main Actions run `33469070755`
passed all eight required job classes. The zero-provider Docker preflight passed all five stages:
the control plane plus command-image and adapter startup for PR-3231 and PR-3204. It recorded zero
provider episodes and zero provider calls.

The first scheduled training episode,
`hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231`, made one provider call. The normalized
response contained exactly two sibling tool calls, no non-empty visible text, and no private
reasoning. OpenHands SDK 1.42.1 represented the empty Chat Completions `content` string as one
`TextContent` item, producing this sanitized shape:

- classification: `tool_calls`
- tool-call count: 2
- text-part count: 1
- non-empty text-part count: 0
- reasoning, Responses reasoning, and thinking blocks: absent

Protocol v21 required `text_part_count=0` for its one permitted atomic two-call recovery. It
therefore rejected this semantically text-empty SDK-normalized shape as a protocol violation. No
sibling call was dispatched. The broker recorded zero decisions, zero tool calls, zero commands,
zero file reads, zero mutations, zero patches, and zero finish calls. The unchanged candidate then
failed its hidden regression as an ordinary test failure.

The resulting six planes were:

- verifier: false
- protocol: false
- trajectory: false
- infrastructure: true
- security: true
- SFT admission: false

The runner stopped immediately. The PR-3204 validation episode did not run. Final state remains
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`. No benchmark score is claimed.

## Frozen accounting and evidence

- authorization merge: `732d82f835e9c2ba9e0b681244e5edc1410c1484`
- authorization hash: `4405e47077efcb527510302dca90632e1a8d76184a7dc49f0c686435cb12b586`
- evidence tree: `1fee66ee5a9f3902ce726a4459da875ba2dccb13c576763c2a4b5d6b44bac6be`
- report hash: `072f237207f22f7f04a640819bded258d05e880ffc634340739e956064b03077`
- report/progress file SHA-256:
  `3f9f65de1f5e585c58630d30e49d8576aefbefc6cbc33001396400d85b08acca`
- attempt file SHA-256:
  `f4709f0cb1901fba17adfcdd05eb931ebd8f8d7685dd495efef8882ef384b7ff`
- agent-version hash: `0f16474f7803326d726905a28e7e178ff0871f0093c64a514a90d0b8c59602f9`
- agent-version file SHA-256:
  `66d708d480e45a1abb51d851418c5e192ad36efa7d6e50a81fdc3d133c828a95`
- contract receipt hash: `5cf8bd093be852361fe3019f7a2a23be08ebde5928cab545f27e03015506b29e`
- contract receipt file SHA-256:
  `4accedc50bb29bbd115454fe0c9889f0f1757d9f84a8da0de4457470c6e978c0`
- zero-call preflight receipt hash:
  `789201e5ec09b21d1b3929f766f35b312dd2297b1bdbaaa2de2e58460d109c23`
- zero-call preflight file SHA-256:
  `f94fae2197462cd870f8c52174b377fe15a38de8fca1de739a8d80aa5e878255`
- run hash: `0186b2560ea5c545c9cc58f065de7b28479fe5edb631153ec0a5d94cdc6af125`
- security-scan hash: `59a9e564dc07a0161f2216c23784c54532890ee6a085cb09efddc46abe8f5f7b`
- security-scan file SHA-256:
  `83079b8de700a2c54e19b72ba186e70370253ef76de838794f34afa869f460a5`
- provider accounting: one episode, one call, 2,468 input tokens, 69 output tokens
- provider-value scan: passed across 7,703 files and 179,882,888 bytes; zero hits
- security scan: passed; zero hard-secret findings and zero scanner errors
- raw repository-observation records: zero
- output symlinks: zero

The evidence remains external under
`/data/jzhu484/Agent/experiments/openhands-hwe-v39-provider-canary-v1`. It is not committed.
Provider URL/key values, raw model content, raw tool arguments, tool names, tool-call IDs, and
private reasoning were neither printed nor persisted nor hashed.

## Root cause and upstream boundary

V21 checked `not text_parts`, where `text_parts` is the list returned by OpenHands
`content_to_str()`. Its unit test constructed a response with `content=[]`, so it covered
`text_part_count=0` but not the pinned SDK's Chat Completions conversion of an empty string.

OpenHands SDK 1.42.1 converts any string-valued Chat Completions content into one `TextContent`,
including the empty string, while its Responses API path omits an empty aggregate string:

- <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/llm/message.py>

DeepSeek documents that tool choice may yield one or more calls. The LiteLLM upstream repository
also records that DeepSeek tool-call assistant messages require string content such as the empty
string (or `null`) rather than an empty content list:

- <https://api-docs.deepseek.com/api/create-chat-completion/>
- <https://api-docs.deepseek.com/guides/tool_calls/>
- <https://github.com/BerriAI/litellm/issues/9905>

This evidence supports a local semantic predicate of “no non-empty public text,” independent of
whether the pinned SDK normalizes transport-level empty content to zero or one empty text parts.
It does not support accepting whitespace, mixed non-empty content, private reasoning, another
sibling count, invalid JSON, or repeated recovery.

## Successor constraints

Any repair must use a new append-only protocol and agent/runtime identity. V39, PR-3231, and the
observed attempt remain immutable. PR-3204 remains unstarted but unauthorized until a separately
reviewed successor contract merges and its main checks pass.

A safe v22 repair may admit exactly two calls when `nonempty_text_part_count=0`, every content item
is a `TextContent` whose value is exactly the empty string, and all reasoning fields are absent.
It must still reject both calls atomically before dispatch, expose no raw call data, share the
single recovery budget with content-only recovery, require exactly one canonical replacement
call, and loss-mask the fixed synthetic recovery turn. Whitespace-only or image content must fail
closed. Tests must reproduce the pinned Chat Completions conversion through
`Message.from_llm_chat_message`, not only construct `Message(content=[])` directly.

PR-3231 is permanently consumed by this canary and may not be retried or counted as a fresh formal
collection task. The formal training schedule therefore needs another replacement in addition to
the replacements already required for PR-2330 and PR-3226.
