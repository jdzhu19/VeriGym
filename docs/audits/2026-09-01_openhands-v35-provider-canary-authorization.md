# OpenHands v35 provider-canary successor authorization

## Authorization boundary

This change authorizes one execution of the v35 provider canary only after this pull request is
merged and all eight repository protection classes pass on `main`. It is the next unused identity
after the sealed, zero-provider v34 infrastructure stop:

- orchestration identity `openhands-hwe-v35-provider-canary-v1`;
- campaign `openhands-hwe-v35-codex-free-required-tool-canary-v1`; and
- agent `openhands-deepseek-v4-flash-hwe-v35-codex-free-canary-v1`.

The schedule remains PR-2330 training followed by PR-3204 validation, seed 489 and sample index 5.
The authorization hash is
`b69f313c8f48ba2e990c420f7a702a31054001b2924bd1c9f2521b542fec091d`.
DeepSeek v4 Flash, OpenHands SDK 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0,
transformers 4.57.6, temperature zero, 64 calls, 1,000,000 provider tokens, 65,536 context
tokens, 2,048 output tokens and zero retries remain fixed. No reserve task, fallback identity,
formal collection, held-out task, SFT, GPU work or adapter publication is authorized.

## Frozen predecessor and command-runtime evidence

The runner revalidates the v33 materialization tree
`62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6` and both exact command
images. PR-2330 remains bound to
`sha256:3ba2d622fbec6891484c8529892be39db33e02127ec9aaec80381b7d87e64540`; PR-3204 remains bound
to `sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784`.
The containers are Codex-free and credential-free, use `episode_container_exec_v1`, and run with
`network=none`.

The successor also requires the v34 stop audit merge
`874671e05f67d25fe4efd23bc16d56912eeba0f2` and exact four-file evidence tree
`fd529806fa40590de65bfdd09cd0428399923a3f9f581c5e39533f003a11cf5a`. The predecessor report
hash is `e684f04fe14184df0ee47ec48b225dfe965fb48da2c2fc54c898f1a8383af234`; it proves zero provider
episodes, zero calls, zero task attempts and no formal collection or training. v34 remains sealed
and is never retried or relabelled.

## Control-plane correction and fail-closed result policy

Before creating the v35 output, the runner requires the exact short, real, non-symlink broker
directory `/data/jzhu484/Agent/.verigym-tmp/oh-v35` and four absolute, unique, existing,
non-symlink MCP Python-path entries frozen in the authorization. It invokes the same validators
used by the runtime. The content-free control-plane contract hash is
`4cb55cc32e5d5ede372b6a76d98df2737e0a7b882ee164a7c44b95d7934b3981`.

After output creation, the zero-provider preflight records only completed stage identifiers, a
failed stage identifier and exception class. It never records raw exception text. Both locked
command images must prepare and close successfully before the provider service is constructed.
Any failure seals v35 without an in-place retry and requires another unused identity.

PR-3204 runs only if PR-2330 passes benchmark verifier, required-tool protocol, exact trajectory,
infrastructure, security and SFT admission. Successful tasks atomically retain the full OpenHands
trajectory, decision-only rows, protocol and trajectory receipts, exact-64K token receipt and
security sidecar. Endpoint, credential and active proxy values are checked in memory and are not
printed, persisted or hashed. Only two complete six-plane passes set
`formal_collection_allowed=true`; collection and training still remain unstarted pending a
separate result audit and later materialization/readiness authorizations.

## Unique authorized execution

After merge and green `main` checks, create the dedicated controller directory and execute exactly
once from a clean checkout whose `HEAD` equals `origin/main`:

```bash
install -d -m 700 /data/jzhu484/Agent/.verigym-tmp/oh-v35

PYTHONPATH=/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/tiktoken-overlay:.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src:integrations/verigym-deepseek-harness/src \
VERIGYM_OPENHANDS_BROKER_ROOT=/data/jzhu484/Agent/.verigym-tmp/oh-v35 \
VERIGYM_OPENHANDS_MCP_PYTHONPATH=/data/jzhu484/Agent/VeriGym/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src \
VERIGYM_RUN_OPENHANDS_HWE_V35_PROVIDER_CANARY_V1=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/collect_cva6_hwe_openhands_v35_provider_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v35_provider_canary_v1.json \
  --materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --stopped-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v34-provider-canary-v1 \
  --training-source /data/jzhu484/Agent/experiments/openhands-hwe-v26-streamed-public-qualification-v1/sources/pr-2330 \
  --validation-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-3204 \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v1/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v35-provider-canary-v1
```

The opt-in remains disabled during review. The later zero-provider formal command-image
materialization and formal collection readiness identities shift to v36 and v37 respectively.
