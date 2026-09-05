# DeepSeek Harness v180 outer-DinD mount repair authorization

Date: 2026-09-06

## Decision

Authorize one zero-provider invocation of
`deepseek-harness-hwe-v180-dind-mount-repair-qualification-v1` only after this implementation is
merged to `main` and all eight post-merge workflow classes pass. V180 may retry the reserved Ibex
PR-1816 open-toolchain qualification; it authorizes no model process, provider call, trajectory,
collection, SFT import or mixing, training, GPU work, benchmark-score claim, or production state.

V178 is frozen and must not be retried or relabeled. Its exact six-file result tree, sealed report,
v179 audit, audit merge `d2cd61dd8e9152a99b7ab49015abf6b8c090002f`, and successful post-merge
`main` run `33989708246` are immutable predecessors. The v180 manifest hash is
`84944af9c15919cba6043e6d8eea76174e2bc0728487cc922768c8c1524c0115`; the final Dockerfile
SHA-256 is `aa86ed13a05bdd5b9f1a15022dbacdac7a4285b61b7fe9a0577d5a7cb7743daa`.

## Exact repair boundary

The v179 authorization paragraph described all three outer bind mounts as changing from a bare
`rw` field. This successor records the exact command-level correction: only the output and scratch
bind mounts carried the rejected trailing `,rw` field. V180 omits that field from those two mounts,
leaving them writable by Docker's default. The third bind mount is the host-sentinel mount; it
already used the accepted trailing `,readonly` field and remains byte-for-byte unchanged. The two
named DinD volume arguments retain their accepted `:rw` suffixes.

This clarification does not alter the immutable v179 audit or its finding. The installed Docker
CLI rejected v178 before creating a container with
`invalid field 'rw' must be a key=value pair`; the category remains
`invalid_mount_write_flag`. The v180 runner binds the exact v178 and v172 runner hashes and exposes
the repaired command as a pure function so the two writable bind forms, the one read-only form,
and both named-volume forms are regression tested.

After start, the runner must inspect exactly five mounts and require:

- named volumes at `/var/run` and `/var/lib/docker`, both writable and bound to the fresh v180
  volume names;
- same-path output and scratch bind mounts with exact host sources and `RW=true`;
- the exact empty host-sentinel source at `/verigym-host-sentinel` with `RW=false`;
- no host `/var/run/docker.sock`, no extra mount, outer `network=none`, privileged DinD, exact
  owner/role labels, and no provider or proxy environment name.

The inner daemon must still match the frozen server version, VFS storage driver, default runtime,
image ID, repository digest, and `linux/amd64` platform.

## Unchanged inputs and qualification gates

V180 reuses the v178 immutable dependency-only builder archive under `/data2`, including its
sidecar, eleven-member inventory, config/image ID, two ordered rootfs layers, canonical history,
package inventory, and six build-tool hashes and versions. It reuses the completed HWE archive,
accepted Icarus/Yosys image, Verilator and ripgrep source archives, PR-1816 source and patch locks,
and official verifier image. The final Dockerfile differs from v178 only in its fresh inner
builder tag, `v180-builder`.

All outer, build, builder-probe, agent-command, and official-verifier networks remain `none`.
Registry access, downloads, partial archives, VPN/proxy changes, default-bridge changes, host EDA
fallbacks, HWE-tool inheritance, provider clients, credentials, Codex, and `LocalRuntime` remain
forbidden. The builder probe remains non-root, read-only, mount-free, cap-drop `ALL`,
no-new-privileges, and resource bounded.

The atomic qualification contract requires the open agent-only and digest-locked official routes
to independently reproduce base-FAIL/reference-PASS, plus exact source/image/toolchain locks, the
v2 scan, role separation, empty inner inventory, and complete outer cleanup. Any failure publishes
no partial contract and does not authorize a successor canary.

## Cleanup and successor boundary

V180 uses only fresh output, scratch, backing, volume, container, builder-tag, final-image, receipt,
and report identities under `/data2`. Failure removes all transient v180 resources while retaining
the frozen input archives and owner-only result evidence. Success may retain only the purpose-bound
DinD data volume with reopen budget one.

A successful v180 result requires an independent v181 audit, merge, and eight green post-merge
`main` workflow classes. Only then may a separately versioned v182 PR-1816 research-only canary
with seed/sample `503/19` be considered. It is not authorized here, and its data may never be
automatically mixed with official-route candidate SFT data.

All formal and training flags remain false:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`;
- `production_training_ready=false`.

## Invocation

After merge and the new green post-merge gate, invoke exactly once:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V180_DIND_MOUNT_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v180_dind_mount_repair.py \
  --post-merge-main-run-id <successful-v180-main-run-id>
```

The launcher removes every provider configuration name and both ambient Docker endpoint names
without reading or emitting their values. A different manifest, output, archive root, source
commit, branch, Docker endpoint, untracked inventory, preexisting v180 resource, or non-new main
run ID fails closed.
