# DeepSeek Harness v75 scanner-path DinD materialization authorization

Date: 2026-09-03

Status: **implementation authorization only**. After this change is merged and the resulting
`main` run passes all eight required workflow classes, exactly one zero-provider execution may
rematerialize the inherited five-task schedule. This does not authorize provider access, formal
collection, SFT export, training, production-readiness work, or task substitution.

## Frozen predecessor and disposition

V74 classified v73 as a pre-provider infrastructure/security failure. V75 binds the v73 report
file SHA-256 `659b5a0de53facc49cdd9ab8ce68de05f39e0257548010b5a184fc2ecf400d97`,
embedded report hash `5c135eaa11f850bc1c707312d06521b9dc42312a19d72937584576110b17fdde`,
v74 audit file SHA-256
`202ceb1bca32f941b7f2a17a4887e2c8dfb7bde43ac17305ad0b7fc9d9eb4e19`, and merged audit
commit `25392d1e7c60cbdcebcbeff17a4c40fb5ff13242`.
The bound report is `stopped_without_provider_contract` with `stop_reason=RuntimeError`, zero
completed tasks/provider calls/model processes, and unconfirmed in-run socket cleanup.

The v73 data volume and `/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/data` remain retired
evidence. They are not reused, reopened, deleted, or pruned. V75 creates fresh
`verigym-deepseek-harness-v75-dind-{data,socket}` volumes backed only by
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/{data,socket}`. It reruns PR-465, PR-1135,
PR-1780, PR-2017, and PR-2711 in order from the original completed local archives. No v73 task
receipt, `.partial` archive, registry access, shared Docker pruning, VPN/proxy change, or downloader
control is permitted.

## Corrected scanner namespace boundary

V73 placed the command-image scanner bind source outside the only same-path directory visible to
the trusted DinD sidecar. V75 adds an explicit scanner scratch argument while preserving the
historical default for all earlier callers. The v75 runner alone creates owner-only
`scan-workspaces` below its new output root and passes that absolute, nonsymlink path into every
task scan. The output root is already the sidecar's sole writable same-path task mount, so the
inner daemon can resolve the bind source without mounting the shared scratch tree.

Each scanner workspace remains temporary and is removed by the scanner on success or failure.
V75 checks that the parent is empty before execution and after every task. Contract publication
also records `scanner_workspace_policy=successor-output-root-only-v1` and requires confirmed
scanner-workspace cleanup.

The socket cleanup allowlist is advanced to `networkless-readonly-fixed-path-v2` and now includes
`/verigym-socket/runc` in addition to the prior Docker socket, PID, containerd, Docker runtime, and
xtables paths. The cleanup container remains networkless, read-only-root, single-mount, and limited
to `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`; success still requires removal of the socket volume plus
host verification of an empty mode-`0700` UID:GID-owned backing.

## Atomic publication

V75 uses the original v69 manifest and all five original archive/source/verifier locks. It must
reproduce reference-patch compatibility, base-FAIL/reference-PASS, task-specific command-image
build and v2 scan, empty inner inventory, and both scanner/socket cleanup. Any failure seals
`stopped_without_provider_contract`; no partial contract is published.

A completed contract remains `provider_execution_authorized=false` and requires a separately
merged v76 result audit followed by an eight-class green post-merge `main` run before a new
official-matrix authorization can be created.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
