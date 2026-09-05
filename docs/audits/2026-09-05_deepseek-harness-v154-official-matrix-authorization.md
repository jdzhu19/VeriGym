# DeepSeek Harness v154 replacement official matrix authorization

Date: 2026-09-05

Status: **one provider-bearing execution authorized only after merge and green post-merge `main`**.

## Decision

Authorize exactly one execution of `deepseek-harness-hwe-v154-official-matrix-v1` after this
implementation is merged to `main` and that exact merge commit passes all eight ordinary Actions
job classes. V154 replaces the frozen pre-provider v150 failure; it is not a retry under the v150
identity. V150 and the successful zero-provider v152 scaffold must never be rerun or relabelled.

V154 may reopen the exact retained v148 DinD data volume once, only after repeating the audited
absolute host-root capacity gate. It must use a fresh v154 socket volume and fresh `/data2` socket,
control, runtime, output, and receipt identities. It may not rebuild, pull, import, or substitute a
task image.

This authorization is only for the bounded five-task DeepSeek v4 Flash matrix. It does not
authorize formal collection, candidate import, SFT, GPU work, production training, held-out access,
or a benchmark-score claim. Every result remains pending an independent v155 audit.

## Frozen implementation and predecessor gate

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v154_official_matrix_v1.json`
- Manifest file SHA-256:
  `08cb90e0ae7f22f9e7d281185999c95f78f78b15bc2086387528ad485ffb3191`
- Manifest canonical hash:
  `95be7665adbc220c1350b23743aa56f9062e03b5fe7c1b1b0ae19293fdc657ec`
- Launcher: `scripts/launch_hwe_deepseek_harness_v154_official_matrix.py`
- Launcher SHA-256:
  `2d14334226d684fcbaa59d4e8ad4921c2efe8f4d7825f13b06347ba25d685d54`
- Runner: `scripts/collect_hwe_deepseek_harness_v154_official_matrix.py`
- Runner SHA-256:
  `05021b235fa22f7673cd567824b95b4d1d8123c00ffaec6a0eb4729314e7d8d5`
- v153 audit SHA-256:
  `9559aadeacccd424795afa452579a50e46002ca75feba780f928490fe7c7548d`
- v153 audit commit: `246c2f887a0b8e0c1047d65dc4e416aadb584cd2`
- v153 audit merge: `2ee9d12bd101d81cd0c2d534865d92676b3b2a72`
- v153 post-merge `main` run: `33955466475`, eight of eight jobs passed

The manifest preserves the complete v150 v92/v134 protocol baseline and v148 task, source, image,
toolchain, verifier, and scaffold locks. It additionally binds the exact v150 manifest, launcher,
runner, authorization, failed report/progress, PR-465 pre-provider attempt, cleanup-recovery
receipt, and v151 audit. That evidence proves zero provider calls, zero provider tokens, and zero
v148 data-volume reopens before the host-root exhaustion stop.

The successor gate separately binds the exact v152 manifest, runner, authorization, identical
report/progress, scaffold contract, before/after headroom receipts, host-image identity, readiness,
empty inventory, predecessor preflight, volume setup, cleanup, and v153 audit. The v152 inventory
is fixed at one mode-`0700` directory, eleven mode-`0600` files, zero symlinks, and valid canonical
self-hashes. Its contract remains non-provider and records no v148 volume inspection, mount,
mutation, or reopen.

## Frozen task matrix and provider policy

Execute strictly and serially with seed/sample `502/18`:

1. Ibex PR-465
2. Ibex PR-1135
3. Ibex PR-1780
4. CVA6 PR-2017
5. CVA6 PR-2711

Each task uses its v148 task/source receipt, task-specific credential-free command image, 29-check
v2 scan, official verifier image, explicit agent toolchain identity, and repository-specific
profile. The fixed provider is DeepSeek v4 Flash through Harness `0.1.1-rc.2`, integration
`0.5.0`, and revision `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. Per-task limits are
64 calls, 1,000,000 provider tokens, 65,536 context tokens, 2,048 output tokens, temperature zero,
and zero request or episode retries. Ordinary tool choice is `auto`; public concise rationale and
sibling calls are accepted. Hidden reasoning, foreign tools, illegal paths, and unpaired
observations fail closed.

Every admitted decision uses the exact locked Qwen tokenizer, must be strictly shorter than 65,536
tokens, uses no truncation, and applies the decision-only loss mask. A candidate SFT row requires
all six result planes, including the authoritative official verifier. Trajectory collection is
migratable only with at least two of three eligible Ibex trajectories and one of two eligible CVA6
trajectories containing real modifications. The SFT path is migratable only with at least one
six-plane, exact-64K pass in each repository. Passing tasks may only be listed as candidates pending
v155; failed trajectories remain audit context.

## Provider, host-root, Docker, and cleanup boundary

The launcher removes the complete frozen twelve-name provider configuration set and `DOCKER_HOST`
and `DOCKER_CONTEXT` before copying back only `VERIGYM_DEEPSEEK_API_KEY` and
`VERIGYM_DEEPSEEK_API_BASE_URL`. It selects blocked entries by name before reading values, never
prints them, and passes a fixed child-boundary marker. Concrete provider and proxy values are never
persisted or hashed.

The runner validates the merged source, predecessor evidence, five locks, and exact tokenizer
without Docker. It then creates its new output and writes an `os.statvfs` receipt for `/`
immediately before the first Docker access. At least 4,294,967,296 available bytes and 100,000
available inodes are mandatory. Percentage-used values are not gates. If either threshold fails,
the runner records a pre-provider infrastructure stop without calling Docker cleanup, consuming a
task, or reopening the v148 data volume.

After the gate passes, the only retained predecessor volume that may be mounted is
`verigym-deepseek-harness-v148-dind-data`, owner
`deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1`, bind-backed by
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/data`. Its reopen budget remains exactly one and
its prior count is zero. The v154 socket volume is
`verigym-deepseek-harness-v154-dind-socket`, bind-backed by the initially absent
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v154/socket`. The socket parent, control root, and
runtime scratch must all be fresh and owner-only.

The outer DinD sidecar and inner controller alone may use `verigym-hwe-net`; all command-image and
official-verifier sessions use `network=none`. Host `LocalRuntime`, registry access, `.partial`
input, Docker/VPN changes, and unrelated resource cleanup are forbidden. Before the first provider
request, all five 300-second command-runtime probes, the 120-second exact DinD readiness policy,
complete 12-image inventory, empty inner container/volume inventory, and synthetic zero-call
Harness initialization must pass. Final cleanup is bounded, accepts only empty stdout and stderr,
removes the exact v154-owned socket volume, and restores its backing empty at mode `0700`. The
retained v148 data volume is never deleted.

## Consumption, stopping, and one-shot execution

The provider marker is authoritative. A scaffold, infrastructure, or security failure before a
valid marker stops the campaign and leaves that task provider-unconsumed. Once a valid marker
exists—or marker state is invalid or unreadable—the current task is conservatively consumed;
infrastructure or security failure then stops immediately. Ordinary model or official-verifier
failure consumes the task and permits the next task. Two consecutive no-progress,
no-effective-modification, or trajectory-structure outcomes stop the remainder. V154 is never
retried under the same identity regardless of where it stops.

After the authorization merge and its green post-merge `main` run, invoke the launcher exactly once
from an execution window that already contains the two required provider variables:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V154_OFFICIAL_MATRIX=1 \
python scripts/launch_hwe_deepseek_harness_v154_official_matrix.py \
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
must cover the exact v150/v152 evidence, five-task locks, first-Docker headroom ordering, fresh
v154 socket/scratch identities, deterministic order, provider consumption and bounded continuation,
exact child environment, network separation, toolchain/verifier role binding, strict exact-64K
admission, output cleanup, and v155-only result status.
