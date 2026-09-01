# OpenHands v37 provider canary stopped before output

Date: 2026-09-01

Status: infrastructure-invalid, zero provider episodes, identity permanently sealed.

## Result

The authorized v37 command was invoked once after authorization PR 53 and all eight post-merge
`main` checks passed at commit `2398e5e928b584d06fa777fdabda511bc7ec0f3e`.

It stopped while importing the exact tokenizer dependency closure, before the authorized output
directory was created and before `_service()`, the per-task loop, an OpenHands agent, or a provider
client could start. Therefore:

- provider episodes: 0
- provider calls: 0
- model processes: 0
- task attempts: 0
- PR-3226 started: false
- PR-3204 started: false
- authorized output directory created: false
- formal collection or training started: false

The sanitized local stop receipt is stored outside the repository at
`/data/jzhu484/Agent/experiments/openhands-hwe-v37-provider-canary-pre-output-stop-v1`.
Its identities are:

- receipt hash: `ef98bbdda2329fa0746c8c24c5fd51e614007a73347371654d0e86ebcc48377e`
- receipt file SHA-256: `2107843637320035bfa748e8d16e1a896495b7c1551223ebd9f939a037466521`
- evidence tree hash: `796b2f56316c4b0b2fb0392b3ea8b218bc2f84030e9a79c30c0e46227d241ee9`

No concrete provider URL, key, traceback text, model response, prompt, task content, or raw exception
was persisted in the receipt.

## Root cause

The newly resolved environment selected NumPy 2.5.2 and built its native extension locally. In
the runner's import order, the process had already loaded `/usr/lib64/libstdc++.so.6`, whose newest
advertised ABI was `CXXABI_1.3.7`; the generated NumPy extension required `CXXABI_1.3.9`.
Transformers consequently failed to import, and the existing tokenizer loader raised a sanitized
`ConfigurationError`.

This is an environment-resolution failure, not a benchmark, protocol, security, verifier, or model
failure. NumPy's official troubleshooting guide identifies C-extension import failures as an
installation/environment issue and recommends verifying the exact Python and NumPy versions:
<https://numpy.org/doc/stable/user/troubleshooting-importerror.html>.

The earlier validated OpenHands environments use NumPy 2.2.6, which imports successfully against
the host library in the same process closure. NumPy 2.2.6 supports Python 3.10 through 3.13:
<https://numpy.org/doc/2.3/release/2.2.6-notes.html>.

The resolver selected the newest transitive version because it was unconstrained. uv documents
that its default strategy selects the latest compatible dependency and that existing locked or
constrained versions should be supplied explicitly for reproducibility:
<https://docs.astral.sh/uv/concepts/resolution/>.

## Disposition and successor requirements

v37 must not be rerun. The authorized output path remains absent, and both scheduled task episodes
remain fresh because neither entered the task loop.

Any successor must use a new v38 runtime and authorization identity, bind this stop receipt and its
merged audit, and retain the v20 protocol, task order, no-retry policy, image locks, and all six
result planes. It must additionally freeze NumPy 2.2.6 and Pillow 12.1.1, verify all direct and
newly frozen transitive versions, and successfully import Transformers and load the exact Qwen
tokenizer before creating output or enabling a provider episode.

The existing tiktoken 0.7.0 identity remains unchanged. LiteLLM 1.93.0's current dependency
metadata asks for a newer tiktoken, but the frozen v36 environment demonstrated the exact 0.7.0
runtime path and a separate zero-provider compatibility probe passed. Changing tiktoken would
constitute another model/runtime identity change and is not folded into this infrastructure repair.

At this stop:

- `formal_collection_allowed=false`
- `formal_collection_started=false`
- `collection_started=false`
- `training_started=false`
- `production_training_ready=false`
