# OpenHands v22 daemonless prewarm preflight stopped

## Result

The independently authorized no-candidate preflight
`openhands-hwe-v22-daemonless-prewarm-preflight-v1` ran once after authorization PR #20 merged at
commit `f5716fd9f863bbe63fb9a50eab005d1c9d7e425e`. It stopped fail closed with status
`stopped_security_or_infrastructure_invalid` and will not be retried. The sealed report hash is
`7506b9f12d0e66b53fc49272817da4f44753b0239f1dc85bb9def5bc530e83b9`; the report file SHA-256 is
`93f94ab312d7bb54d405f9336edc24ab18d292f2b8dfb3a78922351f0cb12800` over 1,859 bytes.

This result belongs only to authorization hash
`6eebf2cce2283d27ae51d4286110ae5b720a092b14f8ff560f8e5cfbfc69d203`. It preserves the sealed
v20 and v21 results and does not modify, reconstruct, or relabel either predecessor.

## Passed repair boundary

The v22 atomic helper receipt completed all nine registered stages:

1. download the crane archive, checksum list, Sigstore provenance, and `slsa-verifier`;
2. validate the official checksum and structural Sigstore/SLSA bindings;
3. invoke `/download/slsa-verifier-linux-amd64` through the new absolute-path control;
4. complete cryptographic SLSA verification and safe crane extraction;
5. persist the final bootstrap receipt.

The verifier returned exit code zero with zero stdout bytes and 303 bounded stderr bytes. The
bootstrap progress hash is
`803d279a20eb587b8797def895396933d0f47803cbaa9787259fe55b1ada1bfb`; the receipt hash is
`942053a31b4078cbb44960d460cdb99472fe5aca1a305d6eff369c7ac486b7c9`. The extracted crane binary
SHA-256 is `771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94`.

These facts prove that v22 fixed v21's process-launch defect. The SLSA verifier was actually
started by its fully qualified path and passed; the failure did not recur at signature validation,
TUF refresh, extraction, cache validation, or cleanup.

## Exact new failure boundary

The next `network=none` stage executed the verified crane binary's `version` command successfully:
exit code zero, zero stderr bytes, and seven stdout bytes. The runner then rejected the output at
`crane_version_output`; its frozen assertion had constructed `v0.22.0\n` from the GitHub release
tag, which is eight bytes.

An offline invocation of the already verified public binary confirmed the exact seven bytes
`0.22.0\n`. The upstream v0.22.0
[`crane version` documentation](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_version.md)
explicitly warns consumers not to depend on the version-string format because it is determined by
how the binary was built. The corresponding
[`version.go` implementation](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/cmd/version.go)
prints the build-injected `Version` value as-is. The release tag and CLI output are therefore not
interchangeable, even for the same release. This is a local output-contract defect, not a tool,
network, signature, or release-identity failure.

## Post-stop invariants

The sealed result and independent host inspection establish:

- candidate downloads authorized: `false`
- candidate downloads started: `false`
- candidate images imported or present: `0`
- qualification started: `false`
- provider calls: `0`
- held-out task IDs loaded: none
- promoted v22 public tool cache present: `true`, with exactly eight registered regular files
- remaining v22 temporary containers: `0`

The one-file experiment output passed the context-aware artifact scan over 1,859 bytes with zero
hard leaks and zero scanner errors. Its scan report hash is
`49781d0a8c08fa9bccb2ef777440f49b38a658cc08c9988b169a7df13adb66d2`.

## Decision

This audit does not authorize a retry or successor run. Candidate transfer, public-task
qualification, provider canary, collection, SFT, GPU work, and held-out evaluation remain
unauthorized and unstarted. The v22 cache remains external immutable evidence and must not be
promoted into or reused by a successor identity.

A v23 successor requires a new reviewed authorization. It must not derive CLI output from a release
tag. If the version smoke remains, its expected bytes must be independently registered for the
exact SHA-256-bound binary, with a regression distinguishing `0.22.0\n` from `v0.22.0\n`. The full
merge gate must pass before one new no-candidate preflight.

This is also the required efficiency rule for later infrastructure failures: preserve the exact
content-free failing stage, consult the upstream command contract and implementation before making
a successor, and add a regression for the observed boundary before another real run.
