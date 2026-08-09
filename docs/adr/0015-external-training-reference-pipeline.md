# ADR 0015: Keep the reference trainer outside the evaluator

- Status: accepted

## Decision

VeriGym provides an independently installable external-training reference integration. It
consumes only validated observable trajectories, deterministic rewards, and frozen task splits.
It may call ordinary VeriGym runs as an online reward oracle, but it cannot select held-out tasks,
change verifier semantics, or receive hidden verifier contents.

The integration records framework and algorithm configuration, model snapshot metadata, training
dataset identity, and checkpoint provenance. It does not add a trainer or model-weight dependency
to the core package. Trainer frameworks remain replaceable external consumers.

## Consequences

The repository can demonstrate the complete evaluation-to-training-to-evaluation interface
without claiming that VeriGym implements TRL, veRL, OpenRLHF, PPO, or GRPO. Infrastructure-invalid
rollouts remain distinct from model reward. Weight-bearing artifacts are registered by hash and
must be served through an explicitly compatible external runtime before evaluation.
