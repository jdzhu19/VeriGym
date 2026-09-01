# OpenHands v41 provider canary failed closed

Date: 2026-09-01

Status: sealed ordinary model/trajectory failure; v41 and PR-2549 may not be retried.

## Authorization and execution boundary

PR #63 merged the v41 authorization as
`b8c6651ef78bdaed37a63c7d0cd9b3f8f7b71cc7`. Post-merge `main` Actions run
`33477420038` passed all eight required job classes. The frozen authorization hash was
`d29ee68cf1cd70d55c7bbdbdc13701aec7463b01a357ad56faf1fbf0e986811b`.

The documented command ran once from that exact clean tracked commit. The output path did not
exist before execution. Docker used `/data/docker`, with 401,562,173,440 bytes and 250,611,701
inodes available. The provider endpoint and credential were loaded through their frozen
`VERIGYM_...` environment names and checked only for presence. Their values were not printed,
persisted, or hashed.

The zero-provider preflight passed, in order:

1. control plane;
2. PR-2549 command image;
3. PR-2549 adapter-start bridge;
4. PR-3204 command image; and
5. PR-3204 adapter-start bridge.

The preflight receipt records zero provider episodes and calls.

## Result

The first scheduled training episode,
`hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549`, made 42 provider calls in one episode.
It consumed 1,023,946 input tokens and 3,240 output tokens, for 1,027,186 total provider tokens.
The fixed cumulative one-million-token budget was therefore exhausted. The frozen scorecard
classified the outcome as `openhands_hwe_v22_provider_token_budget`, an ordinary model failure
rather than an infrastructure or security failure.

The broker recorded 40 decision steps and 40 read-only tool calls. It recorded zero commands,
file writes, patches, or public-test invocations. The candidate stayed unchanged, the patch was
empty, and the single hidden regression failed as an ordinary test failure. The resulting six
planes were:

| Admission plane | PR-2549 result |
| --- | --- |
| Benchmark verifier | failed |
| Required-tool protocol | failed |
| Trajectory eligibility | failed |
| Infrastructure | valid |
| Security | valid |
| SFT admission | failed |

No protocol, trajectory, decision, or exact-token receipt was admitted. The attempt has zero
decision records, `exact_64k_eligible=false`, `decision_only_loss_mask=false`, and
`truncation_applied=false`.

The runner stopped immediately. PR-3204 did not start. Final state remains
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`. No fallback identity was created, no held-out task was loaded,
and no benchmark score is claimed.

## Frozen evidence and security accounting

- evidence root:
  `/data/jzhu484/Agent/experiments/openhands-hwe-v41-provider-canary-v1`;
- evidence tree hash:
  `b105784e55d7024e1f17074d1779e652060780721c67bded3bd27707a4e195f7`;
- report hash:
  `dabd954df613b624279da8d1a0600c024ecd344c759afdbb638a36aefb896922`;
- report and progress file SHA-256:
  `a4a774177b1a78d34057ae2d5223957a2d65456a601b9dee024d2f2964473a5c`;
- attempt run hash:
  `24b643931cdb45cb6680bad8e37ca2685a00ef6be0744d2cad947bc92c2a65a7`;
- attempt file SHA-256:
  `d4640183529f47e9ffd7559b75d71c39639539de088a6e76fb5d6a781a8ee6d5`;
- agent-version hash:
  `c7791deb031c3ff0623b70faf111e0287cc3cc1458a3353853f6bb3452bf6963`;
- agent-version file SHA-256:
  `b2fefa5b060df24f1242c6e686dd4768071a692f138a18fa693571cde4daaeec`;
- contract receipt hash:
  `3019b501e9d8cede16624ccbf8f31080066fef2ef4bb0eff48638384c90ecdfa`;
- contract-receipt file SHA-256:
  `f0f34d933169539a0be3368dd30cb2e9788db26cee2226a214f1f6bf442b714a`;
- zero-call preflight receipt hash:
  `f9d98d51c29cd6f8ff761afbb1c2af10c4c0515addcb0d61595597fc921fb4eb`;
- zero-call preflight file SHA-256:
  `e93455543a454eff69907c2719052e3fecda292b9a079be6bd1d59fea85b70c4`;
- security-scan hash:
  `2658641431987039afbd4798e8e1d91d233a548bb2932915f0a0fe40c9313bbe`;
  and
- security-scan file SHA-256:
  `9f17ba60ec4d9f85c1152686ce5cf87a5f431fffb95427282026dd2138af0065`.

The v2 security scan passed with zero hard-secret findings and zero scanner errors. The separate
in-memory exact-value scan covered 6,922 files and 147,173,360 bytes, found zero endpoint or
credential hits, and persisted or hashed neither provider value. The sealed tree contains 6,924
files and zero symlinks. No v41 container remains and the dedicated broker directory is empty.

The evidence remains external and is not committed. Raw model content, raw tool arguments,
private reasoning, provider values, full trajectories, run trees, Docker layers, and benchmark
assets are excluded from this audit.

## Stop decision and successor constraints

This is a valid ordinary canary outcome under the frozen one-million-token policy, not an
implementation or infrastructure defect. The failure cannot be repaired in place by increasing
the budget, changing the prompt, replaying the task, or reinterpreting the empty candidate.
Accordingly, no upstream workaround is used to authorize a retry.

V41, PR-2549, and the observed attempt are immutable and may not be retried, reconstructed,
relabelled, or admitted as training data. PR-2549 now has disposition
`replace_after_failed_canary`; any future formal training schedule must replace it. PR-3204 remains
unstarted and may run only under a new, separately reviewed successor authorization after this
failure audit merges and post-merge `main` again passes all eight required job classes.
