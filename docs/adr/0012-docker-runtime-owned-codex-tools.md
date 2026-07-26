# ADR 0012: Runtime-Owned Codex Tools

## Status

Accepted for the bounded Docker-backed Codex CLI pilot.

## Context

Changing a run from `LocalRuntime` to `DockerRuntime` did not previously
containerize an external agent: the plugin still launched Codex on the host
against a host workspace path. Provider authentication must remain outside any
model-controlled shell while the agent sees only public task files.

Codex CLI 0.144.6 supports an app-server remote environment whose shell,
patch, and filesystem requests are served by `codex exec-server`. Capability
and source inspection was performed without a model call. AppArmor and SELinux
child transitions are unavailable on the campaign host.

## Decision

Use contract architecture Path A, external tool delegation. A host Codex
app-server owns the existing ChatGPT authentication and provider control plane.
VeriGym starts one exact, hash-bound `codex exec-server` per episode in a
network-none Docker container. A loopback-only WebSocket-to-stdio bridge links
the app-server to that container; it is not reachable from the container or
another host.

The container runs non-root with a read-only root filesystem, dropped
capabilities, no-new-privileges, private PID/IPC namespaces, bounded resources,
and only the public task workspace mounted at `/workspace`. It receives no
credential or proxy names or values. The separate verifier image contains
Icarus 12, has network disabled, and receives hidden assets only after candidate
freeze.

`ExternalAgentBridge.execute_process()` is runtime-owned and uses strict
request, result, identity, and security schemas. Existing host execution remains
available only under the explicit `host_local_trusted` label. The Docker inner
sandbox label is `outer_runtime_delegated`; it never authorizes host
danger-full-access.

## Consequences

Each run records immutable agent and verifier image IDs, effective controls,
logical paths, cleanup, and credential-isolation evidence. Replay drops the
external-agent configuration and can execute only the verifier. This evaluates
Codex CLI agent harnesses, not a `ModelClient`, ChatEval path, pure API
evaluation, or direct API benchmark.
