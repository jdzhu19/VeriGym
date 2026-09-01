# VerilogEval V2 adapter and pass@k

VeriGym’s `verilog-eval` suite adapter normalizes an externally supplied VerilogEval V2
specification-to-RTL task into the same `VeriTask`, ChatEval, verifier DAG, trace, replay, and
scorecard contracts used by the toy RTL slice. VeriGym never searches for, clones, downloads,
caches, or packages the benchmark.

## Supported source and variant

Supply either the root of a local checkout containing `dataset_spec-to-rtl/` or that dataset
directory directly. Milestone 6 supports only `v2-spec-to-rtl`, whose tasks are complete triplets:

```text
dataset_spec-to-rtl/
  <native-id>_prompt.txt
  <native-id>_ref.sv
  <native-id>_test.sv
```

The full common stem is the native ID. Discovery uses deterministic natural ordering. Legacy V1,
V2 MachineEval, and V2 code-completion are not supported. An ambiguous repository root requires
an explicit variant.

Validate without changing the source, then list normalized tasks:

```bash
verigym suites validate \
  --suite verilog-eval \
  --source /path/to/verilog-eval \
  --variant v2-spec-to-rtl

verigym tasks list \
  --suite verilog-eval \
  --source /path/to/verilog-eval \
  --variant v2-spec-to-rtl
```

Validation checks complete triplets, UTF-8 and nonempty prompts, file size bounds, case collisions,
readability, symlink/path escapes, and the expected `TopModule`, `RefModule`, testbench-top, and
native mismatch-summary conventions. Source discovery, validation, execution, and replay do not
contact the network.

## One-task ChatEval

The separate `v2-spec-to-rtl-agent-eval-v1` variant provides multi-turn file actions and a public,
candidate-only Icarus compile check. Its hidden golden/testbench mismatch regression is unchanged,
PPA is always disabled, and its results are not included in native ChatEval pass@k. See
[RTL AgentEval v1](rtl_agent_eval.md).

Because every V2 task uses the same prompt/reference/testbench triplet and `TopModule` contract,
this compile-only L1 projection discovers the full validated corpus without per-task adapter
branches. Functional AgentEval variants remain a separately qualified subset with frozen,
independently authored public smokes. Full-corpus discovery therefore means L1 Gym coverage, not
full-corpus public functional feedback. VerilogEval does not gain PPA eligibility through either
projection.

The normalized candidate contract is one complete `rtl/TopModule.sv`. Raw RTL and exactly one
fenced Verilog/SystemVerilog block are accepted by the existing single-turn parser.

```bash
verigym run \
  --suite verilog-eval \
  --suite-source /path/to/verilog-eval \
  --suite-variant v2-spec-to-rtl \
  --task Prob001_zero \
  --mode chat \
  --agent single-turn \
  --model openai-compatible \
  --model-base-url https://models.example.test/v1 \
  --model-id example-model \
  --model-api-key-env VERIGYM_MODEL_TOKEN \
  --temperature 0.2 \
  --top-p 0.95 \
  --runtime local \
  --output runs/
```

The source path and source hashes are recorded in the user-facing manifest but never enter model
messages or observations. Each ordinary run retains the standard layout:

```text
<run-id>/
  run_manifest.json
  task_snapshot.json
  trace.jsonl
  scorecard.json
  workspace_diff.patch
  candidate/
  logs/
  artifacts/
```

Replay validates frozen artifacts without calling the model. `--verify` reruns only the verifier:

```bash
verigym replay runs/<run-id>
verigym replay runs/<run-id> --verify
```

## Benchmark-faithful verification

The agent workspace contains only public guidance and `rtl/TopModule.sv`. For verification,
VeriGym copies only the selected task’s golden and testbench contents into a separate verifier
session under neutral local names. They are never copied into the candidate snapshot or exposed to
the model. Compilation uses SystemVerilog 2012, selects the recognized testbench top, and places
the candidate last:

```text
iverilog -Wall -Winfloop -Wno-timescale -g2012 -s tb -o simv \
  verifier/golden.sv verifier/testbench.sv rtl/TopModule.sv
```

Simulation runs with `vvp`. A pass requires a successful launch and the final native line
`Mismatches: 0 in <positive integer> samples`, with no native or process timeout. A nonzero
mismatch, candidate compile failure, missing `TopModule`, reserved-module collision, or
candidate-caused timeout is an incorrect candidate. Missing tools, process-launch faults,
corrupted source, and internal parser/runtime faults are infrastructure errors.

Tool metadata additionally carries stable diagnostic subtypes such as `compile.syntax_error`,
`compile.unknown_module`, `simulation.native_timeout`, and `verification.mismatch`. These bounded
labels support aggregate analysis without making raw compiler wording part of the result contract.

The manifest, scorecard, and verifier artifacts record exact detected Icarus versions and one of:

- `canonical_or_reference_compatible` for the upstream reference major version 12;
- `unverified_tool_version` for other versions without a known compatibility determination;
- `incompatible_tool_version` for major version 13, which upstream reports as incompatible.

Nonreference tools may be used for development, but their reports do not claim exact upstream
comparability. PPA and synthesis fields remain `null`.

The host may keep Icarus 13 side by side, but reference-compatible execution must resolve Icarus
and vvp 12. VerilogEval does not accept VCS/DC verifier or PPA profiles; commercial RTLLM profiles
are a separate partition. See [verifier backend profiles](verifier_profiles.md).

With `--runtime docker`, tool discovery and compatibility come from the immutable resolved image,
not host `iverilog` or `vvp`. Native simulation runs beside the compiled artifact in the verifier's
writable internal build directory so upstream testbenches can emit temporary VCD files without
making candidate or golden/testbench sources writable. The external checkout itself is never
mounted into a container. See [DockerRuntime](docker_runtime.md) for image, isolation, replay, and
opt-in conformance-test details.

## Independent samples and canonical pass@k

Milestone 6 can run N sequential, independent ChatEval samples of one task. Every child receives a
fresh model-client clone, agent workspace, verifier workspace, run ID, trace, sample index, and
derived seed. It remains an ordinary independently replayable run.

```bash
verigym run \
  --suite verilog-eval \
  --suite-source /path/to/verilog-eval \
  --suite-variant v2-spec-to-rtl \
  --task Prob001_zero \
  --mode chat \
  --agent single-turn \
  --model openai-compatible \
  --temperature 0.8 \
  --top-p 0.95 \
  --samples 20 \
  --pass-k 1 \
  --pass-k 5 \
  --runtime local \
  --output runs/
```

The aggregate layout is:

```text
<sample-group>/
  sample_set_manifest.json
  pass_at_k.json
  samples/
    0000/<ordinary run-id>/...
    0001/<ordinary run-id>/...
```

For `n` samples and `c` correct candidates, VeriGym uses the exact-combination unbiased estimator:

```text
pass@k = 1 - C(n-c, k) / C(n, k)
```

A canonical value is available only when every requested sample has a candidate-level verdict,
all children have the same task/source, model fingerprint, agent, prompt policy, generation
settings, runtime, verifier/toolchain profile, and budget, no infrastructure result is present,
and `n >= k`. Malformed model output is a valid incorrect sample. Model transport failure,
missing Icarus, runtime failure, cancellation, truncation, mixed configuration, or a missing child
invalidates canonical pass@k instead of being counted as incorrect RTL.

The same report records the number of distinct candidate snapshots and their Gini-Simpson
diversity, `1 - sum((count(hash) / n)^2)`. Candidate identity comes from the immutable snapshot
SHA-256 rather than log text. Diversity is `null` with a reason when a child or candidate hash is
missing or the group mixes configurations; it does not affect pass@k or correctness.

Aggregate regeneration reads only completed child manifests, scorecards, and traces and never
calls the model:

```python
from pathlib import Path
from verigym.core.sampling import regenerate_sample_report

regenerate_sample_report(Path("runs/<sample-group>"))
```

## Provenance, citation, and security boundary

Manifests record the adapter/suite versions, variant and native layout, deterministic dataset and
per-task hashes, positively identified local license, and best-effort local Git commit and sanitized
remote metadata. Git metadata collection does not resolve or contact the remote. Cite the upstream
benchmark and honor the license from the exact supplied checkout when publishing results.

Do not claim reproduction of an official published score unless the source revision, prompt
variant, sampling settings, model configuration, Icarus version, and all recorded compatibility
fields match the claimed setup.

Standard tests use only the independently authored fixture under
`tests/fixtures/verilog_eval_v2_synthetic/`, marked “Synthetic layout-conformance fixture; not an
official benchmark task.” No official task data is bundled, and normal tests require neither an API
key nor network access.

`LocalRuntime` remains `local_trusted`: verifier separation prevents accidental model-visible
leakage but is not an untrusted-code security boundary. Docker or other adversarial isolation,
Yosys/PPA, broader adapters, general batch scheduling, external agent frameworks, and RL are
deferred.
