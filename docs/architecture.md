# Platform Architecture

VeriGym is an evaluation environment, not an RTL benchmark or an agent implementation. Its core
contracts keep the task suite, agent harness, execution backend, EDA toolchain, and evaluation
summary independently identifiable and replaceable.

```text
SuiteAdapter ──> VeriTask ──> AgentProtocol ──> ToolPlugin
                     │              │               │
                     │              └──────> RuntimeSession
                     │                              │
                     └──────────────> Verifier DAG ─┘
                                            │
                         Trace + ScoreCard + Evaluation Summary
                                            │
                              Offline Evaluation Campaign
```

## Evaluation Protocols

- **ChatEval** performs one normalized model request and grants no tool feedback.
- **AgentEval** exposes bounded observations and multi-turn actions through an agent harness.
- **EvolvingAgentEval** freezes an agent version, its update inputs, update procedure, and lineage,
  then compares versions on an independently sealed held-out split. The alpha implementation is
  limited to observable trajectory export and context-memory evolution; external weight training
  remains non-executable.

## Extension and Trust Boundaries

`SuiteAdapter` converts external task collections to strict `VeriTask` records. Agent and model
plugins consume normalized requests. Tool plugins execute declared argument arrays through a
runtime session; verifier stages run only after the candidate is frozen. External plugins are
trusted host code, while benchmark contents, generated RTL, tool output, and artifacts are treated
as untrusted data.

Toolchain results carry declared and resolved profile identities. The resolved identity binds tool
and image versions, scripts, constraints, libraries, and metric semantics. Correctness can be
summarized across compatible tasks, but PPA values are comparable only when the complete resolved
profile hashes match. Commercial binaries, licenses, PDKs, credentials, and proprietary scripts
remain site-owned and are never packaged by VeriGym.

## Reproducibility Boundary

Every run records task, suite, model, agent, runtime, tool-policy, profile, and source provenance.
Replay operates on a frozen candidate without calling the model. Experiment reports preserve
denominators and infrastructure failures instead of collapsing incompatible runs into a universal
score. Campaign reporting validates and projects completed ChatEval, AgentEval, and
EvolvingAgentEval experiments into one path-free summary; it does not execute those protocols or
rank incompatible PPA partitions.
