# OpenHands v36 provider-canary successor authorization

## Authorization boundary

This change authorizes one execution of the v36 provider canary only after this pull request is
merged and all eight repository protection classes pass on `main`. It is the next unused identity
after the sealed, zero-provider v35 infrastructure stop:

- orchestration identity `openhands-hwe-v36-provider-canary-v1`;
- campaign `openhands-hwe-v36-codex-free-required-tool-canary-v1`; and
- agent `openhands-deepseek-v4-flash-hwe-v36-codex-free-canary-v1`.

The schedule remains PR-2330 training followed by PR-3204 validation, seed 489 and sample index 5.
The authorization hash is
`71d6ed7f4d33d5dd71125c53415e8baff3c72458657d89547ac2635eeda87592`.
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

The successor retains the v34 stop chain and additionally requires the v35 stop audit merge
`8c0ddbff2ad62243e90e3aba8b6209c04d26adc4` and exact 13-file evidence tree
`5070d15deb17650bb368290a3757b0f2d7f3c2b31dc7ebff108a7ab547849f8f`. The immediate
predecessor report hash is
`e95d52b2bc1ab570aa792449405ca893992fb54e14808656821858cd1d421690`; it proves both locked command
images passed zero-call preflight and the first task stopped at the stale adapter-start gate before
any model call. It records zero provider episodes, zero calls, zero completed task attempts and no
formal collection or training. Both v34 and v35 remain sealed and are never retried or relabelled.

## Control-plane correction and fail-closed result policy

Before creating the v36 output, the runner requires the exact short, real, non-symlink broker
directory `/data/jzhu484/Agent/.verigym-tmp/oh-v36` and four absolute, unique, existing,
non-symlink MCP Python-path entries frozen in the authorization. It invokes the same validators
used by the runtime. The content-free control-plane contract hash is
`f06c1d69cac05c5a8479d5593a6384f4dba4c203d38b5984d8c9206c05a68656`.

After output creation, the zero-provider preflight records only completed stage identifiers, a
failed stage identifier and exception class. It never records raw exception text. Both locked
command images must prepare successfully and each real runtime session must expose the exact
`episode_container_exec_v1` capability through the production external-agent bridge. The
OpenHands adapter-start validator must accept each bridge before the provider service is
constructed. Any failure seals v36 without an in-place retry and requires another unused identity.

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
install -d -m 700 /data/jzhu484/Agent/.verigym-tmp/oh-v36

PYTHONPATH=/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/tiktoken-overlay:.:src:integrations/verigym-hwe-bench/src:integrations/verigym-openhands/src:integrations/verigym-deepseek-harness/src \
VERIGYM_OPENHANDS_BROKER_ROOT=/data/jzhu484/Agent/.verigym-tmp/oh-v36 \
VERIGYM_OPENHANDS_MCP_PYTHONPATH=/data/jzhu484/Agent/VeriGym/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src:/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src \
VERIGYM_RUN_OPENHANDS_HWE_V36_PROVIDER_CANARY_V1=1 \
/data/jzhu484/Agent/.verigym-tmp/openhands-ci-py312-v1/bin/python \
  scripts/collect_cva6_hwe_openhands_v36_provider_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v36_provider_canary_v1.json \
  --materialization-root /data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1 \
  --stopped-v34-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v34-provider-canary-v1 \
  --stopped-v35-canary-root /data/jzhu484/Agent/experiments/openhands-hwe-v35-provider-canary-v1 \
  --training-source /data/jzhu484/Agent/experiments/openhands-hwe-v26-streamed-public-qualification-v1/sources/pr-2330 \
  --validation-source /data/jzhu484/Agent/experiments/cva6-multiturn-sft-qualification-v1/sources/pr-3204 \
  --tokenizer-root /data/jzhu484/Agent/datasets/Qwen3.5-9B \
  --base-model-lock /data/jzhu484/Agent/experiments/cva6-hwe-codex-native-shell-v2/training-ready-complexity-repair-v1/base-model-lock.json \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v36-provider-canary-v1
```

The opt-in remains disabled during review. The later zero-provider formal command-image
materialization and formal collection readiness identities shift to v37 and v38 respectively.
