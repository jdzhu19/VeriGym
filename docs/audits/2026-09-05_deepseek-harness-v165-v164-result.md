# DeepSeek Harness v165 audit of the v164 controller diagnostic

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v164-controller-initialize-diagnostic-v1` completed and is now frozen. Both
the direct controller-container probe and the real Harness `initialize` path passed. The v162
initialization failure did not reproduce with the same pinned Harness checkout, helper, controller
image, explicit nested Docker endpoint, and retained task-image data volume.

V164 made zero provider requests and calls, executed no HWE task or official verifier, created no
trajectory, and admitted no data. The result supports treating the v162 `RuntimeError` as a
transient controller-initialization infrastructure failure rather than a deterministic endpoint,
image, mount, permission, or Harness configuration defect. This inference does not prove that a
future provider-bearing episode will succeed.

V164 does not authorize a provider retry. A separately versioned v166 authorization may bind this
complete result and prepare a new one-use official-matrix identity with fresh socket, control,
runtime, output, and receipt paths. It must preserve the frozen five-task order and model protocol,
revalidate the retained volume and all task/image locks, and remain fail closed at the provider
marker. Until that authorization is merged and its post-merge `main` run is green, provider
execution remains closed.

## Implementation and execution gates

- v164 implementation commit: `872e3eba5c36fd5f52a13753025b384d4be90255`
- v164 authorization merge/source commit: `b94d50ad3e4bef9f49df70f8af1cab0c2a1c3095`
- v164 pull request: [#190](https://github.com/jdzhu19/VeriGym/pull/190)
- branch-push run `33970192996`: eight of eight job classes passed
- pull-request run `33970204660`: eight of eight job classes passed
- post-merge `main` run `33970415999`: eight of eight job classes passed
- manifest file SHA-256:
  `9f96a2f505b4d3f84b6ba1fc061320efd5cc2b69b43be5dc37dca52bb2c0f936`
- manifest canonical hash:
  `570ebd074536732f3d7128741ec5a3cf0d359fed12ebce36a3145cd39a0b85ab`
- runner SHA-256: `9255fa993170f04d8694a353c8aece50f10dfcba01a72fcfe6e8bf114181c46a`
- launcher SHA-256: `df0c5c7493e61ef44ef8384fdcee7c79335c3fd0b7fdf48205875ce11a45e722`
- authorization SHA-256:
  `388dbc40561c50c134c03e6c440b5199ebbf1bf03de9c56dc7552401728def0e`
- campaign implementation SHA-256:
  `a0dcbf3d0a49f2fc85e1fcb6fd96c330471cc5ea215e959b62864149bc52b561`
- structured process module SHA-256:
  `710269e4c3be6cf084fbf7f744f14496ceffd2325f313380cde8e866ab6cfa24`

The launcher was invoked exactly once from clean, merged, up-to-date `main` after the post-merge
run completed. Four ambient blocked provider names were present. The launcher selected them by
name without reading their values and removed them, along with all other frozen aliases and Docker
endpoint variables, before starting the child. No concrete provider or proxy value was printed,
persisted, or hashed.

## Immutable execution evidence

The frozen v164 evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v164-controller-initialize-diagnostic-v1`

It contains one directory including the root, nine regular files, zero symlinks, and no other
filesystem objects. The files total 11,036 bytes. The directory is mode `0700`; all files are mode
`0600`; all are owned by UID 1004/GID 100. Every canonical self-hash validates. Terminal progress
and report are byte-identical. The complete evidence-tree hash is
`53f31166e17c5c02254091bfe126bcd829abe213771e44b8c0447e99d492aa0e`.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| predecessor | `b24a0447f8954338b2aec664abfae035ed02d1bdcda66c1fa5890d72567c4476` | `83887347462203186fee4b7ff182ef4de63e382a38fd20499c029c00bc200263` |
| host headroom | `e05196d51bd8f117831269b1a08de9c8c8beb4eec9f5866a651612122f959f22` | `f5fa26bcbc0e5fba8ac0473c06d27a17d65d1897bc5d72dd15c7037cceeca056` |
| DinD runtime | `68bc1deceef21659c730eef0b6e9bf586b391890eae3dcb704699cfd03a97152` | `ada1766ca1135a765d34b2771e67f8b75927e308f268525047dbc3661f30c4c4` |
| network | `b2cc332149fffd2bcbb698475c0650cd52c7598f39d24f4c5d768c583e8f1f62` | `34ec5f523a0ab2386d1c96593be9ef4391df015e8342df91fb7bf8df48160519` |
| direct controller probe | `3d462724de62d4172349bb70e61b33951a966b9b2a07bd8a142f7339e2fd4b3b` | `ef927ca508dc1bc5dc2c9bc1634fa93982a6ecc96951cd91aa1e0586f77ac4f1` |
| Harness initialize | `229e51d516f2f6d6c9a57163d3e38a46cc289b1f60e5af02247cc65c883b5e9f` | `dbfcc2ba14598359384fba01f38f55333675aad0021af1ccdbabe1f07a3a8de9` |
| socket cleanup | `5359199b2d4e49da07ed0555f37c518ae2fbda73898a4e8c6da813fbc665a1aa` | `234466b782460c88884c5a86ffabb466c9a34a140628ba85f4ff08b5b41baffa` |
| report/progress | `3f2ca562607fa8a91c7abdacef0cbfd2eb2c7cfc27a08b3783477500adc6b0ba` | `c0caeaeda0ecb95f5649f6dcf9f2a54920c1e826fb6a60b3e1c189271178513f` |

## Diagnostic result

The predecessor receipt revalidated the frozen v162 tree and its zero-consumption boundary. The
absolute host-root gate passed before Docker access with 18,894,151,680 free bytes and 25,955,197
free inodes. The DinD runtime used the exact retained v158 bind backing, VFS storage, `runc`, and
the same host/inner data-root inode; host Docker storage did not hold task layers.

The direct probe passed every recorded control: immutable controller ID, explicit nested endpoint,
dedicated bridge, non-root identity, read-only root, capability drop, no-new-privileges, private
PID/IPC namespaces, init and resource limits, bounded tmpfs, exact source/session/broker mounts,
bounded empty output, provider environment absence, and container removal.

Harness initialization then passed with the pinned configuration fingerprint and explicit v164
Unix socket. It returned zero events, no finish reason, no final response, no format repairs, and
zero run intervals. The provider marker remained absent and the provider call/token counts stayed
zero. The two synthetic values produced zero persisted hits; no private session or broker file was
left to retain.

The DinD runtime receipt's `v158_data_volume_reopen_count=1` denotes the single reopen performed by
that runtime. The terminal report's cumulative chain count is two: one v162 reopen plus one v164
reopen. This field scope is explicit here so neither value is relabeled or rewritten.

## Cleanup and successor boundary

The v164 sidecar, direct controller, Harness controller, and inner bridge were removed. The
owner-bound v164 socket volume no longer exists. Its backing, the v164 control root, and the v164
runtime root are empty, mode `0700`, and owned by UID/GID 1004:100. No container uses the retained
v158 data volume.

V164 is consumed and must not be rerun. A future v166 matrix must use a new identity and must treat
the retained volume's cumulative reopen count as two before it starts. It must not relabel the
v162 or v164 outcomes and must stop on any image, inventory, provider-marker, infrastructure,
security, or cleanup drift.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
