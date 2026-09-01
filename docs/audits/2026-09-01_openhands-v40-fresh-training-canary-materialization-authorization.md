# OpenHands v40 fresh training-canary image authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; zero-provider materialization has not run.

## Why a new materialization is required

The three v33 training reserves are no longer available to a successor provider canary. PR-2330
was consumed by v36, PR-3226 by v38, and PR-3231 by v39. None may be retried or counted as a fresh
formal task. PR-2989 and PR-3059 retain their validation-reserve roles, and PR-3204 remains the
unstarted canary-validation task. Reassigning either validation reserve to training would change
the frozen v33 role contract and is not authorized.

V39 failed because OpenHands SDK 1.42.1 normalized transport-level empty content to one empty
`TextContent` part. The separately merged v22 protocol accepts only that semantically empty shape
for the existing atomic two-call recovery. It still rejects whitespace, non-empty or non-text
content, private reasoning, any other sibling count, and repeated recovery. The evidence and
upstream references are sealed in
`docs/audits/2026-09-01_openhands-v22-empty-content-normalization.md`.

V40 therefore authorizes one new, zero-provider command-image materialization for PR-2549. The
task has older evidence under other frozen campaigns, so this authorization does not claim that it
has never been run and does not relabel or reconstruct any historical trajectory. It is new only
to this v22 successor-canary identity. If the future canary succeeds, that exact trajectory must be
imported into formal readiness without executing PR-2549 again. If it fails, the task and identity
freeze and the formal training schedule needs another replacement.

## Frozen inputs and output

The authorization file is
`configs/training/qwen35_hwe_openhands_v40_fresh_training_canary_materialization_v1.json`.
It binds:

- the completed v33 materialization audit merge, tree, progress, catalog, and the PR-3204 v2 lock
  and security scan;
- the failed v39 audit merge, tree, report, PR-3231 attempt and security scan;
- the v22 repair merge, audit file, and post-merge eight-class Actions run `33471695480`;
- the PR-2549 v2 legacy lock, task/source/verifier identities, its historical public qualification
  audit commit, and the locally available immutable verifier image;
- the official ripgrep 15.2.0 release archive and binary hashes;
- a future static v41 order of PR-2549 training followed by PR-3204 validation, seed 493 and sample
  index 9, using `required_tool_atomic_shape_recovery_v22`.

The one permitted output root is:

`/data/jzhu484/Agent/experiments/openhands-hwe-v40-fresh-training-canary-materialization-v1`

It must not exist before the one authorized invocation. The runner creates one PR-2549 command
image, runs the v2 content-free security scanner, writes one command-image lock, and seals a
two-task static canary catalog/contract that reuses only the unstarted v33 PR-3204 validation
binding. The PR-2549 image tag namespace is new and task-specific.

Although only one image is built, execution must pass the existing conservative six-image
absolute headroom policy: 96 GiB on the Docker data root plus the independent control, scratch,
output, and inode thresholds. This preserves the reviewed safety margin and avoids weakening the
shared preflight implementation.

## Authorized execution

Only after this pull request is merged, `HEAD` equals `origin/main`, and all eight required main
job classes pass, the following command may be invoked once with the opt-in set only for that
process:

```bash
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V40_TRAINING_CANARY=1 \
python scripts/materialize_cva6_openhands_v40_fresh_training_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v40_fresh_training_canary_materialization_v1.json \
  --legacy-image-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/image-locks/pr-2549.json \
  --v33-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v39-root /data/jzhu484/Agent/experiments/openhands-hwe-v39-provider-canary-v1 \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --scratch-root /data/jzhu484/Agent/.verigym-tmp \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v40-fresh-training-canary-materialization-v1
```

At execution time the runner revalidates merged source state, input hashes, ancestor commits,
space and inodes, the v33 validation binding, v39 terminal evidence, the PR-2549 legacy lock, and
the ripgrep release identity before building. A failed headroom check, build, scan, cleanup, hash,
or binding freezes v40 with no retry.

## Explicitly not authorized

This change authorizes no provider client or request, canary episode, formal collection, SFT,
inference evaluation, GPU work, held-out access, reserve-role change, historical retry, or
historical relabeling. The terminal state before and after successful materialization remains:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`;
- zero provider episodes, calls, retries, and model processes.

A separate v41 authorization and green post-merge `main` run are required before any provider
canary may start.
