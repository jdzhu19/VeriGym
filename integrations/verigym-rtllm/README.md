# VeriGym RTLLM Integration

This optional package exposes pinned RTLLM tasks through VeriGym without redistributing the
benchmark. A frozen manifest inventories all 50 task directories and 207 files at commit
`41b26896e33b536940116a975626455eed3de65e`; loading fails if the checkout tree or any qualified
task asset drifts. Runnable variants remain an explicit, separately qualified subset of that
inventory.

```bash
git clone https://github.com/hkust-zhiyao/RTLLM.git /path/to/RTLLM
git -C /path/to/RTLLM checkout 41b26896e33b536940116a975626455eed3de65e
python -m pip install -e ./integrations/verigym-rtllm
python -m pip install -e ./integrations/verigym-synopsys
verigym suites validate --suite rtllm --source /path/to/RTLLM --variant counter_12
verigym suites validate --suite rtllm --source /path/to/RTLLM --variant up_down_counter
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant up_down_counter_iverilog_training
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-all-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-verilator-public-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-harder-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-l2-batch1-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-l2-batch2-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-all-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-l2-diagnostic3-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-ppa3-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-all-v2
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-ppa47-v1
```

Each packaged workspace contains only a known-incomplete candidate skeleton and instructions. The
prompt, hidden VCS testbench, and normalized reference are loaded from the external checkout after
hash validation. Both chat and agent modes use the same verifier graph. A separate user-supplied
Design Compiler profile can enable hash-bound area/timing evaluation after correctness passes. New
commercial runs should select a task-bound `synopsys.vcs.mcp` verifier profile and an independent
`synopsys.dc.mcp` toolchain profile; neither commercial tool, license setup, hidden testbench, nor
PDK enters the model workspace.

`up_down_counter_iverilog_training` is an explicitly separate long-context sampling profile. It
keeps the 900-second task budget and checks candidates with the pinned Icarus 12 Docker image. Its
task metadata links back to `rtllm/up_down_counter`; its results must not be reported as VCS
benchmark scores.

`counter_12_agent_eval_v1` and `up_down_counter_agent_eval_v1` are separate multi-turn partitions.
They use verifier-only Icarus 12 for final functionality and public candidate-only compile
feedback. RTLLM alone may opt in to Yosys/OpenSTA ATP v2 feedback or to DC/MCP feedback backed by
a resolved disposable worker. Both use `--agent-ppa-feedback`; final-PPA-only DC profiles remain
ineligible for iteration. Final VCS/DC, Icarus/Open, and AgentEval results retain distinct
suite/profile identities.
The Icarus AgentEval variants fail closed unless the resolved `iverilog` and `vvp` identities are
major version 12. The opt-in qualification test checks the pinned image against reference and
known-bad candidates, so an unqualified image is not silently published under the AgentEval
identity.

`v2-agent-eval-all-v1` is the full-corpus L1 Gym projection. It discovers all 50 frozen RTLLM 2.0
tasks with IDs `rtllm/v2-agent-eval-all-v1/<task-name>`, materializes one intentionally incomplete
repository-relative RTL entry per task, and exposes repeatable candidate-only compilation. It does
not expose functional smoke or PPA feedback and records `gym_qualification_level=L1_compile_only`,
`diagnostic_only=true`, and `benchmark_score_claimed=false`. The original hidden functional
verifier inputs, with any declared hash-bound compatibility projection, are staged only after typed
`finish`.

`v2-agent-eval-verilator-public-v1` is a distinct 50-task L1 projection. Its repeatable public
action uses Verilator compile/lint instead of Icarus, while the one final hidden functional verdict
still uses isolated Icarus 12. PPA and functional public smoke remain disabled. The tool image,
observed Verilator version, fixed public command, and contract hash are recorded independently; a
lint pass is never presented as proof of functional correctness.

All prompt, reference, testbench, auxiliary-file, DUT/top, parser, and projection identities are
frozen in the metadata catalog. Verifier-only projections are exact and hash-bound. Most normalize
a conflicting upstream module name or remove a simulator scheduling ambiguity. The full L2 variant
also declares two judgeability guards for underconstrained upstream tests: `edge_detect` corrects
four conjunctions that otherwise accept a wrong single output, and `square_wave` requires at least
one observed high sample. Neither guard changes stimulus vectors or expected RTL values. The
opt-in Icarus 12
qualification requires every reference to pass public compile and hidden verification and requires
one missing-module candidate per task to be rejected by the hidden verifier. Full-corpus L1 is not
the same as L2 functional feedback: only separately qualified functional variants may expose a
repeatable public smoke. See the
[full-corpus L1 qualification record](../../docs/audits/rtllm_full_corpus_l1_qualification_v1.md).

`v2-agent-eval-functional-l2-batch1-v1` is the first evidence-selected L2 expansion. It contains
`adder_pipe_64bit`, `LFSR`, and `serial2parallel`, each with a hash-frozen independent public
functional smoke and four-category reference/known-bad qualification. It records
`gym_qualification_level=L2_functional_smoke`; PPA remains disabled, so this variant exposes only
functional iteration and a final hidden verdict. See the
[L2 batch-one qualification](../../docs/audits/rtllm_l2_batch1_qualification_v1.md).

`v2-agent-eval-functional-l2-batch2-v1` applies the same no-PPA L2 contract to
`sequence_detector`, `synchronizer`, and `RAM`. These were no-finish control outcomes in the L1
pilot, not hidden functional failures; batch two evaluates whether task-specific functional
feedback makes those tasks operable without reinterpreting the earlier result. Each task has a
separate hash-frozen public smoke and the same four-category reference/known-bad qualification
bar. See the
[L2 batch-two qualification](../../docs/audits/rtllm_l2_batch2_qualification_v1.md).

`v2-agent-eval-functional-all-v1` is the unified 50-task L2 Gym projection. It reuses the twelve
previously qualified functional assets and adds independent, hash-frozen public smokes and
candidate skeletons for the remaining 38 tasks. Every task exposes repeatable candidate-only
functional feedback and one final verifier-only hidden verdict. The variant records
`gym_qualification_level=L2_functional_smoke`, `diagnostic_only=true`, and
`benchmark_score_claimed=false`; PPA is disabled. Qualification requires every upstream reference
to pass and four independently authored controls per task to be rejected by both public and hidden
paths. See the
[full L2 qualification](../../docs/audits/rtllm_full_corpus_l2_qualification_v1.md).

`v2-agent-eval-functional-l2-diagnostic3-v1` is a corrected diagnostic projection for
`div_16bit`, `LFSR`, and `freq_divbyodd`. It keeps PPA disabled and freezes more informative public
smokes; notably, the LFSR reset check now follows the prompt's rising-edge semantics. See the
[diagnostic-three qualification](../../docs/audits/rtllm_l2_diagnostic3_qualification_v1.md).

`v2-agent-eval-functional-ppa3-v1` is the separate PPA-enabled projection for `radix2_div`,
`multi_pipe_8bit`, and `LIFObuffer`. It advertises L2 functional, L3 candidate-feedback, and L4
correctness-gated final-PPA qualification only with task-bound resolved profiles. Yosys/OpenSTA
and Design Compiler/MCP are distinct, non-comparable partitions. `asyn_fifo` is excluded pending
resolution of its repeated public/hidden functional gap. See the
[dual-backend PPA qualification](../../docs/audits/rtllm_ppa3_dual_backend_qualification_v1.md).

`v2-agent-eval-functional-all-v2` keeps the 50-task, multi-turn L2 surface while freezing a
12-control public-spec mutation contract per task. Public and hidden qualification use different
partition IDs and seeds. The catalog identity and a separate 600-source digest map bind the
obligation metadata and the actual compile-shaped controls independently. The asynchronous FIFO
uses an independent queue scoreboard with bounded CDC visibility instead of the upstream
cycle-exact trace comparison. Its verifier-only checker is site supplied through
`VERIGYM_RTLLM_FIFO_BEHAVIOR_CHECKER_V2`; the checker hash is public, but its bytes and path are
never added to a task workspace or repository. PPA remains disabled for this 50-task variant.

`v2-agent-eval-functional-ppa47-v1` is a separate PPA-enabled projection of the 47 references with
valid synthesis models. It binds every task to one top, source, SDC, clock mode, and power-base
clock. Single-clock tasks use 10 ns, `asyn_fifo` uses 10 ns `wclk` and 14 ns `rclk` with
asynchronous groups, and combinational tasks use a 10 ns virtual clock with frozen 1 ns I/O delays.
`float_multi`, `synchronizer`, and `clkgenerator` remain in the 50-task L2 variant but are excluded
from PPA47 with stable reason codes. OpenSTA and DC/MCP remain separate non-comparable profile
partitions. The `sequence_detector` and `ROM` bindings apply explicit, hash-checked, PPA-only
synthesis normalizations; the upstream goldens, L2 task identities, and candidate source paths are
unchanged. See the [feedback-v2 mutation audit](../../docs/audits/rtllm_feedback_v2_mutation_matrix.md),
[FIFO contract audit](../../docs/audits/rtllm_asyn_fifo_behavior_contract_v2.md), and
[PPA47 qualification audit](../../docs/audits/rtllm_ppa47_dual_backend_qualification_v1.md).

`v2-agent-eval-functional-harder-v1` is a derived, diagnostic-only four-task partition containing
`radix2_div`, `multi_pipe_8bit`, `LIFObuffer`, and `asyn_fifo`. Task IDs have the form
`rtllm/v2-agent-eval-functional-harder-v1/<task-name>`. Each task has one repository-relative RTL
entry and an independent public candidate-only functional smoke. The public smoke is not copied
from the upstream hidden test and may be rerun during an episode. The hidden functional verifier
runs only after one typed `finish`; hidden auxiliary files are mounted only in the final verifier
workspace. In particular, `asyn_fifo` keeps `wfull.txt`, `rempty.txt`, and `tdata.txt` out of the
model workspace and persisted trajectory.

The final-submission requirement is enforced by both live execution and verifier-enabled replay.
If an episode ends without typed `finish`, the verifier DAG contains only skipped placeholders and
no hidden asset is staged or executed.

The manifest retains the exact upstream prompt and hash, and appends a separately identified
projection note. The asynchronous FIFO projection fixes `WIDTH=8` and `DEPTH=16`, permits its RAM
submodule in the same candidate file, and derives pointer widths from `DEPTH`. Two deterministic
hidden-testbench compatibility projections are hash-bound: divider stimulus is edge-aligned for
the frozen handshake contract, and the asynchronous FIFO's unsupported Icarus 12 loop `break` is
rewritten as an equivalent named-block exit. Neither projection changes hidden vectors, expected
outputs, or pass/fail logic. The original upstream bytes and their hashes remain in the frozen
source manifest.

Results from this harder partition must carry `diagnostic_only=true` and
`benchmark_score_claimed=false`; they are not native RTLLM leaderboard scores.

RTLLM is MIT-licensed. Synopsys tools and licenses are neither included nor required by ordinary
VeriGym CI; commercial execution is site-local and opt-in.

The supported functional-version matrix is intentionally partitioned:

- original commercial RTLLM uses the exact VCS version frozen by its verifier profile;
- `counter_12_agent_eval_v1` and `up_down_counter_agent_eval_v1` require `iverilog` and `vvp`
  major version 12;
- `v2-agent-eval-all-v1` requires the same Icarus 12 identity and provides compile-only L1 Gym
  feedback for all 50 frozen tasks;
- `v2-agent-eval-verilator-public-v1` additionally requires Verilator and replaces only the public
  compile/lint action; final functionality remains on Icarus 12 and PPA stays disabled;
- `v2-agent-eval-functional-l2-batch1-v1` requires Icarus 12, provides public L2 functional
  feedback for three tasks, and explicitly disables PPA;
- `v2-agent-eval-functional-l2-batch2-v1` requires Icarus 12, provides public L2 functional
  feedback for three additional tasks, and explicitly disables PPA;
- `v2-agent-eval-functional-all-v1` requires Icarus 12, provides public L2 functional feedback
  for all 50 frozen tasks, and explicitly disables PPA;
- `v2-agent-eval-functional-ppa3-v1` requires Icarus 12 and a separately resolved task-bound
  OpenSTA or DC profile, and enables PPA only for its three qualified tasks;
- `v2-agent-eval-functional-all-v2` requires Icarus 12 and an external hash-matched FIFO checker,
  provides 50-task L2 feedback with 12 mutation controls per task, and disables PPA;
- `v2-agent-eval-functional-ppa47-v1` uses the same functional contract and enables PPA only for
  the 47 explicitly eligible task bindings;
- Icarus 13 can remain installed for development but is not accepted for these AgentEval results.

See [verifier backend profiles](../../docs/verifier_profiles.md) for configuration and
[the phase-one qualification](../../docs/audits/rtl_commercial_mcp_qualification_v1.md) and
[the phase-two worker qualification](../../docs/audits/rtl_agent_dc_worker_qualification_v2.md)
for bounded reference/known-bad evidence. The
[32-run harder diagnostic](../../docs/audits/rtllm_harder_multiturn_codex_32_diagnostic_v1.md)
records the new partition's frozen campaign and its post-run integrity finding. The
[12-task full-corpus L1 pilot](../../docs/audits/rtllm_full_l1_codex_12task_pilot_v1.md) records a
separate compile-only Codex diagnostic and the evidence used to select the next L2 batch. The
[three-task L2 diagnostic](../../docs/audits/rtllm_l2_batch1_codex_3_diagnostic_v1.md) then records
three visible fail -> repair -> pass sequences and two hidden resolutions under the PPA-disabled
L2 variant. These checks qualify bounded infrastructure or projections; they are not benchmark
scores.

The [remaining-38 diagnostic](../../docs/audits/rtllm_full_l2_remaining38_codex_diagnostic_v1.md)
completes one bounded full-L2 observation for the rest of the corpus: 37/38 resolved with seven
visible repair sequences, zero retries, and one asynchronous-FIFO hidden rejection.
