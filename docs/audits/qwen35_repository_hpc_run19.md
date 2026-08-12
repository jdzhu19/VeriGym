# Qwen3.5 Repository HPC Qualification: run19

Date: 2026-08-13

This audit records an opt-in, single-step development attempt on four job-exclusive A30 GPUs. The
task was the non-held-out CVA6 PR2170 development task. This is not a benchmark score or evidence
of RL convergence.

## Isolation and frozen inputs

The LSF job requested four GPUs and sixteen CPU slots on the GPU compute node. Its effective GPU
requirement was `mode=shared:mps=no:j_exclusive=yes`; job exclusivity excluded unrelated LSF jobs
while preserving the multiple CUDA processes required by FSDP and tensor-parallel vLLM.

The run used implementation commit `800946226b56aef8418e78fdab8453e704042466`, FSDP size four,
rollout group size four, tensor parallelism two, and the 0.5 vLLM memory envelope. The native
runtime manifest SHA-256 was
`3af8b4ca01fc3e0160b8ff53a2cd11da33cceb45545656ad3d7a6beaebbf300d`.
The online task and split file SHA-256 values were, respectively,
`c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36` and
`a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`.

The trusted repository broker and Docker verifier remained CPU-only on the VM. The broker
container used the pinned image with network disabled and did not export the source root, Docker
socket, hidden assets, reference patch, or credentials to the training process.

## Observed outcome

Both tensor-parallel rollout engines initialized and all four sessions exercised the strict
multi-turn `repository_action.v2` scaffold. The broker report recorded four infrastructure-valid
sessions, zero infrastructure-invalid sessions, and zero resolved sessions; its report SHA-256
field was `1c95dc1cb4b67e33d3b79608aeaa19b6e8728e430ab1347f57b3c0fc8e044c05`.
The sessions terminated as malformed JSON, extra prose, invalid arguments, and a repository policy
violation. These are model or policy outcomes, not verifier or infrastructure failures.

After rollout collection, actor log-probability computation failed during an FSDP2 all-gather.
Each affected GPU had approximately 0.98 GiB free while the next unshard required 1.89 GiB. The
actor process used 10.13 GiB and the resident vLLM process used 12.40 GiB. No unrelated GPU process
was present, so job exclusivity isolated this as an actor/rollout memory-envelope failure. No
optimizer step, checkpoint, completion report, or changed adapter was produced.

## Corrective action

Keep the 0.5 vLLM envelope because 0.4 cannot allocate a KV-cache block. Enable the supported
FSDP2 actor CPU-offload policy so parameter shards need not remain resident beside vLLM during
actor log-probability computation. Retain job exclusivity and use a fresh run identity. Acceptance
still requires reward variance, one completed optimizer update, a resumable checkpoint, and a
changed registered adapter.
