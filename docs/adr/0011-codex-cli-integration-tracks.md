# ADR 0011: Separate Codex CLI read-only and workspace-writing agent tracks

- Status: accepted

## Context

`codex exec` is an agent harness. Codex CLI 0.144.6 does not expose a supported true no-tools
mode: read-only sandboxing restricts effects but does not remove tool availability. Treating a
read-only invocation as a pure model proxy would therefore misstate its semantics. The CLI also
does not provide the same observation surface as a direct model API.

## Decision

Ship the pilot as a separate `verigym-codex-cli` package with two agent entry points.

`codex-cli-readonly-agent` implements `AgentAdapter` and runs once in a fresh empty directory with
the CLI read-only sandbox. A typed fail-closed policy permits only harness planning and
non-side-effecting reads confined to that directory. Writes, patches, outside-directory or
home/config reads, network, MCP, external, and unknown tools are forbidden. A passing text
response is materialized through VeriGym's ordinary `file.apply_patch` action, then submitted
through the existing candidate-freeze and hidden-verifier flow. The CLI never receives the
visible task workspace.

`codex-cli-agent` implements `AgentAdapter`, receives only a narrow core-owned bridge to a visible
LocalRuntime workspace, and may edit it once. The existing candidate freeze and hidden verifier
remain authoritative. Its CLI events, tools, tokens, cost, and wall time use separate external
accounting.

Both tracks use zero-call capability discovery, one exact executable hash, explicit model
selection, bounded secret-free options, `shell=False` process execution, ephemeral sessions,
machine-event parsing, and model-free replay. Reports partition by execution surface,
interaction class, harness, tool policy, track, requested/observed model, CLI version, and
capability fingerprint.

The former `codex-cli-exec-model`/`codex_cli_model_proxy` identity is retired. It is not
ChatEval-compatible and is not replaced by a direct API path. Historical sealed evidence remains
immutable and retains its original verdict.

## Consequences

Results can be displayed side by side but are not interchangeable systems. Improvements on
either track cannot be attributed solely to the model. Direct API evaluation is unimplemented
and unexecuted. Missing identity, token, or cost values remain unknown, and infrastructure
failures never become incorrect candidates. These LocalRuntime paths are conformance pilots, not
untrusted-code sandboxes.
