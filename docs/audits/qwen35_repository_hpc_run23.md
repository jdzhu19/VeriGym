# Qwen3.5 repository GRPO HPC run 23

Run 23 was a four-A30 developmental repository-GRPO attempt on CVA6 PR 2170. It was not a
qualified optimizer step or benchmark score. All four repository sessions were infrastructure
valid and unresolved, received zero reward, and terminated with `ENV_DONE`. The broker reported
no infrastructure-invalid sessions and the trainer received no Docker socket, source root,
hidden asset, reference solution, or credential values.

The run used implementation commit `b75d5a32bfd4ec5cd3ca84d5a627b24c21f02b89`, native runtime
manifest hash `e14566fd19af53430d6eede47d21eb83f3ee39dcc4d0cf697ad4e9d4fefffb79`,
task input SHA-256 `c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36`,
split SHA-256 `a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`,
and broker report hash `9e41e1bc08148e574513cd5e51c6d6bc8c21b61e1884d411bcd7e7317ad1fc3d`.
The job-exclusive LSF allocation bound four A30 GPUs and 16 CPU slots. The official pinned
PyTorch container remained the verifier environment; verification ran with networking disabled.

## Result

All four trajectories completed in 25 minutes 58 seconds. Covering the causal
`qwen3_5_text` model identifier eliminated run 22's mixed Tensor/DTensor failure, and the trainer
entered actor log-probability computation. It then failed in the Qwen3.5 backbone's
`torch_chunk_gated_delta_rule` while trying to allocate 256 MiB with 135.44 MiB free:

```text
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 256.00 MiB.
```

This was a training integration failure after valid rollouts, not a verifier rejection. No
optimizer step, checkpoint, or completion report was produced. The broker stopped cleanly and
the reusable interactive LSF bash allocation remained active.

## Root cause and follow-up

Run 22's compatibility change kept the approximately 2 GiB output head inside the root FSDP2
unit. That avoided a direct operation on a sharded head, but also retained the full head on each
GPU for the entire backbone forward. The actor used about 10.94 GiB per GPU while the colocated
vLLM process used about 12.40 GiB, leaving insufficient space for a 256 MiB recurrent-attention
allocation.

Restore independent FSDP2 wrapping for `lm_head` and invoke the bounded fused projection through
the head module. Its pre-forward hook can then all-gather the head only for the chunked projection
and reshard it immediately afterward. A two-rank CUDA probe using nested FSDP2, CPU offload, veRL's
Torch fused PPO operation, and a standard Transformers model output completed forward and
backward on both ranks; the head gradients returned to CPU DTensor shards.
