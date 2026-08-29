# OpenHands v25 streamed public qualification authorization

## Decision

This preregistration authorizes exactly one zero-model public qualification run under identity
`openhands-hwe-v25-streamed-public-qualification-v1`, and only after this authorization merges and
all repository checks pass. It binds the passed v24 preflight report hash
`71e315de5eda2fb7bd3bbc2fb4f6b38405b33a47a028bc22191eaa5f306a1b35`, report-file SHA-256
`569e9d62b71632d2e80cea09152e0cc6debb3085d18698fc00f0bb17e30949c0`, and audit commit
`3671d34ca16f87ee21ba51c37bbc1b454d826b76`.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v25_streamed_qualification_v1.json`; its authorization hash
is `8d4836d05cec9188b00330ee6074bcff247e733a7a8a2da2ca7f74151bb612be`. The reviewed runner
SHA-256 is `c233eb13aa7ecaa868b8756b386dea4662345000469e7636f46191219de33a8a`.

## Upstream-informed transfer repair

The stopped v19 stage used a privileged nested Docker daemon and attempted to prewarm every
candidate before any qualification. v25 removes both properties. The official HWE-Bench
[`images` documentation](https://github.com/pku-liang/hwe-bench/blob/10c78a87e1f92695d78d15b1464a6107dcac8837/docs/images.md)
confirms the public GHCR repository/tag convention and the local retag step. The pinned crane
[`pull` command](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_pull.md)
supports a local Docker-loadable tarball and a layer cache without running a daemon in the
networked container.

The go-containerregistry
[`tarball` documentation](https://github.com/google/go-containerregistry/blob/v0.22.0/pkg/v1/tarball/README.md)
also warns that registry digests are difficult to preserve through tarball round trips. Its pinned
[`MultiSave` source](https://github.com/google/go-containerregistry/blob/v0.22.0/pkg/crane/pull.go)
shows that a digest-qualified pull receives the fixed `i-was-a-digest` tag. v25 therefore does not
infer provenance from Docker `RepoDigests` after load. For each candidate it:

1. resolves the frozen public tag to one manifest digest;
2. fetches the exact raw config from that digest-qualified reference and hashes it;
3. pulls that same immutable reference to the bounded tarball with a run-local shared layer cache;
4. rejects duplicate, nonregular, escaping, oversized, or unexpected tar entries and requires the
   exact config name and generated digest-sentinel tag;
5. loads the tarball, requires the Docker image ID to equal the raw-config digest, applies the
   frozen candidate tag, removes the temporary sentinel tag and archive, and records a content-free
   transfer receipt;
6. passes the independently verified manifest/image binding into source preparation, where an
   exact selected-task mapping is required and simultaneous Docker pulls are forbidden.

The crane container remains non-root, non-privileged, read-only-root, cap-drop `ALL`,
no-new-privileges, private-PID/IPC, resource-bounded, port-free, and socket-free. It receives only
the exact read-only v24 public-tool cache and one writable transfer/cache scratch. Networked crane
commands use only `verigym-hwe-net`; source preparation and both verifier arms use `network=none`.
No registry credentials, proxy values, provider settings, hidden task IDs, task source, or reference
patch enter the transfer container.

## Efficiency and qualification gate

The candidate order remains PR-2330, 3226, 2844, 3231, 2989, 1482, and 3059, frozen by changed
lines then PR number. The official dataset SHA-256 is
`732c5dac910815c1c7ac72c8ccca88f66dbb7ed5d097806a5ddea611102f60f1`, revision
`1403afb57ce056c659c82b35e39c38c6a21ee635`, and source commit
`10c78a87e1f92695d78d15b1464a6107dcac8837`.

Unlike v19's bulk prewarm, v25 executes `transfer -> prepare -> base/reference smoke -> atomic
receipt` for one candidate before touching the next. The shared content-addressed crane layer cache
avoids re-downloading common layers. After every ordinary outcome the runner recomputes qualified
count plus remaining distinct capacity. It stops before another transfer when five tasks have
qualified, or when five can no longer be reached. An ordinary fail/pass mismatch advances to the
next candidate; infrastructure, security, identity, cleanup, or verifier-environment invalidity
stops immediately. No transfer or task is retried.

Five qualified tasks are assigned deterministically as the first three training reserves and the
last two validation reserves. Fewer than five authorizes no provider canary. Full sources, hidden
verifier payloads, patches, tarballs, caches, smoke outputs, and progress remain outside Git.

## Verification before authorization

- v25 runner regressions: `4 passed`; v19 plus v25 qualification regressions: `10 passed`;
- HWE credential-free suite: `39 passed`; strict mypy: `9 source files`;
- OpenHands Python 3.12 credential-free suite: `266 passed`; strict mypy baseline:
  `28 source files`;
- v25 runner strict Python 3.12 mypy: `1 source file`; scoped Ruff and format checks: passed;
- ordinary credential-free repository suite: `1035 passed`, `1 skipped`, `52 deselected`;
- the real networkless v25 control test revalidated the authorization, all eight v24 cache files,
  internal bootstrap receipts, exact CA check, exact crane version, dual-mount controls, cleanup,
  zero temporary containers, and zero candidate images;
- documentation contracts: `12 passed`, `2 deselected`;
- HWE and OpenHands wheel/sdist builds and package-content audits: passed; the first isolated build
  bootstrap received HTTP 502 from the configured package-index proxy, while the already-installed
  requirement-compatible backend produced and passed both scans;
- core wheel and sdist were byte-identical across two builds; distribution audit: passed;
- changed implementation/config/security scan: `8 files`, `170,810 bytes`, zero hard leaks and zero
  scanner errors; proxy values were neither persisted nor hashed; report hash
  `87695cb0a66aaf39e53a2e9e2b7562d3db57d26f605da7a9a5ab744956f85e2a`;
- GitHub Actions remain the authoritative stage guard.

These are infrastructure and contract checks, not task qualification or a benchmark result.

## Explicitly not authorized

This authorization permits candidate digest resolution, download, local load, source preparation,
and zero-model base-FAIL/reference-PASS qualification only. It does not permit provider calls,
agent-image construction, canary contract materialization, collection, SFT, GPU work, adapter
publication, or held-out access. The run must not start before this authorization merges. It may not
be retried. Any result requires a separate sanitized audit before a later stage can be authorized.
