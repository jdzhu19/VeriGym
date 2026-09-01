# OpenHands v51 PR-2728 public qualification authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; zero-model qualification has not run.

## Decision and predecessor boundary

This preregistration authorizes exactly one zero-provider qualification attempt under the new
identity `openhands-hwe-v51-pr2728-public-qualification-v1`. It may run only after this
authorization merges and the post-merge `main` workflow passes all eight required job classes.

The predecessor is the sealed v50 ordinary failure. Its result audit merged at
`6177cfa5d9566bdebbd3feef9be54e7329349a37`, and post-merge main run `33513250028` passed all
eight classes. V50 evidence tree
`ac49a3f79ea7b1e025280a822057f8c7f370a6cc328e7f7bec8be057adace418`, report
`11a6cc828708e6a2fa48214e5c241436e8ba55c599e210c43f78846b4e32075f`, PR-2916 attempt
`a95c81161ccbc8ac8e3d8ce3f52393d524c05e5876e980df6461d93b0a90d42c`, and scorecard
`9d630fb264b6909b08836be16e911536916282dab8b48e1a5bdc497bdbecc848` are immutable. PR-2916
cannot be retried, and v51 does not start the still-unattempted PR-3204 validation task.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v51_pr2728_public_qualification_v1.json`. Its canonical
authorization hash is
`fe0be8fe67180851a2f507559822f2baf4c50939b9bc2487e0145e783520a8b3`.
The reviewed runner SHA-256 is
`4b077469d1059d9367a496eb03a930d5d4c23469f06c00d9fc1293e05a422c97`.

## Public-task selection and upstream reference

Every training candidate named by the prior formal schedule has now been consumed by a sealed
provider attempt. The successor therefore cannot reuse PR-2549, PR-2589, PR-2802, PR-2916,
PR-2330, PR-3226, or PR-3231. Historical attempts, imported historical passes, old qualification
failures, validation-role tasks, PR-2170, and the frozen held-out IDs are also excluded.

The remaining official public CVA6 metadata was ordered by changed lines and PR number, then
checked against repository history. PR-2728 was selected from the never-attempted set because its
official record is a bounded one-file decoder correction with 25 changed lines. The upstream
[CVA6 PR-2728](https://github.com/openhwgroup/cva6/pull/2728) describes the RV32/RV64 bit-manip
decode distinction, shows the final successful upstream run, and records the merged result. This
public metadata is a task-selection heuristic, not proof of local qualification or a benchmark
score.

The official dataset remains fixed at SHA-256
`732c5dac910815c1c7ac72c8ccca88f66dbb7ed5d097806a5ddea611102f60f1`, dataset revision
`1403afb57ce056c659c82b35e39c38c6a21ee635`, and source commit
`10c78a87e1f92695d78d15b1464a6107dcac8837`. The selected public row is independently locked at
SHA-256 `42f3040a91af4e735e1107dd2536691c9fa3286b4e9441cc8ebb039e3d3c1a16`.

Before any Docker or network access, v51 runs the existing metadata-only reference-patch
classifier. Its content-free receipt hash is
`cccec1b44901f1e3cd7d6694a5a825cd9716536e445a7678ff408cedcf6fe0d2`: one in-place regular text
file, with zero creation, deletion, rename, copy, mode change, or binary patch. The classifier is
informed by the official [HWE-Bench repository](https://github.com/pku-liang/hwe-bench) and
[`git apply` metadata modes](https://git-scm.com/docs/git-apply); neither source predicts the
local verifier outcome.

## Isolation, data minimization, and one-use policy

The dataset reader scans record envelopes for top-level PR numbers without decoding unselected
JSON values. Only the selected public PR-2728 row is decoded and copied to a temporary one-row
dataset. Known held-out record values are never decoded, selected, loaded into Docker, copied to
the output, or exposed to the verifier. The temporary row and daemonless transfer archive are
removed with the dedicated scratch root.

Before output creation, the runner requires clean `HEAD == origin/main`, the exact v50 audit file
and ancestor, the authorization hash, official dataset and selected-row hashes, the patch receipt,
the pinned v24 crane/SLSA tool cache, the pinned Python transfer image, `/data/docker`, at least 64
GiB available space and one million available inodes, the dedicated `verigym-hwe-net` bridge, an
absent PR-2728 host tag, and an absent digest sentinel.

Only digest/config resolution and the bounded daemonless image transfer use
`verigym-hwe-net`. Transfer containers are non-root, read-only, capability-free,
`no-new-privileges`, resource bounded, use exactly two mounts, expose no ports or Docker socket,
and receive no proxy or registry credential. The base and reference verifier arms use
`network=none`. Progress and the content-free pull receipt are persisted atomically; raw command
output is never persisted.

PR-2728 is single-use once transfer begins. Base-FAIL/reference-PASS records it as
`qualified_pending_command_image`. An ordinary base/reference mismatch records `not_qualified`.
Infrastructure, security, cleanup, identity, capacity, or receipt drift stops fail closed. None of
these outcomes may be retried under v51.

## Unique post-merge command

The output and v51 scratch paths must not exist. Only after merge and green post-merge main may
this exact command run once:

```bash
PYTHONPATH=.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src \
VERIGYM_RUN_OPENHANDS_HWE_V51_PR2728_QUALIFICATION=1 \
.venv/bin/python \
  scripts/qualify_cva6_openhands_v51_pr2728_public_qualification.py \
  --authorization configs/training/qwen35_hwe_openhands_v51_pr2728_public_qualification_v1.json \
  --dataset /data/jzhu484/Agent/datasets/HWE-Bench-data/openhwgroup__cva6.jsonl \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v51-pr2728-public-qualification-v1
```

No provider endpoint or key is needed or permitted. A terminal result requires a separate
sanitized audit before any command-image build authorization.

## Pre-merge verification

Credential-free verification covers authorization mutation, v50 evidence, PR-2728 selection,
held-out non-decoding, patch compatibility, one-task admission, ordinary mismatch, zero retry,
bounded transfer diagnostics, tarball identity, merged-source ordering, type/style checks,
package contents, Docker security, and reproducible builds. PR and post-merge CI remain the
authoritative Python 3.11/3.12/3.13, quality, package, OpenHands 3.12, Docker-security, and
reproducible-build gates.

Completed local checks are:

- v51 focused regressions: `9 passed`; v26/v28/v51 continuation regressions: `21 passed`;
- ordinary credential-free core suite: `1065 passed`, one explicit real-Codex skip, and 52
  deselected;
- HWE credential-free suite: `52 passed`; OpenHands credential-free suite: `535 passed` and 66
  explicit historical/real-runtime evidence skips;
- audit, release, schema, and security contracts: `79 passed`; schema export drift: zero;
- tracked and new source Ruff format/check: `743 files`; Git patch hygiene: passed;
- strict mypy: core `208 source files`, HWE `9 source files`, OpenHands `47 source files`, and the
  standalone Python 3.12 runner passed;
- OpenHands and HWE wheel/sdist package-content audits: passed with zero issues;
- two fixed-epoch core builds: wheel and sdist byte-identical;
- real read-only preflight: exact authorization/dataset/selected-row/patch receipts, dedicated
  network, execution image, tool cache and `/data/docker` passed; PR-2728 and digest-sentinel images,
  output and scratch were absent; available capacity was 321,797,910,528 bytes and 250,499,986
  inodes; and
- the final changed-source security scan found zero hard-secret leaks and zero scanner errors.

No Docker image was downloaded, no container was created, no verifier or provider was called, and
no experiment output was written by these authorization checks.

The current authorization does not claim a qualification result or benchmark score.

## Explicitly not authorized

V51 cannot invoke a provider, run an agent episode, build a command image, materialize a canary
contract, start a canary or formal collection, run SFT or GPU work, load held-out tasks, retry any
historical task, or change historical roles. All formal collection and training state remains
false.
