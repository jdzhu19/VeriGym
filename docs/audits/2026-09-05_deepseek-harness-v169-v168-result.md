# DeepSeek Harness v169 audit of the v168 real-configuration diagnostic

Date: 2026-09-05

## Decision

The one authorized execution of
`deepseek-harness-hwe-v168-real-config-initialize-diagnostic-v1` is consumed and must not be
rerun. It reproduced the exact v166 Harness initialization payload while supplying the two real
provider configuration values only in child-process memory. Harness initialization passed, the
first-request marker was not observed, and there were zero provider calls and zero provider
tokens. The v166 initialization failure therefore did not reproduce.

This result rules out a stable failure caused merely by supplying the real two-name provider
configuration to the frozen Harness initialization path. It does not identify the unique cause of
the v166 `RuntimeError`: a transient controller/helper/process failure remains consistent with the
evidence. It also does not test provider reachability, authenticate to the provider, execute a
task, run an official verifier, create a trajectory, or establish a benchmark result.

A successor may separately authorize a replacement official matrix under a fresh identity. It
must preserve the v166 task order, model and Harness protocol, use the still-unconsumed per-task
provider budgets, stop under the existing fail-closed policy, and bind the cumulative retained
v158 data-volume reopen count of four before authorizing at most one additional reopen. This audit
does not itself authorize that matrix, any provider request, collection, SFT, or training.

## Implementation and execution gates

- v168 implementation commit: `ebcb55c180e4ba0ac838be1d78ef6fe27e74b0c3`
- v168 authorization merge/source commit:
  `282e7f627f29b3967f75c75d311c97ab350bddaa`
- v168 pull request: [#194](https://github.com/jdzhu19/VeriGym/pull/194)
- branch-push run `33974749079`: eight of eight job classes passed
- pull-request run `33974751965`: eight of eight job classes passed
- post-merge `main` run `33974998196`: eight of eight job classes passed on the exact merge
- manifest file SHA-256:
  `24bfdc937718e12d60e4590d01d22d3241e8cf8a9da43eea9f7302adab2ebaa9`
- manifest canonical hash:
  `cc0f1afa54416f3806a13c7afe963559c792cbf723748c47fb85c5635be04fdb`
- runner SHA-256:
  `46c81870b96f5f213620b00e2eb2a9bf7338680882937779c2da89ef3e64047e`
- launcher SHA-256:
  `2ee17360279c3e29260b7c199c9a962ba552f2619167247b28f867a02dba478e`
- authorization SHA-256:
  `4241b09fe5f36999472af81c9493b350284a42b7b2317bb85e035afaa8dee22d`

The launcher was invoked exactly once from clean, merged, up-to-date `main` after the post-merge
run completed successfully. Before execution, the host root had 16,745,725,952 free bytes and
`/data2` had 36,400,774,504,448 free bytes. Both required provider environment names were present;
the preflight inspected only their presence. The launcher removed all provider aliases and Docker
endpoint variables, then restored only the two required DeepSeek names for the child.

## Immutable execution evidence

The frozen v168 evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v168-real-config-initialize-diagnostic-v1`

It contains one directory including the root, nine regular files, zero symlinks, and no other
filesystem objects. The files total 11,700 bytes. The directory is mode `0700`; every file is mode
`0600`; all are owned by UID 1004/GID 100. All nine canonical self-hashes validate. Terminal
progress and report are byte-identical. The complete evidence-tree hash is
`b2220e911a1406f0579f89ffd7db01ffb6aea5a8a75b5779c75aa2aff8f339bb`.

The independent audit compared the two distinct nonempty provider values with all nine files in
memory without printing, persisting, or hashing either value and found zero matches. The execution
receipt independently records zero value hits, no raw stderr or exception persistence, and zero
private diagnostic artifacts requiring removal.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `6a890ac493c43300256d3fd8210681c6aefdede34882f704fd830a8640a3724d` | `8a1763484f27b5ef736f4fa9cc214f085d8b19e92055412d3531c0a887798694` |
| Harness initialize | `cc74eefa91ab37e0b502a9608e456c49c896e9068f3dd3bb52bfa5b4b7da417c` | `e42c1183991140d309c829cc3b670a5eed365eca62fd18161c6c3675d50025fc` |
| direct-container probe | `8490b7a5374cf562a084c3f7fc4ef6904a541315b56308af23cc846584901ca1` | `1747aa36a441da18d1978e4bf0f55ff0b39dee758b9d1315c6432cdd21ec0c2c` |
| socket cleanup | `e7fab59e7ac717b47c16d3e1f1b709ed1f742255277c8868580b3e685558a50f` | `c74bd4b1e8e7c4f3a43a01e2ef88035b94f3493fc83b5fcf3bbc3b8419f12b8f` |
| DinD runtime | `989c0695ef9b88abdad8b50e5a0db23a47ed4eda3ca1e437164d9c943477c74f` | `8e3a0dfafc4796e719da6abecc84294c176860c923227a5774e34d7837093d9d` |
| host headroom | `fc285934c96dabd978ea89eab91f8283614e0ab913b20e0c0092ce63b62bc826` | `67081d9dc8aa95f1a2e9f2e63c3366d3c901aac9aaaff6529b9554bd719bc752` |
| network | `12610235e026f7c3b283d4d0918684feaff140114850b70c4c6d69dcd834914e` | `dfcfe8a44c733138866e744a6c6524120a22d99ca440ed37647d9002bfe387e6` |
| predecessor | `23121f1bf62959413bf44547fc2f09a00b881bc0c60f09df9c20f9f8a57b313e` | `6bab82876cf4a4ce08ed67c4b6801a9b7643e999cc37f79c0258ec5a9cbac309` |

## Diagnostic boundary

The absolute host-root gate passed before Docker access with 16,746,057,728 free bytes and
25,955,194 free inodes. The direct controller-container probe passed with the frozen controller
image, explicit nested Docker endpoint, non-root user, read-only root, private PID/IPC namespaces,
all capabilities dropped, no-new-privileges, bounded resources, and no provider environment.

The retained v158 data volume reopened once, bringing its cumulative campaign count to four. Its
runtime receipt validates the exact `/data2` bind backing, VFS driver, `runc`, host/inner inode
equality, and absence of task layers from the host Docker root. The provider controller used the
dedicated `verigym-hwe-net` bridge. Task and verifier networking remained fixed to `none` and
neither was executed.

The Harness receipt records `real_provider_configuration_used=true`, exactly two environment
values, the frozen v166 initialize payload, a bound settings endpoint, `helper_status=passed`, and
`diagnostic_category=passed`. It also records `provider_request_started=false`, `provider_calls=0`,
and no task execution. The final diagnosis
`v166_initialize_failure_not_reproduced_with_real_configuration` is therefore supported by the
published evidence.

## Cleanup and successor boundary

The v168 sidecar, controller, and inner bridge were removed. The owner-bound v168 socket volume no
longer exists. Its backing directory and the v168 control and runtime roots are empty, mode `0700`,
and owned by UID/GID 1004:100. No container uses the retained v158 data volume.

V168 may never reopen the retained volume again. A successor must either explicitly bind the
cumulative count of four and independently authorize exactly one more reopen, or use a fresh
owner-bound data volume materialized only from locked complete local archives. It must also use
fresh output, control, runtime, socket, and campaign identities.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
