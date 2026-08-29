# OpenHands v20 daemonless prewarm preflight stopped

## Result

The independently authorized no-candidate preflight
`openhands-hwe-v20-daemonless-prewarm-preflight-v1` ran once after authorization PR #16 merged.
It stopped fail closed with status `stopped_security_or_infrastructure_invalid`. The sealed report
hash is `47d737c58adbcc5486613042ca1bac9c8aeae6ec1dee3a7dc75b61b66a0d279f`; the report file SHA-256
is `9e6312f1c5affc64a8752d6061aa47a7e6279aff233ff214f1a61dcdc915e0b3` over 1,176 bytes.

The result belongs only to authorization hash
`1741352e5a2664191f594d975c798279e4bb19b4ef0c9f1815e2e2a6e17b9898` and merged source commit
`e483b300c886b0c7963b463120875e57f2755ac8`. It does not modify or retry the sealed v19 result.

## Failure boundary

The runner validated the registered network and both local image identities, confirmed that all
seven frozen candidate image references were absent, created the atomic running receipt, and
reached the controlled bootstrap container. Effective container inspection completed before the
container was started. The bootstrap command then either returned nonzero or emitted unexpected
stderr, which the runner maps to the single sanitized `ConfigurationError` failure class.

Command output was bounded and deliberately not persisted. The available evidence therefore does
not distinguish a public-network, release-download, checksum, provenance, archive, or other helper
failure. No narrower cause is claimed. The temporary bootstrap directory and container were removed
before control returned, so the stopped identity cannot be resumed or reconstructed from partial
tool files.

## Post-stop invariants

The sealed result and independent host inspection establish:

- candidate downloads authorized: `false`
- candidate downloads started: `false`
- candidate images imported or present: `0`
- qualification started: `false`
- provider calls: `0`
- held-out task IDs loaded: none
- promoted `crane` cache present: `false`
- remaining v20 temporary containers: `0`

The one-file experiment output passed the context-aware artifact scan over 1,176 bytes with zero
hard leaks and zero scanner errors. Its security scan report hash is
`a2c91e759a0be804ea933cfa88aede4b95ad36f3ec9c84ee8266d4108d2340ba`.

## Decision

This v20 identity is sealed and will not be retried. Candidate download/load, public-task
qualification, provider canary, formal collection, SFT, GPU work, and held-out evaluation remain
unauthorized and unstarted. Diagnosing or replacing the bootstrap path requires a new identity and
a separate reviewed authorization; this stopped report grants no continuation authority.
