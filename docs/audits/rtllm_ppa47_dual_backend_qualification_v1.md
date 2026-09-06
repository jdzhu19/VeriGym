# RTLLM PPA47 dual-backend qualification v1

Completed: 2026-09-03 (qualification began 2026-09-02)

Status: passed. The 47 RTLLM references with valid synthesis models are qualified under the
separate `v2-agent-eval-functional-ppa47-v1` variant for both the open Yosys/OpenSTA partition and
the commercial Synopsys Design Compiler/MCP partition. This was a zero-model infrastructure and
projection qualification. It is diagnostic only, makes no benchmark-score claim, and does not
compare absolute values between the two backends.

## Frozen scope

- PPA task-binding aggregate SHA-256:
  `7ce5dc1bbfc01fe0de19ed64f895da705830ced601789ded2054f3e59bd486ae`.
- PPA47 task-identity aggregate SHA-256:
  `e999360992f388cea2e43b0b8dc54087c11341c97e974d05c9262e44a087fb10`.
- Runtime image identity:
  `sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
- Result flags: `diagnostic_only=true`, `benchmark_score_claimed=false`, and `model_calls=0`.
- Clock modes: 32 single-clock tasks at 10 ns, one asynchronous FIFO with 10 ns `wclk` and
  14 ns `rclk`, and 14 combinational tasks with a 10 ns virtual clock and frozen 1 ns I/O delays.
- The asynchronous FIFO SDC declares the two clocks asynchronous and uses `wclk` as the frozen
  vectorless-power base clock.

Three tasks remain in the 50-task functional variant but are intentionally absent from PPA47:

| Task | Stable exclusion reason |
| --- | --- |
| `float_multi` | `reference_non_synthesizable_event_control` |
| `synchronizer` | `reference_multiple_edge_drivers` |
| `clkgenerator` | `reference_zero_cell_delay_model` |

The PPA47-only reference projection contains two explicit, hash-checked synthesis normalizations.
Neither changes the external golden repository, any L2 variant, historical task identity, or
candidate source path:

| Task | Normalization | Normalized reference SHA-256 | Reason |
| --- | --- | --- | --- |
| `sequence_detector` | `dc_ver134_combinational_blocking_assignment_v1` | `da9720d113e7b248230569f6e707273e99d16645645b55e83d2276f2a8554ffd` | Make the combinational default assignment consistently blocking; DC otherwise reports `VER-134`. |
| `ROM` | `dc_ver281_fixed_rom_case_v1` | `484b9dcd649a2aac9c8a5801fc3c6f52af066b07c3aab3e5767f3b914a817d02` | Express the four fixed public ROM words as a synthesizable combinational case; DC otherwise ignores the `initial` writes under `VER-281`. |

## Qualification matrix

The final v8 run resolved 47 task-bound profiles in each backend partition. Every profile executed
one L3 reference-as-candidate synthesis job and two L4 candidate/reference synthesis jobs.

| Check | Open | Commercial | Total | Result |
| --- | ---: | ---: | ---: | --- |
| Resolved task-bound profiles | 47 | 47 | 94 | v8 identity-bound |
| L3 candidate-only synthesis | 47 | 47 | 94 | passed |
| L4 candidate synthesis | 47 | 47 | 94 | passed |
| L4 reference synthesis | 47 | 47 | 94 | passed |
| Real synthesis jobs | 141 | 141 | 282 | passed, zero automatic retries |
| Functional-rejection PPA skips | 47 | 47 | 94 | passed without synthesis |

The functional gate was rerun for the PPA47 projection before synthesis: 47 references and 564
mutation controls produced 611 public plus 611 hidden verdicts, all as expected. Public and hidden
use separate frozen vector partitions. No model process ran and no historical episode was replayed
or amended. A later feedback-v2-only source-hardening pass changed mutant source bytes without
changing the catalog, references, PPA bindings, task identities, profiles, or synthesis inputs; its
current 50-task matrix is recorded separately in the feedback-v2 mutation audit and does not alter
the completed 282 synthesis jobs below.

For every L3 and L4 synthesis result, mapped cell count was nonzero; mapped area, maximum-path
delay, and power were positive and finite; WNS was finite; and units were explicitly `um^2`, `ns`,
and `uW`. OpenSTA and Design Compiler remain different profile partitions and their absolute values
must not be pooled or ranked against each other. The audit records metric presence, units, and
identity hashes rather than raw values or reports.

Private qualification staging reported complete cleanup and zero residual paths. Runtime cleanup
was complete, and the sanitized result contains no dataset path, source text, hidden checker,
commercial asset path, scheduler output, license value, credential, or raw PPA value. Its SHA-256
is `5f8372f054f784ca9025a35e5b4c632c4d42a0f7a8ca02c7f837d316d16e6aff`.

## Diagnostic history

Earlier v1 through v7 identities remain immutable diagnostic artifacts and are not counted in the
passing 282-job result. Their fail-fast runs successively exposed canonical profile drift, a
commercial-worker profile allowlist gap, an OpenSTA structural-netlist parser incompatibility,
missing latch-cell mapping for `fsm`, DC `VER-134` on `sequence_detector`, and DC `VER-281` on
`ROM`. Each correction received a new profile or task identity; no failed job was automatically
retried inside a frozen run.

The v6 `sequence_detector` one-job diagnosis and v7 three-job preflight established the exact
assignment issue and its repair. After v7 stopped at `ROM-commercial`, a local DC front-end check
identified ignored initialization, the v8 ROM commercial preflight passed three jobs, and the five
not-yet-reached tail tasks passed 15 additional diagnostic jobs. These diagnostics are not part of
the final count. The final v8 qualification then started from the first task and completed all 282
jobs under one identity without retries.

The open flow uses `verigym-yosys-opensta-atp-v4`, including parser-compatible structural netlist
export and explicit latch mapping. Commercial execution used the fixed MCP control plane and
disposable-worker release contract. Site profiles, tool paths, PDK/commercial assets, and complete
trajectories remain outside the repository.
