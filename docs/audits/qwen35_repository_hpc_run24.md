# Qwen3.5 repository GRPO HPC run 24

Run 24 was a four-A30 developmental repository-GRPO attempt on the non-held-out CVA6 PR 2170
task. It was not a qualified optimizer step or benchmark score. All four repository sessions were
infrastructure valid and unresolved, received zero reward, and terminated with `ENV_DONE`. The
broker reported no infrastructure-invalid sessions, and the trainer received no Docker socket,
source root, hidden asset, reference solution, or credential values.

The run used implementation commit `7b97a26f248410c167b70dc7230b898854075da6`, native runtime
manifest SHA-256 `a68eda67f2961afbda19d549fab080494fe7afad5395e4704d05622bdf4eedfb`,
task input SHA-256 `c13f2de18f7b48c69e0370a1c28286b409f82d5fe72e0ffd4b3622a063b86c36`,
split SHA-256 `a11ac5fbebaecce5eb41c320f39a2e07641cbffdd3fb63703a4c8bf4e85f9a58`,
and broker report file SHA-256
`32ba1020e7e62684b3b4122ee18537706d2b91b38b8c18acd1de00edc74b67f9`. The
job-exclusive LSF allocation bound four A30 GPUs and 16 CPU slots. The official pinned PyTorch
container remained the verifier environment, and verification ran with networking disabled.

## Result

The four trajectories completed in 36 minutes 29 seconds. Three sessions stopped on repository
workspace policy after 15, 41, and 21 turns. The remaining session exhausted the frozen 128-turn
budget. The trainer retained 205 rows in one stable GRPO group. Independent FSDP2 wrapping and
bounded invocation of `lm_head` eliminated run 23's backbone-forward memory failure: actor
log-probability computation completed, and the trainer entered `update_actor` for epoch 0, step 1.

Actor forward then failed after approximately 18 minutes 43 seconds of sustained four-GPU
computation. Each A30 simultaneously held an approximately 11 GiB training worker and a 12.40 GiB
resident vLLM worker. Only 35.50--111.50 MiB remained when Qwen3.5 recurrent attention requested
another 128 or 256 MiB:

```text
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 256.00 MiB.
```

No optimizer step, checkpoint, changed adapter, or completion report was produced. The broker
stopped cleanly, and the reusable interactive LSF bash allocation remained active.

## Evidence, finding, and execution path

### E-001

- Source: `native-grpo.log`, SHA-256
  `bd0d95429987aa4b6a59640f9fb2efdbc8ad7b3cce9416dc210470f1853b180c`.
- Observation: all four trajectories reached 100%, four zero-reward rollouts were logged, and the
  GRPO bridge retained 205 rows in one stable group.
- Reproduction: inspect the preserved run log for `Generating trajectories`, `Rollout completed`,
  and `VeriGym GRPO group bridge active`.

### E-002

- Source: the same log and the broker report identified above.
- Observation: `actor_rollout_update_actor` failed in `torch_chunk_gated_delta_rule`; the exception
  attributes approximately 12.40 GiB to the colocated vLLM process and leaves less memory than the
  requested activation allocation. The broker still records four valid sessions and zero
  infrastructure-invalid sessions.
- Reproduction: inspect the run log for `RayTaskError(OutOfMemoryError)` and parse
  `online-repository-broker-report.json` without loading trajectory contents.

### F-001

- Finding: the 0.5 resident-vLLM envelope leaves insufficient actor-forward activation headroom
  on a 23.5 GiB A30.
- Evidence: E-001 and E-002.
- Confidence: high.
- Impact: the full rollout and actor log-probability paths work, but the optimizer boundary remains
  unqualified.

### P-001

1. Four isolated repository rollouts complete (E-001).
2. The fused, independently sharded output head completes actor log-probability computation
   (E-001).
3. `update_actor` starts while the rollout workers remain resident (E-002, F-001).
4. Recurrent-attention forward requests 128--256 MiB beyond available device memory and the step
   aborts (E-002, F-001).

## Follow-up

The node's legacy CUDA driver previously rejected vLLM's CuMem sleep allocator, so sleep mode
remains disabled. A 0.4 rollout envelope is also known to fail before generation because it cannot
allocate one KV-cache block. The next fresh run reduces the envelope conservatively from 0.5 to
0.48, which should return about 480 MiB per A30 while remaining materially above the failed 0.4
setting. Acceptance still requires reward variance, one completed optimizer update, a resumable
checkpoint, and a changed registered adapter.
