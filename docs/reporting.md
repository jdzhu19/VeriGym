# Experiment reporting semantics

Reports are projections over validated persisted manifests and scorecards. Generation never calls
a model, tool, runtime, Docker daemon, or network service and never reads candidate RTL or hidden
source to derive metrics. It accepts either a Milestone 9 experiment root or an arbitrary root of
ordinary run directories. Discovery does not follow symlinks; JSON sizes/depth, required artifact
types, containment, cross-references, and duplicate records are validated. Invalid inputs are
recorded and excluded rather than silently treated as benchmark failures.

Generate one format with:

```bash
verigym report generate EXPERIMENT_OR_RUN_ROOT \
  --format json \
  --output /tmp/aggregate.json \
  --group-by system
```

Allowed group dimensions are `suite`, `release`, `category`, `difficulty`, `task`, `system`,
`model`, `agent`, `interaction_mode`, `runtime`, `profile_id`, `profile_hash`, and `base_seed`.
Arbitrary expressions are not evaluated.

Integrity status and package provenance scope appear in report metadata. Reports never upgrade a
legacy artifact to verified, and tampered children are excluded with a distinct diagnostic.

## Coverage and denominators

`aggregate.json` is the authoritative strict `1.0` schema. It reports planned, started, terminal,
valid-artifact, evaluable, resolved, unresolved-evaluable, infrastructure, cancelled, corrupt,
and missing counts. Its named rates are exactly:

```text
resolved_rate_evaluable   = resolved / evaluable_candidate_runs
resolved_rate_planned     = resolved / planned_plan_items
evaluation_completion_rate = evaluable_candidate_runs / planned_plan_items
```

Every rate stores numerator and denominator. A zero denominator produces JSON `null`, never a
fabricated zero. If more than one release/source or correctness definition is present, the two
coarse combined resolved-rate values are also `null` with
`mixed_release_or_correctness_partitions`; `compatibility_aggregates` carries the separate rates
and stage summaries. Compile, hidden regression, formal, and equivalence rows separately report passed,
applicable denominator, rate, missing count, and infrastructure-error count. A candidate failure
is not infrastructure; structured categories are never inferred by regexing logs.

Efficiency mean/median values use resolved runs only and include known/missing counts and units.
Token values of zero are real when recorded; `null` remains missing. Model API cost is aggregated
only inside an exact currency or explicit unit partition. Missing values, unknown units, and
incompatible partitions have separate counts; VeriGym performs no exchange-rate or unit
conversion. Legacy numeric costs without a unit remain visible but are not summed.

## Sampling and canonical pass@k

A sample group requires an exact match of task/source/release, model and agent descriptors/options,
prompt/tool policy, mode, budget/generation, verifier/correctness definition, runtime/image,
declared/resolved profile, system, and base seed. Base seeds are separate replicate groups and are
never pooled to manufacture a larger `n`.

Within each complete group, `n` is the planned sample count and `c` is the resolved count.
VeriGym reuses the Milestone 6 unbiased estimator:

```text
pass@k = 1 - C(n-c, k) / C(n, k)
```

Candidate and model-output failures are incorrect candidate verdicts. Any missing child,
infrastructure failure, cancellation/truncation, duplicate sample index, or incomplete verdict
invalidates canonical pass@k and yields `null` with a reason. Macro mean/median is over valid
task/system/base-seed groups only and reports valid, invalid, and missing group counts. Best-of-N
is reported only for a complete canonical group.

## Area-only quality

Quality remains educational synthesis area only. A ranked value requires an evaluable, functionally
resolved candidate plus successful candidate/reference synthesis. Partitions bind exact
suite/release/source, task/hash, correctness definition, declared profile ID/hash, resolved profile
hash, runtime/image, area unit, and reference candidate. Raw synthesis area may remain diagnostic
for an ineligible run, but ranked area/reference/ratio remains null. Different partitions are never
ranked together; `verigym report compare` retains the strict Milestone 8 refusal behavior. Timing,
power, delay, frequency, WNS, and TNS remain unavailable. There is no universal “VeriGym Score.”

Different releases and correctness definitions receive compatibility identities and warnings; they
must be read as separate coverage scopes. Per-system groups report task coverage so unequal task
sets are not presented as a matched comparison.

## CSV and Markdown

`runs.csv` has one deterministic row per indexed attempt, ordered by `plan_index`, then attempt.
Its fixed columns are:

```text
experiment_id, plan_index, plan_item_id, attempt, run_id, relative_run_path,
suite, suite_version, release_id, task_id, task_hash, category, difficulty,
interaction_mode, system_id, model_id, agent_id, base_seed, sample_index, child_seed,
runtime_id, isolation_level, image_id, declared_profile_id, declared_profile_hash,
resolved_profile_hash, status, resolved, evaluable, infrastructure_error, failure_category,
termination_reason, compile_status, tests_passed, tests_total, ppa_eligible, area, area_unit,
reference_area, area_ratio, wall_time_s, model_input_tokens, model_output_tokens, total_tokens,
model_cost, cost_currency, turns, tool_calls, failed_tool_calls, changed_files, diff_lines,
warning_count, artifact_validation_status
```

Missing fields are empty CSV cells. Newlines/control characters are normalized and untrusted text
starting with `=`, `+`, `-`, or `@` receives a leading apostrophe to mitigate spreadsheet formula
injection. No prompt, candidate code, hidden source, trace, log, credential, or absolute child path
is included.

`report.md` includes identity, coverage, denominators, failure taxonomy, efficiency/cost coverage,
system coverage, sampling, exact quality partitions, warnings, invalid inputs, and safe relative
child links. Untrusted Markdown/HTML metacharacters and link paths are escaped.
