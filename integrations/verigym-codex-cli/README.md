# VeriGym Codex CLI Integration

This package provides three ordinary evaluation plugins plus an opt-in training-only teacher:

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
- `codex-cli-agenteval-agent` is the scoring-only RTL AgentEval adapter. It freezes Codex CLI
  0.147.0, GPT-5.4, `xhigh`, and agent version
  `codex-cli-agenteval-gpt54-xhigh-v5`. One ephemeral, read-only
  `codex exec --json` process receives only the six `repository_action.v2` MCP tools through the
  Unix-socket broker. Shell, Web, skills, plugins, apps, rules, and user configuration are
  disabled. Its prompt and broker observations expose the task/process wall-time, rounded elapsed
  and remaining time, and the static limits of 40 tool calls, 20 patch calls, and three
  consecutive rejections. The prompt reserves the final 60 seconds for final patching,
  compile/PPA, diff inspection, and typed `finish`.
- `codex-cli-mcp-teacher` is available only to captured training campaigns. It fixes GPT-5.4 with
  `xhigh` reasoning, disables shell and web search, and exposes only the required VeriGym MCP
  repository tools.

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

The package registers four `verigym.agents` entry points. Configuration accepts only bounded,
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

The scoring-only AgentEval track instead stores only sanitized capability, invocation, identity,
usage/accounting, broker counters, content-free event statistics, and summary documents. It does
not store raw stdout/stderr, parsed event text, prompts, responses, or a training transcript.
Recoverable patch failures use fixed format/header/body/context/count/range/empty/rename
categories. Terminal path failures expose only the allowlisted tool name and a bounded path
category; request arguments, paths, and raw exceptions are never returned or persisted.

After every returned Codex process, the adapter tolerantly parses the event stream before applying
broker/process failure precedence. It emits exactly one external-agent identity: a complete
terminal event may provide the observed model and usage, while an incomplete stream records only
the requested model with `usage_complete: false`. It never estimates tokens. Prompt, tool-policy,
capability, and agent-version fingerprints are bound into the safe invocation and identity
evidence. Recoverable broker responses include a bounded state summary and next allowed actions;
malformed unified diffs remain recoverable, including malformed hunk headers and bodies. Empty
visible files produce a valid zero-line observation. Path, symlink, hardlink, hidden-asset, and
workspace-boundary violations remain terminal policy failures. Terminal broker evidence stores
only an allowlisted failure subtype, never the underlying diagnostic or path.

Reasoning is discarded, secrets and runtime roots are redacted, output is bounded, and the
ordinary run integrity manifest binds every file. `verigym replay <run-dir> --verify` uses frozen
artifacts and the hidden verifier without launching Codex.

Offline tests use `tests/fake_codex.py`. Real execution requires the explicit opt-in and fixed
launchers documented in `docs/integrations/codex_cli.md`.

## Run a bounded MCP teacher

Configure all broker limits together. The current CVA6 collection freezes 32 total tool calls,
eight executed patch attempts, three consecutive rejected calls, and a 600-second process wall
timeout. Reaching a broker limit cancels the complete Codex process group and records an
infrastructure-valid `broker_resource_limit` agent failure. Reaching the configured process wall
deadline is likewise an infrastructure-valid `agent_timeout`, including when the model has not yet
used a broker tool. Launch, runtime-security, and protocol failures remain infrastructure-invalid.
A successful teacher stream without input/output usage is rejected as infrastructure-invalid
`provider_usage_missing`.

Successful teacher artifacts also include `provider-usage.json` with input, output, total, and
cached-input tokens. A deadline failure records an explicit incomplete usage artifact instead of
inventing missing counts. The cost fields remain null when the Codex CLI does not report currency
data.
