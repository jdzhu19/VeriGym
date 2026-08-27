# OpenHands HWE validated-recovery finish diagnostic v8

Date: 2026-08-27

This audit records one bounded PR-2032 termination diagnostic. It is not a benchmark score, a
verifier-pass trajectory, or a training-readiness claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed 484
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- ordinary tool choice: `auto`; receipt-bound recovery request: named and validated `finish`
- limits: 65,536 context tokens, 2,048 output tokens, 200 iterations, no retry
- source commit: `767ed72c65056e7ae4f0ab1451ff80f1af780bc4`
- agent version hash: `dbca4e86c1efe65b0ea212a1e3a4295bacc0ba0b9e0c9e5a0b3f25439932127e`
- prior v7 report hash: `dc9b36d8a3a05f71a39ba45e2c599403c7043b7cb45606f0455b80cb10ac4bce`
- prior v7 trace SHA-256: `911790a6c465c533b8936ce63cf9509c8f5a3eddcef0b3c9396063bcf1ad1b0f`

## Result

The ordinary phase made 12 accepted typed actions: seven reads and five shell calls. The model then
produced content-only completion, and the trusted Stop hook denied it once and wrote the exact
private recovery receipt. The v8 LLM guard sent named `finish`, recorded forced-request count 1,
received a response that was not exactly one `finish`, and raised `RecoveryToolChoiceViolation`
before OpenHands dispatched any recovery response to the broker. Validated-finish count remained 0.

The adapter recognized that violation through OpenHands' `ConversationRunError` causal chain,
persisted normal broker/accounting/summary evidence, and classified the result as the
infrastructure-valid model failure `openhands_hwe_recovery_tool_choice_violation`. There was no
`InterruptEvent`, broker rejection, broker infrastructure failure, patch, finish, positive
trajectory, or dataset row. The ordinary verifier remained unresolved. Wall time was 244.949
seconds. The credential scan covered 5,976 files and 117,015,678 bytes with zero provider-value
matches.

- report hash: `5bfc3f0de6a73cad47659542c9f4c699e172effaf096767802675243ce28b723`
- private broker receipt: 12 records, SHA-256
  `5c531e20e89899fac14ca32f74018494f2c5b299de5ff0659b8606f7e7162dd1`
- GPU/HPC jobs, optimizer steps, checkpoints, and adapters: zero

## Interpretation

The adapter defects are fixed: a non-finish recovery response can no longer become another
repository action, the run cannot loop after recovery, and the SDK wrapper no longer turns the
controlled model protocol violation into an infrastructure error. The remaining failure is the
actual provider/model response under the full agent history. Short bounded compatibility probes
with the same SDK, provider, and all six tool schemas did return one typed `finish`, but this real
history did not.

The run therefore does not qualify OpenHands trajectory collection for this model. No tool schema
was removed, no context was truncated, no `finish` was synthesized, and no retry was used to force
a pass. The next development step should address provider/model behavior or train/evaluate a model
that reliably follows the named-finish contract; the current bridge will fail closed until then.
