# OpenHands HWE finish and trajectory qualification v14

Date: 2026-08-27

This audit records the bounded v12 through v14 PR-2032 evidence and the resulting OpenHands
collector changes. It is not a benchmark score, an SFT dataset admission, or a training-readiness
claim.

## Frozen scope

- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032`
- model: `openai/deepseek-v4-flash`, thinking disabled, seed 484
- OpenHands SDK / LiteLLM / tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- context / output / iteration limits: 65,536 / 2,048 / 200
- whole-episode and provider retries: zero
- ordinary transport: Chat Completions; receipt-bound recovery transport: Responses
- task runtime and verifier: separate digest-bound Docker sessions with verifier network disabled
- GPU jobs, optimizer steps, checkpoints, adapters, and dataset admissions: zero

## v12: verifier-passing patch withheld by the old policy

Source commit `af1cca89c9981078f5448ba981bc088c47b61dc5` made 48 model decisions and 49
broker tool attempts. The model called typed `finish`, changed only `core/decoder.sv`, and the
ordinary hidden verifier passed 2/2 tests. The broker had rejected two earlier shell calls with the
sole code `invalid_arguments`; the old all-or-nothing policy therefore classified the episode as
`openhands_hwe_action_policy` and withheld the trajectory.

The v12 runner also required a recovery response-shape receipt even though this direct-finish run
made no recovery request. Its sealed `infrastructure_invalid` status is consequently a historical
report-classification defect, not a provider or verifier infrastructure failure. The immutable
report remains unchanged.

- report hash: `1eca19161e5fce6304c138d42c78d65801420f5aef4376f4defa182c787fdfc9`
- agent version hash: `0c0119edb43eb1db25e1dc690bc480473a552e7543d93c862ae7f632cee0ac4f`
- trace SHA-256: `5e984af0d14224eb0ec520ae7b7afa0a0ed1f9cba038c561424a433e2255773b`
- wall time: 765.550 seconds

## Collector correction

OpenHands exact trajectory, decision, and dataset v3 formats now implement the same narrow rule as
the existing DeepSeek Harness v3 collector:

- only episodes that eventually reach broker-authoritative typed `finish` may use the exception;
- every broker rejection code must be `invalid_arguments`;
- rejected calls and their SDK `is_error=true` observations remain hash-bound in exact input
  context;
- their complete assistant decisions use `supervised_target=false` and produce no target row;
- later accepted decisions retain the failed interaction in the loss-masked input prefix;
- unknown tools, valid arguments mislabeled as rejected, other rejection codes, causal mismatches,
  missing error flags, truncation, or verifier failure remain fail-closed.

The implementation is in commits `751e96a` and `ca585eb`. OpenHands plugin tests cover exact
round-trip, decision masking, accepted/rejected observation semantics, tool schemas, hashes, and
64K token receipts.

## v13: named finish was not honored

The v13 run made nine ordinary model/tool calls and exercised the Responses recovery path once.
OpenHands' full-history duplicate `function_call_output` blocks were coalesced successfully. The
provider returned exactly one known `read_file` call with no text instead of the named `finish`.
The pre-broker guard rejected it, leaving the workspace unchanged and exporting no trajectory.

- status: `responses_recovery_finish_response_rejected`
- report hash: `714222f55902441ef477398f78518aa717e79f96ec8bc5718d178ff9e606b169`
- trace SHA-256: `68f994fa7846ef97d2e951d235023c3338fe6f01284f46405197cda5ae567600`
- coalesced outputs: 9; validated finish calls: 0
- wall time: 217.148 seconds

## v14: required-tool continuation succeeded, episode did not

The v14 recovery policy uses the Stop-hook's literal contract instead of narrowing it to finish.
Exactly once, after the private recovery receipt is validated, the Responses request uses
`tool_choice="required"`. A response is admitted only when it contains one call to a tool in the
exact six-tool schema and no assistant text. The response is then dispatched through the unchanged
broker, and later turns return to ordinary Chat Completions. This policy never synthesizes an
action or bypasses broker validation.

The real v14 run coalesced 23 historical output blocks, validated one recovered `read_file`, and
continued the same OpenHands session. It later produced a second content-only stop after the sole
recovery allowance was exhausted. The broker recorded 24 accepted tool calls, no rejection, no
infrastructure error, no mutation, and no typed `finish`. The ordinary verifier failed 0/2 against
the unchanged candidate, so no trajectory or dataset row was exported.

- source commit: `627618ec99102690c0e20cbb0bcd6511c8075369`
- status: `responses_recovery_finish_regression_failed`
- failure category: `openhands_hwe_missing_finish`
- report hash: `1d6daa70656c485aef67b61d606fc359ba3d31703faf849a372222350a638c6e`
- agent version hash: `4335269a2fb3634384183d33f5a7da53967ec9420c4c45e6e8ef858552decbca`
- trace SHA-256: `e2609e45427b9aadb9e5adfa15f2fb46302ac61fde8f4c64437dd4fc3e441140`
- wall time: 505.014 seconds

The credential scans for v12, v13, and v14 covered 5,976 files per run and found zero provider
value matches. Provider values were neither persisted nor hashed.

## Conclusion

The Responses serialization defect, direct-finish evidence classification, recoverable
`invalid_arguments` supervision policy, and safe non-terminal recovery continuation are fixed and
covered by tests. The v14 evidence shows that the remaining PR-2032 failure is the model outcome:
this attempt neither repaired the candidate nor emitted broker-authoritative typed `finish`.
Because exact v12 OpenHands events were held only in memory and were not persisted after the old
policy rejected the episode, its verifier-passing patch cannot be retroactively converted into an
exact OpenHands trajectory. The collector correctly refuses to reconstruct or synthesize one from
broker observations alone.
