# OpenHands v21 daemonless bootstrap repair authorization

## Decision

This preregistration authorizes one new no-candidate preflight under identity
`openhands-hwe-v21-daemonless-prewarm-preflight-v1`. It preserves the sealed v20 status
`stopped_security_or_infrastructure_invalid`, report hash
`47d737c58adbcc5486613042ca1bac9c8aeae6ec1dee3a7dc75b61b66a0d279f`, and audit commit
`166d357ca085d809a5495af2043d3a113f76a34d`. It does not retry or relabel v20.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v21_daemonless_preflight_v1.json`; its authorization hash is
`e2212d71e39c8447872fdbe9e2eeda8bf7aded2b016ac72179aa7b48446100a7`.

## Root cause and upstream evidence

An offline replay using the exact three v20 public crane assets established the failure before a
new campaign was authorized. The v20 helper expected each provenance line to be a bare DSSE object
with a top-level `payload`. The official v0.22.0 `multiple.intoto.jsonl` instead contains one
Sigstore bundle with media type `application/vnd.dev.sigstore.bundle.v0.3+json` and a nested
`dsseEnvelope`. Archive hash/checksum validation and safe extraction passed; the old provenance
shape check alone raised `ValueError`.

The producer's official
[v0.22.0 release workflow](https://github.com/google/go-containerregistry/blob/v0.22.0/.github/workflows/release.yml)
uses `slsa-verifier` v2.7.1 to verify every release archive against the provenance, source
repository, and source tag. The pinned official verifier reproduced `PASSED` for the exact Linux
x86-64 archive and identified builder
`generator_generic_slsa3.yml@refs/tags/v2.1.0` at commit
`3f4ff3ca60f51c876ac4bd89e9a787157aaa4f15`. This matches the
[SLSA consumer verification guidance](https://slsa.dev/spec/v1.2/verifying-artifacts), so v21 uses
the producer's supported verifier rather than another local signature approximation.

A second v20 assumption was also over-strict. Docker documents that
[`docker start --attach`](https://docs.docker.com/reference/cli/docker/container/start/) attaches
both stdout and stderr. The official verifier succeeds with exit code zero while emitting bounded
public verification status to stderr. v20 treated any stderr byte as command failure. v21 instead
requires exit code zero, keeps exact role-specific stdout checks, and records only output byte
counts and stderr presence.

## Pinned supply-chain repair

v21 retains the exact crane v0.22.0 archive, checksums, provenance, bootstrap image, execution
image, and non-candidate registry probe registered by v20. It adds the official
[`slsa-verifier` v2.7.1 release](https://github.com/slsa-framework/slsa-verifier/releases/tag/v2.7.1):

- Linux amd64 binary: 33,291,668 bytes, SHA-256
  `946dbec729094195e88ef78e1734324a27869f03e2c6bd2f61cbc06bd5350339`
- v2.7.1 source tag commit: `ea584f4502babc6f60d9bc799dbbb13c1caa9ee6`
- reviewed v21 bootstrap helper SHA-256:
  `c041d06d368a61b50b1d271899b2ef3d6c5bea0bfb426ed631d6241574744deb`

Before executing the verifier, the helper independently requires the exact Sigstore v0.3 bundle
media type, certificate and transparency-log material, nested DSSE payload, unique archive subject
and digest, SLSA v0.2 predicate, builder, build type, tagged config source, source commit, workflow
entry point, and material binding. It then runs the producer's `verify-artifact` command. Extraction
begins only after both checks pass.

The verifier requires Sigstore trust metadata on a fresh machine. Its official implementation uses
the TUF repository maintained by
[`sigstore/root-signing`](https://github.com/sigstore/root-signing) at
`https://tuf-repo-cdn.sigstore.dev`; the same offline limitation is tracked in upstream
[`slsa-verifier` issue 837](https://github.com/slsa-framework/slsa-verifier/issues/837). v21
therefore explicitly authorizes one verifier invocation with its built-in TUF refresh through
`verigym-hwe-net`. It receives a new private HOME inside the bounded `/tmp`, no proxy values or
credentials, and that HOME is destroyed when verification returns. Candidate and registry
credentials remain absent.

## Diagnostic and isolation contract

The helper atomically records these content-free stages before and after execution:

1. the four fixed public downloads;
2. checksum and Sigstore bundle validation;
3. cryptographic SLSA verification;
4. safe crane extraction;
5. bootstrap receipt persistence.

On success or failure, the outer runner retains only the stage, failure class, exit code,
stdout/stderr byte counts, stderr-presence bit, effective-control hash, and verified cleanup state.
It never persists command output, exception text, URLs containing user data, proxy values,
credentials, task source, hidden tests, or trajectories. Output is bounded to 16 KiB per stream.

The v20 container boundary remains in force: ordinary non-root containers, read-only root,
cap-drop `ALL`, no-new-privileges, private IPC/PID namespaces, bounded resources and `/tmp`, no
ports, no Docker socket or daemon, one narrow scratch mount, exact argv/environment inspection,
and verified cleanup. Bootstrap alone uses `verigym-hwe-net`; `crane version` uses `network=none`;
the registered non-candidate digest probe uses `verigym-hwe-net`.

## Verification before authorization

The repair was exercised without loading a candidate or invoking a provider:

- exact v20 public artifacts reproduced the old parser failure;
- the pinned official verifier passed the exact archive and provenance;
- an equivalent `network=none` container failed only at the expected TUF refresh boundary;
- targeted v21 unit regression: `7 passed`;
- combined v20/v21 daemonless regression: `11 passed`;
- ordinary credential-free repository suite: `1011 passed`, `10 skipped`, `43 deselected`;
- OpenHands credential-free Python 3.12 suite: `262 passed`; strict mypy: `28 source files`;
- HWE credential-free suite: `37 passed`; strict mypy: `9 source files`;
- core strict mypy: `206 source files`; v21 scripts strict mypy: `2 source files`;
- documentation contracts: `2 passed`; exported schemas: no drift;
- Ruff lint/format over tracked Python and the three new Python files, plus `git diff --check`:
  passed;
- core wheel and sdist were each byte-identical across two builds; distribution content audit:
  passed;
- OpenHands wheel/sdist build and content audit in the frozen Python 3.12 environment: passed with
  zero issues. A separate isolated local build dependency bootstrap received HTTP 502 from the
  configured package-index proxy; the isolated GitHub Action remains the authoritative merge gate;
- changed implementation/config/governance scan: `6 files`, `119,251 bytes`, zero hard leaks and
  zero scanner errors; report hash
  `3eed996ffb4d1e467c3c17cfe3ab290ec97bc009033a1cfc2a915c7c0072bc6f`.

The remaining repository, integration, typing, documentation, packaging, reproducible-build, and
artifact-security checks are merge gates for this authorization. They are not candidate
qualification or agent-quality evidence.

## Explicitly not authorized

This authorization does not permit downloading or loading any frozen CVA6 candidate image,
running zero-model qualification, materializing a reserve split, making a provider call, starting
collection, SFT or GPU work, or accessing held-out tasks. Only after this authorization merges may
one new v21 no-candidate preflight run. Passing it would prove only the downloader controls and
would still require a separate candidate-transfer authorization.
