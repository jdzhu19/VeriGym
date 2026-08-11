# HWE repo-level Codex GPT-5.4 held-out v1 campaign

- Date: 2026-08-11
- Status: three samples completed; two resolved; one infrastructure-invalid
- Code commit: `000c8e3c825e8728de6be5482cd63fc51829dddc`
- Agent: `codex-gpt54-xhigh-hwe-heldout-v1`, `gpt-5.4`, reasoning `xhigh`
- Split: `hwe-repo-heldout-codex-gpt54-v1`
- Sampling: one sample per task, base seed 3, no retry, no best-of-K

This is a bounded three-task evaluation-line result, not a benchmark score.

## Qualification and independent freeze

The local Codex 0.146.0 model catalog exposed `gpt-5.4` but no GPT-4 model. A minimal ephemeral,
read-only `gpt-5.4/xhigh` call completed in about four seconds. The JSONL surface did not expose a
provider model field for that minimal call, so its identity remained request-bound.

A stronger non-held-out qualification then ran Ibex PR167 through the official isolated
repository path. The CLI returned observed model identity `gpt-5.4`, emitted 70 external CLI
events, used 42,862 input and 1,160 output tokens, and completed in 304.19 seconds. Its one-file,
12-line repair passed the digest-locked verifier. The sanitized diagnostic report hash is
`676b7a06a3db0c76302f7f9df9deb48b050c64c8aa28b397ea0aeb56acc7628c`.

Only after that qualification was the held-out identity frozen. Its agent-version hash is
`6af02f538c3e9c002ef083e14e05a72ebac1700857a88c6794ef8d66664473c8`, its split
manifest hash is `1cb14ea72beafac9f9adb4b70d2f059e03709efaf39dcfdf7bc7db9767b0e29c`,
and its content-free freeze hash is
`786040ad369fc9d93f8d1502f1cdaf5cb8f5f5ca527c92438db09bcb767a44ce`.
It is independent of both the Luna and DeepSeek freezes.

## Held-out outcomes

| Task | Agent time | Usage (input/output) | Patch | Verifier outcome |
| --- | ---: | ---: | ---: | --- |
| Ibex PR222 | 243.02 s | 37,507 / 1,115 | one file, 10 lines | passed |
| CVA6 PR2945 | 88.05 s | 214,542 / 286 | one file, 2 lines | passed |
| Rocket PR3065 | 315.70 s | 72,203 / 1,129 | one file, 12 lines | infrastructure-invalid |

All three CLI observations reported model identity `gpt-5.4` and reasoning `xhigh`. The campaign
plan hash is `670cb749baa7f1ad8fa5b4202d70a4f37fd3e7e1387592af325462bb2901c088`.
It completed exactly three model processes: two resolved records and one infrastructure-invalid
record, under summary hash
`501880edb6d99902d4bf3529f50cbfe8c8c35fcfc3adbc2a6500c01942d75474`.

The Rocket agent completed normally and produced a candidate. Its digest-locked Scala/Chisel
verifier ran for 273.57 seconds, but Docker reported failure while releasing the isolated
coursier cache volume. The sample was therefore correctly classified as infrastructure-invalid;
its candidate was not scored as either pass or reject. A verifier-only replay made zero model
calls but encountered a separate Docker container-creation timeout, so it also could not
determine candidate correctness.

Docker events showed a stale volume reference to a container ID the daemon no longer exposed.
The verifier now makes bounded retries when Docker briefly delays final mount release, covered by
commit `22c3dc753e5b98958b17085e207fe021e6db4e4f`. The host daemon's deeper ghost-reference state
cannot be repaired safely without administrator control; the campaign itself was not retried.

## Offline replay, training exclusion, and safety

Visible replay passed for all stored runs. Trajectory export, validation, and source replay agreed
on dataset hash `2960e005a629320b04a83b7f1ad7474ae64394424f06eda804b76a4a24e7e6dc`.
The dataset contains all three records, marks the two resolved records structurally eligible, and
explicitly excludes Rocket as `infrastructure_invalid`. Every record still belongs to the frozen
`heldout` split.

Training-reference preparation therefore exited with code 2 and created no bundle. The training
exclusion report hash is
`f22a60d3dae07caad8753aba4e7fbbc9fa20c87f81cb335fb0d954f72ba0aa55`.
The final context-aware scan covered 308 exported files and 22,131,467 bytes. It passed with zero
hard secret leaks and zero scanner errors under report hash
`1794dbd07909768e28f54863f765a5b7dc7bd87a5eaf9df660109b4f92f4a1c5`.

The result demonstrates that an available non-Luna Codex model can complete the real HWE
repository path. It does not establish a general model ranking, and the infrastructure-invalid
Rocket record is not a model failure or a valid score.
