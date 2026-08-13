#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 VERIGYM_CHECKOUT RLLM_CHECKOUT VLLM_SERVICE_IMAGE_ID IMAGE_TAG BUILD_ROOT" >&2
  exit 2
fi

verigym_checkout=$(realpath "$1")
rllm_checkout=$(realpath "$2")
vllm_base=$3
image_tag=$4
build_parent=$(realpath "$5")
rllm_commit=1d1109a655e291b3001d8526d7c9ecc5b9328226

if [[ ! $vllm_base =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "vLLM service base must be an immutable local image ID" >&2
  exit 2
fi
if [[ -n $(cd "$verigym_checkout" && git status --porcelain) ]]; then
  echo "VeriGym trainer image requires a clean checkout" >&2
  exit 2
fi
if [[ -n $(cd "$rllm_checkout" && git status --porcelain) ]] || \
  [[ $(cd "$rllm_checkout" && git rev-parse HEAD) != "$rllm_commit" ]]; then
  echo "rLLM checkout is dirty or differs from the frozen commit" >&2
  exit 2
fi
verigym_commit=$(cd "$verigym_checkout" && git rev-parse HEAD)
base_id=$(docker image inspect "$vllm_base" --format '{{.Id}}')
if [[ ! $base_id =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "vLLM base has no immutable local image ID" >&2
  exit 2
fi
base_check_home=$(mktemp -d "$build_parent/verigym-trainer-base-home.XXXXXXXX")
trap 'rmdir "$base_check_home"' EXIT
observed_runtime=$(docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --env HOME=/work/home --env LOGNAME=verigym --env USER=verigym \
  --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --volume "$base_check_home:/work/home:ro" --entrypoint python3 "$base_id" \
  -c 'import importlib.metadata,torch; print(importlib.metadata.version("vllm").split("+")[0], torch.version.cuda)')
if [[ $observed_runtime != "0.22.1 12.9" ]]; then
  echo "vLLM service base must contain vllm==0.22.1 with CUDA 12.9" >&2
  exit 2
fi

context=$(mktemp -d "$build_parent/verigym-multiturn-trainer.XXXXXXXX")
mkdir -p "$context/wheels"
cp "$verigym_checkout/docker/multiturn-trainer/Dockerfile" "$context/Dockerfile"
cp "$verigym_checkout/docker/multiturn-trainer/.dockerignore" "$context/.dockerignore"
cp "$verigym_checkout/scripts/train_qwen35_multiturn_sft.py" \
  "$context/train_qwen35_multiturn_sft.py"
cp "$verigym_checkout/scripts/smoke_reload_qwen35_multiturn_adapter.py" \
  "$context/smoke_reload_qwen35_multiturn_adapter.py"
cp "$verigym_checkout/scripts/smoke_qwen35_rllm_multiturn.py" \
  "$context/smoke_qwen35_rllm_multiturn.py"
cp -a "$rllm_checkout" "$context/rllm"
printf '%s\n' "$rllm_commit" >"$context/rllm/.verigym-rllm-commit"
python -m build --wheel --no-isolation --outdir "$context/wheels" "$verigym_checkout"
python -m build --wheel --no-isolation --outdir "$context/wheels" \
  "$verigym_checkout/integrations/verigym-training-reference"

DOCKER_BUILDKIT=0 docker build \
  --network verigym-hwe-net \
  --build-arg "VLLM_BASE=$vllm_base" \
  --build-arg "RLLM_COMMIT=$rllm_commit" \
  --build-arg "VERIGYM_COMMIT=$verigym_commit" \
  --label "io.verigym.vllm.base_id=$base_id" \
  --tag "$image_tag" \
  "$context"

if [[ $(docker image inspect "$vllm_base" --format '{{.Id}}') != "$base_id" ]]; then
  echo "vLLM base identity changed during the trainer build" >&2
  exit 2
fi
image_id=$(docker image inspect "$image_tag" --format '{{.Id}}')
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --env HOME=/work/home --env LOGNAME=verigym --env USER=verigym \
  --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 \
  --env PYTHONDONTWRITEBYTECODE=1 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --volume "$base_check_home:/work/home:ro" \
  --entrypoint python3 "$image_id" -c \
  'import importlib.metadata,os,torch; assert importlib.metadata.version("verl") == "0.8.0"; assert os.environ["VERIGYM_VLLM_SERVICE_VERSION"] == "0.22.1"; assert torch.version.cuda == "12.9"; assert "vllm" not in {str(item.metadata["Name"]).lower() for item in importlib.metadata.distributions()}'
printf '%s\n' "$image_id"
