# RTLLM harder multi-turn Codex 32-run diagnostic v1

Date: 2026-09-01

Status: all 32 frozen model-process slots reached an immutable terminal state with one identity
observation and zero retries. Twenty-two candidates resolved. Offline replay, exact leakage
scanning, and redaction auditing passed. The campaign nevertheless records
`diagnostic_complete=false` because two model processes ended without a typed `finish`, but the
then-current orchestrator still executed their hidden verifier nodes. Those episodes were not
rerun. This is diagnostic evidence only, not a native RTLLM score or benchmark claim.

## Frozen scope

The derived variant `v2-agent-eval-functional-harder-v1` contains four qualified RTLLM 2.0 tasks:

- `Arithmetic/Divider/radix2_div`;
- `Arithmetic/Multiplier/multi_pipe_8bit`;
- `Memory/LIFO/LIFObuffer`;
- `Memory/FIFO/asyn_fifo`.

The external checkout was frozen at commit
`41b26896e33b536940116a975626455eed3de65e`. Its manifest inventories 50 task directories and 207
files. The task-tree inventory hash is
`ca6c86e761b14074e738b7ae90a6bc5f4ff02bcc7f2f7f51bb5c67fd3856814c`; the complete file
inventory hash is `5877ebc9ab8dbf6aada22a981cd9e087423ea95ce15e527e9cac47122733edda`.
Only the four tasks above were made runnable by this variant.

The metadata refactor preserves the two pre-existing functional-v2 task identities. Six prior
frozen campaign manifests per task independently record task hashes
`23efb4a898070f8489c459d292374df0aebf9cbf5a3a05b60a704e7c26fe3715` for `counter_12` and
`f7ed592251502b77b55c3055dba1e1cc8bba987faec75a095233e156853e01c4` for
`up_down_counter`; opt-in source-identity regression tests now freeze both values.

Each task had one repository-relative candidate RTL entry, an independently authored public
functional smoke, an Icarus 12 hidden profile, a task-bound VCS/MCP hidden profile, and separate
open and DC/MCP PPA profiles. The asynchronous FIFO used `wclk=10 ns` and `rclk=14 ns` as
asynchronous clock groups, with `wclk` frozen as the power-base clock. Its three auxiliary data
files remained verifier-only.

The ordered matrix used seed 0, serial execution, one sample for each
identity/task/backend cell, and no retry authorization:

| Cell | Requested model / reasoning | Frozen agent version hash | Slots |
| --- | --- | --- | ---: |
| mini-low | `gpt-5.4-mini` / `low` | `d41741d8f4cee7e4cf53e3c99f3aad9512a9ea0266c4be89522fc1d5e94d85ef` | 8 |
| mini-medium | `gpt-5.4-mini` / `medium` | `2bc08440bad001e83a238aceaa9da4fa647e04723d9f85124609e0f232f43f81` | 8 |
| mini-high | `gpt-5.4-mini` / `high` | `cad433bd3e90d5623d889229971069993321ab765f677946bf1bb698c9405239` | 8 |
| full-xhigh | `gpt-5.4` / `xhigh` | `467d2ba0847fab60f39ee7d85a7073abc832e5c35fa299d8e09cb5761c230b3c` | 8 |

All cells used functional-v3 prompt hash
`14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9` and tool-policy
fingerprint `6a0cf3b44d0bdb1b6ba2a016607db639e857af8979389ece947c8bea55415ef4`.
The recorded Codex CLI identity was `codex-cli 0.147.0`. The open runtime image resolved to
`sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1` and ran with
network disabled, a non-root user, read-only root, dropped capabilities, and bounded resources.

## Zero-model qualification

Qualification completed before model authorization and made zero model calls:

| Path | Checks | Result |
| --- | ---: | --- |
| Public functional reference plus four known-bad categories per task | 20 | passed |
| Icarus 12 hidden reference plus four known-bad categories per task | 20 | passed |
| VCS/MCP hidden reference plus four known-bad categories per task | 20 | passed |
| Yosys/OpenSTA and DC/MCP reference PPA, one per task/backend | 8 | passed |

The known-bad categories covered stuck-zero behavior, reset errors, protocol/latency errors, and a
task-specific functional error. VCS and DC profiles were task-bound and content-addressed;
commercial binaries, licenses, reports, endpoints, and private paths are not included in this
audit.

## Results

The authorization ledger contains exactly 32 unique terminal records: 22 `completed`, seven
`verifier_rejection`, and three `contained_model_failure`. Open and commercial paths each resolved
11/16. All 32 processes started and recorded exactly one valid identity observation; automatic
retry count was zero. No episode timed out or recorded a policy or infrastructure failure.

| Group | Resolved | First public pass | Fail -> repair -> pass | No typed finish |
| --- | ---: | ---: | ---: | ---: |
| mini-low | 6/8 | 1 | 7 | 0 |
| mini-medium | 6/8 | 1 | 7 | 0 |
| mini-high | 4/8 | 3 | 3 | 2 |
| full-xhigh | 6/8 | 6 | 2 | 0 |
| Total | 22/32 | 11 | 19 | 2 |

Task totals were 7/8 for `radix2_div`, 7/8 for `multi_pipe_8bit`, 8/8 for `LIFObuffer`, and 0/8
for `asyn_fifo`. The FIFO result is descriptive for this fixed diagnostic sample; it is not a
leaderboard score or a general capability estimate.

The following table records each public-test/repair sequence and final PPA disposition. The three
numbers are public failures, repair patches after a visible failure, and public rechecks after a
repair. `Final PPA=yes` means correctness passed and the final-candidate PPA result was eligible;
all 30 typed-finish candidates had first produced a legal candidate-only PPA observation.

| # | Identity | Task | Backend | Public sequence `fail/patch/recheck` | Finish | Terminal | Hidden | Final PPA |
| -: | --- | --- | --- | --- | ---: | --- | --- | ---: |
| 1 | mini-low | `radix2_div` | open | fail-repair-pass `3/3/3` | yes | completed | passed | yes |
| 2 | mini-low | `radix2_div` | commercial | first-pass `0/0/0` | yes | completed | passed | yes |
| 3 | mini-low | `multi_pipe_8bit` | open | fail-repair-pass `6/6/6` | yes | completed | passed | yes |
| 4 | mini-low | `multi_pipe_8bit` | commercial | fail-repair-pass `4/4/4` | yes | completed | passed | yes |
| 5 | mini-low | `LIFObuffer` | open | fail-repair-pass `1/1/1` | yes | completed | passed | yes |
| 6 | mini-low | `LIFObuffer` | commercial | fail-repair-pass `1/1/1` | yes | completed | passed | yes |
| 7 | mini-low | `asyn_fifo` | open | fail-repair-pass `1/1/1` | yes | verifier rejection | failed | no |
| 8 | mini-low | `asyn_fifo` | commercial | fail-repair-pass `2/2/2` | yes | contained model failure | failed | no |
| 9 | mini-medium | `radix2_div` | open | fail-repair-pass `4/4/4` | yes | completed | passed | yes |
| 10 | mini-medium | `radix2_div` | commercial | fail-repair-pass `3/3/3` | yes | completed | passed | yes |
| 11 | mini-medium | `multi_pipe_8bit` | open | fail-repair-pass `3/3/3` | yes | completed | passed | yes |
| 12 | mini-medium | `multi_pipe_8bit` | commercial | first-pass `0/0/0` | yes | completed | passed | yes |
| 13 | mini-medium | `LIFObuffer` | open | fail-repair-pass `1/1/1` | yes | completed | passed | yes |
| 14 | mini-medium | `LIFObuffer` | commercial | fail-repair-pass `1/1/1` | yes | completed | passed | yes |
| 15 | mini-medium | `asyn_fifo` | open | fail-repair-pass `1/1/1` | yes | verifier rejection | failed | no |
| 16 | mini-medium | `asyn_fifo` | commercial | fail-repair-pass `1/1/1` | yes | verifier rejection | failed | no |
| 17 | mini-high | `radix2_div` | open | unverified finish `0/0/0` | no | contained model failure | invalid execution | no |
| 18 | mini-high | `radix2_div` | commercial | first-pass `0/0/0` | yes | completed | passed | yes |
| 19 | mini-high | `multi_pipe_8bit` | open | fail-repair-pass `2/2/2` | yes | completed | passed | yes |
| 20 | mini-high | `multi_pipe_8bit` | commercial | unverified finish `0/0/0` | no | contained model failure | invalid execution | no |
| 21 | mini-high | `LIFObuffer` | open | first-pass `0/0/0` | yes | completed | passed | yes |
| 22 | mini-high | `LIFObuffer` | commercial | fail-repair-pass `1/1/1` | yes | completed | passed | yes |
| 23 | mini-high | `asyn_fifo` | open | first-pass `0/0/0` | yes | verifier rejection | failed | no |
| 24 | mini-high | `asyn_fifo` | commercial | fail-repair-pass `1/1/1` | yes | verifier rejection | failed | no |
| 25 | full-xhigh | `radix2_div` | open | first-pass `0/0/0` | yes | completed | passed | yes |
| 26 | full-xhigh | `radix2_div` | commercial | first-pass `0/0/0` | yes | completed | passed | yes |
| 27 | full-xhigh | `multi_pipe_8bit` | open | fail-repair-pass `1/1/1` | yes | completed | passed | yes |
| 28 | full-xhigh | `multi_pipe_8bit` | commercial | fail-repair-pass `1/1/1` | yes | completed | passed | yes |
| 29 | full-xhigh | `LIFObuffer` | open | first-pass `0/0/0` | yes | completed | passed | yes |
| 30 | full-xhigh | `LIFObuffer` | commercial | first-pass `0/0/0` | yes | completed | passed | yes |
| 31 | full-xhigh | `asyn_fifo` | open | first-pass `0/0/0` | yes | verifier rejection | failed | no |
| 32 | full-xhigh | `asyn_fifo` | commercial | first-pass `0/0/0` | yes | verifier rejection | failed | no |

## Integrity finding and hardening

Runs 17 and 20 ended in the agent harness with a contained broker resource-limit failure before a
typed `finish`. The campaign correctly did not retry either process, but the orchestrator version
used for the campaign went on to execute one hidden functional verifier for each frozen candidate.
That violated this variant's final-submission gate even though neither candidate resolved and no
hidden content was exposed to the model. The corrected finalization therefore reports 30 valid
hidden-execution decisions and two invalid ones, making `infrastructure_complete=false` and
`diagnostic_complete=false`.

The post-campaign implementation adds strict boolean task metadata for this gate. When such a task
does not terminate through `FINAL_SUBMISSION`, the orchestrator now emits skipped verifier
placeholders and does not stage or execute hidden assets. Campaign summarization counts only an
executed `functional_hidden` node, distinguishes skipped placeholders from the complete four-node
verifier DAG, and accepts absent provider usage only for a contained no-finish model failure. Tests
cover the task metadata, skip/count semantics, and provider-usage rule. The immutable campaign was
not modified or rerun, preserving its zero-retry contract.

Run 8 is the third contained model failure. It occurred after a valid typed finish, so its single
hidden-verifier execution was authorized; the candidate was rejected. This is distinct from the
gate defect in runs 17 and 20.

## Replay and sanitized evidence

An independent `--finalize-existing` pass used no model calls. It reconstructed all 32 slots and
reported `replay.all_valid=true`, `security-scan.passed=true`, and
`redaction-audit.passed=true`. Provider usage was complete for 30 typed-finish episodes; the two
no-finish contained failures had no provider-usage receipt and are explicitly accounted for by the
corrected summary. No raw model stream, prompt, response, reasoning, hidden test, reference RTL,
auxiliary data, commercial report, private path, endpoint, proxy value, or credential is included
here.

| Evidence | SHA-256 |
| --- | --- |
| Frozen plan | `35a7976f4b037dd0c940cceeefab0ca125dca11c3c5640692e202b218f7d04aa` |
| Corrected summary | `9df73934d073f41e76300708b641334f1016c2989105f8deef47d7b67c135f90` |
| Authorization ledger | `ece85329dc77d4aed81ecd760df246b5a08a1f8a49e98de73bad855e76c3947c` |
| Offline replay | `a3701913523e61d93d77afe0f16c711723b30fd474ee4de0c45593a6c3ec10df` |
| Leakage scan | `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7` |
| Redaction audit | `e270d4a26b1dfbcf45ad9fcecaecfab00b3714b1640fdb843969c0cb3f33a632` |

## Interpretation

The campaign demonstrates real visible-feedback repair behavior: 19 of 32 episodes failed a
public check, patched the candidate, and later passed the public smoke before finalization. It also
shows that public qualification is intentionally weaker than the hidden contract: every typed
finish had passed the final public smoke, while all eight asynchronous FIFO candidates were still
rejected.

Because the run exposed a hidden-verifier sequencing defect, its 22/32 resolved count is retained
only as diagnostic evidence. It must not be presented as an RTLLM score, used to rank the four
model identities, or silently combined with a future corrected campaign. Any successor must use a
new frozen campaign identity and freshly resolved profiles; these 32 model episodes remain
non-repeatable under the zero-retry rule.
