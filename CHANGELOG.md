# Changelog

## Unreleased

- Added an isolated, multi-turn `repository_action.v2` workflow for online Qwen3.5 training with
  rLLM and veRL. A host-owned broker retains the live repository, Docker runtime, and verifier;
  the training container receives only frozen public inputs, bounded observations, and sparse
  terminal rewards.
- Added a versioned repository state machine that permits tasks without public tests to finish
  after a successful patch and diff inspection, while retaining exact v1 replay compatibility.
- Extended online policy export to register both legacy verifier-broker and repository-broker
  rollouts without changing an existing frozen workflow identity.

## 0.1.0 alpha - 2026-08-02

- Stabilized the versioned task, verifier, runtime, artifact, replay, experiment, reporting, and
  plugin contracts for release-candidate auditing.
- Added ChatEval and AgentEval paths, VerilogEval V2 adaptation, Icarus and profile-scoped Yosys
  evaluation, Local and Docker runtimes, and Codex CLI agent conformance tracks.
- Added bounded repository-level RTL repair, observable trajectory export, decomposed rewards,
  contamination-controlled splits, and immutable context-memory agent-version comparison.
- Added the provider-neutral `repository_action.v2` protocol, deterministic multi-turn API-call
  accounting and replay, and three independent repository conformance tasks.
- Added build provenance, artifact integrity, schema compatibility, secret-aware scanning, and
  installed-distribution conformance checks.

This alpha does not claim cross-toolchain PPA comparability, commercial execution, built-in
training/RL, continuously evolving benchmark releases, or broad external repository coverage.
