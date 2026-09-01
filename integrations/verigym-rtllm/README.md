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
  --variant v2-agent-eval-functional-harder-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-l2-batch1-v1
verigym suites validate --suite rtllm --source /path/to/RTLLM \
  --variant v2-agent-eval-functional-l2-batch2-v1
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

All prompt, reference, testbench, auxiliary-file, DUT/top, parser, and projection identities are
frozen in the metadata catalog. Verifier-only compatibility projections are exact and hash-bound;
they may normalize a conflicting upstream module name or remove a simulator scheduling ambiguity,
but never change hidden vectors, expected values, or pass/fail conditions. The opt-in Icarus 12
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
- `v2-agent-eval-functional-l2-batch1-v1` requires Icarus 12, provides public L2 functional
  feedback for three tasks, and explicitly disables PPA;
- `v2-agent-eval-functional-l2-batch2-v1` requires Icarus 12, provides public L2 functional
  feedback for three additional tasks, and explicitly disables PPA;
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
