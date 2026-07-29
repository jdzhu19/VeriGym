# ADR 0007: Keep RL frameworks outside the evaluator

- Status: accepted

## Decision

The MVP exposes typed run, sampling, replay, and reporting services, but does not embed an RL
loop, reward trainer, or training framework. Milestone 10B later adds a bounded observable
trajectory interchange and deterministic reward derivation without changing this decision.

## Consequences

Evaluation artifacts remain stable and framework-neutral. Future training integrations, if
authorized, must consume the public contracts rather than change verifier semantics or weaken
hidden-data boundaries. External checkpoint and adapter manifests are provenance records only;
they are not executable in the Milestone 10B campaign.
