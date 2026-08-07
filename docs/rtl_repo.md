# RTL-Repo adapter

The optional `verigym-rtl-repo` package adapts the official
[AUCOHL/RTL-Repo](https://github.com/AUCOHL/RTL-Repo) dataset without copying it into the VeriGym
distribution. RTL-Repo is a repository-context, next-line-completion benchmark; it is not a
compile, simulation, synthesis, or PPA benchmark.

## Install and prepare the source

Install the adapter beside the core package:

```bash
python -m pip install -e integrations/verigym-rtl-repo
```

Provide a local snapshot of `ahmedallam/RTL-Repo` with this native layout:

```text
/datasets/RTL-Repo/
  data/
    train-*.parquet
    test-*.parquet
```

VeriGym never downloads the dataset or uses network access during discovery, execution, replay,
or reporting. Strict validation checks the official 2,924-train/1,174-test row counts, required
columns, Parquet readability, path safety, size bounds, and a content hash:

```bash
verigym suites validate \
  --suite rtl-repo \
  --source /datasets/RTL-Repo \
  --variant official-parquet-v1
```

## Task and scoring semantics

Stable native IDs are `train-000000` and `test-000000` style row ordinals. Each task sends the
official prompt text unchanged as its single ChatEval user message (`// Repo Name`, context
paths/snippets, and cropped target file), places only `completion.txt` in the candidate workspace,
and keeps `next_line` verifier-only. The provider may still apply its own chat template. ChatEval
makes one model call with a 50-token output bound and no tools:

```bash
verigym run \
  --suite rtl-repo \
  --suite-source /datasets/RTL-Repo \
  --suite-variant official-parquet-v1 \
  --task test-000000 \
  --mode chat \
  --agent single-turn \
  --model openai-compatible \
  --runtime local \
  --output runs/
```

The harness selects the first nonempty, non-`//` line, matching upstream post-processing.
Correctness is the upstream whitespace-token Exact Match. The verifier also records upstream
character Edit Similarity on a 0–100 scale. Reports aggregate these as benchmark-native metrics
only within an exact suite-version/dataset-hash/metric-profile/split/unit partition; they are not
a universal score.

## Bounded smoke validation

The ordinary plugin tests use synthetic Parquet rows. To inspect the real release without running
all 1,174 test tasks, run only the official first-row contract test:

```bash
VERIGYM_RTL_REPO_ROOT=/datasets/RTL-Repo pytest \
  -m external_benchmark \
  integrations/verigym-rtl-repo/tests/test_adapter.py::test_official_snapshot_first_test_row_smoke
```

The prompt policy uses the full official context without the upstream script's model-tokenizer-
specific truncation. Experiments that apply another context-window policy must use a distinct
profile and must not combine their native metric aggregates with this profile.
