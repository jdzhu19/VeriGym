# RTL functional multi-turn strength diagnostic v2

## Scope

This audit records three diagnostics-only, single-seed campaigns over the same 14 frozen
RTLLM/VerilogEval slots. It is not a benchmark score. Each tier used a distinct frozen Codex CLI
agent identity, exactly one model process per slot, no retries, one typed `finish`, and at most one
hidden-verifier execution.

The strength tiers were:

| Tier | Model | Reasoning |
| --- | --- | --- |
| Low | `gpt-5.4-mini` | `low` |
| Medium | `gpt-5.4-mini` | `high` |
| High | `gpt-5.4` | `xhigh` |

The tier names describe the overall comparison, not three adjacent reasoning settings on one
model. Model and reasoning support were checked against the official
[GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) and
[GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4) documentation before freezing the
agents.

## Gym changes

- Added a bounded Codex-native patch compatibility profile while retaining the strict unified-diff
  profile. All paths still pass through the workspace policy; renames remain rejected; operations
  are planned before writes; hidden, read-only, traversal, link, size, and editable-path boundaries
  remain unchanged. The grammar was cross-checked against the upstream
  [Codex patch parser](https://github.com/openai/codex/blob/main/codex-rs/apply-patch/src/parser.rs)
  and [native patch instructions](https://github.com/openai/codex/blob/main/codex-rs/prompts/templates/apply_patch_tool_instructions.md).
- Split non-interactive Docker execution into create/start, wait, and logs/inspect phases. A wait
  deadline after an observed container exit is now classified as a control-plane failure, not a
  candidate timeout. This follows the lifecycle separation exposed by Docker's
  [container start](https://docs.docker.com/reference/cli/docker/container/start/) and
  [container wait](https://docs.docker.com/reference/cli/docker/container/wait/) interfaces.
- Added a VerilogEval functional-v2 revision with Codex-compatible patching and an exhaustive
  public smoke for `Prob150_review2015_fsmonehot` derived only from its public specification.
- Added bounded wall-time visibility and explicit tool/patch/reserve budgets to prompt v8.
- Added content-free, atomic campaign progress containing only allowlisted phases, statuses, tier,
  and process counts. It contains no task text, paths, arguments, model output, or commercial
  diagnostics.

## Frozen v2 result

| Tier | Resolved | Typed finish | Visible failure/repair loops | Public failures | Valid PPA | Timeout / policy / infrastructure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 14/14 | 14/14 | 4 | 7 | 4/4 | 0 / 0 / 0 |
| Medium | 14/14 | 14/14 | 3 | 5 | 4/4 | 0 / 0 / 0 |
| High | 13/14 | 14/14 | 4 | 5 | 4/4 | 0 / 0 / 0 |

All 42 processes recorded one valid identity observation and complete provider usage. Offline
replay, exact leakage scanning, and redaction audits passed for every tier. All campaign summaries
record `diagnostic_only=true` and `benchmark_score_claimed=false`.

The visible `test failed -> patch -> re-test passed` loop occurred in these run instances:

- Low: `Prob096`, `Prob107`, `Prob124`, and `Prob150`.
- Medium: `Prob096`, `Prob124`, and `Prob150`.
- High: `Prob096`, `Prob128`, `Prob137`, and `Prob150`.

Thus the three campaigns contain 11 directly observed functional repair loops. Ten of those run
instances also passed the one-shot hidden verifier. High-tier `Prob137` passed the visible test only
after two repair/re-test loops but was rejected by the hidden regression with 47 mismatches over
905 samples.

## Post-diagnostic v3 hardening

Inspection of the high-tier `Prob137` candidate found that the public smoke did not exercise the
specified invalid-stop recovery behavior. The candidate could assert `done` while resynchronizing
after a bad stop bit. This is both a model error and a visible-feedback coverage gap.

The v2 evidence was kept immutable. A separate functional-v3 suite revision adds a public,
specification-derived invalid-stop/recovery check. In a direct differential check, the low-tier
candidate that passed hidden verification also passes the v3 smoke, while the formerly
hidden-rejected high-tier candidate is rejected publicly. The v3 launcher profiles are available as
`low-v3`, `medium-v3`, and `high-v3`.

A zero-model v3 qualification completed successfully:

- 12 public reference/known-bad functional checks;
- 10 VerilogEval hidden-reference checks;
- four open/commercial synthesis checks and two exact agent-feedback checks;
- four VCS/MCP preflight records;
- 14 distinct frozen run-configuration hashes.

No v3 model campaign was started automatically. The completed 42-process comparison remains the
immutable v2 diagnostic; v3 is the qualified next revision.

## Interpretation and limits

The earlier 7/14 diagnostic was primarily Gym-limited: six candidates failed before compilation
because the broker accepted only strict unified diffs while Codex emitted its native patch grammar,
and `Prob150` had an underpowered public smoke. After those fixes, the same bounded matrix resolved
41/42 slots with no policy, timeout, or infrastructure failure.

The remaining v2 failure cannot be assigned solely to the model because its visible feedback missed
a public-spec behavior; v3 closes that observed gap. Conversely, public feedback is intentionally
not a copy of the hidden verifier, so a future hidden rejection is not automatically a Gym defect.

Low already resolving 14/14 shows that this fixed sample is too easy for ranking model strength.
The meaningful evidence here is operational and multi-turn: weaker agents can use visible
compile/test/PPA feedback to repair candidates before a one-shot hidden verifier. A future scoreable
pilot should use unseen, harder tasks, multiple seeds, and a pre-frozen v3-or-later suite. The
[posteda-bench repository](https://github.com/pengjas/posteda-bench) remains a useful comparison for
the read/edit/visible-feedback/revalidate interaction shape, but these diagnostics preserve
VeriGym's typed-tool, one-shot-hidden, identity, and artifact contracts.
