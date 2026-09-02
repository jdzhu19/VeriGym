# RTLLM full-L2 remaining-38 Codex diagnostic v1

Date: 2026-09-02

Status: complete. All 38 frozen slots reached immutable terminal states with one valid identity
observation each, zero retries, and one typed finish each. The result was 37/38 resolved. This is
diagnostic-only evidence, not a native RTLLM score or leaderboard claim.

## Frozen design

- Campaign: `rtllm-full-l2-codex-gpt54-xhigh-remaining38-diagnostic-v1`.
- Variant: `v2-agent-eval-functional-all-v1`; aggregate 50-task identity
  `9a36fdf432c0cbfc2dfaef7a2b067a5ef02b83578e38c0f2015113e7ae9e3d38`.
- Selected task-name identity:
  `02aa62181ea52eaf4766dc315a1a854474b945d423b820389350bf2cfa727eb0`.
- Selected task-identity aggregate:
  `0457f7f4328c041be0001ed1550f2864d993fa07d6f853c5821aea15868e3894`.
- The selected 38 and earlier 12-task contrast are disjoint and their union is the frozen 50-task
  corpus.
- Model request: GPT-5.4, `xhigh`, seed 0, one sample per task, serial execution.
- Agent identity: `codex-cli-agenteval-gpt54-xhigh-functional-v3`; agent-version hash
  `467d2ba0847fab60f39ee7d85a7073abc832e5c35fa299d8e09cb5761c230b3c`.
- Prompt hash: `14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9`.
- Tool-policy fingerprint:
  `6a0cf3b44d0bdb1b6ba2a016607db639e857af8979389ece947c8bea55415ef4`.
- Automatic retries and retry authorization: 0. PPA feedback and final PPA: disabled.

Before model authorization, private zero-model qualification checked one reference and four
controls per task through both public and hidden paths: 190 public and 190 hidden verdicts all
matched expectation. The private staging receipt recorded 0700 directories, 0600 files, complete
cleanup, and zero residual paths. A pre-freeze broker-path-length rejection occurred during an
earlier preflight with zero model calls; the final campaign used a shorter frozen broker root.

## Result

| Outcome | Count |
| --- | ---: |
| Codex processes authorized / started | 38 / 38 |
| Identity / provider observations | 38 / 38 |
| Typed finish | 38 |
| Resolved | 37 |
| First public pass | 31 |
| Public fail -> repair -> pass | 7 |
| Automatic retry | 0 |
| Infrastructure or policy failure | 0 |
| PPA evaluation | 0 |

The seven visible repair sequences were `multi_pipe_8bit` (`1/1/1`), `LIFObuffer` (`1/1/1`),
`freq_divbyfrac` (`2/2/2`), `parallel2serial` (`1/1/1`), `pulse_detect` (`4/4/4`), `alu`
(`1/1/1`), and `instr_reg` (`1/1/1`), where each tuple is public failures, repair patches, and
rechecks after repair. Every final candidate passed its final public smoke.

`asyn_fifo` was the sole hidden rejection. It passed its first public smoke, reached typed finish,
and executed the hidden verifier exactly once. This repeats the public/hidden gap observed for all
eight asynchronous-FIFO slots in the earlier harder diagnostic. It is evidence that the public
projection remains incomplete for this protocol, not infrastructure failure and not a reason to
retry the immutable episode.

## Finalization and evidence

Automatic finalization and an independent `--finalize-existing` pass both completed without a
model call. Offline replay reported all 38 records valid; the exact leakage scan and redaction
audit passed. No generated candidate, trajectory, hidden asset, reference RTL, dataset checkout,
credential, proxy value, Docker layer, or commercial artifact is committed.

| Evidence | SHA-256 |
| --- | --- |
| Plan | `3c45886cdaef507706063b92f1ed0dee5bec667b9b7554358d7764642c12d82b` |
| Summary | `9f2a040789af0aaab6e5b4eea3699512f4a9af03be08f4fdaa043f2e5b9bb4af` |
| Offline replay | `857e5529c57172a6083e4c25538b7945ecf774652c00bc641452ae40e164ec3b` |
| Leakage scan | `1cc2d895955cdb1bc154399b5950fbd5ee7af45ef3a2ba633148b3ee7dfc1ce7` |
| Redaction audit | `6433a08526a21d7c22d6b289a26f5df03cdc68930ecd2b69cbc4eb0bbed1b810` |

Together with the earlier 12-task contrast, this executes one bounded full-L2 observation for all
50 frozen tasks. It does not estimate a deterministic model accuracy, because each slot is a
single stochastic sample.
