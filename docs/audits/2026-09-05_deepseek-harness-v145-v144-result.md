# DeepSeek Harness v145 audit of the v144 command-probe control scaffold

Date: 2026-09-05

## Decision

The single authorized start of
`deepseek-harness-hwe-v144-command-probe-control-scaffold-v1` is consumed and stopped fail-closed.
The runner rejected the child environment at its outer execution boundary because provider
configuration environment names were still present. This happened before manifest loading,
output-root creation, Docker resource creation, local archive import, task materialization,
command-image probing, Harness initialization, or provider access.

No v144 report or partial evidence tree exists. No provider request, model process, task
execution, candidate modification, verifier run, trajectory, collection, or training started.
All five tasks remain provider-unconsumed. The planned
`deepseek-harness-hwe-v146-official-matrix-v1` identity is unreachable and is not authorized.

## Implementation and merge gates

- v144 implementation commit: `52b6974b7eb18a4a72f9d6318bd8f1cd891d26e3`
- v144 authorization merge/source commit: `f88d81d9e969f7389092c41355824685a9e9778a`
- v144 pull request: [#170](https://github.com/jdzhu19/VeriGym/pull/170)
- v144 branch-push run: `33909671879`, eight of eight jobs passed
- v144 pull-request run: `33909676197`, eight of eight jobs passed
- v144 post-merge `main` run: `33910123765`, eight of eight jobs passed
- v144 manifest file SHA-256:
  `6cb713dfd60e71bf565567259b4849e4b4a1de8754db269f8f5d6a4a12ea984f`
- v144 manifest canonical hash:
  `329ef1af435ecd1ce48a7d389b5f0b4d64bdd21bf6eca6a4cc0e1250d9ef322b`
- v144 runner SHA-256:
  `3f7552853685c13c24cdeed015d19e84d2d7392555b078cab0fde707f4f2306c`
- v144 authorization SHA-256:
  `abf0a3ffbdf0453f7552d7d2e5ca4c95e21e694be336adc06d7953ae83457275`

The source was the exact merged `main` commit after its green post-merge gate. Before the start,
an independent read-only preflight confirmed 35 TiB available on `/data2`, absence of every v144
path, volume, and container, exact presence of the three host image IDs, and absence of `.partial`
inputs for the fixed schedule. All five completed HWE archives passed SHA-256 sidecar, registry
digest lock, Docker archive manifest, image-config digest, and repository-base validation.

## Failure classification

The runner raised `ConfigurationError` with the fixed public category
`provider configuration environment` in `_require_execution_boundary`. The invocation removed
the common API key/token names listed in the v144 authorization command, but that list was not
equal to the complete fail-closed set enforced by the runner. In particular, the v69 boundary
also treats provider base-URL and VeriGym-specific DeepSeek names as provider configuration.

Only environment names were compared during this audit; their values were not printed, read into
evidence, persisted, or hashed. The rejection proves that the provider boundary was not crossed.
It does not consume any task or provider budget. Because the one-shot runner was started, however,
the v144 campaign identity itself is consumed and must never be retried.

## Resource disposition

After the failure, all four exact v144 filesystem roots remained absent:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v144`
- `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v144-control`
- `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v144-runtime`
- `/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v144-command-probe-control-scaffold-v1`

No `verigym-deepseek-harness-v144-*` Docker volume and no v144-labelled or v144-named container
exists. There is therefore no v144 data volume or evidence tree to open, freeze, clean, relabel,
or promote. The frozen v142 predecessor volume was not inspected or mutated.

## Successor boundary

V145 is only an independent result audit and authorizes no execution. A fresh provider-free
successor may use a new identity and fresh `/data2` resources, but its launcher must derive the
environment names to remove from the same complete frozen provider-boundary set that the runner
enforces. It must also prove before creating resources that the child environment contains none
of those names and none of `DOCKER_HOST` or `DOCKER_CONTEXT`. Provider values remain forbidden to
printing, persistence, or hashing.

The successor may otherwise repeat the byte-locked v144 behavior, including all five local
archive validations, official base-FAIL/reference-PASS checks, bounded v2 command-image scans,
and the explicit 300-second content-free command-image identity probe. It must use a new version
because v144 is consumed. Any official DeepSeek matrix moves to a later unused identity and
remains unreachable until the provider-free successor succeeds, its independent audit is merged,
and all eight post-merge `main` check classes pass.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
