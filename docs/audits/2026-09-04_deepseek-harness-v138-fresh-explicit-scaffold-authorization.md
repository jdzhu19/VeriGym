# DeepSeek Harness v138 fresh explicit scaffold authorization

Date: 2026-09-04

## Decision

Authorize exactly one zero-provider execution of
`deepseek-harness-hwe-v138-fresh-explicit-scaffold-v1` after this implementation is merged and the
exact merge commit passes all eight post-merge `main` Actions classes. This successor rebuilds the
fixed PR-465, PR-1135, PR-1780, PR-2017, and PR-2711 scaffold in fresh bind-backed `/data2`
volumes. It does not reopen, inspect, copy, or mutate the frozen v132 data volume.

V138 is not a provider campaign. It cannot start a model, Harness episode, candidate task,
trajectory collection, SFT training, or production workflow. A successful atomic scaffold is
evidence for an independent v139 result audit only. It may be consumed once and must not be
retried under the same identity after Docker startup or any task archive read.

## Immutable implementation

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v138_fresh_explicit_scaffold_v1.json`
- Manifest file SHA-256:
  `44d916136f0c52725b43222c208bc9b598531b57a68343b2a90f8956cd24be14`
- Manifest canonical hash:
  `82a041fc1a8ee234a08f48178c11699a9b8ef45e50fb110b2d7da234f00a1992`
- Runner:
  `scripts/materialize_hwe_deepseek_harness_v138_fresh_explicit_scaffold.py`
- Runner SHA-256:
  `f77febd523ee7d9653f93a987141e56cf120fe8416a7f05cb56d3e31202cb0d6`
- Required audit merge: `98c083b7dfc6cb378d0ee7239148370308f7c06f`
- Required post-merge `main` run: `33861403120` (eight of eight jobs passed)

The schedule, seed/sample `502/18`, completed archive identities, source commits, official verifier
images, tool hashes, base-FAIL/reference-PASS predicates, v2 scanner policy, and command-image
security properties remain inherited from the byte-exact v132 baseline. The v132 terminal report
and contract are revalidated from immutable evidence, while the failed v136 report and v137 audit
are bound as the reason for the new import policy.

## Explicit archive-import boundary

Each completed local tar is loaded through a subprocess environment that sets `DOCKER_HOST` to the
exact v138 Unix socket and removes `DOCKER_CONTEXT`. The runner then verifies the immutable image
ID, rejects a conflicting official tag, creates a missing tag locally, and verifies the final tag
binding. Registry access and `.partial` archives remain forbidden.

Every task writes a stage diagnostic whether import passes or fails. It retains only exit codes,
stdout/stderr byte counts, timeout bounds, stage names, and an allowlisted category. Raw command
output and raw exception text are neither persisted nor hashed. Import is bounded at 1,800 seconds
and one MiB of captured output per stream. A failed import stops the atomic scaffold and leaves no
partial provider authorization.

## Runtime and security boundary

The outer DinD remains `network=none`, uses VFS, and stores layers only in the exact fresh v138
bind-backed data volume. Command-image scans use deterministic v138 owner/name identities and the
audited 300/60/180/120/720-second create/inspect/start/remove/overall bounds. Task command images
and official verifier containers remain non-root where required, read-only, capability-free,
`network=none`, and restricted to the declared workspace mount.

The five-task runtime-prepare preflight constructs every `DockerRuntime` with a
`DockerCliEngine(docker_host=<exact v138 socket>)`; inherited and remote endpoints are forbidden.
It also requires the all-container/all-volume inner inventory to be empty after every probe.
Agent-toolchain diagnostics cannot replace official verifier outcomes.

On success, the socket volume is removed and only the exact v138 success data volume is retained
for one separately authorized v140 successor reopen. On infrastructure, security, or cleanup
ambiguity, execution stops fail-closed and the exact owned data volume is frozen for audit. No
broad Docker cleanup, daemon restart, VPN/proxy change, downloader interaction, host
`LocalRuntime`, registry request, or predecessor-volume access is authorized.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
