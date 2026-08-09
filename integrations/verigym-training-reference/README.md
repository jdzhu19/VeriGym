# VeriGym external training reference

This optional distribution is a framework-neutral consumer of VeriGym's public trajectory,
reward, split, and agent-version contracts. It does not embed TRL, veRL, OpenRLHF, or a training
loop in the evaluator.

Install it from the checkout:

```bash
python -m pip install -e ./integrations/verigym-training-reference
export VERIGYM_TRAINING_MODEL_ROOT=/path/to/Qwen3.5-9B

verigym-training-reference prepare \
  --dataset /path/to/trajectory-dataset \
  --config integrations/verigym-training-reference/examples/qwen3.5-9b-grpo.json \
  --output /path/to/training-bundle
verigym-training-reference validate \
  --bundle /path/to/training-bundle \
  --dataset /path/to/trajectory-dataset
```

The bundle contains aligned eligible `training` episodes and offline rewards, a frozen split,
the core external-trainer manifest, a secret-free trainer configuration, and a metadata-bound
model snapshot. Local model paths and weight contents are not copied into the bundle.

External RL code can call `TrainingRewardOracle.score(task_id, completion)`. The oracle accepts
only tasks frozen into the bundle's training split, evaluates the completion through an ordinary
VeriGym run, and returns a typed reward without exporting verifier assets. Infrastructure-invalid
results have no scalar reward and should be rescheduled, not treated as model failures.

For TRL, `build_trl_dataset_rows(oracle)` creates the required `prompt` column plus a bound
`task_id`, and `TrlRewardAdapter(oracle)` implements the custom reward callable. The adapter returns
`None` for infrastructure-invalid completions, matching TRL's non-applicable reward convention.
TRL and its GPU dependencies remain trainer-owned and are not installed with this package.

After training, register a LoRA adapter or checkpoint as provenance:

```bash
verigym-training-reference register-checkpoint \
  --bundle /path/to/training-bundle \
  --dataset /path/to/trajectory-dataset \
  --checkpoint /path/to/adapter \
  --output checkpoint-import.json \
  --import-id qwen35-rtl-lora-v1 \
  --parent-version-hash <sha256> \
  --compatible-runtime-hash <sha256> \
  --license Apache-2.0 \
  --provenance external-trl-run-001 \
  --revision step-100
```

See `docs/external_training_reference.md` for the complete boundary and rollout guidance.
