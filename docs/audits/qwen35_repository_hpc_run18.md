# Qwen3.5 Repository HPC Qualification: run18

Date: 2026-08-13

This audit records an opt-in initialization attempt on four job-exclusive A30 GPUs. The task was
the non-held-out CVA6 PR2170 development task. No model completion, repository action, verifier
run, optimizer step, or benchmark result was produced.

## Isolation and frozen inputs

The scheduler reported an effective GPU requirement of
`mode=shared:mps=no:j_exclusive=yes`. All four visible GPUs had zero allocated memory and no
compute processes at preflight. The native runtime manifest bound four GPUs, FSDP size four,
rollout group size four, and implementation commit
`4e4c7bd53ade951ae7480d8a0eee63d253594921`; its SHA-256 was
`349f103295f22efc8b770bb135dba15099c66deda22d883a5da1d437021f0b7c`.

The trusted broker used the official digest-locked verifier image with networking disabled. It
stopped normally with zero sessions, confirming that the failure preceded model interaction.

## Observed outcome

Both tensor-parallel rollout engines loaded all four model safetensor shards under the 0.4 vLLM
memory envelope. Initialization then failed with `No available memory for the cache blocks`.
There was no CUDA out-of-memory exception, actor log-probability computation, broker session,
checkpoint, or changed adapter.

The attempt is infrastructure-invalid for optimizer-step qualification. It does provide a bounded
configuration result: 0.4 is below the minimum viable resident-rollout envelope for the frozen
Qwen3.5 model and context on a 23.5 GiB A30.

## Corrective action

Restore the last envelope known to initialize and generate rollouts, 0.5, while retaining
scheduler-enforced job exclusivity. Use a fresh run identity. If actor memory still fails after
external GPU load has been excluded, diagnose actor/FSDP memory separately rather than reducing
vLLM below its initialization threshold.
