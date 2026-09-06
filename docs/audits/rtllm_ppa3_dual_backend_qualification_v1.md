# RTLLM PPA-three dual-backend qualification v1

Date: 2026-09-02

Status: passed. Three RTLLM tasks are qualified under a distinct PPA-enabled variant for both an
open Yosys/OpenSTA partition and a commercial Synopsys Design Compiler/MCP partition. This is
zero-model infrastructure and projection qualification, not a benchmark score or a comparison
between the two backends.

## Frozen scope

- Variant: `v2-agent-eval-functional-ppa3-v1`.
- Tasks: `radix2_div`, `multi_pipe_8bit`, and `LIFObuffer`.
- Aggregate task-identity SHA-256:
  `f2477aee14579046161d73dd427b059f4502fc786f74bf15becbcebd065bfdaa`.
- Adapter/suite identity: `0.12.0` /
  `rtllm-41b2689-v2-agent-eval-functional-ppa3-v1`.
- Gym levels: L2 functional smoke, L3 candidate-only synthesis feedback, and L4
  correctness-gated candidate/reference final PPA.
- Result flags: `diagnostic_only=true`, `benchmark_score_claimed=false`.

`asyn_fifo` is intentionally excluded. It was the only hidden rejection in the remaining-38
campaign and all eight of its candidates were rejected in the earlier harder 32-run diagnostic,
despite public passes. PPA qualification would not repair that functional-specification gap.

## Qualification matrix

The no-pull runtime image was
`sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
All verifier and open-synthesis containers used `network=none`. Commercial synthesis used the
frozen host verifier control plane and disposable-worker release contract; it was not exposed to
an agent workspace.

| Check | Open | Commercial | Result |
| --- | ---: | ---: | --- |
| Resolved task-bound profiles | 3 | 3 | stable on repeated resolution |
| L3 candidate-only compile + PPA | 3 | 3 | passed |
| L4 candidate synthesis | 3 | 3 | passed |
| L4 reference synthesis | 3 | 3 | passed |
| L4 PPA eligibility | 3 | 3 | eligible |

All twelve L4 candidate/reference metric vectors contained mapped area, maximum-path delay, WNS,
and power with explicit `um^2`, `ns`, and `uW` units. The audit intentionally records presence,
units, and identity hashes rather than raw reports or metric values. Open and commercial profiles
remain separate comparison partitions; their values must not be pooled or ranked against one
another.

The variant's functional gate was also requalified: three references passed and twelve controls
were rejected by each of the public and hidden paths, for 15 public plus 15 hidden verdicts. No
model process ran. Private hidden/reference/artifact staging used the hardened cleanup helper;
its receipt recorded 45 directories, 53 files, complete cleanup, and zero residual paths. Runtime
cleanup was complete and no managed qualification container or commercial worker remained.

Two aborted zero-model development attempts are not counted as passing evidence. They failed the
first open L3 synthesis as an infrastructure error because a process-wide restrictive umask made
Docker tool staging unreadable to the non-root runtime user. Narrowing 0700/0600 enforcement to
the protected staging tree corrected the boundary. No model episode, retry, or benchmark result
was involved.

The sanitized external qualification summary has SHA-256
`136e734b574c74b0b71486164cc1a9357042119e67e3a6138988ebc691129a99`.
It contains no dataset path, reference source, hidden testbench, raw synthesis report, commercial
asset path, scheduler output, license value, or credential.

## Tool boundary

Design Compiler is the commercial PPA backend and passed all six L3/L4 checks. VCS is a functional
simulation/verifier backend, not a PPA backend, and was not part of this PPA qualification. The
full 50-task L2 variant remains deliberately PPA-disabled; only this separately identified
three-task variant advertises PPA support.
