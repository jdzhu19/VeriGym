# OpenHands HWE required-tool-choice diagnostic v3

Date: 2026-08-26

This audit records one bounded PR-2032 termination diagnostic. It is not a benchmark score, a
verifier-pass trajectory, or a training-readiness claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed 484
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- tool policy: exactly six MCP tools with `tool_choice=required` on every chat request
- limits: 65,536 context tokens, 2,048 output tokens, 200 iterations, no retry
- source commit: `7faa4a40f5fe74154a061e8accb76fdd88a03a2a`
- agent version hash: `0920a50aec8c50c380cce2ea46f73be0e3483399587a98b19cc21c50dd0a9552`
- prior v2 report hash: `0d985d27f11c3db45a6ec4002b0a5536b117a200db90893ac4107e7f1814ac14`

## Result

The endpoint accepted required tool choice, all 200 accepted decisions were typed tools, and the
content-only Stop-hook recovery path was never exercised. However, the model selected 197 file
reads and three shell calls, made no patch, inspect-diff, or `finish` call, and reached the frozen
limit. Decision 201 was rejected as `episode_limit`.

The outcome was infrastructure-valid but failed as `openhands_hwe_action_policy` with status
`model_rejected_before_typed_finish`. Both candidate patch files remained empty, the ordinary
verifier did not resolve, and no trajectory or dataset record was exported. Wall time was
826.461 seconds. The credential scan covered 5,976 files and 133,631,147 bytes with zero provider
value matches.

- report hash: `e4b40518c0d5b42d1fbbde5e115bacaeb588e4671e01e5f8627fcb456b8115d3`
- GPU/HPC jobs, optimizer steps, checkpoints, and adapters: zero

## Interpretation

Always-required tool choice removes OpenHands' asymmetric content termination, but it also removes
the model's plain-text completion signal. For this model and task, the provider repeatedly selected
`read_file` instead of the available `finish` function. The next policy therefore retains `auto`
for ordinary turns and forces only the concrete `finish` function after the trusted Stop hook has
observed the model's content-only completion intent.
