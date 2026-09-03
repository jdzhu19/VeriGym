# DeepSeek Harness v76 audit of the v75 DinD materialization stop

Date: 2026-09-03

Status: **frozen pre-provider source-hygiene safety stop**. V75 may not be retried, resumed,
reconstructed, or relabelled. No provider episode, formal collection, SFT export, training, or
production-readiness work started.

## Authorization and execution boundary

The v75 implementation was merged through PR #112. Its only authorized execution used exact
clean tracked `main` commit `d672e4e8b2769e18c214fe976fd30963b4d9031a`. Post-merge `main`
Actions run `33720498576` passed all eight required job classes before invocation.

The output root, DinD backing root, and both fixed v75 outer volumes did not exist before the
invocation. Recognized DeepSeek, OpenAI, Anthropic, and VeriGym provider variables plus
`DOCKER_HOST` and `DOCKER_CONTEXT` were removed from the child environment without printing,
persisting, or hashing their values. The command ran exactly once. It did not change the host
Docker daemon configuration, restart Docker, alter VPN/proxy state, start or stop the user-owned
image downloader, access a registry, read a `.partial` archive, prune a cache, delete a shared
`/data/docker` image, or reopen the retired v73 data volume.

The v75 manifest file SHA-256 is
`6d57202435bae04fbafa51766b7b0e6c08c1df51cd970718a0d779260a125f54` and its canonical manifest
hash is `9e36ba35d6266fa2efa7e85ae6e1e1e0f437e838de32afcf612bbc9769239e66`.

## Passed boundaries

All five inherited tasks passed reference-patch metadata compatibility before archive or Docker
access. Those receipts record no Docker access, network access, or raw output.

The content-free headroom gate passed all four roles:

| Role | Minimum bytes | Observed bytes | Minimum inodes | Observed inodes |
| --- | ---: | ---: | ---: | ---: |
| `control_root` | 4,294,967,296 | 9,401,503,744 | 100,000 | 18,380,321 |
| `docker_root` | 103,079,215,104 | 41,901,394,350,080 | 250,000 | 716,447,756 |
| `scratch_root` | 8,589,934,592 | 41,901,394,350,080 | 50,000 | 716,447,756 |
| `output_parent` | 2,147,483,648 | 41,901,394,350,080 | 10,000 | 716,447,756 |

The `docker_root` observation was the exact new backing directory
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/data`. The receipt file SHA-256 is
`246dd43d5db7045f2ba8c43df05c7c830e9a1e511427b32f7915b7acf2dcc936`; its reproduced canonical
hash is `bb9c3fe5461082d1bb2f69945355bbd6cb9d5943eb58fd53cfe49effd7c64285`.

The frozen Docker sidecar matched image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`, repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`, server 23.0.6,
`vfs`, and `runc`. It had `network=none`, no host Docker socket, and only the fixed data/socket,
output, and sentinel mounts. Runtime receipt file SHA-256:
`9e3b34627e2682cf4de58355fd6f2d67f78c58c80c3d83d7ef5565d2bcce9524`; reproduced embedded hash:
`af0ef3800a6d0b03a2773f0329c0342f8022e6060508884548fcaebc0c791a05`.

The scanner-namespace repair worked for all three Ibex tasks. Every temporary scanner workspace
was removed, and `scan-workspaces` was empty after each completed task and at terminal audit.
Each task reproduced base-FAIL without infrastructure error and reference-PASS. Each derived
command image passed the v2 scan with `network=none`, a read-only root, all capabilities dropped,
`no-new-privileges`, non-root `1004:100`, one workspace mount, no Codex, no credentials, no hidden
reference/verifier payload, and no detected secret.

| PR | Task receipt hash | Command image | Smoke report file SHA-256 |
| --- | --- | --- | --- |
| 465 | `48ae4bb9e642e2e5b3a01127ac6dd18d2e1e748a703c81e5614e52ca589f8295` | `sha256:08f499d8a85d3b50b1eef53df982e1cfb0e3a2e3933371c3e61fb0860b243f9c` | `f31aef682ef74774205da019fefa70327f13af028e00b4a88038432c49b70f0e` |
| 1135 | `2ea91d0b43bd8eac70a578322b34073288cc0bbbf69a6ba2deecb11509e56e61` | `sha256:e9a1b3da6e9aa01fecce68b841f19f1d92d21388fd128d44e12d606592cdf30b` | `e96d73a0c6bd6d0f928c66c7ff813f63eaa04a4599c6153ef62363cfab162414` |
| 1780 | `9e72fa3ac8e6e6d4eb664eb11c6d45dcf97775a78cefe00d4d398ce2442166f9` | `sha256:e9fe001908dcd046a876afb078f770813aca6b3d372d69a6f28f75c003a2ddae` | `d727ec730d0b7f8aff247cc3f72fff4954b5d0de4d12cb2e41ff72c0001919f9` |

The command diagnostic, security scan, and image-lock file SHA-256 values are:

| PR | Command diagnostic | Security scan | Image lock |
| --- | --- | --- | --- |
| 465 | `547836c102844488c32e3b90a608b9e87f391ea2b9edf3a950d4b0e0cb2dec1a` | `39a23087834687a5fd107ad0f1fa96891730e0a4c569e0b2262da64e907415c5` | `180dfbc627402e3a32bd82096c0bc7dc990e71745aae1c9a719adf1ea2423377` |
| 1135 | `e458b27d8752f131eca3cc8e5474669eee9a403409263c2be332996faf132e97` | `b61da1ee24b7205ab23f089a2b13f1901e56127a684b8c816c1ab0514abbc727` | `74ab8db90c6d129355ee9ab6871cb7afec9884b669143f4f8b0caf57f5d0b990` |
| 1780 | `ef461447e908333fd36992bf3bb4d0b71adb48e05f799ec5928e429e7f76cb0a` | `f869151e0da918aaf4c16615825c230815cdbbc58e57ec68d1e881f75af1cb88` | `fb87ce493cc87bd20c229f923e272967d20b4d44aafe2b0a39b463dc3ea88778` |

All report, runtime, cleanup, archive, task, diagnostic, scan, source-lock, and command-lock
canonical hashes reproduced independently.

## Stop finding

PR-2017 passed completed-archive identity validation without registry access. Its archive receipt
file SHA-256 is `eba4aac48206d3a48b373d32a717d4a5312ebd4ecb77020a1f8781b904a0ec3c`,
and its reproduced receipt hash is
`404905cd479155469525384271d56de2e33647ec0af21d343112fc1cd3bb98c5`.

Source preparation then failed closed with `ConfigurationError` before source binding,
qualification, command-image construction, or scanning. Read-only inspection of the already
validated offline image archive identifies the exact entry in its final layer:

`/home/cva6/.hwe_tools/verilator -> /tools/verilator-v5.008`

This absolute link is a task-image tool bridge, not repository content that can be copied into the
agent workspace. After `docker cp`, the current CVA6 workspace profile excludes only
`verif/core-v-verif/vendor/riscv/riscv-isa-sim/build`; the generic source sanitizer therefore
correctly rejects the remaining link because it escapes the extracted repository root. No raw
exception was persisted. PR-2711 did not start archive validation or materialization.

A successor must add the exact `.hwe_tools` task-image bridge directory to the CVA6
`workspace_excluded_paths` policy before generic symlink materialization. It must retain the
existing fail-closed rejection for every other escaping link and add regression tests proving that
the profile-owned bridge is removed while unlisted absolute and relative escapes still fail. This
is a source-profile repair; it does not authorize reuse of v75 storage or provider access.

## Cleanup and storage finding

The exception path removed the v75 sidecar. The fixed v2 cleanup inventory included
`/verigym-socket/runc`; its dedicated `network=none`, read-only-root, single-mount cleanup
container removed all listed runtime paths, restored the exact socket directory to mode `0700`
and UID:GID `1004:100`, removed the socket volume, and removed itself. The backing was empty at
independent host audit. Cleanup receipt file SHA-256:
`e443226d8376e62a7343e414456e42b312494b3b4fb961bc2cd1046e9959120c`; reproduced embedded hash:
`aa7fae0d75c63cb457f7965cbbdc3d7cbf072dafb76955f0ecb3885f931dd402`.

The persistent v75 data volume remains labeled and bound to exact
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v75/data`; Docker's shared root stores only the
small bind-volume metadata. The v75 data backing is not deleted, pruned, reopened, or reused. A
successor must use a new versioned data volume and a new `/data2` backing directory.

## Frozen evidence and disposition

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v75-dind-zero-provider-successor-v1`.

- `zero-provider-report.json` and `materialization-progress.json`: file SHA-256
  `850f1ba2277abd72609d021a3c5939aab5bb11d35e1198516716cfba2cada16a`; reproduced embedded report
  hash `0eb7ac52c6577932134dd9bd3518da2c755c0c3409b166ad6b3944fade36a2fe`.
- `headroom-preflight.json`: file SHA-256
  `246dd43d5db7045f2ba8c43df05c7c830e9a1e511427b32f7915b7acf2dcc936`.
- `dind-runtime-receipt.json`: file SHA-256
  `9e3b34627e2682cf4de58355fd6f2d67f78c58c80c3d83d7ef5565d2bcce9524`.
- `dind-cleanup-receipt.json`: file SHA-256
  `e443226d8376e62a7343e414456e42b312494b3b4fb961bc2cd1046e9959120c`.

The report is sealed as `stopped_without_provider_contract`, with stop reason
`ConfigurationError`, three completed Ibex task IDs, zero provider calls, zero model processes,
`provider_contract_published=false`, and `dind_cleanup_confirmed=true`. The provider contract file
is absent. Partial task receipts are evidence only and confer no partial authorization. All five
tasks remain provider-unconsumed because no provider boundary was crossed.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
