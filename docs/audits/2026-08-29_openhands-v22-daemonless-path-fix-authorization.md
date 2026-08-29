# OpenHands v22 daemonless verifier-path fix authorization

## Decision

This preregistration authorizes one new no-candidate preflight under identity
`openhands-hwe-v22-daemonless-prewarm-preflight-v1`. It preserves the sealed v21 status
`stopped_security_or_infrastructure_invalid`, report hash
`5134b3adbc8747691516041acb3ce87524ff221b7bbcc68c4a168dd3c9c3837e`, report-file SHA-256
`c0ad1a9755d9e5769d770b6784d257ba16e629b43e396dcc58104c6a10fc7748`, and audit commit
`62d07e94294dc9c4cb84658d7c2bef0a4765ca7d`. It does not retry, relabel, or import v21.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v22_daemonless_preflight_v1.json`; its authorization hash is
`6eebf2cce2283d27ae51d4286110ae5b720a092b14f8ff560f8e5cfbfc69d203`.

## Root cause and upstream reference

The v21 content-free stage receipt completed every public download, checksum check, and structural
Sigstore provenance check, then failed at `verify_slsa_signature` with `FileNotFoundError`, zero
stdout bytes, and zero stderr bytes. Static review found one deterministic process-launch error:
the helper supplied `slsa-verifier-linux-amd64` as an unqualified argv item zero while deliberately
restricting subprocess `PATH` to `/usr/bin:/bin`. Its working directory was `/download`, but that
directory was absent from `PATH`; the verifier therefore never started.

Python's official
[`subprocess` documentation](https://docs.python.org/3.11/library/subprocess.html) recommends a
fully qualified executable path for maximum reliability and documents that executable lookup is
affected by the supplied environment. v22 follows that guidance without adding a writable
directory to `PATH`: it resolves and validates the exact file
`/download/slsa-verifier-linux-amd64`, then uses that absolute path as argv item zero. This leaves
the restricted `PATH` unchanged.

The surrounding supply-chain design remains aligned with the producer's official
[`go-containerregistry` v0.22.0 release workflow](https://github.com/google/go-containerregistry/blob/v0.22.0/.github/workflows/release.yml),
which invokes `slsa-verifier` v2.7.1 for the release archives, and with the
[SLSA artifact-verification guidance](https://slsa.dev/spec/v1.2/verifying-artifacts). The fix is
limited to launching the already pinned and SHA-256-verified upstream verifier; it does not replace,
weaken, or approximate its cryptographic verification.

## Path and receipt contract

Before process creation, v22 requires all of the following:

- the registered download root resolves successfully;
- the requested verifier is either its registered basename or the exact registered absolute path;
- the resulting path is exactly `/download/slsa-verifier-linux-amd64` in the real preflight;
- the path is not a symlink and resolves to itself;
- the file is regular, executable, and has exactly one hard link.

The helper invokes the verifier with that fully qualified path, keeps `cwd=/download`, and retains
the restricted `PATH=/usr/bin:/bin`. Both the atomic progress file and successful bootstrap receipt
bind `slsa_verifier_executable_path=/download/slsa-verifier-linux-amd64`; the outer runner rejects a
missing or different value. A regression executes a temporary verifier while its directory is
absent from `PATH`, proving that process creation depends on the resolved absolute path.

The v21 diagnostic contract is retained: stage, failure class, exit code, bounded output byte
counts, stderr-presence bit, effective-control hash, and verified cleanup state are persisted, but
output bodies and exception messages are not. This makes a repeated failure attributable without
loading a task, invoking a provider, or manually recovering deleted container state.

## Frozen inputs and isolation

v22 retains v21's exact crane v0.22.0 archive, checksum list, Sigstore provenance, official
`slsa-verifier` v2.7.1 binary, source and builder bindings, digest-locked bootstrap and execution
images, registered non-candidate digest probe, and dedicated `verigym-hwe-net` use. The reviewed
v22 bootstrap helper SHA-256 is
`e40169628f22edda5f1070baa120e70746fe11f92ae769a8853a6dbc85fe82d9`.

Containers remain non-root with read-only roots, cap-drop `ALL`, no-new-privileges, private IPC/PID
namespaces, bounded resources and `/tmp`, no ports, no Docker socket or daemon, and one narrow
scratch mount. Bootstrap and the registered public digest probe alone use `verigym-hwe-net`;
`crane version` uses `network=none`. No registry credential, provider credential, proxy value,
candidate source, hidden verifier, or held-out identifier is supplied.

## Verification before authorization

- v22 targeted regression: `8 passed`; combined v20/v21/v22 daemonless regressions: `19 passed`;
- the v22 regression covers restricted-`PATH` absolute execution and receipt binding;
- ordinary credential-free repository suite: `1019 passed`, `1 skipped`, `52 deselected`;
- OpenHands credential-free Python 3.12 suite: `262 passed`; strict mypy: `28 source files`;
- HWE credential-free suite: `37 passed`; strict mypy: `9 source files`;
- core strict mypy: `206 source files`; v22 scripts strict mypy: `2 source files`;
- documentation contracts: `2 passed`; exported schemas: no drift;
- Ruff lint/format over all tracked Python and the three new Python files, plus
  `git diff --check`: passed;
- core wheel and sdist were each byte-identical across two builds; distribution content audit:
  passed;
- changed implementation/config/security scan: `6 files`, `142,766 bytes`, zero hard leaks and
  zero scanner errors; report hash
  `4fd012499bf33934e96a9378e1c64ef4d0700ce048728a911330bf976d978602`.

The frozen OpenHands Python 3.12 environment passed its tests and typing checks. A separate isolated
local plugin build could not bootstrap `setuptools>=77,<81` because the configured package-index
proxy returned HTTP 502; it did not reach package compilation. The isolated OpenHands package job
in GitHub Actions remains the authoritative build and content-audit gate.

These checks establish the implementation and authorization boundary only. They are not candidate
qualification, agent-quality evidence, or a benchmark result. The remaining repository,
integration, Docker-security, packaging, and reproducible-build Actions are merge gates for this
authorization.

## Explicitly not authorized

This authorization does not permit downloading or loading any frozen CVA6 candidate image,
running zero-model qualification, materializing a reserve split, making a provider call, starting
collection, SFT or GPU work, or accessing held-out tasks. Only after this authorization merges may
one new v22 no-candidate preflight run. It may not be retried under the v22 identity. Passing it
would prove only the downloader and verifier-launch controls and would still require a separate
candidate-transfer authorization.
