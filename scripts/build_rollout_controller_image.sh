#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: $0 VERIGYM_CHECKOUT PYTHON_BASE_REPODIGEST DOCKER_CLI_BASE_REPODIGEST IMAGE_TAG BUILD_ROOT EXPECTED_COMMIT" >&2
  exit 2
fi

verigym_checkout=$(realpath "$1")
python_base=$2
docker_cli_base=$3
image_tag=$4
build_parent=$(realpath "$5")
expected_commit=$6

if [[ ! $python_base =~ ^python@sha256:[0-9a-f]{64}$ ]]; then
  echo "Python base must be an immutable official-python RepoDigest" >&2
  exit 2
fi
if [[ ! $docker_cli_base =~ ^docker@sha256:[0-9a-f]{64}$ ]]; then
  echo "Docker CLI base must be an immutable official-docker RepoDigest" >&2
  exit 2
fi
if [[ -n $(cd "$verigym_checkout" && git status --porcelain) ]]; then
  echo "rollout controller image requires a clean VeriGym checkout" >&2
  exit 2
fi
verigym_commit=$(cd "$verigym_checkout" && git rev-parse HEAD)
if [[ ! $expected_commit =~ ^[0-9a-f]{40}$ ]] || [[ $verigym_commit != "$expected_commit" ]]; then
  echo "VeriGym checkout differs from the explicitly selected commit" >&2
  exit 2
fi

python_base_id=$(docker image inspect "$python_base" --format '{{.Id}}')
docker_cli_base_id=$(docker image inspect "$docker_cli_base" --format '{{.Id}}')
for image_id in "$python_base_id" "$docker_cli_base_id"; do
  if [[ ! $image_id =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "controller base has no immutable local image ID" >&2
    exit 2
  fi
done

context=$(mktemp -d "$build_parent/verigym-rollout-controller.XXXXXXXX")
mkdir -p "$context/wheels"
cp "$verigym_checkout/docker/rollout-controller/Dockerfile" "$context/Dockerfile"
cp "$verigym_checkout/docker/rollout-controller/.dockerignore" "$context/.dockerignore"
cp "$verigym_checkout/scripts/run_qwen35_online_repository_broker.py" "$context/"
python3 -m build --wheel --no-isolation --outdir "$context/wheels" "$verigym_checkout"
python3 -m build --wheel --no-isolation --outdir "$context/wheels" \
  "$verigym_checkout/integrations/verigym-hwe-bench"
python3 -m build --wheel --no-isolation --outdir "$context/wheels" \
  "$verigym_checkout/integrations/verigym-training-reference"

DOCKER_BUILDKIT=0 docker build \
  --network verigym-hwe-net \
  --build-arg "PYTHON_BASE=$python_base" \
  --build-arg "DOCKER_CLI_BASE=$docker_cli_base" \
  --build-arg "VERIGYM_COMMIT=$verigym_commit" \
  --label "io.verigym.python.base_id=$python_base_id" \
  --label "io.verigym.docker-cli.base_id=$docker_cli_base_id" \
  --tag "$image_tag" \
  "$context"

if [[ $(docker image inspect "$python_base" --format '{{.Id}}') != "$python_base_id" ]] || \
  [[ $(docker image inspect "$docker_cli_base" --format '{{.Id}}') != "$docker_cli_base_id" ]]; then
  echo "controller base identity changed during the build" >&2
  exit 2
fi
image_id=$(docker image inspect "$image_tag" --format '{{.Id}}')
docker run --rm --network none --entrypoint python3 "$image_id" -c \
  'import verigym,verigym_hwe_bench,verigym_training_reference'
docker run --rm --network none --entrypoint docker "$image_id" --version | \
  grep -F 'Docker version 19.03.14'
printf '%s\n' "$image_id"
