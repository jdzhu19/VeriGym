#!/usr/bin/env bash
set -euo pipefail

if [[ ${VERIGYM_PREPARE_HPC_MULTITURN_ENVS:-} != 1 ]]; then
  echo "VERIGYM_PREPARE_HPC_MULTITURN_ENVS=1 is required" >&2
  exit 2
fi
if [[ $# -ne 3 ]]; then
  echo "usage: $0 VERIGYM_CHECKOUT RLLM_CHECKOUT INVENTORY_DIRECTORY" >&2
  exit 2
fi

verigym_checkout=$(realpath "$1")
rllm_checkout=$(realpath "$2")
inventory_root=$3
openhands_constraints="$verigym_checkout/configs/runtime/openhands_sdk_1.42.1_constraints.txt"

conda_executable=${CONDA_EXE:-$(command -v conda || true)}
if [[ -z "$conda_executable" && -x /hpc/home/connect.jzhu484/miniconda3/bin/conda ]]; then
  conda_executable=/hpc/home/connect.jzhu484/miniconda3/bin/conda
fi
if [[ -z "$conda_executable" || ! -x "$conda_executable" ]]; then
  echo "Conda executable is unavailable" >&2
  exit 2
fi

if [[ $(cd "$rllm_checkout" && git rev-parse HEAD) != \
  1d1109a655e291b3001d8526d7c9ecc5b9328226 ]]; then
  echo "rLLM checkout differs from the frozen commit" >&2
  exit 2
fi
if [[ ! -f "$verigym_checkout/SECURITY.md" ]]; then
  echo "VeriGym checkout is invalid" >&2
  exit 2
fi
if [[ ! -f "$openhands_constraints" ]]; then
  echo "OpenHands compatibility constraints are unavailable" >&2
  exit 2
fi

"$verigym_checkout/scripts/hpc_inventory_training_env.sh" "$inventory_root"

docker_executable=$(command -v docker || true)
if [[ -z "$docker_executable" || ! -x "$docker_executable" ]]; then
  echo "Docker is unavailable on this compute node" >&2
  exit 2
fi
docker version --format '{{.Client.Version}}' >/dev/null

export HF_HOME=/hpc/home/connect.jzhu484/agent/models/huggingface
export VLLM_CACHE_ROOT=/hpc/home/connect.jzhu484/agent/models/vllm
export RLLM_HOME=/hpc/home/connect.jzhu484/agent/datasets/rllm
export VERIGYM_EXPERIMENT_ROOT=/hpc/home/connect.jzhu484/agent/experiments
mkdir -p "$HF_HOME" "$VLLM_CACHE_ROOT" "$RLLM_HOME" "$VERIGYM_EXPERIMENT_ROOT"

if ! "$conda_executable" env list | awk '{print $1}' | grep -Fxq verigym-openhands-py312; then
  "$conda_executable" create -y -n verigym-openhands-py312 python=3.12 pip
fi
if [[ -n ${VERIGYM_OPENHANDS_LITELLM_WHEEL:-} ]]; then
  if [[ -L $VERIGYM_OPENHANDS_LITELLM_WHEEL || \
    ! -f $VERIGYM_OPENHANDS_LITELLM_WHEEL ]]; then
    echo "VERIGYM_OPENHANDS_LITELLM_WHEEL must be a regular non-symlink wheel" >&2
    exit 2
  fi
  litellm_wheel=$(realpath "$VERIGYM_OPENHANDS_LITELLM_WHEEL")
  if [[ $litellm_wheel != *litellm-1.93.0-*.whl ]]; then
    echo "OpenHands requires a locally built litellm 1.93.0 wheel" >&2
    exit 2
  fi
  litellm_wheel_sha256=$(sha256sum "$litellm_wheel" | awk '{print $1}')
  printf '%s\n' "$litellm_wheel_sha256" > "$inventory_root/openhands-litellm-wheel.sha256"
  "$conda_executable" run -n verigym-openhands-py312 python -m pip install \
    --only-binary=:all: "$litellm_wheel"
fi
"$conda_executable" run -n verigym-openhands-py312 python -m pip install \
  --constraint "$openhands_constraints" \
  -e "$verigym_checkout" \
  -e "$verigym_checkout/integrations/verigym-hwe-bench" \
  -e "$verigym_checkout/integrations/verigym-openhands"

"$conda_executable" run --no-capture-output -n verigym-openhands-py312 python - <<'PY'
import importlib.metadata

assert importlib.metadata.version("openhands-sdk") == "1.42.1"
assert importlib.metadata.version("litellm") == "1.93.0"
assert importlib.metadata.version("opentelemetry-semantic-conventions") == "0.60b1"
PY

echo "inventoried agent env and prepared OpenHands; training/model stacks remain in pinned images"
