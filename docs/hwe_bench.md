# HWE-Bench integration

`verigym-hwe-bench` maps selected official HWE-Bench PRs to the normal VeriGym repository-repair
and reporting path. This is a platform adapter, not a repackaged benchmark: the wheel contains no
dataset rows, repositories, golden patches, verifier scripts, or Docker layers.

## Current executable slice

Version 0.1 supports official Ibex per-PR images. Preparation requires explicit task IDs, validates
official base-FAIL/fix-PASS evidence, extracts the clean base tree, normalizes file modes for
deterministic patch freezing, and records the image manifest digest plus local image ID. It rejects
existing output and never discovers or pulls unrelated images.

```bash
verigym-hwe-bench prepare-source \
  --dataset /path/to/lowRISC__ibex.jsonl \
  --output /data/benchmarks/hwe-ibex-1735 \
  --task lowRISC/ibex:pr-1735 --pull
```

Omit `--pull` when the selected image is already local. A full-image download is intentionally not
available as a default workflow.

## Execution and security

The agent receives `TASK.md`, `PUBLIC_TESTS.md`, and `repository/`; the latter is the only editable
path. Golden fixes, test patches, and `tb_script` stay in the external prepared source. After the
candidate is frozen and replayed, a trusted suite hook runs the official script inside the exact
locked image with network disabled, all Linux capabilities dropped, `no-new-privileges`, CPU,
memory, PID, timeout, and output bounds. Raw hidden verifier output is hashed but not persisted.

```bash
verigym-hwe-bench smoke --source /data/benchmarks/hwe-ibex-1735 \
  --output /data/experiments/hwe-ibex-1735-smoke
```

The smoke performs a zero-model no-op run expected to fail, then the official reference expected
to pass. This is two verifier executions for one case, not a campaign. Trace export records general
file tools and the normalized `hwe_bench.simulate` result without hidden contents.

See the [zero-model qualification](audits/hwe_bench_ibex_1735_smoke.md) and the
[single-sample Codex audit](audits/hwe_bench_ibex_1735_codex_luna_max.md) for bounded evidence and
result hashes. Neither audit is a full benchmark campaign.

## Expansion path

Add repository profiles independently for CVA6, Caliptra, Rocket Chip, XiangShan, and OpenTitan.
Each profile declares its repository home, baseline marker, image availability, language/tool
requirements, and isolation limits. Commercial-tool images remain user-supplied and license-bound;
VeriGym stores only safe identities and evaluation summaries.
