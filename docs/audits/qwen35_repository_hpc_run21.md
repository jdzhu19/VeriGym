# Qwen3.5 repository GRPO HPC run 21

Run 21 was a four-A30 developmental repository-GRPO attempt on CVA6 PR 2170. It was not a
qualified optimizer step or benchmark score. All four repository sessions were infrastructure
valid and unresolved; two ended on workspace policy, one emitted invalid action arguments, and
one exhausted the 128-turn budget. No session changed the repository, so the group had no reward
variance.

The run used implementation commit `70b4cb8216128f23aedfc240927d52c70a834259`, native runtime
manifest hash `1b20f011ca968f9e92705554a19619d3f5aaec73871a4a9563dc8d43e5beedab`,
task input SHA-256 `c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36`,
split SHA-256 `a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`,
and broker report hash `bf5ddc50e2823e5aff995453840ac80b713a173cf6d411343095fc0c02add6dc`.
The job-exclusive LSF allocation bound four A30 GPUs and 16 CPU slots. The official pinned
PyTorch container remained the verifier environment; verification ran with networking disabled.

## Result

The four trajectories completed and the trainer entered actor log-probability computation. The
Torch fused PPO head avoided run 20's attempt to allocate a full 32K-by-248,320 logits tensor: no
CUDA out-of-memory error occurred. It instead failed immediately at the first chunked matrix
multiplication because the hidden states were an ordinary Tensor while the independently FSDP2-
wrapped `lm_head.weight` was a sharded DTensor:

```text
RuntimeError: aten.mm.default got mixed torch.Tensor and DTensor
```

This is an infrastructure/software-compatibility failure after valid rollouts, not verifier
rejection and not an optimizer-step qualification. No checkpoint or completion report was
produced. The broker stopped cleanly and reported four valid sessions, zero infrastructure-invalid
sessions, and zero resolved sessions. The reusable interactive LSF bash allocation was preserved.

## Follow-up

Keep the 16K prompt and response limits, FSDP2 CPU offload, 0.5 vLLM envelope, and bounded fused
projection. A two-rank synthetic FSDP2 probe reproduced the failure: the independently wrapped
head was a CPU `Shard(0)` at direct access, while gathering it failed because the CUDA mesh has no
CPU collective backend. Leaving the head in the root FSDP2 unit instead exposed a complete CUDA
Tensor during forward and completed backward into CPU-offloaded parameter shards on both ranks.
Restrict that wrap-boundary adjustment to Qwen3.5 in VeriGym's pinned external compatibility
module before another real repository rollout.
