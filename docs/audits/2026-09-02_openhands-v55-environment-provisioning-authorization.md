# OpenHands v55 PR-2728 environment-provisioning authorization

Date: 2026-09-02

Status: **authorized in code, pending merge and post-merge `main` verification**. This document does
not authorize public qualification, a provider canary, formal collection, SFT export, or training.

## Disposition of the v54 stop

V54 remains permanently frozen. Its provider-free `layer_015` failure receipt is bound by file
SHA-256 `0d43725b76d25386b90f380f787d929f77533cfdfa777bdb2fdce6a5d65066f9` and canonical
receipt hash `44ff66090d4559ccb66037b68d3b8742c2fe483fcde1dbef4e693b1f9f1f1013`.
The receipt contains 15 verified cache hits totaling 774,127,158 bytes, no published output, no
provider call, and no model process. The v54 stopped audit merged as
`e978cc503e232c8d86c244619d211157f9e288be`; post-merge `main` run `33590506108` passed all
eight required job classes.

The v51--v54 one-shot protocols and receipts are not modified or reinterpreted. V55 changes where
registry transfer reliability is handled: environment provisioning is now a separate phase before
public task qualification and before any provider task identity exists.

## Authorized v55 scope

Authorization
`configs/training/qwen35_hwe_openhands_v55_environment_provisioning_v1.json` has identity
`openhands-hwe-v55-pr2728-environment-provisioning-v1`, environment identity
`hwe-cva6-pr2728-linux-amd64-command-environment-v1`, and authorization hash
`7a08a0c5d39c3e12b82a6003267f26f248583a332d6c8d54290dc6cd8f8ca1f6`.

It permits only:

1. resolving the frozen `linux/amd64` PR-2728 registry manifest;
2. downloading missing layers into task-specific staging;
3. validating every layer's manifest-bound size and SHA-256 before atomic cache publication;
4. assembling and importing the image only from the complete verified cache; and
5. atomically publishing an environment manifest pending separate public qualification.

It explicitly does not allocate a model, seed, sample, campaign, agent version, or provider task
identity. It does not run base/reference qualification, the v2 command-image scanner, command-image
locking, PR-3204 validation lock checks, a canary, collection, export, or training. PR-2728 receives
no benchmark disposition and is not consumed by provisioning.

## Bounded resume and diagnostics

A cache miss permits at most three layer attempts. Only DNS, timeout, connection/stream
interruption, selected transient HTTP statuses (408, 425, 429, 500, 502, 503, 504), and
task-staged size/checksum mismatch are retryable. A partial staged layer is removed before another
attempt. TLS, permission, disk-full, archive, persistent-cache corruption, unknown, and policy
failures do not retry.

The same environment identity permits at most three sequential provisioning sessions. A failed
session writes one append-only receipt and may advance only when its final safe diagnostic is
retryable. This is an environment download resume, not a provider or whole-episode retry. Provider
retry count remains zero.

Raw stderr is temporary and retains the 32 MiB command bound. Persistent diagnostics contain only
an allowlisted family/reason, optional allowlisted HTTP status, retryability, byte count, SHA-256,
and `raw_stderr_persisted=false`. Successful manifests contain bounded per-layer cache and attempt
facts. No raw registry output, path, endpoint, proxy value, or credential is persisted.

## Atomicity and next gate

Verified content-addressed cache entries survive a failed session; task staging, controlled
containers, transfer work directories, and temporary archives are cleaned. The existing single
archive owner remains responsible for exactly one cleanup. No partial environment manifest is
published on failure.

The provisioning CLI refuses root, provider credential variables, unmerged files, a dirty tracked
tree, a non-`origin/main` commit, altered v54 evidence, altered cache entries, an out-of-order
session journal, or an output path outside `/data/jzhu484/Agent/experiments`.

One real v55 session may run only after this authorization is merged and its post-merge `main`
workflow passes all eight required classes. A successful environment manifest still requires a
new zero-provider qualification/security/lock authorization before any v23 provider canary can be
materialized. A future provider identity begins at v56; v55 itself never authorizes provider use.

All readiness booleans remain false:

- `formal_collection_allowed=false`
- `formal_collection_started=false`
- `collection_started=false`
- `training_started=false`
- `production_training_ready=false`

## Credential-free local verification

The pre-merge tree passed:

- Ruff checks and format checks over all tracked Python files plus the new v55 files;
- core strict mypy over 209 source files;
- core pytest: 1,095 passed, 1 skipped, 52 deselected;
- HWE-Bench plugin: 52 passed and strict mypy over 9 source files;
- DeepSeek Harness plugin: 14 passed and strict mypy over 7 source files;
- OpenHands plugin: 585 passed, 66 artifact-dependent tests skipped, and Python 3.12 strict
  mypy; and
- targeted v53/v54/v55 transfer and authorization regressions: 43 passed.

The repository contains user-owned untracked experiment and document paths. Full-tree Ruff would
inspect those private untracked files, so local verification used the exact tracked inventory plus
the new v55 paths. CI receives only committed paths and therefore runs the ordinary full-tree
commands without that local-workspace interference.
