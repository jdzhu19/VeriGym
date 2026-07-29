# ADR 0014: Export only observable trajectories and freeze context updates

- Status: accepted

## Decision

Repository-level runs may be exported through the versioned
`observable_repo_trajectory_v1` policy. The exporter is offline, bounded, and
fail-closed. It admits only public task data, observable messages and tool
results, workspace and candidate metadata, outcomes, usage, and recomputable
reward vectors. It never exports private reasoning, hidden tests, reference
solutions, credentials, proxy values, authentication files, or raw host paths.

The first evolving-agent mode is `context_memory`. A memory-free v0 and a
memory-bearing v1 retain the same executable, model, reasoning,
authentication, runtime, tool-policy, source, package, and image identities.
The memory builder sees only a sanitized summary of eligible training
trajectories. Held-out public assets remain gated until v1 is frozen.

## Consequences

Agent evolution is explicit, immutable, replayable without external calls, and
comparable by version identity. Memory is bounded, task-independent, code-free,
and supplied as a distinct read-only prompt artifact. External trainer and
weight-bearing agent manifests remain provenance-only interfaces; M10B neither
modifies model weights nor implements SFT or RL.
