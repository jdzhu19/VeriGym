# HWE-Bench integration

`verigym-hwe-bench` maps selected official HWE-Bench PRs to the normal VeriGym repository-repair
and reporting path. This is a platform adapter, not a repackaged benchmark: the wheel contains no
dataset rows, repositories, golden patches, verifier scripts, or Docker layers.

## Current executable slice

Version 0.1 supports official Ibex, CVA6, and Rocket Chip per-PR images. Preparation requires
explicit task IDs,
validates official base-FAIL/fix-PASS evidence, extracts the clean base tree, normalizes file modes
for deterministic patch freezing, and records the image manifest digest plus local image ID. Safe
internal file symlinks are materialized; escaping and special-file links are rejected. If image
preparation creates a synthetic Git baseline, its marker must remain bound to the official base
through the image provenance file. Preparation rejects existing output and never discovers or
pulls unrelated images. New sources use `verigym_hwe_bench_source_v2`; the loader retains v1
compatibility and task IDs, but newly prepared CVA6 records correctly declare `SHL-0.51`.

| Repository | Runtime home | Base marker | Language | Offline additions |
| --- | --- | --- | --- | --- |
| Ibex | `/home/ibex` | `/home/ibex_base_commit.txt` | SystemVerilog | none |
| CVA6 | `/home/cva6` | `/home/cva6_base_commit.txt` | SystemVerilog | none |
| Rocket Chip | `/home/rocket-chip` | `/home/base_commit.txt` | Chisel/Scala | 3 locked Maven files |

Every source-lock v2 entry binds the repository profile hash, explicit marker, complete declared
license inventory, image identities, base repository, reference candidate, and verifier payload.
Official per-PR images may expose a runtime marker that differs from the upstream PR base. The
profile makes this digest-locked-marker policy explicit; the lock binds both commits, and
preparation still requires the official reference patch to apply to the extracted runtime tree.
Rocket Chip's official image lacks a complete offline SBT compiler-bridge dependency closure.
Preparation therefore requires an explicit `--verifier-cache` and copies only the three public
files named and hashed by the repository profile. It never downloads them implicitly.

```bash
verigym-hwe-bench prepare-source \
  --dataset /path/to/lowRISC__ibex.jsonl \
  --output /data/jzhu484/Agent/datasets/hwe-ibex-1735 \
  --task lowRISC/ibex:pr-1735 \
  --official-dataset-revision 1403afb57ce056c659c82b35e39c38c6a21ee635 --pull
```

Omit `--pull` when the selected image is already local. A full-image download is intentionally not
available as a default workflow.

CVA6 uses the same command with its repository-specific dataset and task ID:

```bash
verigym-hwe-bench prepare-source \
  --dataset /path/to/openhwgroup__cva6.jsonl \
  --output /data/jzhu484/Agent/datasets/hwe-cva6-2170 \
  --task openhwgroup/cva6:pr-2170
```

Rocket Chip additionally supplies the already-prewarmed Coursier cache:

```bash
verigym-hwe-bench prepare-source \
  --dataset /path/to/chipsalliance__rocket-chip.jsonl \
  --output /data/jzhu484/Agent/datasets/hwe-rocket-3065 \
  --task chipsalliance/rocket-chip:pr-3065 \
  --verifier-cache /data/jzhu484/Agent/.verigym-tmp/rocket-coursier-cache
```

## Execution and security

The agent receives `TASK.md`, `PUBLIC_TESTS.md`, and `repository/`; the latter is the only editable
path. Golden fixes, test patches, and `tb_script` stay in the external prepared source. After the
candidate is frozen and replayed, a trusted suite hook runs the official script inside the exact
locked image with network disabled, all Linux capabilities dropped, `no-new-privileges`, CPU,
memory, PID, timeout, and output bounds. Raw hidden verifier output is hashed but not persisted.
When a profile has offline additions, the verifier creates a unique Docker volume, lets Docker
initialize it from the official image's cache, injects the hash-checked additions, and removes the
volume after that one execution. Writable build caches are never shared across candidates.

```bash
verigym-hwe-bench smoke --source /data/jzhu484/Agent/datasets/hwe-ibex-1735 \
  --output /data/jzhu484/Agent/experiments/hwe-ibex-1735-smoke
```

The smoke performs a zero-model no-op run expected to fail, then the official reference expected
to pass. This is two verifier executions for one case, not a campaign. Trace export records general
file tools and the normalized `hwe_bench.simulate` result without hidden contents.

See the [zero-model qualification](audits/hwe_bench_ibex_1735_smoke.md) and the
[single-sample Codex audit](audits/hwe_bench_ibex_1735_codex_luna_max.md) for bounded evidence and
result hashes. The [three-task pilot](audits/hwe_bench_3task_codex_luna_max.md) adds Ibex PR167 and
CVA6 PR2170, multi-source campaign execution, and three sealed trajectories. These are bounded
platform pilots, not full-benchmark or model-quality claims.

The first [repo-level held-out v1 qualification gate](audits/hwe_repo_heldout_v1_qualification.md)
reproduced base-FAIL/reference-PASS for Ibex PR222, CVA6 PR2945, and Rocket PR3065 with zero model
calls. An initial Rocket failure was traced to the official image's incomplete offline dependency
cache; the profile-bound isolated-volume path resolved it without enabling verifier networking.
This qualification is a gate result, not a benchmark score.

For a frozen multi-source campaign, repeat `--source-task SOURCE::TASK_ID`. Training mode remains
the default. Held-out mode additionally requires a content-free repository freeze and the exact
agent-version manifest; it rejects partial task sets, changed task/source hashes, a changed split,
or a different agent/runtime image binding before creating the output. The image binding includes
each task's suite-managed digest-locked verifier image as well as the common repository-agent and
outer-runtime images. Results and the summary are replaced atomically after every run, and the
campaign stops on the first infrastructure-invalid outcome. Ordinary verifier rejection remains
an eligible negative sample.

```bash
verigym-training-reference freeze-repository-heldout \
  --split-id hwe-repo-heldout-v1 --agent-version /path/to/agent-version.json \
  --source-task /path/to/ibex::hwe-bench/repo-repair-v1/lowRISC__ibex__pr-222 \
  --source-task /path/to/cva6::hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2945 \
  --source-task /path/to/rocket::hwe-bench/repo-repair-v1/chipsalliance__rocket-chip__pr-3065 \
  --output /data/jzhu484/Agent/experiments/hwe-repo-heldout-v1-freeze
```

## Expansion path

Add repository profiles independently for Caliptra, XiangShan, and OpenTitan.
Each profile declares its repository home, baseline marker, image availability, language/tool
requirements, and isolation limits. Commercial-tool images remain user-supplied and license-bound;
VeriGym stores only safe identities and evaluation summaries.
