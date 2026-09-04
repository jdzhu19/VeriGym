# DeepSeek Harness v143 audit of the v142 cleanup-control scaffold

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v142-cleanup-control-scaffold-v1` is consumed and stopped fail-closed. It
successfully imported and materialized all five fixed HWE tasks, established base-FAIL and
reference-PASS for each task, built and v2-scanned all five task-specific command images, and
completed the widened socket-cleanup controller. It then failed during the first DockerRuntime
command-image identity probe, before any runtime-preparation receipt, Harness initialization, or
atomic scaffold publication. The terminal status is `stopped_without_execution_scaffold`, the
stop reason is `DockerImageError`, and the report canonical hash is
`933394340f0965bb102191e2958aa228292d57417d4096b60f47a1e6901cb87c`.

No provider request, model process, candidate task execution, modification, trajectory,
collection, or training started. All five tasks remain provider-unconsumed. The planned
`deepseek-harness-hwe-v144-official-matrix-v1` identity is unreachable and is not authorized.

## Implementation and merge gates

- v142 implementation commit: `a1c62969f576720a4794f3693953d7667f13dcf6`
- v142 authorization merge/source commit: `398c3f7171e06b138942fac02ccc4f42eb2cdb43`
- v142 pull request: [#168](https://github.com/jdzhu19/VeriGym/pull/168)
- v142 branch-push run: `33898952368`, eight of eight jobs passed
- v142 pull-request run: `33898955089`, eight of eight jobs passed
- v142 post-merge `main` run: `33899362681`, eight of eight jobs passed
- v142 manifest file SHA-256:
  `0535dbabb1af93aa128504e3a728dfb7a1806d3960a471709689408a0a492230`
- v142 manifest canonical hash:
  `e092e4f943b51acffbd900c967d5732c616051491afed459aa11769813cc30ae`
- v142 runner SHA-256:
  `8f9435da7ec89a32470b930d65a3f58d3ba414d9879c6d2488705e8ed43aaca7`
- v142 authorization SHA-256:
  `299c38bf439e1dc8ee079cc73f6144950bbbc1483788b6c017009ecaaa9cec35`

The authorized child removed the available provider variable and all ambient Docker endpoint
variables before its single start. Its source was the exact merged `main` commit after the
post-merge gate.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v142-cleanup-control-scaffold-v1`

It contains 1,783 directories including the root, 10,488 regular files, and zero symlinks.
Structured evidence accounts for 17 mode-`0700` directories and 61 mode-`0600` files; the five
prepared public source trees account for 1,766 mode-`0755` directories and 10,427 mode-`0644`
files. All 41 top-level canonical self-hashes validate, including the byte-identical progress and
terminal report. An in-memory scan compared the one available nonempty provider value with every
evidence file without printing or hashing the value and found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `d22e73d4d17f6993b1f3d5a0fd3c888854e1299f1a915696937e295220c220fb` | `933394340f0965bb102191e2958aa228292d57417d4096b60f47a1e6901cb87c` |
| headroom preflight | `b30784a3fcfb2ef8f7bf1c64c5e28fba0e77f7e1da9d340550779ea14b2df579` | `23f4966a4382caff8eccc140ebd46056c58ce7f85549c7838a1731d92379b4d2` |
| DinD runtime | `57e5fb9cb62fb51fad93eeafa30f1904c63684ab9cf4a34ec22c58f16aa9d4ce` | `91b327a7d374fc6fe155789d5744812d51ba88f4eb855e7246dc8397e5cbff73` |
| image-transfer set | `3f9f5cbe3b956c274dcd497f0e0cc44a6414d262cef022b43027a09fa219aead` | `2505a035e32b771ab1d611a0db36544969f8f99645e35ee85d834651187f358b` |
| task-materialization set | `6b7797942b3c24fb0acf48dcc4eb5daed4afb48aebea6a2ca7ae5800a8cf1ae2` | `e8f72a5fac4ec03dfd8b9e18b0309e31563eec9542b6994308a61e2272301c63` |
| execution inventory | `bc5edc66366e8e4a2e12512d90e6d2757a8f6c238ce5a31c272b0e3f4395d317` | `46dc68b29014e75c9d71cc150e5cdfe39ab6ee0760153d2f6a31ab9a1d782a81` |
| cleanup receipt | `479a688d276508b4db0482f8c1edf57455d9fe7dd690031b45c1f1b2f106c303` | `45037006f3d2bc7e57802334bd3c07959b1ec7cec987423dbbd18608129279e6` |
| cleanup diagnostic | `640560c57b6299d2542cef1b1ad3ca82f69ef8a09cda82d67b512012c0dfc98a` | `3f2881810424bcc79e22a135597d91769a4458d66e2770ad6ef7c4e159bd013c` |

The terminal evidence records `provider_execution_authorized=false`,
`provider_execution_scaffold_published=false`, `provider_request_started=false`,
`provider_calls=0`, `model_process_count=0`, and no raw exception. Every predecessor-volume
inspection and mutation flag is false.

## Five-task qualification result

All five completed local HWE archives were SHA/digest checked, explicitly imported through the
fresh v142 nested Unix socket, and matched their frozen image identities. Registry access and
`.partial` inputs remained absent. Every official verifier ran with `network=none`, returned the
expected base failure and reference pass, used the separate 300-second Docker control bound and
unchanged 900-second verifier-test bound, and confirmed its container removal.

| Task | Base | Reference | Verifier-control diagnostic hash |
| --- | --- | --- | --- |
| Ibex PR-465 | FAIL | PASS | `32149dd5b7f2537c5525e8a01c6f8c23254c1d0c92ebc9c4155d571eeba59020` |
| Ibex PR-1135 | FAIL | PASS | `47584d2ba1261991a532f2d40ad9b128cf9504523e606ca7e8f710b9ed141d9c` |
| Ibex PR-1780 | FAIL | PASS | `af9b7fa91c6a2e1ac9a94439a60d55fd3eaf7ebceea21f0418a4b50169b81919` |
| CVA6 PR-2017 | FAIL | PASS | `a5cab0a976c601bc0ad83e7811a620286d7ce0e01a80b5d2a258ce3869bdd83e` |
| CVA6 PR-2711 | FAIL | PASS | `226a98e3f0729fce30f71e42b7085be673f98d8aeb45393b968c16d7dc682b4a` |

All five task-specific credential-free, Codex-free command images passed the bounded v2 scan and
produced fresh locks. The final inner inventory contained every required image and no container
or volume. This reconfirms that the local HWE archives, official verifier images, and v142
materialization route are not the current blocker.

## Runtime-probe failure classification

The report completed image transfer and five-task materialization, then recorded
`DockerImageError` before a runtime-preparation receipt existed. The observed public exception
location was the first command-image combined identity probe. The probe implementation has an
inherited hard maximum of 60 seconds even when the command runtime bound is larger. Its
`DockerImageError` can represent an engine error, timeout, OOM kill, output truncation, or nonzero
exit, but v142 intentionally persisted only the exception type and not the allowlisted probe
details. Therefore this audit does not claim that a timeout—or any other specific member of that
set—was proven.

The frozen v142 DinD data was not opened to recover logs or rerun the probe. A successor must use
fresh resources, persist only an allowlisted content-free probe classification, and place the
command-image identity probe under an explicit bounded control timeout. It may raise that control
timeout to at most 300 seconds without changing the probe script, expected image identity,
command-image runtime limits, or Harness behavior.

## Cleanup and resource disposition

The widened cleanup path passed on its first attempt. The exact owner-labelled cleanup helper ran
with `network=none`, exited zero under the 300-second controller wait, and left no raw output,
nonempty output hash, or raw exception. The exact socket volume was removed under the separate
300-second bound. The socket backing is empty, mode `0700`, and restored to UID 1004/GID 100; no
v142-labelled container remains.

Exactly one v142-labelled volume remains: `verigym-deepseek-harness-v142-dind-data`, role `data`,
with its bind device under `/data2`. It and the full result tree are frozen and must not be
reopened, inspected, mounted, mutated, retried, or promoted. Thus the v140 cleanup-control blocker
is fixed, while v142 remains an invalid atomic scaffold because runtime preparation did not
complete.

## Successor boundary

V142 must never be rerun. V143 is only an independent result audit and authorizes no execution. A
fresh provider-free successor may use the next unused identity and fresh bind-backed `/data2`
resources to repeat the atomic five-task scaffold with a content-free command-probe diagnostic
and an explicit maximum 300-second probe-control bound. Any probe ambiguity or other failure must
again stop fail-closed. The official DeepSeek matrix moves to a later unused identity and remains
unreachable until a complete successor is independently audited, merged, and followed by eight
green post-merge `main` check classes.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
