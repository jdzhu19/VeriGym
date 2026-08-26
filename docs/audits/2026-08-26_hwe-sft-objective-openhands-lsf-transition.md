# HWE exact SFT objective and ephemeral LSF transition

Date: 2026-08-26

This change closes three development gaps identified after the 64K SFT qualification: the
decision-level weighting was implicit, the verifier-passed OpenHands decision format did not have
an explicit rLLM/veRL dispatcher, and GPU work relied on a retained interactive LSF shell. It does
not start another training run or claim a production recipe.

## LSF allocation cleanup

The retained allocation was inspected before cancellation:

- job: `466876`
- owner: `connect.jzhu484`
- queue / command: `gpu` / interactive `bash`
- host / resources: `gpu03`, seven job-exclusive NVIDIA GPUs and 28 CPU slots
- submitted: 2026-08-22 22:50

Only job `466876` was sent `bkill`. LSF subsequently reported it as `EXIT` with finish time
2026-08-26 00:22. A final account query reported zero active jobs. No replacement job was
submitted, so this transition used zero GPU seconds.

Future GPU work uses `scripts/submit_ephemeral_lsf_gpu_job.py`. The wrapper submits the actual
Python or executable payload directly, rejects shell payloads and interactive flags, requests one
host with job-exclusive GPUs, bounds wall time, and writes a receipt beside scheduler logs. The
allocation exits automatically when the payload returns. Frozen v1 reports and authorizations that
refer to job `466876` remain historical evidence and are not rewritten or reused as future recipes.

## Exact OpenHands loader

`VeriGymOpenHandsDecisionSft64kTrainer` and
`VeriGymOpenHandsDecisionSft64kBackend` now register the OpenHands SDK decision format at the same
lossless parquet boundary used by the DeepSeek qualification. The loader binds the source dataset,
source record, trajectory, decision index, full messages, exact SDK-visible tool schemas, token
receipt, and explicit objective. Any source hash, row order, tool schema, template token, loss mask,
eligibility, truncation, or objective drift fails closed.

The existing qualified OpenHands dataset was replayed locally with the frozen Qwen tokenizer:

- dataset hash: `e1331ed287cedc76141d9f882992c4a159b76c759371170d259aa6d15492f511`
- rows: 20
- maximum tokens: 13,107
- supervised target tokens: 3,348
- exact receipt mismatches: 0
- parquet round-trip rows / semantic mismatches: 20 / 0
- scratch parquet SHA-256: `968b7a0ef842121164e60ee24e195e0aca9e3a9aaf41998a3070890bc367c8f4`

The dispatcher is loader-qualification-only. It cannot call training until a formal A/B recipe is
frozen.

## Objective correction and A/B boundary

The existing decision path is now named
`decision_balanced_target_token_mean_batch1_v1`. With global batch one, each row is one update and
veRL normalizes that update over the row's supervised target tokens. It is not described as
full-trajectory maximum likelihood.

The matched A/B draft defines:

- trajectory arm: one row per verifier-passed trajectory, supervising every complete assistant
  tool decision and masking system, user, tool, and malformed assistant turns;
- decision arm: exact final-decision rows with a deterministic equal-trajectory epoch sampler,
  resampling eligible decisions within each trajectory.

Across the two DeepSeek trajectories and one OpenHands trajectory, the decision sampler produces
186 epoch slots: 62 slots for each trajectory. The trajectory masking implementation was run on
the three actual longest-prefix records with the frozen Qwen template:

| trajectory tokens | supervised tokens | complete decisions |
|---:|---:|---:|
| 13,430 | 2,911 | 21 |
| 13,107 | 3,348 | 20 |
| 50,117 | 12,410 | 62 |

All three remain below 65,536 tokens. The Qwen template renders an intermediate tool decision
differently from a final decision (notably around empty thinking delimiters), so the all-assistant
mask derives message boundaries from the actual full render rather than concatenating per-decision
receipts. Boundary and receipt drift are fail-closed.

The A/B data gate remains unsatisfied: only one OpenHands trajectory is currently qualified. The
draft requires at least 50 distinct training tasks and 50 verifier-passed OpenHands trajectories,
then equal base checkpoint, supervised-token budget, and held-out tasks. Therefore
`production_training_ready=false` and no optimizer, checkpoint, or adapter action occurred in this
change.
