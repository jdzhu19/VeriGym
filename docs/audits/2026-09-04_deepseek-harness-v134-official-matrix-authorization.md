# DeepSeek Harness v134 official matrix authorization

Date: 2026-09-04

## Decision

Authorize exactly one execution of
`deepseek-harness-hwe-v134-official-matrix-v1`, but only after this authorization, its immutable
manifest, runner, tests, and security contract are merged to `main` and the corresponding
post-merge `main` workflow passes all eight required check classes.

The authorization is inherited from the independently audited v132 zero-provider scaffold. The
v133 audit implementation commit is `270fc62c2b6c9d970b435609607a2e24c13aac87`, its merge commit is
`7fe5de7dd116b01e9e74925aea5af11327924094`, and post-merge `main` run `33852258490` passed all
eight classes. V134 binds the 1,782-directory, 10,481-file, zero-symlink v132 tree, including the
report, atomic contract, task set, byte-identical execution/final inventories, image-transfer set,
controller and workspace-runtime transfers, two preflights, DinD runtime and cleanup receipts, and
all task/source/command-image/security locks.

The v134 manifest canonical hash is
`0cec03eb195a196b3038cfa2921a9054405118a6899a1666f1150b6c3a12b8c3`. It also locks the
byte-exact v92 manifest and runner as the audited provider-protocol baseline; it does not reuse any
v92 task attempt or output identity.

## Frozen execution

The runner must execute these tasks serially with seed/sample `502/18`:

1. Ibex PR-465
2. Ibex PR-1135
3. Ibex PR-1780
4. CVA6 PR-2017
5. CVA6 PR-2711

Every task is bound to its fresh v132 task/source receipt, task-specific credential-free command
image, 29-check v2 security scan, official verifier image, agent toolchain identity, and
repository-specific profile. The provider is DeepSeek v4 Flash through Harness `0.1.1-rc.2` and
integration `0.5.0`. Per-task limits are 64 calls, 1,000,000 provider tokens, 65,536 context
tokens, 2,048 output tokens, temperature zero, and zero request or episode retries. Tool choice is
`auto`; public rationale and sibling calls are allowed; hidden reasoning, foreign tools, illegal
paths, and unpaired observations fail closed.

## Docker and network boundary

The retained `verigym-deepseek-harness-v132-dind-data` volume may be reopened exactly once. It
keeps owner `deepseek-harness-hwe-v132-bounded-scan-scaffold-v1`, role `data`, and only
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/data` as its bind device. V134 must not relabel,
inspect internally, remove, repair, or otherwise claim that predecessor volume.

The fixed socket backing may be recreated only as a v134-owned socket volume and must be removed
after execution. The provider DinD sidecar and cleanup helper use only the v134 runtime owner. Only
the outer sidecar and inner Harness controller may use `verigym-hwe-net`; command-image and official
verifier containers remain `network=none`. The host Docker configuration, VPN and proxy settings,
user-owned downloader, unrelated Docker resources, registries, and `.partial` archives remain out
of scope. Host `LocalRuntime` is forbidden for HWE base, reference, or model candidates.

## Consumption, stop, and data policy

The provider marker defines task consumption. A scaffold, infrastructure, or security failure
before a valid marker stops immediately and does not consume that task. Once the marker exists, an
infrastructure or security failure consumes the current task and stops. An ordinary model or
official-verifier failure consumes that task and permits the next task. Two consecutive
no-modification, no-progress, or trajectory-structure failures stop the remainder. Invalid or
unreadable markers are handled conservatively as consumed, and the campaign identity is never
retried.

A trajectory is eligible only if its protocol, infrastructure, security, real-modification, and
exact-64K gates pass. SFT admission additionally requires the authoritative official verifier.
Every decision uses the exact locked Qwen tokenizer, decision-only loss mask, at most 65,536
tokens, and zero truncation. The two reported conclusions remain separate: trajectory collection
requires at least two of three Ibex tasks and one of two CVA6 tasks to be eligible; SFT migration
requires at least one six-plane pass in each repository.

Passing tasks may be listed only as candidate SFT inputs pending an independent v135 audit. Failed
trajectories remain audit or research context. V134 does not authorize candidate import, formal
collection, training, GPU use, production readiness, task substitution, a second data-volume
reopen, or a benchmark-score claim. All collection and training flags remain false.
