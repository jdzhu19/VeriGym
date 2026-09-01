# OpenHands v50 provider canary authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; provider canary has not run.

## Immutable predecessor and replacement boundary

V48 consumed its only authorized PR-2802 training episode. The episode made 43 provider calls,
failed the verifier/protocol/trajectory/SFT-admission planes as an ordinary benchmark or trajectory
failure, and did not start PR-3204. Its evidence tree
`c0f72852b070f8a2ca2046b3fa3d4a32ba342de4d2edaa92327f9184113053c6` and report
`4ba2cbeaa8c79464dd63a68749e7f4b313251b596ff4a799193ab8cc348a4b2d` are frozen. The failure
audit merged at `8b186bec056ae6c10c3785620ac64ef68d60932a`; post-merge main run
`33504770097` passed all eight required job classes. PR-2802 is not retryable.

V49 is the zero-provider replacement materialization. Its only execution built and v2-scanned a
fresh Codex-free PR-2916 command image, made zero provider calls and attempts, and kept all
collection/training flags false. Its evidence tree is
`c773d0e6e7df8beaaee994a60e89e612b85a4d5ce070414df90692422696a9d0`; the result audit merged
at `a2ac14cdf7911ade37083598c1643a1e676132d8`; post-merge main run `33508192118` passed all eight
required job classes. V50 validates both reviewed absolute predecessor roots before output.

The authorization file is
`configs/training/qwen35_hwe_openhands_v50_provider_canary_v1.json`, with authorization hash
`4937d9fd7e5b46d78cbe746817fff704a768382b5480c6b698171b7726a2760d`.

## Frozen task, runtime, and model identity

The exact schedule is:

1. training: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2916`;
2. validation: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204`.

Both use seed 497 and sample index 13. PR-2916 binds v49 command image
`sha256:d4cfb7b812b59b29a9e0a0c58ef71006e4580b8708f50cf06d0ded650b6ce60e`, lock
`e4db6b85a1bbbdcb9105f51ee23451822dfa7dcded6a64f768e50928d034d5e6`, and v2 scan
`ee2d910595397602d846e9b33d33fc09da38d023b0357c35c959fd3ac8f5f7bd`. PR-3204 reuses only
its still-unstarted v33 validation binding. The two bindings are task-distinct.

The campaign is `openhands-hwe-v50-v22-required-tool-canary-v1`; the agent version is
`openhands-deepseek-v4-flash-hwe-v50-v22-canary-v1`. DeepSeek v4 Flash is fixed at temperature
zero, at most 64 provider calls and 1,000,000 cumulative provider tokens per episode, a 65,536-token
context, 2,048 output tokens, zero request retries, and zero whole-episode retries. OpenHands SDK
1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, transformers 4.57.6, NumPy 2.2.6, and Pillow 12.1.1 are
immutable.

Commands execute only through `episode_container_exec_v1`. Both command containers retain
`network=none`, no external-agent process, no Codex, no provider credential, and no hidden,
reference, verifier, or source asset. Provider values exist only in the host agent process and are
never printed, persisted, or hashed.

## Stop and admission policy

Before output or provider-client construction, the runner requires clean merged
`HEAD == origin/main`, validates every bound audit/hash/ancestor, both source and command-image
bindings, the Qwen tokenizer/model lock, dependency versions, and both credential-free command
runtimes. A redacted zero-call preflight must pass first.

PR-2916 is single-use once its episode starts. Infrastructure or security invalidity stops
immediately. Any failed PR-2916 result plane prevents PR-3204 from starting. Both episodes must
pass verifier, protocol, trajectory, infrastructure, security, and SFT-admission planes and emit
complete trajectory, decision-only mask, exact-64K/no-truncation, accounting, receipt, and security
sidecars. There is no retry, reserve substitution, fallback identity, role reassignment, historical
relabeling, reconstruction, or budget increase.

A two-task pass may set `formal_collection_allowed=true` only in the sealed result. That result
still requires an independent audit, merge, and green post-merge main run before any formal
collection authorization. This authorization always keeps `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and `production_training_ready=false`; it
does not authorize formal collection, SFT, GPU work, inference evaluation, or held-out loading.

## Unique post-merge command

The broker directory must be empty and the output root must not exist. Only after this
authorization merges and its main commit passes all eight job classes may the following command
run once:

```bash
install -d -m 700 /data/jzhu484/Agent/.verigym-tmp/oh-v50

PYTHONPATH=/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/tiktoken-overlay:.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src:integrations/verigym-deepseek-harness/src \
VERIGYM_OPENHANDS_BROKER_ROOT=/data/jzhu484/Agent/.verigym-tmp/oh-v50 \
VERIGYM_OPENHANDS_MCP_PYTHONPATH=/data/jzhu484/Agent/VeriGym/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src \
VERIGYM_RUN_OPENHANDS_HWE_V50_PROVIDER_CANARY_V1=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/collect_cva6_hwe_openhands_v50_provider_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v50_provider_canary_v1.json \
  --v33-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v49-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v49-pr2916-canary-materialization-v1 \
  --failed-v36-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v36-provider-canary-v1 \
  --stopped-v37-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v37-provider-canary-pre-output-stop-v1 \
  --failed-v38-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v38-provider-canary-v1 \
  --failed-v39-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v39-provider-canary-v1 \
  --failed-v41-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v41-provider-canary-v1 \
  --failed-v48-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v48-provider-canary-v1 \
  --training-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-2916 \
  --validation-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-3204 \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v1/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v50-provider-canary-v1
```

The endpoint and key must already exist under their frozen environment-variable names; their
values must not appear on the command line or in logs. A zero-call preflight stop consumes no task.
Any provider episode or later ordinary failure permanently freezes v50 and its output.

## Pre-merge verification requirements

Verification is credential-free and provider-disabled. It covers authorization mutation, fresh
agent/runtime identity, v48/v49 exact evidence, fixed task order and budgets, dependency drift,
zero-call preflight, six-plane stop behavior, exact-64K admission, command-image isolation, source
locks, artifact scanning, type/style checks, package contents, and reproducible builds. The
authorization must not be used until the PR and post-merge main workflows pass all eight required
job classes.

Completed local checks are:

- v50 focused tests with all frozen local evidence roots and both source locks: 21 passed;
- core credential-free suite: 1,065 passed, one explicit real-Codex skip, 52 deselected;
- HWE suite: 51 passed;
- OpenHands credential-free suite: 566 passed and 26 explicit historical/real-runtime skips;
- audit, release, and security subset: 179 passed, one reproducible-build opt-in skip, one
  deselected;
- Ruff format/check over 741 tracked and new Python files, persistent-schema drift, documentation
  contracts, and Git patch hygiene: passed;
- strict mypy: 256 combined core/runner/OpenHands source files, 47 OpenHands package files, and
  nine HWE files passed;
- OpenHands wheel/sdist audit: passed with v50 runtime included and no issues; and
- two fixed-epoch core builds: wheel and sdist byte-identical.

No provider credential or provider call was used by these checks. PR and post-merge CI remain the
authoritative Python 3.11/3.12/3.13, package, Docker-security, and OpenHands acceptance gates.
