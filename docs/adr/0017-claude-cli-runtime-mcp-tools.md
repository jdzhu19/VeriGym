# ADR 0017: Runtime-owned MCP tools for Claude CLI

## Status

Accepted for the bounded Claude CLI repository-agent integration.

## Context

Claude CLI can provide the desired multi-turn DeepSeek-compatible harness, but it has no Codex
app-server remote-environment protocol. Running Claude's built-in Bash/Edit tools against the host
task workspace would place untrusted model actions outside the official benchmark Docker boundary.
Putting Claude itself in the benchmark container would instead copy provider credentials into an
untrusted repository/tool image and require network access there.

## Decision

Keep Claude CLI as a trusted host control plane in bare, non-persistent print mode. Disable every
built-in tool and load exactly one inline, strict MCP server. A fixed credential-scrubbed stdio
adapter forwards tool calls over a private Unix socket to the parent plugin. The parent invokes
core-owned policy-checked file tools or argument-array commands in the selected network-none task
Docker session. Public tests remain separate declared calls. The hidden verifier is never mounted
in the agent session and runs only after candidate freeze.

Set the requested model and `max` effort explicitly. Configure Claude's native dollar budget and a
separate cache-inclusive live-stream token threshold. Do not configure a hidden internal-turn or
model-call override, fallback, retry, or best-of-K. Retain the ordinary process wall boundary,
bounded process-output evidence, and broker limits. Treat the CLI/provider-reported context window
and per-response output maximum as observed provenance; one in-flight response can cross a
response-granular provider threshold before cancellation.

Persist no raw prompt, stream event, assistant/tool content, or thinking content. Store only
executable/configuration identity, content-free event summaries, usage, broker accounting, hashes,
and failure/policy outcomes.

Resolve exactly one host authentication form: `ANTHROPIC_AUTH_TOKEN` for an Authorization-header
gateway or `ANTHROPIC_API_KEY` for API-key authentication. Preserve that form without aliasing it,
bind its semantic ID into the frozen agent version, and scrub both variable names from the MCP
child environment.

Disable Claude's nonessential telemetry, error/bug reporting, and auto-update traffic. Raise the
CLI's MCP-output allowance above the broker's fixed 512-KiB response bound so the CLI does not add
a lower tool-output truncation threshold. Model usage is bounded separately by a native dollar
budget and a cache-inclusive live-stream token monitor.

## Consequences

This creates a distinct `claude_cli_external_agent` identity and `artifacts/claude_cli` namespace.
It cannot be substituted into a frozen Codex or direct-API campaign. The trusted computing base
includes Claude CLI and the MCP adapter/broker, while repository commands and verification retain
the official Docker isolation. A configured provider/broker resource threshold is an
infrastructure-valid agent failure. Provider authentication, transport, service, or malformed
usage failures remain infrastructure-invalid and must never be reported as verifier rejection.
