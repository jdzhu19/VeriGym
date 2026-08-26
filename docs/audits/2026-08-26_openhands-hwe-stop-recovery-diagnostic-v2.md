# OpenHands HWE stop-recovery diagnostic v2

Date: 2026-08-26

This audit records one bounded PR-2032 regression diagnostic for the OpenHands SDK HWE adapter.
It is not a benchmark score, a verifier-pass trajectory, or a training-readiness claim.

## Scope and frozen identity

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model transport / identity: `openai/deepseek-v4-flash` / `deepseek-v4-flash`
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- seed / context / maximum output: `484` / `65,536` / `2,048`
- sampling: temperature `0`, top-p `1`, no provider or whole-episode retry
- tool contract: `hwe_native_shell_v2`, exactly six MCP tools
- recovery policy: `openhands_broker_stop_hook_recovery_v1`, one same-session allowance
- completion authority: broker-observed typed `finish`
- source commit: `8806e5b1b7e51e33345dc5a3a6e533ecae815b2e`
- agent version ID:
  `openhands-deepseek-v4-flash-hwe-stop-recovery-diagnostic-v2-attempt2`
- agent version hash:
  `f832f4d8a6ec1df0e09ac12f72d620842ce0906afd90ed4e9080581831328151`

The diagnostic hash-binds the earlier v1 PR-2032 `openhands_hwe_missing_finish` result. The first
v2 launch stopped during broker initialization because the OpenHands environment exposed
`tiktoken==0.11.0` instead of the frozen `0.7.0` overlay. Its sealed trace proved zero model calls,
zero raw observations, and zero workspace changes. Attempt 2 used a new campaign and agent-version
identity and binds the superseded report hash
`69e1daf08abb1bec39d7a3ccbeb1ddaddcf2441820a52973a7da25bd80cd176f`.

## Observed result

Attempt 2 passed environment, Docker, six-tool MCP, broker, and model-transport setup. It was
infrastructure-valid and made 17 model decisions with 17 reconciled broker tool calls:

- 10 file reads;
- 6 shell calls;
- 0 patch calls;
- 0 rejected tool calls;
- 0 broker policy or infrastructure failures.

After those calls the model attempted a content-only stop. The OpenHands Stop Hook denied that
stop and injected the one canonical recovery message into the same session. The model then
attempted another content-only stop instead of calling `finish`. With the recovery allowance
exhausted, the SDK unwound and the VeriGym adapter failed closed as
`openhands_hwe_missing_finish`.

The final status is `termination_regression_failed`: the real hook and recovery path were
exercised, but recovery did not produce broker-authoritative typed completion. The ordinary
verifier did not resolve a candidate, no positive trajectory was exported, and no record was
admitted to an SFT dataset.

- recovery count: `1`
- typed `finish` observed: `false`
- model / tool calls: `17` / `17`
- patch calls and workspace diff bytes: `0` / `0`
- wall time: `340.716` seconds
- report hash: `0d985d27f11c3db45a6ec4002b0a5536b117a200db90893ac4107e7f1814ac14`

An exact-value scan covered 5,976 files and 117,244,226 bytes. Both configured provider values had
zero matches and were neither persisted nor hashed. The run used no GPU, submitted no HPC job,
wrote no checkpoint or adapter, and performed no optimizer step.

## Interpretation

The adapter now handles the original OpenHands early-stop condition safely: it neither silently
accepts prose as a canonical tool action nor retries the full episode. This run also demonstrates
that one natural-language recovery turn is insufficient to make DeepSeek V4 Flash emit typed
`finish` reliably under OpenHands. Consequently, this policy is not ready for expanded OpenHands
trajectory collection. Any further experiment must register a new policy identity; this failed
episode must not be relabeled as a trajectory or verifier result.
