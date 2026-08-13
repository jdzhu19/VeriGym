#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 VERIGYM_CHECKOUT PYTHON_BASE_DIGEST_OR_ID IMAGE_TAG BUILD_ROOT" >&2
  exit 2
fi

verigym_checkout=$(realpath "$1")
python_base=$2
image_tag=$3
build_parent=$(realpath "$4")
wheel_sha256=365ee929afd73bb5d146235b65053fa948788ec2ee00a2c3e957d3f43bf2b0cd
gcc_package_version=4:12.2.0-3
libc6_dev_package_version=2.36-9+deb12u14

if [[ ! $python_base =~ ^(python@)?sha256:[0-9a-f]{64}$ ]]; then
  echo "Python base must be an immutable official-python RepoDigest or exact local image ID" >&2
  exit 2
fi
if [[ -n $(cd "$verigym_checkout" && git status --porcelain) ]]; then
  echo "vLLM service image requires a clean VeriGym checkout" >&2
  exit 2
fi
verigym_commit=$(cd "$verigym_checkout" && git rev-parse HEAD)
base_id=$(docker image inspect "$python_base" --format '{{.Id}}')
if [[ ! $base_id =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Python base has no immutable local image ID" >&2
  exit 2
fi
base_check_home=$(mktemp -d "$build_parent/verigym-vllm-base-home.XXXXXXXX")
trap 'rmdir "$base_check_home"' EXIT
observed_python=$(docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --env HOME=/work/home --volume "$base_check_home:/work/home:ro" \
  --entrypoint python3 "$base_id" \
  -c 'import platform; print(platform.python_version())')
if [[ $observed_python != 3.11.9 ]]; then
  echo "Python base must contain Python 3.11.9" >&2
  exit 2
fi

context=$(mktemp -d "$build_parent/verigym-vllm-service.XXXXXXXX")
cp "$verigym_checkout/docker/vllm-service-cu129/Dockerfile" "$context/Dockerfile"
cp "$verigym_checkout/docker/vllm-service-cu129/.dockerignore" "$context/.dockerignore"

DOCKER_BUILDKIT=0 docker build \
  --network verigym-hwe-net \
  --build-arg "PYTHON_BASE=$python_base" \
  --build-arg "PYTHON_BASE_ID=$base_id" \
  --build-arg "VLLM_WHEEL_SHA256=$wheel_sha256" \
  --build-arg "GCC_PACKAGE_VERSION=$gcc_package_version" \
  --build-arg "LIBC6_DEV_PACKAGE_VERSION=$libc6_dev_package_version" \
  --build-arg "VERIGYM_COMMIT=$verigym_commit" \
  --tag "$image_tag" \
  "$context"

if [[ $(docker image inspect "$python_base" --format '{{.Id}}') != "$base_id" ]]; then
  echo "Python base identity changed during the vLLM service build" >&2
  exit 2
fi
image_id=$(docker image inspect "$image_tag" --format '{{.Id}}')
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --env HOME=/work/home --volume "$base_check_home:/work/home:ro" \
  --entrypoint python3 "$image_id" -c \
'import importlib.metadata,shutil,torch,torchaudio,torchvision,vllm; assert importlib.metadata.version("vllm").split("+")[0] == "0.22.1"; assert torch.__version__.split("+")[0] == "2.11.0"; assert torch.version.cuda == "12.9"; assert torchvision.__version__ == "0.26.0+cu129"; assert torchaudio.__version__ == "2.11.0+cu129"; assert vllm.__version__.split("+")[0] == "0.22.1"; assert shutil.which("cc")'
printf '%s\n' "$image_id"
