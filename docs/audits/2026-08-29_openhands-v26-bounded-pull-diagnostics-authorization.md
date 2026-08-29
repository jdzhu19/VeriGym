# OpenHands v26 bounded pull diagnostics authorization

## Decision

This preregistration authorizes exactly one zero-model public qualification run under the new
identity `openhands-hwe-v26-streamed-public-qualification-v1`, and only after this authorization
merges and all repository checks pass. It does not retry or rewrite the sealed v25 identity.

The predecessor is the audited v25 stop at commit
`ac9f9e77fa199bcc8e5df8bbfe1d334a1601839e`, with progress hash
`f3fa6795b0db0e7592dc168d9dd15d842f80945c1df06fa969b14a3642be916b`, report-file SHA-256
`90a7d04a3cb16863b366757584859dfb7ae96c52bccef316a02573ef58a22594`, and result-scan hash
`26febefa88a6942f9d7ff9463bbda9dfe35ab70828bea6e0220138a89320ff98`.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v26_streamed_qualification_v1.json`; its authorization hash
is `570ac67b7c348a943030bea2e415a0aecc63cda31fe95465a4e913230ab501b8`. The reviewed runner
SHA-256 is `1145aa6dd6d764b63cad73d8373ab4a0d12c001cd3f16b016581691f9b2bfd7f`.

## Upstream-informed repair

The pinned go-containerregistry v0.22.0
[`pull` command](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/cmd/pull.go)
defines no semantic stdout payload and returns after the tarball save succeeds. Its pinned
[`MultiSave` implementation](https://github.com/google/go-containerregistry/blob/v0.22.0/pkg/crane/pull.go)
delegates registry, cache, and tar writing to the underlying libraries and does not define empty
stderr as an image-integrity condition. Docker independently documents that
[`docker image load`](https://docs.docker.com/reference/cli/docker/image/load/) restores images and
tags from a tar archive.

v26 therefore requires the controlled pull to exit zero, stay within the existing stdout/stderr
byte limits, and emit no stdout. Bounded stderr is permitted, but its raw bytes are discarded. A
content-free receipt containing byte counts and stream SHA-256 values is atomically written to the
qualification progress before the output policy is applied. Nonempty stdout, an over-bound stream,
a nonzero exit, receipt-write failure, or malformed accounting remains fail closed.

Diagnostic acceptance cannot establish image identity. v26 retains the independently checked
digest-qualified reference, exact remote config hash, bounded regular-only tar inventory,
digest-sentinel tag, Docker-loaded image ID, frozen manifest binding, and source-preparation binding
from v25. The official HWE-Bench
[`images` documentation](https://github.com/pku-liang/hwe-bench/blob/10c78a87e1f92695d78d15b1464a6107dcac8837/docs/images.md)
remains the source for the public repository/tag and local-retag convention.

## Efficiency and stage boundary

Candidate order and the five-task gate are unchanged: PR-2330, 3226, 2844, 3231, 2989, 1482, and
3059. v26 transfers, imports, prepares, and zero-model qualifies one candidate before touching the
next. One run-local content-addressed layer cache reuses shared layers. The runner stops before
another download as soon as five tasks qualify or as soon as the remaining distinct capacity
cannot reach five. No command, image, or task is automatically retried.

The crane container remains non-root, non-privileged, read-only-root, cap-drop `ALL`,
no-new-privileges, private-PID/IPC, resource-bounded, port-free, credential-free, proxy-free, and
Docker-socket-free. Public transfer alone uses `verigym-hwe-net`; source preparation and both
verifier arms use `network=none`. The exact passed v24 tool cache, execution image, dataset hashes,
candidate inventory, and source commit remain frozen.

Five qualified tasks are assigned deterministically as three training reserves and two validation
reserves. Fewer than five authorizes no provider canary. Full sources, verifier payloads, patches,
tarballs, caches, smoke output, and progress remain outside Git.

## Verification before authorization

- v26 regressions: `6 passed`; v25 plus v26 regressions: `10 passed`;
- OpenHands Python 3.12 credential-free suite: `272 passed`; strict mypy: `28 source files`;
- HWE credential-free suite: `39 passed`; strict mypy: `9 source files`;
- v26 runner strict Python 3.12 mypy: `1 source file`; scoped Ruff and format checks: passed;
- ordinary credential-free repository suite: `1035 passed`, `1 skipped`, `52 deselected`;
- a real `network=none` v26 control test revalidated the authorization, dataset, all eight v24
  cache files, execution image, dedicated network, CA precheck, receipt hashes, scratch cleanup,
  zero temporary containers, and zero candidate images;
- OpenHands wheel/sdist build and package-content audit: passed;
- changed implementation/config/security scan: `5 files`, `138,161 bytes`, zero hard leaks and
  zero scanner errors; proxy values were neither persisted nor hashed; report hash
  `1cdc1b673618c4a90a8f0cf1a32622cc0f244588ea45dddb3648a907e5fc135c`;
- GitHub Actions remain the authoritative stage guard.

These are infrastructure and contract checks, not task qualification or a benchmark result.

## Explicitly not authorized

This authorization permits candidate digest resolution, download, local load, source preparation,
and zero-model base-FAIL/reference-PASS qualification only. It does not permit provider calls,
agent-image construction, canary contract materialization, collection, SFT, GPU work, adapter
publication, or held-out access. The run must not start before this authorization merges and may
not be retried. Any result requires a separate sanitized audit before a later stage is authorized.
