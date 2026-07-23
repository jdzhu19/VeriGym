# ADR 0006: Exact-profile, correctness-gated area

- Status: accepted

## Decision

MVP quality is Liberty-mapped synthesis area only. Ranked area requires functional correctness
and candidate/reference synthesis with the same resolved profile hash. Cross-profile and
same-ID/different-hash comparisons are refused.

## Consequences

Area ratios are meaningful only within one educational profile. Timing, frequency, power, WNS,
and TNS remain null; generic cell count is never renamed area. OpenROAD and signoff PPA are out of
scope.
