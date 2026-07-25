# Codex CLI conformance smoke audit

This audit is intentionally separate from the historical VeriGym v0.1.0 release-candidate
bundle. That bundle and audited commit were not modified or reinterpreted.

## Scope and frozen policy

- Baseline commit: `0a1948f96b44811afa00cc87743c22b6d0396f33`
- Work branch: `codex-cli-conformance`
- Tracks: `codex_cli_model_proxy` and `codex_cli_external_agent`
- Tasks: `toy-rtl/and-gate-basic` and `toy-rtl/counter-basic`
- Planned real runs: four, one attempt each
- Retry, best-of-K, and outer-agent repair: disabled
- Total real-smoke wall-time bound: 1,800 seconds
- Larger VerilogEval pilot: configuration only unless separately opted in and budgeted

Track A is a CLI-mediated model proxy and not a direct API benchmark. Track B is an external
coding agent whose candidate is judged only by VeriGym’s ordinary freeze and hidden verifier.

## Evidence status

Implementation, fake-CLI, regression, package, zero-call doctor, and real-smoke evidence are
recorded here only after each command is actually executed. A missing external prerequisite is
reported as blocked; a code, policy, parser, test, or evidence failure is reported as failed.

At the source-writing stage, no real model-bearing Codex smoke process had been launched. The
final gate therefore remains **not yet determined**. This statement must be replaced by recorded
commands, run directories, replay results, scans, and an exact PASS/FAIL/BLOCKED gate before the
audit is complete.
