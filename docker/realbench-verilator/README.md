# RealBench functional Verilator image

This separate, credential-free image adds `g++` and `make` to the existing Verilator 5.052/Icarus
12 image. The old lint image is unchanged. No source dataset, candidate, testbench, golden RTL,
site profile, model client or commercial tool is included.

The local qualified build used base image ID
`sha256:9bd1ce7fdbb3c7cbcf82cc53fb5092513669b9c5ca5001d4089d2931d985f58a` and produced
`sha256:be95d9fe17d331144b2aa35b4481750236c426045a395358a4f100991e9d847b`.
This is a local image identity, not a published registry digest or a reproducible-build claim.
APT resolved the build packages at build time; later builds must freeze a new resulting image ID.

For a new build, set `VERILATOR_BASE` to a verified installed image ID or digest reference and
`REALBENCH_BUILD_TAG` to a fresh tag. From the repository root, after the site's required
per-command proxy/route checks:

```bash
DOCKER_BUILDKIT=0 docker build --network verigym-hwe-net --pull=false \
  --build-arg VERILATOR_BASE="$VERILATOR_BASE" \
  --tag "$REALBENCH_BUILD_TAG" docker/realbench-verilator
docker image inspect "$REALBENCH_BUILD_TAG" --format '{{.Id}}'
```

The dedicated bridge is for the controlled dependency build only. Verification must use
`DockerRuntime` with `network=none`, the exact image ID, a matching non-root host UID/GID and
bounded resources. Only the private `.verigym_internal` staging area is writable. Default image
UID `10001` must be overridden to the worker user's UID/GID to make cleanup deterministic.

The opt-in synthetic Docker regression requires `VERIGYM_RUN_DOCKER_TESTS=1`,
`VERIGYM_REALBENCH_FUNCTIONAL_IMAGE` and `VERIGYM_REALBENCH_FUNCTIONAL_IMAGE_ID`:

```bash
pytest -c integrations/verigym-realbench/pyproject.toml \
  integrations/verigym-realbench/tests/test_docker_functional.py
```
