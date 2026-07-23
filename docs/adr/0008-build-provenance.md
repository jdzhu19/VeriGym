# ADR 0008: Embedded build provenance

- Status: accepted

## Decision

Builds bind package version to a verified source commit, deterministic source-tree hash, dirty
state, backend/Python identity, and optional reproducible-build epoch. Wheels embed the record;
live checkouts derive it from Git plumbing.

## Consequences

Installed runs no longer use a nullable best-effort commit. Unknown and dirty states remain
representable and visible; unknown source identity fails an official candidate gate.
