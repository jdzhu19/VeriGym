# DeepSeek Harness v100 inventory-timeout scaffold authorization

Date: 2026-09-04

## Decision

Authorize exactly one credential-free execution of
`deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1`, and only after this change is merged
and the resulting `main` commit passes all eight ordinary Actions classes.

V100 repairs only the under-sized Docker control-plane timeout found by the v98 audit. It is a
zero-provider infrastructure qualification, not a model episode. Formal collection, SFT training,
and production readiness remain closed.

## Audited predecessor

V97 stopped before provider access while creating the network-disabled toolchain-inventory
container for CVA6 PR-2017. Its fixed 30-second Docker-create bound expired. The three preceding
Ibex tasks had already reproduced base-FAIL/reference-PASS, passed all 29 v2 security checks, and
accepted fresh command-image identities, proving that v97 repaired the historical image-ID gate.

The v98 audit at merge `a766cc9d564f89c96170b1e451852e29e107388e` froze v97, retired the
unused v99 provider identity, and required a fresh successor. Post-merge `main` run `33782913003`
passed all eight check classes after one failed-job-only rerun of the timing-sensitive fake-Codex
Docker test.

The v98 document transcribed the v97 manifest and runner file SHA-256 values incorrectly. The
immutable v97 commit and current files recompute to
`8d08ff6198a1c730f19a401b0822116bae757694267d0a551dad39594c9520b4` and
`bc7e7c0df6337bf66411a5d5be49ace4fc7415c52263a54ea06f91fa6b39fbea`; this erratum does not alter
the v97 execution or result evidence.

V97 and its `/data2` data volume must not be retried, reopened, edited, imported, or promoted.

## Authorized repair

V100 uses new bind-backed Docker volumes rooted at:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v100/data`
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v100/socket`

It may read immutable historical evidence and completed local task archives. It must not reopen
any prior Docker data volume, access a registry, use a partial archive, modify the Docker daemon
root, prune host Docker state, modify VPN/proxy settings, or touch the user-owned downloader.

The outer DinD daemon remains on network `none`. Source preparation retains its 300-second Docker
control bound. Toolchain inventory uses separately frozen finite bounds:

- create: 300 seconds;
- inspect: 300 seconds;
- execute: 120 seconds; and
- force-remove: 300 seconds.

The bounds apply only inside the v100 task-materialization scope and are restored afterward. A
timeout remains an infrastructure failure that atomically withholds the contract and triggers
sidecar/socket cleanup. V100 retags fresh command images under its own identity and must
rematerialize all five tasks; no partial v97 artifact may enter the contract.

Every task must independently pass patch compatibility, archive/config/source locks, base-FAIL
without infrastructure failure, reference-PASS, audited source/verifier/tool/behavior/security
semantics, and the complete task-specific v2 command-image scan. The fixed controller and
workspace runtime must be transferred, all 12 required images inventoried, all five runtime
prepare cycles run with task network `none`, and the synthetic Harness initialization preflight
must leave no provider marker, request, value, container, volume, or inner network behind.

V100 may publish its contract only after removing the DinD sidecar and socket volume. The fresh
v100 data volume is then retained as immutable successor evidence.

## Successor boundary

A successful v100 contract still authorizes no provider execution. It permits at most one future
reopen by the distinct identity `deepseek-harness-hwe-v102-official-matrix-v1`, only after the
v101 result audit is merged and its post-merge `main` commit passes all eight Actions classes.

The following remain false throughout v100:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`
