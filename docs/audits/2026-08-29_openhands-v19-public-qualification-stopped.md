# OpenHands v19 public qualification stopped before task execution

## Outcome

The v19 public-task stage stopped fail closed during controlled verifier-image prewarming. The
temporary `docker:23.0.6-dind` entrypoint added an unauthenticated TCP 2375 listener even though the
requested daemon argument named only its Unix socket. That effective control was not accepted.

The downloader was interrupted immediately. Its temporary privileged container was removed, its
root-owned scratch directory under `/data/jzhu484/Agent/.verigym-tmp/` was removed by a separate
`--network none` cleanup container, and no candidate image was imported into the host daemon. The
sealed experiment progress records:

- status: `stopped_security_invalid`
- failure reason: `downloader_tcp_api_exposed`
- progress hash: `57c67665465b1730a4457505741212d6d63da96f58d51eb6019d65b6056f4b29`
- host images imported: `0`
- zero-model qualifications started: `0`
- provider calls: `0`

This is an infrastructure/security stop, not a verifier rejection and not a benchmark result.

## Scope retained and excluded

The frozen candidate order remains PR-2330, 3226, 2844, 3231, 2989, 1482, and 3059. None was
loaded as a task or assigned to a reserve. The six held-out tasks were not loaded. No qualification
receipt, reserve split, static canary contract, provider canary, formal collection, SFT dataset,
GPU job, adapter, or held-out A/B run was created.

Consequently:

- `qualified_task_count=0`
- `training_reserve_task_ids=[]`
- `validation_reserve_task_ids=[]`
- `canary_contract_materialized=false`
- `production_training_ready=false`
- `benchmark_score_claimed=false`

The sanitized Git receipt is
`configs/training/qwen35_hwe_openhands_v19_public_qualification_v1.json`. Full progress remains only
under `/data/jzhu484/Agent/experiments/openhands-hwe-v19-public-prewarm-v1/`.

## Runner and control changes

The qualification runner is opt in, uses only the seven frozen candidates, never enables implicit
Docker pulls, writes progress atomically, runs zero model processes, and stops immediately on
infrastructure invalidity. It records immutable verifier image and manifest identities, but would
seal a 3-training/2-validation reserve only after five base-FAIL/reference-PASS tasks and five
independently scanned agent images.

The image builder derives one task-keyed agent image at a time with build and runtime network set
to `none`, then invokes the existing v2 image security scan. The sealer requires exact coverage,
distinct agent image IDs, passed security locks, and the historical immutable PR-3204 validation
binding. Substituting PR-3204 now fails before a canary contract is produced.

The prewarm implementation was corrected for future review to bypass the image's entrypoint and
start `dockerd` directly with only `--host=unix:///var/run/docker.sock`. It also validates the
effective path, argument list, and dedicated `verigym-hwe-net` network before any pull. This code
repair does not authorize or perform a retry of the stopped prewarm.

## Verification

Before the real prewarm, local checks passed:

- HWE credential-free suite: `37 passed`
- OpenHands credential-free suite: `262 passed`
- ordinary credential-free repository suite: `1000 passed`, `10 skipped`, `43 deselected`
- HWE strict mypy: `9 source files`, no issues
- OpenHands strict mypy: `28 source files`, no issues
- core strict mypy: `206 source files`, no issues
- targeted v19 qualification tests: `14 passed`
- OpenHands and HWE wheel/sdist content scans: passed
- reproducible core build: wheel and sdist both byte-identical
- changed executable/config artifact security scan: `10 files`, `144,223 bytes`, zero hard leaks
  and zero scanner errors; report hash
  `51c5daf3de069c12a49301af07f8f3d3fdd28e7ac43094588ef4f016837ce01b`
- Ruff lint and `git diff --check`: passed for the touched sources

The stage-specific regression covers frozen candidate order, ordinary fail/pass mismatch skipping,
five-task capacity, atomic infrastructure stop, task-specific image identity rebinding, exact
PR-3204 validation binding, dedicated-network prewarm, TCP daemon rejection, and interrupted
security-failure sealing. GitHub check results belong to the separate qualification audit pull
request. No later v19 stage may start from this stopped receipt.

The first local ordinary-suite invocation accidentally placed a Python 3.12 tiktoken overlay on a
Python 3.11 process; one tokenizer import failed after 999 passes. The failing node passed alone,
then the complete suite passed with the installed frozen `tiktoken==0.7.0`. The first isolated
plugin build bootstrap also received HTTP 502 from the configured package-index proxy; rebuilding
with the already-installed requirement-compatible backend passed both distribution scans. A
whole-worktree Ruff invocation saw four unrelated files in the user's untracked `.verigym-tmp/`;
the scoped changed-source check passed without modifying those files. GitHub checks run from a
clean checkout and remain the authoritative stage guard.
