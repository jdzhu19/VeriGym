# OpenHands v23 daemonless version-contract fix authorization

## Decision

This preregistration authorizes one new no-candidate preflight under identity
`openhands-hwe-v23-daemonless-prewarm-preflight-v1`. It preserves the sealed v22 status
`stopped_security_or_infrastructure_invalid`, report hash
`7506b9f12d0e66b53fc49272817da4f44753b0239f1dc85bb9def5bc530e83b9`, report-file SHA-256
`93f94ab312d7bb54d405f9336edc24ab18d292f2b8dfb3a78922351f0cb12800`, and audit commit
`728f012c3fe7ea1ffe1a71aa8f3ab0f3ad5435fc`. It does not retry, relabel, import, or reuse v22.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v23_daemonless_preflight_v1.json`; its authorization hash is
`aa9b8bdc9c00a0c7eeb0bd39bc4febe4ea681b2a16d034f11d16c3359347bdc3`.

## Root cause and upstream contract

v22 completed all nine bootstrap stages, including its fully qualified verifier invocation and
cryptographic SLSA pass. Its next `network=none` command returned exit code zero, no stderr, and
seven stdout bytes. The runner rejected those bytes because it had constructed `v0.22.0\n` from
the release tag. Offline inspection of the already verified public binary established the actual
bytes as `0.22.0\n`.

The upstream v0.22.0
[`crane version` documentation](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_version.md)
explicitly says consumers should not depend on its format because it depends on how the binary was
built. The matching
[`version.go` source](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/cmd/version.go)
prints the build-injected `Version` value without adding a release-tag prefix. v23 therefore treats
the GitHub tag and CLI version output as two independent observations. It does not strip or add a
`v` at runtime and does not weaken the exact-output gate.

## Independent version-output binding

The v23 authorization binds all three related but distinct facts:

- GitHub release tag: `v0.22.0`
- exact verified crane binary SHA-256:
  `771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94`
- exact registered `crane version` stdout: seven bytes `0.22.0\n`, SHA-256
  `464863ee696ca862f6ae2bfee9728ebbd84463597825442efc62838d945b00fb`

Authorization validation requires that the registered stdout is exactly the observed value and is
not equal to `release_tag + newline`. The networkless smoke compares exact bytes. A successful
outer report retains only the output byte count and SHA-256; the content-free command receipt still
records exit code and bounded stdout/stderr counts. A regression distinguishes the registered
seven-byte value from the rejected eight-byte tag-derived value.

## Preserved supply-chain and isolation controls

v23 retains v22's exact crane archive, checksum list, Sigstore provenance, official
`slsa-verifier` v2.7.1 binary, source and builder bindings, digest-locked bootstrap and execution
images, and registered non-candidate digest probe. It retains the absolute verifier-path control,
restricted subprocess `PATH`, structural Sigstore validation, cryptographic verification, safe
extraction, atomic stage receipts, bounded output accounting, and cleanup validation. The reviewed
v23 bootstrap helper SHA-256 is
`3491c01ab0e64138e05b0e98dad50de61deb8ac948a16207c165a1d97f8c99b1`.

v23 uses a new cache at a distinct identity-bound path and does not copy or mount the v22 cache.
Containers remain non-root with read-only roots, cap-drop `ALL`, no-new-privileges, private IPC/PID
namespaces, bounded resources and `/tmp`, no ports, no Docker socket or daemon, and one narrow
scratch mount. Bootstrap and the registered public digest probe alone use `verigym-hwe-net`;
`crane version` uses `network=none`. No registry credential, provider credential, proxy value,
candidate source, hidden verifier, or held-out identifier is supplied.

## Verification before authorization

- v23 targeted regression: `8 passed`; combined v20/v21/v22/v23 regressions: `27 passed`;
- v23 regression covers the independent tag/output binding, exact seven-byte success, absolute
  verifier execution under restricted `PATH`, and content-free receipts;
- v23 Ruff lint/format and strict mypy over both scripts: passed;
- ordinary credential-free repository suite: `1027 passed`, `1 skipped`, `52 deselected`;
- OpenHands credential-free Python 3.12 suite: `262 passed`; strict mypy: `28 source files`;
- HWE credential-free suite: `37 passed`; strict mypy: `9 source files`;
- core strict mypy: `206 source files`; v23 scripts strict mypy: `2 source files`;
- documentation contracts: `2 passed`; exported schemas: no drift;
- Ruff lint/format over all tracked Python and the three new Python files, plus
  `git diff --check`: passed;
- core wheel and sdist were each byte-identical across two builds; distribution content audit:
  passed;
- changed implementation/config/security scan: `6 files`, `145,728 bytes`, zero hard leaks and
  zero scanner errors; report hash
  `e5244600ab8897bfc30423b104a37444b2d6c86d8f9dfd8f0be84cabda232f75`.

These checks establish the implementation and authorization boundary only. They are not candidate
qualification, agent-quality evidence, or a benchmark result. The repository, integration,
Docker-security, OpenHands package, packaging, and reproducible-build Actions remain merge gates
for this authorization.

## Explicitly not authorized

This authorization does not permit downloading or loading any frozen CVA6 candidate image,
running zero-model qualification, materializing a reserve split, making a provider call, starting
collection, SFT or GPU work, or accessing held-out tasks. Only after this authorization merges may
one new v23 no-candidate preflight run. It may not be retried under the v23 identity. Passing it
would prove only the downloader, verifier-launch, version-smoke, and registered non-candidate
digest controls and would still require a separate candidate-transfer authorization.
