# VeriGym HWE-Bench integration

This optional distribution maps explicitly selected, official HWE-Bench PRs to VeriGym
repository-repair tasks. It does not bundle the dataset, golden patches, testbench scripts, or
Docker images. Images are pulled one task at a time and locked by both manifest digest and local
image ID; there is no implicit bulk-download path.

The executable slice supports official Ibex, CVA6, and Rocket Chip per-PR images. Candidate
workspaces run
through the original hidden `tb_script` in a network-disabled, capability-dropped container. The
agent sees only the issue statement and clean base repository. Safe internal file symlinks are
materialized during preparation because agent workspaces are symlink-free. Golden patches and
verifier scripts remain in the external source and never enter prompts, traces, or agent
workspaces.

```bash
python -m pip install -e '.[dev]' -e integrations/verigym-hwe-bench
verigym-hwe-bench prepare-source \
  --dataset /path/to/lowRISC__ibex.jsonl \
  --output /path/to/hwe-source \
  --task lowRISC/ibex:pr-1735 \
  --official-dataset-revision 1403afb57ce056c659c82b35e39c38c6a21ee635
verigym-hwe-bench smoke \
  --source /path/to/hwe-source \
  --output /path/to/hwe-smoke
```

Add `--pull` only when the selected image is not already local. Preparation rejects an existing
output directory, unsupported repositories, mutable image mismatches, malformed F2P records,
profile/marker/license drift, and unbound runtime baselines. New preparation emits source-lock v2;
existing v1 prepared sources remain readable. CVA6 is declared `SHL-0.51`; Rocket Chip is
`Chisel/Scala` with the compound `BSD-3-Clause AND Apache-2.0` license inventory. Rocket preparation
also requires `--verifier-cache /path/to/coursier-cache`; only three profile-bound, hash-checked
public Maven files are copied into the source. Each verifier gets an independent Docker volume
initialized from the official image cache, receives those files, stays on `--network none`, and
removes the volume afterward. The smoke runs exactly one no-op probe (expected FAIL) and the
official reference candidate (expected PASS); it is not a full benchmark campaign.

Run that zero-model smoke on the same Docker daemon that will execute the campaign. A PASS from a
different host does not qualify a compute-node daemon. The verifier supplies Git's
`safe.directory` explicitly for the immutable in-image repository and emits only a bounded setup
stage when reset, checkout, marker validation, or patch application fails. Such a failure is
reported as infrastructure-invalid `sandbox_error`; only failures after the testbench-start
boundary are candidate test failures.
