# DeepSeek Harness v78 audit of the v77 DinD materialization stop

Date: 2026-09-03

Status: **frozen pre-provider runtime-baseline binding safety stop**. V77 may not be retried,
resumed, reconstructed, or relabelled. No provider episode, formal collection, SFT export,
training, or production-readiness work started.

## Authorization and execution boundary

The v77 implementation was merged through PR #114. Its only authorized execution used exact
clean tracked `main` commit `afbf2c4e8c6b0eeab7cf30618a8cbcadd7dcda8d`. Post-merge `main`
Actions run `33725105476` passed all eight required job classes before invocation.

The output root, DinD backing root, and both fixed v77 outer volumes did not exist before the
invocation. Recognized DeepSeek, OpenAI, Anthropic, and VeriGym provider variables plus
`DOCKER_HOST` and `DOCKER_CONTEXT` were removed from the child environment without printing,
persisting, or hashing their values. The command ran exactly once. It did not change the host
Docker daemon configuration, restart Docker, alter VPN/proxy state, start or stop the user-owned
image downloader, access a registry, read a `.partial` archive, prune a cache, delete a shared
`/data/docker` image, or reopen the retired v75 data volume.

The v77 manifest file SHA-256 is
`83ab70813cb1a075cfd8e64b1fb72903203a87e2449c22137a8b7b98232b5543` and its canonical manifest
hash is `fe8b538d3486e19a3e19b7e7e152374ad11cd7528a7899702fd5af2c2d8c83c4`. The authorization
document file SHA-256 is
`afc470b0514cfd59766e387e64bab09cf4e1fcf1aaabc7f1fab411ef6578229e`.

## Passed boundaries

All five inherited tasks passed reference-patch metadata compatibility before archive or Docker
access. Those receipts record no Docker access, network access, or raw output.

The content-free headroom gate passed all four roles:

| Role | Minimum bytes | Observed bytes | Minimum inodes | Observed inodes |
| --- | ---: | ---: | ---: | ---: |
| `control_root` | 4,294,967,296 | 9,400,369,152 | 100,000 | 18,378,109 |
| `docker_root` | 103,079,215,104 | 41,796,211,646,464 | 250,000 | 714,009,313 |
| `scratch_root` | 8,589,934,592 | 41,796,211,646,464 | 50,000 | 714,009,313 |
| `output_parent` | 2,147,483,648 | 41,796,211,646,464 | 10,000 | 714,009,313 |

The `docker_root` observation was the exact new backing directory
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/data`. The receipt file SHA-256 is
`9804a8a294a8954b127cb9c6a966cf551a3b20eda15fcef1a34562237625233b`; its reproduced canonical
hash is `61891a5c0f6a62371c052e0d3a92b5a0dcb5dd46d59baf8a4360e09799b29ecb`.

The frozen Docker sidecar matched image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`, repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`, server 23.0.6,
`vfs`, and `runc`. It had `network=none`, no host Docker socket, and only the fixed data/socket,
output, and sentinel mounts. The task-layer mount and the `/data2` backing had identical device
and inode identities during execution. Runtime receipt file SHA-256:
`78b12c95a9d10515a82c05521ccd47aabda33cb736d31ca7890926bfcbc6adfc`; reproduced embedded hash:
`23d5fe785595c83aa490dca6b137d1170509ac48f14b5876cb149ef50e4adfc8`.

The exact `.hwe_tools` CVA6 source-profile repair worked. PR-2017 produced a final prepared source
with the task-image bridge absent, the generic symlink sanitizer completed, and the repository
profile hash was
`f73cc268c08fbc2b66788e61e882b0f390822185b857fce361e21a849ce2dda5`. Thus v77 did not fail at
the v75 escaping-symlink boundary and did not weaken rejection of unlisted escaping links.

All three Ibex tasks again reproduced base-FAIL without infrastructure error and reference-PASS.
Each derived command image passed the v2 scan with `network=none`, a read-only root, all
capabilities dropped, `no-new-privileges`, non-root `1004:100`, one workspace mount, no Codex, no
credentials, no hidden reference/verifier payload, and no detected secret.

| PR | Task receipt hash | Command image | Smoke report file SHA-256 |
| --- | --- | --- | --- |
| 465 | `b604258c08d48b3f19fec75170cb5f9fa5eacdf8562e35c3c0dd4d908ac72927` | `sha256:bea12b55157287dc5285978803f9ab6bd14f39eff6867af6802f81aa3ceff01a` | `f31aef682ef74774205da019fefa70327f13af028e00b4a88038432c49b70f0e` |
| 1135 | `5b826cad6b20a9e5e3e9b096d1716a1679158bfcdb41d891cd65360f1f6660fb` | `sha256:7cbc48b552f348b1195d20264c117f810c66fe1dad2258baccbf5b10d096ea77` | `e96d73a0c6bd6d0f928c66c7ff813f63eaa04a4599c6153ef62363cfab162414` |
| 1780 | `29ea996000f9db18f8ae3b8b83a558e919bcd618df65e1b1e15acd10c863a117` | `sha256:88ce8b355dc569ac4087dd2b9b9ce36516a41be0809b68fc49c20c501ccf6490` | `d727ec730d0b7f8aff247cc3f72fff4954b5d0de4d12cb2e41ff72c0001919f9` |

The command diagnostic, security scan, and image-lock file SHA-256 values are:

| PR | Command diagnostic | Security scan | Image lock |
| --- | --- | --- | --- |
| 465 | `2e689500c9103f55190a851894a77ffd5282b43380046c92a0494eddff835340` | `7a8cff33b75ed6835254b1e50b4264107833a8e6debf7f79ed8e58c6d4d0446b` | `d64b262d91ee677ad115eb9dd5982c32d327e23ed79cb2ceb9cc12fc487847db` |
| 1135 | `66d998256324eb88f41026a9b4c9b7ba574229b017fbc068ff57ab76c40dcfb4` | `15c7914e0cccc965d3e9bcf14b63d8e5251857836349b920b0a0d5ea25d9bb06` | `bd42a43ea280bcd34de4f34cb98bcb787965c03a3d91dcb3b3b286db77dde568` |
| 1780 | `d6cb457f2e99a3d887c0dce5d62a335b92eb8228e2b5a0a6bdc0fd932b74aa07` | `b43ef190c38a084413359f6683c1ae83e81a04c35eede39093372aceac6a1fff` | `8ac8595c655bfabf95e9b4bce8d1e4a68ad6073c33b5568a6e3d484f1d10f557` |

All report, runtime, cleanup, archive, task, diagnostic, source-lock, scan, and command-lock
canonical hashes reproduced independently.

## Stop finding

PR-2017 passed completed-archive identity validation without registry access. Its archive receipt
file SHA-256 is `eba4aac48206d3a48b373d32a717d4a5312ebd4ecb77020a1f8781b904a0ec3c`,
and its reproduced receipt hash is
`404905cd479155469525384271d56de2e33647ec0af21d343112fc1cd3bb98c5`.

Source preparation then completed with a single discoverable task and a present source content
hash. The prepared `image-lock.json` file SHA-256 is
`b3162d87d83dd9bb9a5958a696c8b8c1a1d9858a92b43c658866ac356ee1513d`; its entry binds source
hash `b2eaaf632ae46acf9406791df199ffdbe1d5000edb22b8afdc193cceefd6a6f7`, reference repository
hash `cd918c0473027579a3b52117ff15a40c4d7f44e42872f9bb4e6d0d7893a463ad`, reference patch hash
`7d17f4fd2f1e120921f3c59e960939ecc8c6fb6f2bd174834f37a92bd0305330`, and task-bundle hash
`fe1073d1f55065ca514599da45c55753ab89d9eafec7d6afaf5bcc76bc5d9fbd`.

The next source-binding gate failed closed before qualification, command-image construction, or
scanning. The exact mismatch was:

- frozen public dataset base commit in the v69 task lock:
  `90d780eb14bb99624ad9a377b5140f1781647a33`;
- digest-locked runtime marker observed from the official PR-2017 image:
  `d87707a81fe8926dda2deff844797a491811983a`.

Every other source-binding predicate matched: task ID, instance ID, official image ID, registry
manifest digest, and source content-hash presence. The CVA6 profile deliberately uses
`digest_locked_runtime_marker`, and the HWE preparer records the observed runtime marker in the
image lock and task-bundle identity when it differs from the official dataset base. The historic
v69 `_source_binding` helper instead requires `entry.base_commit == task.source_commit`, conflating
these two separately valid identities.

Independent read-only inspection of the completed PR-2711 archive reproduced archive receipt hash
`ddd4e9f5bbb4d08aec204f8e285d4a00eaf59ccd8793ec31bb589e4d245a48bd`, with registry access and
partial-archive use both false. Its runtime marker equals its dataset base commit
`5518a41c08a1949c606d54b9ac631e8f7635e7f3`; the mismatch is specific to PR-2017. PR-2711 did not
start archive validation or materialization in v77.

A successor must add an exact task-specific runtime-baseline lock for PR-2017 rather than change
the public dataset base commit or globally accept marker drift. Source binding must continue to
verify the dataset base through the selected-row lock, separately require the exact
`d87707a81fe8926dda2deff844797a491811983a` runtime marker for PR-2017, require equality for tasks
without an explicit override, bind the repository profile and task-bundle hashes, and reject any
missing, additional, or changed override. The successor must use a fresh identity and fresh
`/data2` DinD storage.

## Cleanup and storage finding

The exception path removed the v77 sidecar. The fixed v2 cleanup inventory included
`/verigym-socket/runc`; its dedicated `network=none`, read-only-root, single-mount cleanup
container removed all listed runtime paths, restored the exact socket directory to mode `0700`
and UID:GID `1004:100`, removed the socket volume, and removed itself. The backing was empty at
independent host audit. Cleanup receipt file SHA-256:
`a1a267dec29963ddc27bce1370b8424047264e98b5c69bf1af78f37a13959dea`; reproduced embedded hash:
`4a92d1dc38fb3fafb51790ce35ef90db4822da8b82bf6d335ab90a40b8cd866d`.

The persistent v77 data volume remains labeled and bound to exact
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v77/data`; Docker's shared root stores only the
small bind-volume metadata. The v77 data backing is not deleted, pruned, reopened, or reused. A
successor must use a new versioned data volume and a new `/data2` backing directory.

## Frozen evidence and disposition

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v77-dind-zero-provider-successor-v1`.

- `zero-provider-report.json` and `materialization-progress.json`: file SHA-256
  `d284514b6e39fe2b9df6e8e5d1e94e40eee65a73123f5c7e2e08f03be84e4588`; reproduced embedded report
  hash `22cfb52074b901fddbba3881b2608cc70c897d6c2e7431b8b4be0bd8e508a3a0`.
- `headroom-preflight.json`: file SHA-256
  `9804a8a294a8954b127cb9c6a966cf551a3b20eda15fcef1a34562237625233b`.
- `dind-runtime-receipt.json`: file SHA-256
  `78b12c95a9d10515a82c05521ccd47aabda33cb736d31ca7890926bfcbc6adfc`.
- `dind-cleanup-receipt.json`: file SHA-256
  `a1a267dec29963ddc27bce1370b8424047264e98b5c69bf1af78f37a13959dea`.

The report is sealed as `stopped_without_provider_contract`, with stop reason
`ConfigurationError`, three completed Ibex task IDs, zero provider calls, zero model processes,
`provider_contract_published=false`, and `dind_cleanup_confirmed=true`. The provider contract file
is absent and `scan-workspaces` is empty. Partial task receipts are evidence only and confer no
partial authorization. All five tasks remain provider-unconsumed because no provider boundary was
crossed.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
