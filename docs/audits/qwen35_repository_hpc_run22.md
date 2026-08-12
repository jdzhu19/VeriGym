# Qwen3.5 repository GRPO HPC run 22

Run 22 was a four-A30 developmental repository-GRPO attempt on CVA6 PR 2170. It was not a
qualified optimizer step or benchmark score. All four repository sessions were infrastructure
valid and unresolved. Two ended on workspace policy, one emitted an invalid model action, and one
exhausted the turn budget. None changed the repository or reached a passing verifier result, so
the group had no reward variance.

The run used implementation commit `829e33b073024a7dcc349ce26f62706962e00bf2`, native runtime
manifest hash `caad5f12a3dd77aa81b647cfc398ffdb751525d84c059965455327d8d3e53f2e`,
task input SHA-256 `c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36`,
split SHA-256 `a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`,
and broker report hash `3e2a8575f19d4f231ff50c55e74772d7c31374647d191d470fc728e72f2c7e26`.
The job-exclusive LSF allocation bound four A30 GPUs and 16 CPU slots. The official pinned
PyTorch container remained the verifier environment; verification ran with networking disabled.

## Result

All four trajectories completed in 30 minutes 49 seconds and the trainer entered actor
log-probability computation. The intended FSDP2 wrap-boundary compatibility module loaded, but
the trainer again failed at the first chunked vocabulary projection:

```text
RuntimeError: aten.mm.default got mixed torch.Tensor and DTensor
```

This was a training integration failure after valid rollouts, not verifier rejection. No
optimizer step, checkpoint, or completion report was produced. The broker stopped cleanly and
reported four valid sessions, zero infrastructure-invalid sessions, and zero resolved sessions.
The reusable interactive LSF bash allocation remained active.

## Root cause and follow-up

A real Qwen3.5-plus-PEFT meta-model probe showed that the causal checkpoint exposes
`config.model_type == "qwen3_5_text"`. The compatibility selector recognized only the multimodal
wrapper identifiers `qwen3_5` and `qwen3_5_moe`, so it remained nominally active while still
selecting `base_model.model.lm_head` as an independent FSDP2 unit. The fused forward then read its
sharded DTensor directly without invoking the head module's pre-forward all-gather hook.

Cover the causal `qwen3_5_text` and `qwen3_5_moe_text` identifiers and retain regression coverage
for the exact causal model-type shape. A two-rank CPU-offload probe confirmed that leaving the
head in the root FSDP2 unit completes the bounded fused forward and backward and returns the
gradient to CPU DTensor shards.
