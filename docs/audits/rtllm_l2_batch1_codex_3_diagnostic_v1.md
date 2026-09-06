# RTLLM L2 batch-one Codex three-task diagnostic v1

Date: 2026-09-01

Status: complete diagnostic. All three frozen model-process slots reached immutable terminal
states with one identity observation and zero retries. Two candidates resolved. Automatic and
independent finalization both passed offline replay, exact leakage scanning, and redaction audit.
This is not a native RTLLM score or a benchmark claim.

## Frozen scope

- Campaign ID: `rtllm-l2-batch1-codex-gpt54-xhigh-3task-diagnostic-v1`.
- Suite variant: `v2-agent-eval-functional-l2-batch1-v1`.
- Ordered tasks: `adder_pipe_64bit`, `LFSR`, `serial2parallel`.
- Requested model and reasoning: `gpt-5.4` / `xhigh`.
- Agent identity: `codex-cli-agenteval-gpt54-xhigh-functional-v3`.
- Agent version hash:
  `467d2ba0847fab60f39ee7d85a7073abc832e5c35fa299d8e09cb5761c230b3c`.
- Codex CLI identity: `codex-cli 0.147.0`.
- Prompt hash: `14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9`.
- Tool-policy fingerprint:
  `6a0cf3b44d0bdb1b6ba2a016607db639e857af8979389ece947c8bea55415ef4`.
- Seed and sample count: seed 0, one process per task.
- Execution: serial, one process per slot, automatic retry count and authorization both zero.
- PPA: disabled; no candidate or final synthesis execution.
- Runtime image:
  `sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
- Launcher SHA-256:
  `7b07fd8f5957fe0859bbccfc942a3a27b3e04f2e719be4d45c469448d31e279f`.

The three unique run-config hashes were
`d218745915501553557808b0af10437303d7285d83ef85f68cc8e4f2d5121961`,
`ff27f6dd43142aa26e30a0ac68e99ff84c24895b3ed3535cf14c9cccb2abc032`, and
`9c4c5ec46c48f4348db566a161e500e3ea2ffd6aea6624a020af3d9ca611e52e`.

## Qualification and authorization

The committed launcher first repeated zero-model qualification in the formal campaign process.
For each task, the reference passed both its independent public functional smoke and original
hidden verifier; stuck-zero, reset, protocol/latency, and task-specific functional controls were
rejected by both. The frozen plan therefore contains three reference public passes, three
reference hidden passes, 12 public known-bad rejections, and 12 hidden known-bad rejections.

Only after qualification and freeze completed did the launcher authorize the three model
processes. All three started, produced exactly one valid functional-v3 identity observation, and
ended without timeout, policy failure, or infrastructure failure. No slot was repeated.

## Results

| Task | Public sequence | Typed finish | Hidden execution | Terminal result |
| --- | --- | ---: | --- | --- |
| `adder_pipe_64bit` | fail -> patch -> recheck pass (`1/1/1`) | yes | rejected once | verifier rejection |
| `LFSR` | fail -> patch -> recheck pass (`1/1/1`) | yes | passed once | resolved |
| `serial2parallel` | fail -> patch -> recheck pass (`1/1/1`) | yes | passed once | resolved |

All three initial candidates failed the visible functional smoke, were patched after that visible
failure, and passed one public recheck for the final candidate. This is the intended multi-turn
repair signal that the compile-only L1 pilot could not provide. Every final candidate then used
one typed `finish` and exactly one hidden-verifier execution; no hidden placeholder was needed.

The adder result also preserves the intended public/hidden separation: passing the independent
public smoke did not imply hidden correctness. It is reported as one verifier rejection, not an
infrastructure failure and not a reason to rerun the slot. The diagnostic resolved count is 2/3,
with 3/3 observed fail -> repair -> pass sequences and 0/3 first-public-pass sequences.

Every run records zero PPA evaluations and no final PPA object. Neither Yosys/OpenSTA, VCS, nor
Design Compiler was invoked.

## Replay, usage, and sanitized evidence

The automatic finalization reported `infrastructure_complete=true` and
`diagnostic_complete=true`. A separate `--finalize-existing` invocation made no model call and
reproduced the same terminal summary from persisted run evidence. Replay, exact leakage scan, and
redaction audit all passed.

Provider usage was complete for all three episodes:

| Task | Input | Cached input | Output | Total |
| --- | ---: | ---: | ---: | ---: |
| `adder_pipe_64bit` | 113,840 | 93,696 | 5,317 | 119,157 |
| `LFSR` | 147,031 | 118,272 | 3,796 | 150,827 |
| `serial2parallel` | 197,561 | 167,424 | 12,755 | 210,316 |
| Total | 458,432 | 379,392 | 21,868 | 480,300 |

No provider cost was recorded.

| Evidence | SHA-256 |
| --- | --- |
| Frozen plan | `28a02c263ce4468ac535f8553586deb783197a6a9a4e15db53b5c48d0fca2730` |
| Summary | `1817b26e300f023ce92d3f8f47f6fcb70ca3e007219e9f4edf8858647d09a811` |
| Authorization ledger | `1e24155e9f42e039c8e69928485660c3999766b8764fd3c56a50ec2f3ca0c75f` |
| Offline replay | `90c5ac3c5f12e77a72316c9d834411a2e39202c9890bd8829802b4310f83a881` |
| Leakage scan | `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7` |
| Redaction audit | `4841444093e052169a91c84565e1ebd7510dbf284adaa04441e34339dd58cd88` |

Experiment outputs remain outside the repository. No source checkout, reference RTL, hidden
testbench, generated candidate, raw trajectory, model reasoning, Docker layer, credential, proxy
value, or commercial asset is included here.

## Interpretation

This bounded diagnostic validates the L1 -> L2 promotion strategy: an independently qualified
functional smoke can expose a real repair loop while the typed final hidden gate retains a
strictly stronger verdict. The three observations are not a statistical estimate and must not be
combined with the earlier L1 pilot as a leaderboard result.

The next corpus-expansion batch should use the same no-PPA L2 contract and qualification bar. PPA
remains a later, separately identified L3/L4 effort after functional coverage has scaled and is
not authorized by this result.
