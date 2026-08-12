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

## Split broker and native GPU trainer

Clusters that expose Docker only on a login node can keep the same trust boundary by running
`run_qwen35_online_broker_container.py` on that node and
`run_qwen35_online_native.py` inside the scheduler-owned GPU allocation. The trusted broker keeps
the prepared source in a role-labeled Docker volume and communicates through the existing
hash-bound filesystem protocol. The native trainer receives only the public task manifest,
bounded observations, sparse outcomes, model, adapter, and code; it receives no source-root or
Docker-socket argument. Both sides use a shared campaign directory for requests and responses.

The native launcher requires a numeric scheduler-provided `CUDA_VISIBLE_DEVICES`, samples GPU
contention before importing PyTorch, and supports 4, 6, or 8 GPUs. It couples world size, FSDP
size, rLLM parallelism, and GRPO rollout group size (`n=N`) and writes the resolved values to a
hash-bound `native-training-runtime.json` before the first model call. `--gpu-count auto` uses the
largest supported uncontended subset; a fixed count fails closed when insufficient GPUs are clean.
Different topology hashes are different runs even when task and policy inputs are unchanged. The
runtime also binds the exact rLLM, verl, and Transformers source commits.

On an older host ABI, the native launcher may be invoked from an explicitly qualified PRoot
userspace with `run_qwen35_online_proot.py`; the inner launcher receives both
`--proot-executable` and `--proot-rootfs-identity`. The launchers fail
unless PRoot seccomp acceleration is disabled, then binds the executable SHA-256, exported rootfs
image ID, host kernel, and guest glibc to the runtime manifest. Paths are never persisted. This is
an ABI compatibility mechanism, not a relaxation of the broker/source separation.

When PRoot's process tracing is incompatible with Ray or NCCL multiprocessing, use the narrower
`run_qwen35_online_glibc.py` path. It verifies a regular Python executable whose ELF interpreter
and transitive RPATH are pinned to the exported userspace, plus the patched-Python, dynamic-loader,
patchelf, and rootfs image hashes. It removes inherited loader and proxy variables before launch.
This preserves native process creation while changing only the userspace glibc; it does not expose
the prepared source, Docker socket, hidden tests, or credentials to the trainer.

Native execution is opt-in. First freeze the Conda package inventory, verify a CUDA tensor, NCCL
collective, and vLLM load on the selected node, then run the zero-model base-FAIL/reference-PASS
qualification through the broker. A driver, image, package, or verifier mismatch is an
infrastructure failure and must stop before online training.
