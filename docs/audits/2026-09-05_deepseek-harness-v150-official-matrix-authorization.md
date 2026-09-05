# DeepSeek Harness v150 official matrix authorization

Date: 2026-09-05

Status: **one provider-bearing execution authorized only after merge and green post-merge `main`**.

## Decision

Authorize exactly one execution of `deepseek-harness-hwe-v150-official-matrix-v1` after this
implementation is merged to `main` and that exact merge commit passes all eight ordinary Actions
job classes. V150 is the sole provider-bearing successor named by the independently audited v148
contract. It may reopen the exact retained v148 DinD data volume once; it may not reuse any older
data volume or rebuild, pull, or substitute a task image.

This authorization is only for the bounded five-task DeepSeek v4 Flash matrix. It does not
authorize formal collection, candidate import, SFT, GPU work, production training, held-out access,
or a benchmark-score claim. Every result remains pending an independent v151 audit.

## Frozen implementation and predecessor gate

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v150_official_matrix_v1.json`
- Manifest file SHA-256:
  `5520fdac6b3ac583633aa987c534b319228b474581659519a00b116aa77c91c4`
- Manifest canonical hash:
  `f471c11b6371218c3d5bfab4380152eabec52b3637d466ef81658b36bcc47553`
- Launcher: `scripts/launch_hwe_deepseek_harness_v150_official_matrix.py`
- Launcher SHA-256:
  `a3503e8879604b19384b9e1b94c732b10d600ecc610aea0356a66fb350384ade`
- Runner: `scripts/collect_hwe_deepseek_harness_v150_official_matrix.py`
- Runner SHA-256:
  `8228a86d7ca38a9f3db09be156ce8c51bec349352b22e14c59bace1286a496b4`
- v149 audit SHA-256:
  `5d0e907a7a81551d948191fbd45e194720cd96f8995f3a3403e64fe4177e94a6`
- v149 audit commit: `a96372e51a6e1fae63059ac76c1df357f58ede9c`
- v149 audit merge: `cd42038703654cadab3aebc66ae0127fa87f3ad1`
- v149 post-merge `main` run: `33940855243`, eight of eight jobs passed

The manifest binds the exact v92 wire-protocol manifest and runner and the v134 provider-matrix
manifest and runner. It separately binds the v148 manifest, launcher, runner, authorization,
terminal report, atomic contract, task-materialization set, identical execution/final inventories,
image-transfer set, controller and workspace-runtime receipts, both preflights, DinD runtime, final
cleanup, and v149 audit. The v148 evidence inventory is fixed at 1,786 directories, 10,493 regular
files, and zero symlinks with its exact mode distribution.

## Frozen task matrix and provider policy

Execute strictly and serially with seed/sample `502/18`:

1. Ibex PR-465
2. Ibex PR-1135
3. Ibex PR-1780
4. CVA6 PR-2017
5. CVA6 PR-2711

Each task uses its v148 task/source receipt, fresh task-specific credential-free command image,
29-check v2 scan, official verifier image, agent toolchain identity, and repository-specific
profile. The fixed provider is DeepSeek v4 Flash through Harness `0.1.1-rc.2`, integration
`0.5.0`, and revision `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. Per-task limits are
64 calls, 1,000,000 provider tokens, 65,536 context tokens, 2,048 output tokens, temperature zero,
and zero request or episode retries. Ordinary tool choice is `auto`; public concise rationale and
sibling calls are accepted. Hidden reasoning, foreign tools, illegal paths, and unpaired
observations fail closed.

Every admitted decision is counted with the exact locked Qwen tokenizer, must be strictly shorter
than 65,536 tokens, uses no truncation, and applies the decision-only loss mask. A candidate SFT
row additionally requires all six result planes, including the authoritative official verifier.
The separate conclusions are:

- trajectory collection is migratable only with at least two of three eligible Ibex trajectories
  and one of two eligible CVA6 trajectories containing real modifications;
- the SFT path is migratable only with at least one six-plane, exact-64K pass in each repository.

Passing tasks may only be named in a candidate list pending v151. Verifier-rejected or otherwise
failed trajectories remain audit context and are never automatically admitted.

## Provider, Docker, and cleanup boundary

The launcher removes the complete frozen 12-name provider configuration set and `DOCKER_HOST` and
`DOCKER_CONTEXT` before copying back only `VERIGYM_DEEPSEEK_API_KEY` and
`VERIGYM_DEEPSEEK_API_BASE_URL`. It selects blocked entries by name before reading values, never
prints them, and passes a fixed child-boundary marker. The runner rejects any missing marker,
missing required value, extra provider alias, inherited Docker endpoint, root identity, changed
source, or unmerged source before output or Docker access. Concrete provider and proxy values are
never persisted or hashed.

The only retained predecessor volume is
`verigym-deepseek-harness-v148-dind-data`, owner
`deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1`, bind-backed by
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/data`. V150 may reopen it exactly once. The
absent socket volume is recreated with v150 ownership over
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/socket`. The outer DinD sidecar and inner
controller alone may use `verigym-hwe-net`; all command-image and official verifier sessions use
`network=none`. Host `LocalRuntime`, registry access, `.partial` input, Docker/VPN changes, and
unrelated resource cleanup are forbidden.

Before the first provider request, the runner must pass all five command-runtime preparations with
the explicit 300-second image probe, the 120-second monotonic DinD readiness policy, complete
12-image inventory, empty inner container/volume inventory, and synthetic zero-call Harness
initialization. Final cleanup has a 300-second bound, accepts only empty stdout and stderr, removes
the exact v150-owned socket volume, and restores the fixed backing empty at mode `0700`.

## Consumption and stopping

The provider marker is authoritative. A scaffold, infrastructure, or security failure before a
valid marker stops the campaign and leaves that task provider-unconsumed. Once a valid marker
exists—or marker state is invalid or unreadable—the current task is conservatively consumed;
infrastructure or security failure then stops immediately. Ordinary model or official-verifier
failure consumes the task and permits the next task. Two consecutive no-progress,
no-effective-modification, or trajectory-structure outcomes stop the remainder. V150 is never
retried under the same identity regardless of where it stops.

## One-shot execution

After the authorization merge and its green post-merge `main` run, invoke the launcher exactly
once from an execution window that already contains the two required provider variables:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V150_OFFICIAL_MATRIX=1 \
python scripts/launch_hwe_deepseek_harness_v150_official_matrix.py \
  --post-merge-main-run-id <green-main-run-id>
```

Do not replace the launcher with a hand-maintained `env -u` command. All collection and training
flags remain false:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

## Credential-free verification

Before merge, run the core, HWE Bench, DeepSeek Harness, and Synopsys credential-free suites and
their mypy checks, plus `ruff check . && ruff format --check . && mypy src`. Focused regressions
must cover the exact v148 evidence and five-task locks, deterministic order, task consumption and
bounded continuation, 300-second image probes, exact child environment, network separation,
toolchain/verifier role binding, strict exact-64K admission, output cleanup, and v151-only result
status.
