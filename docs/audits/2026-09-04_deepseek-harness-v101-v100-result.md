# DeepSeek Harness v101 audit of the v100 inventory-timeout scaffold

Date: 2026-09-04

## Decision

The one authorized `deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1` execution is
validly closed as a pre-provider infrastructure stop. It published no execution-scaffold
contract, started no model process or provider request, and consumed no provider call. The v100
identity and retained data volume are frozen and must not be retried, reopened, imported, or
promoted.

V100 completed the isolated runtime transfer and reproduced base-FAIL/reference-PASS for Ibex
PR-465. It then stopped while inspecting that task's bounded, network-disabled
toolchain-inventory container. The failure was caused by a v100 wrapper regression: it applied
the 4,096-byte generic command-output bound to `docker container inspect`, replacing the
1-MiB bound in the audited v69 implementation. This is an infrastructure implementation failure,
not a task, patch, verifier, capacity, or security rejection.

Because v100 did not atomically publish its prerequisite contract, the conditionally reserved
v102 provider identity is retired unused. A repair must use a new zero-provider identity, a
fresh `/data2` DinD data volume, and a later separately authorized provider identity.

## Authorization and execution identity

- v100 authorization merge: `c264d75ebacba0eeabaf8bc5f180214ff60c198a`
- v100 post-merge `main` run: `33786512313`, all eight required check classes passed
- manifest file SHA-256:
  `f9e59ff5b82b81e3dc1d89ad4a0daad55952815e6221e0180cf2410736bc14d5`
- manifest canonical hash:
  `617aa02631333d7347ddfb54fde9f34f8554098ec003a229158d65cb2d33dfbe`
- runner SHA-256:
  `72bbe820877dcaa7fa69eb052be2adf8e1796e2deffd88b5cbb712dc0b383945`
- authorization document SHA-256:
  `8a120d302f3f58c6adebaabe2a56fb2c44835df39a050637b02f08fdf9272663`
- source commit recorded by the result:
  `c264d75ebacba0eeabaf8bc5f180214ff60c198a`
- audited predecessor: v98 merge
  `a766cc9d564f89c96170b1e451852e29e107388e`, post-merge run `33782913003`
- predecessor v97 report hash:
  `6000435cb3f439cb206666dc06c55332e02d8a85cd688eb5e055537274f67f18`

## Result integrity

The result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v100-inventory-timeout-scaffold-v1`.
It contains 277 regular files totaling 2,514,532 bytes and no symbolic link. The report and
progress file are byte-identical. Every embedded canonical hash below recomputes exactly:

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `execution-scaffold-report.json` | `a74be75ef863c77130fdcf5bea5bf1001348bf70e7127202bae1c46bed293d6b` | `9aa3c4716f528429040ff95aa6e12d1da780543c26ad3fab6dce9f2672724b22` |
| `execution-scaffold-progress.json` | `a74be75ef863c77130fdcf5bea5bf1001348bf70e7127202bae1c46bed293d6b` | `9aa3c4716f528429040ff95aa6e12d1da780543c26ad3fab6dce9f2672724b22` |
| `dind-cleanup-receipt.json` | `a674c144c44ab73467f896b6fa71982cfcc777ac631557e1a3c39e384504b6cd` | `92acc49c591e2f0613a35087b9d7fc97e12674de59ba7e25d743a979687fe81f` |
| `dind-runtime-receipt.json` | `c3e83088a993482f5e6b73372f4b23d598cde78b255bf1f2615298646af7c558` | `6a45bddbaabddab9cc63ac649e93ca402a4ccae7fcd491079a9d8e011ac0d781` |
| `headroom-preflight.json` | `34963e1e057b7339d1f86929c1e7fd02cf34b8e428be430849c190aa50f926a4` | `e1ac2a4eb483c734a9d8f12f0d9eab1bbdcf132d5dd446606108f999957c4b08` |
| `image-transfer-set.json` | `6107d298e6e8f83c6ce0f7438eea586bb9a8d45c65906c6446cde7d59f6398b9` | `d8a8393eff90f12a15c679bca99c39c3cd1eccbc4fd51901b05d03b41a2590d7` |
| `qualification/pr-465/smoke-report.json` | `f31aef682ef74774205da019fefa70327f13af028e00b4a88038432c49b70f0e` | n/a |
| `sources/pr-465/image-lock.json` | `cd89cd593ea6989ca50e20260720d63e468f68e98572636e1890d8b90d2a21b3` | n/a |

The report records status `stopped_without_execution_scaffold`, reason `ConfigurationError`,
and only the completed stage `controller_and_workspace_runtime_transferred`. It also records
`provider_execution_authorized=false`, `provider_execution_scaffold_published=false`,
`provider_request_started=false`, zero provider calls, and zero model processes. No
`execution-scaffold-contract.json` exists.

## Partial qualification evidence

Ibex PR-465 passed patch compatibility, archive validation, source/image locking, and its
zero-model smoke qualification. Its base failed the hidden regression without an infrastructure
error, while the reference patch passed. The fixed official verifier image remained
`sha256:d0d2c8a6391c3c35a2fc2e6e310786d65d0f0c4c9f08f6fcec5098d0be34c410`.

The run stopped before PR-465 could publish a fresh command-image lock, toolchain inventory,
security scan, or task receipt. PR-1135, PR-1780, PR-2017, and PR-2711 completed only static patch
compatibility. Therefore none of the five tasks is contract-admissible, and the atomic
publication gate correctly remained closed.

## Root cause and repair boundary

The PR-465 toolchain container was successfully created with `--pull never`, network `none`, a
read-only root, a non-root user, dropped capabilities, bounded CPU/memory/PIDs, and an allowlisted
`sha256sum` entrypoint. V100 then called its replacement `_inventory_docker_inspect`. That wrapper
allowed at most `v69._MAX_CONTROL_OUTPUT`, which is 4,096 bytes. The original audited
`v69._docker_inspect` permits up to 1 MiB. The immutable PR-465 archive's image config alone is
5,953 bytes, before Docker adds the container inspection envelope, so a valid response
necessarily violated the accidental v100 limit. The `finally` path removed the inventory
container before the outer DinD cleanup completed.

A successor must keep the 300-second inspect timeout but restore the dedicated 1-MiB inspect
output bound. Regression tests must accept valid inspect JSON above 4 KiB and at or below 1 MiB,
while rejecting nonzero exit, nonempty stderr, oversized, malformed, and multi-record responses.
Timeout and cleanup behavior must remain fail-closed. All five tasks must be rematerialized from
completed local archives; no partial v100 result may enter a successor contract.

## Cleanup, storage, and credential boundary

- No v100 campaign container remains.
- The socket volume is absent. Its backing directory is empty, owner-only, and restored to
  UID/GID `1004:100`.
- The retained data volume is a local-driver bind volume with exact device
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v100/data`. It is frozen as audit evidence only.
- The runtime receipt proves the host and inner data roots shared inode `64770:682230408`, the
  outer DinD daemon used network `none`, and host `/data/docker` was not used for task layers.
- An independent in-memory scan compared all four live nonempty provider values against all 277
  regular evidence files: zero matches. Values were not printed, persisted, or hashed.
- No registry, partial archive, VPN/proxy change, host-Docker prune, or second downloader was used.

## Successor boundary

V101 authorizes no provider access and no execution by itself. After this audit is merged and its
post-merge `main` commit passes all eight Actions classes, a new zero-provider repair may be
implemented under unused identity v103 with fresh paths rooted at
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v103`. V100 and all earlier volumes remain closed.

A successful v103 result requires an independent v104 audit before any provider matrix is
authorized. That provider matrix must use a later unused identity; v102 remains retired.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks, research trajectories,
or authorized imports. Failed context is audit-only. The following remain false:
`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready`.
