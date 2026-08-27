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

The package also provides `run-campaign`, a shell-free resumable DAG runner for rollout,
verification, selection, training, checkpoint registration, and evaluation stages. Stage receipts
bind commands to artifact hashes and reject mutated outputs on resume.

Repository-level held-out sets can be frozen across prepared source roots without exporting issue
text, repository files, hidden verifier assets, or reference patches:

```bash
verigym-training-reference freeze-repository-heldout \
  --split-id hwe-repo-heldout-v1 \
  --agent-version /path/to/frozen-agent-version.json \
  --source-task /path/to/ibex::hwe-bench/repo-repair-v1/lowRISC__ibex__pr-222 \
  --source-task /path/to/cva6::hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2945 \
  --source-task /path/to/rocket::hwe-bench/repo-repair-v1/chipsalliance__rocket-chip__pr-3065 \
  --output /path/to/heldout-freeze
```

The output contains only a task split and its hash-only task/source/agent binding. It is marked
ineligible for training. `run_codex_repository_campaign.py --campaign-role heldout` requires both
this directory and the same complete agent-version manifest, and rejects task-set or identity
drift before sampling.

Verifier-filtered strong-model solutions can be exported separately for SFT:

```bash
verigym-training-reference export-sft \
  --sampling-root /path/to/codex-solution-sample \
  --output /path/to/verified-sft
```

This fail-closed export accepts only a resolved, integrity-verified run. `train.jsonl` contains
portable `messages` plus model, task, source, candidate, and verifier hashes; hidden tests, reference
solutions, private reasoning, credentials, and host paths are excluded.

External RL code can call `TrainingRewardOracle.score(task_id, completion)`. The oracle accepts
only tasks frozen into the bundle's training split, evaluates the completion through an ordinary
VeriGym run, and returns a typed reward without exporting verifier assets. Infrastructure-invalid
results have no scalar reward and should be rescheduled, not treated as model failures.

For TRL, `build_trl_dataset_rows(oracle)` creates the required `prompt` column plus a bound
`task_id`, and `TrlRewardAdapter(oracle)` implements the custom reward callable. The adapter returns
`None` for infrastructure-invalid completions, matching TRL's non-applicable reward convention.
TRL and its GPU dependencies remain trainer-owned and are not installed with this package.

## rLLM and verl reference smoke

The repository also includes opt-in scripts for a small but real two-stage training check:

1. `generate_qwen35_rllm_rollouts.py` records two-turn rLLM `Episode` objects and old-policy token
   log probabilities from a local Qwen3.5 adapter.
2. `score_rllm_rollouts.py` submits candidates to isolated VeriGym Docker runs and exports only
   sparse rewards and artifact identities.
3. `merge_rllm_reward_groups.py` optionally combines compatible task groups after checking policy
   identity, infrastructure validity, and per-group reward variance.
4. `train_qwen35_verl_grpo.py` uses verl's GRPO advantage and clipped policy loss for bounded
   4-GPU FSDP LoRA updates. Each group produces one distributed optimizer step.

Every expensive script requires an explicit `VERIGYM_RUN_*` opt-in. The smoke fails closed on
infrastructure-invalid outcomes and on groups without reward variance. It validates the data and
optimizer boundary; it does not qualify verl's full Ray/vLLM rollout stack.

Register each executable policy before sampling it:

```bash
verigym-training-reference register-policy-version \
  --output /campaign/versions/policy-v1.json \
  --policy-version-id qwen35-9b-rtl-policy-v1 --weight-version 1 \
  --update-type verigym_grpo --model-id Qwen/Qwen3.5-9B \
  --model-root /models/Qwen3.5-9B --artifact /campaign/checkpoints/policy-v1 \
  --parent /campaign/versions/policy-v0.json \
  --training-manifest /campaign/trajectories/iteration-000/rollout-manifest.json \
  --reward-manifest /campaign/rewards/iteration-000/reward-manifest.json \
  --training-report /campaign/checkpoints/policy-v1/training-report.json \
  --source-commit <40-character-git-commit>
```

Pass that manifest to rollout generation with `--policy-version`, and to GRPO with
`--input-policy-version`. Adapter bytes, policy hash, and rLLM `weight_version` must agree across
the complete rollout/reward/update chain.

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

The [weight-bound online iteration](../../docs/audits/qwen35_online_rl_iteration_v2.md) records a
fresh policy-v1 rollout, VeriGym reward group, and four-GPU policy-v2 update.
The [multi-task online campaign](../../docs/audits/qwen35_multitask_online_rl_v4.md) records two
fresh cross-suite iterations from policy-v2 through policy-v4.

An opt-in full-stack example is defined in
`configs/training/qwen35_rllm_verl_online_smoke_v1.json`. It uses `VeriGymRtlWorkflow` with the
official rLLM `AgentTrainer`, Ray/vLLM rollouts, and verl GRPO. rLLM, verl, vLLM, and GPU
dependencies remain external requirements; ordinary package tests do not import or require them.
The trainer container has no network, verifier source mount, or Docker socket. Candidate scoring is
performed by a host-side, hash-bound broker so verifier-owned assets remain outside the policy
process.

For repository-level online rollouts, launch `run_qwen35_online_container.py` with
`--workflow repository`. This selects `VeriGymRepositoryWorkflow`: rLLM owns the multi-turn loop
and captures every turn's token IDs and log probabilities, while a separate host broker owns the
VeriGym Docker workspace and hidden verification. The repository workflow uses
`repository_action.v2` and does not impose an additional per-action output-token cap unless one
is explicitly configured.

`configs/training/qwen35_repository_rllm_verl_online_smoke_v1.json` is the bounded opt-in CVA6
PR2170 example. It requires a frozen training split and source-lock v2 source through
`VERIGYM_REPOSITORY_TRAINING_SPLIT` and `VERIGYM_CVA6_TRAINING_SOURCE`. Its 32K rollout capacity
is an explicit four-24-GiB-GPU smoke resource envelope; the workflow itself still delegates turn
count to the task budget and sets no per-action token override.

On the current LSF cluster, do not retain an interactive GPU `bash` allocation. Submit each bounded
GPU qualification, training run, or GPU-coupled rollout as its own non-interactive payload and let
the allocation exit when that payload returns. `scripts/submit_ephemeral_lsf_gpu_job.py` constructs
an argv-only `bsub`, rejects shell payloads and interactive flags, requests job-exclusive GPUs on
one host, and writes a secret-free submission receipt beside the scheduler logs. For example:

```bash
PYTHONPATH=src:integrations/verigym-training-reference/src \
python scripts/submit_ephemeral_lsf_gpu_job.py \
  --job-name hwe-sft-probe --gpus 4 --cpus 16 --wall-minutes 120 \
  --working-directory /hpc/home/connect.jzhu484/agent/VeriGym \
  --output-directory /hpc/home/connect.jzhu484/agent/experiments/hwe-sft-probe-001 \
  -- python -m verigym_training_reference.hwe_decision_sft_64k_entry <bound arguments>
```

Do not put credentials in payload arguments: LSF owns job command metadata even though VeriGym's
receipt intentionally does not persist the arguments. CPU-only controller/verifier work remains a
separate scheduler payload. The login VM is only a control plane and image relay. The trusted
controller container uses the compute-node Docker socket to launch digest-locked sibling benchmark
sandboxes; it never uses privileged Docker-in-Docker. For schedulers that expose Docker only on a
login node, the older split native fallback remains documented in `../../docs/online_training.md`.

The exact 64K HWE loader declares its current batch-one objective as
`decision_balanced_target_token_mean_batch1_v1`: each decision is one optimizer batch and veRL
normalizes over that decision's supervised target tokens. This is deliberately not described as
full-trajectory maximum likelihood. OpenHands SDK decision datasets have their own explicit
`VeriGymOpenHandsDecisionSft64kTrainer` dispatcher and preserve the SDK-visible tool schemas through
the same parquet and Qwen template boundary. This dispatcher remains loader-qualification-only
until a matched full-trajectory-versus-decision objective is frozen.

## Verified multi-turn SFT mainline

The current SFT path is separate from the legacy one-record smoke. The legacy `v1` exporter and
trainer remain available at 16,384 tokens for replay compatibility. New bounded campaigns use
`export-multiturn-sft --format-version v2`, which accepts only integrity-bound training-split
transcripts and verified runs, applies the local Qwen chat template with rLLM's `hf_template`
segmentation, and fails instead of truncating beyond 32,768 tokens. The v2 path records the
`repository_observation_v1` identity and observation-efficiency metrics; raw observations remain
in the restricted training-run audit area and are not included in the dataset. Set
`VERIGYM_MULTITURN_SFT_VERSION=v2` when invoking `scripts/run_multiturn_sft_container.sh`.
Both versions require exactly eight sealed records and the frozen rLLM/veRL/vLLM versions before
launching `AgentSFTTrainer` for six optimizer steps.
The sealed records keep canonical OpenAI JSON-string tool arguments. A training-only dataset
adapter converts those strings to the mappings required by Qwen3.5's native template and groups
the leading masked `system`/`user` prefix, because that template rejects a system-only prefix. The
adapter is selected explicitly in the resolved veRL config; all assistant segments remain
supervised and the source records are never rewritten.

The supporting real-run sequence is:

1. `scripts/qualify_cva6_multiturn_pool.py` freezes 11 training candidates and two development
   validation tasks after zero-model base-FAIL/reference-PASS qualification.
2. `scripts/collect_cva6_multiturn_teachers.py` runs three independent Claude/DeepSeek MCP-only
   samples per task and one Codex/GPT-5.4 fallback, stopping after eight eligible successes.
3. `verigym-training-reference export-multiturn-sft --format-version v2 --collection-root
   <collection>` resolves the campaign receipt and seals the bounded mixed-provider training JSONL.
4. `scripts/train_qwen35_multiturn_sft_v2.py` trains the adapter, and
   `scripts/smoke_reload_qwen35_multiturn_adapter.py` performs the required four-A30 reload.
5. `scripts/smoke_qwen35_rllm_multiturn.py` exercises the native future-rollout interface with
   zero optimizer/GRPO updates.

The collection command freezes its resource envelope into `collection-progress.json`: 600 seconds,
32 broker tool calls, eight executed patch attempts, three consecutive rejected calls, a
2,000,000-token cache-inclusive Claude threshold, and a native USD 2 Claude budget. It also stops
the complete collection at 32,000,000 observed provider tokens or USD 40 of known cost. A resumed
output directory must match every value. Broker/provider-limit exhaustion remains an
infrastructure-valid agent failure and advances the bounded schedule; campaign-limit exhaustion
produces an incomplete report, while missing provider usage or another infrastructure-invalid
result stops the batch immediately. Provider token and dollar thresholds are response-granular,
so one in-flight response can cross a threshold before it becomes observable.

The native smoke client fixes BLAS, OpenMP, MKL, and NumExpr to one thread. It performs tokenizer
and HTTP orchestration rather than CPU training; bounding these libraries avoids importing NumPy
with a node-wide thread fan-out inside scheduler-constrained Docker without relaxing seccomp.
The runner also supplies a synthetic `USER`/`LOGNAME` for scheduler UIDs that are intentionally
absent from the image password database, so Torch cache discovery does not depend on host NSS.
On legacy compute-node Docker, the same explicit `VERIGYM_GPU_DOCKER_SECCOMP_PROFILE=unconfined`
compatibility switch used by the model and trainer containers is available for rLLM's required
Python executor thread. It never enables privileged mode, adds capabilities, or mounts a socket.

Every real command is explicitly opt in. Incomplete qualification or fewer than eight eligible
training trajectories ends with a report and does not start SFT.
