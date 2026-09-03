# DeepSeek Harness v88 audit of the v87 pre-provider stop

Date: 2026-09-03

Status: **safe zero-provider infrastructure stop; v87 and its data volume are frozen**. V87 ran
exactly once and may not be retried, resumed, reconstructed, or relabelled. The new `/data2`
backing and sidecar passed their capacity, identity, isolation, and readiness gates, but the first
Ibex image's cold VFS container start exceeded the HWE source-preparation control timeout. No task
qualification completed and no execution-scaffold contract was published. No provider episode,
model process, verifier result, trajectory, SFT candidate, formal collection, training, or
production-readiness work started.

## Authorization and invocation boundary

The v87 implementation and authorization were merged through PR #124 at exact clean tracked
`main` commit `65f0c22c6d1c3dfe3faed6146eef83a7f02506ce`. Post-merge `main` Actions run
`33755827780` passed all eight required job classes before the single invocation.

Before invocation, the fixed output, backing root, and both v87 volumes were absent. All twelve
recognized Anthropic, DeepSeek, OpenAI, and VeriGym provider variables plus `DOCKER_HOST` and
`DOCKER_CONTEXT` were removed from the child environment without printing, persisting, or hashing
their values. The outer sidecar used `network=none`; its inner bridge was disabled. The invocation
did not access a registry, accept a `.partial` archive, modify Docker daemon or VPN/proxy
configuration, prune Docker, touch `/data/docker`, reopen any historical DinD data root, or start,
stop, or reconfigure the user-owned downloader.

A post-stop scan compared every nonempty recognized provider value present in the parent shell
against all eleven persisted v87 files and found zero concrete-value hits. Values were neither
printed nor hashed during that check.

The v87 manifest file SHA-256 is
`a54d9c06dce3b1d3c0954cdcb1392685c5577179700f867ebbd4eb136a64220b`; its reproduced canonical
manifest hash is `39ed2ef554ab3d747d8573c012eca4a3fcd14b4280141963ca51e95247ef693d`.
The authorization document file SHA-256 is
`126491655bf2b95a97fcc97d6d37c05484dc1484422584e26d3409b957b4c1c8`, the materializer file
SHA-256 is `27556e44ac6399e4cd7de43f815d1addd2acc1849bd26577786dd9892d568ff9`, and the shared DinD
controller file SHA-256 is
`5cfcde10298db21b90cd6bf02deb6591af520aa9b0d1395a425c791e9881e925`.

## Capacity and fresh `/data2` identity

The content-free headroom preflight passed all four absolute byte and inode gates. The control
root had 9,404,375,040 free bytes. The exact v87 Docker backing, scratch root, and output parent
each observed 41,227,315,441,664 free bytes. The preflight file SHA-256 is
`10128a16f138ad244da44094158b49b37b7fa8d831f6f374c9b62e774d96d20d`; its reproduced canonical
hash is `bd889d74b8d5951dea2aa3daae0895903e69704fdfca436e98e54ac671a56645`.

The sidecar used the frozen Docker 23.0.6 image, VFS storage, runc, outer network `none`, no host
Docker socket, and no inner bridge. Independent host and sidecar `stat` calls observed identical
device/inode identity `64770:682230193` for exact backing
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v87/data` and inner `/var/lib/docker`. The retained
volume `verigym-deepseek-harness-v87-dind-data` is still an exact local-driver bind to that path,
with owner `rollout-controller-dind` and role `data`. It does not redirect task layers into the
host Docker root.

The physical open was atomically recorded as one immediately after the sidecar start and before
readiness. Readiness then succeeded; this stop is separate from the v85 readiness defect. The
runtime receipt file SHA-256 is
`366290a0ce2b55e43cc3121bb110bba680584f1753e95ff80d061bbb6f8b7b97`; its reproduced canonical
hash is `69c274a8c81931c2870199a426182c86218bf285b664c068ac146e1e441d938a`.

## Stop cause and task disposition

All five selected rows passed their source-commit and reference-patch metadata preflight.
PR-465's completed local archive then passed its SHA-256, OCI manifest/config, repository-base,
image-ID, registry-free, and non-partial checks. Its archive receipt file SHA-256 is
`21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516`; its reproduced canonical
hash is `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63`.

The locked PR-465 image was loaded into the fresh nested daemon. Source preparation next issued
the fixed networkless `/bin/cat /home/ibex_base_commit.txt` container command. The command did not
finish inside its existing 60-second subprocess bound, and the HWE preparation layer converted
the underlying `subprocess.TimeoutExpired` into `ConfigurationError("command timed out: docker")`.
The outer runner sealed the result and cleaned up. This is a bounded cold-VFS control-plane
infrastructure timeout, not a base/reference qualification, verifier, model, security, archive,
or capacity failure.

The final disposition is:

- `physical_data_volume_open_count=1`;
- `completed_task_ids=[]`, with no task receipt, source/image lock, qualification, command image,
  or security scan completed;
- `provider_calls=0` and `model_process_count=0`;
- `provider_execution_scaffold_published=false` and
  `provider_execution_authorized=false`;
- no `execution-scaffold-contract.json`; and
- all formal collection and training flags false.

V87 and its data volume have exhausted their only physical opening and are permanently frozen.
The conditional v89 provider successor never became eligible, was never authorized, and must not
open v87. A future attempt requires a new versioned zero-provider identity, a new exact volume and
backing, another full five-task materialization from the locked local archives, and a merged
authorization after extending only the affected Docker control timeout to a reviewed finite
bound. No old Docker data root may be read or copied to accelerate that successor.

## Atomic report and cleanup

`execution-scaffold-report.json` and `execution-scaffold-progress.json` are byte-identical. Each
has file SHA-256 `f9acd67b51561ff5c3fbf1d17569ea04d281fd3e4545370742a95f75ad3886bf`
and reproduced canonical report hash
`ea4a69158765b05cb5d18d52b87ec292986be3a21e8a1169c8c28b9ab92efdcd`. The sealed status is
`stopped_without_execution_scaffold`, the sanitized stop class is `ConfigurationError`, raw
exception text was not persisted, and cleanup is confirmed.

The outer sidecar and transient socket volume are absent. The socket backing is empty, mode
`0700`, and UID:GID `1004:100`. The networkless, read-only cleanup container returned zero with
empty bounded stdout/stderr, dropped all capabilities except `CHOWN`, `DAC_OVERRIDE`, and
`FOWNER`, and persisted no raw output. Its receipt file SHA-256 is
`5429b77c94f44a0de7b87b802965b2020f69d1aa0de7e22d7087c84cad5d6d50`; its reproduced canonical
hash is `afb7e716c40cd1d649fe420f519f04c1b41cbb25cedb69811663e65567659cdb`.

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v87-fresh-scaffold-successor-v1`.
V88 grants no provider execution, rematerialization, SFT import, formal collection, training, or
production authority.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.
