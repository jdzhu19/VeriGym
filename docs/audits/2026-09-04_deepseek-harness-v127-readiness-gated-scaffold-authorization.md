# DeepSeek Harness v127 readiness-gated scaffold authorization

Date: 2026-09-04

## Decision

This change authorizes exactly one zero-provider execution of
`deepseek-harness-hwe-v127-readiness-gated-scaffold-v1`, and only after this implementation is
merged to `origin/main` and that exact merge commit passes all eight Actions classes. The run may
materialize the fixed five-task scaffold from completed local archives and may publish one atomic
provider-execution contract. It does not authorize a model or provider request; an independent
v128 result audit must merge and pass its own post-merge gate first.

The authorized task order is Ibex PR-465, PR-1135, PR-1780, then CVA6 PR-2017 and PR-2711, with
seed 502 and sample index 18. A failure in any readiness, infrastructure, security, archive,
source, image, patch, base/reference, inventory, Harness initialization, or cleanup check consumes
v127 and publishes no partial contract.

## Frozen predecessors

- v118 manifest canonical hash:
  `c646f65d13b19096cf46ed4a9e3ab24a79c94382cd1d1ea9ab36c36c667bf72d`
- v118 authorization merge: `928b117882ae8be4c60520f8d4a49d82edc548b8`
- v118 post-merge `main` run: `33819300080`, eight of eight jobs passed
- v119 audit commit: `c22066916ba51e8c74678be2b0af6ac8d438ac9a`
- v119 post-merge `main` run: `33820413201`, eight of eight jobs passed
- v125 manifest canonical hash:
  `76de583642c6614d80a4b4bac1b95a4f2bd533e3be42a6b5caac3f9fd6ad07c0`
- v125 report canonical hash:
  `6da2ba5dcff5aa424aea2bc1af02157c703fedd12fa6ae11897b3fad0ba9b7de`
- v125 readiness receipt canonical hash:
  `23fc06716d775e4f132e30b8cc0fdf79e3c246f39f632b78f77703cd414160fc`
- v125 cleanup canonical hash:
  `3c6d805971c794b1c30c04c61f7a26b0a422e2f43c4d077c9e7d9532e2c3b1c8`
- v125 source/authorization merge: `70cfa0393b3d2bfa06e26ca11fdccc09cde69d1f`
- v125 post-merge `main` run: `33829039148`, attempt 2 passed all eight jobs
- v126 audit merge: `084afb7c6e690f222d8274871c4fcc51ecf1a56a`
- v126 post-merge `main` run: `33830266674`, eight of eight jobs passed
- v127 manifest canonical hash:
  `cfa04d557d68e3d03efdfc15fdd579eb439b38e31876f186ab7270ed90e5bfcb`

The runner verifies these source and evidence bindings without opening, listing, inspecting,
repairing, importing, removing, or otherwise mutating any v118 or other predecessor Docker volume.

## Exact readiness gate

V127 uses one fresh bind-backed data volume and one fresh bind-backed socket volume under
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v127`. It starts the immutable local
`docker:23.0.6-dind` image once with privileged mode, outer network `none`, no bridge or iptables,
the frozen PID limit, empty TLS-directory setting, and a read-only sentinel. The startup command
has a 60-second limit.

Before any inner-Docker operation, the runner repeatedly executes only the explicit formatter:

`docker info --format '{{.ServerVersion}}\t{{.Driver}}\t{{.DefaultRuntime}}'`

An iteration qualifies only with exit zero, empty stderr, exactly three values, and exact matches
for `23.0.6`, `vfs`, and `runc`. A clean complete mismatch fails immediately. All incomplete,
timed-out, stderr-bearing, or nonzero responses remain transient until the monotonic 120-second
deadline. Each probe is limited to five seconds, sleeps at most one second, and has no smaller
fixed poll-count cap. JSON-formatted Docker info cannot establish readiness. The Docker root and
socket group are checked explicitly after qualification and before any inner operation.

## Offline materialization and isolation

V127 inherits the audited v118 task, source, archive, image, command-image, and verifier locks.
Only complete local archives may be read; registry access and partial archives are forbidden. Each
task must independently demonstrate compatible reference metadata, base-FAIL without an
infrastructure error, reference-PASS, verifier `network=none`, command `network=none`, and a passed
v2 scan. All five tasks must succeed before the contract can be published.

The command images use a fresh v127 tag identity. Runtime preparation, container/volume inventory,
inner-network creation and removal, and streaming attach are bound to the canonical v127 inner
Unix socket. Host-side sidecar commands cannot stand in for inner inventory or inner-network
control. Harness initialization uses only generated synthetic values and cannot cross a provider
marker.

Cleanup removes only resources with the exact v127 owner and role, restores the fresh backing
paths, and must finish before publication. The output, control, runtime, container, volume, socket,
and network identities are all fresh. The shared `/data/docker`, user-owned downloader, VPN/proxy
state, `.partial` files, and other checkouts remain outside this execution.

Execution requires clean synchronized `main`, the exact positive v127 post-merge run ID, the v127
opt-in set to `1`, and all provider variables plus `DOCKER_HOST` and `DOCKER_CONTEXT` removed from
the child environment. The identity is consumed on its first authorized invocation and cannot be
retried.

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
