# DeepSeek Harness v163 audit of the v162 official matrix

Date: 2026-09-05

## Decision

The single authorized execution of `deepseek-harness-hwe-v162-official-matrix-v1` is consumed and
must not be rerun. It stopped fail closed on PR-465 with
`stop_reason=pre_provider_infrastructure_failure`. The provider marker remained `not_started`, so
the run consumed zero provider episodes, zero provider calls, zero provider tokens, and zero task
provider budget. PR-1135, PR-1780, PR-2017, and PR-2711 were not attempted.

No trajectory was admitted. Both `trajectory_collection_migratable` and
`sft_path_migratable` are false, and this result is not a benchmark score. Formal collection,
ordinary collection, SFT, and production training remain closed.

The failure is localized to the Harness controller initialization boundary after the five fresh
task-runtime prepares. The intentionally sanitized v162 result records only `RuntimeError`, not
the helper's raw exception or stderr, so this audit does not claim a more specific cause. A new
identity may perform a bounded, synthetic-credential, zero-provider controller diagnostic after
its own merged authorization and green post-merge gate. This audit alone does not authorize that
diagnostic, a provider retry, or another reopen of the retained v158 data volume.

## Implementation and execution gates

- v162 implementation commit: `63c47f27bb430fd639bfe7a14fe16a756fd2d389`
- v162 authorization merge/source commit: `22bef6516b83048ccd71f7b1b65a0b4ff291f7ef`
- v162 pull request: [#188](https://github.com/jdzhu19/VeriGym/pull/188)
- v162 branch-push run: `33966948515`, eight of eight jobs passed
- v162 pull-request run: `33966951303`, eight of eight jobs passed
- v162 post-merge `main` run: `33967203488`; its first Docker security attempt failed in an
  unrelated fake-Codex integration test that had passed in both pre-merge runs. The failed job was
  rerun once, passed, and the final run state is eight of eight successful job classes.
- v162 manifest file SHA-256:
  `fa394fcde9fda0de8f43e80981a14d591c93d379ae066a0381b7e92110111531`
- v162 manifest canonical hash:
  `a8fe31eff7419815272356fb2e12715b09833aaf8b79fbe747082f9a640495e3`
- v162 runner SHA-256:
  `90dcbc8dd88a7377ea7151c57dd9a2917e41b1ea9943a35631078d1a16f48ee1`
- v162 launcher SHA-256:
  `c3aaf66b4006e5a10c751c4c0ecbe97f927ab1fa21e1331dbf2404d93506bdee`
- v162 authorization SHA-256:
  `d818664222fbf1923e72def329210f0ed0d3c0ff84412d299a753bf8dfa315fd`
- campaign implementation SHA-256:
  `fcf3c1362e021ff1d6540f5afe67b686d2a54540238304c6f8f29535aaa643be`

The launcher was invoked exactly once from clean merged `main`, after the post-merge run had
reached its final successful state. It selected provider environment names before values, passed
only the two required provider names into the child, and did not print, persist, or hash either
value.

## Immutable execution evidence

The frozen v162 evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v162-official-matrix-v1`

It contains nine directories including the root, seven regular files, zero symlinks, and no other
filesystem objects. The files total 19,574 bytes. Every directory is mode `0700`; every file is
mode `0600`; all are owned by UID 1004/GID 100. All seven canonical self-hashes validate. The
terminal progress and report are byte-identical. The evidence-tree hash is
`b5edb9f26d6df006e940a66c230e9ca3deda9cee2fff4a40b853fd7939cc27b2`.

An in-memory scan compared the two distinct nonempty provider values with all seven files without
printing, persisting, or hashing the values. It found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| PR-465 attempt | `250a55968ea0d381b2401619ea9f0bd9d2ae9a686cdc263c2259103feca41cb5` | `9dbda2b939c4762c1ce843bd79bcb17e1794816f0b899cc0224302d72d98d17c` |
| socket cleanup | `c64098515d0119cf19f500709b85fa797f44628e3dd130c1936ca76cba264ca5` | `71d9a57818bc4ea06d54e89abe0c6b9af904e3f7573dae23ed856d3733bb6804` |
| host headroom | `cefc6e5f3c3bdb5669517e58a535b3c1ac9d3678024d0c37e8d7f29f8649901f` | `34a3069805f894430f9ac5fe44a9b368e6efd0107c98c2dc590012aa1a0eae97` |
| report/progress | `f3da4046870d15f4f799296d7a8a0354995e566e22b98d949b6a684afe204be3` | `29bd573e93e063801955bc74cc4bc3705c5904069c2b7bf6546b4254571d9d33` |
| provider DinD runtime | `f6093d02113f9adc3ffcd4c2ae1cb0c01e3fff4d55158677e9f3f847cb6aa969` | `3c510f16ad63ead6839cf246f45390147dd5f2f030d4e92ea6f51c59650740e9` |
| provider network | `8322d3c5af77ff597324fbd4d9523a3a021b85e050a85e10b11fb388c04b44cf` | `4ef93835bb868f08f8d68ebf87493acf810bb76ae926355be25a22e51114e537` |

## Failure boundary

The host-root headroom gate passed with 18,894,561,280 free bytes and 25,955,197 free inodes before
the first Docker access. The retained v158 DinD data volume reopened exactly once. Its runtime
receipt confirms the `/data2` bind backing, VFS storage driver, `runc` default runtime, exact
host/inner inode identity, and no use of the host Docker root for task layers. The dedicated inner
provider bridge was created and validated while task and verifier networking remained `none`.

All five runtime prepares occur before the empty Harness session and broker directories are
created. Those directories exist, while no `zero-provider-preflight.json` was published. The
terminal exception class is `RuntimeError`; `resolve_settings` reports configuration failures as
`ValueError`. Together these observations localize the failure after the task-runtime loop, in the
sanitized Harness helper initialization call. No provider request marker, task run directory,
candidate edit, transcript, decision record, dataset, or task/verifier result exists.

PR-465 is recorded as `infrastructure_failure` with all six admission planes false,
`first_effective_modification_action=null`, `exact_64k_eligible=false`, and
`provider_consumed=false`. The matrix then stopped immediately as required. This is an
infrastructure failure, not a verifier rejection and not evidence about DeepSeek's task-solving
quality.

## Cleanup and successor boundary

The v162 provider DinD container and inner bridge were removed. The owner-bound v162 socket volume
was removed by a `network=none`, read-only-root cleanup helper with all capabilities dropped except
`CHOWN`, `DAC_OVERRIDE`, and `FOWNER`. Its backing directory is empty and restored to mode `0700`
and UID/GID 1004:100. The v162 control and runtime scratch directories are also empty.

The retained volume remains `verigym-deepseek-harness-v158-dind-data`, with exact v158 owner and
`data` role labels and bind backing
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v158/data`. No container uses it. It must not be
reopened again under v162.

A successor diagnostic must use a new immutable identity, synthetic provider values, initialize
mode only, zero provider requests, bounded categorized errors, exact endpoint binding, fresh
owner-bound socket/control/runtime paths, and explicit cleanup. It must not execute an HWE task or
claim provider authorization. A later provider retry requires a separate audited authorization;
it may not reuse v162 seed/sample `502/18` under the consumed v162 identity.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
