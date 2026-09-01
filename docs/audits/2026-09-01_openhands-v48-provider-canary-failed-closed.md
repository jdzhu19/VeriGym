# OpenHands v48 provider canary failed closed

Date: 2026-09-01

Status: sealed ordinary model/trajectory failure; v48 and PR-2802 may not be retried.

## Authorization and execution boundary

PR #77 merged the v48 authorization as
`904359e988afad43d07028daed3d17ccfb47ed8c`. Post-merge `main` Actions run
`33502988103` passed all eight required job classes. The frozen authorization hash was
`f55864631727942b0e7336c7df4537324ae9db2a28cda07ad18782005698e672`.

The documented command ran once from that exact clean tracked commit. The output and dedicated
broker paths did not exist before execution. Docker used `/data/docker`, with 330,116,067,328
bytes and 250,521,039 inodes available at the final audit check. The provider endpoint and
credential were loaded through their frozen `VERIGYM_...` environment names and checked only for
presence. Their values were not printed, persisted, or hashed.

The zero-provider preflight passed, in order:

1. control plane;
2. PR-2802 command image;
3. PR-2802 adapter-start bridge;
4. PR-3204 command image; and
5. PR-3204 adapter-start bridge.

The preflight receipt records zero provider episodes and calls.

## Result

The first scheduled training episode,
`hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2802`, made 43 provider calls in one episode.
It consumed 1,029,775 input tokens and 3,231 output tokens, for 1,033,006 total provider tokens.
The fixed cumulative one-million-token budget was therefore exhausted. The frozen scorecard
classified the outcome as `openhands_hwe_v22_provider_token_budget`, an ordinary model failure
rather than an infrastructure or security failure.

The model's first response did not call a tool. The frozen v22 stop hook denied termination and
performed its one permitted same-session format recovery. This was not a provider-request or
whole-episode retry. The recovered and subsequent responses produced 41 validated tool calls with
zero failed tool calls: 35 file reads and six command executions. The agent made zero file writes,
patches, or public-test invocations. The candidate stayed unchanged, the patch was empty, and the
single hidden regression failed as an ordinary test failure. The resulting six planes were:

| Admission plane | PR-2802 result |
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
  `/data/jzhu484/Agent/experiments/openhands-hwe-v48-provider-canary-v1`;
- evidence tree hash:
  `c0f72852b070f8a2ca2046b3fa3d4a32ba342de4d2edaa92327f9184113053c6`;
- report hash:
  `4ba2cbeaa8c79464dd63a68749e7f4b313251b596ff4a799193ab8cc348a4b2d`;
- report and progress file SHA-256:
  `a49f69fc59d86f480abf162d93810abde5898535fd90996e5934fe562a549d0f`;
- attempt run hash:
  `6d1366b2c014185485eb0ec6e84ab17e4955607a13951748aeeb10d199f8ded1`;
- attempt file SHA-256:
  `e32a62298b5d9d075f2745905d57a70a2c1649ffa08216f896387c34edbe0777`;
- agent-version hash:
  `c762f569bc8c66c257ea5581e098630928905f7f0198830e0479cd4163fddf8f`;
- agent-version file SHA-256:
  `f5897efc12583a5cb9dad68ae9eaa56bbddb2873624e856f58f03d724202ad3d`;
- contract receipt hash:
  `429e973db001bb028b9ff09bc2c64298fea52793f9e4c652a30fdeba31d5c4bc`;
- contract-receipt file SHA-256:
  `c76472a77531ef93527fb16cda8dbefc789ae9f22b826270adccf3d2654b68cd`;
- zero-call preflight receipt hash:
  `7f6e85f0538f81c17cb0e85ac692dbf81bc27c17a46b1699c345df5c8a3dd2db`;
- zero-call preflight file SHA-256:
  `2638dc153a8e54b8b0c97e8a87eedbc1c6db246454f982e3ee853f82e34f855e`;
- security-scan hash:
  `9deaebbe98f8b177801ef72a71a3131e0843804dab87e32fad4a5f1c96659913`;
  and
- security-scan file SHA-256:
  `a0800cc96fb70d8a7f2e638c396f4a4597fa35db243bbda44ba92eb6f64af2bc`.

The v2 security scan passed with zero hard-secret findings and zero scanner errors. The runner's
separate in-memory exact-value scan covered 7,482 files and 155,490,651 bytes and found zero
endpoint or credential hits. A post-run independent exact-value scan covered the complete 7,484
file, 155,505,007-byte tree and also found zero hits. Neither scan persisted or hashed provider
values. The sealed tree contains zero symlinks. No v48 container remains and the dedicated broker
directory is empty.

The evidence remains external and is not committed. Raw model content, raw tool arguments,
private reasoning, provider values, full trajectories, run trees, Docker layers, and benchmark
assets are excluded from this audit.

## Stop decision and successor constraints

This is a valid ordinary canary outcome under the frozen one-million-token policy, not an
implementation or infrastructure defect. The provider returned usable typed tool calls and the
broker executed them without errors; the model exhausted the budget through read-only analysis
without producing a candidate change. The failure cannot be repaired in place by increasing the
budget, changing the prompt, replaying the task, or reinterpreting the empty candidate.
Accordingly, no upstream workaround is used to authorize a retry.

V48, PR-2802, and the observed attempt are immutable and may not be retried, reconstructed,
relabelled, or admitted as training data. PR-2802 now has disposition
`replace_after_failed_canary`; any future formal training schedule must replace it. PR-3204
remains unstarted and may run only under a new, separately reviewed successor authorization after
this failure audit merges and post-merge `main` again passes all eight required job classes.
