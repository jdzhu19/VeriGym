# Qwen3.5 repository GRPO HPC run 25

Run 25 was a four-A30 developmental repository-GRPO attempt on the non-held-out CVA6 PR 2170
task. It was not a qualified optimizer step or benchmark score. All four repository sessions were
infrastructure valid and unresolved, received zero reward, and terminated with `ENV_DONE`. The
broker reported no infrastructure-invalid sessions, and the trainer received no Docker socket,
source root, hidden asset, reference solution, or credential values.

The run used implementation commit `6b188bbd2515ff68076a864fa1c07fb942b38e84`, native runtime
manifest SHA-256 `809731171a532d01f159848ac1a584a8e2855c900f44d8e8680cbf45c3fc5c21`,
task input SHA-256 `c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36`,
split SHA-256 `a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`,
and broker report file SHA-256
`4ce0946740d5213c7ad472f0a6cc8b00139eabe2e542a1aa07072330e9d6708d`. The
job-exclusive LSF allocation bound four A30 GPUs and 16 CPU slots. The official pinned PyTorch
container remained the verifier environment, and verification ran with networking disabled.

## Result

The four trajectories completed in 27 minutes 21 seconds. Two sessions stopped on repository
workspace policy after 59 and 35 requests; two emitted invalid repository actions after 39 and 58
requests. The trainer retained 191 rows in one stable GRPO group. The 0.48 vLLM envelope initialized
successfully, completed generation, and left substantially more actor-update headroom than run 24.

`update_actor` nevertheless failed during recurrent-attention forward. Each A30 simultaneously
held an approximately 11.29 GiB training worker and an 11.96 GiB resident vLLM worker. Only
229.50 MiB remained when `torch_chunk_gated_delta_rule` requested another 256 MiB:

```text
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 256.00 MiB.
```

No optimizer step, checkpoint, changed adapter, or completion report was produced. The broker
stopped cleanly, all GPU memory was released, and the reusable interactive LSF bash allocation
remained active.

## Evidence, finding, and execution path

### E-001

- Source: `native-grpo.log`, SHA-256
  `ebac78500e39f03ffb787a1ada8a6f77fd34e04acb93b8c11f76bc4eb9276824`.
- Observation: all four trajectories reached `ENV_DONE`, four zero-reward rollouts were logged,
  and the GRPO bridge retained 191 rows in one stable group.
- Reproduction: inspect the preserved run log for `Rollout completed` and
  `VeriGym GRPO group bridge active`.

### E-002

- Source: the same log and the broker report identified above.
- Observation: `actor_rollout_update_actor` failed in `torch_chunk_gated_delta_rule`; the
  exception attributes 11.96 GiB to the colocated vLLM process and reports 229.50 MiB free. The
  broker still records four valid sessions and zero infrastructure-invalid sessions.
- Reproduction: inspect the run log for `RayTaskError(OutOfMemoryError)` and parse
  `online-repository-broker-report.json` without loading trajectory contents.

### F-001

- Finding: the 0.48 resident-vLLM envelope is about 26.5 MiB short of the observed
  recurrent-attention allocation on a 23.5 GiB A30.
- Evidence: E-001 and E-002.
- Confidence: high for the observed batch; future trajectories can change the actor peak.
- Impact: rollout generation and the path into `update_actor` work, but the optimizer boundary
  remains unqualified.

### P-001

1. Four isolated repository rollouts complete (E-001).
2. The broker returns four infrastructure-valid, zero-reward sessions (E-001, E-002).
3. `update_actor` starts while the rollout workers remain resident (E-002, F-001).
4. Recurrent-attention forward requests 256 MiB with only 229.50 MiB free and the step aborts
   (E-002, F-001).

## Follow-up

The next fresh run reduces the rollout envelope from 0.48 to 0.47. This should return about another
240 MiB per A30 while remaining materially above the 0.4 setting that could not allocate one
KV-cache block. Acceptance still requires reward variance, one completed optimizer update, a
resumable checkpoint, and a changed registered adapter.
