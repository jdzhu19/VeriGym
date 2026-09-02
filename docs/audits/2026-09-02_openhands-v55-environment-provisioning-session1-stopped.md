# OpenHands v55 PR-2728 environment-provisioning session 1 stopped audit

Date: 2026-09-02

Status: **session 1 stopped after three bounded failures of the same registry stream**. The
environment identity remains resumable, but session 2 was not run. No task qualification,
provider canary, formal collection, SFT export, or training was authorized or started.

## Merged-main execution gate

PR [#91](https://github.com/jdzhu19/VeriGym/pull/91) merged the v55 environment-provisioning
authorization as `63678ebd465b623f30b1f16c84228818aa6ceee2`. Its independent post-merge
`main` Actions run
[`33594103024`](https://github.com/jdzhu19/VeriGym/actions/runs/33594103024) passed all eight
required job classes before session 1 began.

The invocation used authorization hash
`7a08a0c5d39c3e12b82a6003267f26f248583a332d6c8d54290dc6cd8f8ca1f6`, explicitly
removed all five allowlisted provider credential variables, and enabled only
`VERIGYM_PROVISION_OPENHANDS_HWE_V55_PR2728_ENVIRONMENT=1`. Preflight confirmed a non-root host
identity, the clean merged `origin/main` commit, the dedicated `verigym-hwe-net` bridge, the exact
v54 failure receipt, all 15 inherited cache entries, an absent PR-2728 image tag, an absent v55
manifest, and an empty session journal.

## Result and new diagnosis

Digest, manifest, and config resolution completed. The runner reused all 15 verified layers
totaling 774,127,158 bytes. The remaining manifest layer was:

- digest: `sha256:7e1d7d9f7d00f70045cfc814abf0f91600950f822d0f5e067851d4e438b32eb6`
- size: 1,996,197,226 bytes
- cache state after session: absent

The three bounded `crane blob` attempts all failed. Each temporary stderr stream was 192 bytes
with SHA-256
`3b1989f565aa82c8afc920e54e89f22692e8bfb6cf59d62e5fcd52ad5f8e5409`. The v2
classifier mapped all three to `error_family=transport`, `reason=stream_error`, and
`retryable=true`. Raw stderr was neither printed by the runner nor persisted.

This is the same byte count and hash recorded as `unknown` by v53 and v54. V55 therefore achieved
the intended diagnostic improvement: the repeated failure is now attributable to a registry
stream interruption while transferring one approximately 1.86 GiB layer. It remains a
provider-before infrastructure condition, not an OpenHands decision, trajectory, verifier, or
benchmark result.

## Evidence and cleanup

The append-only session receipt is
`/data/jzhu484/Agent/experiments/openhands-hwe-v55-pr2728-environment-v1.attempts/session-01.failure.json`.
Its file SHA-256 is
`3736d1d04473456b4a5ffbab8ae435ef811d4f5f36efa1866a26b718c65a4904`, and its canonical
receipt hash is `c8134934b82ee495ca3f864c5764b75b3c08086731561306584f9fca146035c9`.
Independent recalculation confirmed both hashes and the bounded layer accounting.

Post-session read-only checks confirmed:

- exactly the 15 inherited content-addressed blobs remain verified in the persistent cache;
- the 1,996,197,226-byte layer has no persistent cache publication;
- no v55 task-specific staging directory or labeled container remains;
- neither the PR-2728 candidate tag nor an environment manifest exists;
- `session_resumable=true`, but no session 2 receipt exists; and
- `provider_calls=0`, `model_process_count=0`, `provider_task_identity_allocated=false`, and
  `benchmark_task_consumed=false`.

The traceback exposed only the controlled stage name and exception type. It did not contain raw
registry output, a credential, a proxy value, or a provider response.

## Disposition and next boundary

Session 1 is immutable and must not be rerun. The v55 environment identity is not frozen: the
authorization permits session 2 because the final closed diagnostic is retryable. Session 2 was
intentionally not started during this audit.

Three identical failures inside v55, on top of identical v53 and v54 fingerprints, show that a
second session using the same whole-layer `crane blob` transfer would add little diagnostic value.
The next implementation decision should be made before spending another long transfer window:
either explicitly consume the already-authorized session 2, or authorize a digest-verified
range/chunk-resumable supplier for this single large layer. Any supplier change must preserve the
manifest-bound final size and SHA-256, task staging, atomic cache publication, redacted diagnostics,
dedicated transfer network, zero provider calls, and the separation from qualification.

OpenHands remains the primary behavior route because no v51--v55 attempt has reached a provider in
this sequence and the behavior-failure count remains zero. Harness fallback conditions are still
not triggered. A later successful environment manifest would still require a separate
qualification/security/lock authorization before any v23 canary contract can exist.

All readiness booleans remain false:

- `formal_collection_allowed=false`
- `formal_collection_started=false`
- `collection_started=false`
- `training_started=false`
- `production_training_ready=false`
