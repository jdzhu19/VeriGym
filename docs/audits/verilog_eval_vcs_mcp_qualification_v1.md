# VerilogEval VCS/MCP functional qualification v1

Date: 2026-09-03

## Result

The independent `v2-spec-to-rtl-agent-eval-vcs-mcp-v1` partition is qualified as a
commercial functional-verification replacement for 155 eligible tasks from the frozen
156-task VerilogEval V2 source snapshot.

| Check | Result |
| --- | --- |
| Eligible task identities | 155/155 bound and resolved |
| Reference-as-candidate | 155/155 passed |
| Known-bad empty-interface candidate | 155/155 rejected |
| Real VCS/MCP simulation jobs | 310 |
| VCS identity | `V-2023.12-SP2-2_Full64` |
| Model calls | 0 |
| Automatic job retries | 0 |
| Bundle identity | `74bf2fcaea84241d61c32c4829240549b2d9b2011f4b524253da6c06054b54c6` |
| Qualification identity | `c790e6e96ad7175ff93ea99f28e321d9637ee1e812398920549c4aec02f2f168` |

The 16 deterministic shard receipts cover 155 distinct task IDs without overlap. Their task
counts sum to 155 and their commercial-job counts sum to 310. The aggregate receipt verifies the
bundle, dataset, task, client/server profile, transport, resolved-profile, and exact-tool
identities before accepting the coverage result.

This is qualification evidence, not a model benchmark score. The variant remains
`diagnostic_only`; `benchmark_score_claimed=false` and `ppa_enabled=false`.

## End-to-end AgentEval smoke

A separate zero-model `Prob014_andgate` run exercised the complete Gym control path with the
qualified commercial partition. Its deterministic agent performed five turns: list visible files,
apply the reference patch, run the public compile, inspect the diff, and submit typed `finish`.
The public Icarus 12 compile evaluation passed inside the network-disabled repository-agent
container, then the one-shot hidden `vcs_regression` passed through VCS/MCP. The run completed with
`final_submission`, its scorecard resolved true, and its artifact manifest verified.

This smoke added one real VCS job outside the 310-job corpus qualification aggregate. It made zero
model calls and used resolved verifier profile hash
`acd715cb0edbc9fef811e2a4be0de388fe7f710ab9ed0af0dd4cee2661a9a305`. The external run directory,
candidate, trace, and commercial output remain outside the repository.

## Contract

Public multi-turn feedback remains a candidate-only Icarus 12 compile check. Hidden functional
verification runs once only after typed `finish`, through a required task-bound
`synopsys.vcs.mcp` profile. A missing profile or a profile targeting another backend fails before
model startup. Direct VCS fallback is not permitted.

The client submits only `repository/rtl/TopModule.sv`. The server owns the official reference,
testbench, executable, license setup, source order, top, marker, timeout, and raw output. The
private combined compilation unit preserves both official bodies. If the reference has no
timescale, it first copies the official testbench's own `` `timescale`` directive so VCS does not
reject earlier design units with `ITSFM`.

A pass requires a normal VCS exit and the official `Mismatches: 0 in` summary prefix. The
180-second process timeout rejects hangs, and absence of that pass marker rejects native watchdog
exits. The testbench's `TIMEOUT` text is not a higher-priority marker because several official
tests schedule the watchdog and successful final summary at the same simulation time; VCS may
print both while still reporting zero mismatches.

## Eligibility exclusion

`Prob099_m2014_q6c` is excluded with
`reference_testbench_port_contract_mismatch`. Its frozen testbench connects ports absent from the
frozen `RefModule`; the reference fails compilation under both Icarus 12 and VCS. Because the
golden side is not compilable, no candidate can receive a valid comparative verdict. This was a
zero-model source eligibility decision, not a model failure or retry.

## Compatibility and identity preservation

The VCS result is a separate profile partition and is not reported as an official/upstream Icarus
score. No DC adapter or synthesis/PPA result participates. Existing `v2-spec-to-rtl`,
`v2-spec-to-rtl-agent-eval-v1`, and functional-smoke variants were not modified. Synthetic-fixture
regressions retain the previously frozen task hashes:

- base task: `6544e7d5ad244cd5caeacacf6559a2a596c4657ebc2f876febd8f673d4f0f0f7`
- AgentEval v1 task: `c6af36b522e08b55694938c514fd3aa7b12e5ea408a768525a8e41675f786398`

## Artifact boundary

The complete profile bundle, combined hidden assets, site paths, transports, raw VCS output,
license environment, workspaces, and per-task receipts remain outside the repository. This audit
contains only stable counts, reason codes, tool identity, and aggregate hashes. No benchmark RTL,
test vector, commercial asset, credential, or license value is committed.
