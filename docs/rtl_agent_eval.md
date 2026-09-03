# RTL AgentEval v1

AgentEval v1 adds multi-turn variants without changing or aggregating the original RTLLM,
VerilogEval V2, or RTL-Repo single-turn partitions. The six-action `repository_action.v2`
envelope is unchanged. AgentEval resolves `repository_action_state_machine_v3` and its prompt
contract before any model lookup.

## Variants

- RTLLM: `counter_12_agent_eval_v1` and `up_down_counter_agent_eval_v1`.
- RTLLM full corpus: `v2-agent-eval-all-v1` provides L1 candidate-only compile feedback for all
  50 frozen tasks; `v2-agent-eval-functional-l2-batch1-v1` adds PPA-disabled L2 functional
  feedback for three evidence-selected tasks; `v2-agent-eval-functional-all-v1` provides a
  separately frozen, PPA-disabled L2 projection for all 50; and
  `v2-agent-eval-functional-harder-v1` remains the separately qualified L2/L3 four-task diagnostic
  partition. `v2-agent-eval-functional-ppa3-v1` is a distinct three-task L2/L3/L4 projection with
  separately qualified OpenSTA and DC partitions.
- VerilogEval V2: `v2-spec-to-rtl-agent-eval-v1`.
- RTL-Repo: `official-parquet-v1-agent-eval-v1`; the compatible, separately identified
  source-priority projection is `official-parquet-v1-agent-eval-v2`; the independently frozen
  immediate-physical-line projection is `official-parquet-v1-agent-eval-v3`.

Every successful patch invalidates compile, PPA, and diff evidence. `ppa` is accepted only after
`compile` passes for the exact current candidate hash. Finish requires a current diff and, when
exposed, a current compile pass. Repeating a candidate/profile PPA request uses a cache but remains
a normal tool call. Real synthesis executions default to three and are hard-bounded to eight.

The full-corpus RTLLM projection deliberately sets `ppa_supported=false` and
`gym_qualification_level=L1_compile_only`. A successful public compile proves only syntax and
elaboration. It does not imply public functional coverage, hidden correctness, synthesis
qualification, or a native RTLLM score. Hidden RTLLM assets are staged only after typed `finish`;
the final result remains a derived diagnostic projection with the upstream task identity retained.
The bounded [12-task L1 Codex pilot](audits/rtllm_full_l1_codex_12task_pilot_v1.md) demonstrates
this boundary in practice: nine first-pass public compiles produced six hidden passes and three
hidden rejections, while three no-finish episodes did not execute the hidden verifier.

The later `v2-agent-eval-functional-all-v1` projection is a distinct task identity. It preserves
the same frozen 50-task source inventory but replaces compile-only feedback with one independent,
hash-bound candidate-only functional smoke per task. It records
`gym_qualification_level=L2_functional_smoke`, keeps PPA disabled, and retains final-only hidden
verification. Its [qualification record](audits/rtllm_full_corpus_l2_qualification_v1.md) covers
50 reference candidates and 200 four-category controls through both public and hidden paths. L2
means useful repeatable functional feedback, not exhaustive correctness, synthesis qualification,
or a native RTLLM score.

The bounded [12-task full-L2 contrast](audits/rtllm_full_l2_codex_12task_contrast_v1.md) reuses
the exact task order, GPT-5.4/xhigh request, seed, serial policy, and zero-retry/no-PPA dimensions
from the earlier L1 pilot. It produced 9/12 resolved, 11 typed finishes, and five visible
fail -> repair -> public-pass sequences; replay, leakage, and redaction audits passed. The
functional-v3 prompt/tool identity is separately frozen for L2, so the paired single observations
are diagnostic evidence rather than a pure single-variable causal estimate.

The [remaining-38 campaign](audits/rtllm_full_l2_remaining38_codex_diagnostic_v1.md) completed one
GPT-5.4/xhigh, seed-zero, zero-retry observation for every full-L2 task not in the earlier 12-task
contrast. It recorded 37/38 resolved, 31 first public passes, seven fail -> repair -> pass
sequences, and one asynchronous-FIFO hidden rejection. Together the two campaigns cover all 50
frozen task slots once, but remain diagnostic single samples rather than a benchmark score.

The [`v2-agent-eval-functional-ppa3-v1` qualification](audits/rtllm_ppa3_dual_backend_qualification_v1.md)
passes candidate-only L3 feedback and correctness-gated candidate/reference L4 projection for
`radix2_div`, `multi_pipe_8bit`, and `LIFObuffer` under both Yosys/OpenSTA and isolated DC/MCP.
The two backends remain non-comparable profile partitions. The unified 50-task L2 variant remains
PPA-disabled, and `asyn_fifo` is excluded because its public/hidden functional gap repeated across
independent campaigns.

The separately frozen L2 batch-one projection also sets `ppa_supported=false`, but replaces the
compile-only contract with an independent public functional smoke for `adder_pipe_64bit`, `LFSR`,
and `serial2parallel`. Its [qualification record](audits/rtllm_l2_batch1_qualification_v1.md)
requires reference pass plus four public/hidden negative-control rejections per task. Disabling PPA
here means the agent has no `ppa` action and final scoring performs no synthesis; it does not mean
that the RTL is unsynthesizable or that PPA can never be added under a later qualified variant.
The bounded [three-task L2 Codex diagnostic](audits/rtllm_l2_batch1_codex_3_diagnostic_v1.md)
observed fail -> repair -> public pass in all three slots, followed by two hidden passes and one
hidden rejection, with zero retries and zero PPA evaluations.

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

VerilogEval's separate `v2-spec-to-rtl-agent-eval-vcs-mcp-public-v1` variant may route the existing
`compile` public-test action through `synopsys.vcs.public-compile.mcp`. This does not expose the MCP
service itself to the model: core returns only a sanitized compile verdict and bounded candidate
path/line/error-code diagnostics. The compile service has no testbench, reference, simulation, or
artifact interface. Final hidden verification still requires an independent `synopsys.vcs.mcp`
profile, and neither path adds DC or PPA feedback.

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

The successor freezes Agent `codex-cli-agenteval-gpt54-xhigh-v3` and campaign smoke-v5. A
scripted no-model diagnosis reproduced concrete defects capable of producing both broad smoke-v4
failure classes: some malformed unified-diff hunk syntax was treated as terminal policy, and a
bounded read of an empty RTL-Repo visible file raised an internal exception. Smoke-v4 deliberately
did not retain enough call detail to claim these were its exact model actions. Smoke-v5 keeps
malformed patches recoverable, renders empty files as zero-line observations, persists only
allowlisted terminal broker subtypes, and finalizes formal replay/leakage evidence when the fourth
materialized run is infrastructure-invalid. Earlier infrastructure failure still stops before
another model authorization.

Smoke-v5 then showed that the first three public compile calls were rejected before their
utility containers started because the launcher had not bound the external public-test image.
Smoke-v6 bound that exact image and qualified the compile bridge without a model. Its open RTLLM
run completed typed `finish` with valid PPA feedback, while the commercial RTLLM run stopped the
campaign after a dispatched disposable worker failure; ordinary candidate and reference DC/MCP
verification still passed. Smoke-v6 therefore remains a failed qualification and does not
authorize a pilot.

The next successor freezes Agent `codex-cli-agenteval-gpt54-xhigh-v4` and campaign smoke-v7.
Commercial worker failures now retain only an allowlisted `scheduler`, `worker`, or `response`
subcategory across the server, client, feedback controller, and broker. Unknown remote text is
reduced to a fixed generic subtype. The launcher also executes real open and commercial
candidate-feedback synthesis during its no-model qualification, so a disposable-worker failure
stops before any Codex process is authorized.

Smoke-v7 preflight exposed and fixed two no-model integration defects: qualification candidates
were staged under an extra repository directory, and the already-validated outer release binding
was incorrectly forwarded to the inner local synthesis service. The rebuilt release passes the
complete disposable-worker lifecycle and commercial synthesis qualification. After host capacity
was restored, the full plan-only pass completed with zero model calls and the formal smoke started
four frozen Codex processes with zero retries. All four produced one valid identity observation,
resolved through typed `finish`, and passed replay and leakage scanning; both RTLLM tasks contain
legal current-candidate PPA feedback. The first post-run replay exposed and fixed a composite
Yosys/OpenSTA script-identity validator defect without rerunning a model. Smoke-v7 now authorizes
the separately gated 14-run pilot, which has not started, and remains a qualification rather than a
benchmark score. The complete result is recorded in the
[smoke-v7 audit](audits/2026-08-29_rtl-agenteval-codex-gpt54-xhigh-smoke-v7-result.md).

The completed read-only pilot-v1 then recorded 10/14 resolved candidates and 12/14 typed finishes;
it did not claim a benchmark score. Its successor freezes Agent
`codex-cli-agenteval-gpt54-xhigh-v5`, adapter `5.0.0`, prompt v4, and the v2 RTL-Repo projection.
The prompt exposes both task and effective process wall-time, hard tool/patch limits, exact
editable paths, and a final 60-second completion reserve. Broker responses expose rounded elapsed
and remaining wall-time without an absolute deadline. Recoverable patch diagnostics and terminal
path diagnostics are bounded enums; path termination cancels the process and persists neither the
requested path nor raw exception text.

The guarded six-process diagnostic is implemented by
`scripts/run_rtl_agenteval_codex_gymfix_diagnostic.py`. It runs counter/OpenSTA,
counter/DC, RTL-Repo v2 tests 000002/000003/000005, and test 000004 as a success control, exactly
once each with zero retry. Model failure and verifier rejection are recorded before continuing;
identity drift, policy failure, Docker/tool infrastructure failure, or commercial control-plane
failure stops later authorization. Replay, exact leakage scanning, and a separate redaction audit
are finalized offline. Every plan and summary remains `diagnostic_only=true` and
`benchmark_score_claimed=false`; success does not automatically launch a new pilot.

The completed diagnostic launched all six frozen processes once with six requested-only identity
observations, complete provider usage, and no timeout, policy, or infrastructure failure. It did
not meet the all-success gate: 5/6 runs used typed `finish` and 1/6 resolved. Both RTL-Repo
test-000003 and the test-000004 control passed native Exact Match, but their episodes failed closed
on a non-canonical MCP machine-event stream; the DC candidate similarly compiled and produced
legal candidate PPA before that event-stream classification made final PPA ineligible. The
campaign remains read-only and does not authorize pilot-v2. See the
[gym-fix diagnostic audit](audits/2026-08-29_rtl-agenteval-gymfix-diagnostic-v1-report.md).

Agent `codex-cli-agenteval-gpt54-xhigh-v6` preserves prompt v4 and the six-tool broker but fixes
the scoring event contract to match Codex CLI 0.147.0: a completed assistant message after typed
`finish` is optional. The adapter still requires a successful process, a terminal event, exact
broker/event tool accounting, one broker-accepted `finish`, and no post-finish tool call. Bounded
event failure subcategories are retained without raw stdout, message content, arguments, or paths.

The current `codex-cli-agenteval-gpt54-xhigh-v10` keeps prompt v6 and the same six canonical tools.
It attests the exact broker tool sequence and accepted `finish` index, treats the JSONL MCP server
label as bounded advisory metadata, and configures the VeriGym server with
`omit_tools_from=["deferred"]` so Codex 0.147.0 exposes the tools directly instead of routing them
through deferred tool search. See the
[qualification v6 and pilot v7 audit](audits/2026-08-30_rtl-agenteval-codex-gpt54-xhigh-pilot-v7-report.md).

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
