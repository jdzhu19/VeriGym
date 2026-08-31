# RTLLM Codex strength × dual-backend diagnostic v1

Date: 2026-09-01

Status: the four frozen cells completed 16 real Codex CLI episodes. All 16 candidates resolved,
used typed `finish`, recorded one identity observation, passed public validation, and produced a
legal final-candidate PPA result through the selected open or commercial backend. This is a
diagnostic, not a benchmark score.

## Frozen matrix

Each cell ran the same four ordered slots with seed 0, one sample per task/backend, and no episode
retry:

1. RTLLM 12-bit counter with Yosys/OpenSTA;
2. the same counter with Synopsys DC/MCP;
3. RTLLM up/down counter with Yosys/OpenSTA;
4. the same up/down counter with Synopsys DC/MCP.

The agent was functional-v3. The shared prompt hash was
`14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9`, and the shared tool-policy
fingerprint was `6a0cf3b44d0bdb1b6ba2a016607db639e857af8979389ece947c8bea55415ef4`.

| Cell | Requested model / reasoning | Agent version hash | Valid runs |
| --- | --- | --- | ---: |
| mini-low | `gpt-5.4-mini` / `low` | `d41741d8f4cee7e4cf53e3c99f3aad9512a9ea0266c4be89522fc1d5e94d85ef` | 4 |
| mini-medium | `gpt-5.4-mini` / `medium` | `2bc08440bad001e83a238aceaa9da4fa647e04723d9f85124609e0f232f43f81` | 4 |
| mini-high | `gpt-5.4-mini` / `high` | `cad433bd3e90d5623d889229971069993321ab765f677946bf1bb698c9405239` | 4 |
| full-xhigh | `gpt-5.4` / `xhigh` | `467d2ba0847fab60f39ee7d85a7073abc832e5c35fa299d8e09cb5761c230b3c` | 4 |

Before every cell, the launcher independently qualified the source and task identities, Codex CLI,
Docker isolation, open PPA profiles, content-addressed DC workers, VCS/MCP reference and known-bad
behavior, and all four exact agent-feedback paths. Model execution remained serial.

## Results

| Cell | Resolved | Typed finish | Legal final PPA | Tool calls | Patches | Fail → repair → pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mini-low | 4/4 | 4/4 | 4/4 | 46 | 7 | 0 |
| mini-medium | 4/4 | 4/4 | 4/4 | 35 | 4 | 0 |
| mini-high | 4/4 | 4/4 | 4/4 | 42 | 6 | 0 |
| full-xhigh | 4/4 | 4/4 | 4/4 | 25 | 4 | 0 |
| Total | 16/16 | 16/16 | 16/16 | 148 | 21 | 0 |

Open and commercial paths each resolved 8/8. Every episode had complete provider usage, one
requested identity observation, no timeout, no policy failure, no model-time infrastructure
failure, and at most one execution of each hidden verifier node. All 16 first public validations
passed.

This run demonstrates tool-interaction multi-turn behavior: an episode used 6–16 typed tool calls,
read and edited the candidate, ran public compile/functional/PPA feedback, inspected the result,
and finished through the typed protocol. It does **not** demonstrate functional repair multi-turn
behavior because no candidate received a visible failing validation before passing. The two RTLLM
tasks are therefore too easy for this model set to rank reasoning strength or estimate repair-loop
benefit. The lower tool-call count for full-xhigh is descriptive only; four repeated task/backend
slots do not support a capability claim.

The per-cell `fully_successful` field is false solely because this diagnostic's strict gate requires
at least one observed fail → repair → pass loop. `infrastructure_complete`,
`diagnostic_complete`, and `all_candidates_resolved` are true for all four valid cells.

## Gym gap found and fixed

The first mini-medium v1 attempt completed the expensive no-model qualification but stopped before
Codex started. The broker's final Unix socket exceeded its 100-byte bound because the launcher
accepted a broker root up to 72 bytes without reserving the 36-byte temporary-directory/socket
suffix. Its authorization ledger contains one infrastructure-failed record with
`process_started=false`, zero identity observations, and retry count zero.

The fix validates the resolved broker-root byte length at input qualification, before Codex,
Docker, or commercial qualification work, and aligns the adapter's defense-in-depth bound to 64
bytes. The failed v1 output remains immutable. Mini-medium continued under a distinct successor v2
campaign with the same frozen agent, prompt, task, seed, and backend identities; because v1 started
no Codex process, this did not repeat a model episode.

## Replay and security evidence

Independent `--finalize-existing` passes reconstructed all four cells without model access. Every
cell reports `replay.all_valid=true`, exact leakage scan passed, and broker redaction audit passed.
No raw provider stream, prompt, response, reasoning, hidden RTL, reference RTL, commercial report,
site path, worker endpoint, proxy value, or credential is included here.

| Cell | Plan SHA-256 | Summary SHA-256 |
| --- | --- | --- |
| mini-low v1 | `737a1207a5b56730951ca503aabe3965a9014221cd621429bd818875c14e20ad` | `7b29d11a0c405422c8139acb1b34bea10bd23108aba8b8284e40c105853123b6` |
| mini-medium v2 | `0e89ae6b007a9f941736f3bf31104116a8ff7cd53ed268c46ce99fe2706957d1` | `269f68f95c5c1ee124176658d6eda53187a8772ddad9abd1fa781f4b17048397` |
| mini-high v1 | `92eb53d324691ea2b1ee0856c8e10b71637f4af91d9ec6046f978cfd4972a764` | `d66de0bde3525813cba9ae05fabb9c655b10e8cbddea81c792cb1bec704523a4` |
| full-xhigh v1 | `424dded4bf6a788f20f47a8f14c260f1404b497a02180a551d88dee60cb95707` | `46bb5e683edf7430a2896372f472a8eb23a363bd3ed3ef800d82f07853436291` |

The stopped mini-medium v1 authorization-ledger hash is
`6916c11896a0263d9bacf883754eca3675cce4e1fcd9078b814a959c353871ff`.

## Interpretation and next step

The commercial and open Gym paths are both operational and consistent for these two tasks. This
result cannot distinguish the four model settings and should not be aggregated into a benchmark
score. A useful RTLLM successor needs separately frozen, harder task projections with independent
public functional smoke that can reject plausible first candidates, while retaining the same
open/DC pairing and hidden-verifier-once boundary.

