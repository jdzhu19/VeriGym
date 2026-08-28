# RTL AgentEval Codex GPT-5.4/xhigh smoke-v2 audit

Date: 2026-08-28

Status: formal smoke stopped after one real Codex process. This is a controlled stopped run, not a
completed four-run smoke and not a benchmark score.

## Frozen identities

- Campaign: `rtl-agenteval-codex-gpt54-xhigh-smoke-v2`.
- Agent: `codex-cli-agenteval-gpt54-xhigh-v1`.
- Model request: GPT-5.4 with `xhigh` reasoning, seed 0, one sample per task.
- Codex CLI: `codex-cli 0.147.0`.
- Codex executable SHA-256:
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`.
- Open tool image:
  `sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
- OpenSTA executable SHA-256:
  `343bdff22f5d81d92f6bd1286e064b590305503c514194fae02e6c9cc3626662`.
- Planned real Codex process count: 4. Automatic retry count: 0.

No prompt, response, raw CLI event stream, private reasoning, training transcript, dataset, PDK,
SDC, commercial report, license diagnostic, worker address, or site path is included in this
audit.

## Qualification

A fresh plan-only qualification completed with `model_calls: 0`. It passed:

- RTLLM counter and up/down reference plus known-bad hidden Icarus checks;
- Open Yosys/OpenSTA reference metrics and known-bad synthesis gating for both RTLLM tasks;
- isolated DC/MCP reference metrics and known-bad synthesis gating for the up/down task; and
- independent VCS/MCP reference plus known-bad regressions for both RTLLM tasks.

The formal run repeated the complete preflight before authorizing a model process. Docker verifier
execution remained networkless, and the commercial profiles remained verifier-side only.

## Formal execution result

Exactly one Codex process was started. It was ordinal 1,
`rtllm/counter_12_agent_eval_v1`, using the open PPA profile. The process exited normally after
95.52 seconds and was not retried. The repository broker recorded 9 typed tool calls: 4 reads, 2
patches, 1 diff inspection, 1 public test, and 1 rejected call. It recorded no typed `finish` call.
The adapter classified the result as a non-infrastructure `workspace_policy` failure with
`policy_violation`; the candidate was unresolved and quarantined before hidden verification or
synthesis. Consequently, no candidate PPA metrics were produced.

The policy-failure parse path terminates before constructing the ordinary external-agent identity
observation. The process and broker artifacts prove the single invocation, but the run manifest
contains zero external-agent observations and provider usage is incomplete. This is an evidence
limitation of the stopped run, not permission to infer token usage. The scoring agent and prompt
were not changed after the run.

Before ordinal 2 could start, the required DC/MCP pre-launch re-resolution differed from the exact
resolved identity frozen in the campaign plan. Two immediate no-model resolutions agreed with one
another, the local declared profile remained byte-for-byte equivalent to a fresh binding, and the
frozen input hashes were unchanged. The change was therefore treated as external resolved-identity
drift. Per the campaign contract, execution stopped immediately before spawning another Codex
process.

Ordinals 3 and 4 were not authorized. Final real Codex process count: **1 of 4**. Final automatic
retry count: **0**.

## Offline audit fixes and verification

The stopped run exposed two audit-layer edge cases; neither changes the frozen scoring agent or
prompt:

- verifier-only replay now recognizes only the exact external-workspace quarantine signature. It
  validates stored integrity but does not execute a candidate that the original run quarantined,
  and records `verifier_reexecuted: false`;
- the leakage scanner distinguishes the safe plural local Codex configuration key
  `mcp_servers.verigym` from singular commercial MCP profile or server diagnostics.

The stored ordinal-1 run passed offline integrity replay. Its exact model-facing artifact leakage
scan passed with no findings.

Repository verification after these fixes:

- Core: `1019 passed, 1 skipped, 52 deselected`.
- Ruff: passed.
- Format check: passed for 633 files.
- Core mypy: passed for 213 source files.
- Codex CLI integration: `5 passed`; mypy passed for 25 source files.
- RTLLM integration: `11 passed, 4 skipped`; mypy passed.
- RTL-Repo integration: `13 passed, 1 skipped`; mypy passed.
- VerilogEval integration: `5 passed, 1 skipped`; mypy passed.
- Synopsys integration: `23 passed`; mypy passed.

## Disposition

The four-run smoke did not satisfy its completion criteria: four resolved candidates, four typed
`finish` calls, and valid candidate PPA metrics for both RTLLM runs were not obtained. No aggregate
summary or benchmark score is produced, and the bounded 14-run pilot remains unauthorized.

Do not resume this campaign root. A future attempt requires a fresh campaign identity and output
root with the then-current commercial resolved identity frozen before model authorization. The
ordinal-1 model call remains non-retriable. Any prompt or scoring-agent change also requires a new
agent version.
