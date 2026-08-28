# RTL AgentEval v1

AgentEval v1 adds multi-turn variants without changing or aggregating the original RTLLM,
VerilogEval V2, or RTL-Repo single-turn partitions. The six-action `repository_action.v2`
envelope is unchanged. AgentEval resolves `repository_action_state_machine_v3` and its prompt
contract before any model lookup.

## Variants

- RTLLM: `counter_12_agent_eval_v1` and `up_down_counter_agent_eval_v1`.
- VerilogEval V2: `v2-spec-to-rtl-agent-eval-v1`.
- RTL-Repo: `official-parquet-v1-agent-eval-v1`.

Every successful patch invalidates compile, PPA, and diff evidence. `ppa` is accepted only after
`compile` passes for the exact current candidate hash. Finish requires a current diff and, when
exposed, a current compile pass. Repeating a candidate/profile PPA request uses a cache but remains
a normal tool call. Real synthesis executions default to three and are hard-bounded to eight.

## Feedback boundaries

Public `compile` invokes only Icarus syntax/elaboration over candidate files. It contains no hidden
golden RTL or testbench. RTLLM alone may enable candidate-only Yosys/OpenSTA ATP v2 feedback:

```bash
verigym run ... \
  --suite-variant counter_12_agent_eval_v1 \
  --agent-ppa-feedback --agent-ppa-max-calls 3 \
  --toolchain-profile site-nangate45-yosys-opensta-atp-v2
```

RTLLM AgentEval fails closed unless both resolved Icarus compiler/runtime identities are major
version 12. The opt-in qualification runs reference and known-bad candidates for both tasks against
the explicitly supplied, no-pull image; an incompatible image is not downgraded into a release.

The observation contains candidate area, maximum-path delay, WNS, power, units, and the resolved
profile hash. It never contains a reference metric, ratio, netlist, critical path, or raw report.
Final scoring independently synthesizes candidate and reference only after hidden correctness
passes. Open and commercial profiles have distinct resolved identities and comparison partitions.

AgentEval workspaces use `repository/rtl/<task>.v`, while existing synthesis profiles and the
qualified commercial server contract retain `rtl/<task>.v`. The hash-bound
`synthesis_source_projection.v1` maps those names once and is shared by profile resolution,
candidate feedback, final/reference synthesis, and replay. A missing, extra, reordered, or changed
mapping fails before model lookup.

The pinned open profile may run entirely in the immutable
`verigym/open-rtl-tools:iverilog12-yosys067-opensta310` image. That independent image freezes
Icarus 12, Yosys 0.67 and its ABC source identity, and OpenSTA 3.1.0 without replacing the older
qualified image tag. Docker profile preparation resolves and hashes `sta` inside the image; it
does not attempt to read a container executable through a host path. Build networking is confined
to the explicitly selected site bridge, while benchmark, feedback, synthesis, and verifier
sessions remain `network=none`.

The isolated commercial contract additionally declares that area, delay, and power are minimized
while WNS is maximized. It reports separate PPA tool-call and dispatched-execution counters, keeps
the last valid candidate-only metric vector after a later failed run, and counts a timeout or crash
after dispatch against the execution budget. A pre-dispatch policy, staging, or profile failure
does not consume a synthesis execution. Cache hits remain ordinary repository actions but do not
consume another synthesis execution.

VerilogEval and RTL-Repo reject PPA feedback. RTL-Repo presents a read-only
`official-context projection`: indexed Parquet context snippets and cropped target code, not a
claim of a complete repository. Only `repository/completion.txt` is editable; `next_line` remains
verifier-only and `all_code` is never loaded for task execution.

## Run isolated DC/MCP feedback

Phase two permits `--agent-ppa-feedback` with `synopsys.dc.mcp` only when profile resolution proves
a hash-bound disposable-worker contract. The model still receives exactly the six
`repository_action.v2` actions and invokes PPA only as `run_public_test(test_id="ppa")`; the MCP
tools are not registered as model-visible tools.

The current qualified site contract launches one candidate per LSF job. The job owns a private
workspace, receives the candidate and commercial environment only after scheduler dispatch,
returns structured candidate metrics without artifacts, and must delete its workspace before the
launcher emits a cleanup receipt. The MCP client binds the launcher hash, loaded VeriGym and
integration source-tree identity, isolation-profile hash, worker receipt, server profile, DC
version, DB/SDC hashes, activity contract, and resolved profile hash. Its control-plane timeout
must reserve 300 seconds beyond the worker wall bound so scheduler termination and cleanup finish
before the launcher can be stopped. A profile without all of these fields is rejected before model
lookup; there is no fallback to the older in-process service.

New phase-two profiles also bind `commercial_worker_release.v1`. Server and worker Python,
startup code, sanitized profile identities, remote-tool identities, commercial-asset hash
manifests, and the isolation contract contribute to one release hash. Code is materialized in a
read-only content-addressed directory; DB, PDK, SDC, licenses, and commercial reports are never
copied into it. Resolve and execute carry the same expected release hash, and the launcher,
server, client, and cleanup receipt all reject a mismatch. Legacy worker-protocol-v1 payloads
remain parseable, but smoke-v3 and successor site profiles require the release binding explicitly.

```bash
verigym run ... \
  --suite-variant counter_12_agent_eval_v1 \
  --agent-ppa-feedback --agent-ppa-max-calls 3 \
  --toolchain-profile site-dc-agent-mcp-v2 \
  --toolchain-profile-file /private/profiles/dc-agent-mcp-v2.yaml
```

The Docker agent workspace receives no MCP transport, license, PDK/library path, raw commercial
report, scheduler identity, or control-plane path. The worker's network policy is honestly labeled
`site_license_controlled`, not `none`; only the agent container remains networkless. VCS/MCP stays
functional-verifier-only and is not part of iterative PPA.

Commercial single-turn RTLLM runs may replace their native VCS verifier node with a task-bound
`synopsys.vcs.mcp` profile. This is a verifier transport selection, not an agent tool or a new
benchmark variant. Manifest, scorecard, experiment plan, and replay bind the client profile,
wrapper hash, server declared/resolved identities, public contract hash, and exact VCS version.
See [verifier backend profiles](verifier_profiles.md).
Bounded reference/known-bad and end-to-end VCS/DC evidence is recorded in the
[commercial MCP qualification](audits/rtl_commercial_mcp_qualification_v1.md); it is
infrastructure qualification, not a benchmark score.

Manifest and replay bind the resolved `agent_feedback_contract`, its hash, and a contiguous ledger
of feedback evaluations: test ID, candidate/profile hashes, cache status, synthesis-execution
status, duration, category, and candidate metrics. AgentEval requires Docker for model-bearing
agents. Real Docker, external benchmarks, Open PPA, and commercial tools remain explicit opt-ins.

The guarded four-run Codex smoke is implemented by
`scripts/run_rtl_agenteval_codex_smoke.py`. It completes every dataset, Codex, Docker, OpenSTA,
DC-worker, VCS/MCP, reference, and known-bad check before creating the experiment directory. The
launcher then authorizes exactly four ordered Codex processes, persists its authorization ledger
atomically, never retries, performs structural offline replay, and scans scoring artifacts for
hidden/reference content and site/commercial path leakage. Smoke-v4 records authorization,
process start, provider observation, and retry count separately. Contained model failures,
policy failures, and verifier rejections are recorded before the next ordinal; resolved-identity,
commercial-tool, and Docker control-plane failures stop the campaign immediately. A 14-run pilot
is authorized only when all four processes have one identity observation, every candidate is
resolved through typed `finish`, both RTLLM candidates have current valid PPA metrics, and replay
plus leakage scanning pass without policy or infrastructure failures. This smoke and any successor
pilot are qualifications, not benchmark scores.

Smoke-v3 is a read-only failed predecessor. Its first process returned a contained workspace-policy
failure, and its second ordinal stopped before model launch when the commercial MCP client bound a
session-local output limit into the runtime identity. Smoke-v4 removes that dynamic field while
retaining every stable Docker resource limit, uses a new commercial release and campaign output,
and does not resume or reinterpret smoke-v3.

Smoke-v4 subsequently passed its full no-model open/DC/VCS qualification and launched all four
frozen Codex processes with zero retries. None reached typed `finish`: the first three terminated
on workspace policy and RTL-Repo ended with a broker tool infrastructure failure. Neither RTLLM
task produced PPA feedback, so the pilot remains unauthorized. The complete bounded result and
the distinction between formal and diagnostic replay evidence are recorded in the
[smoke-v4 audit](audits/2026-08-28_rtl-agenteval-codex-gpt54-xhigh-smoke-v4-result.md).

## Design choices informed by POSTEDA-Bench

[POSTEDA-Bench](https://github.com/pengjas/posteda-bench) and its
[paper](https://arxiv.org/abs/2605.06936) distinguish effective period, total power, and die area,
publish structured tool contracts, and define framework-specific iteration accounting. VeriGym
adopts explicit metric direction, dispatched-flow accounting, last-valid-state handling, and
separate multi-objective values. It does not copy POSTEDA's 16/18-flow budgets: commercial
AgentEval retains the frozen default of three and hard limit of eight.

VeriGym also does not compute POSTEDA's target-relative NIS or silently restore a Pareto-best
sandbox. RTLLM tasks do not publish comparable PPA target thresholds, and `finish` must submit the
latest revision. If a future benchmark publishes objective thresholds and constraint floors, it
must use a new objective contract and score partition rather than retrofitting these runs.
