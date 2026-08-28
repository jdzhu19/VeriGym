# RTL commercial MCP qualification v1

Qualification date: 2026-08-28. This is bounded infrastructure evidence for the two pinned RTLLM
tasks; it is not a model campaign and must not be reported as a benchmark score.

This record remains the phase-one final-verifier qualification. The separately reviewed
[phase-two disposable-worker qualification](rtl_agent_dc_worker_qualification_v2.md) supersedes
only its earlier statement that agent-visible commercial feedback was not yet implemented.

## Scope

- RTLLM source commit: `41b26896e33b536940116a975626455eed3de65e`.
- Tasks: `rtllm/counter_12` and `rtllm/up_down_counter`.
- Functional paths: task-bound VCS/MCP on the control-plane host and on an SSH-connected HPC
  verifier.
- Final PPA path: DC/MCP on the HPC verifier, using the existing explicit-power `compile_ultra`
  contract.
- Open compatibility path: native Icarus/vvp 12.0, retained side by side with Icarus 13.

The VCS identity resolved to the site VCS 2023.12 SP2-2 installation. The DC identity resolved to
Design Compiler T-2022.03-SP1. No commercial binary, license value, PDK/library byte, benchmark
checkout, wrapper, server profile, raw report, or trajectory is committed with this record.

## Functional qualification

Both the local and SSH/HPC VCS/MCP transports ran four bounded cases:

| Task | Reference | Known-bad stuck-zero candidate |
| --- | --- | --- |
| `counter_12` | Passed | Rejected as `test_failed` |
| `up_down_counter` | Passed | Rejected as `test_failed` |

The same expected outcomes were observed on each transport. This establishes that the server-owned
hidden testbench and sentinels distinguish the frozen references from a simple incorrect design;
it does not prove completeness of the hidden tests.

## End-to-end VCS plus DC qualification

One frozen reference candidate per task then traversed the normal run path: verifier-profile
resolution before model authorization, VCS/MCP hidden regression, DC/MCP candidate synthesis,
DC/MCP reference synthesis, PPA projection, manifest/scorecard persistence, and offline replay
identity validation.

| Task | Hidden VCS | Candidate DC | Reference DC | Final PPA |
| --- | --- | --- | --- | --- |
| `counter_12` | Passed | Passed | Passed | Eligible |
| `up_down_counter` | Passed | Passed | Passed | Eligible |

The candidate was deliberately identical to the reference, so every recorded ratio was `1.0`.
These PPA values are qualification sentinels, not competitive results. Resolved identities were:

| Task | VCS verifier profile | Resolved verifier hash | DC toolchain profile | Resolved toolchain hash |
| --- | --- | --- | --- | --- |
| `counter_12` | `rtllm-counter-12-vcs-mcp-local-v1` | `2f2c8855f84f…` | `rtllm-counter-12-dc-mcp-hpc-v1` | `7633c1958a65…` |
| `up_down_counter` | `rtllm-up-down-counter-vcs-mcp-local-v1` | `2100f5856f1e…` | `rtllm-up-down-counter-dc-mcp-hpc-v1` | `fb567782f834…` |

Both stored runs passed offline replay validation. A copied `counter_12` run also passed full
`verigym replay --verify`: it re-resolved VCS/MCP and DC/MCP and reran hidden regression plus both
DC synthesis roles without a model call. Unit coverage separately checks expected-identity replay
and fixed-wrapper tamper rejection; the ordinary replay path checks all stored manifest, profile,
scorecard, task, candidate, and artifact identities before any re-execution.

## Disclosure checks

The persisted manifests, scorecards, and VCS artifact namespaces were scanned for verifier-host
paths, commercial installation roots, license-variable names, hidden-testbench paths, and VCS log
names. No match was found. VCS/MCP persisted only the normal request, empty bounded stdout/stderr
placeholders, structured tool result, and verifier result; the structured response itself contains
no raw output, diagnostic, report, hidden RTL, license value, or server path.

The Icarus 12 binaries used for local compatibility checks had SHA-256 identities
`4c46269062c1…` (`iverilog`) and `28beceafe4dc…` (`vvp`). Published AgentEval runs must still bind
their own exact runtime or immutable image identity rather than relying on this host note.

## Remaining boundary

VCS/MCP and DC/MCP remain verifier-control-plane services. Phase one does not expose commercial
PPA to the six-action AgentEval surface. Agent-visible DC/MCP needs a disposable isolated worker,
the same 3/default and 8/hard-limit accounting used by open PPA, and a separate reviewed security
claim before it can be enabled.

That additional boundary is now implemented and qualified in the phase-two record linked above;
this paragraph is retained as historical phase-one scope.
