# OpenHands v58 Ibex PR-54 provider canary result

Date: 2026-09-02

## Disposition

The single authorized provider episode for
`hwe-bench/repo-repair-v1/lowRISC__ibex__pr-54` ran after authorization PR #94
was merged as `1ff2bd0d4394e39146f675aeb6c989ede5f6533e` and post-merge main run
`33621194288` passed all eight required job classes. The episode failed closed.

PR-54 is consumed and permanently frozen for this campaign. No retry, model substitution,
budget increase, verifier reduction, or relabelling is authorized. This result is not an HWE-Bench
score and is not SFT-admitted evidence.

## Bound execution

- identity: `openhands-hwe-v58-ibex-pr54-v23-provider-canary-v1`
- agent version: `openhands-deepseek-v4-flash-hwe-v58-ibex-v23-canary-v1`
- model transport: `openai/deepseek-v4-flash`
- protocol: `auto_public_thought_atomic_recovery_v23`
- seed/sample: `498/14`
- provider retries / episode retries: `0/0`
- provider calls: `41`
- input/output/total provider tokens: `677436/25505/702941`
- first effective modification action: `31`
- progress checkpoint injected: `true`
- no-progress termination: `false`
- SDK stuck state: `not_stuck`
- wall time: `196.8594772570068` seconds

Provider-native hidden thinking remained disabled. The provider-value scan covered 83 files and
1,045,579 bytes, found zero matches for the two in-memory provider values, and did not persist or
hash those values.

## Failure classification

Infrastructure and security were valid. The command and verifier image locks remained exact, the
verifier used `network=none`, and the security scan passed. The failure therefore counts as the
first infrastructure-valid OpenHands behavior failure.

The model used the one allowed content-only recovery. The recovery request used `required`,
returned one valid `inspect_diff` call, and ordinary requests then returned to provider-default
`auto`. At provider call 41 the model emitted a second content-only response. The preserved
structural shape was `content_only` with one non-empty public text part, zero tool calls, and no
private reasoning fields. The adapter raised `V23ProtocolViolation` because the recovery budget
had already been consumed. A credential-free fake-provider regression now reproduces and fixes
this fail-closed behavior as an expected protocol outcome.

Independently, the candidate changed only `rtl/ibex_compressed_decoder.sv`, deleting four lines.
The patch policy and exact reapply checks passed, but the hidden verifier returned 0/1 tests and a
non-infrastructure `test_failed` result. Thus accepting the final text as an implicit `finish`
would neither be permitted by v23 nor make the candidate correct.

The SDK summary's generic `termination_authority=broker_typed_finish` label is not used to classify
this failed episode; the authoritative trace contains `ConversationErrorEvent`,
`V23ProtocolViolation`, and `termination_reason=policy_violation`. This summary-label limitation is
non-causal and does not authorize a second OpenHands provider canary.

## Six-plane and SFT disposition

- verifier: `false`
- protocol: `false`
- trajectory: `false`
- infrastructure: `true`
- security: `true`
- SFT admission: `false`
- exact-64K eligible: `false`
- trajectory collected: `false`

No decision targets, token receipt, protocol receipt, or trajectory receipt were admitted. The
failed decisions and recovery remain only in the private run context. Formal collection,
collection, training, and production-training readiness all remain `false`.

## Frozen evidence hashes

- canary report: `d811afa9c38f43aef0cb6a5e96546e51ff7ea526bb98f165b9fb97815ba84964`
- embedded report hash: `358460586e8babf669122be0528ec1128f2594e1c407d659010a4939ebe61e12`
- attempt: `092c4820bf0c1c7e401448e87f498079f002d9cff360a2b1badd24b2a771054f`
- scorecard: `11d6cc976fc352e59c6064e655aead3c95853983cf5af43aa7989ca5d9bc933a`
- OpenHands summary: `a79b0ef78dc699520a25cd3da0a407be49f7df860dcead58fc0fe0c2404d9781`
- provider accounting: `a3498f4fc823ffd9ccfe9f04bb10aec7c6459b5b81e1db18db53a939ebd3776b`
- v23 progress/observation receipt:
  `1c2d4125754efd350f54845354212ce919d5c623d720f8f3f24b689c4b08e3ee`
- candidate patch: `c05309dd444f3f910a981758a79d6fc89cafd774f4fd4018b4538297079c7e74`
- security scan: `e4ee3dd095cf4b62f409dc8c41359bf45478a3ce0aaedf6cd24cc85377e4ac37`

The raw trajectory, candidate workspace, Docker layers, provider values, and private observations
remain outside the repository under the experiment root.

## Next route

The structural replay reproduces correct fail-closed enforcement rather than a causal scaffold
defect, while the candidate also fails the benchmark verifier. The second OpenHands canary is
therefore not authorized. After this audit is merged and its post-merge main run is green, the
next eligible route is a distinct Harness-derived identity with credential-free regression,
zero-provider qualification, and a fresh task. Formal collection and SFT remain disabled.
