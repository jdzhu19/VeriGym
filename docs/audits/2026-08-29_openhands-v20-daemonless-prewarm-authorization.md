# OpenHands v20 daemonless prewarm preflight authorization

## Decision

This preregistration authorizes one new no-candidate safety preflight under identity
`openhands-hwe-v20-daemonless-prewarm-preflight-v1`. It does not retry, mutate, or supersede the
sealed v19 result. The v19 predecessor remains `stopped_security_invalid` with progress hash
`57c67665465b1730a4457505741212d6d63da96f58d51eb6019d65b6056f4b29` and audit hash
`5a2c440cad385afd5e9bf4eb6f0abb4aa251690e8d6c3c1198c86cbe20984698`.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v20_daemonless_preflight_v1.json`; its authorization hash is
`1741352e5a2664191f594d975c798279e4bb19b4ef0c9f1815e2e2a6e17b9898`.

## Pinned supply-chain inputs

The preflight uses the official Google go-containerregistry `crane` v0.22.0 release:

- release page: `https://github.com/google/go-containerregistry/releases/tag/v0.22.0`
- installation documentation:
  `https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/README.md`
- Linux x86-64 archive: 16,075,919 bytes, SHA-256
  `edb74d53fad9a596860f59d1c5d04a43dfb5f441dc71f57060dd0bf39483c833`
- `checksums.txt`: 1,387 bytes, SHA-256
  `32cb629713e7a5d32274a218f76edef00113a4ff34593199449045d13e98be7a`
- `multiple.intoto.jsonl`: 25,735 bytes, SHA-256
  `0294f0af185efac8b6053d5793a7a5bae90d8b8f989892f363e5e9124667344c`
- reviewed bootstrap helper SHA-256:
  `c9f49649023b616f426dcddf22bf3390c6a9c4324ada2bb3368e50a15a220eed`

The bootstrap validates exact file hashes and sizes, requires the checksum list to contain the
registered archive hash, and requires a provenance payload subject for that archive, source
repository and release tag. It does not independently verify the DSSE signature; the exact GitHub
release digests and this reviewed authorization are therefore explicit trusted inputs.

The already-local container identities are:

- bootstrap: `python:3.11.9-slim-bookworm`, image ID
  `sha256:65a6ce634d975b67ee77c8d0f59248cbcb9d8b8f229d584c3cf5d624038bf963`,
  manifest `sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317`
- execution: `debian:bookworm-slim`, image ID
  `sha256:9fff73c337b947e6e3120b8ce929c92a7c5820228fda7c163145954c31cd32ba`,
  manifest `sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241`

## Effective-control contract

Before starting either container, the runner inspects and requires:

- `privileged=false`, no added capabilities or devices, cap-drop `ALL`
- non-root host UID/GID, read-only root, no-new-privileges
- private PID and IPC namespaces, bounded memory/swap, CPU, PIDs and `/tmp`
- no exposed or published ports and no Docker daemon process
- no Docker socket, host home, repository, task, verifier or credential mount
- exactly one scratch mount; writable only during bootstrap and read-only for `crane`
- exact digest-locked image, executable path, argv and environment
- `network=none` for the version check and `verigym-hwe-net` for bootstrap/digest lookup
- no proxy, provider, registry-auth or Docker configuration values
- verified removal of every temporary container

The network probe is only a digest lookup for
`docker.io/library/python:3.11.9-slim-bookworm`, frozen to manifest
`sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317`.
It is not an HWE candidate.

## Verification before authorization

The no-candidate preflight implementation passed the following local checks without starting the
preflight or downloading a candidate image:

- targeted v20 regression: `4 passed`
- context-aware and Docker security regression: `63 passed`
- OpenHands credential-free suite on Python 3.12: `262 passed`
- HWE credential-free suite: `37 passed`
- ordinary credential-free repository suite: `1004 passed`, `10 skipped`, `43 deselected`
- core strict mypy: `206 source files`; OpenHands strict mypy: `28 source files`; new preflight
  scripts: `2 source files`, all with no issues
- documentation contracts: `2 passed`; exported schemas: no drift
- Ruff lint/format and `git diff --check`: passed
- reproducible core build: wheel and sdist each byte-identical across two builds; distribution
  content audit passed with zero issues
- changed executable/config/documentation artifact scan: `6 files`, `112,863 bytes`, zero hard
  leaks and zero scanner errors; report hash
  `deddfc6f682a4e25d8cbc57095d6836761d753b08e8e5487ae58f8260ca4856b`

The committed eight GitHub Actions checks remain a merge gate. None of these checks is evidence of
candidate qualification, agent quality or benchmark performance.

## Explicitly not authorized

This PR and receipt do not authorize:

- downloading or loading any of the seven frozen CVA6 candidate images
- running zero-model qualification or materializing a reserve split
- creating a provider canary or making any provider call
- starting formal collection, SFT, GPU work or held-out evaluation
- modifying or retrying the sealed v19 experiment

Only after this PR merges may the no-candidate preflight run. Its report must pass independently and
record zero candidate images, zero qualification tasks, zero provider calls and complete cleanup.
Candidate transfer would require another reviewed authorization bound to that exact preflight
report; preflight success alone does not grant it.
