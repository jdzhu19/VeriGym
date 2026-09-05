# DeepSeek Harness v171 audit of the v170 official matrix

Date: 2026-09-06

## Decision

The single authorized execution of `deepseek-harness-hwe-v170-official-matrix-v1` is consumed and
must not be rerun. It stopped fail closed on the first scheduled task, Ibex PR-465, with
`stop_reason=pre_provider_infrastructure_failure`. The provider marker remained `not_started`, so
the run consumed zero provider episodes, zero provider calls, zero provider tokens, and zero task
provider budget. PR-1135, PR-1780, PR-2017, and PR-2711 were not attempted.

No trajectory, candidate modification, verifier result, decision row, or candidate dataset was
created or admitted. Both `trajectory_collection_migratable` and `sft_path_migratable` are false,
and the result is not a benchmark score. Formal collection, ordinary collection, SFT, and
production training remain closed.

The failure is localized to the Harness controller-initialization boundary after all five
task-specific runtime prepares. The same real-configuration initialization had passed once in
v168, but the full v170 path again recorded `RuntimeError`. The sanitized evidence intentionally
does not retain the structured helper error, stderr, a raw exception, or provider values. This
audit therefore does not assign the failure to credentials, endpoint syntax, provider
reachability, Docker storage, an HWE task image, or any other unique cause.

The official-route five-task experiment has not produced collection evidence. A successor may
separately authorize the planned PR-1816 open-toolchain qualification, official-verifier
comparison, and later research-only canary only under fresh identities and the original phase
gates. This audit does not authorize those executions, another official matrix, a provider
request, collection, SFT, or training.

## Implementation and execution gates

- v170 implementation commit: `a92e64d90aff70c0e340d3efbd6b6cd0f3422aa2`
- v170 authorization merge/source commit:
  `7f1f98f97f13597626023225d8c854ecb1d8adc8`
- v170 pull request: [#196](https://github.com/jdzhu19/VeriGym/pull/196)
- branch-push run `33976667398`: eight of eight job classes passed
- pull-request run `33976679717`: eight of eight job classes passed
- post-merge `main` run `33976979942`: eight of eight job classes passed on the exact merge
- manifest file SHA-256:
  `59a7c188a1c5c1cf98dd0fc4959d907929781f91533806c08bf2264420aefbe4`
- manifest canonical hash:
  `1e7c29b95ee380d5fb50df33a31d6a57f8cd2b1db329a2c6d3f527d02c152256`
- runner SHA-256:
  `07753601460889a57acd4f5fedea55cef3401475dfccce562f296fb61c75d356`
- launcher SHA-256:
  `2f8c9968444aecedb34fe415956a234d5b3f67d7f7fc29fa8a7251beacdb7213`
- authorization SHA-256:
  `5d5e191f59a8449192c9dba29da153e26d0a5cd1ec37325779186520b79b6c0f`

The launcher was invoked exactly once from clean, merged, up-to-date `main` after the post-merge
run reached its final successful state. The read-only gate confirmed that both required provider
environment names were present without reading or printing their values. It also confirmed
16,748,163,072 host-root free bytes, 25,955,194 free inodes, 36,350,360,752,128 free bytes on
`/data2`, the exact controller and DinD images, the dedicated bridge, the retained volume's exact
`/data2` bind, and absence of v170 resources.

The launcher selected environment entries by name before reading their values, removed the
frozen provider aliases and Docker endpoint variables, and restored only the two required
DeepSeek names in the child. No concrete provider or proxy value was printed, persisted, or
hashed.

## Immutable execution evidence

The frozen v170 evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v170-official-matrix-v1`

It contains nine directories including the root, seven regular files, zero symlinks, and no other
filesystem objects. The files total 21,358 bytes. Every directory is mode `0700`; every file is
mode `0600`; all are owned by UID 1004/GID 100. All seven canonical self-hashes validate. Terminal
progress and report are byte-identical. The complete evidence-tree hash is
`ba2438b8a8a3a7aeace0d29b4e16a9f8ebb64a0a483b795085419807350b5001`.

The independent audit compared the two distinct nonempty provider values with all seven files in
memory without printing, persisting, or hashing either value and found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| PR-465 attempt | `5398ed10359be4d35d1a02c19a5affcef981a1d2d40364144c21dbdaccad2a47` | `928a476e6b86059deb9699984a9a7cb94c33b2b9322c43a68c1ad1e838eeed06` |
| socket cleanup | `aaface87874f9decb08df4dba93834be6035e56d0bd80a3c8a6ceb14f5dc064c` | `14b1ae17c247d2cba8d0987b0e41529e9fb5089d4846ca81500af1eb539148e8` |
| host headroom | `e69e3e868d08329cdf2b9f2da31cd01f41701433b78e932a2e3fea653161716e` | `fe99e5e0e368ff99dde68293f4a9704ae741c75bc7a454bdb41e1e14319d5d63` |
| provider DinD runtime | `89483fc5b42ab41982fd9da0b494c2295fa37c362e71f11752e59c0d25a5f518` | `54f9d8ca72e746a742b1b0cb0f83425e86c5eb49dfe05711212bc0ce80fd8a44` |
| provider network | `d80a254e5fb407bc635c4df39803f77938f70b1127d754802641f330d8c18733` | `901366ecc64c26551abfcde58701dcd8ca545724f23d70bd25d3c75fb7e5c938` |
| report/progress | `bb475f942c53d7ecec8712e1a74223a96e54e320a445780b30127d80890a9631` | `faece2a1e7d96c2cd195baae689137b5d8497aeb915bc55dca2779d725156751` |

## Failure boundary

The execution-time absolute host-root gate passed before Docker access with 16,748,195,840 free
bytes and 25,955,194 free inodes. The runtime receipt validates the exact `/data2` bind backing,
VFS driver, `runc`, host/inner inode equality, and absence of task layers from the host Docker
root. The provider bridge was created and validated; task and verifier networking remained fixed
to `none`.

The presence of the empty `preflight/harness-session` and `preflight/harness-broker` directories
shows that all five explicit runtime prepares completed and the Harness initialization stage was
entered. `preflight/zero-provider-preflight.json` is absent because initialization did not return
a valid zero-provider result. No task root, provider marker, transcript, security scan, decision
row, candidate change, or verifier artifact exists. The only attempt is PR-465, recorded as
`infrastructure_failure` with `exception_type=RuntimeError`, all six planes false,
`first_effective_modification_action=null`, and `exact_64k_eligible=false`.

V168 proved that the same real two-name provider configuration can pass initialization without a
request. V166 and v170 each failed at that boundary, while the five v170 task runtime prepares and
the `/data2` storage checks passed. The combined evidence is consistent with an intermittent
Harness controller/helper/process failure, but it still does not identify a unique root cause.
Repeating v170 would violate its one-use authorization and would not add the structured helper
diagnostic that the sanitized result omits.

## Cleanup and successor boundary

The v170 sidecar, Harness controller, task probe resources, and inner bridge were removed. The
owner-bound v170 socket volume no longer exists. Its backing directory and the v170 control and
runtime roots are empty, mode `0700`, and owned by UID/GID 1004:100. No container uses the
retained v158 data volume.

The terminal report's cumulative v158 data-volume reopen count is five, equal to its frozen
budget. V170 may never reopen it again, and a successor must not increase or relabel that budget.
Any further Docker-in-Docker phase must use a fresh owner-bound `/data2` backing and materialize it
only from digest-locked, complete local archives; it must not pull from a registry or use a
`.partial` archive.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
