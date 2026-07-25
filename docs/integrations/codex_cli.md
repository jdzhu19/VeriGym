# Codex CLI conformance pilot

The optional `verigym-codex-cli` distribution exposes two systems that must remain separate in
plans, reports, and comparisons.

## Integration tracks

**Codex CLI model proxy** combines `SingleTurnAgent` with `codex-cli-exec-model`. Every generate
call launches one non-interactive CLI process in a newly created empty directory, passes an
ordered deterministic message envelope on stdin, and parses JSONL events. A successful response
requires one terminal event, exactly one final message, no directory changes, and zero command,
file, patch, web, MCP, or unknown tool events. Token usage stays `null` when the CLI does not
report it. This path includes CLI prompting and harness behavior and is not direct API model
performance.

**Codex CLI external agent** uses `codex-cli-agent` with no VeriGym model client. It launches once
inside the visible task workspace, may read/edit only visible files, and returns a submission
without judging correctness. VeriGym validates direct edits, freezes the candidate, and invokes
the existing hidden verifier. CLI event, command, file, patch, token, cost, and wall-time fields
are recorded as external-agent accounting; VeriGym-native `tool_calls` remains unchanged.

## Capability and identity evidence

Set a binary, run the zero-model-call doctor, and reuse its sealed report:

```bash
export VERIGYM_CODEX_BINARY=/opt/codex/bin/codex
verigym-codex doctor --json /tmp/codex-capabilities.json
export VERIGYM_CODEX_CAPABILITY_FILE=/tmp/codex-capabilities.json
```

Doctor runs exactly `--version`, `--help`, and `exec --help`. Execution is rejected if the binary
name, metadata, or SHA-256 changes. Requested model identity is always recorded; observed model
identity is recorded only when a machine event supplies it. `requested_only` must not be treated
as an observed provider identity.

Configure authentication without placing secrets in options or artifacts:

```bash
export VERIGYM_CODEX_AUTH_MODE=chatgpt_cli_session
verigym-codex auth-preflight --json /tmp/codex-auth-preflight.json
# The compatibility label above resolves explicitly to inherited_codex_login.
# The legacy label remains accepted:
export VERIGYM_CODEX_AUTH_MODE=inherited_codex_login
# Or:
export VERIGYM_CODEX_AUTH_MODE=api_key_env
export VERIGYM_CODEX_CREDENTIAL_ENV=OPENAI_API_KEY
```

`chatgpt_cli_session` and `inherited_codex_login` share
`codex.auth.inherited_chatgpt_session.v1`; reports use that semantic ID for comparison while
retaining the requested label as provenance. The inherited-login mode passes `HOME`/`CODEX_HOME`
because current CLI login state may require them. The preflight invokes only `codex login status`;
it never starts login, logout, account switching, or a model process. Project instructions are
disabled, MCP is configured empty, execution occurs under `/tmp`, and ancestor
`AGENTS.md`/`.codex` contamination is rejected. This is still a `local_trusted` pilot, not a
hardened boundary against a malicious CLI or incomplete upstream event telemetry. Track B is
intentionally restricted to LocalRuntime.

## Fixed real smoke

Ordinary CI runs only fake-CLI tests. A protected local audit uses one explicit model and makes
exactly four model-bearing CLI launches:

```bash
export VERIGYM_RUN_CODEX_CLI_TESTS=1
export VERIGYM_CODEX_MODEL=<exact-model-id>
export VERIGYM_CODEX_AUTH_MODE=<mode-label>
python scripts/run_codex_cli_smoke.py --output /new/path/codex-smoke
```

The launcher refuses an existing output root, retries, best-of-K selection, or outer repair. It
runs both tracks on `and-gate-basic` and `counter-basic`, retains failures, replays with an
unavailable Codex path, generates JSON/CSV/Markdown reports, and scans for credentials, host
paths, and hidden assets. PPA stays null.

## Prepared VerilogEval pilot

`examples/experiments/codex-cli-verilog-eval-pilot.yaml` freezes five upstream V2 task IDs,
per-task hashes, source commit, dataset hash, and selection rationale. Prepare its final plan from
the matching user-supplied checkout:

```bash
export VERIGYM_VERILOG_EVAL_ROOT=/path/to/verilog-eval
python scripts/run_codex_cli_pilot.py \
  --plan-output /new/path/codex-pilot-plan.json
```

Without both `VERIGYM_RUN_CODEX_PILOT=1` and
`VERIGYM_CODEX_PILOT_BUDGET=/path/to/budget.yaml`, this command writes only the immutable plan:
no run directory and no model call. A valid budget fixes 30 planned/process attempts, at most four
hours, at most three infrastructure failures, and forbids retry/selection. The pilot is an
integration study. Never pool tracks or differing task hashes, model identities, CLI versions, or
capability fingerprints, and do not publish a universal score.

## Artifacts and interpretation

Both tracks store `capabilities.json`, `invocation.json`, redacted raw/parsed events,
`identity.json`, `accounting.json`, and `summary.json` in `artifacts/codex_cli/`. These files are
integrity-bound. Replay reads the candidate, manifest, verifier inputs, and scorecard; it never
imports the plugin or launches Codex. Service/auth/transport/parser failures are infrastructure
outcomes, while hidden-test failures after a structurally successful episode are ordinary
candidate failures.
