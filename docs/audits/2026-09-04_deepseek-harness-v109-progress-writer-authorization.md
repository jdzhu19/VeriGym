# DeepSeek Harness v109 progress-writer scaffold authorization

Date: 2026-09-04

## Decision

Authorize implementation of `deepseek-harness-hwe-v109-progress-writer-scaffold-v1`.
Authorize exactly one credential-free execution only after this change is merged and the
resulting `main` commit passes all eight ordinary Actions classes.

V109 repairs the immediate v106 progress-writer composition defect while retaining the v106
fresh lock-derived inventory design. It remains a zero-provider infrastructure qualification,
not a model episode. Formal collection, SFT training, and production readiness remain closed.

## Audited predecessor

V106 was invoked exactly once after its authorization merge and post-merge eight-class pass. It
failed during its first progress write because it referenced a nonexistent helper attribute on
the frozen v94 module. The failure occurred before headroom inspection, Docker, archive access,
task materialization, Harness initialization, model startup, or provider access.

The v107 audit at merge `96111d6073e4fe0944035a1a9a4b480e3f08d811` froze v106 and retired the
unused v108 provider identity. Post-merge `main` run `33800282289` passed all eight check classes.
The v106 evidence root contains exactly 14 directories and no files or symlinks; it and every
earlier campaign volume remain immutable and must not be reopened, edited, imported, removed, or
promoted.

## Authorized repair

V109 uses new bind-backed Docker volumes rooted at:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v109/data`
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v109/socket`

It may read immutable historical evidence and completed local task archives. It must not access
a registry, use a partial archive, modify or prune the host Docker root, modify VPN/proxy
settings, touch the user-owned downloader, or use `/data/docker` for task layers. The outer DinD
daemon remains on network `none`.

The progress writer must call the actual frozen base writer captured by the v97 wrapper. Tests
must invoke the real v109 writer, validate its on-disk canonical hash, v109 format and status,
and verify that all patched functions are restored after their scope exits.

V109 must freshly rematerialize, in fixed order, Ibex PR-465, PR-1135, PR-1780, CVA6 PR-2017,
and PR-2711. Every task retains all patch, archive, OCI, source, verifier, semantic,
base-FAIL/reference-PASS, and complete v2 scan gates. Each task receipt must be resealed with the
v109 campaign identity and must agree with its fresh `HweCommandImageLock`.

Both initial and final inventory checks must derive their five command-image IDs from the fresh
lock-and-receipt map. Together with the fixed controller, workspace runtime, and five official
verifier images, exactly 12 distinct required images must be present. Historical schedule
command-image IDs are audit context only. Inventory remains bounded to 1 MiB and fail-closed for
missing, duplicate, nonzero, stderr, malformed, oversized, non-UTF-8, or incomplete results.

Provider credentials must be absent. Provider request count, provider call count, and model
process count must remain zero. Contract publication additionally requires both inventory
checks, all runtime and synthetic Harness preflights, internal-network removal, DinD sidecar and
socket-volume cleanup, and consistent fresh mappings across locks, task receipts, materialization
set, and inventory.

## Failure and successor boundary

V109 is one-use. Any failure freezes the identity and its evidence immediately; it must not be
retried. No partial report or contract authorizes provider access.

A successful v109 contract still authorizes no provider execution. It first requires an
independent v110 result audit, that audit's merge, and a post-merge eight-class `main` pass. Only
then may a separate change consider the unused identity
`deepseek-harness-hwe-v111-official-matrix-v1`. If v109 fails, v111 is retired unused. V108
remains retired.

The following remain false throughout v109:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`
