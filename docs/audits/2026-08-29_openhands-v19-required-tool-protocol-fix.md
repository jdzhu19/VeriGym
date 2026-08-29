# OpenHands v19 required-tool protocol repair

## Outcome

This change registers an independent v19 OpenHands HWE protocol and result model. It does not
modify v12-v18 identities or historical trajectories. No public-task qualification, provider
canary, formal collection, SFT, GPU job, or held-out evaluation was started by this repair.

Current stage flags remain:

- `qualification_started=false`
- `provider_canary_started=false`
- `formal_collection_started=false`
- `training_started=false`
- `optimizer_steps=0`
- `heldout_loaded=false`
- `production_training_ready=false`
- `benchmark_score_claimed=false`

## Frozen v19 protocol

- policy: `required_tool_content_recovery_v19`
- ordinary and special provider requests: `tool_choice=required`
- exact tools: `apply_patch`, `finish`, `inspect_diff`, `list_files`, `read_file`, `shell`
- content-only recovery: at most one, in the same session, with trusted
  `source=environment` feedback
- provider calls / cumulative tokens: `64` / `1,000,000`
- context / output tokens: `65,536` / `2,048`
- temperature / provider retries / episode retries: `0` / `0` / `0`

The LLM boundary validates every provider-emitted tool name and canonical argument object before
returning it to OpenHands. A second content-only response, mixed prose/tool response, empty or
multiple call, foreign tool, pseudo-finish, weakened request, or recovery-state drift fails
closed. Cumulative tokens are checked after the SDK records the provider response but before the
response enters the agent or broker.

The protocol receipt binds required request count, canonical response count, content-only count,
format-recovery count, recovery request/validation counts, provider call and usage counts,
input/output totals, broker decision count, and all four budgets. The exact trajectory and
decision sidecars bind this receipt, the six-plane campaign result, complete transcript hash, row
hashes, exact token counts, `truncation=error`, and decision-only masking. Abnormal assistant text
and environment feedback have loss mask zero; later complete canonical tool decisions have loss
mask one.

## Result planes and PR-2469 correction

The compatibility field `ScoreCard.resolved` is unchanged. v19 derives benchmark correctness from
the actual `verifier_results` list and records these fields independently:

- `benchmark_verifier_pass`
- `agent_protocol_valid`
- `trajectory_eligible`
- `infrastructure_valid`
- `security_valid`
- `sft_admitted`

SFT admission requires every preceding plane and an explicit admission request.

The sanitized offline PR-2469 fixture is bound to the sealed scorecard SHA-256
`603186963396d0306b63e4cc87838ab3ba591b55c85df69b9b0e4ed85adef729`. Its top-level
`resolved=false`, while the actual hidden verifier node is `status=passed`, `tests_passed=1`, and
`tests_total=1`. The regression therefore produces `benchmark_verifier_pass=true`,
`agent_protocol_valid=false`, `trajectory_eligible=false`, and `sft_admitted=false`. It sets
`historical_trajectory_reconstructed=false` and imports no historical bytes.

## Later-stage gates registered but not exercised

The public CVA6 candidate order is frozen as PR-2330, 3226, 2844, 3231, 2989, 1482, and 3059 by
`(changed lines, PR number)`. Existing train/validation tasks, PR-2170, PR-2032/2468/2469/3191,
the three retained historical training passes, and all six held-out tasks are excluded. The gate
requires five zero-model base-FAIL/reference-PASS tasks, assigns the first three qualified tasks to
training reserve and the next two to validation reserve, and stops on infrastructure or isolation
failure.

The canary and formal-collection evaluators require a hash-linked protocol, campaign, trajectory,
decision, and security evidence chain for each admitted episode. The formal gate begins with the
three immutable historical training passes plus the canary training pass and one canary validation
pass. It recalculates distinct remaining capacity after every one-shot attempt and stops at exactly
eight training and two validation passes or as soon as either target becomes impossible.

## Verification

The change adds sync/async required-tool, one-recovery, repeat-prose, recovery-drift, illegal tool,
pseudo-finish, missing/over-budget token accounting, and Responses-route tests. Offline tests cover
PR-2469 two-plane classification, recovery masking, receipt identities, exact-64K rejection,
candidate order/exclusions, five-task capacity, 3/2 reserve assignment, canary failure closure,
one-shot collection capacity, and immediate security stop.

Final local and GitHub check results are recorded in the repair pull request; later qualification
requires a separate post-merge audit and does not inherit authorization from this document.

Local pre-PR verification passed:

- OpenHands credential-free zero-model suite: `256 passed`
- ordinary repository suite with the frozen tiktoken 0.7 overlay and training-reference source:
  `1000 passed, 10 skipped, 43 deselected`
- OpenHands strict mypy: `28 source files`, no issues
- core strict mypy: `206 source files`, no issues
- tracked-source Ruff lint/format and `git diff --check`: passed
- OpenHands wheel/sdist build and optional-plugin distribution scan: passed with no findings

The first ordinary-suite invocation used the OpenHands base environment without its 0.7 tokenizer
overlay or training-reference source and therefore produced eight environment-only failures. The
same failed nodes passed `12/12` after reproducing the CI source/overlay layout, followed by the
clean full result above. No source change was made in response to those environment mismatches.
