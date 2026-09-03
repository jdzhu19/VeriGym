# DeepSeek Harness v98 audit of the v97 rebuild-identity scaffold

Date: 2026-09-04

## Decision

The one authorized `deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1` execution is
validly closed as a pre-provider infrastructure stop. It published no execution scaffold,
started no model process or provider request, and consumed no provider call. The v97 identity
and retained data volume are frozen and must not be retried or reopened.

V97 repaired the invalid historical image-ID equality gate: Ibex PR-465, PR-1135, and PR-1780
each reproduced the required base-FAIL/reference-PASS qualification, passed the complete v2
security scan, and accepted a newly materialized command-image identity. The run stopped while
creating the bounded, network-disabled toolchain-inventory container for CVA6 PR-2017. The
30-second Docker-create bound expired before that task could publish an image lock. This is an
infrastructure timeout, not a task or verifier rejection.

Because v97 did not atomically publish the prerequisite contract, its reserved v99 official
matrix identity is retired unused. A repair must use a new scaffold identity, a fresh `/data2`
DinD data volume, and a later separately authorized provider identity.

## Authorization and execution identity

- v97 authorization merge: `1444ad6e357bca896d31cfb72483f9def2d96f37`
- v97 post-merge `main` run: `33778996841`, all eight required check classes passed
- manifest file SHA-256:
  `8d08ff7ffdf687fd2408c96b99b167e775043d5dd9d052c2197d4da07b4d402c`
- manifest canonical hash:
  `7bb335f8f6418b6cd4d5e315db67060672b8fc4d3d47b1cc68f3b8a7d5e94cc7`
- runner SHA-256:
  `bc7e7ed3180d580b692f410710491ca60cbf23399151064ec50c54ca3d380e14`
- authorization document SHA-256:
  `1667e97f225f2338f54a9162f64a417abdbefc3383c1be4ea581e23138667065`
- source commit recorded by the result:
  `1444ad6e357bca896d31cfb72483f9def2d96f37`
- audited predecessor: v95 merge
  `57cf77be8d9992e5fcc2e5833ec64ff458365d00`, post-merge run `33776059453`
- predecessor v94 report hash:
  `29202688ef99ebed3381b7dcb448cab6bb6db923f5034352e677b7e63515ad12`

## Result integrity

The result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v97-rebuild-identity-scaffold-v1`.
It contains 8,943 regular files totaling 125,660,765 bytes and no symbolic link. The report and
progress file are byte-identical. Every embedded canonical hash below recomputes exactly:

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `execution-scaffold-report.json` | `1f866ceafe00a287081bf7e9e2932f5745b349f128d8ae7cb0f4a20fc363fff7` | `6000435cb3f439cb206666dc06c55332e02d8a85cd688eb5e055537274f67f18` |
| `execution-scaffold-progress.json` | `1f866ceafe00a287081bf7e9e2932f5745b349f128d8ae7cb0f4a20fc363fff7` | `6000435cb3f439cb206666dc06c55332e02d8a85cd688eb5e055537274f67f18` |
| `dind-cleanup-receipt.json` | `0f6cad5e8852eb6892381d1e51dd583c409b05107f248870d834e4653fe9f086` | `2fcee8c5e3da62073e41dc5b3212bf30a6f7618ac7542928fdf7b76cfdf4b452` |
| `dind-runtime-receipt.json` | `6f09142fa26ba4b3a621f9c46935655eab51a4e1090f5633a5a26c8003cdcc7a` | `bb235d4912ebbd53548fdaffa8a22b60d859311624d844e25591008a57a52ed3` |
| `headroom-preflight.json` | `275505877026380284fff51cee0e7f0ba66f60d7de964371f2b9f5fe08282ad9` | `8cb300536356b7e45c592c9412627026b96528fff7cb6ab1c6f18ad19d35ab92` |
| `image-transfer-set.json` | `cfb98789697dc775cde0f4d178a3d05e9d6025801b208a4dfe61ab51ec2346cc` | `b4b0dc2cc0a92f1a8722ab2c2a7f19a5d8972736126f2813f948269e76f895d0` |

The report records status `stopped_without_execution_scaffold`, reason `TimeoutExpired`, and
only the completed stage `controller_and_workspace_runtime_transferred`. It also records
`provider_execution_authorized=false`, `provider_execution_scaffold_published=false`,
`provider_request_started=false`, zero provider calls, and zero model processes. No
`execution-scaffold-contract.json` exists.

## Completed qualification evidence

The three completed Ibex tasks passed the corrected semantic comparison and froze their own new
image identities:

| Task | Qualification | Derived command image | Lock hash | Security scan ID |
| --- | --- | --- | --- | --- |
| PR-465 | base FAIL, infrastructure false, reference PASS | `sha256:6168fa153102d6a8d88cc373e5899c4cf4d5ebb21f44c5c1f5d2c96cfad57950` | `657d5ee1e150c3439adce7cddb78fed7126636194ace69d908c35a3d85071679` | `04b6e7defdbde1db923201e00e973befedd63950576b54149d96b52516f14f97` |
| PR-1135 | base FAIL, infrastructure false, reference PASS | `sha256:c7488c0b8aace18a7583f9bdb375d7866acd9e2072028b73a3538fd677177e5b` | `28eff0d2e3b770b594323a4415e2464cec29134b9f3e8815ca7dcdfa236f14a2` | `794ab15fc6b78dd339f6d30541034240267bc229cd4e827f324118e76f57f7db` |
| PR-1780 | base FAIL, infrastructure false, reference PASS | `sha256:403a7ab911080cfe2c43bf5299d258157240ef16b8c3d9d75001abc5bb512048` | `85bba912bc0d33290ebcc41658b4d7ff4884a30b7f95a54703ff670b8c8c7b44` | `f5f31ad5caadb507e0de41e54d61f986385d4312e7b6abe85df55febcd278b5e` |

For each task, `scan_passed=true`, `secrets_detected=false`, and all 29 v2 checks are true. The
source, task, official-verifier, tool, behavior, and security semantics equal the audited
predecessor after excluding only the explicitly rebuild-derived image, lock, scan, and diagnostic
identities.

PR-2017 completed patch compatibility and local archive preparation. It did not publish a
source-image lock, command-image receipt, final image lock, security scan, or qualification
smoke report. PR-2711 did not begin materialization. Thus the five-task atomic publication gate
correctly remained closed.

## Root cause and repair boundary

The failing operation was the task-specific `docker create` used to inventory the fixed toolchain
paths in the newly built PR-2017 command image. It used `--pull never`, network `none`, a read-only
root, a non-root user, dropped capabilities, bounded CPU/memory/PIDs, and an allowlisted
`sha256sum` entrypoint. The Docker client did not return within the fixed 30-second command bound.
No raw command output or exception text was persisted.

This proves that historical derived-image equality was fixed, but it also exposes an
under-sized generic Docker-control-plane timeout. A successor must preserve a finite bound while
giving image create/inspect/remove operations a separately declared, tested bound. Timeout paths
must remain fail-closed and prove cleanup. It must rematerialize all five tasks from completed
local archives; the three partial v97 results cannot be imported into a successor contract.

## Cleanup, storage, and credential boundary

- No v97 campaign container remains.
- The socket volume is absent. Its backing directory is empty, owner-only, and restored to
  UID/GID `1004:100`.
- The retained data volume is a local-driver bind volume with exact device
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v97/data`. It is frozen as audit evidence only.
- The runtime receipt proves the host and inner data roots shared inode `64770:682230405`, the
  outer DinD daemon used network `none`, and host `/data/docker` was not used for task layers.
- An independent in-memory scan compared all four live nonempty provider values against all
  8,943 regular evidence files: zero matches. Values were not printed, persisted, or hashed.
- No registry, partial archive, VPN/proxy change, host-Docker prune, or second downloader was used.

## Successor boundary

V98 authorizes no provider access and no execution by itself. After this audit is merged and its
post-merge `main` commit passes all eight Actions classes, a new zero-provider repair may be
implemented under unused identity v100 with fresh paths rooted at
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v100`. V97 and all earlier volumes remain closed.

A successful v100 result requires an independent v101 audit before any new provider matrix is
authorized. That provider matrix must use a later unused identity; v99 remains retired.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks, research trajectories,
or authorized imports. Failed context is audit-only. The following remain false:
`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready`.
