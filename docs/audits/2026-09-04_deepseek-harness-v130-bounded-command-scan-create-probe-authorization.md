# DeepSeek Harness v130 bounded command-scan create-probe authorization

Date: 2026-09-04

## Decision

This change authorizes exactly one zero-provider execution of
`deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1`, and only after the implementation
is merged to `origin/main` and that exact merge commit passes all eight Actions classes. The probe
may reproduce only the Ibex PR-465 command image in a fresh `/data2` VFS DinD and repeat its v2
security scan with explicit finite Docker-operation bounds. It cannot publish a provider contract,
run a benchmark candidate or verifier, start Harness, contact a registry, or make a model/provider
request.

The manifest canonical hash is
`c25bd9762befe8a282d9b73be54c4349398f6777dc3a5e5875d8117a09226df2`. Its invocation requires
the exact positive post-merge `main` Actions run ID and the one-use opt-in
`VERIGYM_RUN_DEEPSEEK_HARNESS_V130_BOUNDED_COMMAND_SCAN_CREATE_PROBE=1`. Provider variables,
`DOCKER_HOST`, and `DOCKER_CONTEXT` must be absent at the host boundary.
The authorized runner file SHA-256 is
`cb8287a735ea6d3ea84d794a6e233e555185bc2ce2c53e4debe5277c4d226a0f`.

## Frozen predecessor and task

V130 binds the audited v127 manifest, runner, authorization, report, runtime receipt, PR-465
archive receipt, source lock, failed security scan and nested diagnostic, cleanup receipt, complete
81-directory/281-file evidence inventory, and v128 audit. The v127 terminal report must still show
no scaffold, model, provider request, collection, or training. The frozen v127 data volume is
neither opened nor inspected and remains immutable.

The sole task is `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465`. The completed local archive is
read only from `/data2/jiadongzhu/Agent/hwe-bench-public-images`; its tar SHA-256, sidecar, OCI
manifest digest, config digest, repository base, official verifier image ID, and v69 task lock are
revalidated offline. Registry access and `.partial` archives are forbidden. The audited v127
source/toolchain lock is reused by file hash and canonical lock hash; no source checkout or hidden
verifier asset is placed in the scanner workspace.

## Fresh runtime and bounded scan

The runner creates only these fresh bind-backed Docker volumes:

- `verigym-deepseek-harness-v130-dind-data` backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v130/data`;
- `verigym-deepseek-harness-v130-dind-socket` backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v130/socket`.

It starts the immutable local `docker:23.0.6-dind` image once with outer `network=none`, VFS,
bridge/iptables disabled, and exact `23.0.6`, `vfs`, `runc` readiness. The completed PR-465 archive
is then imported through the explicitly bound nested Unix socket and the task-specific
credential-free, Codex-free Verilator command image is rebuilt with build network `none`. These
steps reconstruct scanner input only; they do not execute the task or official verifier.

The security-scan container is deterministically named
`verigym-hwe-v130-command-scan-pr-465` and carries the exact v130 owner and role labels. Docker
create, each inspect, diagnostic start, deterministic removal, and the monotonic overall scan are
bounded at 300, 60, 180, 120, and 720 seconds. It retains the existing `network=none`, non-root,
read-only root, dropped capabilities, no-new-privileges, resource limits, exact environment, and
single writable workspace mount. A create timeout is a sealed infrastructure result and triggers
name-based cleanup even when no container ID was returned.

Receipts persist no raw Docker output or exceptions and do not hash nonempty diagnostic output.
Success requires the scan and task/image lock to pass and an explicitly bound inner inventory to
contain zero containers and zero volumes after scanner cleanup.

## Cleanup and successor boundary

Cleanup removes only exact v130-owned containers and volumes. A networkless, read-only helper with
only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER` restores the fresh bind paths to the invoking UID/GID and
mode `0700`; cleanup ambiguity fails closed. The runner does not prune Docker, restart the daemon,
alter VPN/proxy state, touch `/data/docker`, access the downloader, or inspect/mutate v71--v127
volumes.

Both a passed and a failed probe consume v130. The result must be independently audited as v131
and that audit must merge and pass a separate post-merge gate before any successor decision.
Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
