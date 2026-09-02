# Synthesis quality profiles and comparison

A `ToolchainProfile` is the contract that gives a synthesis number meaning. The built-in
`open-yosys-toy-area-v1` profile uses an Apache-2.0 educational Liberty library with an abstract
`toy_area_unit`. Its values are profile-relative teaching metrics, not silicon estimates or
signoff results.

A verifier backend profile is orthogonal to this contract. For example,
`--verifier-profile ...synopsys.vcs.mcp...` may select hidden functional verification while
`--toolchain-profile ...synopsys.dc.mcp...` selects final PPA. VCS is not a synthesis/PPA backend,
and changing the verifier transport cannot make open and DC numbers comparable. Both resolved
identities are retained, but only the complete resolved toolchain profile defines a PPA partition.

Optional backends can implement `synthesis_area_timing` or `synthesis_area_timing_power`. VeriGym
supports a site-specific Yosys/OpenSTA synthesis profile and a site-specific Synopsys DC profile.
Both report area, maximum-path delay, worst-negative slack, and estimated power under exact
library, SDC, activity, script, runtime, and tool identities. Neither profile reports physical
design, frequency, TNS, or signoff quality.

## Synthesis metrics are not ranked PPA

RTLLM AgentEval may expose candidate-only Yosys/OpenSTA ATP v2 metrics during iteration. Those
observations are separately quota-bound and cached by candidate/profile hash; they contain no
reference or ratio and are never promoted into the final score. Final PPA reruns candidate and
reference after hidden correctness passes. A DC/MCP profile may expose the same candidate-only
metric projection only when its resolved identity includes the phase-two disposable-worker
contract and cleanup semantics. The final scorer does not reuse iterative results. See
[RTL AgentEval v1](rtl_agent_eval.md).

Open feedback keeps the historical v1 cache-miss ledger. Isolated commercial feedback uses the v2
dispatch ledger: one PPA repository action is distinct from one real synthesis execution, a cache
hit consumes no execution, a dispatched crash/timeout does, and a pre-dispatch failure does not.
Both retain the default execution budget of three and hard maximum of eight.

Open Yosys/OpenSTA and commercial DC results remain independently partitioned even if they use the
same task, nominal library family, clock period, or functional verifier. There is no cross-profile
ranking or silent fallback between them.

`SynthesisMetrics` records what Yosys produced: structural counts, cell histogram, optional mapped
area, diagnostics, tool/profile identity, script hash, and artifact references. These raw metrics
can exist when synthesis is attempted, including on a path that is later ineligible for ranking.

`ScoreCard.ppa` is a separate projection. Area becomes rankable only when all of these hold:

1. hidden functional verification passed;
2. candidate synthesis passed with mapped area greater than zero;
3. the suite's frozen reference RTL synthesized successfully;
4. candidate and reference used the same resolved profile;
5. both areas and their ratio are finite and positive.

An incorrect candidate has `ppa.eligible=false` and ranked `area`, `reference_area`, and
`area_ratio` all remain `null`, even if raw synthesis diagnostics exist. Runs without a synthesis
profile preserve the all-`null` PPA behavior. Area-only profiles keep delay, frequency, power,
worst-negative slack, and total-negative slack `null`. Area/timing profiles additionally require
finite delay and WNS for both candidate and reference with the same timing unit and clock period.
Area/timing/power profiles additionally require finite positive candidate/reference power with the
same power unit and activity mode. The ranked value is unavailable when any of those identities or
measurements are missing.

Generic cell count is not area: cell types have different costs, mapping choices matter, and an
unmapped generic cell has no profile-defined physical area. Only Yosys's Liberty-based area under
the exact resolved library is labeled mapped area.

## Declared and resolved identity

The declared-profile hash covers the strict versioned YAML contract. It expresses intent: tool
requirements, runtime policy, assets, flow, metric unit, and reference strategy.

Resolution checks reality and creates a second canonical hash. The resolved identity covers:

- profile ID/version and declared hash;
- exact Docker image ID, isolation/security policy, and resource contract, or a labeled local
  executable identity for exploratory profiles;
- actual Yosys version/git output and ABC identity observed in the runtime;
- exact Liberty and other asset hashes, licenses, units, and semantics;
- generated flow-template and per-task script hashes;
- source list, fixed top, metric contract, and reference semantics.

Mutable Docker tag text and timestamps are not identity. The requested tag remains audit metadata;
the immutable image ID is used for execution and exact-profile replay. Changing a tool, image,
asset byte, script, unit, flow, or reference contract changes the resolved hash.

## Reference normalization

The reference strategy is `suite_reference_solution`. Reference RTL is copied only into a new
verifier-private runtime session after the candidate is frozen. The public score retains a bounded
reference metric summary, never the RTL, netlist, script, or raw reference log.

The ratio is:

```text
area_ratio = reference_area / candidate_area
```

Therefore `1.0` means equal mapped area, greater than `1.0` favors the candidate, and less than
`1.0` means the candidate is larger. Both operands use the same exact resolved profile and unit.
Delay and power ratios use the same reference-over-candidate convention, so a value above `1.0`
means the candidate is lower under that exact profile. Each metric remains separately reported.

## Strict comparison and replay

`verigym report compare LEFT RIGHT --metric area|delay|worst_negative_slack|power` emits a ranking only
when both scorecards are eligible and
their task, metric scope/unit, reference strategy, profile ID/version, declared hash, and resolved
hash match. It refuses incompatible inputs with a configuration error naming the differing
fields. A shared profile ID alone is insufficient.

`verigym replay RUN --verify` validates stored artifact hashes, re-resolves the stored declared
profile against the exact stored image ID and tool identities, and runs verifier-only correctness,
candidate synthesis, and reference synthesis. It performs no model lookup or call and writes
replay output separately without mutating the original artifacts.

## Adding an open profile

An open profile contribution must include a strict YAML declaration, a uniquely identified and
redistributable Liberty asset with license/NOTICE, pinned tool and runtime contracts, deterministic
flow-template identity, explicit units and area semantics, and a suite reference strategy. Add it
to the built-in registry, package only the intended generic assets, and provide schema, hash,
parser, security, integration, replay, comparison, and license tests. Public ranking profiles must
require immutable Docker resolution, network isolation, and mandatory resource controls.

Do not relabel a changed library or flow under an old identity. Do not claim equivalence between a
host-local exploratory result and the canonical Docker result. Private and commercial profiles
follow the additional rules in [commercial tools](commercial_tools.md).

## Open-source synthesis timing and power

The built-in `open-yosys-toy-area-v1` profile remains area-only. The versioned
`verigym-yosys-opensta-atp-v2` template adds site-specific synthesis area, timing, and power:

1. Yosys reads the frozen Liberty and approved RTL, runs synthesis, maps flip-flops and
   combinational logic through ABC, and emits mapped netlists plus `stat -json` area.
2. Standalone OpenSTA reads that mapped Verilog, the same Liberty, and one hash-bound SDC.
3. OpenSTA selects one named clock, verifies its period, applies an explicit Liberty wire-load
   model, and reports maximum-path arrival and WNS.
4. OpenSTA power uses a frozen global clock-relative activity and duty factor. The parsed value is
   `report_power -format json` `Total.total`: internal plus switching plus leakage power.
5. Every successful run retains `units.rpt` and `activity_annotation.rpt`. The latter reports
   explicit VCD/SAIF/port annotations; global vectorless fallback activity is intentionally shown
   as unannotated and is not treated as a failed power run.

The original `verigym-yosys-opensta-atp-v1` contract remains available only for exact replay of
already frozen results. General new profiles use v2; adding diagnostics did not silently relabel
the v1 script or alter its generated-script hash. The separately identified
`verigym-yosys-opensta-atp-v3` compatibility template retains the v2 reports and metrics but asks
Yosys for a structural Verilog netlist with `-noexpr -nodec -simple-lhs`. Use it for heterogeneous
catalogs where OpenSTA cannot parse every valid Yosys expression form. The v4 template additionally
maps Yosys positive- and negative-enable latch primitives to the corresponding frozen Liberty
cells; RTLLM PPA47 uses v4 because its `fsm` reference infers a latch. Earlier profiles and results
remain unchanged and are not comparable across a changed profile identity.

`scripts/prepare_nangate45_ppa_profile.py` hashes the complete external NanGate45 PDK tree and
emits a local profile without copying PDK bytes into the repository. Local execution is for trusted
RTL smoke tests only. A public campaign profile still needs a digest-locked verifier image,
network isolation, and resource controls.

```bash
python scripts/prepare_nangate45_ppa_profile.py \
  --pdk-root /private/PDK/NangateOpenCellLibrary_PDKv1_3_v2010_12 \
  --sdc /private/constraints/design.sdc --opensta /private/tools/bin/sta \
  --output-manifest /private/profiles/nangate45.manifest.json \
  --output-profile /private/profiles/yosys-opensta.yaml \
  --source rtl/design.v --top design --clock-name clk --clock-period 10
verigym profiles validate site-nangate45-yosys-opensta-atp-v2 \
  --file /private/profiles/yosys-opensta.yaml
```

Clocked designs should name the SDC clock explicitly. A purely combinational design must use a
separately identified profile whose SDC creates a virtual clock and defines input/output delays;
the flow never guesses clocks from port names and never falls back to unconstrained timing.

OpenROAD does not participate in this synthesis profile. Add it only as a separately identified
physical-PPA profile when placement, clock-tree synthesis, routing, and extracted parasitics are
intentionally part of the metric. Physical and synthesis-only results must never share a comparison
partition. VCD/SAIF-annotated and global-activity power likewise require different profile
identities.
