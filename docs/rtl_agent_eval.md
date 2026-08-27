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

VerilogEval and RTL-Repo reject PPA feedback. RTL-Repo presents a read-only
`official-context projection`: indexed Parquet context snippets and cropped target code, not a
claim of a complete repository. Only `repository/completion.txt` is editable; `next_line` remains
verifier-only and `all_code` is never loaded for task execution.

## Commercial-tool phase boundary

Synopsys DC/MCP remains a verifier-only final PPA backend for a frozen candidate. Phase one rejects
agent-visible PPA combined with a commercial backend before model lookup. The Docker agent
workspace never receives MCP transport, license, PDK, commercial reports, or control-plane paths.
Agent-visible DC/MCP requires a future isolated worker and a new security claim.

Manifest and replay bind the resolved `agent_feedback_contract`, its hash, and a contiguous ledger
of feedback evaluations: test ID, candidate/profile hashes, cache status, synthesis-execution
status, duration, category, and candidate metrics. AgentEval requires Docker for model-bearing
agents. Real Docker, external benchmarks, Open PPA, and commercial tools remain explicit opt-ins.
