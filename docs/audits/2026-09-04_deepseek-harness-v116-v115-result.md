# DeepSeek Harness v116 audit of the v115 explicit nested-Docker-socket scaffold

Date: 2026-09-04

## Decision

The one authorized
`deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1` execution is validly
closed as a provider-free runtime-inventory rejection. V115 fixed the v112 daemon-selection
defect: all five tasks were freshly materialized, the first inner-only command image was found,
and its first `DockerRuntime.prepare` returned successfully through the explicit inner Unix
socket. The immediately following resource-inventory check failed because a legacy outer-daemon
helper inherited that inner `DOCKER_HOST` and attempted to locate the outer DinD sidecar from the
inner daemon.

V115 and all of its evidence, retained data volume, and runtime paths are frozen and must not be
retried, reopened, edited, imported, removed, or promoted. The reserved v117 provider identity is
retired unused. No provider execution is authorized.

## Authorization identity

- v115 authorization merge: `48bc47f0dbb020e41f330bf5350bad621d01df1c`
- v115 post-merge `main` run: `33812788683`, all eight required check classes passed
- v115 manifest file SHA-256:
  `43be1d12d329f35539b1bdc51bc12472fa7357619c7e0ff26859b3d41ce4db6b`
- v115 manifest canonical hash:
  `d851e4c0b2831865161f5ada6bf217d1df115dde03303925fece17e63fd4202c`
- v115 runner SHA-256:
  `9243002e66e70d2f3b08300afc7bf095a4a99775ced9b38c8294b73df4bd662f`
- v115 authorization document SHA-256:
  `a2cea407dfdeea77e1516625f9254216a850a0d173152f2f5f2fb4a047ef8539`
- core Docker engine source SHA-256:
  `cd2fb4a995e24450fc4a07851c6e5fa8734479dc477c5b15fe60aa4fd8645840`
- Harness process source SHA-256:
  `24174f7a0314fdac0cf4e133a342127920ec1b815dfdb90677a0461bf195d046`
- source commit recorded by the result:
  `48bc47f0dbb020e41f330bf5350bad621d01df1c`
- audited predecessor: v113 merge
  `9f79f54725c365bd0ab9ba9389f2ac421db1b155`, post-merge run `33810326256`

The v115 authorization PR's push and pull-request workflows each passed all eight jobs before
merge. The post-merge `main` workflow also passed all eight jobs before the single v115
invocation.

## Result integrity

The frozen result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v115-explicit-nested-docker-socket-scaffold-v1`.
It contains exactly 1,780 directories, 10,477 regular files, and no symbolic links. The report
and progress records are byte-identical and carry the same canonical report hash. No raw
exception or provider value is persisted.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `execution-scaffold-report.json` | `3b321bf23f29184bdff7ecf8ce6803fefa100a11ed4a7463695d9bbcd3709af3` | `2116016b0b27d1ad4993a0694609194e2edc7ca7a39043e823e06c0d35b6e168` |
| `execution-scaffold-progress.json` | `3b321bf23f29184bdff7ecf8ce6803fefa100a11ed4a7463695d9bbcd3709af3` | `2116016b0b27d1ad4993a0694609194e2edc7ca7a39043e823e06c0d35b6e168` |
| `headroom-preflight.json` | `c405ad4a462a3dfd4ff6d40ff8a26ed8763a30b821ba03b973f43080cc09311f` | `6434466d8e9a7b577764d0c152a80a6e88714de85aea5b712fa3052c28845abc` |
| `task-materialization-set.json` | `080b7ce11cf12cbc2794c17492e5f7c83cc3b6e10fdccd97e4d615090c3d1225` | `f62e8cfd4eb6a3b47464b49a940aab899a24c7ffa78f61fe0d8e5e36f9aa6f87` |
| `execution-inventory.json` | `4ea4f9b8a161189e4cc43f239102f085026fddebc23bb58f48b4654f75d7ed68` | `9ffb163a8befd467aa30a0d3f68e2221ea6adad4f7dacc803edbf2e4e9e2ce78` |
| `dind-runtime-receipt.json` | `5aa8a98c883ba3f3d9f0beafb79964f18d5e8acf1f9d04973956fe7a8ee32ed7` | `500f3cb1c72e8edee916f6497db2420d6e395ef938c02b11d49373cd7dea1383` |
| `image-transfer-set.json` | `f028f1d4c42d1a2743066f65c2981fe534eb5553d42c776a10378286bc9b8cbf` | `3d3df5505f09f4397cbd92acab9a079a1992e28da797d76932c531df91d0163b` |
| `dind-cleanup-receipt.json` | `7650b20ba3c9b6e841eeec37da88a986d885e5cbaa7940171b83a3f69e862172` | `2719c619e8a41fb75b13d88d6fcba9721983609dd0974e16fc6ace382daa9abb` |

The report records status `stopped_without_execution_scaffold`, stop reason `RuntimeError`,
completed stages `controller_and_workspace_runtime_transferred` and
`five_task_offline_materialization`, `provider_execution_authorized=false`,
`provider_execution_scaffold_published=false`, `provider_request_started=false`, zero provider
calls, zero model processes, cleanup confirmed, no persisted raw exception, and all formal and
training flags false. No runtime-prepare receipt, Harness-initialize receipt, final inventory, or
execution contract exists.

The command explicitly unset all 12 provider-related environment variables. A post-run in-memory
comparison of the four live nonempty parent-process provider values against all 10,477 evidence
files found zero matches. No `provider-request-started-v1.json` exists. The values were not
printed, persisted, or hashed.

## Headroom and five-task materialization

The unchanged headroom policy passed against the real v115 control directory on `/data2` with
`system_root_headroom_required=false` and `thresholds_changed=false`. The first inner inventory
passed with exactly 12 required identities, five fresh lock-derived command images, 17 observed
images, and empty container and volume inventories.

All five primary tasks completed in fixed order from completed local archives. Every receipt has
`base_failed=true`, `base_infrastructure_error=false`, `reference_passed=true`, command and
verifier networks `none`, zero provider/model activity, and a passing v2 security scan.

| Task | Fresh command image | Lock hash | Security scan ID |
| --- | --- | --- | --- |
| Ibex PR-465 | `sha256:a99d74f8057cb1cdc31981d65c3ae9808959802f1c6653398d4cd575795889ac` | `9865e7a6e766f44802de9cbf4929b40e283fb40e46153ab4931cf4125da5ff07` | `5b3b794631dbb4e93ed27c5bf135e7d847107577a06ffbb04ab7e7b83b7c52b5` |
| Ibex PR-1135 | `sha256:9a26021c90b55c7d179b7ecec8b2a1499a4135c4a8ed31c2e59eb41ce8a8d9aa` | `9578e3ba96eddebbe5a4f39443ba5fc0e551c1f83699336cb493e0320015f9b9` | `562776474f52a5ded8ff8b7bf5a80303693c19684bdd9489903d4c40189bc02b` |
| Ibex PR-1780 | `sha256:d634ef837643a2b667292f285e85c8ee5c41f075ea6d31a6a8ccde5706e553d6` | `169b2710b5ebd21a2a190d9f85f1a44e8067303267046afea5324d04c678d814` | `0cb2f442dd7e97fa26c28332e4ae7da3466728177f26634c5b8c5191e8c75366` |
| CVA6 PR-2017 | `sha256:841fdfdc8befc8e53ca947d31e89358bc5832826dbe597d9114c5e585f9ac857` | `0b12a96dbc19de1874b5595b56e0abe963c42af571b460a0052c83a7b100a4c3` | `8991cb48478c29af8fdce2b36faede7516aa453115ed76cd84d5911742ac53f0` |
| CVA6 PR-2711 | `sha256:503583b4401582c4f79dcbe89b437d92f8ac18a80ea294fac6038466a4d36f6e` | `ef2c86f1751b28a71883b24d765920a7d7ca33ab9094177d3e3d523ba203fa00` | `9a61d333dccbf979620538629e6c263243d9cd4510ddcb76e62e82aa605e52f1` |

## Runtime-inventory root cause

The runtime preflight constructed `DockerCliEngine` with the exact validated endpoint
`unix:///data2/jiadongzhu/docker/deepseek-harness-hwe-v115/socket/docker.sock`. The PR-465 fresh
image existed only on that inner daemon. `DockerRuntime.prepare` returned, proving that the v112
host-daemon image lookup defect was repaired.

Immediately afterwards, `_runtime_prepare_preflight` called the inherited
`dind._require_empty_inner_inventory(dind_name)`. That legacy helper implements each check as
`docker exec <outer-dind-name> docker ...`. It is intended to run against the default host Docker
daemon, which owns the outer sidecar. The call occurred before leaving `_nested_runtime`, so its
unsanitized subprocess inherited the inner `DOCKER_HOST`. It therefore asked the inner daemon to
execute into an outer-sidecar name that cannot exist in the inner daemon. Both inventory commands
returned nonzero and the helper raised `RuntimeError: DinD resource inventory is unavailable`.

This is a transport-direction error, not a stale-resource finding, image failure, task failure,
provider failure, or capacity failure. The failure happened after the explicit runtime prepare and
before internal-network creation or Harness initialization.

The audit also identifies a latent completeness gap: `DockerCliEngine.start_attach_streaming`
constructs its own sanitized environment and does not yet reuse the explicit `docker_host`. V115
did not invoke that path, but a successor must make the binding uniform across every Docker CLI
launch before authorizing a provider matrix.

## Docker and cleanup boundary

The outer DinD sidecar and all temporary task/runtime containers were removed. The v115 socket
volume was removed, and its backing directory was restored to the user with mode `0700` and empty
contents. The v115 control and runtime directories are empty. The v115 data volume remains as
frozen evidence under `/data2`; it must not be reopened or reused.

No registry or partial archive was used. No VPN/proxy setting, downloader, `/data/docker` task
layer, unrelated repository, or preexisting untracked file was modified.

## Repair boundary

After this audit is merged and the resulting `main` commit passes all eight Actions classes, a
new zero-provider successor may be implemented as
`deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1`, using entirely fresh v118
evidence, data, socket, control, and runtime paths under `/data2`.

V118 must retain every v115 and v112 gate. It must query all inner containers and volumes through
the already validated explicit inner endpoint, without trying to reach the outer DinD sidecar
from inside the nested scope. The `DockerCliEngine` explicit environment must be centralized and
used by ordinary invocations and streaming attach alike. Tests must distinguish host and inner
daemon ownership, prove exact endpoint use for all launch paths, prove empty and stale inventory
classification, retain omission for an unbound engine, and retain rejection of remote, relative,
symlink, or non-socket endpoints.

V118 is one-use and must freshly rematerialize all five tasks; it may not reuse the v115 data
volume or its derived images. A successful result requires an independent v119 audit before any
provider execution. Any later provider matrix must use a new v120 identity. V108, v111, v114,
and v117 remain retired.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks or trajectories. The
following remain false: `formal_collection_allowed`, `formal_collection_started`,
`collection_started`, `training_started`, and `production_training_ready`.
