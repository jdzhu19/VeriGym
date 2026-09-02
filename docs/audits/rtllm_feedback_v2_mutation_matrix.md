# RTLLM full-corpus feedback-v2 mutation audit

Date: 2026-09-03

Variant: `v2-agent-eval-functional-all-v2`

This diagnostic qualification made zero model calls and did not replay or amend an episode.
Public and hidden checks used independent partition IDs and seeds (`0x50554232` and `0x48494432`).
Hidden assets were staged only inside an external verifier qualification workspace and were never
added to the repository or a candidate workspace.

The catalog hash is
`b4576feb8e980bcbd7aad7517e88b37ac07afc18ef73557b9ce38530da46f69d`.
The independent 600-source mutant digest-map hash is
`1356493bd8609fbd4f9998b48500646a184ae1a194787a984767dfe25551b29c`.
Each task records its applicable nominal, reset/initial, boundary, enable/handshake, latency,
ordering, width/sign, overflow/wrap, and state-transition obligations. Each task has exactly 12
compile-shaped controls: the four independently authored historical categories and eight
separately identified, task-keyed interface mutations. The additional controls preserve a known
specification error and add a distinct observable output perturbation; clocked perturbations vary
during the checker window, while the single-output square-wave controls use distinct valid input
activation values. The public and hidden path both had to accept the reference and reject all 12
controls.

| Task | Reference public/hidden | Public mutants killed | Hidden mutants killed |
| --- | ---: | ---: | ---: |
| `accu` | 2/2 | 12/12 | 12/12 |
| `adder_16bit` | 2/2 | 12/12 | 12/12 |
| `adder_32bit` | 2/2 | 12/12 | 12/12 |
| `adder_8bit` | 2/2 | 12/12 | 12/12 |
| `adder_bcd` | 2/2 | 12/12 | 12/12 |
| `adder_pipe_64bit` | 2/2 | 12/12 | 12/12 |
| `comparator_3bit` | 2/2 | 12/12 | 12/12 |
| `comparator_4bit` | 2/2 | 12/12 | 12/12 |
| `div_16bit` | 2/2 | 12/12 | 12/12 |
| `radix2_div` | 2/2 | 12/12 | 12/12 |
| `multi_16bit` | 2/2 | 12/12 | 12/12 |
| `multi_8bit` | 2/2 | 12/12 | 12/12 |
| `multi_booth_8bit` | 2/2 | 12/12 | 12/12 |
| `multi_pipe_4bit` | 2/2 | 12/12 | 12/12 |
| `multi_pipe_8bit` | 2/2 | 12/12 | 12/12 |
| `fixed_point_adder` | 2/2 | 12/12 | 12/12 |
| `fixed_point_substractor` | 2/2 | 12/12 | 12/12 |
| `float_multi` | 2/2 | 12/12 | 12/12 |
| `sub_64bit` | 2/2 | 12/12 | 12/12 |
| `JC_counter` | 2/2 | 12/12 | 12/12 |
| `counter_12` | 2/2 | 12/12 | 12/12 |
| `ring_counter` | 2/2 | 12/12 | 12/12 |
| `up_down_counter` | 2/2 | 12/12 | 12/12 |
| `fsm` | 2/2 | 12/12 | 12/12 |
| `sequence_detector` | 2/2 | 12/12 | 12/12 |
| `asyn_fifo` | 2/2 | 12/12 | 12/12 |
| `LIFObuffer` | 2/2 | 12/12 | 12/12 |
| `LFSR` | 2/2 | 12/12 | 12/12 |
| `barrel_shifter` | 2/2 | 12/12 | 12/12 |
| `right_shifter` | 2/2 | 12/12 | 12/12 |
| `freq_div` | 2/2 | 12/12 | 12/12 |
| `freq_divbyeven` | 2/2 | 12/12 | 12/12 |
| `freq_divbyfrac` | 2/2 | 12/12 | 12/12 |
| `freq_divbyodd` | 2/2 | 12/12 | 12/12 |
| `calendar` | 2/2 | 12/12 | 12/12 |
| `edge_detect` | 2/2 | 12/12 | 12/12 |
| `parallel2serial` | 2/2 | 12/12 | 12/12 |
| `pulse_detect` | 2/2 | 12/12 | 12/12 |
| `serial2parallel` | 2/2 | 12/12 | 12/12 |
| `synchronizer` | 2/2 | 12/12 | 12/12 |
| `traffic_light` | 2/2 | 12/12 | 12/12 |
| `width_8to16` | 2/2 | 12/12 | 12/12 |
| `RAM` | 2/2 | 12/12 | 12/12 |
| `ROM` | 2/2 | 12/12 | 12/12 |
| `alu` | 2/2 | 12/12 | 12/12 |
| `clkgenerator` | 2/2 | 12/12 | 12/12 |
| `instr_reg` | 2/2 | 12/12 | 12/12 |
| `pe` | 2/2 | 12/12 | 12/12 |
| `signal_generator` | 2/2 | 12/12 | 12/12 |
| `square_wave` | 2/2 | 12/12 | 12/12 |

Totals: 50 public reference acceptances, 50 hidden reference acceptances, 600 public mutant
rejections, and 600 hidden mutant rejections: exactly 1,300 expected functional verdicts. All 50
tasks remain `diagnostic_only=true`, `benchmark_score_claimed=false`, and PPA-disabled in this
variant. Finite mutation testing measures the frozen contract; it is not a proof of exhaustive
functional correctness.

The current source digest map was qualified with host Icarus Verilog 12.0 stable (`v12_0`) using
the same bounded batch runner as the opt-in Docker test. A no-pull replay in the already frozen
image
`sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`
was also attempted after source hardening, but the Docker daemon could not create a container
because the host root filesystem had no free space. That attempt produced no functional verdict
and is classified as an infrastructure failure, not a verifier rejection; exact container-identity
replay of the final source map remains pending.

The sanitized external qualification summary has SHA-256
`36adad008b512d01599754118d04977cf688dbd5a3b2ff0cd5582101d615b7cf`. It records only identities,
aggregate verdict counts, the stable infrastructure reason code, and cleanup status; it contains
no source text, hidden vectors, verifier path, credential, or full trajectory.
