# OpenHands v32 Codex-free materialization stopped audit

## Outcome

The single authorized execution of
`openhands-hwe-v32-codex-free-canary-materialization-v1` stopped fail-closed while
security-scanning the first command image, PR-2330. It did not produce an image lock, security
scan receipt, command catalog, or successor canary contract. This identity and its image namespace
are frozen and must not be retried or admitted as evidence for a provider canary.

The terminal progress records zero provider calls, zero model processes, no canary execution, no
trajectory collection, no training, no inference evaluation, and no held-out task load. No
benchmark score is claimed and `production_training_ready` remains false.

## Authorization and repository gates

Authorization PR [#40](https://github.com/jdzhu19/VeriGym/pull/40) merged to `main` as
`075bfc814c0827a6985157e48950d0a0338e0502`. The materializer ran once from that exact clean
`HEAD == origin/main` commit after both GitHub Actions attempt-2 runs completed successfully:

- push run [33378763919](https://github.com/jdzhu19/VeriGym/actions/runs/33378763919);
- pull-request run
  [33378822484](https://github.com/jdzhu19/VeriGym/actions/runs/33378822484).

Each run passed all eight job classes: ordinary Python 3.11, 3.12, and 3.13; quality; package;
reproducible build; OpenHands Python 3.12; and Docker external-agent zero-model security. The only
annotations were GitHub's Node.js 20 action deprecation warnings. The authorization hash recorded
by the materializer is
`8e0f3a3057053679dd9781cd45bf663f0f7e0ad364e4e1e52f476ebb4f52c1e4`.

## Terminal evidence

The experiment root remains outside Git at:

`/data/jzhu484/Agent/experiments/openhands-hwe-v32-codex-free-canary-materialization-v1`

It contains exactly two files:

- `materialization-progress.json`, file SHA-256
  `27c48e0ff1a2905ba4a3f6f7e2ed1defe17c1746c4a7d01de97fd2ff869d0583`;
- `image-receipts/pr-2330.json`, file SHA-256
  `45fa97a18ed0c7b2e5e540f6d101e972ea928ec401a6ba8400effd0d7cdb5959`.

The terminal progress content hash is
`4d713ed9faa05104a9fcee28a559158d1af03e19915986aedbeacb9672e1942b`; recomputation after the
run matched the sealed value. Its status is `stopped_security_or_infrastructure_invalid`, its
failure task is `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330`, and its recorded failure
type is `CalledProcessError`. The lock map is empty.

The build receipt binds the unscanned PR-2330 artifacts to:

- sanitized candidate image ID
  `sha256:10ff15403de96b2db89e7c48167d0ea968ea8e83ed8be33cc06536ecd755869e`;
- intermediate unsanitized image ID
  `sha256:2368312010a59bcd548219cf1f1a69a4eaffa94a152dc787b04763d428090064`;
- verifier base image ID
  `sha256:bd04dfaa28bf30b408365e26b31bc829a2d3c729e3ea5321522289c583b1dcf9`;
- frozen ripgrep binary SHA-256
  `e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849`.

These image IDs are failure evidence only. The scan did not pass, so neither v32 tag is a locked
command image and neither may be used by a later campaign. The scanner removed its temporary
container; no v32 container remained after the stop. The two v32 image tags were retained so the
failed attempt remains inspectable and were not promoted into a lock.

## Evidence, finding, and execution path

### E-001

- title: Authorization checks passed before the only execution
- observed_at: 2026-08-31 20:08:24 +08:00
- source_type: command
- source_ref: GitHub Actions runs 33378763919 and 33378822484; PR #40
- content_hash: not applicable to remote run metadata
- repro_command: `gh pr checks 40 && gh pr view 40 --json state,mergedAt,mergeCommit`
- raw_excerpt: 16 duplicated push/PR job entries passed; merge state was `MERGED`

### E-002

- title: Terminal v32 progress is sealed and zero-provider
- observed_at: 2026-08-31 20:10:25 +08:00
- source_type: file
- source_ref: external experiment `materialization-progress.json`
- content_hash: `27c48e0ff1a2905ba4a3f6f7e2ed1defe17c1746c4a7d01de97fd2ff869d0583`
- repro_command: `sha256sum <v32-experiment-root>/materialization-progress.json`
- raw_excerpt: status is `stopped_security_or_infrastructure_invalid`; provider and model counts are 0

### E-003

- title: First command-image scan exited before a lock was written
- observed_at: 2026-08-31 20:10:25 +08:00
- source_type: log
- source_ref: materializer terminal traceback and the empty progress lock map
- content_hash: terminal output was not persisted by the runner
- repro_command: `find <v32-experiment-root> -maxdepth 3 -type f -printf '%P\n' | sort`
- raw_excerpt: `docker start --attach` returned exit status 1 for PR-2330

### E-004

- title: Host capacity was invalid at the failure boundary
- observed_at: 2026-08-31 20:15:00 +08:00
- source_type: command
- source_ref: local `df` and Docker daemon metadata
- content_hash: not applicable to live host state
- repro_command: `df -h / /data && docker info --format '{{.DockerRootDir}}'`
- raw_excerpt: `/` was 100% used; `/data` was 99% used; Docker root was `/data/docker`

### F-001

- title: v32 materialization is ineligible and permanently stopped
- severity: info
- category: design
- status: validated
- evidence_ids: E-001, E-002, E-003
- location: `scripts/materialize_cva6_openhands_v32_codex_free_canary.py`
- impact: no locked command images or successor canary contract exist, so no later stage may start
- confidence: high
- remediation: create a separately authorized successor identity; never retry or relabel v32

### F-002

- title: failure attribution is too coarse
- severity: low
- category: design
- status: validated
- evidence_ids: E-003, E-004
- location: `scripts/scan_and_lock_cva6_hwe_command_image.py`
- impact: the audit cannot separate Docker start failure from a failing inner security assertion
- confidence: high
- remediation: persist bounded, sanitized exit attribution before deleting the temporary container

### P-001

- title: Authorized execution to fail-closed stop
- path_type: callflow
- start: authorization commit on clean merged `main`
- goal: materialize six locked command images and a static canary contract
- steps:
  1. Both push and PR protection gates passed, and PR #40 merged — evidence: E-001.
  2. The only v32 invocation built and sanitized the PR-2330 image — evidence: E-002, E-003.
  3. The attached diagnostic exited 1 before its lock was written — evidence: E-003.
  4. The runner atomically sealed a zero-provider terminal stop — evidence: E-002.
- residual_risks: exact inner failure attribution is unavailable; host capacity must be corrected

## Failure boundary and diagnostic limitation

The image build and sanitization completed, and the scanner successfully created and inspected a
network-disabled, read-only, non-root container. `docker start --attach` then returned exit status
1. The scanner deletes the temporary container in its cleanup path. Its subprocess helper captures
stdout and stderr, but the v32 stop receipt currently persists only the exception class. Therefore
the sealed evidence cannot distinguish an engine-level start failure from a failing assertion in
the container diagnostic command. It would be incorrect to assign a narrower root cause.

The contemporaneous capacity snapshot also makes the host invalid for another attempt: `/` had
approximately 20 KiB free at 100% use, and `/data` was at 99% use with approximately 288 GiB free.
Docker reported its data root as `/data/docker`, so root-filesystem exhaustion is an infrastructure
warning but is not proof of the container's exit status. No files, images, caches, or Docker state
were deleted to change that environment.

## Disposition and required successor work

No provider canary, collection, SFT, or held-out phase is authorized after this stop. A successor
must use a fresh identity and a separate authorization PR. Before authorizing it, the repository
should add a zero-provider preflight that rejects unsafe filesystem headroom and should persist a
sanitized diagnostic command exit code plus bounded stdout/stderr hashes or assertion identifiers.
Regression coverage must prove that a failing container start or inner diagnostic assertion is
attributable without retaining the temporary container or exposing sensitive output.

The successor authorization must again pass all eight repository protection checks. Historical
v32 output, tags, and receipts remain frozen and must not be relabeled, imported, or retried.
