# ADR 0011: Separate Codex CLI model-proxy and external-agent tracks

- Status: accepted

## Context

`codex exec` can serve either as a one-turn text-generation transport or as a coding agent with
workspace tools. Treating those modes as one model benchmark would mix different information,
actions, costs, and security boundaries. The CLI also does not provide the same observation
surface as a direct model API.

## Decision

Ship the pilot as a separate `verigym-codex-cli` package with two entry points.

`codex-cli-exec-model` implements `ModelClient`, runs in an empty directory, and is valid only
when machine events prove zero tool use. It is labeled `codex_cli_model_proxy` and never described
as a direct API benchmark.

`codex-cli-agent` implements `AgentAdapter`, receives only a narrow core-owned bridge to a visible
LocalRuntime workspace, and may edit it once. The existing candidate freeze and hidden verifier
remain authoritative. Its CLI events, tools, tokens, cost, and wall time use separate external
accounting.

Both tracks use zero-call capability discovery, one exact executable hash, explicit model
selection, bounded secret-free options, `shell=False` process execution, ephemeral sessions,
machine-event parsing, and model-free replay. Reports partition by track, requested/observed
model, CLI version, and capability fingerprint.

## Consequences

Results can be displayed side by side but are not interchangeable systems. Track B improvements
cannot be attributed solely to the model. Missing identity, token, or cost values remain unknown,
and infrastructure failures never become incorrect candidates. The LocalRuntime external-agent
path is a conformance pilot, not an untrusted-code sandbox.
