# DeepSeek Harness v115 explicit nested-Docker-socket scaffold authorization

Date: 2026-09-04

## Decision

Authorize exactly one zero-provider execution of
`deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1`, and only after this
authorization implementation is merged and the resulting `main` commit passes all eight required
Actions jobs. This authorization does not permit a model request, formal collection, training, use
of a registry or partial archive, reuse of a predecessor DinD data volume, or mutation of
`/data/docker`.

V115 is the narrow repair authorized by the independent v113 audit. It retains the v112 task,
archive, OCI, source, headroom, materialization, security-scan, inventory, cleanup, and
zero-provider constraints. It replaces the two defective implicit Docker connections with one
explicitly supplied, canonical local Unix-socket endpoint:

`unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket/docker.sock`

The endpoint is supplied separately to the core `DockerCliEngine` and to the sanitized DeepSeek
Harness helper environment. Neither interface inherits `DOCKER_HOST`, `DOCKER_CONTEXT`, arbitrary
environment variables, a relative endpoint, or a remote Docker transport.

## Predecessor and merge gates

- v112 authorization merge: `96bbf99c5e358f2bf92cfd912ab92d6d10407ec6`
- v112 post-merge `main` run: `33807102983`, eight of eight jobs passed
- v112 result audit merge: `9f79f54725c365bd0ab9ba9389f2ac421db1b155`
- v113 post-merge `main` run: `33810326256`, eight of eight jobs passed
- v112 manifest canonical hash:
  `762db692017a7286aa97cf8d44311ed64c85fe39d5cc120f6b975acfb1802703`
- v112 report canonical hash:
  `dd63f0945d93a29c2321d15f273a2f567504a2a954d78024212ad30ace3690d0`
- v115 manifest canonical hash:
  `d851e4c0b2831865161f5ada6bf217d1df115dde03303925fece17e63fd4202c`

The runner must execute from clean, synchronized `main`; all required v115 implementation and
test paths must already be tracked in that commit. Its `--post-merge-main-run-id` must identify
the successful post-merge workflow for that exact commit. A branch execution or pre-merge
execution is forbidden.

## Fresh storage and one-use boundary

The exact new writable roots are:

- evidence:
  `/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1`
- DinD data: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v115/data`
- DinD socket: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket`
- control scratch:
  `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-control`
- runtime scratch:
  `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v115-runtime`

All must start fresh under `/data2`. The retained v112 data volume is frozen and must not be
opened, imported, reused, deleted, or modified. The empty v112 socket, control, and runtime paths
must remain empty. V115 may read the frozen v112 evidence solely to validate its exact audit
bindings.

The existing image downloader remains user-owned. V115 may not start another registry download,
alter VPN or proxy state, consume `.partial` data, change the unrelated repository at
`/data/jzhu484/Agent/VeriGym`, or delete anything from `/data/docker`.

## Execution boundary

The invocation must explicitly unset all provider-related names enforced by the runner and set
only the v115 opt-in variable. The initialization provider values are locally generated synthetic
values targeting the closed loopback port and must neither cross the request marker nor persist in
evidence. The helper controller runs on the temporary inner `verigym-hwe-net`, which must be
internal and removed before publication. Task and verifier containers remain `network=none`.

Any infrastructure, safety, qualification, endpoint, inventory, or cleanup failure closes the
single v115 identity without retry and without a partial contract. The result must preserve zero
provider calls, zero model processes, no raw exception, and all formal/training flags false.

## Success condition and successor

Success requires all five tasks to be freshly rematerialized from completed local archives with
base-FAIL/non-infrastructure-failure and reference-PASS; all fresh command images must pass v2
security scans and be present on the inner daemon. Each runtime prepare must use an explicitly
bound `DockerCliEngine`. Harness initialization must use the same explicit socket and must prove
that the controller starts on the inner daemon without a provider request. Cleanup and a final
fresh-image inventory must pass before the provider scaffold contract can be published.

Even on success, no provider execution is authorized until an independent v116 result audit is
merged and its post-merge `main` workflow passes all eight jobs. V114 is retired unused. Any
future provider matrix uses the fresh v117 identity and separately supplied ephemeral credentials.

The following remain false: `formal_collection_allowed`, `formal_collection_started`,
`collection_started`, `training_started`, and `production_training_ready`.
