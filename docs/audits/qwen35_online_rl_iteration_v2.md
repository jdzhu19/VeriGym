# Qwen3.5 Weight-Bound Online RL Iteration

Date: 2026-08-09

This audit records a second real rollout/reward/update iteration. It demonstrates auditable online
semantics across staged processes; it is not a convergence result or qualification of the full
rLLM Ray/vLLM service stack.

## Policy lineage

The registered chain is Base `a3c662e0` -> verified-SFT policy-v0 `227a55ab` -> GRPO policy-v1
`540cc011` -> GRPO policy-v2 `71104d61`. Each manifest binds the base-model snapshot, adapter
artifact, parent version, training data, reward data, trainer report, and source/framework commits.
Rollout records bind policy-v1 and rLLM `weight_version=1`; the update report declares output
`weight_version=2`.

## Fresh rollout and reward

Three bounded sampling attempts were retained:

| Attempt | Seed | Solution limit | Rewards | Disposition |
| --- | ---: | ---: | --- | --- |
| 01 | 684 | 224 | `[0, 0, 0, 0]` | Rejected: no reward variance |
| 02 | 484 | 224 | `[0, 0, 0, 0]` | Rejected: no reward variance |
| 03 | 484 | 512 | `[1, 0, 1, 1]` | Selected for GRPO |

All 12 isolated VerilogEval evaluations were infrastructure-valid. Inspection showed that the
224-token candidates were truncated; increasing the public generation limit produced a complete,
variable group without modifying verifier outcomes.

## Four-GPU update

One 4-GPU FSDP LoRA optimizer step used official rLLM episode types and verl GRPO advantage and
clipped-policy-loss functions. The maximum trainable-parameter change was `5.00055e-5`. All 496
adapter tensors changed relative to policy-v1, no output tensor was non-finite, and the registered
policy-v2 adapter reloaded and generated eight tokens in an independent inference check.

The policy-v2 adapter artifact hash is
`a6abb98334ee094b05ba6a106ca1841f61ebc3078e659adfc4fc97b94fc605a9`; the sealed campaign
manifest hash is `603d0108c8236d8296e17d2effaf4db940d4a5c90829bada05cb600e9e4d36eb`.
Raw checkpoints, trajectories, verifier runs, and rewards remain outside Git under the configured
experiment root. The manifest uses relative storage keys and contains no credentials or host paths.
