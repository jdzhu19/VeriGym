# OpenHands v39 provider canary authorization

Date: 2026-09-01

Status: authorized in source, pending merge and green `main`; do not execute before both gates
pass.

## Purpose

This authorization permits one fresh two-episode provider canary for the append-only v21 atomic
multiple-tool response-shape recovery. It does not authorize a retry of PR-2330, PR-3226, or any
failed identity. It does not authorize formal collection, training, GPU use, or held-out loading.

The exact authorization is
`configs/training/qwen35_hwe_openhands_v39_provider_canary_v1.json`, with authorization hash
`4405e47077efcb527510302dca90632e1a8d76184a7dc49f0c686435cb12b586`.

## Why v21 and a new identity are required

The sealed v38 PR-3226 episode made one provider call. DeepSeek returned exactly two sibling tool
calls with no public text or private reasoning. V20 rejected the complete response before SDK or
broker dispatch, so no sibling call executed and PR-3204 did not start. V38 and PR-3226 remain
failed and frozen.

The response was transport-valid: DeepSeek documents `tool_choice=required` as one or more calls
and requires callers to validate generated function arguments:

- <https://api-docs.deepseek.com/api/create-chat-completion/>
- <https://api-docs.deepseek.com/guides/tool_calls/>

OpenHands SDK 1.42.1 iterates over every sibling call and may schedule multiple actions. The pinned
integration does not provide the serialized mutation/order/barrier semantics needed to execute
siblings safely:

- <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/agent/response_dispatch.py>
- <https://github.com/deepseek-ai/deepseek-harness/blob/master/.agents/notes/implemented/feature/2026-07-10-parallel-tool-call-execution.md>
- <https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/agent-loop/src/tool-calls.ts>

V21 therefore permits one narrow recovery instead of enabling sibling execution. On an exact
first response containing two tool calls, zero text parts, and no private reasoning, it rejects
both calls atomically before dispatch and substitutes a fixed, argument-free assistant message.
The existing Stop hook supplies fixed environment feedback. The next response must be exactly one
canonical allowlisted HWE call. Content-only and two-call recovery share one combined budget; a
second recovery, mixed text, any other sibling count, private reasoning, invalid JSON, or a
non-canonical action fails closed. Rejected tool names, IDs, arguments, and raw content do not enter
the OpenHands message, broker, trajectory, summary, or receipt.

The repair merged as `e651088f977c9854dde48b57cb7588df91380216`. Post-merge main Actions run
`33467383447` passed all eight required job classes. The protocol audit file SHA-256 is
`b33ac48757b6d2fa4420e95e1e82d45556a7703f5efe9adf10f3772563403600`.

## Frozen predecessor evidence

- v33 materialization audit merge:
  `648fe717e88b36876245df09e73222f906f83918`
- v33 evidence tree:
  `62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6`
- v33 catalog:
  `05be424d40014e7ef69106f85e5ea161db2bb8e70103c8d1279e4a7c118f8e05`
- v38 authorization merge:
  `e2583dc1997700387f3c74f526fb6b2e6f6a84b5`
- v38 failure audit merge:
  `99df7a674784c428527222a73828024a248f5174`
- v38 evidence tree:
  `e5e9d518b7f0bf24a0b32947b5ea42efb3d15ac96f44943918bcafeaf171f890`
- v38 report:
  `a90698e672c38c341735c130e1691e13370d44aa75a5b8bf298ec38e1dfb1e6a`
- v38 observed accounting: one episode, one provider call, one task attempt, zero broker decisions
- v38 failed task: PR-3226; retry authorization remains false
- v38 validation task: PR-3204; provider episode never started

The runner also retains the sealed v36 failure and v37 pre-output stop validations inherited by
v38. Before creating output it recomputes the v33, v36, v37, and v38 evidence trees and validates
the exact report, progress, agent-version, contract, preflight, attempt, command-image lock, and
security-scan file hashes. It reads no raw provider response.

## Exact v39 execution contract

The identity is `openhands-hwe-v39-atomic-shape-recovery-provider-canary-v1`, using agent version
`openhands-deepseek-v4-flash-hwe-v39-atomic-shape-recovery-canary-v1`, seed 492, sample 8,
temperature zero, and no whole-episode or provider-request retries. The host software closure fixes
OpenHands SDK 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, Transformers 4.57.6, NumPy 2.2.6, and Pillow
12.1.1.

The only permitted order is:

1. training: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231`
2. validation: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204`

PR-3231 has qualification and v33 command-image materialization evidence but no provider episode.
Its command-image lock is
`bfa5d99faf7f9c5e69dea173da717fd744f6db46d16c4a655f026e23fb2a6406`, and its v2 security scan
is `ef76407bb2565de32a241e67e06111f824edca11b1db06ff21a704dbd18e8941`. Using it for v39
permanently consumes it as a canary and means the later formal training schedule needs another
replacement. PR-3204 remains the unstarted validation canary and is not authorized unless PR-3231
passes first.

Each episode is capped at 64 provider calls, 1,000,000 provider tokens, a 65,536-token context,
and 2,048 output tokens. The command runtime is the locked `episode_container_exec_v1` image with
`network=none`, no external-agent image, no Codex, no provider credentials, and no hidden,
reference, or verifier assets. Provider URL/key values are checked only in memory and scanned
against output; their concrete values are never printed, persisted, or hashed.

The validation episode runs only if every training plane passes. Success requires verifier,
protocol, trajectory, infrastructure, security, and SFT-admission planes all true, plus complete
v21 trajectory and decision receipts, decision-only supervision, loss mask zero for the synthetic
shape-recovery message and recovery feedback, and exact-64K/no-truncation admission. Any failed
plane stops and seals v39 without retry.

## Merge and invocation gates

The authorization becomes executable only after its focused PR is merged into `origin/main` and
all eight required Actions classes pass on the resulting main commit. The runner independently
requires clean `HEAD == origin/main`, validates all predecessor merge ancestry and audit hashes,
checks the exact host dependency versions, validates both command containers and adapter starts
with zero provider calls, and requires the one-use opt-in
`VERIGYM_RUN_OPENHANDS_HWE_V39_PROVIDER_CANARY_V1=1` with the exact campaign identity.

The runner must be invoked once with the exact authorization, v33 materialization, sealed
v36/v37/v38 roots, PR-3231 and PR-3204 source roots, frozen tokenizer, and base-model lock. Output
must be the previously absent directory
`/data/jzhu484/Agent/experiments/openhands-hwe-v39-provider-canary-v1`. A preflight failure records
only its stage and exception type and uses zero provider calls.

Even if both v39 episodes pass, this stage sets only `formal_collection_allowed=true`. It must end
with `formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`. A separate audited image materialization and formal collection
authorization are still required before collection can begin.
