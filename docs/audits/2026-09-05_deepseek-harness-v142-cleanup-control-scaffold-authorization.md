# DeepSeek Harness v142 cleanup-control scaffold authorization

Date: 2026-09-05

## Decision

Authorize exactly one zero-provider execution of
`deepseek-harness-hwe-v142-cleanup-control-scaffold-v1` after this implementation is merged and
the exact merge commit passes all eight post-merge `main` Actions classes. The successor rebuilds
the fixed PR-465, PR-1135, PR-1780, PR-2017, and PR-2711 scaffold in fresh bind-backed `/data2`
volumes. It does not reopen, inspect, copy, or mutate the frozen v140 data volume.

V142 is not a provider campaign. It cannot configure DeepSeek, start a model or Harness episode,
execute a candidate task, collect trajectories, start SFT training, or claim production
readiness. A successful atomic scaffold is evidence for an independent v143 result audit only.
The identity is consumed by its first authorized start and may not be retried after Docker startup
or any task archive read.

## Immutable implementation

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v142_cleanup_control_scaffold_v1.json`
- Manifest file SHA-256:
  `0535dbabb1af93aa128504e3a728dfb7a1806d3960a471709689408a0a492230`
- Manifest canonical hash:
  `e092e4f943b51acffbd900c967d5732c616051491afed459aa11769813cc30ae`
- Runner:
  `scripts/materialize_hwe_deepseek_harness_v142_cleanup_control_scaffold.py`
- Runner SHA-256:
  `8f9435da7ec89a32470b930d65a3f58d3ba414d9879c6d2488705e8ed43aaca7`
- Required audit merge: `9a9713cfab4247f783fd8fc841ee46c5d0347bf6`
- Required post-merge `main` run: `33896629910` (eight of eight jobs passed)

The exact v140 manifest, runner, authorization, terminal report, five-task materialization set,
runtime-preparation receipt, Harness-initialization receipt, separate late-cleanup receipt, and
v141 audit are hash-bound. The schedule, seed/sample `502/18`, completed local archive identities,
task/source locks, official verifier images, tool hashes, base-FAIL/reference-PASS predicates,
and command-image scan policy remain inherited from the audited path.

## Narrow cleanup-control repair

V140 proved all five task, verifier, command-image, runtime, and zero-provider Harness preflights.
It failed only because the inherited socket-cleanup `docker run` controller used a 60-second wait.
The independently executed late cleanup proved that the exact already-created helper completed in
about two seconds when allowed a 300-second controller wait.

V142 changes only that cleanup-control surface. Its exact owner-labelled, `network=none`,
read-only-root, capability-minimized cleanup helper uses a maximum 300-second controller wait, and
the exact socket-volume removal uses the same bound. Every attempt records only allowlisted stage
status, exit code, byte counts, numeric bounds, cleanup booleans, and canonical hashes. Raw output,
raw exceptions, and nonempty output hashes are forbidden. A helper timeout, nonzero result,
oversized output, volume-removal failure, or backing ownership/mode mismatch stops fail-closed and
prevents atomic scaffold publication.

The official verifier still uses its separate 300-second Docker control bound and unchanged
900-second test bound. Task scripts, images, candidate semantics, resource profile, and
`network=none` isolation are unchanged.

## Runtime and artifact boundary

Each completed local HWE tar is imported through the exact fresh v142 nested Unix socket.
Registry access and `.partial` archives are forbidden. Task command and official verifier
containers remain `network=none`; command images remain task-specific, credential-free, and
Codex-free and must pass the existing v2 scan. All five tasks and every preflight must complete,
then socket cleanup must be confirmed, before the atomic scaffold contract is published.

Success retains only the exact v142 data volume for one independently audited and separately
authorized `deepseek-harness-hwe-v144-official-matrix-v1` successor. Failure freezes the exact
owned v142 data volume for audit. No broad Docker cleanup, daemon restart, VPN/proxy change,
downloader interaction, host `LocalRuntime`, registry request, or v132/v138/v140 volume access is
authorized. Provider and ambient Docker variables must be removed from the authorized child
environment without printing, persisting, or hashing their values.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
