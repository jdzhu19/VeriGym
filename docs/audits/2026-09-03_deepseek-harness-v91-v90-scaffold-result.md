# DeepSeek Harness v91 audit of the v90 zero-provider scaffold

Date: 2026-09-03

Status: **five-task zero-provider scaffold qualified; v90 is frozen pending any separately
authorized successor**. V90 ran exactly once after its merged authorization and green post-merge
`main`. All five fixed tasks reproduced base-FAIL/reference-PASS with infrastructure-valid,
networkless official verification, task-specific command images, and passing v2 security scans.
The atomic execution-scaffold contract was published only after all task receipts and cleanup were
complete. No provider request, model process, trajectory, SFT candidate, formal collection,
training, or production-readiness work started.

## Authorization and execution boundary

The v90 implementation was merged through PR #126 at exact clean tracked `main` commit
`b56917fdb460d329eb680795667bc1f1a48bcbb9`. Post-merge `main` Actions run `33759714274` passed
all eight required job classes before the single invocation.

All twelve recognized Anthropic, DeepSeek, OpenAI, and VeriGym provider variables plus
`DOCKER_HOST` and `DOCKER_CONTEXT` were removed from the child environment without printing,
persisting, or hashing their values. The outer scaffold used `network=none`; its inner bridge was
disabled. Task, command-image scan, and official verifier execution used `network=none`. The run
did not access a registry, accept a `.partial` archive, change the host Docker daemon or VPN/proxy
configuration, prune Docker, touch the user-owned downloader, or open, read, copy, or reuse v87 or
any other historical DinD data root.

The checked-in v90 manifest SHA-256 is
`0b8101706f8cc00ae604cc8751e812f7cf583240552967cb02a178eda30a73d8`; its canonical manifest
hash is `f98925ea8fe49e6b490e02d3e87d1efeac70213b55c69b869e20d218f258b724`. The authorization
document SHA-256 is `bdb70a915e40afa6b079ea520e5e05e2e5f66cd278e7711efdd09166ffa68caa`, the materializer
SHA-256 is `a43d99ef8edf41033b5790b692530aa6cc0e350b0fdc9925ea70fa26a0c9f1ea`, and the HWE source
preparation module SHA-256 is
`633c993f5edd0fb51148fa127e8b2426169ccef1a31ed69efe670b08ae1aaf16`.

## Capacity and `/data2` Docker identity

The content-free preflight passed every absolute byte and inode gate. It observed 9,403,408,384
free bytes and 18,384,123 free inodes at the control root, and 41,190,214,959,104 free bytes and
702,067,448 free inodes for the exact v90 Docker backing, scratch root, and output parent. The
preflight file SHA-256 is
`6d56a00cd7cd5e988b3e09513a063c2ab94569c4b5e2f9d52a5dc7e3e49fe8ab`; its canonical hash is
`3d3de9fff632e2772302153ac013b79971701e4646829d6517e9fb13b0e64338`.

The retained volume `verigym-deepseek-harness-v90-dind-data` uses the Docker local driver with
exact option `type=none,o=bind,device=/data2/jiadongzhu/docker/deepseek-harness-hwe-v90/data` and
labels `verigym.owner=rollout-controller-dind`, `verigym.role=data`. Docker reports its conventional
daemon-side volume mountpoint under `/data/docker/volumes/.../_data`, but the explicit bind device
and matching host/inner identity `64770:682230205` establish that task layers are stored on the
`/data2` filesystem; the host Docker root is not used for those layers.

The outer sidecar used the locked Docker 23.0.6 image, VFS storage, runc, no host Docker socket,
outer network `none`, and no inner bridge. The physical data-volume open count was atomically
persisted as one immediately after container start. The runtime receipt file SHA-256 is
`8a8cf35c56fb0212d9ff55397acfcee9cab9fc042880febde837382a3adca6fd`; its canonical hash is
`74c8a616da3145a5a0533c40a6fc82ce7e0987453015d65154d878fc854fb8b0`.

## Five-task qualification

The fixed order completed without substitution:

1. Ibex PR-465 — task receipt
   `17ea3fccd3e38cf0a0d3ba851d093ad58f4251f2834f82c58a61a79f8ec2ecee`;
2. Ibex PR-1135 — task receipt
   `1adff356610515bd8add6480d1029cca788d49e5a5eff473aa3e32f745d66e4f`;
3. Ibex PR-1780 — task receipt
   `fc0c0e494800f60a302a566b2fe4e15e219be9d86b39e1104af2b38c2da7bbb0`;
4. CVA6 PR-2017 — task receipt
   `c5a76c4f24d9e12d79daa6c8ea9ae2d39e519b8bf7edf16c7198d9895a8efa3d`; and
5. CVA6 PR-2711 — task receipt
   `9bfdfbfb1af80f429706c6322788a1d4147a473d0b0bf365a922ce26b251e059`.

Every task receipt has a reproducible canonical hash and locks the source-preparation Docker
control timeout to exactly 300 seconds. Each records `base_failed=true`,
`base_infrastructure_error=false`, `reference_passed=true`, verifier and agent command network
`none`, and zero provider calls/model processes. All five completed archives have canonical
receipts, all five source/image locks are canonical, and the official source commits, image IDs,
OCI manifest digests, repository hashes, and runtime baseline policy remained bound.

Every v2 command-image scan has `scan_passed=true`, `secrets_detected=false`, all declared checks
true, `network_mode=none`, and no raw diagnostic output persisted. Each scan ID and derived image
ID exactly matches its task receipt; every task-specific agent image is distinct from its locked
official verifier base image. The `agent_toolchain_id` remains
`hwe-official-task-toolchain-v1`; no agent result is substituted for an official verifier result.

The controller image transfer used the exact read-only outer canonical tag pipe, verified source
tag/image/repository digest and inner tag/image identity, persisted no transfer archive or raw
output, observed no provider environment, and accessed no registry. Its receipt file SHA-256 is
`66016a9007ceb13687cde568bdb67fdde090c05d416aa15bcdeeaf617a2ff91a`; its canonical hash is
`4935b12eaafa5f834875d85c1b970d1359510085187021e457e95891049951c2`.

## Atomic contract, cleanup, and secret scan

The final `execution-scaffold-progress.json` and `execution-scaffold-report.json` are
byte-identical, each with file SHA-256
`47ef5569ecc0e8f296faf4fd8c1d80179c5781eb109d7d09785be793cd27e187`. Their reproducible
canonical report hash is `c8cad60517cd000b20557c5686a89d48140bbd7e0a47ca3e4ed986f3e9d59beb` and status is
`completed_pending_independent_v91_audit`.

The atomic contract contains all five receipts, exact timeout 300, all-task and all-scan pass
flags, provider successor reopen count zero, and no partial authorization. Its file SHA-256 is
`400ec1084c726ff5b3d0b3a4203d4d09492f9226fadc7b1b2c866669ba9a1162`; its reproducible
canonical contract hash is `70da1bf264a65272238ed891245c8ef69949faec5396ccc88470cfb58bf379f6`.

Before sidecar removal, the execution inventory found every required locked image present, no
inner containers or volumes, and no provider network created. Its file SHA-256 is
`c21794599ed1d5cffe0236620fafa66f5ee139370f23d26f71100c87277f6fbe`; its canonical hash is
`b78594a159cca8aab37bb272e6acc14551bb9f4ddf63d1d62d90812b8d5d249e`.

After completion, no v90-labeled container remains and the transient socket volume is absent. The
socket backing is empty, mode `0700`, UID:GID `1004:100`. The networkless read-only cleanup
container returned zero with empty stderr/stdout, dropped all capabilities except `CHOWN`,
`DAC_OVERRIDE`, and `FOWNER`, and persisted no raw output. Its receipt file SHA-256 is
`7ae27bbd91ec1aada45b91bff7324f21687d2ac480b9f9c6f6260efd11065d20`; its canonical hash is
`a2519eaf13600ba6b63c9c55adace3bf9dfbd7088576e5d99e2d81149c19ab33`.

A post-run scan checked all 10,475 regular files and 164,091,678 bytes under the v90 evidence root
against the four nonempty recognized provider values present in the parent environment. It found
zero concrete-value matches and zero symlink nodes. Concrete values were neither printed nor
hashed.

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v90-fresh-scaffold-timeout-successor-v1`.
V90 is now immutable. V91 grants no provider execution itself. Only the separately versioned
`deepseek-harness-hwe-v92-official-matrix-v1` may be considered for one reopen after this audit is
merged and its post-merge `main` run passes all eight job classes.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
