# DeepSeek Harness v103 inspect-output-bound scaffold authorization

Date: 2026-09-04

## Decision

Authorize exactly one credential-free execution of
`deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1`, and only after this change is
merged and the resulting `main` commit passes all eight ordinary Actions classes.

V103 repairs only the Docker inspect output-bound regression found by the v101 audit. It is a
zero-provider infrastructure qualification, not a model episode. Formal collection, SFT
training, and production readiness remain closed.

## Audited predecessor

V100 stopped before provider access after reproducing base-FAIL/reference-PASS for Ibex PR-465.
Its bounded toolchain-inventory container was created successfully, but the replacement inspect
wrapper rejected the valid response because it used the 4,096-byte generic command-output cap
instead of the original dedicated 1-MiB inspect cap. The immutable PR-465 image config alone is
5,953 bytes before Docker adds the container inspection envelope.

The v101 audit at merge `3546e64c00b80f570334781a228ed521d5a601e8` froze v100, retired the
unused v102 provider identity, and required a fresh successor. Post-merge `main` run
`33789571225` passed all eight check classes.

V100 and its `/data2` data volume must not be retried, reopened, edited, imported, or promoted.

## Authorized repair

V103 uses new bind-backed Docker volumes rooted at:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v103/data`
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v103/socket`

It may read immutable historical result evidence and completed local task archives. It must not
reopen any prior Docker data volume, access a registry, use a partial archive, modify the Docker
daemon root, prune host Docker state, modify VPN/proxy settings, or touch the user-owned
downloader.

The outer DinD daemon remains on network `none`. Source preparation retains its 300-second Docker
control bound. Toolchain inventory retains the v100 finite bounds:

- create: 300 seconds;
- inspect: 300 seconds;
- execute: 120 seconds; and
- force-remove: 300 seconds.

Only the inspect response-size rule changes. V103 accepts exactly one valid Docker inspect JSON
record up to and including 1 MiB. It rejects empty, oversized, malformed, or multi-record output,
nonzero exit, and any stderr. Timeout and cleanup paths remain fail-closed. The scoped wrapper and
all inherited functions must be restored after execution.

V103 retags fresh command images under its own identity and must rematerialize all five tasks; no
partial v100 artifact may enter the contract. Every task must independently pass patch
compatibility, archive/config/source locks, base-FAIL without infrastructure failure,
reference-PASS, audited source/verifier/tool/behavior/security semantics, and the complete
task-specific v2 command-image scan.

The fixed controller and workspace runtime must be transferred, all 12 required images
inventoried, all five runtime prepare cycles run with task network `none`, and the synthetic
Harness initialization preflight must leave no provider marker, request, value, container,
volume, or inner network behind.

V103 may publish its contract only after removing the DinD sidecar and socket volume. The fresh
v103 data volume is then retained as immutable successor evidence.

## Successor boundary

A successful v103 contract still authorizes no provider execution. It permits at most one future
reopen by the distinct identity `deepseek-harness-hwe-v105-official-matrix-v1`, only after the
v104 result audit is merged and its post-merge `main` commit passes all eight Actions classes.
V102 remains retired.

The following remain false throughout v103:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`
