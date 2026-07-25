# VeriGym Codex CLI Integration

This package provides two deliberately separate VeriGym plugins:

- `codex-cli-exec-model` runs one `codex exec` process in a new empty directory and adapts its
  final machine-readable event to `ModelClient`. It is valid for ChatEval only when the event
  stream proves zero file, command, web, MCP, or other tool use. This is a CLI-mediated model
  proxy, not a direct API benchmark.
- `codex-cli-agent` runs one external coding-agent episode in the visible LocalRuntime workspace.
  The CLI may edit visible task files; VeriGym then applies its ordinary workspace-policy check,
  candidate freeze, and hidden verifier. External CLI actions never increment VeriGym-native
  tool-call counters.

## Install and discover

Install matching wheels in an isolated environment:

```bash
python -m pip install dist/verigym-0.1.0-*.whl \
  integrations/verigym-codex-cli/dist/verigym_codex_cli-0.1.0-*.whl
verigym plugins list
```

The package registers `verigym.models` and `verigym.agents` entry points. Configuration accepts
only bounded, typed, secret-free options. Supply an explicit model ID; no CLI or provider default
is inferred.

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

Each run stores exactly these files under `artifacts/codex_cli/`:

```text
capabilities.json  invocation.json  raw_stdout.jsonl  raw_stderr.log
parsed_events.jsonl  identity.json  accounting.json  summary.json
```

Reasoning is discarded, secrets and runtime roots are redacted, output is bounded, and the
ordinary run integrity manifest binds every file. `verigym replay <run-dir> --verify` uses frozen
artifacts and the hidden verifier without launching Codex.

Offline tests use `tests/fake_codex.py`. Real execution requires the explicit opt-in and fixed
launchers documented in `docs/integrations/codex_cli.md`.
