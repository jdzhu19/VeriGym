# DeepSeek Harness v113 audit of the v112 data2 control-headroom scaffold

Date: 2026-09-04

## Decision

The one authorized `deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1`
execution is validly closed as a provider-free runtime-preflight rejection. V112 fixed the
system-root headroom defect: its unchanged absolute byte and inode policy passed after measuring
the real, empty v112 control directory on `/data2`. It then completed all five offline task
materializations and the first fresh-image inventory. The following runtime preflight failed
closed because the core Docker CLI transport discarded the purpose-bound `DOCKER_HOST` and
inspected the host daemon instead of the inner DinD daemon.

V112 and all of its evidence, retained data volume, and runtime directories are frozen and must
not be retried, reopened, edited, imported, removed, or promoted. The conditionally reserved v114
provider identity is retired unused. No provider execution is authorized.

## Authorization identity

- v112 authorization merge: `96bbf99c5e358f2bf92cfd912ab92d6d10407ec6`
- v112 post-merge `main` run: `33807102983`, all eight required check classes passed
- manifest file SHA-256:
  `ef6584540478f2d615cfe0e738a46ed68e3c5051834183ee45ac5286753aead6`
- manifest canonical hash:
  `762db692017a7286aa97cf8d44311ed64c85fe39d5cc120f6b975acfb1802703`
- runner SHA-256:
  `c4653f2e141c0efcc21171e9e285643dd3cb28f5d52db6d4b5075cae6f16661f`
- authorization document SHA-256:
  `165ec17af1370acecb84517e4b8b67065c82bd41a3cce8b69fb4871a18af973f`
- source commit recorded by the result:
  `96bbf99c5e358f2bf92cfd912ab92d6d10407ec6`
- audited predecessor: v110 merge
  `557e11ffbca95175352e5221e2ee9d8c994588bf`, post-merge run `33804279053`

The v112 authorization PR's push and pull-request workflows each passed all eight jobs before
merge. The post-merge `main` workflow also passed all eight jobs before the single v112
invocation.

## Result integrity

The frozen result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v112-data2-control-headroom-scaffold-v1`.
It contains exactly 1,780 directories, 10,477 regular files, and no symbolic links. The report
and progress records are byte-identical and carry the same canonical report hash. No raw
exception or provider value is persisted.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `execution-scaffold-report.json` | `071a72151724979b93d21abc24a579195f751e6fbff8425c5b2aa8c19292d0fd` | `dd63f0945d93a29c2321d15f273a2f567504a2a954d78024212ad30ace3690d0` |
| `execution-scaffold-progress.json` | `071a72151724979b93d21abc24a579195f751e6fbff8425c5b2aa8c19292d0fd` | `dd63f0945d93a29c2321d15f273a2f567504a2a954d78024212ad30ace3690d0` |
| `headroom-preflight.json` | `52981cc85be7c4d1d02555c2285d4c469f512b0343ae2f981bed3c7548e012de` | `47f340552c57a3bc19ac1638550c2f89828ac7f6c8beefa7731bc8d896800f85` |
| `task-materialization-set.json` | `f67cc47c5923db05615950029058f1f4322f33ea4ce09eb1e7bdd73d58a2d980` | `38ee50df8a21f93ad9be59a0cc15300375b51879b39b82c9816895e22b907eb3` |
| `execution-inventory.json` | `0d28a97c3bd0f0e28387c65d42823219642fe1da77435d62ac1ab83e7e8e68ef` | `15ea70cd7fcfd83f21a4c533269664dfff854c1057723d67c395f4fb0a9b682b` |
| `dind-cleanup-receipt.json` | `9907c99be184fbbb5657042772b0e563383d0074fa6ccb37f46e8612c677c581` | `9e4d7233a9ce370c6fe1e9cfef43d826237d1a803e41d2f625fef039457b8619` |

The report records status `stopped_without_execution_scaffold`, stop reason `DockerImageError`,
completed stages `controller_and_workspace_runtime_transferred` and
`five_task_offline_materialization`, `provider_execution_authorized=false`,
`provider_execution_scaffold_published=false`, `provider_request_started=false`, zero provider
calls, zero model processes, cleanup confirmed, no persisted raw exception, and all formal and
training flags false. No runtime-prepare receipt, Harness-initialize receipt, final inventory, or
execution contract exists.

The command explicitly unset all 12 provider-related environment variables. A post-run in-memory
comparison of the four live nonempty parent-process provider values against all 10,477 evidence
files found zero matches; the values were not printed, persisted, or hashed.

## Headroom and data2 finding

The v112 headroom receipt passed and explicitly binds:

- inherited argument: `control_root=/`
- measured argument:
  `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v112-control`
- `system_root_headroom_required=false`
- `all_campaign_writable_roots_under_data2=true`
- `thresholds_changed=false`

All four roles passed the same fixed policy: 4 GiB and 100,000 inodes for control, 96 GiB and
250,000 inodes for bind-backed Docker data, 8 GiB and 50,000 inodes for scratch, and 2 GiB and
10,000 inodes for output. V112 therefore confirms that the chosen `/data2` scheme resolves the
capacity problem without sudo, Docker-root relocation, or deletion from `/data/docker`.

## Five-task materialization

All five primary tasks completed in fixed order from completed local archives. Every receipt has
`base_failed=true`, `base_infrastructure_error=false`, `reference_passed=true`, matching command
image lock and security-scan semantics, network-none verifier and command paths, and zero provider
or model activity. All five security scans passed every v2 check and detected no secrets.

| Task | Fresh command image | Lock hash | Security scan ID |
| --- | --- | --- | --- |
| Ibex PR-465 | `sha256:0239b2b25561eb2725ade61b5977847201b9200219b5a325c22e6b7b71229187` | `5121f698df469001c91b48241f2acb8960e7d83532f29b6bf1d9eb4074bcdd47` | `1d915d5ee92c9f7ed2406b447625255bdc1126310c9456fd0ad76f77948cfba0` |
| Ibex PR-1135 | `sha256:062eabe446499892946ab840e31232e27f26304b62e94ba57c5699c09a95ea93` | `d76051cd29974928e6ad56fb6de96ed3da24debe125a2deadd611b1119879a5b` | `06ec109900008a22d4fc8609f39a7d5931f5d0dd22bfb44d9b6ed70a3f59fb14` |
| Ibex PR-1780 | `sha256:5c8b6a3702c1e5f50ec69211925133e26c67282d163f523bbaccf0a72ded4025` | `ae67f68013b4b48f847f366b0f57acd64393a5389ab59272279e1ed757f4d05a` | `491a83d0df95c55903526cf782c9c7e269169fba24004bd411c211d0d0adcff1` |
| CVA6 PR-2017 | `sha256:92bc2064c0f7bfe62759f36d6225f22130df2ac08e4af4308f20623bcfa8652a` | `86680044891ef4bcac0bf9e88091e882b8546c6357b52f5a3739aa0367fa22ce` | `e0a7ec71ecdb695e07a694f2edddc84190f7b1580db01a99b7bfaa9491ac4d06` |
| CVA6 PR-2711 | `sha256:2d2ce45bde8898084e8053399a43c6bb105ad9e66e13d74cc505a63a39995e45` | `702339a1f56c436a873fc1f5442f3587332939ee74289f8aaa6a1531e92c61cd` | `30d44f857e9e6fcd745c5487e7ec22a3d06842fd5dd5dd5f3f2d27dafcfdedda` |

The first inner inventory passed with exactly 12 required identities, five fresh lock-derived
command images, and 17 total observed images. Historical command-image identities were not
required.

## Runtime-preflight root cause

The first runtime-preflight command image was the PR-465 fresh identity
`sha256:0239b2b25561eb2725ade61b5977847201b9200219b5a325c22e6b7b71229187`.
The immediately preceding inner inventory records it as present. The following `DockerRuntime`
reported it unavailable because `DockerCliEngine._invoke` constructs a three-variable environment
containing only `PATH`, `LANG`, and `LC_ALL`; it drops the `DOCKER_HOST` set by the audited
`_nested_runtime` context. Consequently its image inspection reached the host Docker daemon,
where that fresh inner-only image correctly does not exist.

The DeepSeek Harness helper uses a separate sanitized subprocess environment that also omits
`DOCKER_HOST`. Fixing only the runtime-preflight transport would therefore be insufficient: the
controller initialize check could still reach the host daemon. Any successor must explicitly and
safely bind the same local Unix socket through both sanitized control-plane transports and prove
that no arbitrary environment or remote Docker endpoint is admitted.

## Docker and cleanup boundary

The outer DinD sidecar and all temporary task containers were removed. The v112 socket volume was
removed, and its backing directory was restored to the user with mode `0700` and empty contents.
The v112 control and runtime directories are also empty. The v112 data volume remains as frozen
evidence under `/data2`; it must not be reopened or reused. A host network named
`verigym-hwe-net` predates v112, is non-internal, has no attached containers, and is not the inner
temporary network that v112 had not yet created.

No registry or partial archive was used. No VPN/proxy setting, downloader, `/data/docker` task
layer, unrelated repository, or preexisting untracked file was modified.

## Repair boundary

After this audit is merged and the resulting `main` commit passes all eight Actions classes, a
new zero-provider successor may be implemented as
`deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1`, using entirely fresh v115
evidence, data, socket, control, and runtime paths under `/data2`.

V115 must retain every v112 headroom, archive, OCI, source, task, security, inventory, cleanup,
and zero-provider gate. It must add a narrowly validated local Unix-socket transport binding for
both `DockerCliEngine` and the DeepSeek Harness helper. Tests must prove exact endpoint
propagation, omission when not explicitly bound, rejection of relative, non-Unix, symlink, or
non-socket endpoints, absence of arbitrary environment propagation, restoration after the scope,
runtime preparation against an inner-only image, and controller initialization against the same
inner daemon.

V115 is also one-use and must freshly rematerialize all five tasks; it may not reuse the v112 data
volume or its derived images. A successful result requires an independent v116 audit before any
provider execution. Any later provider matrix must use a new v117 identity. V108, v111, and v114
remain retired.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks or trajectories. The
following remain false: `formal_collection_allowed`, `formal_collection_started`,
`collection_started`, `training_started`, and `production_training_ready`.
