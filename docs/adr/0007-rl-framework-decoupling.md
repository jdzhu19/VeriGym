# ADR 0007: Keep RL frameworks outside the evaluator

- Status: accepted

## Decision

The MVP exposes typed run, sampling, replay, and reporting services, but does not embed an RL
loop, trajectory format, reward trainer, or external agent framework.

## Consequences

Evaluation artifacts remain stable and framework-neutral. Future training integrations, if
authorized, must consume the public contracts rather than change verifier semantics or weaken
hidden-data boundaries.
