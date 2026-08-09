# Qwen3.5 Multi-Task Online RL Campaign

Date: 2026-08-09

This audit records two consecutive weight-bound, multi-task rollout/reward/update iterations. It
demonstrates staged online RL semantics and cross-suite training compatibility, not convergence or
qualification of the full rLLM Ray/vLLM service stack.

## Tasks and data boundary

Both iterations used one RTLLM group (`up_down_counter_iverilog_training`) and one VerilogEval V2
group (`Prob079_fsm3onehot`). The model received only public task text and candidate skeletons.
Each candidate was scored by an isolated Icarus 12 verifier; hidden testbenches and reference
solutions remained evaluator-owned.

The fail-closed group merger required the same registered policy hash and weight version across all
records, zero infrastructure-invalid outcomes, unique group IDs, and reward variance within every
group. It exported no credentials or host paths.

## Iterations

| Iteration | Policy update | RTLLM rewards | VerilogEval rewards | Optimizer steps |
| --- | --- | --- | --- | ---: |
| 002 | v2 `71104d61` -> v3 `3cfc23e0` | `[0,1,0,1]` | `[1,1,1,0]` | 2 |
| 003 | v3 `3cfc23e0` -> v4 `085d2ead` | `[0,1,0,1]` | `[1,1,0,1]` | 2 |

Both updates ran with four-GPU FSDP. Maximum trainable-parameter changes were `1.00068e-4` and
`1.00073e-4`. After each update, all 496 LoRA tensors differed from the parent, no tensor was
non-finite, and the registered adapter reloaded for independent local inference.

Rejected groups were retained. RTLLM `counter_12` produced four infrastructure-invalid outcomes
because its commercial VCS verifier was incompatible with the isolated Icarus training runtime;
these were never converted to zero rewards. Two additional RTLLM groups were rejected for having
uniform `[1,1,1,1]` and `[0,0,0,0]` rewards.

The policy-v4 adapter artifact hash is
`508c0d3b2ffc5096e31253122dcdfe9eae55c8b02370585dfab1e4630b1c24a7`. The sealed campaign
manifest hash is `94d05886d460866b80a0d218e0bc4bb6bc91a667296d73399fa3e9abaef85c8c`.
Raw checkpoints, trajectories, rewards, and verifier runs remain outside Git under the configured
experiment root. This two-task campaign is interoperability evidence, not a benchmark score.
