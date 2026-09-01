# OpenHands v38 provider canary authorization

Date: 2026-09-01

Status: authorized in source, pending merge and green `main`; do not execute before both gates pass.

## Purpose

This authorization permits one fresh two-episode provider canary for the v20 public-thought
protocol. It does not authorize a retry of the sealed v36 PR-2330 attempt, formal collection,
training, GPU use, or held-out loading.

The exact authorization is
`configs/training/qwen35_hwe_openhands_v38_provider_canary_v1.json`, with authorization hash
`b5f18acb9165a759c13da78fd1773b4422e8a3bb080115c54b7a16a535e2f6e4`.

## Why the successor chain is required

The sealed v36 PR-2330 episode made one provider call and failed before broker dispatch because
v19 required the response to be both a single tool call and content-free. The persisted redacted
failure identity cannot distinguish a missing tool call from a valid tool call accompanied by
visible text, so the earlier statement that the model made no tool call is not supported by the
sealed evidence. The correction and hash-level diagnosis are recorded in
`2026-09-01_openhands-v36-provider-response-root-cause.md` and were merged at
`24705dff206845cb8741a7cadeeaeaa6913cc178`.

The v20 implementation follows these upstream boundaries:

- OpenHands SDK v1.42.1 dispatches tool calls before text and preserves response text as the
  action's public `thought`: <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/agent/response_dispatch.py>
- The corresponding `ActionEvent` includes that thought with the tool call:
  <https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/event/llm_convertible/action.py>
- DeepSeek's Chat Completions contract permits nullable content and a `tool_calls` list, while
  `tool_choice=required` means one or more tool calls rather than exactly one:
  <https://api-docs.deepseek.com/api/create-chat-completion/>
- DeepSeek documents that generated tool arguments must be validated by the caller:
  <https://api-docs.deepseek.com/guides/tool_calls/>
- OpenHands issue 3992 is a related upstream report about tool-call/content response handling:
  <https://github.com/OpenHands/software-agent-sdk/issues/3992>

The local policy remains intentionally stricter than the provider API: exactly one of the six
allowlisted HWE tools is accepted, arguments are strict duplicate-key-free JSON, private reasoning
is rejected, and raw response content or tool arguments are not persisted in the safe response
shape. Public visible text accompanying the one tool call is retained as the supervised action
thought. A single content-only response may use the existing same-session recovery; its abnormal
text and environment feedback remain input-only and loss-masked.

The separately authorized v37 identity never reached its output creation, provider service, or
task loop. Its fresh Python 3.12 environment resolved NumPy 2.5.2, whose native extension required
`CXXABI_1.3.9` after the process had already loaded a system `libstdc++` exposing only
`CXXABI_1.3.7`. The failure was therefore classified as infrastructure-invalid before output and
sealed with zero provider episodes, zero provider calls, and zero task attempts. The v38 repair
pins NumPy 2.2.6 and Pillow 12.1.1 and requires the tokenizer import to pass before output creation.
This follows NumPy's official guidance to inspect binary/runtime compatibility, the NumPy 2.2.6
release's Python 3.10–3.13 support, and uv's documented newest-compatible default resolution:

- <https://numpy.org/doc/stable/user/troubleshooting-importerror.html>
- <https://numpy.org/doc/2.3/release/2.2.6-notes.html>
- <https://docs.astral.sh/uv/concepts/resolution/>

## Frozen predecessor evidence

- v33 materialization audit merge:
  `648fe717e88b36876245df09e73222f906f83918`
- v33 evidence tree:
  `62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6`
- v33 catalog:
  `05be424d40014e7ef69106f85e5ea161db2bb8e70103c8d1279e4a7c118f8e05`
- v36 failure audit merge:
  `e650953f5d508c1b53dc35c325944108d4b90420`
- v36 evidence tree:
  `ccf9094dfe373587454346f5b52b4a8f7d3ade828b4f15b524c63d14a6d26f4d`
- v36 report:
  `debf637e7697c921c24898a027a907d045514c0f7f65d131ad7e3471998124d0`
- v36 observed accounting: one episode, one provider call, no retry
- v37 pre-output stop audit merge:
  `9f5e0153047c10eb1e799e98075af8d4ac6b73c8`
- v37 stop evidence tree:
  `796b2f56316c4b0b2fb0392b3ea8b218bc2f84030e9a79c30c0e46227d241ee9`
- v37 stop receipt:
  `ef98bbdda2329fa0746c8c24c5fd51e614007a73347371654d0e86ebcc48377e`
- v37 observed accounting: zero episodes, zero provider calls, zero task attempts

The runner revalidates those trees and individual report, progress, agent-version, contract,
preflight, attempt, stop-receipt, command-image-lock, and security-scan file hashes before creating
output.

## Exact v38 execution contract

The identity is `openhands-hwe-v38-numpy-pinned-provider-canary-v1`, using agent version
`openhands-deepseek-v4-flash-hwe-v38-numpy-pinned-public-thought-canary-v1`, seed 491,
sample 7, temperature zero, and no whole-episode or provider-request retries. The host-side
software closure fixes OpenHands SDK 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, Transformers 4.57.6,
NumPy 2.2.6, and Pillow 12.1.1.

The only permitted order is:

1. training: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3226`
2. validation: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204`

Both tasks have never previously started a provider episode. PR-2330 is absent from the v38
schedule and may not be retried. PR-3226 was a v33 training reserve; using it here permanently
marks `training_reserve_consumed_by_canary=true` and
`formal_training_schedule_requires_replacement=true`. It therefore cannot also be counted as a
fresh formal-collection task.

Each episode is capped at 64 provider calls, 1,000,000 provider tokens, a 65,536-token context,
and 2,048 output tokens. The command runtime is the locked `episode_container_exec_v1` image,
with `network=none`, no external-agent image, no Codex, no provider credentials, and no hidden or
verifier assets. Provider URL/key values are checked only in memory and scanned against output;
their concrete values are never printed, persisted, or hashed.

The validation episode runs only if every training result plane passes. Success requires verifier,
protocol, trajectory, infrastructure, security, and SFT-admission planes all true, plus a complete
trajectory receipt, decision-only loss mask, public-thought supervision, and exact-64K/no-truncation
receipt. Infrastructure or security invalidity stops immediately. Any other plane failure also
stops and seals the identity without retry.

## Merge and invocation gates

The authorization becomes executable only when its focused PR is merged into `origin/main` and
all eight required Actions classes pass on the resulting main commit. The runner independently
requires a clean `HEAD == origin/main`, verifies the predecessor merges and audit hashes, and
requires all six frozen host dependency versions plus the one-use opt-in
`VERIGYM_RUN_OPENHANDS_HWE_V38_PROVIDER_CANARY_V1=1` together with the exact campaign identity.

Before any provider episode it runs a zero-call control-plane, command-image, runtime-manifest,
and adapter-start preflight for both tasks. A preflight failure records only the stage and exception
type and uses zero provider calls.

Even if both v38 episodes pass, this stage sets only `formal_collection_allowed=true`. It must end
with `formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`. A separate audited materialization and formal authorization are
still required before collection can begin.
