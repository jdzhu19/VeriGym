# Codex CLI conformance pilot

The optional `verigym-codex-cli` distribution exposes two systems that must remain separate in
plans, reports, and comparisons.

## Baseline status

Commit `1deea550815603f72f68887b8db3577ea9c72462` is the final Codex CLI
semantic-conformance baseline. Its sealed PASS evidence and every earlier FAIL/BLOCKED bundle
are immutable. See the [release/audit index](../audits/codex_cli_smoke.md) for identities and
historical verdicts.

## Integration tracks

**Codex CLI read-only single-turn agent** uses `codex-cli-readonly-agent`. Every episode launches
one non-interactive CLI process in a fresh empty directory, supplies all visible task context on
stdin, and parses JSONL events. Codex CLI 0.144.6 has no supported true no-tools mode, so this
path is not a `ModelClient`, is not ChatEval-compatible, and is not a pure model evaluation. Its
typed fail-closed policy permits only harness planning and explicitly classified
non-side-effecting reads confined to the empty directory. Writes, patches, outside-directory or
home/config reads, network, MCP, external, and unknown tools are forbidden. A passing response
is parsed as one RTL submission, materialized by the adapter through the ordinary
`file.apply_patch` action, and enters candidate freeze and the hidden-verifier flow. The CLI
never receives or writes the visible task workspace.

**Codex CLI external agent** uses `codex-cli-agent` with no VeriGym model client. It launches once
inside the visible task workspace, may read/edit only visible files, and returns a submission
without judging correctness. VeriGym validates direct edits, freezes the candidate, and invokes
the existing hidden verifier. CLI event, command, file, patch, token, cost, and wall-time fields
are recorded as external-agent accounting; VeriGym-native `tool_calls` remains unchanged.

Both paths are Codex CLI agent-harness evaluations. Direct API support is unimplemented and was
not executed; it remains a separate future integration. Neither path is a direct API benchmark.
The former model-proxy identity is retired; historical sealed bundles and their verdicts remain
immutable.

## Docker runtime-owned execution

The Docker backend uses [ADR 0012](../adr/0012-docker-runtime-owned-codex-tools.md), architecture
Path A. The host Codex app-server owns the existing ChatGPT session and provider control plane,
while every shell, patch, and filesystem operation is delegated through a loopback stdio bridge
to one credential-free `codex exec-server` container. The plugin calls the generic
`ExternalAgentBridge.execute_process()` operation; it does not launch a host subprocess against a
host workspace.

The trusted app-server environment is built centrally and fails closed before launch unless its
loopback WebSocket is guaranteed to bypass HTTP(S) proxies. Only uppercase `HTTP_PROXY` and
`HTTPS_PROXY` provider transport values are forwarded. `NO_PROXY` and `no_proxy` are synthesized
with mandatory localhost, IPv4-loopback, and IPv6-loopback entries; lowercase host transport
proxies and `ALL_PROXY` are ignored. Evidence contains the control names and bypass status only.

The agent container has `network=none`, an immutable Codex 0.144.6 image, a non-root effective
UID/GID, read-only rootfs, bounded `/tmp`, and only `/workspace` mounted. It receives no
credential, proxy, host-home, repository, hidden-verifier, or Docker-socket material. The
`outer_runtime_delegated` inner label is valid only because the inspected Docker boundary owns
these controls. A separate immutable Icarus 12 image performs candidate verification after
freeze. Runtime artifacts record both role image IDs, effective controls, logical paths, process
limits, and verified cleanup.

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
retaining the requested label as provenance. The inherited-login host control plane passes
`HOME`/`CODEX_HOME` because current CLI login state may require them; neither name nor its
contents enters the agent container. The preflight invokes only `codex login status`;
it never starts login, logout, account switching, or a model process. Project instructions are
disabled, MCP is configured empty, execution occurs under `/tmp`, and ancestor
`AGENTS.md`/`.codex` contamination is rejected. Host execution remains available only under the
explicit `host_local_trusted` compatibility label. Docker pilot runs require
`docker_outer_runtime_delegated`; there is no Docker-to-local fallback.

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
runs both agent tracks on `and-gate-basic` and `counter-basic`, retains failures, replays with an
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

Planning also requires exact core/plugin wheels, immutable verifier and agent image IDs, a
zero-call capability report, and the existing-login preflight. It runs all five official
transformed references through the network-none Icarus 12 verifier before permitting a model
process. Without both `VERIGYM_RUN_CODEX_PILOT=1` and
`VERIGYM_CODEX_PILOT_BUDGET=/path/to/budget.yaml`, this command writes only the immutable plan:
no run directory and no model call. A valid budget fixes 30 planned/process attempts, at most four
hours, at most three infrastructure failures, and forbids retry/selection. The pilot is an
integration study. Never pool tracks or differing task hashes, model identities, CLI versions, or
capability fingerprints, and do not publish a universal score.

## Artifacts and interpretation

Both tracks store `capabilities.json`, `invocation.json`, redacted raw/parsed events,
`identity.json`, `accounting.json`, and `summary.json` in `artifacts/codex_cli/`; the read-only
track also stores `event_policy.json`. Docker runs additionally store `runtime_process.json`
with sanitized role identities and security evidence. These files are integrity-bound. Replay
reads the candidate, manifest, verifier inputs, and scorecard; it never imports the plugin or
launches Codex or its tool bridge. Service/auth/transport/parser failures are infrastructure
outcomes, while hidden-test
failures after a structurally successful episode are ordinary benchmark outcomes for the frozen
candidate, not integration failures. They remain unrepaired.
