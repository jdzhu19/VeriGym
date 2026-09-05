# RTLLM full-corpus L1 Codex 12-task pilot v1

Date: 2026-09-01

Status: passed as a bounded diagnostic. All 12 frozen model-process slots reached an immutable
terminal state with one identity observation and zero retries. Six candidates resolved. Offline
replay, exact leakage scanning, and redaction auditing passed. This is compile-only L1 evidence,
not a native RTLLM score, functional qualification of the 50-task corpus, or a PPA result.

## Frozen scope

- Campaign ID: `rtllm-full-l1-codex-gpt54-xhigh-12task-pilot-v1`.
- Source commit: `41b26896e33b536940116a975626455eed3de65e`.
- Suite variant: `v2-agent-eval-all-v1`.
- Agent version: `codex-cli-agenteval-gpt54-xhigh-v10`.
- Requested model and reasoning: `gpt-5.4` / `xhigh`.
- Codex CLI identity: `codex-cli 0.147.0`.
- Seed and sample count: seed 0, one process per task.
- Execution policy: serial, zero retry, stop on infrastructure, policy, or identity failure.
- PPA: disabled; no open or commercial synthesis tool was invoked.
- Runtime image:
  `sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.

The 12 tasks were selected before model authorization and exclude the two original counter tasks
and the four tasks from the prior harder diagnostic. They cover Arithmetic, Control, Memory, and
Miscellaneous:

| Order | Task | Category |
| ---: | --- | --- |
| 1 | `adder_32bit` | Arithmetic |
| 2 | `fixed_point_substractor` | Arithmetic |
| 3 | `div_16bit` | Arithmetic |
| 4 | `multi_booth_8bit` | Arithmetic |
| 5 | `adder_pipe_64bit` | Arithmetic |
| 6 | `JC_counter` | Control |
| 7 | `sequence_detector` | Control |
| 8 | `LFSR` | Control |
| 9 | `synchronizer` | Control |
| 10 | `RAM` | Memory |
| 11 | `freq_divbyodd` | Miscellaneous |
| 12 | `serial2parallel` | Miscellaneous |

Each task exposed only repeated candidate-only Icarus compile feedback. A successful public check
therefore established syntax and elaboration, not behavior. Hidden assets were staged only after a
typed `finish`; the full-corpus L1 variant remained `ppa_supported=false`,
`gym_qualification_level=L1_compile_only`, `diagnostic_only=true`, and
`benchmark_score_claimed=false`.

## Zero-model qualification

Qualification ran before model authorization and made zero model calls. For every selected task,
the reference passed public compile and hidden verification, while a missing-module candidate was
rejected by both paths. All 48 checks passed. The exact image identity, 12 task hashes, launcher
hash, agent identity, prompt contract, tool policy, hidden gate, and zero-retry policy were bound
into the frozen plan.

## Results

The authorization ledger contains exactly 12 unique terminal records: six `completed`, three
`verifier_rejection`, and three `contained_model_failure`. All 12 processes started and recorded
one valid identity observation. No process timed out and no policy or infrastructure failure was
recorded.

| Task | Typed finish | Public compile | Hidden execution | Terminal result |
| --- | ---: | --- | --- | --- |
| `adder_32bit` | yes | first pass | passed | resolved |
| `fixed_point_substractor` | yes | first pass | passed | resolved |
| `div_16bit` | yes | first pass | passed | resolved |
| `multi_booth_8bit` | yes | first pass | passed | resolved |
| `adder_pipe_64bit` | yes | first pass | rejected | verifier rejection |
| `JC_counter` | yes | first pass | passed | resolved |
| `sequence_detector` | no | not called | not executed | contained model failure |
| `LFSR` | yes | first pass | rejected | verifier rejection |
| `synchronizer` | no | not called | not executed | contained model failure |
| `RAM` | no | not called | not executed | contained model failure |
| `freq_divbyodd` | yes | first pass | passed | resolved |
| `serial2parallel` | yes | first pass | rejected | verifier rejection |

Nine episodes reached typed `finish`; all nine had passed their candidate-only public compile on
the first attempt. Three of those nine candidates were nevertheless rejected by the hidden
functional verifier. No episode exhibited a visible fail -> repair -> pass loop. This is expected
evidence that compilation alone is too weak to guide functional repair.

The three no-finish episodes are agent-control outcomes, not functional verdicts. Their Codex
processes exited without timeout, but no typed `finish` was observed. The final-submission gate
emitted only skipped verifier placeholders: it did not stage or execute hidden assets for those
episodes. They must not be counted as either hidden passes or hidden failures.

PPA feedback and final PPA were disabled for every slot. Neither Yosys/OpenSTA, VCS, nor Design
Compiler was used by this campaign.

## Replay and sanitized evidence

Automatic finalization and an independent `--finalize-existing` pass made no additional model
calls and reproduced the same terminal summary. Replay reported all records valid; exact leakage
scanning and redaction auditing passed. Provider usage was complete for the nine typed-finish
episodes and totals 1,277,639 input tokens, 1,118,720 cached input tokens, 51,925 output tokens,
and 1,329,564 total tokens. No provider cost was recorded. Missing usage for the three contained
no-finish outcomes is retained rather than estimated.

| Evidence | SHA-256 |
| --- | --- |
| Frozen plan | `aeead1839f07291edcd8cb5852c787e48e75d8b1248691a4200283f97266fe23` |
| Summary | `0fab3dadfa15faef421a9acb52f5a97c1d195d52cc0bbd2b103a450b7113e7df` |
| Authorization ledger | `bade990a3e785c5c634d9b84fa4beedd0ff7ce045c131664c9373c3baf4e9ac4` |
| Offline replay | `a432744cae79c5eeb468bd769b2fa3da6ceb1fbb5822f91bf99f6e889992a981` |
| Leakage scan | `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7` |
| Redaction audit | `63a0ccb1d4e3b2995bdcc2006ea93addf28b25b6e3ed6dcb931313ed72718f0b` |

Experiment outputs remain outside the repository. No dataset checkout, reference RTL, hidden
testbench, auxiliary hidden data, generated candidate, raw trajectory, model reasoning, Docker
layer, credential, proxy value, or commercial asset is committed in this record.

## Interpretation and next stage

The pilot demonstrates that the generic all-50 adapter, typed finish gate, and immutable campaign
discipline work in a real multi-turn Codex path. It does not show that every task has useful
multi-turn functional feedback: the only visible validation was compilation.

The strongest evidence-driven L2 candidates are `adder_pipe_64bit`, `LFSR`, and
`serial2parallel`, because all three reached typed finish, passed public compilation, and were then
rejected by hidden functionality. They should receive independently authored public functional
smokes in a new, separately qualified variant. The no-finish tasks may be revisited later but are
not promoted on the basis of an unobserved hidden result. PPA remains a later, separate L3/L4
qualification and must not be enabled by inheriting this L1 variant.
