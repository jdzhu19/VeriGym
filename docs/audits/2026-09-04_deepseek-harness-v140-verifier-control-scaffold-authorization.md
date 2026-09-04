# DeepSeek Harness v140 verifier-control scaffold authorization

Date: 2026-09-04

## Decision

Authorize exactly one zero-provider execution of
`deepseek-harness-hwe-v140-verifier-control-scaffold-v1` after this implementation is merged and
the exact merge commit passes all eight post-merge `main` Actions classes. The successor rebuilds
the fixed PR-465, PR-1135, PR-1780, PR-2017, and PR-2711 scaffold in fresh bind-backed `/data2`
volumes. It does not reopen, inspect, copy, or mutate the frozen v138 data volume.

V140 is not a provider campaign. It cannot configure DeepSeek, start a model or Harness episode,
execute a candidate task, collect trajectories, start SFT training, or claim production readiness.
A successful atomic scaffold is evidence for an independent v141 result audit only. The identity
is consumed by its first authorized start and may not be retried after Docker startup or any task
archive read.

## Immutable implementation

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v140_verifier_control_scaffold_v1.json`
- Manifest file SHA-256:
  `6fa8856d49185893fe0dd67c38a4e0137451b80200c39a5af375908229c458b9`
- Manifest canonical hash:
  `ccd0e7927fde7d72ca0638bf5081b994d30a505e5e28c2ad869791f6ae1e236c`
- Runner:
  `scripts/materialize_hwe_deepseek_harness_v140_verifier_control_scaffold.py`
- Runner SHA-256:
  `b80d5bb043b00ecdda48e39fd5c5ee06effc9eaf68049f12db13dd4b077c273f`
- Required audit merge: `6837518e4014cd3431e3b6b40a42282c2fbbddc8`
- Required post-merge `main` run: `33866159895` (eight of eight jobs passed)

The exact v138 manifest, runner, authorization, terminal report, PR-465 import diagnostic, base and
reference verifier results, smoke report, cleanup receipt, and v139 audit are hash-bound. The
schedule, seed/sample `502/18`, completed local archive identities, task/source locks, official
verifier images, tool hashes, base-FAIL/reference-PASS predicates, and command-image scan policy
remain inherited from the audited path.

## Narrow verifier-control repair

V138 proved that PR-465 archive import and immutable image identity checks complete, then produced
the expected base verifier failure. Its reference verifier stopped on the previous 60-second
Docker control bound before a usable result. V140 changes only this infrastructure-control layer:
image inspection, cache-volume creation/removal, verifier-container creation/removal, and their
cleanup calls use a frozen maximum of 300 seconds.

The official verifier test execution retains its distinct 900-second timeout and unchanged task
script, image, candidate, pass/fail semantics, resource profile, and `network=none` isolation. Each
successful base and reference invocation must persist content-free metadata proving a completed
Docker control path, the 300-second control bound, the 900-second verifier bound, network
isolation, and successful container cleanup. Any timeout, missing metadata, cleanup failure, base
infrastructure error, or missing reference PASS stops the workflow and prevents an atomic scaffold
contract.

## Runtime and artifact boundary

Each completed local HWE tar is imported through the exact fresh v140 nested Unix socket. Registry
access and `.partial` archives are forbidden. Import diagnostics and verifier-control diagnostics
contain only allowlisted stages, status/category values, numeric bounds, cleanup booleans, and
self-hashes; they do not persist raw Docker/verifier output or hash nonempty output.

The outer DinD uses VFS and fresh bind-backed data/socket volumes under `/data2`. Task command and
official verifier containers remain `network=none`; command images remain task-specific,
credential-free, and Codex-free and must pass the existing v2 security scan. All five tasks must
complete before the atomic scaffold contract is published. Success retains only the exact v140
data volume for one independently audited and separately authorized v142 provider successor.
Failure freezes the exact owned v140 data volume for audit.

No broad Docker cleanup, Docker daemon restart, VPN/proxy change, downloader interaction, host
`LocalRuntime`, registry request, or v132/v138 volume access is authorized. Provider and Docker
ambient variables must be removed from the authorized child environment without printing,
persisting, or hashing their values.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
