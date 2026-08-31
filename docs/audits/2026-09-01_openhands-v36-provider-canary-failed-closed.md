# OpenHands v36 provider canary failed closed

## Authorization and execution boundary

PR #50 merged the v36 authorization as
`3347fbfb8f5284151e62e127b84bc323401cdc74`. All eight protection classes passed on the pull
request and again on post-merge `main` Actions run `33430192286`. The frozen authorization hash
was `71d6ed7f4d33d5dd71125c53415e8baff3c72458657d89547ac2635eeda87592`.

The documented command was executed once from that exact clean tracked commit. The output path did
not exist before execution. Docker used `/data/docker`; 416 GiB and more than 250 million inodes
were available. The provider endpoint and credential were checked only for presence. Their values
were not printed, persisted or hashed.

## Result

The canary stopped after PR-2330 and did not execute PR-3204. The final status is
`canary_failed_closed`, with failure reason
`training-pr2330-s489-v36:six_plane_gate_failed`. This was an ordinary model/protocol rejection,
not an infrastructure or security failure.

| Admission plane | PR-2330 result |
| --- | --- |
| Benchmark verifier | failed |
| Required-tool protocol | failed |
| Trajectory eligibility | failed |
| Infrastructure | valid |
| Security | valid |
| SFT admission | failed |

The provider produced one successful response using 2,370 input tokens and 69 output tokens. It
made no required tool call. OpenHands emitted one `ConversationErrorEvent` and terminated with
`policy_violation`. The broker recorded zero tool calls, decisions, commands, file operations,
mutations, diff inspections, finish calls and rejected calls. No candidate change was made; the
patch is empty and has SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

Consequently there is no protocol receipt, trajectory receipt, decision receipt or exact-token
receipt. The attempt has zero decision records, `exact_64k_eligible=false`,
`decision_only_loss_mask=false`, and `truncation_applied=false`. The empty candidate failed the
single hidden regression. No benchmark score is claimed.

## Preflight, accounting and security evidence

The zero-provider preflight passed, in order:

1. control plane;
2. PR-2330 command image;
3. PR-2330 adapter-start bridge;
4. PR-3204 command image; and
5. PR-3204 adapter-start bridge.

The preflight receipt records zero provider episodes and calls. The canary then recorded exactly
one provider episode and one provider call, with zero retries. The PR-2330 command image remained
`sha256:3ba2d622fbec6891484c8529892be39db33e02127ec9aaec80381b7d87e64540`, using
`episode_container_exec_v1` and `network=none`.

The per-attempt v2 security scan passed with zero hard-secret findings and zero scanner errors. A
separate in-memory exact-value scan covered all 6,422 evidence files and 136,571,939 bytes; it found
zero endpoint or credential value hits and persisted or hashed neither value. No v36 container
remained, and the dedicated broker directory was empty after cleanup.

## Immutable evidence identities

- evidence root:
  `/data/jzhu484/Agent/experiments/openhands-hwe-v36-provider-canary-v1`;
- evidence tree hash:
  `ccf9094dfe373587454346f5b52b4a8f7d3ade828b4f15b524c63d14a6d26f4d`;
- report hash: `debf637e7697c921c24898a027a907d045514c0f7f65d131ad7e3471998124d0`;
- report and progress file SHA-256:
  `9abe705efe3ddfd24c51f9261febe5349a8649037771036063b803c8523e55e8`;
- agent version hash:
  `0f346efa5627469a7d71c595459e97b061225385d005d124816b91c8bc37ed77`;
- agent-version file SHA-256:
  `43d212129f9c99c234ffe81b267a000274e299e9bba241ef77fe684cf8e8ed03`;
- contract receipt hash:
  `07d88c51512cc57f55d857627700d3fd8fbe0e87668eb355a4bbb45068365bd7`;
- contract-receipt file SHA-256:
  `70bd0f9929a3cae3acd52cd12c9cb5602232773e46ea746e13f9eab9c71a2644`;
- preflight receipt hash:
  `fb784dbcd80a369833634edc4ccf8b875d5393984c40eedc1260e2cc689c5e68`;
- preflight file SHA-256:
  `f5fae39b09cc20ca58f2b67a3e59e190738a1eb7a8ac7be6ad6390502a6b887b`;
- attempt run hash:
  `0bc967184d262f08aed00bb5ca5d9c74aa9d0e691deb09113c4a3eebcc4d461c`;
- attempt file SHA-256:
  `fa0bc526bae7d7734bec3adca53ff57d8b1f67b3fc6a7072a25e85ca9575634f`;
- security scan hash:
  `91b6ff730b0d7ec5dec6e504e1f93a39af4326c87d6eb109adc08a90866c3277`;
  and
- security-scan file SHA-256:
  `69dc1937e9088e624b608527c177eeff35d57247d692c7d5fdf3782f22471651`.

## Stop decision

v36 is sealed and must not be retried, reconstructed, relabelled or admitted as training data.
`formal_collection_allowed=false`, `formal_collection_started=false`, `training_started=false`,
and `production_training_ready=false` remain final for this identity. Because the fixed first
canary task received an ordinary provider/protocol failure, the planned v37 materialization and
v38 readiness authorization do not proceed. Any changed canary task or policy would require a new,
separately reviewed authorization; this audit does not create one.
