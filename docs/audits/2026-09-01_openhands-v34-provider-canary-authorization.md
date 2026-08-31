# OpenHands v34 Codex-free provider-canary authorization

## Authorization boundary

This change authorizes one execution of the v34 provider canary, and only after this pull request
is merged and all eight repository protection classes pass on `main`. The new immutable identities
are:

- orchestration identity `openhands-hwe-v34-provider-canary-v1`
- campaign `openhands-hwe-v34-codex-free-required-tool-canary-v1`
- agent `openhands-deepseek-v4-flash-hwe-v34-codex-free-canary-v1`

The schedule is fixed to PR-2330 training followed by PR-3204 validation, seed 489 and sample
index 5. It binds DeepSeek v4 Flash, OpenHands SDK 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0,
transformers 4.57.6, temperature zero, 64 provider calls, 1,000,000 provider tokens, a 65,536
token context, 2,048 output tokens and zero retries per episode.

The authorization hash is
`720e445dee059d3a147240ff0471975f3695ee780e29f8a6417b30d3ad4a690b`. It permits no more than
two provider-bearing episodes. It does not authorize formal collection, reserve consumption,
fallback identity creation, held-out loading, SFT, GPU work or adapter publication.

## Frozen predecessor and command-runtime evidence

The runner accepts only the merged v33 result audit
`648fe717e88b36876245df09e73222f906f83918` and its exact local evidence tree:

- tree hash `62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6`
- progress hash `463aa8016d62e947421379cd925009c131a589d754e0c17e7c7f83c72fef26df`
- catalog hash `05be424d40014e7ef69106f85e5ea161db2bb8e70103c8d1279e4a7c118f8e05`
- canary-contract hash `6acc93394bbfd0023063d218033316750cfc92b02a173e1ad5771ca563453687`

Each file SHA-256 and both task-specific command-image lock and scanner receipts are independently
bound in the authorization. PR-2330 uses command image
`sha256:3ba2d622fbec6891484c8529892be39db33e02127ec9aaec80381b7d87e64540`; PR-3204 uses
`sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784`.

The command containers are credential-free and Codex-free, have no external-agent image or
process, and run through `episode_container_exec_v1` with `network=none`. The provider client and
credentials remain only in the trusted controller. A zero-provider Docker preflight resolves and
probes both exact command images before any episode can be created.

## Fail-closed result and trajectory policy

PR-3204 runs only if PR-2330 passes all six independent planes: benchmark verifier, required-tool
protocol, exact trajectory, infrastructure, security and SFT admission. Infrastructure or security
invalidity stops immediately. Any other failed plane, a missing trajectory/decision/token receipt,
an overlength decision, a non-decision-only loss mask or any truncation stops the canary without a
retry.

Successful tasks atomically persist the full exact OpenHands trajectory, decision-only JSONL,
v19 protocol and trajectory receipts, an exact-64K token receipt and a content-aware security
sidecar. Provider endpoint and credential values are scanned in memory against all artifacts and
are never printed, persisted or hashed. Accounting is recovered from each run even if protocol
validation fails, so a provider-bearing failure cannot be reported as zero calls.

Only two fully passing attempts set `formal_collection_allowed=true`. Even that state leaves
`formal_collection_started=false`, `training_started=false`,
`production_training_ready=false` and `benchmark_score_claimed=false`; the result still requires
a separate sanitized audit pull request and green `main` checks.

## Pre-review verification

Credential-free checks on the authorization branch produced:

- v34 regressions with the sealed local v33 evidence enabled: `8 passed`;
- complete OpenHands Python 3.12 zero-model suite: `330 passed`, `1 skipped` when the external v33
  evidence path is intentionally absent;
- ordinary core suite: `1064 passed`, `1 skipped`, `52 deselected`; HWE plugin: `50 passed`;
- strict mypy: core `208` files, HWE `9` files, OpenHands `31` files and v34 runner `1` file;
- tracked-source and new-file Ruff/format: `690` Python files; Git diff hygiene: passed;
- OpenHands wheel/sdist content audit: passed, with the v34 runtime present in the wheel;
- authorization-hash recomputation and the real pre-merge opt-in rejection: passed, with no output
  root created;
- read-only v33 evidence tree, contract, catalog, progress and two command locks: passed;
- local tiktoken 0.7.0 overlay: version, import origin and no-symlink checks passed;
- provider calls, canary episodes, collection, training, GPU work and held-out loads: zero.

The local HWE Git 2.31 binary filters `git apply --numstat` when invoked from a repository
subdirectory. Running the same 50 tests from the repository root passes, matching the established
Actions invocation. An initial unqualified full-tree Ruff command also saw user-owned untracked
scratch scripts; the scoped tracked-source check passed without modifying those files.

## Unique authorized execution

After the authorization merge and green `main` checks, execute exactly once from a clean checkout
whose `HEAD` equals `origin/main`:

```bash
PYTHONPATH=/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/tiktoken-overlay:.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src:integrations/verigym-deepseek-harness/src \
VERIGYM_RUN_OPENHANDS_HWE_V34_PROVIDER_CANARY_V1=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/collect_cva6_hwe_openhands_v34_provider_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v34_provider_canary_v1.json \
  --materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --training-source /data/jzhu484/Agent/experiments/openhands-hwe-v26-streamed-public-qualification-v1/sources/pr-2330 \
  --validation-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-3204 \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v1/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v34-provider-canary-v1
```

The opt-in remains disabled until the merge and protection checks are complete. No provider call,
formal collection, training, GPU work or held-out loading is part of this authorization review.
