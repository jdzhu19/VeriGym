# DeepSeek Harness v135 audit of the v134 official matrix

Date: 2026-09-04

## Decision

The single authorized execution of `deepseek-harness-hwe-v134-official-matrix-v1` is consumed and
stopped fail-closed. It opened the retained v132 DinD data volume once, created and verified the
provider-only bridge, and then encountered `DockerImageError` while preparing the first PR-465
command runtime during the zero-provider preflight. The runner removed the inner bridge, outer
sidecar, and v134-owned socket volume and did not continue to another task.

The PR-465 provider marker is `not_started`; provider episodes, calls, and tokens are all zero.
Consequently PR-465 and the other four scheduled tasks remain provider-unconsumed, but the v132
data-volume reopen budget is exhausted and v134 itself must never be retried. The terminal status
is `stopped_pending_independent_v135_audit`, the stop reason is
`pre_provider_infrastructure_failure`, and the report canonical hash is
`7cb512ae8dd34f67c003289894112ee6ac79b413dbc949eb7ce16ba107ab4cf8`.

This result neither supports nor refutes trajectory or SFT migration. Both reported migration
booleans are false because no trajectory exists, not because a model task or official verifier was
attempted.

## Implementation and merge gates

- v134 implementation commit: `0601089122a392719acf716e3e64459b5374e36e`
- v134 authorization merge/source commit: `4c018fd912435ecf487cde3d101ef7cb997e6724`
- v134 pull request: [#160](https://github.com/jdzhu19/VeriGym/pull/160)
- v134 branch-push run: `33854648347`, eight of eight jobs passed
- v134 pull-request run: `33854668811`, eight of eight jobs passed
- v134 post-merge `main` run: `33855046037`, eight of eight jobs passed
- v134 manifest file SHA-256:
  `240ad78aaf7f9c0463787c44baa42af67a8313289c4695f898253c6aa2db86cb`
- v134 manifest canonical hash:
  `0cec03eb195a196b3038cfa2921a9054405118a6899a1666f1150b6c3a12b8c3`
- v134 runner SHA-256:
  `b4be13a97142209852de6ffe3ec0e4d26ae353f23a93398c4318fb645c0121e5`
- v134 authorization SHA-256:
  `fad5dd140c7601dbbe966bbac3f286b6aeebfbc104f507aac116f5ccc200e5c4`

The invocation used only the exact merged `main` source and its post-merge gate. Provider values
were present only in the execution environment and were not printed, persisted, or hashed.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v134-official-matrix-v1`

It contains seven directories including the root, six regular files, and zero symlinks. Every
directory is mode `0700`; every file is mode `0600`. All six files parse as JSON and their declared
canonical self-hashes validate. The atomic progress and terminal report are byte-for-byte equal.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `e606b301ede015bf135956c627e20859ee83d64b97f530bfaaa8213a04998f22` | `7cb512ae8dd34f67c003289894112ee6ac79b413dbc949eb7ce16ba107ab4cf8` |
| PR-465 stopped attempt | `5275d891005178c783875ed46b26e7ebf82e169e98c0549d6c3002a5e3a22d2a` | `7cc65e849ec8ef6857d5069d0279ee234393d144fb9feb9550bf3c0afb0ab5d4` |
| provider DinD runtime | `6b451c8ad51e69f1f817fc0711fba1f9756d533a4e2b1842d732f8afb7654178` | `5ba4cd0ae76e1638bc187276a91d6ca5806092f62160427e18a84a3bd1c98f66` |
| provider network | `fee849571dfb15fb37089002f17434425021e9f0799f94fbc92597b9ca08b156` | `6ff62f733af5a930a20ac7e40e506018188528539ef3259645c552d9e485efb8` |
| socket cleanup | `949ce3d0a8b694e4b06d7d8ecd2a2820be864e3f59154a726a1baa1cbbbfa955` | `4902e56f08494a54d45ab111be2df116dc73c0b0698d8d4eaffe10b4c9f547c1` |

An independent scan compared both available nonempty provider values with every evidence file in
memory, without printing or hashing those values. It found zero matches.

## Provider boundary and task disposition

The stopped PR-465 receipt records:

- episode `official-ibex-pr465-s502-v134`;
- provider marker `not_started`;
- zero provider calls and zero provider tokens;
- no first effective modification;
- outcome `infrastructure_failure` and exception type `DockerImageError`;
- all six admission planes false, zero exact-64K records, and no candidate dataset.

No `zero-provider-preflight.json`, Harness session, provider marker file, model transcript,
trajectory record, candidate dataset, or official verifier result was created. The raw exception
and Docker output were intentionally not persisted, so this audit cannot safely assign a narrower
Docker image subreason. PR-1135, PR-1780, PR-2017, and PR-2711 never started.

## Cleanup and successor boundary

No v134-owned container remains. The v134-owned socket volume was removed, and the socket backing,
v134 control root, and v134 runtime scratch are empty, owned by UID 1004/GID 100, and mode `0700`.
The retained data volume still has its exact v132 owner and role labels and only
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/data` as its bind device. It must now remain
frozen: its sole successor reopen was consumed even though the provider boundary was not crossed.

A successor must use a new identity and fresh `/data2` data/socket volumes. It may preserve the
five tasks as provider-unconsumed, but must first perform a zero-provider, content-free diagnostic
that records an allowlisted `DockerImageError` subreason and deterministic cleanup. It may not
reopen or inspect the v132 volume, rerun v134, call a provider, or authorize the matrix in the same
step. Any later provider matrix requires a separate merged authorization and green post-merge
`main` run.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
