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
