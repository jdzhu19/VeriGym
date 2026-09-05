# DeepSeek Harness v153 audit of the v152 host-headroom scaffold

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v152-host-headroom-scaffold-v1` completed successfully. It proved that the
host root filesystem had the required absolute byte and inode headroom both before and after a
fresh bind-backed `/data2` DinD lifecycle, started the exact local DinD image, qualified the exact
Docker server identity, observed an empty inner mutable inventory, and completed deterministic
cleanup. The terminal status is `completed_pending_independent_v153_audit`; the report canonical
hash is `db4e01ad7c7b476172a642711b34f06901ede51a0487440d38b42c17271fb6b3`.

No provider request, task archive read, HWE task materialization, official verifier, Harness
controller, model process, registry access, candidate modification, trajectory, collection, or
training started. Provider calls and tokens are zero. V152 is frozen and must never be rerun.

Subject to this audit being merged and that merge's `main` commit passing all eight ordinary
Actions classes, a distinct v154 authorization may preserve the still-unconsumed v150 official
matrix. This audit does not itself authorize provider execution or reopen the retained v148 data
volume.

## Implementation and merge gates

- v152 implementation commit: `3ab6b5d2df65a315e593d33a2d279ec1729a01ff`
- v152 authorization merge/source commit: `62c887abcd3416d6e3aceb01d48ab439e9dbe406`
- v152 pull request: [#178](https://github.com/jdzhu19/VeriGym/pull/178)
- v152 branch-push run: `33954500687`, eight of eight jobs passed
- v152 pull-request run: `33954503203`, eight of eight jobs passed
- v152 post-merge `main` run: `33954713104`, eight of eight jobs passed
- v152 manifest file SHA-256:
  `ebd71e07ed6368cdbe76ab71c09e4cf4efcc9032ed2dea4ccc80868768c04ee5`
- v152 manifest canonical hash:
  `47281bc99187fb22d26606f3d7065462b60262a1678f84a1c694f72675ac1478`
- v152 runner SHA-256:
  `d2dfa9aa09713ff7361452bd6e41d58170362b645bc28f70729424f18569a529`
- v152 authorization SHA-256:
  `e4be187d5bb57c17205359b4c58db3983c1ed3819dc312a6bb353eba5c5c7aa7`

The runner was invoked exactly once from the clean merged `main` commit after the post-merge gate.
Its one-shot environment refused all twelve provider configuration names and both Docker endpoint
variables. No provider or proxy value was printed, persisted, or hashed.

## Immutable execution evidence

The frozen evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v152-host-headroom-scaffold-v1`

It contains one directory including the root, eleven regular files, zero symlinks, and no other
filesystem objects. The directory is mode `0700`; all files are mode `0600`. Every JSON canonical
self-hash validates. The terminal progress and report files are byte-identical. An in-memory scan
compared three distinct nonempty provider values with all eleven files and found zero matches
without printing, persisting, or hashing any value.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| cleanup receipt | `96c25e475111a6bdbcbf46a28d3439bd9c53ef9f0d94333e328c97996000e669` | `a19b88a1777dbfe7889780cfc828f5d93acabeba016a7aea0e1e80d5adceba7b` |
| host image identity | `0fb47b6ffc025ff0347e80018490a3f517a53f20758f7250dbea75699b572768` | `5dcb8e0bb4cea33c761a9070a512740a44de4b7e4e0dcfcb93f7490976c142df` |
| host-root headroom after | `3192f51fd477de06eab3c188473bb1bd98dd71581daf646e7cc30c4f49850940` | `e8059f40be65cef18af0362b32a5af0a23b55fcb9f4563ba1a234f5a4df77f77` |
| host-root headroom before | `d28f69fd3b119b55809311d6880dfbac34604e34f2aad7e5f1a181c642d95e43` | `04098ccdc94873e40875b2df5d29eb3734d4f1207066fa5772c0b6c4174404ed` |
| host-runtime scaffold contract | `e35eddfafea15b36719cde632939f69003d81133b80049bc2aafa0257f12c58d` | `610d2f7a80271d872c4d1cc90cac3b7c9df08db92f91b7257a6b4941a4c292d1` |
| inner-inventory receipt | `014544e3acb06953741a3f09b6ccdd5fa06ce1529a888cf2992b3134f9b3a87c` | `b78d3e670a7eff4b7a9146c914a3563a0dbed0b1b22156d711c65646465cfda0` |
| predecessor preflight | `4cc5e869205c365d8b676de421ff40fe8c6fdeb4594f7f7e592196058e439b39` | `b64b4c6cf17a5d2955819659fa445e808cd6eb6b08a7ecd08350191eba6e8e5b` |
| readiness probe | `a6479e7be39f49f6720d41d7cd984077a155033d41e12c30629a86135128486d` | `e5188586bd9910115099e6cd12870f929b2913cc48d436ad7b2bcede3d0fba1b` |
| report/progress | `c4cd681bbc9079e3957e5b120e1530bcfaa93d3a59e6727c5902b9af39f98553` | `db4e01ad7c7b476172a642711b34f06901ede51a0487440d38b42c17271fb6b3` |
| volume-setup receipt | `cbd2f7cbd84e903c9478827fb5f33fbe277ef45c9dd45421a17d0ceae52aff30` | `1462a0a392445a20d52b333df5d25de6670866404d0b6586200d9b78f2003743` |

The report records `provider_request_started=false`, `provider_calls=0`, `provider_tokens=0`,
`model_process_count=0`, and `provider_execution_authorized=false`. The contract remains only a
non-provider scaffold pending this audit and its post-merge gate.

## Host-root headroom and DinD identity

The absolute host-root gate required at least 4,294,967,296 available bytes and 100,000 available
inodes. The before receipt observed 9,324,367,872 bytes and 18,227,684 inodes; the after receipt
observed 9,324,273,664 bytes and 18,227,500 inodes. Both gates passed. Percentage-used values were
not gates.

The outer sidecar used the exact local `docker:23.0.6-dind` identity, `network=none`, the `vfs`
storage driver, disabled bridge/iptables/ip6tables behavior, and fresh v152 data and socket
backings under `/data2`. The bounded monotonic readiness check completed on poll 14. Its three
explicit predicates all matched: server version `23.0.6`, storage driver `vfs`, and default
runtime `runc`. The startup attempt count was one; the outer control inspection passed.

The inner container, image, volume, and custom-network inventories each returned exit zero, zero
observed objects, empty stdout and stderr, no timeout, and no truncation. No inner Docker network
was created.

## Cleanup and predecessor isolation

The exact v152 outer container was removed. The networkless bounded cleanup helper was attempted,
returned exit zero with the required empty stdout and stderr, and was itself removed. Both exact
v152 Docker volumes were removed. The data and socket backings are empty, mode `0700`, and owned by
the invoking host UID 1004/GID 100. A fresh read-only residual check found no v152-owned container
or volume.

V152 did not inspect, mount, mutate, or reopen the retained v148 data volume or its socket identity.
The v148 reopen count therefore remains zero. V152 did not touch any v148, v150, downloader, VPN,
proxy, registry, or host Docker-daemon configuration. No partial archive was used.

## Successor boundary

V150 and v152 must never be rerun or relabelled. V153 is only an independent result audit. After
this audit is merged and all eight post-merge `main` Actions classes pass, a fresh, one-use v154
authorization may preserve the exact v150 task order and seed/sample `502/18`, together with every
v150 protocol, source, image, agent-toolchain, official-verifier, credential-boundary, stopping,
tokenizer, exact-64K, and cleanup control.

V154 must bind the exact v152 report, scaffold contract, before/after headroom, image identity,
readiness, inventory, volume-setup, cleanup, and this v153 audit. It may budget the still-zero
single reopen of the exact retained v148 data volume, but must use a fresh v154 runtime/socket
identity. Immediately before creating its outer DinD sidecar it must repeat the 4-GiB and
100,000-inode host-root gate. Any pre-provider scaffold, infrastructure, security, identity, or
headroom failure stops without provider consumption; the provider-marker and bounded-continuation
rules remain unchanged.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
