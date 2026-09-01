# OpenHands v43 provider canary authorization

Date: 2026-09-01

Status: authorized only after merge and green `main`; provider canary has not run.

## Purpose and immutable predecessor boundary

V41 consumed its only authorized PR-2549 training episode and failed the fixed cumulative
one-million-provider-token budget after 42 calls. That ordinary model/trajectory failure, its
empty candidate, and PR-2549 are frozen and may not be retried, reconstructed, relabelled, or
admitted. The failure audit merged as
`a2f756330a196da04c30788ce4381c6dffde6440`; post-merge main run `33478968324` passed all eight
required job classes.

V42 then made zero provider calls while materializing and scanning a new PR-2589 command image.
Its result audit merged as `e306ea60be69a2483eb848af89a649258d5e56f0`; post-merge main run
`33482242247` passed all eight required job classes. V43 is a new append-only provider identity. It
does not modify v19–v22, v33, or v36–v42 records.

The authorization file is
`configs/training/qwen35_hwe_openhands_v43_provider_canary_v1.json`, with authorization hash
`49d8f2097dbf05311c003c5f40e512c29290c869d7c86097e74aa1d2e7f40237`.

## Frozen task, runtime, and model identity

The fixed schedule is:

1. training: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2589`;
2. validation: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204`.

Both use seed 494 and sample index 10. PR-2589 binds v42 command image
`sha256:5632d0b3eac6086244a976fb0def3d49e765de2e8af2cdbc208161991db0fbc1`, lock
`c4034d47e2c1fd976755b2425f945da72c19cb4f4f514041e3c1960d262655a6`, and v2 scan
`3ef950839998cbbbad67e181e5e95315dd962605990c575e33eb47713b9582dd`. PR-3204 reuses only
its unstarted v33 validation binding. The two command image IDs are distinct.

The campaign is `openhands-hwe-v43-v22-required-tool-canary-v1`; the agent version is
`openhands-deepseek-v4-flash-hwe-v43-v22-canary-v1`. The runner binds the full v33, v36–v39,
v41, and v42 evidence inventories, the v22 repair, the Qwen tokenizer/model snapshot, both source
locks, and the exact dependency versions. PR-2589 source-directory lock
`76d0a8eb24be90980acde53bc5084d4c1b358c0ac399b80caf1987e84006b145` is intentionally
separate from the legacy image lock used during v42 materialization.

The provider is fixed to DeepSeek v4 Flash with OpenHands SDK 1.42.1, LiteLLM 1.93.0,
tiktoken 0.7.0, transformers 4.57.6, NumPy 2.2.6, Pillow 12.1.1, temperature zero, at most 64
provider calls and 1,000,000 cumulative provider tokens per episode, a 65,536-token context,
2,048 output tokens, zero provider-request retries, and zero whole-episode retries.

Commands execute through `episode_container_exec_v1` only. Both command containers have
`network=none`, no external-agent process, no Codex, no provider credential, and no hidden or
verifier assets. Provider environment values remain in the host agent process and are never
printed, persisted, or hashed.

## Stop and admission policy

Before output and before provider construction, the runner requires clean merged
`HEAD == origin/main`, checks all predecessor audit hashes and ancestry, loads the frozen source,
tokenizer, model lock and dependency versions, and starts both command containers and adapters in
a zero-provider-call preflight.

Once an episode starts, its task is consumed regardless of outcome. Infrastructure or security
failure stops immediately. Any failed training result plane prevents PR-3204 from starting. Both
episodes must pass benchmark verifier, required-tool protocol, trajectory eligibility,
infrastructure, security, and SFT admission. Each must also produce a complete trajectory,
decision-only loss mask, exact-64K receipt with no truncation, and security sidecar.

No retry, reserve substitution, fallback identity, task-role reassignment, historical relabeling,
or budget increase is implicit. A failed PR-2589 episode freezes v43 and requires a different
unused formal task. A two-task pass may set only `formal_collection_allowed=true`; the result must
still be independently audited, merged, and followed by green main checks.

At all times in this authorization:

- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`;
- no held-out task, GPU job, SFT job, or formal collection is authorized.

## Unique post-merge command

The output root must not exist. Only after this authorization merges and the resulting main commit
passes all eight job classes may the following command run once:

```bash
install -d -m 700 /data/jzhu484/Agent/.verigym-tmp/oh-v43

PYTHONPATH=/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/tiktoken-overlay:.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src:integrations/verigym-deepseek-harness/src \
VERIGYM_OPENHANDS_BROKER_ROOT=/data/jzhu484/Agent/.verigym-tmp/oh-v43 \
VERIGYM_OPENHANDS_MCP_PYTHONPATH=/data/jzhu484/Agent/VeriGym/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src \
VERIGYM_RUN_OPENHANDS_HWE_V43_PROVIDER_CANARY_V1=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/collect_cva6_hwe_openhands_v43_provider_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v43_provider_canary_v1.json \
  --v33-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --v42-materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v42-pr2589-canary-materialization-v1 \
  --failed-v36-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v36-provider-canary-v1 \
  --stopped-v37-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v37-provider-canary-pre-output-stop-v1 \
  --failed-v38-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v38-provider-canary-v1 \
  --failed-v39-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v39-provider-canary-v1 \
  --failed-v41-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v41-provider-canary-v1 \
  --training-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-2589 \
  --validation-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-3204 \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v1/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v43-provider-canary-v1
```

The provider endpoint and credential must already exist under their frozen environment-variable
names. Their values must not be placed on the command line or in logs. If the zero-call preflight
stops before service construction, no task is consumed. Any later ordinary failure freezes the
identity and output with no in-place rerun.

## Pre-merge verification

The implementation is tested without provider opt-in, provider calls, task execution, Docker image
mutation, formal collection, training, GPU work, or held-out loading. The focused suite covers
authorization mutation, fresh agent/runtime identity, fixed order, budgets, dependency drift,
zero-call preflight, six-plane stop behavior, exact-64K admission, command-image isolation, source
locks, and read-only validation of all sealed local predecessor evidence.

The local checks passed as follows:

- v43 focused Python 3.12 tests with all sealed evidence and both source locks: 18 passed;
- complete OpenHands credential-free suite: 446 passed, 29 explicit external/real-run skips;
- core credential-free suite: 1,083 passed, 35 explicit external/real-run skips;
- HWE suite: 51 passed;
- Ruff check and format over 724 tracked/new Python files;
- strict mypy: core 208 files, HWE 9 files, OpenHands 44 files, and the standalone runner;
- OpenHands wheel/sdist content audit: passed with no issues; and
- two normalized core builds: byte-identical wheel and sdist.

The first OpenHands package build attempted its normal isolated backend setup, but the configured
package index proxy returned HTTP 502 while fetching an already installed setuptools version. The
official PyPA `build` documentation defines `--no-isolation` for using preinstalled build
dependencies: <https://build.pypa.io/en/latest/how-to/basic-usage.html>. After verifying local
`build` 1.5.0, setuptools 78.1.1, and wheel 0.45.1 satisfy this repository's build requirements,
the same package built with `--no-isolation` and passed the distribution-content audit. This local
verification workaround changes neither CI nor the provider/runtime environment.
