# ADR 0016: Permit identity-bound suite-managed external verifiers

- Status: accepted

## Decision

`SuiteAdapter` may optionally verify a frozen candidate when an upstream benchmark requires an
immutable per-instance execution environment that does not fit VeriGym's ordinary runtime plus
tool-plugin DAG. The suite must return the complete result set or `None`; VeriGym rejects missing,
extra, plugin, or request drift against the frozen task graph.

The hook runs after ordinary candidate export and repository patch replay. It receives no agent or
model handle. External adapters own environment validation, containment, limits, cleanup, and safe
artifact persistence. Core scoring, trace events, reports, qualification, and verifier-only replay
remain unchanged consumers of normalized `VerifierResult` records.

## Consequences

HWE-Bench can retain its official per-PR Docker images and hidden scripts without teaching the
core about Ibex, Chisel, FuseSoC, Verilator, or commercial EDA commands. Ordinary suites continue
using `VerifierExecutor`. A suite-managed implementation is trusted plugin code, not an agent tool,
and therefore requires distribution audit, immutable request identities, no-daemon unit tests, and
an explicit real-environment smoke before campaign use.
