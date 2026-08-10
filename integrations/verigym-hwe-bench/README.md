# VeriGym HWE-Bench integration

This optional distribution maps explicitly selected, official HWE-Bench PRs to VeriGym
repository-repair tasks. It does not bundle the dataset, golden patches, testbench scripts, or
Docker images. Images are pulled one task at a time and locked by both manifest digest and local
image ID; there is no implicit bulk-download path.

The executable slice supports the official Ibex and CVA6 per-PR images. Candidate workspaces run
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
  --task lowRISC/ibex:pr-1735
verigym-hwe-bench smoke \
  --source /path/to/hwe-source \
  --output /path/to/hwe-smoke
```

Add `--pull` only when the selected image is not already local. Preparation rejects an existing
output directory, unsupported repositories, mutable image mismatches, malformed F2P records, and
unbound runtime baselines. The smoke runs exactly one no-op probe (expected FAIL) and the official
reference candidate (expected PASS); it is not a full benchmark campaign.
