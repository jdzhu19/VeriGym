# DeepSeek Harness v158 explicit-endpoint scaffold authorization

Date: 2026-09-05

Status: implementation authorization; execution is forbidden until this change is merged and the
post-merge `main` workflow passes all eight required job classes.

## Decision

Authorize exactly one provider-free, fresh five-task qualification under the immutable identity
`deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1`. This is not a provider run, task
attempt, trajectory collection, benchmark score, or SFT authorization.

V156 established that PR-465's locally imported verifier and derived command image pass when the
runtime owns an explicitly bound nested-Docker CLI engine. The corresponding unbound runtime used
the host daemon and returned `image_missing`. The independent v157 audit is merged at
`97cd9e2cd967f18627af209a1939e9fdbee2a346`, and post-merge `main` run `33959974205` passed all
eight required job classes.

## Frozen implementation and inputs

- Manifest canonical hash:
  `045c2d1f875438c8237602ece254ad6e3483b8739585efa004363e7a72084228`.
- Manifest file SHA-256:
  `3173df38fb75d2d45159a66760611834721423522046b1fcc7c8ef2e1dca87f4`.
- Runner SHA-256:
  `fc6a565dd465e9616a6041485bde1b87541fc138b10f86362cd1ad141fb8e489`.
- Launcher SHA-256:
  `fd3eafe632a63ada4225b901e5f6262e7dbb90f96f74037338493df9e750ff1c`.
- Docker runtime implementation SHA-256:
  `f3627bc187c6e98a833a0dbf17b12893478e0b07322ef6a2c5a05cd61d91a470`.
- Harness settings implementation SHA-256:
  `5e10762068073f0ebf2a57394f6fba3e89729a85a01ca1b6ffb4be5627efb6f4`.
- Harness agent implementation SHA-256:
  `45fbb74820bb1a123362d6c7309c40bdc43a584d2b61a482963767362de54372`.
- V156 report file SHA-256:
  `2582bcdf424763bbbccbd8ab1953ac51de0d35fa16e6751002c66bfea4cbc9ef`.
- V156 report canonical hash:
  `8f5a984f24b15c34eb3e8978ec91aa2c26af8a575058233e2c867777fe700a05`.

The schedule remains PR-465, PR-1135, PR-1780, PR-2017, and PR-2711 with seed/sample `502/18`.
Every completed local archive must again pass its SHA-256 sidecar, Docker manifest/config,
repository base, registry digest, source commit, and immutable image-ID checks. Each freshly built
command image must pass the bounded v2 security scan and remain credential-free, Codex-free, and
`network=none`.

## Transport qualification

The Docker runtime accepts either an injected engine or an explicit Docker endpoint, never both.
An endpoint-bound template creates a fresh `DockerCliEngine` for every `configure()` result. V158
uses the actual VeriGym service runtime registry and requires five distinct owned engines, so one
task's `close()` cannot invalidate a sibling task.

DeepSeek Harness settings accept only a canonical, existing, non-symlink local Unix socket. The
endpoint is included in the configuration fingerprint, used for controller-image inspection, and
forwarded by the v4 agent to the controller helper. V158 initializes the real Harness controller
with a synthetic non-routable provider configuration and requires no provider marker, events, run
interval, or retained synthetic value.

## Boundaries

- V158 creates only new bind-backed data and socket volumes under
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v158/`; retained v148 and v156 volumes may not be
  mounted, inspected, mutated, relabelled, or reopened.
- The launcher removes all twelve provider names plus `DOCKER_HOST` and `DOCKER_CONTEXT` before
  any output or Docker resource is created. It selects allowed names before reading values.
- Only completed archives are allowed. Registry access and `.partial` archives are forbidden.
- The outer DinD, all command-image scans, all task runtime probes, and all official verifier
  checks use `network=none`. The Harness initialize preflight uses only the already qualified
  controller image and the existing controlled `verigym-hwe-net` path.
- Raw Docker output, image contents, verifier logs, exceptions, credentials, and synthetic values
  are neither persisted nor hashed.
- Any partial materialization, verifier regression, unsafe endpoint, shared engine, cleanup issue,
  or evidence drift prevents atomic scaffold publication.
- A successful result remains pending an independent v159 audit and a later eight-class
  post-merge `main` gate. Only that audit may authorize a new v160 provider identity.

Execution command after merge and the v158 post-merge gate:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V158_EXPLICIT_ENDPOINT_SCAFFOLD=1 \
  python scripts/launch_hwe_deepseek_harness_v158_explicit_endpoint_scaffold.py \
  --post-merge-main-run-id <v158-post-merge-main-run-id>
```

The following values remain false throughout v158:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
