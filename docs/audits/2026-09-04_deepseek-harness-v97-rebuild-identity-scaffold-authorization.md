# DeepSeek Harness v97 rebuild-identity scaffold authorization

Date: 2026-09-04

## Decision

Authorize exactly one credential-free execution of
`deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1`, and only after this change is merged and
the resulting `main` commit passes all eight ordinary Actions classes.

V97 repairs only the invalid cross-build image-ID equality requirement found by the v95 audit. It
is a zero-provider infrastructure qualification, not a model episode. Formal collection, SFT
training, and production readiness remain closed.

## Audited predecessor

The v94 identity stopped before provider access after PR-465 reproduced base-FAIL/reference-PASS,
retained the frozen source and official verifier identities, and passed every v2 security check.
Its rebuilt unsanitized and derived command image IDs differed from their historical v90 values.
The v95 audit at merge `57cf77be8d9992e5fcc2e5833ec64ff458365d00` froze v94, retired the
unused v96 identity, and identified historical derived-image equality as the invalid requirement.
Post-merge `main` run `33776059453` passed all eight check classes.

V94 and its `/data2` data volume must not be retried, reopened, edited, imported, or promoted.

## Authorized repair

V97 uses new bind-backed Docker volumes rooted at:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v97/data`
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v97/socket`

It may read the immutable v90/v92/v94 evidence and completed local task archives. It must not
reopen any historical Docker data volume, access a registry, use a partial archive, modify the
Docker daemon root, prune host Docker state, modify VPN/proxy settings, or touch the user-owned
downloader.

The outer DinD daemon remains on network `none`. V97 must transfer the fixed controller and
workspace-runtime images, then rematerialize the exact five-task schedule from completed local
archives. Every task must independently pass patch compatibility, archive/config/source locks,
base-FAIL without infrastructure failure, reference-PASS, and the complete task-specific v2
command-image security scan.

V97 compares the new artifact to the audited predecessor on task/source/verifier/tool identity,
runtime behavior, and security semantics. The historical v90 command image, scan, and derived
lock identities remain recorded as advisory provenance but are not equality gates. Instead, v97
freezes the immutable command image, scan, and lock IDs produced by this one materialization in
its own atomic successor contract.

Before publishing that contract, v97 must also:

1. prove that the fixed controller, workspace runtime, five new command images, and five official
   verifier images form the complete required inner inventory;
2. run `DockerRuntime.prepare()` and cleanup for all five tasks with task network `none`;
3. initialize the pinned DeepSeek Harness controller with synthetic values only on a temporary
   internal inner network while the outer daemon remains network-isolated;
4. prove no provider marker, call, retained synthetic value, runtime container, volume, or inner
   network remains; and
5. remove the DinD sidecar and socket volume, retaining only the fresh v97 data volume.

Any failure publishes no partial contract and permanently freezes v97 for a v98 result audit.

## Successor boundary

A successful v97 contract still authorizes no provider execution. It permits at most one future
reopen by the distinct identity `deepseek-harness-hwe-v99-official-matrix-v1`, only after the v98
result audit is merged and its post-merge `main` commit passes all eight Actions classes.

The following remain false throughout v97:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`
