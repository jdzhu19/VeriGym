# OpenHands HWE recovery-forced-finish diagnostic v4

Date: 2026-08-26

This audit records one bounded PR-2032 termination diagnostic. It is not a benchmark score, a
verifier-pass trajectory, or a training-readiness claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed 484
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- ordinary tool choice: `auto`; recovery request: named `finish`
- limits: 65,536 context tokens, 2,048 output tokens, 200 iterations, no retry
- source commit: `0d3a802406aa6d104ef707015f7ee170b96dce74`
- agent version hash: `7de6285e4278158831b4192d907bc3338ebaba7a05bd84106b30f3ed835be93f`
- prior v3 report hash: `e4b40518c0d5b42d1fbbde5e115bacaeb588e4671e01e5f8627fcb456b8115d3`

## Result

The ordinary `auto` phase made 13 accepted typed actions: seven reads and six shell calls. The
model then produced content-only completion, the trusted Stop hook denied it once, and the same
session received canonical feedback. The recovery detector required that feedback to be the only
content block in the latest user message. OpenHands had merged adjacent plain-user blocks, so the
detector did not select named `finish`; the second response was content-only and the exhausted
hook allowed the SDK to unwind.

The run was infrastructure-valid, with no rejected broker calls or broker failures, but failed as
`openhands_hwe_missing_finish`. It made no patch and exported no verifier result, trajectory, or
dataset row. Wall time was 314.657 seconds. The credential scan covered 5,976 files and
116,968,358 bytes with zero provider-value matches.

- report hash: `efdddafc0b023fd955fe2b9e214f13d3b3ed5bd1181bc5ce5a97f8fdb1b5b7c7`
- GPU/HPC jobs, optimizer steps, checkpoints, and adapters: zero

## Interpretation

A separate no-repository compatibility probe confirmed that the endpoint can return a tool call
for named `finish`; the failure was local recovery-message recognition. The v5 policy therefore
matches an exact canonical final content block instead of requiring an exact whole message. It
still rejects substrings, modified feedback, and any untrusted trailing block.
