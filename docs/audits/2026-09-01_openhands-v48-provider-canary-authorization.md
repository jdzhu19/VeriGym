# OpenHands v48 provider canary authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; provider canary has not run.

## Purpose and immutable predecessor boundary

V43 consumed its only authorized PR-2589 training episode and failed the fixed cumulative
one-million-provider-token budget after 38 calls. That ordinary trajectory failure is sealed and
cannot be retried, reconstructed, relabelled, or admitted. V44 then stopped before output because
an ambient editable install resolved stale code, and v45 completed a zero-provider image build but
failed the independent result scan because raw host paths were persisted. Both identities and all
their outputs remain immutable.

V46 is the append-only repair. Its sole execution made zero provider calls, built a fresh PR-2802
command image, passed the v2 image scanner, and passed an independent context-aware result scan.
Its result audit merged at `3f823123a5bda5fe3c36db379697103341c68e3e`; post-merge main run
`33497174753` passed all eight required job classes. V48 binds the complete v46 evidence tree
`80e224648c35fb8e40155a0428e57d29cf867a42be7438e3b04e67c9960d2a40` and does not modify any
predecessor record.

V47 authorization merged at `ee45d60171e96f77dcbbbbbe8a3402b745275f5a`, but its sole launch
supplied a nonexistent sibling for `--stopped-v37-canary-root`. It stopped during sealed path
resolution before output, tokenizer loading, zero-call runtime preflight, provider-client
construction, or task loading. Its content-free evidence tree
`decd32eef21aae7b56662aba78e6ae19007b994125d75b5ae9bea2e5072c7482` records zero provider
episodes, zero provider calls, and zero task attempts. The audit merged at
`c81ff7803fc9bca981a20c8e6e43001fe810de33`; post-merge main run `33500488497` passed all eight
required job classes. V47 is frozen and neither task was consumed.

The authorization file is
`configs/training/qwen35_hwe_openhands_v48_provider_canary_v1.json`, with authorization hash
`f55864631727942b0e7336c7df4537324ae9db2a28cda07ad18782005698e672`.

## Frozen task, runtime, and model identity

The exact schedule is:

1. training: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2802`;
2. validation: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204`.

Both use seed 496 and sample index 12. PR-2802 binds v46 command image
`sha256:f370d7c34c8ea2c7d7a2fdde6a5bc47bf5cf887f5f35ab4bd759bb18b173a4db`, lock
`56eb714597459b0f6462d78049fc85fef3cd68d52de90931fec7ed2bc9757bde`, and v2 scan
`523853d2ac78c030cc5ae47e8fea21ad1f526f8afa5d841e07ab1f833856c59c`. PR-3204 reuses only
its still-unstarted v33 validation binding. The images and locks are task-distinct.

The campaign is `openhands-hwe-v48-v22-required-tool-canary-v1`; the agent version is
`openhands-deepseek-v4-flash-hwe-v48-v22-canary-v1`. The runner binds the exact v33 and v46
inventories, sealed predecessor failure evidence, the exact v47 stop receipt and audit, the merged
v22 protocol repair, both public source locks, the Qwen tokenizer/model lock, and exact dependency
versions. The runner also requires the resolved v37 and v47 stop roots to equal their reviewed
absolute identities; sibling names are rejected.

DeepSeek v4 Flash is fixed at temperature zero, at most 64 provider calls and 1,000,000 cumulative
provider tokens per episode, a 65,536-token context, 2,048 output tokens, zero request retries, and
zero whole-episode retries. OpenHands SDK 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, transformers
4.57.6, NumPy 2.2.6, and Pillow 12.1.1 are immutable.

Commands execute only through `episode_container_exec_v1`. Both command containers retain
`network=none`, no external-agent process, no Codex, no provider credential, and no hidden,
reference, verifier, or source asset. Provider values exist only in the host agent process and are
never printed, persisted, or hashed.

## Stop and admission policy

Before output and provider construction, the runner requires clean merged `HEAD == origin/main`,
checks every bound audit hash and ancestor, validates both source and command-image bindings, loads
the exact tokenizer/model and dependency versions, and starts both command runtimes and adapters
under a zero-provider-call preflight.

Once an episode starts, its task is single-use. Infrastructure or security invalidity stops
immediately. Any failed PR-2802 result plane prevents PR-3204 from starting. Both episodes must
pass verifier, protocol, trajectory, infrastructure, security, and SFT-admission planes and must
produce complete trajectory, decision-only mask, exact-64K/no-truncation, accounting, and security
sidecars. There is no retry, fallback identity, role reassignment, reserve substitution, historical
relabeling, or budget increase.

A two-task pass may set `formal_collection_allowed=true` only in the sealed canary result. That
result still requires independent audit, merge, and a green post-merge main run. This authorization
always keeps `formal_collection_started=false`, `collection_started=false`,
`training_started=false`, and `production_training_ready=false`; it authorizes no formal
collection, SFT, GPU work, inference evaluation, or held-out loading.

## Unique post-merge command

The broker directory must be empty and the output root must not exist. Only after this
authorization merges and the resulting main commit passes all eight job classes may the following
command run once:

```bash
install -d -m 700 /data/jzhu484/Agent/.verigym-tmp/oh-v48

PYTHONPATH=/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/tiktoken-overlay:.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src:integrations/verigym-deepseek-harness/src \
VERIGYM_OPENHANDS_BROKER_ROOT=/data/jzhu484/Agent/.verigym-tmp/oh-v48 \
VERIGYM_OPENHANDS_MCP_PYTHONPATH=/data/jzhu484/Agent/VeriGym/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src \
VERIGYM_RUN_OPENHANDS_HWE_V48_PROVIDER_CANARY_V1=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/collect_cva6_hwe_openhands_v48_provider_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v48_provider_canary_v1.json \
  --v33-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v46-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v46-pr2802-canary-materialization-v1 \
  --failed-v36-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v36-provider-canary-v1 \
  --stopped-v37-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v37-provider-canary-pre-output-stop-v1 \
  --failed-v38-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v38-provider-canary-v1 \
  --failed-v39-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v39-provider-canary-v1 \
  --failed-v41-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v41-provider-canary-v1 \
  --stopped-v47-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v47-provider-canary-pre-output-stop-v1 \
  --training-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-2802 \
  --validation-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-3204 \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v1/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v48-provider-canary-v1
```

The two stopped-root arguments above are regression-tested byte-for-byte, including the
`-pre-output-stop-v1` suffixes. The endpoint and key must already exist under their frozen
environment-variable names; their values must not appear on the command line or in logs. A
zero-call preflight stop consumes no task.
Any provider episode or later ordinary failure permanently freezes v48 and its output.

## Pre-merge verification

Verification remains credential-free and provider-disabled. It covers authorization mutation,
fresh agent/runtime identity, exact task order and budgets, dependency drift, zero-call preflight,
six-plane stop behavior, exact-64K admission, command-image isolation, source locks, and read-only
validation of the sealed local evidence. The completed local checks are:

- v48 focused Python 3.12 tests with v33/v46/v47, all directly bound predecessor evidence, and
  both source locks: 21 passed;
- complete OpenHands credential-free suite with all available frozen evidence: 554 passed;
- core credential-free suite: 1,083 passed, 33 explicit external/real-runtime skips, and two
  marker deselections;
- HWE suite: 51 passed;
- audit and security subset: 62 passed and two marker deselections;
- Ruff check and format over 733 tracked files plus the three new v48 Python files: passed;
- strict mypy over 208 core, 9 HWE, and 46 OpenHands source files plus the standalone runner:
  passed;
- OpenHands wheel/sdist content audit: passed with the v48 runtime included and no issues; and
- two normalized core builds: byte-identical wheel and sdist.

The local plugin build used the existing, version-satisfying build environment with
`--no-isolation --skip-dependency-check`; CI retains its ordinary isolated build and remains the
authoritative cross-environment package check. No provider value was read by these tests.
