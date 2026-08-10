# Online RTL Training

VeriGym keeps policy training outside the evaluator package while providing three hash-bound
interfaces: frozen held-out evaluation, resumable campaign execution, and an optional rLLM/verl
online workflow. None of these interfaces makes held-out samples eligible for training.

## Freeze and compare policies

`configs/training/qwen35_heldout_v1.json` selects a fixed 12-task VerilogEval V2 set spanning
combinational, sequential, LFSR, and FSM designs. Freeze it before sampling:

```bash
python scripts/freeze_qwen35_heldout.py \
  --config configs/training/qwen35_heldout_v1.json \
  --source "$VERILOG_EVAL_ROOT" --output "$EVAL_ROOT" \
  --training-public-input prior-task.json \
  --frozen-after-policy "$POLICY_VERSION_HASH"
```

Run `scripts/run_qwen35_heldout_policy.py` once per registered policy with identical sampling and
verifier arguments. `scripts/summarize_qwen35_heldout.py` then reports compile rate, resolved rate,
task-level pass@k, infrastructure-invalid count, and verifier wall time. The summary requires exact
task coverage and never silently turns infrastructure errors into zero rewards.

## Resumable campaigns

`verigym-training-reference run-campaign` executes a declarative JSON DAG without a shell. Each
stage declares dependencies, GPU IDs, retry policy, timeout, workspace-relative outputs, and a
workspace quota. Ready stages may run concurrently only when their GPU allocations do not overlap.
Completed outputs are hashed; resume skips an intact stage and fails closed if an artifact changed.
Only a small system environment allowlist is inherited, and credential-like variables are rejected.

```bash
verigym-training-reference run-campaign \
  --config configs/training/qwen35_rllm_verl_online_smoke_v1.json \
  --workspace "$CAMPAIGN_ROOT" --repository "$PWD"
```

Set `VERIGYM_OUTPUT_POLICY_ID` to the portable successor identity before launching. After the
online stage succeeds, the campaign writes `registered-policy/adapter/`, a hashed reward manifest,
and `registered-policy/policy-version.json`. The compact policy is registered as the exact
successor of `VERIGYM_INPUT_POLICY_VERSION`; the large resumable FSDP checkpoint remains a trainer
artifact and is not needed for evaluation.

## Full rLLM + verl smoke

The online smoke uses rLLM `AgentTrainer`, Ray, asynchronous vLLM rollout servers, verl GRPO, and a
VeriGym `Workflow`. The model receives two public turns (plan, then RTL). Training runs in a
network-disabled container that has neither the Docker socket nor the verifier source tree. A
host-side broker accepts hash-bound candidates, runs the evaluator-owned Docker verifier, and
returns only a sparse outcome and artifact hashes. Hidden testbenches and reference solutions never
enter model messages, trajectories, or the training container. Infrastructure-invalid verification
raises a retryable workflow error rather than producing reward zero.

The committed campaign is deliberately bounded to two training tasks, four rollouts per task, four
GPUs, and one optimizer update. It loads the registered input LoRA, saves a resumable verl
checkpoint, emits `online-completion-report.json`, and registers the changed LoRA as a compact
successor policy. The completion report qualifies interoperability and
weight synchronization only when at least one rollout group has reward variance; it is not a
convergence or benchmark claim. The pinned compatibility pair is rLLM `v0.3.0-pre` with verl
`v0.7.1`, which includes the upstream Qwen3.5 FSDP2/vLLM path.
