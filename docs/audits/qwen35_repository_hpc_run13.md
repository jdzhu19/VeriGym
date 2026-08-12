# Qwen3.5 Repository HPC Qualification: run13

Date: 2026-08-12

This audit records an opt-in, single-step development qualification on six scheduler-owned A30
GPUs. The task was the non-held-out CVA6 PR2170 development task. This is an infrastructure and
agent-scaffold qualification, not a benchmark score or evidence of RL convergence.

## Isolation and frozen inputs

The model and trainer ran on the GPU compute node. The trusted repository broker and Docker
verifier ran on the login VM, where Docker is available; verification remained CPU-only and used
the official digest-locked HWE image with network disabled. The trainer received no source root,
Docker socket, hidden verifier assets, reference patch, or credential values.

The run used implementation commit `d90f61897586867b4dd7f521dcb0abc840479d24`, Qwen3.5-9B with
the registered RTL policy-v5 adapter, rLLM `v0.3.0-pre`, verl `v0.7.1`, tensor parallelism two,
FSDP2 over six GPUs, and six GRPO rollouts. The native runtime manifest was hash-bound before the
first model request.

## Observed outcome

The deterministic repository projection reduced the initial model prompt to 5,000 tokenizer
tokens, below the frozen 16,384-token prompt limit. All six rollouts therefore reached real model
generation; no prompt-length failure recurred. The broker completed six sessions with zero
infrastructure-invalid outcomes, and its report SHA-256 is
`c63b6941bac941cefec686edd1335f16cfbb37b6650b36b181b651b0e253609e`.

Each first completion selected a semantically plausible CVA6 cache-related file and a `read_file`
action, but every completion omitted the required top-level `protocol` member. Strict
`repository_action.v2` validation rejected these as model-output errors. No permissive repair or
protocol inference was added.

rLLM retained six zero-reward trainable trajectories and advanced to actor log-probability
computation. That phase exhausted GPU memory before the optimizer step: one worker had only
161.50 MiB free when a 256 MiB allocation was requested. The accompanying
`CUBLAS_STATUS_NOT_INITIALIZED` errors were secondary CUDA failures. The LSF allocation's
effective GPU mode was also `mode=shared:j_exclusive=no`; OOM diagnostics identified unrelated
processes using several hundred MiB on the selected GPUs. The run therefore does not isolate a
single memory cause: the 0.5 resident-rollout envelope left inadequate headroom, and scheduler
sharing allowed external load after the clean startup preflight. No checkpoint or changed adapter
was produced, so run13 is infrastructure-invalid as a training qualification even though the
broker/verifier path itself remained valid.

## Corrective action

The repository system prompt now includes one exact canonical JSON envelope with all three
required top-level keys while preserving strict parsing. An initial follow-up reduced the vLLM
memory envelope from 0.5 to 0.4, but the clean, job-exclusive run18 follow-up documented separately
showed that 0.4 cannot allocate a single KV-cache block. The configuration therefore retains the
viable 0.5 envelope. The rollout engine remains resident: this node's legacy CUDA driver was
separately observed to reject vLLM's CuMem sleep allocator, so enabling cache-engine sleep is not a
valid workaround. Subsequent optimizer-step qualification must use scheduler-enforced
job-exclusive GPUs; a point-in-time contention preflight alone cannot prevent another shared LSF
job from entering after startup.

The next qualification must use a fresh run identity. Acceptance still requires reward variance,
one completed optimizer update, a resumable checkpoint, and a changed registered adapter.
