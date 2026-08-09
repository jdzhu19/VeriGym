# External Training Reference Pipeline

The `verigym-training-reference` integration proves that an external trainer can consume VeriGym
without moving RL framework code, credentials, model weights, or hidden verifier data into the
evaluator. It supports offline warm-start data and an online completion-to-reward adapter.

## Pipeline boundary

1. Run a frozen training split with VeriGym and export `observable_repo_trajectory_v1`.
2. `prepare` validates that dataset, excludes held-out, ineligible, and infrastructure-invalid
   episodes, then seals aligned `episodes.jsonl` and `rewards.jsonl`.
3. An external framework trains the model. It can wrap `TrainingRewardOracle.score()` as its
   reward function; only scalar/decomposed outcomes cross the verifier boundary.
4. `register-checkpoint` hashes the resulting adapter or checkpoint and creates an immutable,
   secret-free `ExternalAgentVersionImportManifest`.
5. Serve the registered artifact through a compatible OpenAI-style endpoint and evaluate it with
   an ordinary frozen VeriGym experiment and held-out split.

The online oracle rejects task IDs outside the frozen training split. Hidden tests remain mounted
only in the verifier session, and infrastructure-invalid runs return `scalar_reward: null` so a
trainer can reschedule them instead of learning from an infrastructure failure.

## TRL/GRPO adapter

The reference package supplies a dependency-free adapter for TRL's documented `prompt` dataset
column and custom reward callable:

```python
import os

from datasets import Dataset
from trl import GRPOConfig, GRPOTrainer
from verigym_training_reference import (
    TrainingRewardOracle,
    TrlRewardAdapter,
    build_trl_dataset_rows,
)

oracle = TrainingRewardOracle(
    bundle=training_bundle,
    source_dataset=trajectory_dataset,
    output_root=rollout_runs,
    runtime="local",
)
training_data = Dataset.from_list(build_trl_dataset_rows(oracle))
trainer = GRPOTrainer(
    model=os.environ["VERIGYM_TRAINING_MODEL_ROOT"],
    args=GRPOConfig(output_dir=os.environ["VERIGYM_TRAINING_OUTPUT_ROOT"]),
    train_dataset=training_data,
    reward_funcs=TrlRewardAdapter(oracle),
)
trainer.train()
```

The adapter accepts plain-text or conversational completions and passes each completion to its
frozen task ID. This follows the official
[TRL GRPO custom-reward contract](https://huggingface.co/docs/trl/grpo_trainer); install and pin
TRL, Transformers, PEFT, Accelerate, and the distributed runtime in the external trainer
environment, not in VeriGym.

## Local Qwen3.5-9B preparation

The checked-in example uses an environment variable so host paths never enter persistent
artifacts:

```bash
python -m pip install -e ./integrations/verigym-training-reference
export VERIGYM_TRAINING_MODEL_ROOT=/path/to/Qwen3.5-9B
export VERIGYM_TRAINING_OUTPUT_ROOT=/path/to/training-runs

verigym-training-reference prepare \
  --dataset /path/to/exported/trajectory-dataset \
  --config integrations/verigym-training-reference/examples/qwen3.5-9b-grpo.json \
  --output /path/to/training-bundle
```

Model preflight verifies `config.json`, the safetensors index, every declared shard, byte counts,
and portable metadata hashes. It intentionally does not hash roughly 19 GB of weight contents on
every bundle preparation; the final trained adapter/checkpoint is fully content-hashed when it is
registered.

For high-frequency RL, use local Icarus/Yosys-backed training tasks. Reserve VCS/DC for bounded
qualification or held-out audits so license availability and tool latency do not become the
learning signal.

The [Qwen3.5-9B/VCS reference smoke](audits/external_training_reference_smoke.md) records the first
real model-snapshot preflight, sealed handoff replay, and online reward-oracle result.

## Codex distillation and rLLM/verl path

The bounded reference path keeps model sampling, verifier execution, and training in separate
processes:

```text
Codex public-task sample -> isolated VeriGym verifier -> verified chat JSONL -> Qwen LoRA SFT
Qwen rLLM trajectory     -> isolated VeriGym verifier -> sparse reward      -> verl GRPO
```

Use `scripts/export_public_task_input.py` to create a public-only task record. Strong-model samples
can be produced with `scripts/run_codex_solution_sampler.py` and sealed with
`verigym-training-reference export-sft`; run `scripts/train_qwen35_verified_sft.py` from an
Accelerate environment for the warm-start step.

For the RL boundary, `scripts/generate_qwen35_rllm_rollouts.py` serializes official rLLM
`Episode`, `Trajectory`, and `Step` objects, including old-policy token log probabilities. Then
`scripts/score_rllm_rollouts.py` evaluates each candidate. It retains full verifier artifacts under
the evaluator-owned output while the scored JSONL exports only a scalar outcome and hashes.
For multi-task updates, `scripts/merge_rllm_reward_groups.py` accepts only groups from one policy
version with valid infrastructure and nonzero reward variance in every group. Finally,
`scripts/train_qwen35_verl_grpo.py` calls verl's outcome-GRPO advantage and clipped policy loss
implementations and writes a content-hashed LoRA adapter. Each group maps to one distributed
optimizer step.

For iterative experiments, keep evaluator source separate from weight-bearing artifacts:

```text
campaign/
  versions/       base.json, policy-v0.json, policy-v1.json
  trajectories/   iteration-000/, iteration-001/
  rewards/        iteration-000/, iteration-001/
  checkpoints/    policy-v0/, policy-v1/, policy-v2/
  campaign-manifest.json
```

Use `verigym-training-reference register-policy-version` for the base snapshot, verified-SFT
adapter (`weight_version=0`), and every GRPO successor. Rollout generation requires the registered
input manifest and records its version hash and weight version in each rLLM step. Reward scoring
preserves this binding, and GRPO refuses trajectories or adapter bytes that do not match it. This
makes `policy-vN -> fresh rollout -> VeriGym reward -> policy-vN+1` auditable without embedding
trainer checkpoints in the repository.

The supplied `configs/accelerate/qwen35_4gpu_fsdp.yaml` is a four-GPU 3090 smoke configuration.
Change the world size and rollout group together for another machine. These scripts demonstrate a
real optimizer update; production Ray/vLLM rollout throughput, checkpoint recovery, and longer
campaign convergence remain separate qualification work.
