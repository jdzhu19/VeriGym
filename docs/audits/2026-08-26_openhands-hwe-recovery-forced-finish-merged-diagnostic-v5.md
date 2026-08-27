# OpenHands HWE merged-recovery forced-finish diagnostic v5

Date: 2026-08-26

This audit records one bounded PR-2032 termination diagnostic. It is not a benchmark score, a
verifier-pass trajectory, or a training-readiness claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed 484
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- ordinary tool choice: `auto`; recovery request: named `finish`
- limits: 65,536 context tokens, 2,048 output tokens, 200 iterations, no retry
- source commit: `e371306aa205b6a72af8f46236c716fc7916f642`
- agent version hash: `88e7d40f5865fda25dca24f08be855c5a5a0e2e51af87b7d7cb1761430ecd88f`
- prior v4 report hash: `efdddafc0b023fd955fe2b9e214f13d3b3ed5bd1181bc5ce5a97f8fdb1b5b7c7`

## Result

The ordinary phase made 14 accepted typed actions: nine reads and five shell calls. The model then
produced content-only completion, and the trusted Stop hook denied it once in the same session. The
v5 final-content-block detector did not cause the subsequent provider request to reach the broker as
typed `finish`; the exhausted hook allowed the second content-only stop to unwind.

The run was infrastructure-valid, with no rejected broker calls or broker failures, but failed as
`openhands_hwe_missing_finish`. It made no patch, did not resolve the ordinary verifier, and exported
no trajectory or dataset row. Wall time was 280.981 seconds. The credential scan covered 5,976 files
and 117,134,402 bytes with zero provider-value matches.

- report hash: `90cb6fe64ea6e03d4e9ae3c2967b52ed7c29409907bc758db5d743d014cd6cfe`
- GPU/HPC jobs, optimizer steps, checkpoints, and adapters: zero

## Interpretation

A bounded direct replay through the same VeriGym LLM subclass, OpenHands SDK, LiteLLM, provider,
and named tool selection returned one `finish` tool call with `finish_reason=tool_calls`. The
provider and SDK response parser therefore support this request. The remaining weak boundary was
the OpenHands agent's effective recovery-message representation. The v6 policy instead consumes the
Stop hook's already-existing private, hash-bound recovery receipt and fails closed on any receipt
mismatch; it no longer infers recovery from conversation-message layout.
