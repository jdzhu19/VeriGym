# Qwen3.5 Repository HPC Qualification: run20

Date: 2026-08-13

This audit records an opt-in, single-step development attempt on four job-exclusive A30 GPUs. The
task was the non-held-out CVA6 PR2170 development task. This is not a benchmark score or evidence
of RL convergence.

## Isolation and frozen inputs

LSF job 455225 requested four GPUs and sixteen CPU slots on the GPU compute node. Its effective
GPU requirement was `mode=shared:mps=no:j_exclusive=yes`; the reusable interactive bash remained
alive after the training child returned.

The run used implementation commit `6429471e0793e253269aeb94d95ff28426fe0a09`, FSDP size four,
rollout group size four, tensor parallelism two, the 0.5 vLLM memory envelope, and FSDP2 actor CPU
offload. The native runtime manifest identity was
`d238ae391d5bb1c524b22a3aaf626783388e5a1d98024149db4d1422ffbbebe5`. The online task and split
file SHA-256 values were, respectively,
`c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36` and
`a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`.

The trusted repository broker and Docker verifier remained CPU-only on the VM. The verifier used
the pinned image with network disabled and did not export the source root, Docker socket, hidden
assets, reference patch, or credentials to the training process.

## Observed outcome

Both tensor-parallel rollout engines initialized, and all four sessions exercised the strict
multi-turn `repository_action.v2` scaffold. The final broker report recorded four
infrastructure-valid sessions, zero infrastructure-invalid sessions, and zero resolved sessions;
its report hash was `84f08e7449a2babf8c35215688c0273377fab029e3d949960d8d78d6ae7fde36`.
Three trajectories stopped after 4, 10, and 27 actions because of extra prose, a repository policy
violation, and invalid arguments. The fourth remained active through 111 repository reads before
ending in a policy violation. These are model or policy outcomes, not verifier or infrastructure
failures.

Actor CPU offload eliminated run19's parameter-unshard failure and reduced the observed host
resident set during rollout generation from approximately 97 GiB to 62.4 GiB. Actor
log-probability computation then failed at a distinct activation peak: Qwen3.5's ordinary
causal-LM head tried to allocate 15.16 GiB while materializing logits for the maximum-length
trajectory. The model vocabulary has 248,320 entries, so a full 32K-sequence logits tensor cannot
fit beside the resident 12.41 GiB vLLM worker on a 24 GiB A30. No optimizer step, checkpoint,
completion report, or changed adapter was produced.

## Corrective action

Retain actor CPU offload and the viable 0.5 rollout envelope. Enable verl's supported fused PPO
linear head with the Torch backend, which computes log probabilities and entropy in bounded
512-token chunks instead of materializing the full sequence-by-vocabulary tensor. Keep the frozen
16K prompt and 16K response limits, job exclusivity, and a fresh run identity. Acceptance still
requires reward variance, one completed optimizer update, a resumable checkpoint, and a changed
registered adapter.
