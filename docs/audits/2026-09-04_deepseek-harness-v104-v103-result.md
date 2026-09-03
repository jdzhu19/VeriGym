# DeepSeek Harness v104 audit of the v103 inspect-output-bound scaffold

Date: 2026-09-04

## Decision

The one authorized `deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1` execution is
validly closed as a pre-provider infrastructure stop. It published no execution-scaffold
contract, started no model process or provider request, and consumed no provider call. The v103
identity and retained data volume are frozen and must not be retried, reopened, imported, or
promoted.

V103 repaired the v100 Docker-inspect output bound and completed all five offline task
materializations. Every task reproduced base-FAIL/reference-PASS, used its fixed official
verifier, built a fresh task-specific command image, and passed all 29 v2 security checks. The run
then stopped during the final inner-image inventory because the inherited inventory predicate
still required the historical command-image IDs in the static schedule instead of the fresh
command-image IDs locked by this execution. This is an infrastructure evidence-binding failure,
not a task, patch, verifier, capacity, or security rejection.

Because v103 did not atomically publish its prerequisite contract, the conditionally reserved
v105 provider identity is retired unused. A repair must use a new zero-provider identity, a fresh
`/data2` DinD data volume, and a later separately authorized provider identity.

## Authorization and execution identity

- v103 authorization merge: `f9f8d58ef92382891bc89a33cbc9269ca1bf7797`
- v103 post-merge `main` run: `33792547851`, all eight required check classes passed
- manifest file SHA-256:
  `53a64afa03dad8bab30243405d0797c328a92abb32a3e76b05c056e5dd61675d`
- manifest canonical hash:
  `931a3863559c848e53a6015fc023275f5fb4a12927e09fe70b47c38ac66c5fee`
- runner SHA-256:
  `903eed74f6aa982824addd699bd96d77c396ecaad275602dc810eaf72da42d91`
- authorization document SHA-256:
  `b632f59cbe003d6700222827cec92aa14905c9d979031f4900808579e14f6c0e`
- source commit recorded by the result:
  `f9f8d58ef92382891bc89a33cbc9269ca1bf7797`
- audited predecessor: v101 merge
  `3546e64c00b80f570334781a228ed521d5a601e8`, post-merge run `33789571225`
- predecessor v100 report hash:
  `9aa3c4716f528429040ff95aa6e12d1da780543c26ad3fab6dce9f2672724b22`

## Result integrity

The result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v103-inspect-output-bound-scaffold-v1`.
It contains 10,476 regular files totaling 164,072,509 bytes and no symbolic link. The report and
progress file are byte-identical. Every embedded canonical hash below recomputes exactly:

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `execution-scaffold-report.json` | `1a96570be6c32f2089b5910348d01a29fbf42cfa627a482d9c822f880611d7e8` | `0de771890a66ab9b70016b02892851135767c96d601d9927b3123deeb3a22e7c` |
| `execution-scaffold-progress.json` | `1a96570be6c32f2089b5910348d01a29fbf42cfa627a482d9c822f880611d7e8` | `0de771890a66ab9b70016b02892851135767c96d601d9927b3123deeb3a22e7c` |
| `dind-cleanup-receipt.json` | `1ec2d08fcbe6f49130477411d1c46f9d20d800589ae1945e085b267b66a1f9e2` | `5be5f5545a383aa3144d5f9920242bf3980238897e7d2dfdef83d94561bfcc77` |
| `dind-runtime-receipt.json` | `16dd9098bea8bcf6d839fb6a94e33a2eb7c1df0b0dbd643ee7a3d13f6bdba0bc` | `450ec13456eaa6da82296a1cf574d978796be8ed70c717037c8c80068424bcac` |
| `headroom-preflight.json` | `ec7deba5e7089538ee8610c995c07592c997977cfd2aff749c0761407dfb7b57` | `5e2881f38c3721a925de7b0fcf3befd51391fb867aba88e5285639988a851a9d` |
| `image-transfer-set.json` | `b07faa5884be28d49c553884020d3e692a9bb6af60eb01cb5ab6ff6a1ca93175` | `875f5ca948631f849bb0158d2dc47cb6d87eb0403b5f1eb3c32a6495bb6f8722` |
| `task-materialization-set.json` | `9cea2996e79d78af5d4bf203a9435475c4420c939cde49434a0722e7e0117bd5` | `eebe10c4b4d0ef2e7f3c1b783daeab187da6fa3556060f727fcb1349e9080d90` |

The report records status `stopped_without_execution_scaffold`, reason `ConfigurationError`, and
the completed stages `controller_and_workspace_runtime_transferred` and
`five_task_offline_materialization`. It also records
`provider_execution_authorized=false`, `provider_execution_scaffold_published=false`,
`provider_request_started=false`, zero provider calls, and zero model processes. No
`execution-scaffold-contract.json` or `execution-inventory.json` exists.

## Completed qualification evidence

All five scheduled tasks passed patch compatibility, archive/source/image locking, zero-model
smoke qualification, command-image construction, toolchain inventory, and the v2 security scan:

| Task | Qualification | Fresh command image | Lock hash | Security scan ID |
| --- | --- | --- | --- | --- |
| PR-465 | base FAIL, infrastructure false, reference PASS | `sha256:901f0e641ad515aeaf137086bc45fb292b4601d664b9a0e856b8551afc7fcb23` | `1c0c0deecaf4423b6c062d23f51d1e259b16c28052eb000909802363302cbb72` | `e50a7f5cb37bc1e50f582cbc289edc4ebb6652a6f2cac2d08b3e6db2653e16ae` |
| PR-1135 | base FAIL, infrastructure false, reference PASS | `sha256:0c294c2b95bb4320850ba1dd6230582ca60ce4c57c5ca84665d8bdacd8558b6c` | `745508d02317cffd5f74759134389c4666d48cbe05270796136118e4232eaf59` | `0d157e349a1aa9c600a988e31e4b6d2771a1de924369a0a6ca5f876a41c7fdf2` |
| PR-1780 | base FAIL, infrastructure false, reference PASS | `sha256:bd32d0a3ec9d707418f0a252511710f1aef92a468a37280eaff26208deb4ce70` | `e6c4b769e5124f825bcf324d60070ed70edc7ac7280b737e15fe35f97bb0b38c` | `085e73e9f69a884ccf858b03587bb14a4d57c0470b2b9e37fa63202689018c79` |
| PR-2017 | base FAIL, infrastructure false, reference PASS | `sha256:e7d4b9a08eedb793b7f414c502a5f081fa6619af0903cce7d6b52b5af4877b5e` | `ce3728b85c0432c1523d8860901af8dd027c24d0487ab215cf2e6f265abf8488` | `d62cb19b7b045720bb1d2a1a65fd6e6d3c5fe57025897e3444fd0de1ac63b1c2` |
| PR-2711 | base FAIL, infrastructure false, reference PASS | `sha256:9ec38afea9ba421eaa00b50ffa20e7867662522a8e0c0d99e66d855709b535b4` | `d7b2f0c6ad4ba7ff519be8ae7b6c1f70f19c1a365baf244849de975100e7048a` | `8120d1c57bc23595ff46e3f4358a9105f9d4b5b5959d0dc4ab1800d864875266` |

For every task, `scan_passed=true`, `secrets_detected=false`, and all 29 checks are true. The
materialization set records the exact 1-MiB Docker-inspect output bound and the 300-second
create/inspect/remove bounds. It records five task receipts, no registry access, and no partial
archive use. These complete task results remain audit context only because final runtime
inventory and atomic contract publication did not complete.

## Root cause and repair boundary

The repaired inspect wrapper accepted the bounded container-inspect responses and allowed all
five command-image locks to be published. Each fresh command-image ID intentionally differs from
the corresponding historical derived ID, and each task receipt records
`historical_derived_image_identity_required=false` and semantic lock equivalence.

The inherited v94 final inventory instead constructs its required set from each static schedule
entry's `command_image` field. Those fields remain the historical derived IDs:

| Task | Historical ID required by inherited inventory | Fresh locked ID present in v103 |
| --- | --- | --- |
| PR-465 | `sha256:1ad1a577a7b9abf6b0ee2c2f7ff8f9418887fe53ff81f321513fabb1f0be569e` | `sha256:901f0e641ad515aeaf137086bc45fb292b4601d664b9a0e856b8551afc7fcb23` |
| PR-1135 | `sha256:3d8c6a4f94a4310d18956423c32004787892902a86f5f636c93ce2d44a616f0c` | `sha256:0c294c2b95bb4320850ba1dd6230582ca60ce4c57c5ca84665d8bdacd8558b6c` |
| PR-1780 | `sha256:bc4d755461dd2e83e07418f510ae35725b0820b21b579b8ab05ee32e0d405762` | `sha256:bd32d0a3ec9d707418f0a252511710f1aef92a468a37280eaff26208deb4ce70` |
| PR-2017 | `sha256:b81f077fef2b82a58c48ea4ad17d3a8c7f8729317fb6c15abe307b526ece8098` | `sha256:e7d4b9a08eedb793b7f414c502a5f081fa6619af0903cce7d6b52b5af4877b5e` |
| PR-2711 | `sha256:1d461c3bbc213151f421cc20e88a6b73567d831ffce8809581d27efaf06ea491` | `sha256:9ec38afea9ba421eaa00b50ffa20e7867662522a8e0c0d99e66d855709b535b4` |

V103 used a fresh empty DinD volume and imported only the controller, workspace runtime, and
official verifier archives before building the five new command images. Therefore its inner
daemon could not satisfy a required-image subset containing the five unimported historical
derived IDs, and the inherited combined inventory predicate failed. The outer `finally` path
then removed the DinD container and socket volume without persisting raw inventory output.

A successor must derive the final required command-image set from the freshly returned,
hash-verified `HweCommandImageLock` objects (and cross-check those IDs against the five task
receipts), while continuing to require the controller, workspace runtime, and static official
verifier IDs. It must still require exactly 12 distinct images and reject nonzero, malformed,
missing, or inconsistent inventory results. All five tasks must be rematerialized from completed
local archives; no v103 task result or retained layer may enter a successor contract.

## Cleanup, storage, and credential boundary

- No v103 campaign container remains.
- The socket volume is absent. Its backing directory is empty, owner-only, and restored to
  UID/GID `1004:100`.
- The retained data volume is a local-driver bind volume with exact device
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v103/data`. It is frozen as audit evidence only.
- The runtime receipt proves the host and inner data roots shared inode `64770:682230412`, the
  outer DinD daemon used network `none`, and host `/data/docker` was not used for task layers.
- An independent in-memory scan compared all four live nonempty provider values against all
  10,476 regular evidence files: zero matches. Values were not printed, persisted, or hashed.
- No registry, partial archive, VPN/proxy change, host-Docker prune, or second downloader was used.

## Successor boundary

V104 authorizes no provider access and no execution by itself. After this audit is merged and its
post-merge `main` commit passes all eight Actions classes, a new zero-provider inventory-binding
repair may be implemented under unused identity v106 with fresh paths rooted at
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v106`. V103 and all earlier volumes remain closed.

A successful v106 result requires an independent v107 audit before any provider matrix is
authorized. That provider matrix must use a later unused identity; v105 remains retired.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks, research trajectories,
or authorized imports. Failed context is audit-only. The following remain false:
`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready`.
