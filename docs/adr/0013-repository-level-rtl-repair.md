# ADR 0013: Runtime-Owned Repository RTL Repair

## Status

Accepted for Milestone 10A.

## Decision

Repository repair reuses the immutable experiment and ordinary run pipeline.
The suite materializes only a frozen visible repository and issue text. A
runtime-managed launcher executes declared public tests from a separate
read-only mount. Docker owns the external Codex process and its workspace
mounts; the credential-bearing host control plane communicates through the
existing loopback broker, while the agent container remains credential-free
and network-none.

The candidate is frozen before hidden assets are staged. VeriGym derives a
canonical text-only unified patch and proves in a fresh directory that applying
it to the base recreates the final repository hash. Hidden regression uses a
separate network-none Icarus Verilog 12 session.

## Consequences

Task adapters remain independent of Codex. Public test feedback cannot become a
hidden-data channel, and replay needs neither the agent nor the public launcher.
Binary patches, arbitrary shell public tests, evolving repositories, formal
verification, PPA, and external repository benchmarks are outside this
milestone.
