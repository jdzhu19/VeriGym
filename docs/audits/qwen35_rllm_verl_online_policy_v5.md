# Qwen3.5 rLLM/verl Online Policy v5

Date: 2026-08-10

This audit records a minimal end-to-end online GRPO campaign and its frozen held-out evaluation.
It qualifies VeriGym's rLLM/verl interoperability and policy artifact lifecycle; it does not claim
RL convergence or a benchmark improvement.

## Online update

The campaign used the official rLLM `AgentTrainer`, asynchronous Ray/vLLM rollouts, and the verl
Ray GRPO trainer on four RTX 3090 GPUs. Two VerilogEval V2 tasks produced nine verifier-scored
rollouts, three resolved outcomes, two reward-variance groups, and zero infrastructure-invalid
outcomes. The single optimizer update had finite gradients, changed all 496 LoRA tensors, and had
a maximum absolute adapter delta of `2.001412e-6`.

The completed training report hash is
`e22d32ed2f82328e7c6d3c74fd3acbbd82bb403f533ea419887278d131aa00aa`. The campaign used rLLM
commit `09567646bfeacfa022c64aa8f97135d7f1e3f824` and verl commit
`bec9ef74768dd201881cd4e54cd0385e87caae27`.

## Registered policy

The compact export registered `qwen35-9b-rtl-policy-v5` as the exact successor of policy-v4:

- version hash: `c43c0572a246b7e0876aa7c2bec1944e45f244bc3e718b2ef767e27dc7877f28`
- artifact hash: `a5a254927c0ed5bc58efe722d6aaaf988620ed55022023849a62e8578054a4bf`
- adapter weight hash: `8a1b0fde473120a737cc29e55d2b05aaf66766e6b94a86fc9aa380e285a13257`

Only portable PEFT configuration, adapter weights, hashed reward provenance, and the training
report are required for evaluation. The 34 GB resumable trainer checkpoint remains outside Git.
The registered artifact contains no credentials, raw host paths, hidden assets, or reference
solutions.

## Frozen held-out comparison

Both policies were evaluated on the same sealed 12-task VerilogEval V2 split with two samples per
task. The split hash is
`c8319e374c684ed93167112adb34bf92d41f4cd5be764283e2318e349489a936`; the v4/v5 comparison report
hash is `4d4d52ca61c26e925b615509fa926c73c3f24552c1910f79392b1710d95a8cbf`.

| Policy | Compile | Resolved | Task pass@2 | Infrastructure invalid |
| --- | ---: | ---: | ---: | ---: |
| v4 | 16/24 (66.7%) | 11/24 (45.8%) | 7/12 (58.3%) | 0 |
| v5 | 16/24 (66.7%) | 10/24 (41.7%) | 7/12 (58.3%) | 0 |

The one-step update did not improve task-level held-out performance. The result supports the
platform claim that a verified online policy can be trained, compactly registered, reloaded, and
evaluated without crossing the hidden-verifier boundary. Larger training should wait for broader,
repo-level tasks and stronger reward/data design.
