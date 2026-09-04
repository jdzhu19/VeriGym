# DeepSeek Harness v136 command-runtime diagnostic authorization

Date: 2026-09-04

Status: implementation authorization; execution is forbidden until this change is merged and the
post-merge `main` workflow passes all eight required job classes.

## Decision

Authorize one provider-free diagnostic of the v134 PR-465 `DockerRuntime.prepare()` failure under
the immutable identity `deepseek-harness-hwe-v136-command-runtime-diagnostic-v1`. This is not a
provider retry, task attempt, collection run, verifier run, or benchmark claim.

The v135 audit established that v134 stopped before the provider boundary with
`DockerImageError`, consumed the sole v132 volume reopen budget, and left all five scheduled tasks
provider-unconsumed. V136 therefore uses only fresh bind-backed Docker data and socket volumes at
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v136/`. It may not inspect, mount, relabel, reopen,
or mutate the v132 data volume.

## Frozen inputs and expected observation

- Manifest identity hash:
  `eb277948d452225f105185e2d919767e1369ede7e4c95f04a03a2e9809de0f3c`.
- Manifest file SHA-256:
  `5ce70387aec85f4a9cf75a72139e56574c46cbd1d59a9589fc086cc5e47bfc67`.
- Runner SHA-256:
  `07b2e63529fad93f3075c6d22694754d788a905f0820bb1ad0da43a3f033ce17`.
- V134 report hash:
  `7cb512ae8dd34f67c003289894112ee6ac79b413dbc949eb7ce16ba107ab4cf8`.
- V132 PR-465 command lock hash:
  `45054a863ca9c736441206fcf973fe2522071b8fda3beddb9e32158dc9a2c9fa`.
- V132 PR-465 security scan ID:
  `19da6e02194d1f22046e249b7582232be0c430d1ccd415556d92976849358f3e`.
- V132 PR-465 command image ID:
  `sha256:7de54938ca619ac008a2f1dbcaedb243d2beb08aecf44125889d0c06a5783d2c`.
- V135 audit merge: `da971e808b8da441d01ce7f76445fe6284939cd7`; its post-merge run
  `33856107497` passed all eight required job classes.

The runner first rematerializes only PR-465 from its completed local archive in a fresh VFS DinD.
Docker image creation metadata makes cross-build image IDs non-stable, so it does not pretend that
a fresh image ID or scan ID equals the historical v132 value. Instead it requires every immutable
task, source, toolchain, protocol, environment, tool hash, security, and execution-backend field in
the new v2-scanned lock to equal the v132 semantic baseline, excluding only the newly generated
image ID, scan ID, and lock hash. It transfers only the trusted workspace-runtime image from the
host; no archive produced by the transfer is persisted.

Using the exact v134 runtime configuration, the runner performs two preparation probes:

1. the v134 inherited-environment construction, expected to produce the allowlisted structured
   subreason `image_missing` because an unbound `DockerCliEngine` does not inherit `DOCKER_HOST`;
2. an otherwise identical runtime with `DockerCliEngine(docker_host=<fresh nested socket>)`, which
   must pass and leave no inner containers or volumes.

Only the allowlisted subreason and bounded booleans/counts may be retained. Raw exception messages,
exception details, container output, credentials, host image contents, and command output are
neither persisted nor hashed.

## Boundaries

- Exactly one v136 startup attempt and one probe of each transport construction are allowed.
- The outer DinD and all diagnostic containers use `network=none`; registry access is forbidden.
- `.partial` archives are forbidden; only the completed PR-465 archive and its locked sidecars may
  be read.
- Task execution, base/reference verification, Harness/controller startup, model startup, provider
  configuration, and provider requests are forbidden.
- `formal_collection_allowed`, `formal_collection_started`, `collection_started`,
  `training_started`, and `production_training_ready` remain false.
- Cleanup must validate exact v136 ownership, remove only v136 containers/volumes, and restore the
  fresh backing directories empty with the invoking non-root UID:GID and mode `0700`.
- The result requires an independent immutable v137 audit and another eight-class post-merge
  `main` gate before a repaired provider identity can be authorized.

Execution command after both gates:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V136_COMMAND_RUNTIME_DIAGNOSTIC=1 \
  python scripts/run_hwe_deepseek_harness_v136_command_runtime_diagnostic.py \
  --post-merge-main-run-id <v136-post-merge-main-run-id>
```
