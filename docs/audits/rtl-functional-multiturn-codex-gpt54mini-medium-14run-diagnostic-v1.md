# RTLLM/VerilogEval functional multi-turn diagnostic v1

This note records a diagnostic campaign, not a benchmark score. Full run artifacts remain outside
the repository under the configured experiment root.

## Frozen identity

- Campaign: `rtl-functional-multiturn-codex-gpt54mini-medium-14run-diagnostic-v1`
- Suites: RTLLM and VerilogEval
- Processes: 14 independent Codex CLI invocations, one per frozen slot, with zero retries
- Requested model/reasoning: `gpt-5.4-mini` / `medium`
- Agent: `codex-cli-agenteval-gpt54mini-medium-functional-v1`
- Agent version hash: `0258bfa172121f0010e023e30790efe8042d242310c30c8409374cb14e74bc79`
- Prompt hash: `c01db084d23d79c89bcd7d9374fcb7586748983d9bbc57b4e049c62378db8153`
- Tool-policy fingerprint:
  `7692a4acfe39a4cf3511fe4a4be7e9eac5037a34c4e911a2bfec3d9bcea7047d`
- Codex CLI: `0.147.0`, executable SHA-256
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`

The public `compile` action compiled the candidate and ran an independent bounded functional
smoke. Hidden verification remained outside the model-facing feedback loop.

## Result

- The campaign executed all 14 processes and recorded exactly one requested-only identity
  observation for every process.
- Seven candidates resolved: RTLLM 3/4 and VerilogEval 4/10.
- Eight processes reached typed `finish`; one of those was rejected by the hidden verifier.
- Six contained agent failures hit the consecutive rejected-patch limit before public validation.
- No process timed out, retried, changed model identity, or reported a policy or infrastructure
  failure.
- The three resolved RTLLM runs produced legal final-candidate PPA evidence. The failed RTLLM run
  did not claim candidate PPA.
- Offline replay validated all 14 run histories. The exact leakage scan reported zero findings and
  the redaction audit passed all 14 runs.

`Prob137_fsm_serial` demonstrated the intended functional multi-turn effect: its first two public
functional validations failed, the agent patched and rechecked the candidate, the third validation
passed, and the run then completed diff inspection, typed `finish`, and hidden verification
successfully. The broker recorded `public_validation_failed_then_passed=true`.

`Prob150_review2015_fsmonehot` passed public validation and reached typed `finish`, but the hidden
regression passed only 277 of 300 samples and rejected the candidate. The other six unresolved runs
did not reach the functional feedback loop because the weaker model could not reliably produce a
broker-accepted unified diff.

Consequently, this campaign confirms that the Gym can expose and attest a real public
failure-to-repair loop, while also showing that `gpt-5.4-mini` at `medium` is too weak for the strict
patch protocol on a substantial fraction of this sample. The result remains
`diagnostic_only=true`, `benchmark_score_claimed=false`, and `fully_successful=false`.
