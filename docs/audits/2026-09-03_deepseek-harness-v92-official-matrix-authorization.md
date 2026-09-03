# DeepSeek Harness v92 official matrix authorization

Date: 2026-09-03

## Decision

Authorize exactly one execution of
`deepseek-harness-hwe-v92-official-matrix-v1` after this authorization, its immutable
manifest, runner, tests, and security contract are merged to `main` and the corresponding
post-merge `main` workflow passes all eight required check classes.

The authorization is inherited from the independently audited v90 zero-provider scaffold.
The v91 audit was merged as commit `15919391354ddecdf29996893f4c745835101f17`, and
post-merge `main` run `33762766907` passed 8/8 required check classes. V92 binds that gate,
the v90 manifest and canonical identity, and the exact SHA-256 and canonical hashes of the
v90 report, contract, image inventory, controller transfer receipt, DinD runtime receipt,
cleanup receipt, and every task/source/image/security receipt. The qualified source-control
timeout remains exactly 300 seconds.

## Frozen execution

The runner must execute these tasks serially with seed/sample `502/18`:

1. Ibex PR-465
2. Ibex PR-1135
3. Ibex PR-1780
4. CVA6 PR-2017
5. CVA6 PR-2711

Every task remains bound to its v90 task/source receipt, task-specific credential-free
command image, v2 security scan, official verifier image, agent toolchain identity, and
repository-specific profile. The provider identity is DeepSeek v4 Flash through Harness
`0.1.1-rc.2` and integration `0.5.0`. Per-task limits are 64 calls, 1,000,000 provider
tokens, 65,536 context tokens, 2,048 output tokens, temperature zero, and zero request or
episode retries. Tool choice remains `auto`; public rationale and sibling calls remain
allowed; hidden reasoning and foreign tools remain fail-closed.

## Docker and network boundary

The audited v90 DinD data volume may be reopened once. It is a local-driver bind volume
whose data backing is `/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/data`; task layers
therefore remain on `/data2` and do not consume the host daemon root under `/data/docker`.
The socket volume is recreated over the fixed owner-only `/data2` backing and removed after
execution. A timed-out readiness probe is treated only as not-ready inside the bounded
startup deadline. It does not escape the retry loop or authorize an episode retry.

Only the outer DinD sidecar and the inner Harness controller may use the existing
`verigym-hwe-net` bridge. Task command containers and official verifier containers remain
`network=none`. The host Docker configuration, VPN, proxy configuration, downloader,
unrelated Docker resources, and partial archives remain out of scope.

## Stop and data policy

Infrastructure or security failure stops immediately. An ordinary model or verifier failure
consumes that task and permits the next task. Two consecutive no-modification, no-progress,
or trajectory-structure failures stop the remaining matrix. A task that provably fails before
the public provider marker is not provider-consumed; an invalid or unreadable marker is
handled conservatively as consumed. The identity is never retried.

Passing trajectories may be listed only as candidate SFT inputs pending an independent v93
audit. Failed trajectories remain audit or research context. This run does not authorize
formal collection, candidate import, training, production training, task substitution, or a
second opening of the v90 data volume. All collection and training flags remain false.
