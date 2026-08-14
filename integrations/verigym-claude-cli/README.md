# VeriGym Claude CLI integration

`verigym-claude-cli` registers `claude-cli-agent`, a multi-turn Claude Code harness whose model
transport remains on the trusted host while all repository operations are delegated to VeriGym.
It is a CLI-agent evaluation, not a direct API or ChatEval path.

## Install and zero-call qualification

```bash
python -m pip install -e integrations/verigym-claude-cli
install -d -m 0700 /data/jzhu484/Agent/.vgpt
export VERIGYM_CLAUDE_BINARY=/home/jzhu484/.npm-global/bin/claude
export VERIGYM_CLAUDE_BROKER_ROOT=/data/jzhu484/Agent/.vgpt
```

The adapter runs `--version` and `--help` before any model call, hashes the resolved executable,
and rejects a CLI that lacks `--bare`, strict MCP, stream JSON, explicit model/effort, disabled
session persistence, `--max-budget-usd`, or exact tool controls. `VERIGYM_CLAUDE_BROKER_ROOT` must be a short,
mode-0700 directory; no socket or large scratch artifact is placed in `/tmp` by the real path.

Bare provider authentication requires a credential-free HTTPS `ANTHROPIC_BASE_URL` and exactly one
of `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`. The token form is preserved for gateways that use
an `Authorization` header; it is never aliased to the API-key form. The adapter never opens Claude
user settings. It passes the selected credential only to the host Claude process and records its
environment-variable name and the provider origin, never credential or proxy values. Set
`allow_proxy_environment=true` only when the provider route needs the existing uppercase
`HTTP_PROXY`, `HTTPS_PROXY`, or `NO_PROXY` values; the global VPN is not modified.

Nonessential Claude telemetry, error/bug reporting, and auto-update traffic are disabled for every
run. `MAX_MCP_OUTPUT_TOKENS=524288` keeps Claude's default MCP-output allowance from clipping a
response that is still inside the broker's 512-KiB byte safety bound; it is not a model-token limit.

## Evaluation settings

Every run requires an explicit model. The current frozen effort policy is `max`:

```text
--agent claude-cli-agent
--agent-option 'model_id="deepseek-v4-flash[1m]"'
--agent-option 'reasoning_effort="max"'
--agent-option 'expected_context_window=1000000'
--agent-option 'max_process_time_s=1800'
--agent-option 'max_provider_billed_units=2000000'
--agent-option 'max_budget_usd=2.0'
```

`max_process_time_s` is the outer process wall timeout. `max_output_bytes` (8 MiB by default)
bounds captured process evidence, not model tokens. `max_provider_billed_units` counts input, output,
cache-creation, and cache-read tokens from live provider messages, deduplicated by message ID.
`max_budget_usd` is also passed to Claude's native print-mode budget control. The defaults are
2,000,000 cache-inclusive tokens and USD 2 per episode. No hidden turn/model-call override, retry,
fallback model, or best-of-K setting is accepted.

Once the Claude process launches, reaching its configured wall deadline is an infrastructure-valid
`agent_timeout`, even if it has not used a broker tool. Process-launch, runtime-security, event
protocol, and broker infrastructure failures remain infrastructure-invalid.

Both provider thresholds are checked after each response becomes observable, so one in-flight
response can overshoot a threshold. For the current DeepSeek route, the campaign also freezes the
observed 1,000,000-token context window; the 32,000-token per-response maximum remains recorded
upstream provenance.

Training campaigns can additionally configure all three broker limits together:

```text
--agent-option 'max_tool_calls=32'
--agent-option 'max_patch_calls=8'
--agent-option 'max_consecutive_rejected_calls=3'
```

The broker and provider monitors signal the process runner as soon as a limit becomes terminal;
the runner terminates the complete Claude process group. These are infrastructure-valid agent
failures named `broker_resource_limit` or `provider_resource_limit`, not verifier or infrastructure
failures. Successful training episodes must include provider-reported input and output token
counts. Missing usage is fail-closed as `provider_usage_missing` so a paid campaign cannot silently
accept an unaccounted trajectory.

A formal campaign must freeze a distinct `AgentVersionManifest` with
`base_agent_id=claude-cli-agent`, the exact model, `max` effort, and the effective auth semantic.
For the current gateway token route that semantic is
`claude.auth.anthropic_auth_token_env_custom_base.v1`; the API-key route instead uses
`claude.auth.anthropic_api_key_env_custom_base.v1`. It must not reuse a Codex/Luna or direct
DeepSeek identity.

## Tool and artifact boundary

Claude runs from an empty private control directory with built-in tools disabled. The strict MCP
server exposes only `list_files`, `read_file`, `apply_patch`, `run_public_test`, `inspect_diff`, and
`finish`. The MCP child is launched with provider and proxy variables removed. Repository commands
execute in the selected official Docker image with networking off; the provider credential never
enters that image.

Artifacts live under `artifacts/claude_cli/`. They contain executable/configuration identities,
content-free event summaries, broker counts, observed context/output ceilings, failure
classification, and final-verifier status. `provider-usage.json` records input, output, total,
cache-creation, cache-read, and cost fields when the provider supplies them, plus explicit
completeness flags, the cache-inclusive observed total, and any provider-limit termination.
Prompts, raw stdout, messages, tool arguments/results, source contents, and thinking text are
deliberately excluded.
