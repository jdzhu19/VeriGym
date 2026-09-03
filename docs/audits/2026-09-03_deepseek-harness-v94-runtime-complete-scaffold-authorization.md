# DeepSeek Harness v94 runtime-complete scaffold authorization

Date: 2026-09-03

## Decision

Authorize exactly one credential-free execution of
`deepseek-harness-hwe-v94-runtime-complete-scaffold-v1`, and only after this change is merged and
the resulting `main` commit passes all eight ordinary Actions classes.

This is an infrastructure repair, not a model episode. Formal collection, SFT training, and
production readiness remain closed.

## Audited predecessor

The independently audited v92 result is frozen at v93 merge commit
`04ce5601446078db6084c90ac0eb812807807d0b`; post-merge `main` run `33766642633` passed all eight
classes. V92 stopped before the first provider request with zero provider episodes, calls, and
tokens. It consumed the one permitted reopen of the v90 data volume, so neither v90 nor v92 may be
retried or rewritten.

The failure was an incomplete image inventory: v90 sealed the controller, five task-specific
command images, and five official verifier images, but omitted the fixed workspace runtime image
`sha256:5b95472e7fbfa80eb0cf173099254ef5285fcd78f7c3c78b42678ae9181dd96e` required by
`DockerRuntime`.

## Authorized repair

V94 must use new bind-backed Docker volumes rooted at:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v94/data`
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v94/socket`

It may read the immutable v90 task evidence, completed local task archives, and the already-present
controller and workspace-runtime host images. It must not reopen
the v90 or v92 Docker data volume, access a registry, use a partial archive, modify the Docker daemon
root, prune host Docker state, modify VPN/proxy settings, or touch the user-owned downloader.

The isolated DinD daemon runs with outer network `none`. It transfers the controller and workspace
runtime by a read-only outer `docker save | docker load` pipe with bounded content-free diagnostics
and no persisted transfer archive. Inside that fresh daemon, it revalidates the five completed local
archives, reproduces base-FAIL/reference-PASS, and deterministically rebuilds the five command images.
The sealed inner inventory must then contain exactly the twelve required immutable image identities:
controller, workspace runtime, five command images, and five official verifier images.

Before publishing a successor contract, v94 must:

1. prove all twelve image IDs are present, including the workspace runtime;
2. run `DockerRuntime.prepare()` and cleanup for all five tasks with task network `none`;
3. initialize the pinned DeepSeek Harness controller using synthetic values only, on a temporary
   internal inner network while the outer DinD daemon remains network-isolated;
4. prove that no provider-request marker, provider call, retained synthetic value, container,
   runtime volume, or temporary inner network remains;
5. remove the DinD sidecar and socket volume while retaining only the fresh v94 data volume.

Any failure publishes no partial execution contract. The result is then frozen for an independent
v95 audit.

## Successor boundary

A successful v94 contract remains unauthorized for provider execution. It permits at most one
future reopen by the distinct identity `deepseek-harness-hwe-v96-official-matrix-v1`, only after a
separate v95 result audit is merged and its post-merge `main` commit passes all eight Actions
classes.

The following values remain false throughout v94:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`
