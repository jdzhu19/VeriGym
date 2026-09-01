# OpenHands v41 provider canary authorization

Date: 2026-09-01

Status: authorized in source, pending merge and green `main`; do not execute before both gates
pass.

## Purpose and boundary

This authorization permits one fresh, fixed-order, two-episode provider canary under the v22
SDK-normalized empty-content recovery protocol. It authorizes PR-2549 training followed by
PR-3204 validation, only once under the new v41 agent/runtime identity. It does not authorize a
retry of PR-2330, PR-3226, PR-3231, or any failed identity. It does not authorize formal
collection, SFT, GPU work, benchmark-score publication, or held-out loading.

The exact authorization is
`configs/training/qwen35_hwe_openhands_v41_provider_canary_v1.json`, with authorization hash
`d29ee68cf1cd70d55c7bbdbdc13701aec7463b01a357ad56faf1fbf0e986811b`.

## Why v41 is a new identity

V39 consumed one PR-3231 provider episode and failed closed before broker dispatch because the
pinned OpenHands SDK normalized transport-level `content=""` to one empty `TextContent` part.
V39, PR-3231, and that attempt remain immutable and cannot be retried or relabelled. PR-3204 did
not start.

The separately merged v22 repair permits only the SDK-equivalent empty shape: exactly two sibling
tool calls with either zero text parts or one exactly empty text part, zero non-empty text, and no
private reasoning. Both calls are rejected atomically before dispatch, and the next response must
be exactly one canonical allowlisted HWE action. Whitespace, non-empty or non-text content, any
other sibling count, repeated recovery, invalid JSON, private reasoning, or accounting drift still
fails closed. The diagnosis and upstream OpenHands SDK, DeepSeek, and LiteLLM references are sealed
in `docs/audits/2026-09-01_openhands-v22-empty-content-normalization.md`.

V40 then performed a zero-provider materialization for PR-2549. That task has historical evidence
under other frozen campaigns, so v41 claims only that it is new to this identity. It does not
reconstruct or relabel a historical trajectory. A successful v41 PR-2549 trajectory must later be
imported into formal readiness without re-executing the task; a failed episode freezes PR-2549 and
requires a distinct formal replacement.

## Frozen evidence and task order

The runner binds and revalidates the complete v33, v36, v37, v38, v39, v40, and v22 evidence
chains before output creation. The newest bindings are:

- v39 failure audit merge: `5a3c4cdb547cd3ca8bc7d3c45d21267e5d47648b`;
- v39 evidence tree: `1fee66ee5a9f3902ce726a4459da875ba2dccb13c576763c2a4b5d6b44bac6be`;
- v39 report: `072f237207f22f7f04a640819bded258d05e880ffc634340739e956064b03077`;
- v22 repair merge: `299cc6212be24f12c7cb695f596e4328258e294d`;
- v22 post-merge main run: `33471695480`, all eight required job classes passed;
- v40 result audit merge: `c1b4b9e366aed3642d4828df24f508aa32c377ab`;
- v40 evidence tree: `49cfed8ee15733519db036e64e4e26962dc91d5775ac90d2bcf11c6f6177a8ee`;
- v40 catalog: `622b1cbbbb06d84dc8190344ab90c0f45493c754a3623b50c175d0b426cd7ed7`;
- v40 static contract: `5689104dc6d011724e68fab197748cd099be0067442f7ca98ccd35f8ef8a7b37`;
- v40 post-result-audit main run: `33474832177`, all eight required job classes passed.

The only permitted order is:

1. training: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549`;
2. validation: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204`.

PR-2549 uses v40 command-image lock
`f099358ae9858d2b894525d999c13b45a790abed549f9b480c0117f6dad22985` and v2 security scan
`86deb3062ba5554be39960ccb5180fda13d1b21cae215617e8bc5ec8853b52b7`.
PR-3204 reuses only its unstarted v33 validation binding, with lock
`4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7` and v2 security scan
`55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf`.
The validation episode cannot start unless every training gate passes.

## Runtime, budgets, and admission

The identity is `openhands-hwe-v41-atomic-shape-recovery-provider-canary-v1`, using agent version
`openhands-deepseek-v4-flash-hwe-v41-atomic-shape-recovery-canary-v1`, seed 493, sample index 9,
temperature zero, and no provider-request or whole-episode retries. Host software is fixed to
OpenHands SDK 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, Transformers 4.57.6, NumPy 2.2.6, and
Pillow 12.1.1.

Each episode is capped at 64 provider calls, 1,000,000 cumulative provider tokens, a 65,536-token
context, and 2,048 output tokens. Commands execute only in the bound
`episode_container_exec_v1` image with `network=none`, no external-agent image, no Codex, no
provider credential, and no hidden, reference, or verifier payload. Provider URL and key values
are used only in trusted host memory, scanned against the complete output tree, and never printed,
persisted, or hashed.

Success requires all six verifier, protocol, trajectory, infrastructure, security, and
SFT-admission planes to be true for both tasks. Each admitted trajectory must have v22 protocol,
trajectory, decision, exact-64K token, and security receipts; use a decision-only loss mask; leave
synthetic recovery content unsupervised; and apply no truncation. An infrastructure or security
failure stops immediately. Any other failed plane stops after that task, freezes v41, and forbids
all retries.

## Merge and unique execution gates

The authorization becomes executable only after its focused PR is merged into `origin/main` and
all eight required Actions classes pass on the resulting main commit. At invocation the runner
again requires clean `HEAD == origin/main`, verifies predecessor ancestry and exact audit hashes,
loads no held-out task, verifies frozen sources/tokenizer/model lock and dependency versions, and
runs both command-container/adapter preflights with zero provider calls before constructing the
provider service.

The provider base URL and key must already be present under their registered environment-variable
names; their concrete values must not be placed in shell history or command output. Create the
private broker root and invoke the runner exactly once:

```bash
install -d -m 700 /data/jzhu484/Agent/.verigym-tmp/oh-v41

PYTHONPATH=/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/tiktoken-overlay:.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src:integrations/verigym-deepseek-harness/src \
VERIGYM_OPENHANDS_BROKER_ROOT=/data/jzhu484/Agent/.verigym-tmp/oh-v41 \
VERIGYM_OPENHANDS_MCP_PYTHONPATH=/data/jzhu484/Agent/VeriGym/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src \
VERIGYM_RUN_OPENHANDS_HWE_V41_PROVIDER_CANARY_V1=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/collect_cva6_hwe_openhands_v41_provider_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v41_provider_canary_v1.json \
  --v33-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v40-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v40-fresh-training-canary-materialization-v1 \
  --failed-v36-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v36-provider-canary-v1 \
  --stopped-v37-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v37-provider-canary-pre-output-stop-v1 \
  --failed-v38-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v38-provider-canary-v1 \
  --failed-v39-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v39-provider-canary-v1 \
  --training-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-2549 \
  --validation-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-3204 \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v1/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v41-provider-canary-v1
```

The output directory must be absent before invocation. A pre-provider stop consumes no task and
records zero calls. Once a provider episode begins, its task is consumed regardless of outcome.
No fallback identity or reserve task is implicitly authorized.

## Credential-free verification

Local verification completed without provider opt-in, network execution, Docker image mutation,
formal collection, or training:

- v41 focused tests, including all sealed local predecessor roots: 15 passed;
- complete OpenHands plugin suite: 427 passed, 20 explicit evidence/real-run skips;
- core ordinary tests: 1,065 passed, 1 real-Codex opt-in skip, 52 deselected;
- HWE integration: 51 passed; HWE mypy: 9 source files passed;
- core mypy: 208 source files passed; OpenHands mypy: 43 source files passed;
- the frozen PR-2549/PR-3204 source locks, Qwen snapshot/tokenizer identities, base-model lock,
  and six host dependency versions were independently rechecked.

The HWE run exposed a pre-existing current-working-directory dependency in the reference-patch
metadata classifier. Git's official `git apply` documentation describes paths outside the current
working area as a distinct safety boundary: <https://git-scm.com/docs/git-apply>. The repository
fix does not enable `--unsafe-paths`; it runs the two metadata-only commands in a new empty
directory with parent repository discovery stopped, then retains the existing strict path parser.
A new regression executes from a nested Git worktree directory and proves the result is invariant.

Package, reproducible-build, Docker security, pull-request checks, and post-merge main checks remain
required gates; local verification does not substitute for them.

## Required terminal state

If both episodes pass, v41 may set only `formal_collection_allowed=true`. The result must still
have `formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`. A sanitized result audit, green post-merge main run, separate
formal image materialization, and separate formal collection-readiness authorization remain
required. Until those later gates pass, formal collection must not start.
