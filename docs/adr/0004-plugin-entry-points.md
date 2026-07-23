# ADR 0004: Versioned plugin entry points

- Status: accepted

## Decision

External suites, tools, agents, models, and runtimes use Python entry-point groups and strict
descriptor API version `1.0`. Discovery records package/version origins and isolates individual
load failures.

## Consequences

Extensions install without editing core registries. Plugin code is trusted host code, while task
policy and runtime enforcement remain core responsibilities. Incompatible and duplicate plugins
fail explicitly.
