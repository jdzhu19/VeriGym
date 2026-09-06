# PR-1816 open-tool research continuation

This continuation tests whether the repaired open toolchain can support one real DeepSeek Harness
trajectory while the official HWE image remains the authoritative verifier. It uses PR-1816 and
seed/sample `503/19`, as described in the [v188 handoff](../todo/2026-09-06_deepseek-harness-v188-astra-handoff.md).

Run from the repository's Python environment after the v188 repair succeeds:

```bash
python scripts/run_hwe_pr1816_open_research.py --run-canary
```

Omit `--run-canary` for qualification only. Each invocation requires fresh output, scratch, and
Docker backing paths; it never overwrites an earlier result or retries a consumed canary. The
script records its Git commit and its own SHA-256. Exact resource paths are defined in the script.

The runner cross-checks the repair report, image lock, cleanup receipt, and exported archive before
loading task inputs. It reuses local HWE archives, starts fresh bind-backed Docker storage under
`/data2`, and requires base-FAIL/reference-PASS on both the open toolchain and official verifier.
Provider configuration is removed during qualification. A failed route stops before the canary.

The canary uses the existing Harness v4 adapter and bounded episode protocol. The trusted Harness
controller runs on the host Docker endpoint and its existing `verigym-hwe-net` network; task and
verifier containers run on the explicitly bound isolated Docker endpoint with `network=none`.
Only the controller receives the existing `VERIGYM_DEEPSEEK_API_KEY` and
`VERIGYM_DEEPSEEK_API_BASE_URL` configuration. No task image layers are imported into the host
Docker daemon. Runtime and Harness initialization finish before the one-use episode marker is
created; the model never receives the qualification workspaces or reference solution.

Output includes `repair-review.json`, both qualification receipts, `qualification.json`, the
research run and teacher transcript when available, `research-canary.json`, a transcript security
scan, `cleanup.json`, and the terminal `result.json`. Report a verifier failure separately from an
infrastructure or protocol failure. All trajectories remain research-only: this command neither
admits examples to SFT nor starts formal collection or training.

Focused development checks:

```bash
pytest -q tests/unit/test_hwe_open_research.py \
  integrations/verigym-deepseek-harness/tests/test_v172_open_toolchain.py
ruff check scripts/run_hwe_pr1816_open_research.py \
  scripts/materialize_hwe_deepseek_harness_v172_open_toolchain.py \
  tests/unit/test_hwe_open_research.py
```
