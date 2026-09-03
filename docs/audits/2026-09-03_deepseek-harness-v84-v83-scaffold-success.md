# DeepSeek Harness v84 audit of the v83 execution-scaffold success

Date: 2026-09-03

Status: **successful zero-provider execution scaffold frozen for one bounded successor reopen**.
V83 ran exactly once and may not be retried, resumed, reconstructed, or relabelled. All five tasks
passed the offline qualification contract, and the corrected canonical-tag controller transfer
passed. No provider episode, model process, formal collection, SFT export, training, or
production-readiness work started. This audit does not itself authorize provider execution.

## Authorization and execution boundary

The v83 implementation was merged through PR #120. Its only execution used exact clean tracked
`main` commit `4b57a5db51b2fe6848ef0c195e061446273d84c7`. Post-merge `main` Actions run
`33744354298` passed all eight required job classes before invocation.

The output root, DinD backing root, and both fixed v83 outer volumes did not exist before the
invocation. Recognized DeepSeek, OpenAI, Anthropic, and VeriGym provider variables plus
`DOCKER_HOST` and `DOCKER_CONTEXT` were removed from the child environment without printing,
persisting, or hashing their values. The command ran exactly once. It did not change the host
Docker daemon configuration, restart Docker, alter VPN/proxy state, start or stop the user-owned
image downloader, access a registry, read a `.partial` archive, prune a cache, delete shared
`/data/docker` content, or reopen v79 or v81.

The v83 manifest file SHA-256 is
`ebb58a8917444b8d96d37f4fc27ec037313f7f7e9a1d0b5d93ba2136418bc30b`; its reproduced canonical
manifest hash is `24bdcfa839d0b4aedde41a11c404c134d777a6c7220225c86e6588136b6ac3a8`.
The authorization document file SHA-256 before execution is
`5a5e64c8fdd83f678ca1ff35c3af03244292160635c9f2ced8e7101792f531b5`, and the runner file
SHA-256 is `535224ae711475a0ab93233a19742fea36452b6168507eac40698725c036dd75`.

## Capacity, isolation, and `/data2` binding

The content-free headroom gate passed all four roles:

| Role | Minimum bytes | Observed bytes | Minimum inodes | Observed inodes |
| --- | ---: | ---: | ---: | ---: |
| `control_root` | 4,294,967,296 | 9,402,986,496 | 100,000 | 18,383,300 |
| `docker_root` | 103,079,215,104 | 41,347,082,067,968 | 250,000 | 706,888,365 |
| `scratch_root` | 8,589,934,592 | 41,347,082,067,968 | 50,000 | 706,888,365 |
| `output_parent` | 2,147,483,648 | 41,347,082,067,968 | 10,000 | 706,888,365 |

The `docker_root` observation was the exact new backing directory
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data`. Independent host and sidecar `stat`
calls observed the same device and inode identity, `64770:682230182`, for that backing and inner
`/var/lib/docker`. The retained local volume
`verigym-deepseek-harness-v83-dind-data` is labeled with owner
`rollout-controller-dind` and role `data`, and its exact bind device is the v83 `/data2` path.
The host-visible mountpoint below `/data/docker/volumes` is only Docker's volume descriptor;
nested image layers and writable VFS snapshots are on `/data2`.

The sidecar used image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`,
Docker 23.0.6, VFS, runc, outer network `none`, and no host Docker socket. The inner bridge was
disabled, and task/verifier execution stayed on `network=none`.

- `headroom-preflight.json`: file SHA-256
  `8bde52ae0c9fa4ba2eff20371662a2adaa03e89b6c40becc1da5255b44bb61b3`; reproduced canonical
  hash `2208f87942fce704864be23337476fbcc74fe13efe3d6ca77dcc81f5c48f924a`.
- `dind-runtime-receipt.json`: file SHA-256
  `81a8900a46fdb9072cda540ee79b1f01dab93af5e2a9e8b924189fe3a1f9a01c`; reproduced canonical
  hash `c702997435cc506c727da252ca04c79b24c0879e142f7eb204f49bd0f3440e5b`.

## Five-task qualification and image locks

All task, archive, command-lock, source-lock, and security-scan hashes independently reproduced.
Every task recorded reference-patch compatibility, a completed archive with valid
SHA/config/manifest locks, base-FAIL without infrastructure failure, reference-PASS, verifier and
command networks `none`, a task-specific v2-scanned command image, zero provider calls, and zero
model processes. Every scan recorded `scan_passed=true` and `secrets_detected=false`.

| PR | Task receipt | Command image | Command lock | Security scan |
| --- | --- | --- | --- | --- |
| 465 | `ac3a262806841580a2910f4cf32927e680cd2d1bd881c55188a1100da15a0563` | `sha256:45584028a46eb1e5dc2ba837db4483db4ca76f4550e660b4f6279dbdd6b7366e` | `f62969cccb910a2b2b4bb3ba5a5f603a28b4f3e45b2d1eebd9b2356c1f6753e6` | `e1103e63ead1e208f25c174e28ff4db02be0307e6ecf65e3649ff713728b59df` |
| 1135 | `d04c0978f0c7ca13108b04785ec7e02c7be562fa2cc94626f28822b4683aa62c` | `sha256:185bedc6981c46a7a7bce294375b123e503e3503c6a789944c29e05a2add23e2` | `433b46c9d891977443b8b96fa87688b528b47e081cf1c252b0d4608096f7b976` | `536f0735c1545a532c913e23c82fe53638260f5da17a8e4068863e344498d67e` |
| 1780 | `cb199aef462ef7243b66eb37f431d84f5f44917c553f3dfe3375918fefe2b51c` | `sha256:8bab89609b9e5142280d85c49700c1a98d62ecabbace9f0a1e4ce3f95551fdc5` | `e6cf301505fb2924545d4a97e89cfb9bd9b62506142a94409168a758e5dc390d` | `4fea1b75731f239a124899a48e6eca2ba236ceb3b77256f39a0d717719d0151f` |
| 2017 | `ad0795029730a86eda99dfd0620da254a58a6d06cfcdd03e92229f289e0fd7bd` | `sha256:47325f03083e775db7594ea87c0b7d1813a05214500d7792d56b86fb7fb5ea7f` | `c7d9cf2c9c718222256e10673be0465f054d5ade60f5418db726a3c319e6791a` | `aa5590cc01e042a79b06b70818b3dab8af6b3f13a28bac67a6eb481c4e35afa1` |
| 2711 | `8a91992926393ca5b6fb8c6e304bd6e256c3dc3bedf0caa8d6b4ddc46f0d0786` | `sha256:631d92865e1446003efabfb0702498db9ebce174d4c717f141f9ff8e5694d255` | `4429fd8fe0e35d74caa1bb67dbc7539fd73775bada2e5d68223c535ebe1e9999` | `6a507d68464d180e98cae5fca163cbb5c6a66a8cdf7e8cddec50fa8c6a6f5c0f` |

PR-2017 alone retained `runtime_base_commit_override_applied=true`; the other four tasks matched
their dataset bases. The five archive receipt hashes remained the previously frozen values, and
all recorded `registry_accessed=false` and `partial_archive_used=false`.

## Corrected controller transfer

The host canonical tag `node:22.19.0-bookworm-slim` was verified to resolve to exact image ID
`sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8`
and repository digest
`node@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90`.
V83 saved that canonical tag through a read-only content-free pipe and loaded it into the fresh
inner daemon. The inner result had the exact image ID and canonical tag. As expected for an
offline load, it had no `RepoDigests`; the receipt explicitly records that fact and binds source
provenance to the verified host digest. No archive or raw transfer output was persisted, no
registry was accessed, stdout was bounded to 41 bytes, and stderr was empty.

`controller-image-receipt.json` has file SHA-256
`96ed81b156aa3c51fcb91a9316e895eddde0705996c957bc0c11c84481b7d5fd` and reproduced canonical
hash `7a72261b70c26fd4cad349d548415246219434bd13dbacaa0a9fdef29a44f1a7`.

The execution inventory contained all 11 required unique image IDs: five official verifier
images, five task-specific command images, and the controller. Sixteen total unique IDs were
observed because sanitized builds retained intermediate images. The inner container and volume
inventories were empty, and the provider inner network was not created. The inventory file
SHA-256 is `8713b804ac116e7da20d99a8f3cb047c8153e3fcf0eac35c92aaab3ac530392a`;
its reproduced canonical hash is
`3754325cdd3b244fa6dc4868bae8f268ec2e315c1b05e6b305038bf93cc6d06a`.

## Atomic publication and cleanup

The report, progress file, and scaffold contract have the same fixed task order and task receipt
objects. Publication occurred only after all five tasks, controller transfer, complete inventory,
sidecar removal, and socket cleanup passed.

- `execution-scaffold-report.json` and `execution-scaffold-progress.json` are byte-identical with
  file SHA-256 `6400ff76939b1abe4dbd9616df645d665dea20fb96bc1a5e1814bb806a22a0cc`;
  reproduced report hash
  `a8efd496f1082d224d9a22cbaf5e4b57fd8c277d9ea2a7b25b8a8ee8b2a89cbb`.
- `execution-scaffold-contract.json`: file SHA-256
  `42a6c01b15735e64df5f05bf839486a522491676bab78e344955826d6c9ec8ac`; reproduced canonical
  hash `32d2f6cbcf4f165c7eed294a48467c85c03464f1d94ea32b8378e61b23158d8a`.

The final status is `completed_pending_independent_v84_audit`;
`provider_execution_scaffold_published=true`, but `provider_execution_authorized=false`;
provider/model counts are zero; and `provider_successor_reopen_count=0`.

The fixed cleanup container returned zero with bounded empty output, `network=none`, a read-only
root, one mount, all capabilities dropped except the three fixed filesystem cleanup capabilities,
and `no-new-privileges`. It removed itself and the socket volume, restored the empty socket
backing to mode `0700` and UID:GID `1004:100`, and left no v83 sidecar. The cleanup receipt file
SHA-256 is `5fc5db636bbb2abde5383967df6f947a95d69e43695da28e88de9c2c6e0018cb`;
its reproduced canonical hash is
`84738f35cfb8cb7fac3206f211fcd55467384d2d54fbb3f361f762d4477bfb75`.

## Frozen disposition

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v83-controller-tag-successor-v1`.
The v83 data volume remains retained and closed. It must not be deleted, pruned, or generally
reused. Only the exact `deepseek-harness-hwe-v85-official-matrix-v1` successor may reopen it once,
and only after a separate v85 implementation/authorization is merged and its post-merge `main`
run passes all eight required classes. That successor must preserve the exact task/image/controller
locks, attach only the outer sidecar and controller to the pre-existing user-defined
`verigym-hwe-net`, and keep task and verifier containers on `network=none`.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
