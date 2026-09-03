# DeepSeek Harness v73 clean-room DinD materialization authorization

Date: 2026-09-03

Status: **implementation authorization only**. After this change is merged and its post-merge
`main` run passes all eight required workflow classes, exactly one zero-provider execution may
rematerialize the inherited five-task schedule. This does not authorize a provider call, formal
collection, SFT export, training, production-readiness work, or task substitution.

## Frozen predecessor and schedule

V72 independently classified v71 as a pre-provider infrastructure/security failure. V73 binds the
v71 report file SHA-256
`486f486fc730e6b58767c9b8bcfa460afead5f0834ce1750895b0bb7b83b50ab`, embedded report hash
`4f12e20da48abc2ffce048194519c8afb3c973796ed60e661c245815b0dc47c8`, v72 audit file SHA-256
`3835f86bc03ca1d870a8478939c8ecbd8772c60784e7998aa3b2f2e01ad54be7`, and merged audit commit
`fcc80a6f6ed45d4f0e424bf5781fe3a0ef493643`.

The v71 data volume and `/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data` backing remain
retired evidence and are not reused, reopened, deleted, or pruned. V73 reuses no v71 task receipt.
It reruns PR-465, PR-1135, PR-1780, PR-2017, and PR-2711 in that order from the original completed
local archives and rechecks patch compatibility, archive/config/repository/source identities,
base-FAIL/reference-PASS, and command-image security. No `.partial` archive or registry is allowed.

## Fresh storage and corrected controls

The frozen local `docker:23.0.6-dind` image identity is unchanged, but v73 creates new data and
socket volumes bound only to `/data2/jiadongzhu/docker/deepseek-harness-hwe-v73/{data,socket}`.
Only the trusted outer DinD sidecar is privileged. It remains networkless, has no host Docker
socket, uses `vfs` and `runc`, and mounts only the v73 output, sentinel, data, and socket paths.
The shared `/data/docker` daemon root is not reconfigured, restarted, pruned, or used for task
layers. VPN/proxy state and the user-owned downloader remain untouched.

V73 replaces the ambiguous v69 build-command boundary with a 32 MiB-per-stream content-free
diagnostic. The runner records exit code, timeout state, stdout/stderr byte counts and SHA-256
digests, but no raw output. A successful command may have nonempty output; nonzero exit, timeout,
or over-limit output fails closed before the command-image scan.

After the inner runtime inventory is empty and the sidecar is removed, a dedicated cleanup
container mounts only the exact v73 socket volume. It uses `network=none`, a read-only root,
`cap-drop=ALL`, and adds only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER` to remove the fixed DinD
socket/PID/runtime paths and restore the directory identity. The runner then removes the volume
and verifies on the host that the backing is empty, mode `0700`, and owned by the invoking user.
Outer container or volume removal alone is never accepted as cleanup evidence.

## Atomic publication

Progress and failed cleanup diagnostics are non-authoritative. `provider-contract.json` is written
only after all five task receipts, their content-free command diagnostics, empty inner runtime
inventory, sidecar removal, hashed cleanup receipt, and persistent data-volume binding all pass.
Any failure seals `stopped_without_provider_contract`; no partial schedule is authorized.

A completed v73 contract still states `provider_execution_authorized=false` and requires an
independent v74 audit plus post-merge eight-class green `main` before any official DeepSeek matrix
authorization can be created.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
