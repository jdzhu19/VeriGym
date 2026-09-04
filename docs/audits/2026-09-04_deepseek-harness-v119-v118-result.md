# DeepSeek Harness v119 audit of the v118 explicit inner-inventory scaffold

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1` is consumed and failed closed
before the isolated DinD daemon started. No execution-scaffold contract was published, no task
was materialized, no Harness controller or model process started, and no provider request or call
occurred. This result is an infrastructure startup failure, not a benchmark-verifier rejection
and not evidence that the v118 inner-endpoint implementation passed its real scaffold canary.

Cleanup was not confirmed. The failed main sidecar and cleanup helper containers no longer exist,
but both v118 bind-backed Docker volumes remain registered. Their four backing/scratch directories
are empty; the socket backing was left `root:root` mode `0755` by the failed cleanup path. These
resources are frozen as v118 evidence and must not be reused, removed, repaired, imported, or
opened by a successor campaign.

Both migration conclusions remain false. There are no candidate trajectories or SFT tasks.

## Authorization and merge gates

- v116 audit merge: `7faf47a4ba49139bf9e93200e104b8b9e9cbfea2`
- v116 post-merge `main` run: `33815411217`, eight of eight jobs passed
- v118 implementation commit: `1ad79267ba1abe8c95134980405b40d1f24c7f4f`
- v118 authorization merge: `928b117882ae8be4c60520f8d4a49d82edc548b8`
- v118 post-merge `main` run: `33819300080`, eight of eight jobs passed
- v118 manifest file SHA-256:
  `71489c93e226c2f9b74d9e972f788e251b6c5604665c115debc1b7f69fd8f16c`
- v118 manifest canonical hash:
  `c646f65d13b19096cf46ed4a9e3ab24a79c94382cd1d1ea9ab36c36c667bf72d`
- v118 runner SHA-256:
  `83497b53e058786983c7e6d69b71b63bb498234ae1fc7b282e8aa0ec0ceaada4`
- v118 authorization SHA-256:
  `fc775c0fdbe00176a86ff153e37bb4f334c3b373e8509f0124900b396aac19a3`
- merged Docker engine SHA-256:
  `bc5fc27563fd87a6f814fee0c6598f50d6e86fe61cb42f3e29fd2d814ced2df1`
- merged campaign-model SHA-256:
  `6122d0c174f55f0159cbbe5a12a31904ec770331d1407e5a11d41251aabd5eed`
- v118 DeepSeek regression SHA-256:
  `526cb02d569c4ba8c3f11f852e5b9a912215f283312269a2c5822adc6aecf842`
- Docker-engine regression SHA-256:
  `d8683f994fe76f92fd61345e2d7d50e8f134aa9ec12ccb34b3bd082749b28b51`
- campaign-model regression SHA-256:
  `bd77b132ab261152b990e0f48f22bbcacbcd3af61cecee844d4c21fba168ce84`

The v118 authorization PR accumulated duplicate GitHub check suites after an API timeout. Every
suite that actually acquired runners passed all eight jobs; two initial zero-step infrastructure
failures were superseded, including one explicit attempt-2 rerun. At merge, PR #146 was
`MERGEABLE/CLEAN` with 48 successful, zero pending, and zero failing attached checks. The exact
post-merge run above independently passed all eight jobs before v118 was invoked.

## Frozen execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v118-explicit-inner-inventory-scaffold-v1`

It contains exactly 14 directories including the root, eight regular files, and zero symlinks.
The only files are the equal report/progress pair, the headroom receipt, and five patch-compatibility
receipts. There are no archive, source, image, qualification, security-scan, transfer, runtime
prepare, Harness initialize, final-inventory, cleanup, or scaffold-contract receipts.

- report and progress file SHA-256:
  `353874efff13292fd075e339dd05eec35d45747d0f9eac5057a7ac7fb0ec7565`
- report canonical hash:
  `6e40aa486c9949883cdfe5a253fb99eff5bb671de67d6ab687a2ba72d422fd0f`
- headroom receipt SHA-256:
  `1addbe9410d5bfc3365be3362769bc4ced8c96990a98c974e283ce9c9f627df6`
- headroom canonical hash:
  `6c9bf7a5abb99b74bbb194a3564bec145f34c8c79022084470cc3b0924b82694`

The equal report/progress pair records:

- `status=stopped_without_execution_scaffold`
- `stop_reason=RuntimeError`
- `completed_stages=[]`
- source commit `928b117882ae8be4c60520f8d4a49d82edc548b8`
- post-merge run `33819300080`
- `provider_execution_scaffold_published=false`
- `provider_execution_authorized=false`
- `provider_request_started=false`
- `provider_calls=0`
- `model_process_count=0`
- `dind_cleanup_confirmed=false`
- `dind_cleanup_receipt_hash=null`
- `raw_exception_persisted=false`

All five patch metadata receipts remain compatible and record no archive, Docker, or network
access before completion. The v118 headroom policy passed all four roles. At execution it observed
40,458,099,068,928 free bytes and 686,638,784 free inodes on `/data2`; therefore this failure is
not a headroom rejection.

## Startup and cleanup classification

The failing call was the inherited bounded `docker run --detach` for the outer privileged DinD
sidecar. Host Docker events show container
`90f584efa3a0fedb949e769d7f8b7318894501b9bb8588a3d49c740d1961959d` created and destroyed under
the generated name `verigym-dind-v94-ecd9f7ec3d3656f21e9e`, with no intervening start event. The
best-effort socket-cleanup helper
`eb31d7fbec305721053d6a4fdad6598dd498db9906ad5e0c4f91665506e3e350` was likewise created,
attached, and destroyed without producing a cleanup receipt. No v118-labeled container remains.

The original Docker stderr was intentionally discarded by the inherited security boundary, and
the current user cannot read the Docker service journal. Consequently, an OCI runtime, mount,
daemon-capacity, or other host-start subreason cannot be selected from existing evidence. It would
be incorrect to attribute this failure to the inner inventory or network code, which was never
reached, or to retry v118 merely to recover diagnostics.

The registered frozen volumes are:

- `verigym-deepseek-harness-v118-dind-data`, bind-backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v118/data`
- `verigym-deepseek-harness-v118-dind-socket`, bind-backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v118/socket`

Both retain the exact `rollout-controller-dind` owner and `data`/`socket` role labels. The data,
socket, control, and runtime directories each have zero direct children. The data, control, and
runtime directories remain owned by the campaign user at mode `0700`; the empty socket directory
is the cleanup exception described above. No deletion or repair is authorized by this audit.

## Provider and data boundary

The invocation explicitly removed all 12 forbidden provider environment names plus
`DOCKER_HOST` and `DOCKER_CONTEXT`, then set only the v118 opt-in variable. A post-run scan used
the four provider values present in the parent process without printing, persisting, or hashing
them: eight regular evidence files were scanned and zero matches were found. No provider marker
exists. No synthetic provider value was created because Harness initialization was never reached.

The user-owned downloader, VPN/proxy state, `.partial` files, `/data/docker`, and the unrelated
`/data/jzhu484/Agent/VeriGym` checkout were not changed. No registry access occurred.

## Successor boundary

V120 is retired unused because v118 did not publish a scaffold. After this audit is merged and the
resulting `main` commit passes all eight Actions classes, a new one-use zero-provider diagnostic
identity may be implemented as
`deepseek-harness-hwe-v121-bounded-dind-start-diagnostic-v1` with entirely fresh v121 paths and
volumes under `/data2`.

V121 may perform only the static predecessor checks, headroom check, host-image identity check,
fresh bind-volume setup, one bounded DinD startup attempt, bounded sanitized startup diagnostics,
and deterministic cleanup. It must not inspect or reuse v118 volumes or data, read task archives,
materialize command images, run base/reference verification, create Harness networks/controllers,
or contact a provider. Diagnostic output must be allowlisted, length-bounded, redact paths and
environment values, and classify the Docker phase without retaining raw stderr. Its cleanup logic
must handle a `docker run --rm` failure after container creation and independently restore/remove
the socket volume. A failed cleanup must remain visible and must not be reported as success.

Any later five-task scaffold requires a separate identity and an independent audit of v121.
Formal collection, SFT training, and production readiness remain closed throughout.

## Closed policy

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
