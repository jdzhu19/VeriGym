# OpenHands v38 provider canary failed closed

Date: 2026-09-01

Status: sealed ordinary protocol failure; v38 and PR-3226 may not be retried.

## Outcome

The authorized v38 command ran once from merged `main` commit
`e2583dc1997700387f3c74f526fb6b2e6f6a84b5`, after main Actions run `33464020217`
passed all eight required job classes. The NumPy repair was successful: the host-side runner-first
tokenizer import passed with NumPy 2.2.6 and Pillow 12.1.1, and the two-task zero-provider Docker
preflight passed all five stages.

The first scheduled training episode,
`hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3226`, made one provider call. Its response had
classification `tool_calls` with two tool calls and no non-empty visible text. Protocol v20
requires exactly one tool call per response, so it rejected the complete response before broker
dispatch. The broker consequently recorded zero decisions, zero tool calls, zero commands, zero
file reads, zero writes, zero patches, and zero finish calls. The candidate remained byte-for-byte
at its source identity and the hidden verifier failed the unchanged candidate as an ordinary test
failure.

The resulting six planes were:

- verifier: false
- protocol: false
- trajectory: false
- infrastructure: true
- security: true
- SFT admission: false

The runner stopped immediately. The PR-3204 validation episode did not run. Final state remains
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`. No benchmark score is claimed.

## Frozen accounting and evidence

- authorization merge: `e2583dc1997700387f3c74f526fb6b2e6f6a84b5`
- authorization hash: `b5f18acb9165a759c13da78fd1773b4422e8a3bb080115c54b7a16a535e2f6e4`
- evidence tree: `e5e9d518b7f0bf24a0b32947b5ea42efb3d15ac96f44943918bcafeaf171f890`
- report hash: `a90698e672c38c341735c130e1691e13370d44aa75a5b8bf298ec38e1dfb1e6a`
- report/progress file SHA-256:
  `ab0ac6a6a5594a40dbcf722ba8d7f5a790789e7864ee7e4e3b4e41841367921b`
- attempt file SHA-256:
  `1b54b5f58e8317a5709acfdcd08f91da16ce9f5214caa9c8937a516205d0f754`
- agent-version hash: `05387b92124088c35763440e54e3a0513bf649aec4ad4233371a90e27771ac07`
- agent-version file SHA-256:
  `3707fa5fee7c062c5be4e0ae5fb8352849aee221275d4bdb1eca78934e085cec`
- contract receipt hash: `380ef13bb6ca3282afb4f502ca572f5147758f489b5e5cb1000dc56a7716cb5e`
- contract receipt file SHA-256:
  `de837d309b1096832578d2c0e7df62b702da6e1e3cde6a9ceabb7efd4358de6c`
- zero-call preflight receipt hash:
  `3117d560a71cdb146d4ae44144f0cc01f0bf778f045c1fbce1bd2f291dd25fd6`
- zero-call preflight file SHA-256:
  `04224c4fd4e72eab4961525b6e6d5f86a63fcf2336e01b5fd2a1e7437141dc30`
- run hash: `9774e8273fedf7bd3b39c055bd73a56787408181b5523230baa9b937cf67c732`
- security-scan hash: `99bc36f5098e1e7f2dcf812cd1aaa5698b00e6d7748b34e938f0f8f933b64b05`
- security-scan file SHA-256:
  `6e02973cb1c961fca48efb85d7fd8599c19f8735d359cd9b56767ce7999ecf84`
- provider accounting: one episode, one call, 2,411 input tokens, 69 output tokens
- provider-value scan: passed across 7,381 files and 169,158,311 bytes; zero hits
- security scan: passed; zero hard-secret findings and zero scanner errors
- raw repository-observation records: zero
- output symlinks: zero

The evidence remains external under
`/data/jzhu484/Agent/experiments/openhands-hwe-v38-provider-canary-v1`. It is not committed.
Provider URL/key values, raw model content, and raw tool arguments were neither printed nor
persisted nor hashed.

## Upstream boundary and repair constraints

The response is valid at the provider transport layer but invalid under the frozen local v20
policy. DeepSeek documents that `tool_choice=required` means the model calls **one or more** tools,
and its current Chat Completions request schema does not document a `parallel_tool_calls` switch:
<https://api-docs.deepseek.com/api/create-chat-completion/>. It also requires callers to validate
generated tool arguments:
<https://api-docs.deepseek.com/guides/tool_calls/>.

OpenHands SDK v1.42.1 iterates over every returned tool call, constructs multiple action events,
and its asynchronous path may schedule those actions concurrently:
<https://github.com/OpenHands/software-agent-sdk/blob/v1.42.1/openhands-sdk/openhands/sdk/agent/response_dispatch.py>.
Therefore, simply deleting the exact-one check would change ordering, mutation, trajectory, and
loss-mask semantics and is not an admissible hot fix.

Any future repair must use a new protocol and agent/runtime identity, preserve v38 unchanged, and
use a task that has never started a provider episode. A safe candidate design is a single bounded,
same-session, shape-only recovery: reject all sibling calls atomically before dispatch, expose no
raw arguments in artifacts, request exactly one replacement call, loss-mask the rejected response,
and fail closed if the replacement is not exactly one valid allowlisted call. An alternative that
executes sibling calls would require an explicit serialized scheduler, per-tool mutation classes,
ordered observation commits, and new trajectory/token-accounting proofs. Neither design is
authorized by this result audit.

PR-3226 is permanently consumed by this canary and may not be retried or counted as a fresh formal
collection task. PR-3204 was not started, but it also remains unauthorized until a separately
reviewed successor contract is merged and its main checks pass.
