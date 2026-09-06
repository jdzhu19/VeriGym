# RTLLM L2 diagnostic-three qualification v1

Date: 2026-09-02

Status: passed. This is a zero-model qualification of a derived, diagnostic-only RTLLM Gym
projection. It is not a native RTLLM score or a model campaign.

## Scope and review finding

The variant `v2-agent-eval-functional-l2-diagnostic3-v1` contains `div_16bit`, `LFSR`, and
`freq_divbyodd`. Its aggregate task-identity SHA-256 is
`450b098809e5827aaa096ac1e2c05f135941a4d7728cfb2884a54fab7b2ec7ae`.
PPA remains disabled.

Review used only the frozen upstream prompts and independently authored public smokes. It found
that the older `LFSR` smoke implicitly required reset to change the output before a rising edge,
although the prompt specifies reset behavior on the rising edge. The diagnostic projection now
samples reset synchronously. The `div_16bit` smoke adds independent boundary vectors and reports
the complete failing quotient/remainder observation. The `freq_divbyodd` smoke covers `NUM_DIV=3`
and `NUM_DIV=5`, models both clock-edge domains, and reports the failing edge and phase. It does
not disclose hidden vectors or expected-output files.

The frozen public-smoke SHA-256 values are:

| Task | Public smoke SHA-256 |
| --- | --- |
| `div_16bit` | `5bc52e81b079c67fca11c1a45121bb1f3689122cf1bc03b1fcca693ea75b6655` |
| `LFSR` | `8f91095e663e03ba459150a92c33bd8d27ac74318e5cf9cb288962d3b3566174` |
| `freq_divbyodd` | `0eb84a162792ed278a04a5b8031838ef9ab073ca703742216c370615fc58f04c` |

## Qualification

For each task, the normalized upstream reference and four compile-shaped controls were checked
against both the public smoke and final hidden verifier. Controls represent stuck-zero,
reset/initial-boundary, protocol/latency, and task-specific functional errors.

| Path | Reference passes | Controls rejected | Result |
| --- | ---: | ---: | --- |
| Public functional smoke | 3 | 12 | passed |
| Hidden functional verifier | 3 | 12 | passed |

All 30 compile/simulation paths ran in the no-pull Icarus 12 Docker image identified by
`sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`, with networking
disabled. Hidden assets and normalized references were written only to private 0700/0600 staging.
The Docker runtime and staging cleanup receipts both reported complete cleanup and zero residual
paths. No model, agent, PPA, VCS, or Design Compiler process ran.

## Interpretation

This qualification corrects a public-feedback contract and improves diagnostics without changing
the upstream prompt bytes, the hidden verifier, or the historical full-L2 task identities. It
does not prove the three public smokes are exhaustive. A public pass remains weaker than the one
final hidden verdict.
