# DeepSeek Harness v69 multi-task zero-provider authorization

Date: 2026-09-03

## Decision

Authorize one credential-free, registry-free materialization of an atomic five-task DeepSeek
Harness provider contract. This stage may inspect only completed local image archives, reproduce
official base-FAIL/reference-PASS qualification, and build and scan task-specific command images.
It authorizes no provider request, model process, formal collection, SFT training, or production
readiness.

Execution is permitted only after this authorization is merged and the post-merge `main` workflow
passes all eight required job classes. The runner requires that merged run ID, a clean
`main == origin/main`, a non-root host identity, the explicit v69 opt-in, and absence of provider
credential variables. It neither changes VPN/proxy state nor starts, stops, or replaces the
independent public-image downloader.

## Frozen schedule and dispositions

The exact primary order is:

1. `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465`
2. `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135`
3. `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780`
4. `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017`
5. `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711`

Ibex fallback order is PR-48 then PR-293. PR-1816 is reserved exclusively for the later
alternative-toolchain comparison. CVA6 PR-3042 and PR-3137 remain archive-incomplete fallbacks and
cannot be used by v69. The manifest records and excludes historical, held-out, already authorized,
and provider-consumed tasks; in particular, Ibex PR-166 and PR-222 are provider-consumed and cannot
be retried.

The frozen manifest is
`configs/training/qwen35_hwe_deepseek_harness_v69_multitask_zero_provider_v1.json`, with content
hash `a20be68167d37e1acf68e1a9623a8dd5dcfaab973c0f6832d1238658af8f1d8b`.

## Offline and atomic gates

For all five tasks, reference-patch metadata compatibility, dataset SHA-256, selected-row SHA-256,
and source commit are checked before any archive or Docker access. Then the runner validates the
archive SHA-256 and sidecar, registry-manifest digest lock, Docker archive manifest, image config,
repository working directory, and official verifier image. A `.partial` file, registry operation,
drifted binding, unsafe member, or unexpected base is terminal.

Every task must independently produce a non-infrastructure base failure and a passing official
reference under verifier `network=none`. Its command image is credential-free, Codex-free,
task-specific, non-root, read-only-root, network-none, and v2-scanned; the ripgrep release archive
and executable are hash-bound. The provider contract is published only after all five task
receipts pass in order. Any capacity, infrastructure, safety, qualification, or build failure
atomically stops without a partial contract.

Before the first image is loaded or built, the shared HWE headroom policy requires 4 GiB and
100,000 inodes on the host control root, 96 GiB and 250,000 inodes on the Docker data root, 8 GiB
and 50,000 inodes on the fixed `/data2/jiadongzhu/Agent/.verigym-tmp` scratch root, and 2 GiB and
10,000 inodes on the output filesystem. A rejection receipt contains only roles and numeric
capacity, never resolved paths or raw `docker info` output.

## Successor boundary

A completed v69 output remains pending the independent v70 result audit. Only a separate merged
v71 authorization may permit the five real DeepSeek v4 Flash episodes. These flags remain false
through v69: `formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready`.
