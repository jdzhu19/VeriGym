# Synthesis-area profiles and comparison

A `ToolchainProfile` is the contract that gives a synthesis number meaning. Milestone 8 supports
one metric scope, `synthesis_area_only`; it does not implement full PPA. The built-in
`open-yosys-toy-area-v1` profile uses an Apache-2.0 educational Liberty library with an abstract
`toy_area_unit`. Its values are profile-relative teaching metrics, not silicon estimates or
signoff results.

## Synthesis metrics are not ranked PPA

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
profile preserve the Milestones 0–7 all-`null` PPA behavior. Delay, frequency, power,
worst-negative slack, and total-negative slack remain `null` for every Milestone 8 run.

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

## Strict comparison and replay

`verigym report compare LEFT RIGHT` emits a ranking only when both scorecards are eligible and
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
