# OpenHands v49 PR-2916 canary materialization result

Date: 2026-09-01

Status: passed and sealed; zero-provider result awaiting merged audit.

## Authorization and execution

PR #79 merged the v49 authorization as
`402818e09bfa443e234d5969db7ab0b5f5af51d8`. Post-merge main Actions run
`33506771209` passed all eight required job classes. The frozen authorization hash is
`7a04e2dc24a4f380bc85223589a63ccf7619a2d76c9a8eb76b993985f5fb3010`; the authorization audit
file SHA-256 is `9cec036a55e0b0d58cb598017a6d7a147b3f419eaaabbd1a8c6d3fbee55a3577`.

The documented materialization command ran once from that exact clean tracked commit. The output
root did not exist before execution. The execution-time absolute headroom receipt observed:

| Role | Free bytes | Free inodes | Gate |
| --- | ---: | ---: | --- |
| control root | 9,464,803,328 | 18,505,852 | passed |
| Docker root | 321,292,288,000 | 250,516,738 | passed |
| scratch root | 321,292,288,000 | 250,516,738 | passed |
| output parent | 321,292,288,000 | 250,516,738 | passed |

The Docker root was `/data/docker`. The exact PR-2916 legacy lock, v33 PR-3204 validation lock,
v43/v44/v45/v48 evidence, repository runtime, ripgrep binary/archive, and required Docker images
were all revalidated before image construction. The headroom preflight hash is
`c5adefd9c75f2783b88237c8f5e84e04ddde7a973e4f1034966521a5d98a64ee`.

## Result

V49 built one new task-distinct PR-2916 command image:

- derived command image:
  `sha256:d4cfb7b812b59b29a9e0a0c58ef71006e4580b8708f50cf06d0ded650b6ce60e`;
- image lock hash:
  `e4db6b85a1bbbdcb9105f51ee23451822dfa7dcded6a64f768e50928d034d5e6`;
- image-lock file SHA-256:
  `dde4c79f0aae67977ed015b5e6c2fa4b360fd9ab560d57cc8e3010f5af2db152`;
- v2 security-scan ID:
  `ee2d910595397602d846e9b33d33fc09da38d023b0357c35c959fd3ac8f5f7bd`; and
- security-scan file SHA-256:
  `445c6cc272c206ae3814662e56b07584a5bb8720e8f45921548cf552e85314dd`.

The v2 scan passed. Build and runtime networks are `none`; Codex, provider credentials, hidden
assets, verifier payload, reference patch, and legacy source are absent. The diagnostic receipt
records zero exit codes, bounded streams, no persisted raw output, no hash of nonempty output, and
successful temporary container/workspace cleanup. No v49 container remains.

The static catalog and future contract bind PR-2916 training followed by the sealed v33 PR-3204
validation image, under protocol v22, seed 497, and sample 13. Their hashes are:

- catalog hash: `1439d400f87d4493d52fb3d2e6cc643c41f64811d2dac8d8340584e167a9f45a`;
- catalog file SHA-256:
  `f63626d2ac5cc29438989beb6c7bf791a1d6946c24f56289e5e5f09ea8e18cb7`;
- contract hash: `f0d80e3a9f2c8498f2024ff74e5de7a9b5062d676585cfb59936076c39e9b78a`;
  and
- contract file SHA-256:
  `06c2baf98bd4388f99132b373b560ec0fc8c34b755ced2509a414b4fd7991ffd`.

The final progress hash is
`9b3919834f40e8444354a137a9b1fe36ac72556205fe3d2fd428e040db14ae48`; its file SHA-256 is
`f5c4dad017fef9445ff9e0bb6b7a481bee0da9a0b157e54bb4fc31fc3d38458d`.

## Sealed evidence and independent security audit

The external result root is:

`/data/jzhu484/Agent/experiments/openhands-hwe-v49-pr2916-canary-materialization-v1`

It contains exactly seven regular files, no symlink, and no special entry. The complete tree hash
is `c773d0e6e7df8beaaee994a60e89e612b85a4d5ce070414df90692422696a9d0`.
The remaining file SHA-256 values are:

- headroom receipt:
  `222549d3d852f673f3173573b01c46c993f437094c71df292f00088a7e20a084`;
- image build receipt:
  `12cf74ece05f536517065783b72e9711c794fbcb47c6bd09d44b0f3fbf061daf`.

An independent context-aware scan covered all seven files and 18,655 bytes. It compared active
proxy/provider-sensitive values and all execution host roots only in memory. The scan passed with
zero hard-secret findings and zero scanner errors; it exported or hashed no suspected value and
found no persisted absolute execution path. The result tree, image layers, task source, provider
values, and benchmark assets remain external and are not committed.

## Accounting and successor boundary

V49 made zero provider calls, zero provider episodes, started zero model processes, and executed
zero benchmark tasks. It did not load a tokenizer, task source, hidden verifier, or held-out data.
It did not create a trajectory or claim a benchmark score. Final state is:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.

This sealed result may support only a separately reviewed v50 provider-canary authorization after
this audit merges and the post-merge main commit again passes all eight required job classes. V50
must bind this exact tree, lock, scan, catalog, and contract and retain the fixed PR-2916 then
PR-3204 order, seed 497, sample 13, six-plane admission, exact-64K/no-truncation, decision-only
mask, and zero-retry requirements. V49 itself does not authorize a provider call, canary execution,
formal collection, training, GPU work, or held-out loading.
