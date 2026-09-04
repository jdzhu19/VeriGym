# DeepSeek Harness v141 audit of the v140 verifier-control scaffold

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v140-verifier-control-scaffold-v1` is consumed and stopped fail-closed. It
successfully materialized all five fixed tasks, including base-FAIL/reference-PASS qualification,
task-specific command-image construction, v2 scans, five DockerRuntime preparation probes, and a
network-isolated zero-provider Harness initialization. Its first socket-cleanup helper and the
best-effort cleanup helper both exceeded the inherited 60-second controller timeout before their
created containers started. The terminal status is `stopped_without_execution_scaffold`, the stop
reason is `TimeoutExpired`, and the report canonical hash is
`30064d0bbd8332dc30c4908c2f42cc8addd6e204243f12686283d1e8bca192f9`.

The v140 atomic scaffold contract was not published. No provider request, model process, candidate
task execution, modification, trajectory, collection, or training started. All five tasks remain
provider-unconsumed. The planned `deepseek-harness-hwe-v142-official-matrix-v1` identity is
unreachable and is not authorized.

## Implementation and merge gates

- v140 implementation commit: `443c637f4008b27600abfa1c9dc51e4627f5e3b0`
- v140 authorization merge/source commit: `1f0b090ddd13998c6772f41f104cc27d375af5bc`
- v140 pull request: [#166](https://github.com/jdzhu19/VeriGym/pull/166)
- v140 branch-push run: `33892064323`, eight of eight jobs passed
- v140 pull-request run: `33892093442`, eight of eight jobs passed
- v140 post-merge `main` run: `33892639380`, eight of eight jobs passed
- v140 manifest file SHA-256:
  `6fa8856d49185893fe0dd67c38a4e0137451b80200c39a5af375908229c458b9`
- v140 manifest canonical hash:
  `ccd0e7927fde7d72ca0638bf5081b994d30a505e5e28c2ad869791f6ae1e236c`
- v140 runner SHA-256:
  `b80d5bb043b00ecdda48e39fd5c5ee06effc9eaf68049f12db13dd4b077c273f`
- v140 authorization SHA-256:
  `9b653391be4a750db13dfc8966d9927f9551891159ca33b209cacc2698823622`

The authorized child removed every frozen provider variable and ambient Docker endpoint variable
before its single start. Its source was the exact merged `main` commit after the post-merge gate.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v140-verifier-control-scaffold-v1`

It contains 1,784 directories including the root, 10,490 regular files, and zero symlinks after
the separate late-cleanup receipt was added. Structured evidence accounts for 18 mode-`0700`
directories and 63 mode-`0600` files; the five prepared public source trees account for 1,766
mode-`0755` directories and 10,427 mode-`0644` files. Every listed canonical self-hash validates,
and the atomic progress and terminal report are byte-for-byte equal. An in-memory scan compared
the four available nonempty provider values with every evidence file without printing or hashing
the values and found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `4eca75c809e3c3404b950fc9135d38c27a1163fd45383bd59e07241139ee2312` | `30064d0bbd8332dc30c4908c2f42cc8addd6e204243f12686283d1e8bca192f9` |
| headroom preflight | `a888fdec80a514f8ca6469029e9a034aff17a25e7548c876ec1dfd15cc5029b8` | `b8af99c93d69afdaf71fc5e779b561e20f9e4fd9bc9d4cde5be77bea0a1fbeb7` |
| DinD runtime | `68229bba640dae137e67718adda57694758df995353658ff2c7754a320c0a70e` | `07fc6776c0912af43c3c59dc623464fcb03f24010f668ac0a8b1ab044e9ddcbc` |
| image-transfer set | `ee1676b0ee8e7f9fbd52167dac4891f2ba931cfa343ff8ecb46d02f8f5cc004b` | `307bde9c94b34a9cc4346e47c11aa8f8a98dff999131edbd1423fd657c8ede58` |
| task-materialization set | `4656cdb563a1cf183d7de0f5b71352b41ef45d300a26c640e63bcd8f07f59baf` | `d6bad1e1b900fff5c11f43ede288615aefc3fb7ef35a4b7283971e2534b049b9` |
| initial/final inventory | `b3c3a887cd3aba1e5433aaca06e2ced0dd87a4883f7445317401e1f76c44d4a9` | `ff2f7abaf2dd15050e340f033deea44a235f9780375fef2dad5e19fca3227989` |
| runtime prepare | `640ad211a47c5381d773c73e61e7c5c87dab49b35abdeae180716f93df898c07` | `6f03fd57b6d0a0439f16916d14792b0b2e3326a309226c7de91860ef49cbbb5a` |
| Harness initialize | `ade7dff4d6371f68bf2a2d433e89b9673fd826d1b2ba8d68b7604b085400938f` | `df55b4f6baef6fc5f3e75c425df4c7612ab02beb6733b8a429e4fa7adb5efb2d` |
| late cleanup | `8ee7f5992942c1abde1590e6001a72cb1687896e930efc8532ecf2714d76ad0b` | `c1634996665e4bbb2600683efecc9c59b361ada609e64f13fd92de2f3168f9ef` |

## Five-task qualification result

All five completed local HWE archives were SHA/digest checked, explicitly imported through the
fresh v140 nested Unix socket, and matched their frozen image identities. Registry access and
`.partial` inputs remained absent. Every official verifier ran with `network=none`, returned the
expected base failure and reference pass, recorded the separate 300-second Docker control bound
and unchanged 900-second verifier bound, and confirmed its container removal.

| Task | Base | Reference | Verifier-control diagnostic hash |
| --- | --- | --- | --- |
| Ibex PR-465 | FAIL | PASS | `f43f37a5e48d2094710096639d1522a8d4d3342eb149e380e8251b12464cc78e` |
| Ibex PR-1135 | FAIL | PASS | `d55d402f02b569545890005517108bf9bd003a9072d07bd1511d2ace6b87fd5c` |
| Ibex PR-1780 | FAIL | PASS | `1ecede9f61bdfb70e488fa4774db421091650c8e1442e8351a0362859943c436` |
| CVA6 PR-2017 | FAIL | PASS | `0f1eb93b1b65f22f5c86e17fc312f9bf298e91b413d1bb897d9356ada4f35d3c` |
| CVA6 PR-2711 | FAIL | PASS | `ea823192a6c70043a1255daeb1a6ae4381628572fc7f37e08e62a71a98ce4f41` |

All five task-specific credential-free, Codex-free command images passed the bounded v2 scan and
produced locks. The final inner inventory contained all required images and no container or volume.
All five explicit `DockerRuntime.prepare` probes passed against the same nested endpoint with empty
post-probe inventories. The internal `verigym-hwe-net` existed only for the synthetic zero-provider
Harness initialization, was removed afterward, and the outer DinD remained `network=none`.

This establishes that the v138 verifier-control blocker is fixed. It does not establish an
execution scaffold because cleanup is part of the atomic publication boundary.

## Cleanup and resource disposition

The outer DinD daemon was removed before the primary cleanup call. The primary and best-effort
60-second `docker run` calls each left one exact v140 owner-labelled cleanup container in `created`
state; neither helper had started. Both were independently checked for the expected owner, role,
digest-locked DinD image, `network=none`, auto-remove policy, and exact socket-volume mount. One
duplicate helper and its anonymous image volume were removed. Starting the other already-created
helper under a bounded 300-second late-cleanup wait exited zero and auto-removed its anonymous
volume. No raw cleanup output was persisted or hashed.

The socket backing is empty, mode `0700`, and restored to UID 1004/GID 100. The socket volume is
removed and no v140-labelled container remains. Exactly one v140-labelled volume remains:
`verigym-deepseek-harness-v140-dind-data`, role `data`, with its bind device under `/data2`. It and
the full result tree are frozen and must not be reopened, inspected, mutated, retried, or promoted.
The separate late-cleanup receipt records cleanup recovery but does not rewrite the original
terminal report or make the failed atomic contract valid.

## Successor boundary

V140 must never be rerun. A fresh provider-free successor must use a new identity and fresh
bind-backed `/data2` resources, retain the now-qualified five-task and verifier-control semantics,
and widen only the socket-cleanup controller wait from 60 to a maximum of 300 seconds with
content-free stage and cleanup diagnostics. The frozen v140 data volume cannot be used as a
shortcut. Only a newly completed atomic scaffold followed by another independent merged audit and
green post-merge `main` checks may authorize an official DeepSeek matrix.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
