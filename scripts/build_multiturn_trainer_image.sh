#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 VERIGYM_CHECKOUT RLLM_CHECKOUT VLLM_BASE_REPODIGEST IMAGE_TAG BUILD_ROOT" >&2
  exit 2
fi

verigym_checkout=$(realpath "$1")
rllm_checkout=$(realpath "$2")
vllm_base=$3
image_tag=$4
build_parent=$(realpath "$5")
rllm_commit=1d1109a655e291b3001d8526d7c9ecc5b9328226

if [[ ! $vllm_base =~ ^vllm/vllm-openai@sha256:[0-9a-f]{64}$ ]]; then
  echo "vLLM base must be an immutable vllm/vllm-openai RepoDigest" >&2
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
observed_vllm=$(docker run --rm --network none --entrypoint python "$base_id" \
  -c 'import importlib.metadata; print(importlib.metadata.version("vllm"))')
if [[ $observed_vllm != 0.22.1 ]]; then
  echo "vLLM base does not contain vllm==0.22.1" >&2
  exit 2
fi

context=$(mktemp -d "$build_parent/verigym-multiturn-trainer.XXXXXXXX")
mkdir -p "$context/wheels"
cp "$verigym_checkout/docker/multiturn-trainer/Dockerfile" "$context/Dockerfile"
cp "$verigym_checkout/docker/multiturn-trainer/.dockerignore" "$context/.dockerignore"
cp "$verigym_checkout/scripts/train_qwen35_multiturn_sft.py" \
  "$context/train_qwen35_multiturn_sft.py"
cp -a "$rllm_checkout" "$context/rllm"
python -m build --wheel --no-isolation --outdir "$context/wheels" "$verigym_checkout"
python -m build --wheel --no-isolation --outdir "$context/wheels" \
  "$verigym_checkout/integrations/verigym-training-reference"

docker build \
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
docker run --rm --network none --entrypoint python "$image_id" -c \
  'import importlib.metadata; assert importlib.metadata.version("verl") == "0.8.0"; assert importlib.metadata.version("vllm") == "0.22.1"'
printf '%s\n' "$image_id"
