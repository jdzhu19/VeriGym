# RTLLM full-corpus L1 qualification v1

Date: 2026-09-01

Status: passed. This is zero-model adapter and verifier qualification for the derived
`v2-agent-eval-all-v1` projection. It is not a native RTLLM score, a model campaign, public
functional coverage, or PPA qualification.

## Frozen scope

- Source commit: `41b26896e33b536940116a975626455eed3de65e`.
- Runnable task manifests: 50.
- Frozen source files: 207.
- Task-tree inventory hash:
  `ca6c86e761b14074e738b7ae90a6bc5f4ff02bcc7f2f7f51bb5c67fd3856814c`.
- Dataset-file inventory hash:
  `5877ebc9ab8dbf6aada22a981cd9e087423ea95ce15e527e9cac47122733edda`.
- Additional task-catalog hash:
  `d1ebca8ae4a8ad05082c8b2ce6f37509af4d0d8e08d08ab3b9c0b5def0c737c4`.

Every task has one repository-relative candidate RTL entry and repeated candidate-only compile
feedback. Hidden testbenches and auxiliary data remain verifier-only and are staged only after a
typed `finish`. The variant records `gym_qualification_level=L1_compile_only`,
`diagnostic_only=true`, `benchmark_score_claimed=false`, and disables PPA scoring and tools.

## Compatibility projections

Five final-verifier inputs use exact, hash-bound compatibility projections:

| Task | Projection |
| --- | --- |
| `radix2_div` | `edge-aligned-handshake-v1` |
| `ring_counter` | `iverilog12-unpacked-array-race-v1` |
| `asyn_fifo` | `icarus12-loop-control-v1` |
| `freq_divbyeven` | `candidate-module-normalization-v1` |
| `clkgenerator` | `pre-edge-clock-sampling-v1` |

These projections make a frozen upstream verifier usable with Icarus 12 by resolving a simulator
construct, scheduling ambiguity, or candidate-module naming conflict. They do not alter hidden
vectors, expected values, or pass/fail markers. Each transform is narrowly matched, and projected
output hashes are stored in the task catalog or manifest and checked before verifier execution.

## Qualification result

The opt-in qualification used
`verigym/open-rtl-tools:iverilog12-yosys067-opensta310`, resolved as
`sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`. The image reported
Icarus Verilog 12.0 stable (`4fd5291`). Each short-lived execution used the normal isolated Docker
runtime with networking disabled, a non-root user, a read-only root filesystem, dropped
capabilities, and bounded resources.

| Check | Cases | Result |
| --- | ---: | --- |
| Reference candidate-only public compile | 50 | passed |
| Reference hidden final verifier | 50 | passed |
| Missing-module hidden final verifier | 50 | rejected |
| Representative missing-module public compile | 1 | rejected |

The single from-scratch test completed in 1814.96 seconds with no retry. It made no model call and
used no VCS, Design Compiler, commercial license, network access, or PPA path. Raw hidden output,
reference RTL, testbench contents, auxiliary data, and transient qualification artifacts are not
included in this record.

## Interpretation

All 50 frozen RTLLM tasks are now runnable as L1 multi-turn Gym tasks: an agent can inspect and
patch its candidate repeatedly, rerun candidate-only compilation, and submit once for hidden final
verification. This result does not promote the remaining tasks to L2 independent public functional
smoke or L3/L4 PPA. Those levels still require separate per-task qualification and distinct
variant identities.
