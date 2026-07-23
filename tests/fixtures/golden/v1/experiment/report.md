# VeriGym experiment report: m9-golden-milestone9-ffa1089ffe7b67bb

This report keeps correctness, coverage, cost, and profile-relative area separate. It does not define a universal VeriGym score.

## Identity and compatibility scope

- Source: `experiment`
- Config hash: `1a0bb010ecffa2f579e8a4874a4aa4d4875f32502ebc2e939b12f08e38565307`
- Plan hash: `ffa1089ffe7b67bb274bf0897b4d23a1937be17c6c1b48d5f98b2852d55fb5dd`
- Input-set hash: `72cdd08446c139d4d4e0c63a2eea7d39af9bd594e73bec35b6a3d97f2425c50f`

## Compatibility partitions

Correctness is never pooled across different suite release/source or correctness identities.

| Partition | Planned | Valid | Evaluable | Resolved | Resolved/evaluable | Tasks | Systems |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `2b01075c7e480bb3a83a4555f1dce282480dd1948416910a9da484d1fe446356` | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

## Plan and completion coverage

| Measure | Count |
| --- | ---: |
| Planned plan items | 1 |
| Started plan items | 1 |
| Terminal child runs | 1 |
| Valid terminal artifacts | 1 |
| Evaluable candidate runs | 1 |
| Resolved runs | 1 |
| Unresolved evaluable runs | 0 |
| Infrastructure errors | 0 |
| Corrupt/incompatible artifacts | 0 |
| Missing plan items | 0 |

## Correctness with explicit denominators

- Resolved rate over evaluable candidates: 1 (1/1)
- Resolved rate over planned items: 1 (1/1)
- Evaluation completion rate: 1 (1/1)

| Stage | Passed | Applicable | Rate | Missing | Infrastructure errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| compile | 1 | 1 | 1 | 0 | 0 |
| hidden_regression | 1 | 1 | 1 | 0 | 0 |
| formal | 0 | 0 | null | 1 | 0 |
| equivalence | 0 | 0 | null | 1 | 0 |

## Failure taxonomy

- Candidate outcomes: resolved=1
- Model infrastructure: none
- Runtime/sandbox: none
- Verifier/tool: none
- Batch/artifact: none

## Efficiency and cost

Efficiency summaries use resolved runs only. Missing cost is not zero, and costs without a persisted currency identity are not summed.

| Metric | Known | Missing | Mean | Median | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| wall_time_s | 1 | 0 | 0 | 0 | seconds |
| model_input_tokens | 1 | 0 | 0 | 0 | tokens |
| model_output_tokens | 1 | 0 | 0 | 0 | tokens |
| total_tokens | 1 | 0 | 0 | 0 | tokens |
| tool_calls | 1 | 0 | 5 | 5 | calls |
| turns | 1 | 0 | 6 | 6 | turns |
| model_api_cost | 0 | 1 | unavailable | unavailable | partitioned below |

Unknown cost unit/currency values: 0; incompatible-unit values: 0.

| Cost dimension | Identifier | Known | Sum |
| --- | --- | ---: | ---: |

## Per-system coverage

| Group | Planned | Valid | Evaluable | Resolved | Resolved/evaluable | Tasks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2b01075c7e48:system=scripted | 1 | 1 | 1 | 1 | 1 | 1 |

## Sampling, Best-of-N, and pass@k

Samples are grouped by exact evaluation identity and base seed; base seeds are not pooled. Infrastructure errors invalidate canonical pass@k.

| Task | System | Base seed | n | c | Valid | Best-of-N | pass@k |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| toy-rtl/and-gate-basic | scripted | 0 | 1 | 1 | yes | True | pass@1=1 |

## Area-only quality partitions

Area is educational, profile-relative, correctness-gated, and non-signoff. Partitions are never ranked against each other; timing and power are unavailable.

No profile-enabled area results are present.
## Child runs

| Plan | Attempt | Status | Run |
| ---: | ---: | --- | --- |
| 0 | 1 | completed | [golden-experiment-child](../runs/golden-experiment-child) |

## Warnings and invalid artifacts

- Warning: 1 legacy artifact set(s) had no integrity manifest.
- Warning: Model cost is missing for 1 resolved run(s).
