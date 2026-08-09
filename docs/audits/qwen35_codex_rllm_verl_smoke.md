# Qwen3.5 Codex Distillation and GRPO Smoke

Date: 2026-08-09

This audit records a bounded end-to-end training-boundary experiment. It is evidence of platform
interoperability, not a benchmark score or a convergence claim.

## Strong sampling and SFT

Codex CLI sampled the pinned RTLLM up/down-counter task with requested model
`gpt-5.6-luna` and reasoning effort `max`. The isolated Icarus 12 verifier resolved the candidate.
The fail-closed SFT exporter produced one public-only chat example with manifest hash
`7307754943c3226624086a88b3b763346c1e33d4e3f09d1efe7411dc53ef56d1`.

Qwen3.5-9B then completed one real four-GPU FSDP LoRA SFT optimizer step. Loss was `0.06198246`;
all 496 adapter tensors were nonzero, and the saved adapter reloaded for inference.

## rLLM trajectory and verl GRPO

The SFT adapter generated four two-turn rLLM trajectories for VerilogEval V2 task
`Prob100_fsm3comb`. Four isolated VeriGym runs yielded sparse rewards `[0, 1, 0, 0]` with no
infrastructure-invalid outcomes. verl computed group advantages approximately
`[-0.5, 1.5, -0.5, -0.5]`.

A four-GPU FSDP job completed one clipped-policy LoRA update. The maximum trainable-parameter
change was `5.0006e-5`; all 496 tensors differed from the parent adapter. The resulting adapter
hash is `5fe8a28ab841b28ea3ff5d829f39ebb0046c875abb354f03d5100a9d5d3187f0` and it reloaded to
generate valid text.

Pinned framework commits were rLLM `1d1109a655e291b3001d8526d7c9ecc5b9328226` and verl
`4a2cba76f7f605d2b9f56e640faaeaa71c2c7f71`. The run used official rLLM trajectory types and verl
GRPO math, but did not qualify the full Ray/vLLM distributed rollout backend.
