# DeepSeek Harness v77 CVA6 source-profile materialization authorization

Date: 2026-09-03

Status: **implementation authorization only**. After this change is merged and the resulting
`main` run passes all eight required workflow classes, exactly one zero-provider execution may
rematerialize the inherited five-task schedule. This does not authorize provider access, formal
collection, SFT export, training, production-readiness work, or task substitution.

## Frozen predecessor and disposition

V76 classified v75 as a pre-provider source-hygiene safety stop. V77 binds the v75 report file
SHA-256 `850f1ba2277abd72609d021a3c5939aab5bb11d35e1198516716cfba2cada16a`,
embedded report hash `0eb7ac52c6577932134dd9bd3518da2c755c0c3409b166ad6b3944fade36a2fe`,
v76 audit file SHA-256
`067cd429d950a9b5d82bdd13921e8711d21cd89cc33428cda8b96c2b337dd794`, and merged audit
commit `cd6d95e39f09104f582bb9d57671aa5edf812933`. The audit commit's post-merge `main` Actions run
`33722953464` passed all eight required job classes.

The bound report is `stopped_without_provider_contract` with
`stop_reason=ConfigurationError`, three completed Ibex tasks, zero provider calls/model
processes, no persisted raw exception, and confirmed socket cleanup. Its partial task receipts
remain evidence only and confer no authorization.

The v75 data volume and `/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/data` remain retired
evidence. They are not reused, reopened, deleted, or pruned. V77 creates fresh
`verigym-deepseek-harness-v77-dind-{data,socket}` volumes backed only by
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/{data,socket}`. It reruns PR-465, PR-1135,
PR-1780, PR-2017, and PR-2711 in order from the original completed local archives. No v75 task
receipt, `.partial` archive, registry access, shared Docker pruning, VPN/proxy change, or downloader
control is permitted.

## Exact source-profile repair

Read-only inspection of the validated PR-2017 archive found the task-image tool bridge
`/home/cva6/.hwe_tools/verilator -> /tools/verilator-v5.008`. The generic source sanitizer
correctly rejected it because the absolute target is outside the extracted repository.

V77 adds exactly `.hwe_tools` to the existing CVA6 repository profile exclusions, before the
generic symlink pass. The exclusion helper accepts only a real directory contained beneath the
repository and deletes it without following child links. The manifest binds profile ID
`hwe-openhwgroup-cva6-v1`, profile hash
`f73cc268c08fbc2b66788e61e882b0f390822185b857fce361e21a849ce2dda5`, repair ID
`cva6-task-image-tool-bridge-exclusion-v1`, and policy `reject-unlisted-v1`.

Regression tests prove that the profile-owned bridge is removed, an absent generated bridge is
accepted, and any unlisted absolute or relative escape still raises `ConfigurationError`. V77
does not allow arbitrary escaping links, copy `/tools` into the workspace, or expose the tool
bridge to the agent. The official verifier image and task-specific command toolchain remain
separately digest-bound.

## Preserved isolation and atomic publication

V77 preserves the successful v75 scanner namespace and socket-cleanup v2 controls. Scanner
workspaces remain below the exact successor output mount, mode `0700`, and must be empty before
execution and after every task. The DinD daemon remains a digest-locked trusted sidecar with
`network=none`, `vfs`, `runc`, no host Docker socket, and only the exact data/socket, output, and
sentinel mounts. Task/verifier execution remains networkless.

All five tasks must reproduce reference-patch compatibility, archive/source/image locks,
base-FAIL/reference-PASS, task-specific command-image builds, v2 scans, empty scanner/inner
inventories, and confirmed socket cleanup. Any failure seals
`stopped_without_provider_contract`; no partial contract is published.

A completed contract remains `provider_execution_authorized=false` and requires a separately
merged v78 result audit followed by an eight-class green post-merge `main` run before any official
DeepSeek matrix authorization can be created.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
