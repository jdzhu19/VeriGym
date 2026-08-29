# OpenHands v21 daemonless prewarm preflight stopped

## Result

The independently authorized no-candidate preflight
`openhands-hwe-v21-daemonless-prewarm-preflight-v1` ran once after authorization PR #18 merged at
commit `8db1887dd6fd2dfe04097c0b2bed021e2aab08af`. It stopped fail closed with status
`stopped_security_or_infrastructure_invalid` and will not be retried. The sealed report hash is
`5134b3adbc8747691516041acb3ce87524ff221b7bbcc68c4a168dd3c9c3837e`; the report file SHA-256 is
`c0ad1a9755d9e5769d770b6784d257ba16e629b43e396dcc58104c6a10fc7748` over 2,642 bytes.

This result belongs only to authorization hash
`e2212d71e39c8447872fdbe9e2eeda8bf7aded2b016ac72179aa7b48446100a7`. It preserves the sealed v20
result and does not modify, reconstruct, or relabel either predecessor.

## Exact failure boundary

The v21 atomic helper receipt completed these stages before failure:

1. download the registered crane archive;
2. download the registered checksum list;
3. download the registered Sigstore provenance bundle;
4. download the registered `slsa-verifier` binary;
5. validate the official checksum binding;
6. validate the Sigstore v0.3 bundle, DSSE payload, artifact, builder, source, commit, workflow, and
   material bindings.

The next stage, `verify_slsa_signature`, failed with helper failure class `FileNotFoundError`. The
controlled bootstrap container returned exit code 2 with zero stdout bytes and zero stderr bytes.
Its effective-control hash was
`559b12034fa894bec3d0c0834968bc3fd78394b28040c93ba1853f07f069711f`, and cleanup verification
recorded `temporary_container_removed=true`.

Static review resolves this content-free diagnostic without recovering deleted tool files or raw
output. The helper constructed `Path("slsa-verifier-linux-amd64")` and passed its unqualified string
as argv item zero while setting subprocess PATH to `/usr/bin:/bin`. The current working directory
was `/download`, but the executable had no directory component and `/download` was not in PATH.
Python's official
[`subprocess` documentation](https://docs.python.org/3.11/library/subprocess.html) recommends a
fully qualified executable path for maximum reliability and explains that the supplied environment
controls PATH resolution. The verifier process therefore never started; this is not a signature,
TUF, release-identity, or network rejection.

## Post-stop invariants

The sealed result and independent host inspection establish:

- candidate downloads authorized: `false`
- candidate downloads started: `false`
- candidate images imported or present: `0`
- qualification started: `false`
- provider calls: `0`
- held-out task IDs loaded: none
- promoted v21 tool cache present: `false`
- remaining v21 temporary containers: `0`

The one-file experiment output passed the context-aware artifact scan over 2,642 bytes with zero
hard leaks and zero scanner errors. Its scan report hash is
`ab30686384b01a570a1400ba5d7d2aaaad7fd4f1205415ee65c8cab705cf5343`.

## Decision

This audit does not authorize a retry or successor run. Candidate transfer, public-task
qualification, provider canary, collection, SFT, GPU work, and held-out evaluation remain
unauthorized and unstarted. A v22 successor requires a new reviewed identity that resolves and
validates the executable as the exact ordinary file `/download/slsa-verifier-linux-amd64`, adds a
regression with PATH excluding the working directory, and passes the full merge gate before one
new no-candidate preflight.

The v21 staged receipt materially reduced diagnosis: the predecessor could identify only a generic
bootstrap failure, while v21 proved the exact failing stage and exception class without persisting
command output. This diagnostic contract is retained for the successor.
