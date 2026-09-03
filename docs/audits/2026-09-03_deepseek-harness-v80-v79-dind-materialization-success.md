# DeepSeek Harness v80 audit of the v79 DinD materialization success

Date: 2026-09-03

Status: **successful zero-provider materialization frozen for successor authorization**. V79 ran
exactly once and may not be retried, resumed, reconstructed, or relabelled. All five inherited
tasks passed the bounded materialization contract. No provider episode, formal collection, SFT
export, training, or production-readiness work started. This audit does not itself authorize a
provider run; any official matrix requires a new, separately frozen identity after this audit is
merged and its post-merge `main` run passes all eight required job classes.

## Authorization and execution boundary

The v79 implementation was merged through PR #116. Its only execution used exact clean tracked
`main` commit `3213e92ad2fe3a0c39d51f607f1af5b6f9c89c87`. Post-merge `main` Actions run
`33731815536` passed all eight required job classes before invocation.

The output root, DinD backing root, and both fixed v79 outer volumes did not exist before the
invocation. Recognized DeepSeek, OpenAI, Anthropic, and VeriGym provider variables plus
`DOCKER_HOST` and `DOCKER_CONTEXT` were removed from the child environment without printing,
persisting, or hashing their values. The command ran exactly once. It did not change the host
Docker daemon configuration, restart Docker, alter VPN/proxy state, start or stop the user-owned
image downloader, access a registry, read a `.partial` archive, prune a cache, delete a shared
`/data/docker` image, or reopen the retired v77 data volume.

The v79 manifest file SHA-256 is
`21cb76734057182d2f74cdd228ad2f4042f30e0379b60c1ba879bad857810f20`; its canonical manifest
hash is `ba780bfc4aa140debee246dbf15125e51208bafeaedf03dea097219076386078`. The authorization
document file SHA-256 is
`0b4ffa2462f55e37a235f28230dead36376c954096c008272b6abd6163b02694`. The runner file SHA-256
is `cd734cfde3ee56ae8013339643de9384f5d238cf978404ddff9132bafd24e5b7`.

## Capacity, isolation, and `/data2` binding

The content-free headroom gate passed all four roles:

| Role | Minimum bytes | Observed bytes | Minimum inodes | Observed inodes |
| --- | ---: | ---: | ---: | ---: |
| `control_root` | 4,294,967,296 | 9,405,231,104 | 100,000 | 18,387,687 |
| `docker_root` | 103,079,215,104 | 41,624,330,571,776 | 250,000 | 712,154,023 |
| `scratch_root` | 8,589,934,592 | 41,624,330,571,776 | 50,000 | 712,154,023 |
| `output_parent` | 2,147,483,648 | 41,624,330,571,776 | 10,000 | 712,154,023 |

The `docker_root` observation was the exact new backing directory
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v79/data`. During execution, independent host and
sidecar `stat` calls observed the same device and inode identity, `64770:682230174`, for that
backing and inner `/var/lib/docker`. The outer volume inspection named only
`verigym-deepseek-harness-v79-dind-data` with exact local-driver device path under `/data2`.
Therefore the nested image layers and writable VFS snapshots used `/data2`; the host Docker
data-root was neither moved nor used for task layers.

The headroom receipt file SHA-256 is
`ef5dd45b9edd3fd386e7ae86ab9323508a0146db5e1aee1f6cf7081ef1e87db5`; its reproduced canonical
hash is `0b5d2610132f445ccaee0101dda6bb65d6cfb81de6cd5f38e1d1f9cf4d07c81f`.

The frozen sidecar matched image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`, repository digest
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`, Docker 23.0.6,
`vfs`, and `runc`. It had `network=none`, no host Docker socket, and only the exact data/socket,
output, and sentinel mounts. Task and verifier execution remained networkless. Runtime receipt
file SHA-256: `6092bfb2ed2476bc929ba63cf9f7e0bb80ad5229e35fac66863fa4d6ef4dd334`;
reproduced canonical hash:
`b08bf7d4b9687097ac956940c67425b08b1e9f0a0c769df1559674240db9a293`.

## Five-task result and runtime-baseline finding

All five task receipts reproduced their canonical hashes. Every task recorded reference-patch
compatibility, a completed archive with valid SHA/config/manifest locks, base-FAIL without an
infrastructure error, reference-PASS, verifier and command networks `none`, a task-specific v2
scanned command image, zero provider calls, and zero model processes.

| PR | Dataset base | Runtime base | Override | Task receipt | Command image |
| --- | --- | --- | --- | --- | --- |
| 465 | `6ce8b6ecf2fa931b333c7878bb2345b92f745854` | same | false | `818294dc459c56e72c5e697db554d3bc41cf9e82a31f28f2e26747c348bd4dd9` | `sha256:c00915adfd04d045529c5849e69fed244a213ae3308c75129a1a7b57d83c7324` |
| 1135 | `adc574b8b0c10381a7728badc2c67c21daabc63f` | same | false | `a8c72b7e800a270303626b34c5dc782285a13c0d8e3443d89baedf5751f56dd4` | `sha256:50b5f4fb7b3597f7d5a0a6a4540128c8439bf0607054fa4d277c30a3d29d125b` |
| 1780 | `1affeff5278d5b2d84984cd3bf173f72d9f024da` | same | false | `4412940a0a897eadacf28b1e72723533251cae775ff5634d5ffd30973820ea89` | `sha256:31f930703c74f121acccd8856f0baad159d61f3b86efbf8cf7d69a547e67c6df` |
| 2017 | `90d780eb14bb99624ad9a377b5140f1781647a33` | `d87707a81fe8926dda2deff844797a491811983a` | true | `80462d2586b4ed6b2c773dabc16ad2067e302b018b9b155797fa60fd7126a73d` | `sha256:0c5b58468143e43d2f3d573249741825ee0f01b481f46895007c004a82186de2` |
| 2711 | `5518a41c08a1949c606d54b9ac631e8f7635e7f3` | same | false | `1403a5b49eba4555db28e8c0a18be11b37b97c027ffd44b065f7986a447d0429` | `sha256:36b72af8e93f9e3b1741c76d0490cdf8479e684a7b403047f8dbb023c95d893c` |

PR-2017 is the only task with `runtime_base_commit_override_applied=true`. Its prepared source
image-lock file SHA-256 reproduced the frozen predecessor value
`b3162d87d83dd9bb9a5958a696c8b8c1a1d9858a92b43c658866ac356ee1513d`; its source hash is
`b2eaaf632ae46acf9406791df199ffdbe1d5000edb22b8afdc193cceefd6a6f7`. The separately bound
task-bundle hash remained
`fe1073d1f55065ca514599da45c55753ab89d9eafec7d6afaf5bcc76bc5d9fbd`. PR-2711 recorded
runtime equality rather than inheriting the override. This closes the v77 finding without changing
the public dataset base or granting global marker drift.

The `.hwe_tools` CVA6 source-profile exclusion also remained exact. Both CVA6 sources used profile
hash `f73cc268c08fbc2b66788e61e882b0f390822185b857fce361e21a849ce2dda5`; the task-image bridge
was absent from the agent workspace, and unlisted escaping links remained rejected.

## Command-image and artifact verification

Every command image lock parsed under its strict schema and reproduced `lock_hash`; every source
lock did the same. Each scan reproduced `security_scan_id`, recorded `scan_passed=true` and
`secrets_detected=false`, and agreed with its command image lock. All five command locks record
`codex_present=false`, `provider_credentials_present=false`, `hidden_assets_present=false`,
`reference_patch_present=false`, and `verifier_payload_present=false`.

| PR | Archive receipt hash | Diagnostic hash | Security scan ID | Command lock hash | Source lock hash |
| --- | --- | --- | --- | --- | --- |
| 465 | `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63` | `ef484aaf3678d3d6b597a37a7292fa0905a7784e5069b2eb972cd8482047eecc` | `7e2143d6836051446a3936c34fa31f2963c2ed9882654858f0d7fb28cd79f7df` | `a9420bf5065c6701a99d9055e83195da92dee43d03b8577c64924527a03f31f5` | `f32616351ff822c6417fc566d34077f30570f73acc8b25d877cf8c6c765f2de7` |
| 1135 | `534d02b83b32adb00ac2f1f561576adc5071ced1186f8d3ab8f437a0002add66` | `e1d91af258ea4ff2b86f5f294f9c9e5cdb4ded0e6ba3f9d61dd62a7b25850d99` | `47ddbc44f45ea549b2b442a35821deb8847583074431d52cc7e9a8c3208ffdfa` | `44e8670128a2be0712e4f9bb974cd28f3a046dcd2976aebcee9862d53c4593d8` | `83d550b854c5bcb65f92adc5506596129e4828848ac0be3d0935dc60329d42aa` |
| 1780 | `35ba87652c5f7bc2217d0b4d0fcd2b8886464d87b2e4256831b64f37a2b49094` | `b092e5ce4c04ea9f05271aa0a171b29ad859d4631b2d39c9170bc2b3181b244a` | `f15e4c2dfac50f3f8faf0ae609055e72c96f22477a9f43e5725388e69c2d0804` | `9447c575ecf91bcbbf86f009710e0a21db6948c8a6a525b7288d7b63a39332db` | `1605bc247a265ccdb8ebf219a59de5aaab35860dd20d5863e5700914e171eb2a` |
| 2017 | `404905cd479155469525384271d56de2e33647ec0af21d343112fc1cd3bb98c5` | `b7e6a00820fb37de066ea8837e87d1997cde729e14f5cda004eb8451e4761ff6` | `9a76a1b8fa4134ec1024e09e6e9e5262de87ce29f069fda327bacffd2b91cd21` | `cd529ee9a68af280d8eed52acb49a02993e6d0b72e12b806a96108e3a7b1d60b` | `9e48f93bbde15c5192f920d233a36b58726b48795c54df5f49a35413f25344b3` |
| 2711 | `ddd4e9f5bbb4d08aec204f8e285d4a00eaf59ccd8793ec31bb589e4d245a48bd` | `0654f23a3341ba6b605ec3f411a0731c15fc94f7af673690604c8d4fc267c20e` | `db6089c2baa351eac7b9bdad42fc6d38a81fee9e67195999689d31f5378445e7` | `daf35d93d93cb047eec4fc8fbc150df6d0fbb2dbf6d6145761254e780a25f002` | `32ed3dc7bd896b4f8759a8d04d757d4bcfa9bb2e69629bc298ab53f40320b8a5` |

All archive receipts independently reproduced their canonical hashes and recorded
`registry_accessed=false` and `partial_archive_used=false`.

## Atomic publication and cleanup

The final report, progress file, and provider contract have identical task lists, task receipt
objects, and frozen order. The contract was written only after all five tasks, empty inner/scanner
inventories, sidecar removal, and socket cleanup succeeded.

- `zero-provider-report.json`: file SHA-256
  `5c9a5c4c7bdd956b487c75d77e866d66095f1bec04904c6859a3bf0306197b9f`; reproduced report hash
  `b47af07187bb63d078fd65272f2922a56e1ec27289148bbebc593bf8e9fcc4cc`.
- `materialization-progress.json`: file SHA-256
  `c778444d400f0371c63002f487226916c436e5afc1e11da3418746c8c3c2e2c7`.
- `provider-contract.json`: file SHA-256
  `677837ff1877b3d247417af75492a9d11b544470f0ca4faecc1d8895983ca963`; reproduced contract hash
  `38d79fcf0a5418c4153827a13ada20f1b8764daa17259ea1abbc19d2ef67b9b7`.

The final status is `completed_pending_independent_v80_audit`; the exact five primary task IDs are
complete; `partial_authorization_published=false`; `provider_execution_authorized=false`; and
provider/model counts remain zero.

The dedicated cleanup container returned zero with bounded empty output, `network=none`, a
read-only root, one mount, all capabilities dropped except the three fixed filesystem cleanup
capabilities, and `no-new-privileges`. It removed itself and the socket volume, restored the socket
backing to empty mode `0700` and UID:GID `1004:100`, and left no v79 sidecar. The cleanup receipt
file SHA-256 is `bce750860355a7e4d19d48e4dfe677693da31a012e290d732d30338a03a79bd9`;
its reproduced canonical hash is
`1d7a5f7f931ca7b45c7a12d0b6e4e5cbcb2bddeb855bed28cd75580b55c490f3`.

The persistent v79 data volume remains labeled and bound to exact
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v79/data`; Docker's shared root stores only the
small volume descriptor. The data backing is frozen evidence and must not be deleted, pruned,
reopened, or reused by a successor.

## Frozen disposition

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v79-dind-zero-provider-successor-v1`.
It is research/audit evidence, not a formal trajectory dataset. No failed or successful task here
is a model sample because no model ran.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
