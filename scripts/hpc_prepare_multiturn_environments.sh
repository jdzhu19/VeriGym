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

if [[ $(git -C "$rllm_checkout" rev-parse HEAD) != 1d1109a655e291b3001d8526d7c9ecc5b9328226 ]]; then
  echo "rLLM checkout differs from the frozen commit" >&2
  exit 2
fi
if [[ ! -f "$verigym_checkout/SECURITY.md" ]]; then
  echo "VeriGym checkout is invalid" >&2
  exit 2
fi

"$verigym_checkout/scripts/hpc_inventory_training_env.sh" "$inventory_root"

export HF_HOME=/hpc/home/connect.jzhu484/agent/models/huggingface
export VLLM_CACHE_ROOT=/hpc/home/connect.jzhu484/agent/models/vllm
export RLLM_HOME=/hpc/home/connect.jzhu484/agent/datasets/rllm
export VERIGYM_EXPERIMENT_ROOT=/hpc/home/connect.jzhu484/agent/experiments
mkdir -p "$HF_HOME" "$VLLM_CACHE_ROOT" "$RLLM_HOME" "$VERIGYM_EXPERIMENT_ROOT"

conda run -n agent python -m pip install --upgrade \
  "verl==0.8.0" \
  "vllm==0.22.1" \
  -e "$rllm_checkout" \
  -e "$verigym_checkout" \
  -e "$verigym_checkout/integrations/verigym-training-reference"

if ! conda env list | awk '{print $1}' | grep -Fxq verigym-openhands-py312; then
  conda create -y -n verigym-openhands-py312 python=3.12 pip
fi
conda run -n verigym-openhands-py312 python -m pip install \
  -e "$verigym_checkout" \
  -e "$verigym_checkout/integrations/verigym-hwe-bench" \
  -e "$verigym_checkout/integrations/verigym-openhands"

conda run -n agent python - <<'PY'
import importlib.metadata

assert importlib.metadata.version("verl") == "0.8.0"
assert importlib.metadata.version("vllm") == "0.22.1"
PY
conda run -n verigym-openhands-py312 python - <<'PY'
import importlib.metadata

assert importlib.metadata.version("openhands-sdk") == "1.42.1"
PY

echo "prepared pinned training and OpenHands environments; no allocation or daemon was changed"
