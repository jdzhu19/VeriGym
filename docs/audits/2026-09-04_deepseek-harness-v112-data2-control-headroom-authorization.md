# DeepSeek Harness v112 data2 control-headroom scaffold authorization

Date: 2026-09-04

## Decision

Authorize implementation of
`deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1`. Authorize exactly one
credential-free execution only after this change is merged and the resulting `main` commit
passes all eight ordinary Actions classes.

V112 repairs only the inherited v94 headroom argument that measured `/` as `control_root`. It
retains every absolute byte and inode threshold and all v109 task, archive, image, semantic,
security, inventory, runtime, cleanup, and zero-provider gates. It is infrastructure
qualification, not a model episode. Formal collection, SFT training, and production readiness
remain closed.

## Audited predecessor

V109 was invoked exactly once after its authorization merge and post-merge eight-class pass. Its
direct progress writer succeeded. It then stopped before Docker because the inherited call used
`control_root=Path("/")`, where 3,344,760,832 free bytes were below the fixed 4-GiB requirement.
The actual Docker, scratch, and output roles on `/data2` all passed, with approximately 40.7 TB
free.

The v110 audit at merge `557e11ffbca95175352e5221e2ee9d8c994588bf` froze v109 and retired the
unused v111 provider identity. Post-merge `main` run `33804279053` passed all eight check classes.
The v109 evidence root contains exactly 14 directories, eight regular files, and no symlinks.
Its report, progress, headroom receipt, five patch-compatibility receipts, and four empty runtime
paths are immutable and must not be reopened, edited, imported, removed, or promoted.

## Authorized repair

V112 uses new bind-backed Docker volumes rooted at:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v112/data`
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v112/socket`

Its real control and runtime directories are:

- `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-control`
- `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-runtime`

The wrapper must intercept the exact inherited v94 headroom call, require its supplied control
argument to remain `/`, require the Docker, shared scratch, and output arguments to remain exact,
then substitute only the empty v112 control directory for measurement. It must reject unexpected
arguments, paths outside `/data2`, non-directories, symlinks, nonempty purpose-bound paths, or any
changed threshold or policy field. The resealed receipt must identify both the inherited and
measured control roots and state that thresholds were unchanged.

V112 may read immutable historical evidence and completed local task archives. It must not access
a registry, use a partial archive, modify or prune the host Docker root, modify VPN/proxy settings,
touch the user-owned downloader, or use `/data/docker` for task layers. The outer DinD daemon
remains on network `none`.

V112 must freshly rematerialize, in fixed order, Ibex PR-465, PR-1135, PR-1780, CVA6 PR-2017,
and PR-2711. Every task retains all patch, archive, OCI, source, verifier, semantic,
base-FAIL/reference-PASS, and complete v2 scan gates. Every task and aggregate receipt must be
resealed with the v112 identity and agree with its fresh `HweCommandImageLock`.

Both initial and final inventory checks must derive their five command-image IDs from the fresh
lock-and-receipt map. Together with the fixed controller, workspace runtime, and five official
verifier images, exactly 12 distinct required images must be present. Inventory remains bounded
to 1 MiB and fail-closed for missing, duplicate, nonzero, stderr, malformed, oversized, non-UTF-8,
or incomplete results.

Provider credentials must be absent. Provider request count, provider call count, and model
process count must remain zero. Contract publication additionally requires both inventory checks,
all runtime and synthetic Harness preflights, internal-network removal, DinD sidecar and
socket-volume cleanup, and consistent fresh mappings across locks, task receipts, materialization
set, and inventory.

## Failure and successor boundary

V112 is one-use. Any failure freezes the identity and its evidence immediately; it must not be
retried. No partial report or contract authorizes provider access.

A successful v112 contract still authorizes no provider execution. It first requires an
independent v113 result audit, that audit's merge, and a post-merge eight-class `main` pass. Only
then may a separate change consider the unused identity
`deepseek-harness-hwe-v114-official-matrix-v1`. V108 and v111 remain retired.

The following remain false throughout v112:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`
