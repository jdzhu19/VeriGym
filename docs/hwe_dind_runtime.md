# Running HWE-Bench with an isolated nested Docker daemon

> **Warning:** this is an opt-in compatibility runtime. It starts one trusted Docker daemon
> sidecar with `--privileged`. Use it only on a controlled worker, never on a shared untrusted
> Docker host. The project controller and every benchmark container remain unprivileged.

The nested runtime lets VeriGym use a frozen Docker 23.0.6 daemon on platforms whose host daemon
cannot start an HWE-Bench image. The host daemon owns only the trusted sidecar and controller. The
nested daemon owns the short-lived benchmark sandboxes.

## Preparing the runtime

Resolve every image to an immutable local image ID. The DinD image must use the official
`dockerd-entrypoint.sh`; the launcher also verifies the inner server version, `vfs` storage driver,
`runc` default runtime, and socket group before it starts the controller.

Set `VERIGYM_CONTROLLER_IMAGE` and `VERIGYM_HWE_VERIFIER_IMAGE` to image references already
approved for the campaign. The commands fail immediately when either variable is absent.

```bash
: "${VERIGYM_CONTROLLER_IMAGE:?select an approved controller image}"
: "${VERIGYM_HWE_VERIFIER_IMAGE:?select the frozen HWE verifier image}"
controller_id=$(docker image inspect "$VERIGYM_CONTROLLER_IMAGE" --format '{{.Id}}')
dind_id=$(docker image inspect docker:23.0.6-dind --format '{{.Id}}')
verifier_id=$(docker image inspect "$VERIGYM_HWE_VERIFIER_IMAGE" --format '{{.Id}}')

docker volume create \
  --label verigym.owner=rollout-controller \
  --label verigym.role=source \
  verigym-rollout-source-v1
docker volume create \
  --label verigym.owner=rollout-controller \
  --label verigym.role=scratch \
  verigym-rollout-scratch-v1
docker volume create \
  --label verigym.owner=rollout-controller-dind \
  --label verigym.role=data \
  verigym-dind-data-v1
mkdir -p .verigym-empty-home broker verifier-output reports
```

Populate the source volume through the existing preparation workflow. Keep
`.verigym-empty-home` empty; it exists only to satisfy the controller home boundary and site mount
policy. Build or pull images over the dedicated `verigym-hwe-net` bridge when network access is
needed. Verification itself remains networkless.

## Starting a repository rollout

Run the launcher from the trusted host control plane. Repeat `--verifier-image-id` when a frozen
task set uses more than one image.

```bash
python scripts/run_repository_rollout_dind_controller.py \
  --controller-image-id "$controller_id" \
  --dind-image-id "$dind_id" \
  --verifier-image-id "$verifier_id" \
  --task-manifest "$PWD/tasks.json" \
  --source-volume verigym-rollout-source-v1 \
  --scratch-volume verigym-rollout-scratch-v1 \
  --dind-data-volume verigym-dind-data-v1 \
  --empty-home "$PWD/.verigym-empty-home" \
  --broker-root "$PWD/broker" \
  --verifier-output "$PWD/verifier-output" \
  --report "$PWD/reports/report.json"
```

The launcher creates a fresh socket volume, starts the sidecar with no outer network, imports only
the selected verifier image IDs, and starts the existing project controller without privilege. It
rejects a nonempty inner container or volume inventory both before and after the run. Cleanup
removes the sidecar and socket volume; the labeled data volume persists only the inner image cache.

## Qualifying one CVA6 candidate

Use the bounded acceptance entry point before enabling a paid model campaign. It runs the base,
official reference, and one already-frozen candidate through the same nested daemon and writes
only verifier summaries.

```bash
python scripts/run_cva6_dind_acceptance.py \
  --controller-image-id "$controller_id" \
  --dind-image-id "$dind_id" \
  --verifier-image-id "$verifier_id" \
  --source "$PWD/prepared-source" \
  --candidate "$PWD/frozen-candidate" \
  --output "$PWD/acceptance-output" \
  --dind-data-volume verigym-dind-data-v1 \
  --empty-home "$PWD/.verigym-empty-home"
```

Acceptance requires base FAIL, reference PASS, candidate PASS, no infrastructure error, and
`model_process_count=0`. The output directory must not already exist. A failed acceptance must not
be reused as permission to start a model run.

## Understanding the isolation boundary

| Component | Outer privilege | Network | Docker access | Untrusted code |
| --- | --- | --- | --- | --- |
| DinD daemon sidecar | Privileged | None | Own daemon only | No |
| VeriGym controller | Unprivileged, read-only root | None | Inner socket only | No |
| HWE verifier container | Unprivileged sandbox controls | None | None | Yes |

The sidecar never receives the host Docker socket. The controller never receives the host socket,
provider credentials, a provider configuration, or `--privileged`. Benchmark containers retain
`network=none`, capability drop, no-new-privileges, resource limits, and the built-in seccomp
profile. No path uses `seccomp=unconfined`.

The privileged sidecar is nevertheless trusted infrastructure: compromise of it can affect any
path deliberately mounted into it and shares the host kernel. Use narrow task/output mounts, a
dedicated labeled data volume, digest-locked images, and a controlled worker. Do not mount the host
home, repository root, Docker socket, credentials, hidden assets, or unrelated experiments.

## Placing nested Docker storage on a separate filesystem

An authorized campaign may use a local-driver volume backed by one exact owner-only directory on
another filesystem. For example, the v71 zero-provider successor binds its inner
`/var/lib/docker` to
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v71/data`. The host daemon still stores a small
volume descriptor in its own data root, but the nested image layers and writable snapshots live in
the inspected `/data2` backing directory. This does not change the host daemon's global
`data-root`, restart Docker, or move/delete resources belonging to other checkouts.

The campaign runner creates the bind-backed volume with local-driver `type=none`, `o=bind`, and
the exact `device` path, then inspects those options and its owner/role labels. A second bind-backed
volume exposes only the new nested Unix socket. The trusted host materializer temporarily sets
`DOCKER_HOST` to that socket only for an explicitly zero-provider execution window; it restores
the host connection before inspecting or removing the outer sidecar. This host-control variant is
not a general substitute for the unprivileged controller on model-bearing rollouts.

After an audited v71 cleanup mismatch, v73 additionally requires a dedicated cleanup container
before removing the socket volume. That container has `network=none`, a read-only root, one exact
socket-volume mount, no added privileges beyond `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`, and a fixed
list of DinD runtime paths. Cleanup succeeds only when the container removes itself and the host
confirms that the backing directory is empty, mode `0700`, and owned by the invoking UID:GID.
Command-image build output is never persisted: v73 records only bounded byte counts, SHA-256
digests, the exit code, and timeout status, so harmless nonempty tool output is accepted without
weakening the diagnostic boundary.

The bind backing must be new for its campaign identity. Never point it at `/data/docker`, an
existing Docker root, a home directory, a repository, another experiment, or a symlink. A stale
volume, nonempty inner container/volume inventory, unexpected mount, or failed cleanup is terminal.
Do not use Docker prune as part of this flow.

## Troubleshooting failures

| Failure | Meaning | Action |
| --- | --- | --- |
| Inner version or runtime policy differs | Wrong or modified DinD image | Stop and select the frozen official image ID |
| Inner inventory is nonempty | A prior run left a container or volume | Preserve evidence, clean only the labeled resources, then retry |
| Verifier image import times out | First-time `vfs` expansion exceeded the bound | Check disk capacity and I/O; increase only the explicit import timeout |
| `git` is unavailable in the controller | Controller image is incomplete | Rebuild with the frozen Git runtime dependency |
| Base/reference status is `error` | Infrastructure failure, not task rejection | Do not start a paid rollout |
| Base or reference verdict is unexpected | Task no longer reproduces fail-to-pass | Exclude or requalify the task |

## Evidence, finding, and path

- **Evidence:** the launcher validates immutable IDs, sidecar metadata, empty inventories, and
  cleanup; acceptance persists content-free verifier summaries.
- **Finding:** an older host daemon can remain the outer scheduler when the incompatibility is in
  its container runtime stack, provided the frozen inner daemon passes the complete verifier path.
- **Path:** host Docker → privileged trusted DinD sidecar → unprivileged trusted controller →
  unprivileged networkless HWE verifier container.
