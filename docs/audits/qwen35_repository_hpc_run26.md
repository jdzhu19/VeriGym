# Qwen3.5 repository GRPO HPC run 26

Run 26 was a four-A30 developmental repository-GRPO attempt on the non-held-out CVA6 PR 2170
task. It was stopped manually after the trainer remained at two of four completed rollouts for
more than two hours. It is not a qualified optimizer step or benchmark score. No optimizer update,
checkpoint, changed adapter, or completion report was produced.

The run used implementation commit `b1fcb4b78004af1ec5e334aad0de5d395f7e26ff`, native runtime
manifest SHA-256 `300871ece6a26ca00a3a488312545970049434b7b55187850ba3b31eaad2447f`,
task input SHA-256 `c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36`,
split SHA-256 `a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`,
and broker report file SHA-256
`5a7183a49e60181e8b3437bcbcc7b914ec179e6552fad9828020f0d1c59e503b`. The native training log
SHA-256 is `1f62060bb8b975fca7ae98237ddd4a2b24bf8cdcc9e45e39df79cdc8182400a`.
The LSF allocation bound four A30 GPUs and 16 CPU slots. The official pinned PyTorch container
remained the verifier environment, and verification ran with networking disabled.

## Result

The 0.47 vLLM envelope initialized successfully without an out-of-memory failure. Two rollouts
completed after approximately 9 minutes 35 seconds and 10 minutes 1 second. The trainer then
remained at `2/4` while two model-response futures remained pending. The log and GPU process state
show that the calls had not returned; they do not prove that the model emitted tokens continuously
throughout that interval. At stop time the broker had 94 request files and 94 corresponding
responses, and all four repository sessions had terminal records. Two sessions ended after
malformed model actions. Two reached the repository session wall limit without submitting a patch.

The preserved broker report labels the latter two sessions infrastructure invalid. That label is a
historical artifact of the run-26 implementation: any terminal scorecard with status `error` was
classified as infrastructure failure, including an agent action timeout explicitly attributed to
the model. It does not indicate a Docker, repository, or verifier infrastructure failure.

The run exposed two independent coordination defects. First, the broker initially returned an
ordinary `turn-N.json` response and later replaced that same path with the terminal response. A
trainer that had already consumed the ordinary response could begin generation for turn `N+1` and
never observe the replacement. Second, the repository action wait created a fresh one-hour deadline
on every turn instead of enforcing one session deadline. The outer native workflow also retained
its permissive default timeout. Together these defects allowed obsolete generations to outlive a
terminal repository session.

The broker was stopped through its supported `STOP` mechanism and emitted its report before the old
LSF job was released. No run-26 process remains.

## Evidence, findings, and execution path

### E-001

- Source: the native training log and runtime manifest identified above.
- Observation: rollout generation reached `2/4`, remained there until manual interruption, and did
  not enter a completed optimizer update.
- Reproduction: inspect the preserved log for rollout progress and the interrupt traceback; inspect
  the run directory for absence of a checkpoint and completion report.

### E-002

- Source: the broker report identified above and the hashed broker message inventory.
- Observation: all 94 requests had responses and four terminal session records existed, while the
  trainer had completed only two rollout futures.
- Reproduction: count hashed request/response messages recursively and parse only the sanitized
  report fields; trajectory text is not required.

### E-003

- Source: implementation commit `b1fcb4b78004af1ec5e334aad0de5d395f7e26ff`.
- Observation: terminal publication reused the pending turn response path, each action wait reset a
  one-hour deadline, and the workflow did not race generation against broker terminal publication.
- Reproduction: inspect the pre-fix broker publication, repository wait, and workflow loop.

### F-001

- Finding: run 26 stalled because the trainer could miss a repository terminal and keep an obsolete
  model generation alive; the verifier and repository side had already finished.
- Evidence: E-001 through E-003.
- Confidence: high.
- Impact: the run cannot qualify rollout completion or an optimizer step, but it does establish that
  the 0.47 rollout envelope initializes and generates without the run-25 OOM.

### F-002

- Finding: the run-26 infrastructure-invalid count is not semantically reliable for model action
  timeouts.
- Evidence: E-002 and E-003.
- Confidence: high.
- Impact: retained run-26 records must keep their original hashes, while reports should carry this
  erratum rather than rewriting the historical artifacts.

### P-001

1. Four repository rollouts begin and vLLM generation succeeds (E-001).
2. Two rollouts complete normally from the trainer's perspective (E-001).
3. All four broker sessions eventually publish terminal outcomes (E-002).
4. Two trainer futures miss those terminal transitions and remain in generation (E-002, E-003).
5. Manual interruption ends the unqualified run before any optimizer update (E-001, F-001).

## Follow-up

The remediation publishes an immutable session-level `terminal.json` rather than replacing a turn
response, races every model generation against that terminal, cancels obsolete generation, enforces
one 3,600-second repository session deadline, sets the broker wait deadline at 3,900 seconds, and
bounds the outer workflow at 4,200 seconds. Agent-attributed action timeouts remain evaluable model
failures; only runtime- or explicitly infrastructure-attributed errors invalidate a session.
Regression coverage includes four concurrent terminal futures, immutable terminal publication,
deadline reuse, cancellation, and classification.
