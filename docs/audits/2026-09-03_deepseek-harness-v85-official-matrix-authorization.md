# DeepSeek Harness v85 official matrix authorization

Date: 2026-09-03

## Decision

Authorize exactly one execution of
`deepseek-harness-hwe-v85-official-matrix-v1` after this authorization, its manifest,
runner, tests, and security contract are merged to `main` and the post-merge `main`
workflow passes all eight required check classes.

The authorization is inherited from the independently audited v83 scaffold. The v84
audit was merged as commit `296c708710bd2e3a33bb78d641c88d72f80d4c11`, and post-merge
`main` run `33747143064` passed 8/8 required check classes. V85 binds those values and
the exact SHA-256 and canonical hashes of the v83 manifest, report, contract, image
inventory, controller transfer receipt, DinD runtime receipt, and cleanup receipt.

## Frozen execution

The runner must execute these tasks serially with seed/sample `502/18`:

1. Ibex PR-465
2. Ibex PR-1135
3. Ibex PR-1780
4. CVA6 PR-2017
5. CVA6 PR-2711

Every task remains bound to its v83 task/source receipt, command-image lock, v2
security scan, task-specific credential-free command image, and official verifier image.
The provider identity is DeepSeek v4 Flash through Harness `0.1.1-rc.2` and integration
`0.5.0`. Per-task limits are 64 calls, 1,000,000 provider tokens, 65,536 context tokens,
2,048 output tokens, temperature zero, and zero request or episode retries.

## Docker and network boundary

The existing v83 DinD data volume may be reopened once. Its local-volume bind backing
is `/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data`; task layers therefore do not
consume the host daemon root under `/data/docker`. The socket volume is recreated over
the fixed owner-only `/data2` backing and removed after execution. The host Docker daemon
configuration, VPN, proxy configuration, downloader, unrelated Docker resources, and
partial archives are out of scope.

Only the outer DinD sidecar and the inner Harness controller may use the existing
`verigym-hwe-net` user-defined bridge. Task command containers and official verifier
containers remain `network=none`. The controller image is accepted inside the isolated
daemon only as the exact canonical tag plus image ID whose offline transfer is bound to
the audited v83 receipt; absence of a synthetic inner repository digest is not a reason
to contact a registry.

## Stop and data policy

Infrastructure or security failure stops immediately. An ordinary model or verifier
failure consumes that task and permits the next task. Two consecutive no-modification,
no-progress, or trajectory-structure failures stop the remaining matrix. A task that
provably fails before the public provider marker is not provider-consumed; an invalid or
unreadable marker is handled conservatively as consumed.

Passing trajectories may be listed only as candidate SFT inputs pending an independent
v86 audit. Failed trajectories remain audit or research context. This run is not a
benchmark score and does not authorize formal collection, import, training, production
training, retries, task substitution, or a second opening of the v83 data volume.

The following flags remain false in every receipt and final result:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`
