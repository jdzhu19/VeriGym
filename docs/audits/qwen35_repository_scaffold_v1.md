# Qwen3.5 Repository Scaffold v1

Date: 2026-08-12

This audit records implementation and zero-model qualification of the repo-level online-training
path. It is not a model result, an RL convergence result, or a benchmark score. The Qwen3.5 GRPO
stage was deliberately not started because four uncontended RTX 3090 GPUs were unavailable.

## Architecture and isolation

rLLM owns the multi-turn `Workflow` and retains prompt IDs, completion IDs, and log probabilities
for every trainable step. veRL remains the backend used by rLLM's `AgentTrainer`. Model actions use
the provider-neutral `repository_action.v2` envelope and the frozen
`repository_action_state_machine_v2`; public tests are required only when the task declares them.

A host-side broker owns the prepared repository, Docker runtime, and hidden verifier. The training
container receives the public task record, bounded observations, and terminal sparse reward. The
source root, Docker socket, hidden assets, reference patch, and credential values are not exported
to it. The repository workflow sets no per-action token override; the opt-in four-GPU smoke config
declares a 32K model resource envelope and delegates turn count to the task's frozen budget.

## CVA6 source and split qualification

The non-held-out development task is CVA6 PR2170. It was freshly prepared as source-lock v2 after
making profile exclusions safely idempotent for generated directories that are absent in older
repository snapshots. Existing symlinks, escaping paths, and non-directory nodes remain rejected.

- official image digest:
  `sha256:70bf6c4e7a9205dc133631b4d5a3a76069e29a467aa5122f1214d8b76ae2b350`
- local image ID:
  `sha256:050095a666ae15e4f2f78f62bce6af38f3779005e789a9020fc4c08c6d53ba87`
- repository hash: `a64181ea041cc96d9da8c1b4135669eb88b136083061853a7e8cdc2a0d40b2ff`
- repository profile hash:
  `a448f3605bb035201a3c7b06e20d8ba4a40d9171cb37bff140f795e98f775034`
- license: `SHL-0.51`, with the profile-bound `LICENSE` inventory
- training split hash: `712bd8e26173eb96de55318e81b3ae1f37065df86f4a599c9d901849fd4f007f`
- task hash: `02e98821e1004822375d5a2158c9586fbb06950bb107cab0e9826ea18bd5e59b`

The official zero-model smoke produced base FAIL, reference PASS, no infrastructure error, and
zero model processes.

## Real broker preflight

A model-free client exercised four actions against a live VeriGym CVA6 workspace: list visible
files, apply a harmless new probe file, inspect the diff, and finish. The task exposes no public
test, so the v2 state machine correctly permitted the final transition after diff inspection. The
official hidden verifier rejected the irrelevant candidate as expected while infrastructure
remained valid.

- public task manifest hash:
  `16a719813902e8cd7277d3bae02653511aa2259858af86b06d7cf030b81bb76d`
- broker report hash: `575c41f65f4ad1daff603bb9b4260a20b89ceea2ef9a2ca51bcd7ba2b22a655b`
- sessions: 1; resolved: 0; infrastructure-invalid: 0
- model calls: 0
- reference patch exposed: no

## Verification

- Ruff and format checks passed.
- Core mypy, training-reference mypy, and HWE plugin mypy passed.
- Core tests: 783 passed, 1 explicit real-Codex opt-in skipped, 51 deselected.
- Training-reference tests: 42 passed.
- HWE plugin tests: 26 passed.
- Core, HWE plugin, and training-reference wheel/sdist builds and package-content audits passed.
- A fake rollout using the installed rLLM `ModelOutput`, `Step`, and workflow types completed three
  trainable turns with aligned token IDs and log probabilities.

Implementation commits are `9e7670a` and `c23b35a`. The next gate is one opt-in run of
`configs/training/qwen35_repository_rllm_verl_online_smoke_v1.json` after four suitable GPUs are
simultaneously available. A new output policy must be registered from that run; it must not reuse
the identity of an earlier RTL-only or held-out campaign.
