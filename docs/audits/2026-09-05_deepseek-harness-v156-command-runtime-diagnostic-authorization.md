# DeepSeek Harness v156 command-runtime diagnostic authorization

Date: 2026-09-05

Status: implementation authorization; execution is forbidden until this change is merged and the
post-merge `main` workflow passes all eight required job classes.

## Decision

Authorize one provider-free diagnostic of the v154 PR-465 `DockerRuntime.prepare()` failure under
the immutable identity `deepseek-harness-hwe-v156-command-runtime-diagnostic-v1`. This is not a
provider retry, task attempt, collection run, verifier run, or benchmark claim.

The v155 audit establishes that v154 stopped with `DockerImageError` before the provider boundary,
with marker `not_started`, zero calls and tokens, no task consumption, and complete cleanup. Its
single v148 data-volume reopen is consumed. V156 therefore uses only fresh bind-backed Docker data
and socket volumes under `/data2/jiadongzhu/docker/deepseek-harness-hwe-v156/`. It may not inspect,
mount, relabel, reopen, or mutate the retained v148 data volume.

## Frozen inputs and expected observation

- Manifest canonical hash:
  `c2ced9bc5a19e725b58ff3acc26db956459162c32b025c557c1c4644114c320e`.
- Manifest file SHA-256:
  `8cd2051aa91cbc9d36b84c505964c9e88000a61ff8a6b2e06101b3f28a4b42bc`.
- Runner SHA-256:
  `09606537c2ad63f7112ef9fad015e548305652301fee33328be3b06cea3d5faa`.
- Launcher SHA-256:
  `9c9d16626142900f2264b12cce4809ce11ee2be67c51a9779f2c2bd1695942cb`.
- V154 report hash:
  `7b58f36501fb19e22daa5c42746cfce6de2bc04d86771d0a28450b208d1c6aca`.
- V154 PR-465 attempt hash:
  `6c7e60969b194d5c1b969dff9c79513411570f872f5b58b46d01885c4c72b682`.
- V154 cleanup hash:
  `4d5ed5b20e02c8d0e0a8c99dcca3553c0e5ca9c24a19763b3000e0486d088cfe`.
- V148 PR-465 command lock hash:
  `b649954b3fe0dc207e873afe2237d970858537ff44d4bf703032fcfc677df609`.
- V148 PR-465 security scan ID:
  `e2051653ce256f046737c67a9a15b42605d7b401d610f93411383c87c7dbdc75`.
- V155 audit merge: `1cba9d58de2fe8bd4952e4494d96e0bd75edd3ae`; its post-merge run
  `33957607230` passed all eight required job classes.

The source comparison shows that the successful v148 runtime preparation instantiated
`DockerCliEngine(docker_host=<nested socket>)`, while v154 only set ambient `DOCKER_HOST` before
constructing an unbound `DockerRuntime`. The current Docker CLI transport deliberately does not
inherit ambient Docker endpoint variables. V156 tests this hypothesis instead of treating it as
an established result.

The runner rematerializes only PR-465 from its completed 473,571,328-byte local archive after
checking its SHA-256 sidecar, Docker archive manifest/config, registry digest lock, immutable image
config, and `/home/ibex` repository base. It transfers only the exact locked workspace-runtime
image from the host and persists no transfer archive. The rebuilt command image must be
semantically identical to the v148 lock except for its newly generated image ID, scan ID, and lock
hash, and must pass the bounded v2 security scan.

Using one identical runtime configuration, the diagnostic performs two preparation probes:

1. an unbound `DockerRuntime`, expected to retain the allowlisted subreason `image_missing` because
   its `DockerCliEngine` selects the local host daemon rather than the nested daemon;
2. a runtime injected with `DockerCliEngine(docker_host=<fresh nested socket>)`, which must pass and
   leave no inner containers or volumes.

Only the allowlisted subreason and bounded, content-free booleans/counts may be retained. Raw
exception messages, arbitrary exception details, task/container output, credentials, image
contents, and command output are neither persisted nor hashed.

## Boundaries

- Exactly one v156 startup attempt and one probe of each transport construction are allowed.
- The outer DinD and every diagnostic task or image-probe container use `network=none`; registry
  access is forbidden.
- `.partial` archives are forbidden; only the completed PR-465 archive and its immutable sidecars
  may be read.
- The launcher removes all twelve provider configuration names plus `DOCKER_HOST` and
  `DOCKER_CONTEXT` before the runner creates output or Docker resources.
- Task execution, base/reference verification, Harness/controller startup, model startup,
  provider requests, candidate generation, trajectory collection, and training are forbidden.
- Cleanup validates exact v156 ownership, removes only v156 containers and volumes, and restores
  the fresh data/socket backings and runtime scratch empty with the invoking non-root UID:GID and
  mode `0700`.
- The result requires an independent immutable v157 audit and another eight-class post-merge
  `main` gate before a replacement official matrix can be authorized.

The supply-chain controls bind all local inputs by SHA-256 and immutable Docker image ID, reject
registry or partial-archive fallback, preserve image/tool provenance, and require credential-free
static and runtime scans before the explicit transport diagnosis can pass.

Execution command after both gates:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V156_COMMAND_RUNTIME_DIAGNOSTIC=1 \
  python scripts/launch_hwe_deepseek_harness_v156_command_runtime_diagnostic.py \
  --post-merge-main-run-id <v156-post-merge-main-run-id>
```

The following values remain false throughout v156:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
