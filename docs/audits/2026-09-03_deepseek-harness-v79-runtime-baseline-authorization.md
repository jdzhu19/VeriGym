# DeepSeek Harness v79 runtime-baseline materialization authorization

Date: 2026-09-03

Status: **implementation authorization only**. After this change is merged and the resulting
`main` run passes all eight required workflow classes, exactly one zero-provider execution may
rematerialize the inherited five-task schedule. This does not authorize provider access, formal
collection, SFT export, training, production-readiness work, or task substitution.

## Frozen predecessor and disposition

V78 classified v77 as a pre-provider runtime-baseline binding safety stop. V79 binds the v77
report file SHA-256
`d284514b6e39fe2b9df6e8e5d1e94e40eee65a73123f5c7e2e08f03be84e4588`, embedded report hash
`22cfb52074b901fddbba3881b2608cc70c897d6c2e7431b8b4be0bd8e508a3a0`, v78 audit file SHA-256
`911cb8075e476bb22f3e22470c1b103d9d85c5d2ff2374667cfd1ab2721828bc`, and merged audit commit
`154733d9b41b9ce5add42e476b0aa3f69d2bc798`. The audit commit's post-merge `main` Actions run
`33728092119` passed all eight required job classes.

The bound report is `stopped_without_provider_contract` with
`stop_reason=ConfigurationError`, three completed Ibex tasks, zero provider calls/model
processes, no persisted raw exception, and confirmed socket cleanup. Its partial task receipts
remain evidence only and confer no authorization. V77 is never retried, resumed, or relabelled.

The v77 data volume and `/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/data` remain retired
evidence. They are not reused, reopened, deleted, or pruned. V79 creates fresh
`verigym-deepseek-harness-v79-dind-{data,socket}` volumes backed only by
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v79/{data,socket}`. It reruns PR-465, PR-1135,
PR-1780, PR-2017, and PR-2711 in order from the original completed local archives. No v77 task
receipt, `.partial` archive, registry access, shared Docker pruning, VPN/proxy change, or downloader
control is permitted.

## Exact runtime-baseline repair

The v69 public task lock correctly freezes PR-2017's dataset base commit as
`90d780eb14bb99624ad9a377b5140f1781647a33`. The digest-locked official verifier image correctly
exposes runtime marker `d87707a81fe8926dda2deff844797a491811983a`. The CVA6 repository profile
uses `digest_locked_runtime_marker`, so the prepared image lock and loaded task source use that
runtime marker while the selected public dataset row retains the dataset base.

V79 changes no dataset record and grants no general drift tolerance. Its manifest contains one
and only one runtime override:

```text
hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017
  dataset base: 90d780eb14bb99624ad9a377b5140f1781647a33
  runtime base: d87707a81fe8926dda2deff844797a491811983a
```

The override is additionally bound to the frozen v77 prepared source image-lock file SHA-256
`b3162d87d83dd9bb9a5958a696c8b8c1a1d9858a92b43c658866ac356ee1513d`, source hash
`b2eaaf632ae46acf9406791df199ffdbe1d5000edb22b8afdc193cceefd6a6f7`, task-bundle hash
`fe1073d1f55065ca514599da45c55753ab89d9eafec7d6afaf5bcc76bc5d9fbd`, official image ID,
registry manifest digest, and repository profile hash. Missing, additional, or changed overrides
fail closed.

Every task without that exact override must have `runtime_base_commit == dataset_base_commit`.
Independent offline inspection of PR-2711 reproduced archive receipt hash
`ddd4e9f5bbb4d08aec204f8e285d4a00eaf59ccd8793ec31bb589e4d245a48bd`, with no registry access or
partial archive use, and its runtime marker equals dataset base
`5518a41c08a1949c606d54b9ac631e8f7635e7f3`.

The historical v69 materializer keeps its default source-binding behavior. V79 supplies a narrow
callback for its own task preparation, validates the selected dataset row and runtime image lock
separately, and writes both identities plus the override decision into each canonical task
receipt. Atomic contract publication revalidates the task receipt hash and every runtime field.

## Preserved isolation and atomic publication

The audited v77 CVA6 source-profile repair remains unchanged: only `.hwe_tools` is removed before
the generic symlink pass, while every unlisted escaping link remains terminal. The manifest keeps
profile ID `hwe-openhwgroup-cva6-v1`, profile hash
`f73cc268c08fbc2b66788e61e882b0f390822185b857fce361e21a849ce2dda5`, and policy
`reject-unlisted-v1`.

V79 preserves the scanner namespace and socket-cleanup v2 controls. Scanner workspaces remain
below the exact successor output mount, mode `0700`, and must be empty before execution and after
every task. The digest-locked DinD sidecar remains `network=none`, `vfs`, and `runc`, with no host
Docker socket and only the exact data/socket, output, and sentinel mounts. Task and verifier
execution remain networkless.

All five tasks must reproduce reference-patch compatibility, archive/source/image locks,
base-FAIL/reference-PASS, task-specific command-image builds, v2 scans, empty scanner/inner
inventories, and confirmed socket cleanup. Any failure seals
`stopped_without_provider_contract`; no partial contract is published.

A completed contract remains `provider_execution_authorized=false` and requires a separately
merged v80 result audit followed by an eight-class green post-merge `main` run before any official
DeepSeek matrix authorization can be created.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
