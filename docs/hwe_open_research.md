# PR-1816 open-tool research continuation

This continuation tests whether the repaired open toolchain can support one real DeepSeek Harness
trajectory while the official HWE image remains the authoritative verifier. It uses PR-1816 and
seed/sample `503/19`, as described in the [v188 handoff](../todo/2026-09-06_deepseek-harness-v188-astra-handoff.md).

Run from the repository's Python environment after the offline successor repair succeeds:

```bash
python scripts/run_hwe_pr1816_open_research.py --run-canary
```

Omit `--run-canary` for qualification only. Each invocation requires fresh output, scratch, and
Docker backing paths; it never overwrites an earlier result or retries a consumed canary. A stop before the episode marker and before any research run may be resumed with
`--resume-canary`: this requires clean previous cleanup, unchanged successful comparison receipts,
and the same task and image locks. It preserves the earlier stop receipts and reloads fresh
Docker storage without rerunning the successful comparisons. The script records its Git commit
and its own SHA-256. Exact resource paths are defined in the script.

The runner cross-checks the repair report, image lock, security scan, cleanup receipt, and exported archive before
loading task inputs. It reuses local HWE archives, starts fresh bind-backed Docker storage under
`/data2`, and requires base-FAIL/reference-PASS on both the open toolchain and official verifier.
Provider configuration is removed during qualification. A failed route stops before the canary.

The canary uses the existing Harness v4 adapter and bounded episode protocol. The trusted Harness
controller runs on the canonical host Docker socket (`/run/docker.sock` here) and its existing `verigym-hwe-net` network; task and
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

## Offline build repair

The v188 run completed its git-package repair but failed during Verilator compilation. Its
terminal evidence remains unchanged under
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v188-git-builder-repair-v1`.
A focused successor uses identity `hwe-open-tools-offline-repair-20260906-v1` and records bounded,
sanitized compiler diagnostics in its own experiment directory.

The actual compiler error was `FlexLexer.h: No such file or directory`. The builder had flex 2.6.4
but omitted its C++ header. The host's flex 2.5.37 header was deliberately not used. The added input
is the unmodified [official flex 2.6.4 header](https://raw.githubusercontent.com/westes/flex/ab49343b08c933e32de8de78132649f9560a3727/src/FlexLexer.h),
SHA-256 `ee9859d6b3027ed565f98f42744e438ab31b2cd2e9f797ddf870029ca2021686`, retained with its
copyright notice under `/data2/jiadongzhu/Agent/datasets/tools/flex/2.6.4/`.

[`Dockerfile.research`](../docker/open-rtl-tools-hwe/Dockerfile.research) records the combined
recipe. Its local context requires the pinned Verilator and ripgrep archives from the v172
manifest plus `FlexLexer.h`. First load the v178 builder archive and accepted open-tools image into
an isolated daemon, build `Dockerfile.v188-builder`, and bind that result to the local
`verigym/open-rtl-tools:v180-builder` tag. Build the research Dockerfile with `--network=none`,
`--pull=false`, and the same Verilator/ripgrep hash and host UID/GID arguments as v180.
No registry access is needed after input acquisition.

The repair session executed configuration, compilation, installation, and runtime-image assembly
as separate phases. Compilation used a retained container with 8 CPUs and 32 GiB memory, enabling
the missing-header fix to reuse completed object files. `build-provenance.json`, the executed
Dockerfile fragments, bounded phase logs, and the final image/archive locks record the actual
build. The combined Dockerfile is a reproduction recipe; it was not independently rebuilt after
those phases passed.

The continuation also fixes two dormant open-route defects: Docker bind mounts used an unsupported
bare `rw` field, and reference candidate paths already prefixed with `repository/` were incorrectly
written into a nested repository directory. A regression test verifies that the test actually
reads the patched reference file. Failed comparisons now retain their result receipt.

## Result on 2026-09-06

The offline repair, independent receipt review, and both PR-1816 base/reference comparisons passed.
The single canary then made 13 real provider calls and 14 tool operations, consuming 26,793 tokens.
It returned `max-tokens` without making an edit or calling `finish`. The adapter classified this
as `incomplete_harness_trajectory`; it emitted no valid teacher transcript and quarantined the
candidate, so the final official verifier was skipped. The earlier official qualification did run
and passed its required base-FAIL/reference-PASS comparison.

The run is consumed and must not be retried. Artifact scanning passed and all owned runtime
resources were removed. `research_canary_completed` in the runner result means the attempt ended,
not that the model repaired the task. No data was admitted to SFT or training. The remaining issue
is bounded model completion under the pinned 2,048-token response cap; image repair and both
qualification routes no longer block progress. See the handoff for exact receipts and next work.
