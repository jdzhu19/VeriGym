# DeepSeek Harness v82 audit of the v81 execution-scaffold stop

Date: 2026-09-03

Status: **safe pre-provider scaffold stop; v81 frozen without authorization**. V81 ran exactly
once and may not be retried, resumed, reopened, reused, reconstructed, or relabelled. All five
tasks completed their credential-free qualification, but the final controller-image identity
check rejected the offline transfer. No execution-scaffold contract was published. No provider
request, model process, formal collection, SFT export, training, or production-readiness work
started.

## Authorization and execution boundary

The v81 implementation was merged through PR #118 at exact clean tracked `main` commit
`2b10dd237de2427607d9405e93799be6c67d1489`. Its post-merge `main` Actions run
`33738477685` passed all eight required job classes before the single invocation.

The output root and both new v81 DinD backing paths did not exist before invocation. Recognized
DeepSeek, OpenAI, Anthropic, and VeriGym provider variables plus `DOCKER_HOST` and
`DOCKER_CONTEXT` were removed from the child environment without printing, persisting, or hashing
their values. The run did not change the host Docker daemon configuration, restart Docker, alter
VPN/proxy state, start or stop the user-owned image downloader, access a registry, use a
`.partial` archive, prune a cache, delete shared `/data/docker` content, or reopen a historical
DinD backing.

The v81 manifest file SHA-256 is
`ed73b55d704fd84b092001bee449252d48cf1c565a73e32ed4c9a8b84cee3e04`; its reproduced canonical
manifest hash is `810af9fcc4c53fd836940b526302a9008d795b9fa631ae764876ba040b4af621`.
The authorization document file SHA-256 is
`e74dcec697bc546419c441a71179627c899cbdedc11fa8b8cee84ff5e01b6498`, and the runner file
SHA-256 is `3e5151c7beccafdd76bda2d095c49272071233cb309cbfbb22dad3e3a8298e7f`.

## Capacity, isolation, and `/data2` binding

The content-free headroom gate passed. The v81 Docker backing was the exact new directory
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v81/data`. Independent host and sidecar `stat`
observations recorded the same device and inode identity, `64770:682230177`, for that directory
and inner `/var/lib/docker`. The runtime used VFS and runc, with outer network `none` and the
inner bridge disabled. Task and verifier containers also remained networkless.

The retained local volume `verigym-deepseek-harness-v81-dind-data` has labels
`verigym.owner=rollout-controller-dind` and `verigym.role=data`, with an exact bind device of the
v81 `/data2` path. Its host-visible mountpoint beneath `/data/docker/volumes` is only Docker's
volume descriptor; nested layers and writable VFS snapshots are stored on `/data2`.

- `headroom-preflight.json`: file SHA-256
  `9d98f6da23c9ce638bca344263c1118c324cd9ff1ac14d18ca279b3b060fe06e`; reproduced canonical
  hash `c2680d464ed259f7bf019165349aedc0e3f975c1752bdeff112e9ace674b30a1`.
- `dind-runtime-receipt.json`: file SHA-256
  `d212023604f2c7e2290a8a82fb0d94edd2ba9601208944315c7f83ca4b52e567`; reproduced canonical
  hash `5a3f1c25fcf38ba95d80638c18ceb1548f8267728f782485fc2a4686127f5076`.

## Five-task qualification result

All five task receipts independently reproduced their canonical hashes. Each task recorded a
compatible reference patch, a complete archive with valid SHA/config/manifest locks,
base-FAIL without an infrastructure error, reference-PASS, verifier and command networks `none`,
a task-specific v2-scanned command image, zero provider calls, and zero model processes. All
command-image scans passed with no detected secret. PR-2017 retained its task-specific runtime
base override; no other task acquired one.

| PR | Task receipt hash | Command image | Security scan ID |
| --- | --- | --- | --- |
| 465 | `59da9e9c1054a65988c82066d3ffae2db95f4909da81ed23303c66a6c773347c` | `sha256:a04015fa5a24df85791e3d53ed181b424af0ed225f1f98a754cdf06df8a26d85` | `f914c78936e2246201608657e26296b8673f67c49b48634b28cc0fdb8de1ddf3` |
| 1135 | `2f6e462b590c6206f29a5303252ed4f7f1e208d14a826720952d10777a63c7e7` | `sha256:d4ae35a9388b9aca6697700b9e69458bdb9b5188cac39c787c8c58f8705066a5` | `f736263613e5b2afbe9e1a95d2702a23a908b68a7a7f92bfd2b1eb3f727213f4` |
| 1780 | `1141d681b584e20a2604f03d376e808933bbb90f29db9ea3d3964fe191d0889e` | `sha256:ab98af64d5d34799c6caf2ef670c53001a1df63911e3a067d5a1cab99ddc1f96` | `a65506a635131e65219910401a48a7a20d5ae09a47563a38ed7321b9d1040e3a` |
| 2017 | `cf4bc06f6f78f0407895ba66213f1b0a3d985d3923d0e2c6e0acb5707e95ffc3` | `sha256:4c695ee158760d0c6b6158080003d7989f3c81e83ba5316bfceaac0d7c1766f5` | `52c45d6c2b6be3755fa179cad9e29d5c264f9bd7da6f706cea1e202cdbf1095c` |
| 2711 | `4d656ee98373a9009e561ddfa450d9e8e9e0920512253bf69af70687dde6afcd` | `sha256:e6dcea006aaee79e0ff8fce44271cdb2464cbbb1f5a50e1279593a48e20c51be` | `660c79fd70729ac11f594ae7a9a0c39a495d31b34bb89413ac9ed3c67e42f3fb` |

These successful qualifications do not make v81 an executable provider scaffold. Their images
and prepared sources remain evidence inside the frozen v81 backing only.

## Stop cause and fail-closed result

The host controller image was correctly verified before transfer as tag
`node:22.19.0-bookworm-slim`, image ID
`sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8`, and repository digest
`node@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90`.
V81 then called its read-only image pipe with the image ID. Docker's save archive preserved the
exact config/image ID but emitted `RepoTags: null`. Loading that archive into the fresh inner
daemon therefore produced the right image content without the required canonical repository tag.
The strict post-transfer check expected `RepoTags == ["node:22.19.0-bookworm-slim"]` and raised
`ConfigurationError`.

This is a pre-provider scaffold identity failure, not a verifier rejection or model failure. The
failure handler persisted no raw exception or transfer output. In particular:

- `status=stopped_without_execution_scaffold` and `stop_reason=ConfigurationError`;
- `provider_execution_scaffold_published=false` and `provider_execution_authorized=false`;
- `provider_calls=0` and `model_process_count=0`;
- no `controller-image-receipt.json` or `execution-scaffold-contract.json` exists; and
- report and progress are byte-identical, with file SHA-256
  `4063c492766135089f86eb3f2cbdc7f170b22bcebc92db903d73e0fc0dd6d807` and reproduced report
  hash `d1910a8446d4a5aab16a6903d216b5056af5ba0ae234db514e2b3764b691dc2f`.

A successor must use a new identity and fresh `/data2` backing. It may transfer this same fixed
controller image by its canonical tag, after verifying that the host tag resolves to the exact
image ID and repository digest. It must then verify the loaded image ID and canonical tag and bind
the transfer to the independently verified host repository digest. An offline `docker load` need
not recreate `RepoDigests`, so absence of that inner metadata cannot by itself replace or weaken
the source-provenance checks. Historical v81 code and evidence remain unchanged.

## Cleanup and frozen disposition

The fixed cleanup path completed successfully. The sidecar and transient socket volume are absent;
the socket backing is empty with mode `0700` and UID:GID `1004:100`. The cleanup receipt file
SHA-256 is `8fe2874f70b59ed198bed3d97e067165131abbec42961ddc85895b20945c11e7`;
its reproduced canonical hash is
`b3804a1f4a2cde339e77252e90480d37d4eeb2c940142d2a6b05e161d02c90d4`.

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v81-provider-execution-scaffold-v1`.
The persistent v81 data volume and backing are frozen audit evidence and must not be deleted,
pruned, reopened, or reused. V82 is an audit only and grants no execution authority. A successor
requires its own implementation, review, merge, eight-class post-merge `main` success, and
single-use invocation.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
