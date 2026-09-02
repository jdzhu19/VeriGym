# OpenHands v52 / v23 zero-provider materialization stopped

Date: 2026-09-02

Status: **frozen pre-provider infrastructure failure**. V52 may not be retried, resumed,
reconstructed, or relabelled. No provider canary, formal collection, SFT export, or training was
started.

## Authorization and execution boundary

PR #85 merged the v23 implementation and v52 authorization as
`b981e26aa75307e431c10033c8b70c77e2ddb672`. Its pull-request checks passed both push and PR
copies of the eight required job classes. The post-merge `main` Actions run `33581474941` then
passed the same eight classes before v52 was opened.

The one authorized command ran from that exact clean tracked `main`. Before execution, the v52
output and failure paths, the PR-2728 host tag, the digest sentinel, and v52 temporary containers
were absent. The official dataset, pinned crane and ripgrep artifacts, sealed v33 PR-3204 inputs,
`verigym-hwe-net`, and Docker daemon all passed the runner's frozen checks. Provider credential
variables were removed from the process environment without printing, persisting, or hashing
their values.

The authorization hash was
`20a504cb526c0eb45083ce1daf69debd78dafef8a7f6b330d8a0b40e5dc62bcc`.
The run used only the authorized zero-provider path. Provider calls and model processes remained
zero.

## Exact stop boundary

The runner resolved the candidate digest and config in isolated containers, then entered
`pr2728_image_transfer` / `candidate_pull`. The single pinned `crane pull` process ran in one
container on `verigym-hwe-net`; no application retry or alternate transport was attempted. It
exited 1, and Docker's retained event metadata independently records that exit code and the
`candidate_pull` role. The runner then failed closed.

The frozen, content-free failure receipt records:

- identity: `openhands-hwe-v52-v23-canary-materialization-v1`;
- status: `frozen_zero_provider_materialization_failed`;
- failure stage and type: `pr2728_image_transfer` / `_CommandFailure`;
- redacted command stage and family: `candidate_pull` / `unknown`;
- temporary stderr: 393 bytes with SHA-256
  `c2ab92d2c3c6f4c06785b8c598537855a951fcbf34d8fb05fd04c7d588bc33da`;
- raw stderr persisted: false;
- output and canary contract published: false;
- provider calls and model processes: zero; and
- formal collection, collection, training, and production readiness: false.

The failure receipt is 1 file with SHA-256
`92bc1d36da3a4619acb0703c10f9df4215a5457d475ae46cf0c5b4ea9af33afa` and canonical receipt
hash `7ab138d0e144c23f7a9809f0d4573f1c9da336ad23b57f868186b6930d80e171`.
It is frozen outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v52-v23-canary-materialization-v1.failure.json`.

The atomic output directory is absent. The candidate and sentinel images are absent, no v52
temporary container remains, and no task staging directory remains. The fixed persistent cache
contains zero promoted layer blobs. No source workspace was created, no verifier was executed,
and PR-2728 still has no benchmark disposition.

## Diagnosis and successor requirement

The allowlisted `unknown` family is the strongest conclusion supported by the retained receipt.
The raw diagnostic was intentionally ephemeral, so this audit does not infer a registry,
transport, cache, disk, or tar-writer cause from its length or hash.

Code inspection does identify a separate, deterministic successor defect. V52 mounted a fixed
persistent cache root but downloaded all layers into task staging and invoked
`promote_task_staging` only after the complete multi-layer `crane pull` returned success. On the
failure path, the `finally` cleanup removed the staging directory before any individually complete
layer could be validated and atomically promoted. The persistent cache therefore could not carry
verified progress across a failed identity. This falls short of the intended failure-resilient
content-addressed cache even though it preserved the no-partial-publication boundary.

The pinned crane's official [`blob` command documentation](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_blob.md)
defines a single registry blob read, while the official
[`crane` recipes](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/recipes.md)
describe obtaining a platform-specific image manifest and its layer sizes with
`crane manifest --platform`. A successor may use those pinned primitives to:

1. resolve and freeze the Linux/amd64 manifest before downloading content;
2. download each bounded manifest layer to task-specific staging exactly once;
3. validate the declared size and SHA-256 before atomically renaming it into the fixed digest
   cache;
4. seed a private assembly cache from those verified immutable blobs; and
5. assemble and independently validate the Docker tar without redownloading layer content.

Each layer command must remain zero-retry at the runner level. A failed successor freezes, but all
layers already validated and published before that failure may be reused by a later, separately
authorized identity. Raw output remains temporary and public receipts remain bounded to digest,
size, cache-hit, stage, error family, byte count, and hash.

## Next gate

This stopped audit must merge and its post-merge `main` run must pass all eight job classes before
a v53 successor implementation or authorization may run. V53 must have a new identity and bind
the exact v52 failure receipt. It may perform zero-provider materialization only; provider access
still requires a later, separately merged authorization and result audit.

The OpenHands behavior-failure count remains zero because the failure happened before provider
access, source preparation, verifier execution, trajectory construction, or SFT admission.
