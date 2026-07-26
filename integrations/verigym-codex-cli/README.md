# VeriGym Codex CLI Integration

This package provides two deliberately separate VeriGym agent plugins:

- `codex-cli-readonly-agent` runs one `codex exec` process in a fresh empty directory under the
  CLI read-only sandbox. A typed fail-closed event policy permits only harness planning and
  non-side-effecting reads confined to that empty directory. It rejects writes, patches,
  outside-directory or home/config reads, network, MCP, external, and unknown tools. After
  validation, the trusted adapter materializes the text response through VeriGym's ordinary
  `file.apply_patch` action; the CLI never receives the visible workspace.
- `codex-cli-agent` runs one external coding-agent episode in the visible LocalRuntime workspace.
  The CLI may edit visible task files; VeriGym then applies its ordinary workspace-policy check,
  candidate freeze, and hidden verifier. External CLI actions never increment VeriGym-native
  tool-call counters.

Codex CLI 0.144.6 has no supported true no-tools mode, so the former
`codex-cli-exec-model`/ChatEval identity is retired. Both current paths are CLI agent-harness
evaluations; neither is direct API evaluation or ChatEval-compatible. Historical sealed bundles
retain their original labels and verdicts unchanged.

## Install and discover

Install matching wheels in an isolated environment:

```bash
python -m pip install dist/verigym-0.1.0-*.whl \
  integrations/verigym-codex-cli/dist/verigym_codex_cli-0.1.0-*.whl
verigym plugins list
```

The package registers two `verigym.agents` entry points. Configuration accepts only bounded,
typed, secret-free options. Supply an explicit model ID; no CLI or provider default is inferred.

Both tracks own reasoning effort explicitly. The strict `reasoning_effort` option is `xhigh`;
each process appends `-c model_reasoning_effort="xhigh"` to its argument array so an incompatible
user default cannot affect the request. Safe configuration, invocation, manifest, and report
identities record requested/effective effort, the `verigym_explicit_cli_override` source, and
that inherited effort is not allowed. User Codex configuration is neither edited nor copied into
evidence.

## Zero-call doctor

```bash
export VERIGYM_CODEX_BINARY=/absolute/path/to/codex
verigym-codex doctor --json /tmp/codex-cli-capabilities.json
```

Doctor executes only `--version`, `--help`, and `exec --help`. The sealed report records the
executable hash, CLI version, supported sandbox/approval modes, event protocol, and a capability
fingerprint with `model_call_count: 0`.

Authentication is selected by the secret-free `VERIGYM_CODEX_AUTH_MODE` label. The explicit
compatibility label `chatgpt_cli_session` resolves to the unchanged `inherited_codex_login`
semantics. `inherited_codex_login`, `api_key_env`, and `custom_provider_environment` remain
accepted. Records preserve the requested label and also store the resolved mode and stable
semantic ID.

Check an existing inherited session without a model call or login flow:

```bash
export VERIGYM_CODEX_AUTH_MODE=chatgpt_cli_session
verigym-codex auth-preflight --json /tmp/codex-auth-preflight.json
```

Credential modes also require `VERIGYM_CODEX_CREDENTIAL_ENV`; only that selected environment
value reaches a later model process, and its value is never persisted.

## Evidence and replay

Each run stores these files under `artifacts/codex_cli/`:

```text
capabilities.json  invocation.json  raw_stdout.jsonl  raw_stderr.log
parsed_events.jsonl  identity.json  accounting.json  summary.json
event_policy.json (read-only track)
```

Reasoning is discarded, secrets and runtime roots are redacted, output is bounded, and the
ordinary run integrity manifest binds every file. `verigym replay <run-dir> --verify` uses frozen
artifacts and the hidden verifier without launching Codex.

Offline tests use `tests/fake_codex.py`. Real execution requires the explicit opt-in and fixed
launchers documented in `docs/integrations/codex_cli.md`.
