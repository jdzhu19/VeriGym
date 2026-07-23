# ADR 0005: No universal aggregate score

- Status: accepted

## Decision

Reports retain correctness, completion, canonical pass@k, cost, and profile-relative quality as
separate numerator/denominator or partitioned measures. They are not collapsed into one scalar.

## Consequences

Comparisons expose missingness and population changes. Users cannot rank systems with an
apparently precise number that mixes failures, currencies, releases, or incompatible profiles.
