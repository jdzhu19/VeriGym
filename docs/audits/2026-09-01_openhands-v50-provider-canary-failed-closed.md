# OpenHands v50 provider canary failed closed

Date: 2026-09-01

Status: sealed ordinary model/trajectory failure; v50 and PR-2916 may not be retried.

## Authorization and execution boundary

PR #81 merged the v50 authorization as
`90bb1833cf55921a0631d1000ea57f45b736da02`. Post-merge `main` Actions run
`33511326430` passed all eight required job classes. The frozen authorization hash was
`4937d9fd7e5b46d78cbe746817fff704a768382b5480c6b698171b7726a2760d`.

The documented command ran once from that exact clean tracked commit. The output path did not
exist and the dedicated broker path was absent or empty before execution. Docker used
`/data/docker`, with 329,279,135,744 bytes and 250,502,039 inodes available at the final audit
check. The provider endpoint and credential were loaded through their frozen `VERIGYM_...`
environment names and checked only for presence. Their values were not printed, persisted, or
hashed.

The zero-provider preflight passed, in order:

1. control plane;
2. PR-2916 command image;
3. PR-2916 adapter-start bridge;
4. PR-3204 command image; and
5. PR-3204 adapter-start bridge.

The preflight receipt records zero provider episodes and calls.

## Result

The first scheduled training episode,
`hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2916`, made 40 provider calls in one episode.
It consumed 1,029,716 input tokens and 3,071 output tokens, for 1,032,787 total provider tokens.
The fixed cumulative one-million-token budget was therefore exhausted. The frozen scorecard
classified the outcome as `openhands_hwe_v22_provider_token_budget`, an ordinary model failure
rather than an infrastructure or security failure.

The model's first response did not call a tool. The frozen v22 stop hook denied termination and
performed its one permitted same-session format recovery. This was not a provider-request or
whole-episode retry. The recovered and subsequent responses produced 38 validated tool calls with
zero failed tool calls: 33 file reads and five command executions. The agent made zero file
writes, patches, or public-test invocations. The candidate stayed unchanged, the patch was empty,
and the single hidden regression failed as an ordinary test failure. The resulting six planes
were:

| Admission plane | PR-2916 result |
| --- | --- |
| Benchmark verifier | failed |
| Required-tool protocol | failed |
| Trajectory eligibility | failed |
| Infrastructure | valid |
| Security | valid |
| SFT admission | failed |

No protocol, trajectory, decision, or exact-token receipt was admitted. The attempt has
`exact_64k_eligible=false` and `truncation_applied=false`.

The runner stopped immediately. PR-3204 did not start. Final state remains
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`. No fallback identity was created, no held-out task was loaded,
and no benchmark score is claimed.

## Frozen evidence and security accounting

- evidence root:
  `/data/jzhu484/Agent/experiments/openhands-hwe-v50-provider-canary-v1`;
- evidence tree hash:
  `ac49a3f79ea7b1e025280a822057f8c7f370a6cc328e7f7bec8be057adace418`;
- report hash:
  `11a6cc828708e6a2fa48214e5c241436e8ba55c599e210c43f78846b4e32075f`;
- report and progress file SHA-256:
  `c0be796debb9b09068440694f8cac01c80777dfb0c1f6021aeed6a255eff6eb6`;
- attempt run hash:
  `a95c81161ccbc8ac8e3d8ce3f52393d524c05e5876e980df6461d93b0a90d42c`;
- attempt file SHA-256:
  `3e7311e4f00514f2246b9a27f51a98f61a53ac4e9c54b69e242f2264e3a640db`;
- scorecard content hash:
  `9d630fb264b6909b08836be16e911536916282dab8b48e1a5bdc497bdbecc848`;
- scorecard file SHA-256:
  `094fafb0bf263461dfa99d43a1737f4c73f0b5bb20f4cf515525042bcc5de95c`;
- agent-version hash:
  `03454ada966363a72cd23bf386a85506d930e5f883996f742268e4cc5adb57b6`;
- agent-version file SHA-256:
  `2364fc8bf721d3e3718e934d6989429e0c8e2fd4360f45f7f0e876d2a1632c53`;
- contract receipt hash:
  `3c83e89b71cb62e55d7108b4034fd7732187906ceb01ad6fb72c2c618ce866e5`;
- contract-receipt file SHA-256:
  `1f9bf31a88c25e7b74793c60e8ff50c41f8ff12c9cda8db45c79f358256e62ab`;
- zero-call preflight receipt hash:
  `7865f7dceeafdaa6d6c14956594fcb253fdd6bf2261d7cd52e304baffb351716`;
- zero-call preflight file SHA-256:
  `6790646e09886fde9f1ae64c9a499b8ee3cc1035c7d257e7422a80ddf114090e`;
- security-scan hash:
  `ece64a9baf19bef3e7826f63e1e20e4400380aa0132be74c6e500662500f2171`;
  and
- security-scan file SHA-256:
  `e062513dbdf1976537d40cdfa461e530fbd82c765b76d8de5db7d48150018ec5`.

The v2 security scan passed with zero hard-secret findings and zero scanner errors. The runner's
in-memory exact-value scan found zero endpoint or credential hits. A post-run independent
exact-value scan covered the complete 7,532-file, 157,173,188-byte tree and also found zero hits.
Neither scan persisted or hashed provider values. The sealed tree contains zero symlinks. No v50
command or verifier container remains and the dedicated broker directory is empty.

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

V50, PR-2916, and the observed attempt are immutable and may not be retried, reconstructed,
relabelled, or admitted as training data. PR-2916 now has disposition
`replace_after_failed_canary`; any future formal training schedule must replace it. PR-3204
remains unstarted and may run only under a new, separately reviewed successor authorization after
this failure audit merges and post-merge `main` again passes all eight required job classes.
