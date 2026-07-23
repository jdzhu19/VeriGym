# ADR 0010: Hash-bound artifacts with explicit legacy status

- Status: accepted

## Decision

New run and experiment roots contain bounded manifests of normalized ordinary files. Consumers
verify required paths, sizes, roles, visibility, and hashes before trust. Missing manifests on
older artifacts produce `legacy_unverified`; mismatches produce a distinct integrity error.

## Consequences

Tampering and partial writes are detectable, and replay/report inputs can state their trust
level. Existing artifacts are not rewritten or falsely upgraded to verified status.
