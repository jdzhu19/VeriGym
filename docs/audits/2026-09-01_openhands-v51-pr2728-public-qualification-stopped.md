# OpenHands v51 PR-2728 public qualification stopped

Date: 2026-09-01

Status: sealed infrastructure transfer failure; v51 may not be retried.

## Authorization and execution boundary

PR #83 merged the v51 zero-provider authorization as
`e9303c2beee2c8e856ae7109e47d4c9db78715b2`. Both push and pull-request Actions passed all eight
required job classes. Post-merge `main` Actions run `33517831377` then passed the same eight
classes. The frozen authorization hash was
`fe0be8fe67180851a2f507559822f2baf4c50939b9bc2487e0145e783520a8b3`.

The documented command ran once from that exact clean tracked `main`. Before execution, the output
and dedicated v51 scratch paths, PR-2728 host image, digest sentinel, and v51 temporary containers
were absent. Docker used `/data/docker`; the external preflight observed 319,137,611,776 available
bytes and 250,495,367 available inodes. The runner's immediately subsequent preflight observed
319,099,392,000 bytes and 250,495,362 inodes. The `verigym-hwe-net` user-defined bridge, official
dataset hash, tool cache, execution image, PR-2728 record identity, and content-free reference-patch
compatibility receipt all passed their frozen checks.

No provider endpoint or credential was required or inspected. No model process, provider call,
formal collection, training, GPU work, or held-out record decoding occurred.

## Exact stop boundary

The runner resolved the PR-2728 manifest and config, completed the network-none CA-bundle control,
and entered the bounded `candidate-pull` stage. The tarball grew continuously to approximately
1.9 GB before the controlled container exited 1. The sealed content-free failure diagnostic
records:

- failure stage and type: `candidate-pull` / `ConfigurationError`;
- create exit code: 0; controlled-command exit code: 1;
- stdout: 0 bytes with the empty SHA-256;
- stderr: 2,340 bytes with SHA-256
  `a63c466c66d1f604cbfc7d8ddcf5e142e62fcaf06ac7f1a4926dacd0d9985e0e`;
- effective container-control hash:
  `88d84598f9118df231b8ba3c39efaa93ddb7fc3d9f92fd3311d5f349391e6ff1`;
- terminal failure-diagnostic content hash:
  `caebce9c7f26c0ab1c5d99b1f91a7e6a1556d2453c4aa45b6c3c3d880412d24f`;
  and
- successful temporary-container and transfer-scratch cleanup.

The transfer produced no import receipt, source workspace, base/reference verifier outcome, or
qualified binding. PR-2728 therefore has no benchmark disposition from v51. The result is an
infrastructure stop, not a verifier rejection and not an ordinary task failure. The candidate and
sentinel images are absent, all v51 temporary containers are absent, and `outcomes` is empty.

The terminal state remains `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

## Upstream-informed diagnosis

The pinned tool is the SLSA-verified `crane` v0.22.0 binary with SHA-256
`771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94`. Its official
[`remote` options source](https://github.com/google/go-containerregistry/blob/v0.22.0/pkg/v1/remote/options.go)
retries a bounded set of temporary transport errors and HTTP statuses with three backoff steps.
An exit 1 after those library controls is still compatible with registry, transport, cache,
filesystem, or tar-writer failure; the exit code alone cannot distinguish them.

The official v0.22.0
[`crane pull` source](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/cmd/pull.go)
wraps the image in a caller-selected filesystem cache when `--cache_path` is set and then writes
the tarball. V51 placed that cache below its one-use transfer scratch and removed the entire
scratch after failure. Consequently, no content-addressed downloaded layers survived for a
separately authorized successor, despite the v51 progress field claiming a shared cache.

The known multi-layer tarball deadlock in v0.21.6 is not a matching explanation. It was fixed by
closing layer readers in
[`#2308`](https://github.com/google/go-containerregistry/pull/2308), and the fix shipped in the
official [`v0.21.7` release](https://github.com/google/go-containerregistry/releases/tag/v0.21.7),
which predates the pinned v0.22.0 binary. V51 also observed an explicit exit 1 rather than a
3600-second timeout.

The frozen runner retained only stderr byte count and digest, so this audit does not infer the raw
message. That privacy boundary prevented credential or proxy persistence, but it also prevented a
safe error-family classification. Source inspection additionally found an unreachable-on-v51
latent success-path defect: the candidate archive is unlinked twice after a successful image load.
It did not cause this stop, but a successor must remove the duplicate cleanup before execution.

A future identity should use a separately provisioned, immutable-location, content-addressed layer
cache with bounded inventory receipts; retain only an allowlisted and redacted error family; keep
raw stderr ephemeral; continue to require independent manifest/config/image-ID/tar validation;
and unlink each temporary archive exactly once. It must remain zero-provider and no-retry. This
audit does not authorize that identity, another registry transfer, a verifier attempt, command
image construction, canary execution, formal collection, or training.

## Frozen evidence and security accounting

The result is frozen outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v51-pr2728-public-qualification-v1`.
Its only file, `qualification-progress.json`, is 4,616 bytes with SHA-256
`66938109ed12db00a2cb4741330aeb4597ee7e720a2d28b225fe0ac1afd96542`. The canonical progress
hash is `3e26f8636288b38af210c76a72355558c1b8ed0deb3e7736d1240fbe5f0ea5ca` and recomputes exactly.

The context-aware security scan covered one file and 4,616 bytes. It passed with zero hard-secret
findings, zero scanner errors, zero symlinks, and report hash
`fe6786d3a422351bc86f19b11f8b2b157cbfa8490fbe3923d89603b78a896c81`. Proxy values were neither
persisted nor hashed.

No dataset row, task source, image, layer cache, tarball, verifier workspace, raw diagnostic,
credential, proxy value, full experiment output, or Docker layer is committed by this audit.
V51 is sealed and may not be rerun, reconstructed, relabelled, or used as qualification evidence.
