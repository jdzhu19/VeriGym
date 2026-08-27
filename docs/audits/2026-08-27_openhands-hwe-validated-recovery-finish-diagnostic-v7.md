# OpenHands HWE validated-recovery finish diagnostic v7

Date: 2026-08-27

This audit records one bounded PR-2032 termination diagnostic. It is not a benchmark score, a
verifier-pass trajectory, or a training-readiness claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed 484
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- ordinary tool choice: `auto`; receipt-bound recovery request: named and validated `finish`
- limits: 65,536 context tokens, 2,048 output tokens, 200 iterations, no retry
- source commit: `f237ac7eb84e58cb01370147319b7242d943f07c`
- agent version hash: `31db37f498ead515316065145cdab9bfc919e1eefbec01133b8155d5d7348052`
- prior v6 report hash: `82772f30f11a65e364f78cca674f5467cb6d8acc2bcc6716bf098016e4d73366`

## Result

The run made 26 ordinary accepted actions: 12 reads, one list, and 13 shell calls. The model then
produced content-only completion, and the trusted Stop hook denied it once and wrote the exact
private recovery receipt. The v7 LLM guard sent named `finish`, recorded forced-request count 1,
received a response that was not exactly one `finish`, and raised `RecoveryToolChoiceViolation`
before OpenHands dispatched any recovery response to the broker. Validated-finish count remained 0.

OpenHands wrapped the controlled violation in `ConversationRunError`. The v7 adapter checked only
the outer exception type, so it emitted the causal failure receipt but then classified the episode
as `openhands_hwe_sdk_episode`. Normal broker/summary evidence was not written, and the report
correctly remained `infrastructure_invalid`. No patch, finish, positive trajectory, or dataset row
was produced. Wall time was 498.563 seconds. The credential scan covered 5,971 files and 117,632,391
bytes with zero provider-value matches.

- report hash: `dc9b36d8a3a05f71a39ba45e2c599403c7043b7cb45606f0455b80cb10ac4bce`
- trace SHA-256: `911790a6c465c533b8936ce63cf9509c8f5a3eddcef0b3c9396063bcf1ad1b0f`
- GPU/HPC jobs, optimizer steps, checkpoints, and adapters: zero

## Interpretation

The important safety property succeeded: unlike v6, the provider's non-finish recovery response
did not become another repository action. The remaining defect was evidence finalization after the
SDK wrapped the local exception. The v8 adapter walks at most eight controlled cause/context links,
recognizes only its own `RecoveryToolChoiceViolation`, persists the broker summary and both counters,
and reports the outcome as a model protocol rejection rather than an infrastructure failure. It
does not weaken the six-tool contract, synthesize `finish`, or retry the provider request.
