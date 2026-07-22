# Batch runner, failures, and recovery

The batch runner calls `VeriGym.run(RunConfig)` directly. It does not spawn the CLI and does not
contain a second evaluator. Each worker creates a fresh service and ordinary run directory with
the established manifest, task snapshot, trace, scorecard, diff, candidate, logs, artifacts, and
replay behavior. Agent workspaces, model cursors, runtime sessions, and verifier sessions are not
shared between children.

## Parent artifacts

An experiment root contains:

```text
experiment_manifest.json  immutable identities plus lifecycle status
experiment_config.json    normalized strict configuration (output stored as ".")
plan.jsonl                 canonical items in plan-index order
events.jsonl               batch-control events only
state.json                 crash-recovery counters and lifecycle
run_index.jsonl            plan item/attempt to relative child path
logs/batch.log             bounded controller diagnostics
runs/<run-id>/             unchanged ordinary child runs
reports/                   aggregate.json, runs.csv, report.md
```

Mutable parent files and reports use a same-directory temporary file, `fsync`, and atomic rename.
Parent JSON/JSONL is strict, bounded, non-symlink input on resume. Child paths remain relative and
are checked for containment, required types, symlinks, special files, identity bindings, and
manifest/score hashes.

## Sequential and parallel behavior

`max_workers: 1` is the canonical default and runs exact plan order. Candidate compile failures,
test failures, and invalid model outputs are ordinary evaluation data, so execution continues and
the batch can still exit zero. Structured model, runtime, or verifier infrastructure failures are
kept separate and continue by default.

`max_workers` may be set from 1 through 32. The bounded thread pool owns one independent child per
worker. Parent events/state/index writes are locked and atomically replaced; reports are sorted by
plan index and attempt rather than completion time. Fail-fast infrastructure mode stops scheduling
new work after the first structured infrastructure result. Already running children may finish so
their cleanup and audit artifacts are retained. Interruption requests best-effort cancellation;
ordinary runtime `finally` cleanup remains authoritative.

Batch exit codes are:

- `0`: controller and reports completed with no infrastructure/internal failure; unresolved
  candidates are allowed;
- `2`: invalid configuration, plan/source drift, or incompatible frozen identity;
- `3`: mandatory dependency missing during preflight;
- `4`: one or more structured infrastructure failures, with reports retained;
- `5`: internal VeriGym/controller invariant failure;
- the standard interrupt behavior for user cancellation.

## Resume

```bash
verigym batch --resume runs/experiments/<experiment-id>
```

Resume reloads the stored config and plan, recomputes their hashes, revalidates current
source/profile inputs, and validates every latest child. Reuse requires exact plan, task, source,
model, agent, prompt/tool policy, seed/sample, runtime/image, verifier, profile, manifest,
scorecard, and filesystem bindings. `replay_run(..., verify=False)` validates ordinary artifact
integrity. Reused children make zero model calls and zero runtime calls.

A valid unresolved candidate and a valid infrastructure-error child are terminal data and are not
automatically retried. Missing work executes once. A partial, corrupt, or incompatible attempt is
preserved, explicitly reclassified in `run_index.jsonl`, excluded from aggregates, and followed by
a new run ID with an incremented attempt. A supplied config with a different normalized hash is
rejected without mutating the frozen plan.
