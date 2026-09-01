# OpenHands v43 provider canary failed closed

Date: 2026-09-01

Status: sealed ordinary model/trajectory failure; v43 and PR-2589 may not be retried.

## Authorization and execution boundary

PR #67 merged the v43 authorization as
`06cf8abce7387c140f3a47fab2ee4c31070e0f39`. Post-merge `main` Actions run
`33484618926` passed all eight required job classes. The frozen authorization hash was
`49d8f2097dbf05311c003c5f40e512c29290c869d7c86097e74aa1d2e7f40237`.

The documented command ran once from that exact clean tracked commit. The output and dedicated
broker paths did not exist before execution. Docker used `/data/docker`, with 385,452,113,920
bytes and 250,567,133 inodes available at the final audit check. The provider endpoint and
credential were loaded through their frozen `VERIGYM_...` environment names and checked only for
presence. Their values were not printed, persisted, or hashed.

The zero-provider preflight passed, in order:

1. control plane;
2. PR-2589 command image;
3. PR-2589 adapter-start bridge;
4. PR-3204 command image; and
5. PR-3204 adapter-start bridge.

The preflight receipt records zero provider episodes and calls.

## Result

The first scheduled training episode,
`hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2589`, made 38 provider calls in one episode.
It consumed 1,041,768 input tokens and 2,956 output tokens, for 1,044,724 total provider tokens.
The fixed cumulative one-million-token budget was therefore exhausted. The frozen scorecard
classified the outcome as `openhands_hwe_v22_provider_token_budget`, an ordinary model failure
rather than an infrastructure or security failure.

The model's first response did not call a tool. The frozen v22 stop hook denied termination and
performed its one permitted same-session format recovery. This was not a provider-request or
whole-episode retry. The recovered and subsequent responses produced 36 validated tool calls with
zero failed tool calls, including 35 file reads. The agent made zero file writes, patches, or
public-test invocations. The candidate stayed unchanged, the patch was empty, and the single
hidden regression failed as an ordinary test failure. The resulting six planes were:

| Admission plane | PR-2589 result |
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
  `/data/jzhu484/Agent/experiments/openhands-hwe-v43-provider-canary-v1`;
- evidence tree hash:
  `d50e4e7958f9804a959d16540da3ea60dd9a8f777bda734ba5ea9733d081e900`;
- report hash:
  `4f4c57e373f983c45197ec87e23da8ab007d3295a504aae39fb82a007ea43425`;
- report and progress file SHA-256:
  `5889c76cb517e8d6efb17a461630ea1f33ceda3cb56ff9f3adcfbd747550ca89`;
- attempt run hash:
  `3a8776b26ce855aba5b869e8f19885decf08dfb3bd28aedb7083e304bde3023a`;
- attempt file SHA-256:
  `356412081913b385f52ad389109a1d6a7d798b3da0f5d6addf7528737f80cbc9`;
- agent-version hash:
  `9f123c134437a8f45dd14dc4782762ecc3a082e71de3d5748950721156bd466d`;
- agent-version file SHA-256:
  `23651d757600cd5e14aacb6b0f2233b2dbfe84dc470853934a1272dddd2c756f`;
- contract receipt hash:
  `e8061fe74576459447de0b49e0802f66e40c466870d7f4d79278ec48a1d1f839`;
- contract-receipt file SHA-256:
  `607720652cd2d37814b71f64114735f36daa7512e953a3ac2dc4b3b56ec94180`;
- zero-call preflight receipt hash:
  `c52702fef55be4e307b6d6ad3105f4d1e4cd0724f9791b3382d8f2efc83eaec2`;
- zero-call preflight file SHA-256:
  `698fcbdd0859884b96336255542be8eca8e75916398c21162041ee01032c2c8e`;
- security-scan hash:
  `c32cb71cdcbb2d347bd31c649aa331fb5dea9c0724409d9419e7ec67b45feaf8`;
  and
- security-scan file SHA-256:
  `a3028127063c797ed147adbddefa29ca069fdde93206f5a8d29ddc05452517cd`.

The v2 security scan passed with zero hard-secret findings and zero scanner errors. The runner's
separate in-memory exact-value scan covered 6,965 files and 141,056,057 bytes and found zero
endpoint or credential hits. A post-run independent exact-value scan covered the complete 6,967
file, 141,070,078-byte tree and also found zero hits. Neither scan persisted or hashed provider
values. The sealed tree contains zero symlinks. No v43 container remains and the dedicated broker
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

V43, PR-2589, and the observed attempt are immutable and may not be retried, reconstructed,
relabelled, or admitted as training data. PR-2589 now has disposition
`replace_after_failed_canary`; any future formal training schedule must replace it. PR-3204 remains
unstarted and may run only under a new, separately reviewed successor authorization after this
failure audit merges and post-merge `main` again passes all eight required job classes.
