# OpenHands HWE recovery-state forced-finish diagnostic v6

Date: 2026-08-27

This audit records one bounded PR-2032 termination diagnostic and its controlled interruption. It
is not a benchmark score, a verifier-pass trajectory, or a training-readiness claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed 484
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- ordinary tool choice: `auto`; receipt-bound recovery request: named `finish`
- limits: 65,536 context tokens, 2,048 output tokens, 200 iterations, no retry
- source commit: `4d1f3fb26b45420b46d3b31ca8ee2bdbf15d778f`
- agent version hash: `03f28f172331e3c3f8fa5e73bd7154f670a9a247fc219562a287f5363db89563`
- prior v5 report hash: `90cb6fe64ea6e03d4e9ae3c2967b52ed7c29409907bc758db5d743d014cd6cfe`

## Result

The run made 69 accepted typed actions: 11 reads and 58 shell calls. The model produced one
content-only completion, and the trusted Stop hook denied it once and wrote the exact private
recovery receipt. Further ordinary tools reached the broker instead of typed `finish`. Because a
valid recovery must finish on its first provider response, the run was already protocol-invalid;
the exact runner PID was interrupted after 69 actions to prevent further API consumption.

OpenHands recorded one `InterruptEvent` and one synthetic `AgentErrorEvent` for the orphaned shell
action during orderly cancellation. The broker had no rejection or infrastructure failure, but no
finish or patch. The ordinary verifier did not resolve, and no trajectory or dataset row was
exported. Wall time was 1,376.424 seconds. The credential scan covered 5,976 files and 117,262,214
bytes with zero provider-value matches.

- report hash: `82772f30f11a65e364f78cca674f5467cb6d8acc2bcc6716bf098016e4d73366`
- GPU/HPC jobs, optimizer steps, checkpoints, and adapters: zero

## Interpretation

The v6 report marked its evidence complete because that format did not exclude `InterruptEvent`;
the audit therefore treats `infrastructure_valid=true` as a known classifier defect, not a valid
ordinary episode. Separate bounded replays through the same LLM subclass, OpenHands SDK, LiteLLM,
provider, and all six effective tool schemas returned exactly one named `finish` on short context.
The failure is consequently specific to the actual agent recovery response or its long history,
not basic schema/provider compatibility.

The v7 policy validates the provider response before OpenHands dispatch. It records one forced
request and one validated finish as separate acceptance evidence, rejects every non-finish response
immediately, and makes any `InterruptEvent` evidence-incomplete. This prevents the v6 action loop
and false-positive report classification without synthesizing a tool action.
