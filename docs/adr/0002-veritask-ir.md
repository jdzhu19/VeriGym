# ADR 0002: VeriTask as the suite/evaluator boundary

- Status: accepted

## Decision

Suite adapters normalize native records into strict, versioned `VeriTask` objects. The IR binds
public task semantics, policies, budgets, and verifier topology while asset resolution keeps
hidden bytes out of model-visible data.

## Consequences

Core execution is suite-agnostic and task identities are hashable. Adapters carry the burden of
faithful normalization and source validation; raw third-party records are not persistent core
contracts.
