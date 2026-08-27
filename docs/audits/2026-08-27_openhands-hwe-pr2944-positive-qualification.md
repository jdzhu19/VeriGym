# OpenHands HWE PR2944 positive trajectory qualification

Date: 2026-08-27

## Scope

This was one independent, no-retry, training-role OpenHands SDK episode on the
already-qualified CVA6 PR2944 task. It qualified collection, ordinary verification,
trajectory export, and an in-memory exact-loader replay. It did not admit a dataset, start
training, use a GPU, write an optimizer checkpoint, or write an adapter.

The frozen source identity was:

- branch: `agent/openhands-trajectory-collector-v1`
- source commit: `4608a26a193018a4c1ef3a5382bdc753949bfe78`
- agent version hash: `ab2c868402617d542ba8ce13515f35093e758d3ab458484e8779c761c2eccbb5`
- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944`
- agent-image lock hash: `99cb8d40807c62fdfb0c48f9b1e98bdbfc2a55e73223367c3f81337eea39de0c`
- model transport: `openai/deepseek-v4-flash`
- seed: `484`
- OpenHands SDK / LiteLLM / HWE tiktoken: `1.42.1` / `1.93.0` / `0.7.0`
- tool-choice policy: `validated_responses_recovery_state_required_tool_v11`

GitHub Actions run
[`33042901115`](https://github.com/jdzhu19/VeriGym/actions/runs/33042901115) completed
successfully for the frozen source commit, including the Python 3.12 OpenHands job.

## Result

The single model episode passed all positive acceptance gates:

- broker-owned typed finish observed
- ordinary verifier resolved the task
- one SFT-eligible trajectory exported
- infrastructure and runtime evidence complete
- 13 model calls, 14 broker tool calls, and 2 patch calls
- 11 assistant decisions and 14 canonical tool actions
- 3 sibling-call decisions
- wall time: 218.966 seconds, excluding Docker preflight
- credential-value scan passed with zero hits

The trajectory used `verigym_openhands_exact_tool_trajectory_v2` because the recovery policy
was enabled. No recovery was actually exercised (`format_recovery_count=0`), and no rejected
decision required masking. The sealed trajectory SHA-256 is
`2fd5b284629fe8dc438802709fc5398f978130638b7a875f9e0be4d3b45bbfc0`; the sealed
qualification report hash is
`22ec2df51b4b9c5ef4b58c894f75f49aa7e2ffdbe02a5a9cb6de046c35b40bc3`.

## Exact-loader replay

An independent, in-memory replay used the official Transformers checkout
`e8ea728a3eeeb903e77c7d1bd29267c80a1be71f`, `trust_remote_code=false`, and the frozen local
Qwen3.5 tokenizer. All 11 decisions passed exact retokenization and complete decision-only
loss-mask validation:

- tokenizer hash: `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`
- chat-template hash: `a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715`
- six-tool schema hash: `bdb68bd257a4bd9a6316bd98df5be7a116d54b2f6f83891444a4bf8d7feda569`
- maximum total/input/target tokens: `9,434` / `9,079` / `355`
- rows over 32,768 / 65,536 tokens: `0` / `0`
- truncation applied: `false`

The replay did not persist a decision dataset, so `dataset_admission=false` remains unchanged.

## Operational notes and limits

One zero-model Docker preflight was interrupted before experiment output or any provider call
because its host scratch directory defaulted to `/tmp`. The temporary container was removed,
`TMPDIR` was moved under `/data/jzhu484/Agent/.verigym-tmp/`, and preflight was restarted. The
accepted model episode itself ran exactly once with provider and whole-episode retries disabled.

The sanitized experiment remains outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-positive-trajectory-qualification-v1/`.
This one-task qualification is not a benchmark score or evidence of production-training
readiness. The final flags remain `production_training_ready=false`, `training_started=false`,
`optimizer_steps=0`, `checkpoint_written=false`, and `adapter_written=false`.
